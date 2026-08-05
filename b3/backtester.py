"""Historical strategy backtester.

Entry:  regra injetável de ``b3.entry_rules`` (padrão: ``momentum``, a faixa
        de RSI que ``b3/decision.py`` aprova como compra)
Exit:   modelo injetável de ``b3.exit_rules`` (padrão: ``trailing_producao``,
        o trailing stop sem alvo que ``b3/monitor.py`` executa)

Os dois padrões existem para uma coisa só: o JSON que este módulo grava
alimenta o gate de compra, então ele precisa medir **a estratégia que a
produção roda**. Já foram `reversao_moderado` e stop fixo com alvo de +15% —
nenhum dos dois existia no pipeline, e o gate aprovava ativos com base em
evidência de uma estratégia que ninguém executava.

A regra de entrada era fixa no laço de simulação, o que impedia rodar teses
diferentes na mesma régua. Agora entrada e saída entram por parâmetro — mesmos
tickers, mesmo período, para qualquer combinação.

RSI is computed with Wilder's exponential smoothing — no TA-Lib or pandas_ta.
A EMA-20 usa ``pandas_ta`` porque é a mesma função que ``b3/scanner.py`` chama:
a tese de momentum precisa ser medida com o indicador que a produção emite.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pandas_ta as ta
import yfinance as yf

from b3.decision import (
    APROVACAO_EXPECTANCIA_MIN,
    APROVACAO_SHARPE_MIN,
    APROVACAO_TRADES_MIN,
    ticker_aprovado,
)
from b3.entry_rules import Candle, momentum
from b3.exit_rules import trailing_producao

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

_DATA_DIR    = Path("data")
_RESULTS_PATH = _DATA_DIR / "backtest_results.json"

# Período da régua de produção. O JSON salvo alimenta o gate de compra, então
# só um run com este período (e a regra de produção) pode sobrescrevê-lo.
#
# Eram 730 dias (2 anos), e nessa janela o n por ticker ficava entre 7 e 16
# trades — o gate decidia alocação de capital por ativo sobre uma amostra em
# que uma operação muda a taxa de acerto em mais de 6 pontos. Com 10 anos vai
# para 45-149. Não custa nada: o tempo é dominado pelo round-trip da rede, não
# pelo volume (0,68s contra 0,75s por ticker na medição).
_DEFAULT_PERIOD_DAYS = 3650

_DEFAULT_TICKERS = [
    "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA",
    "WEGE3.SA", "RENT3.SA", "B3SA3.SA", "SUZB3.SA",
    "RDOR3.SA", "GGBR4.SA", "VBBR3.SA", "PRIO3.SA",
    "CPLE6.SA", "CSAN3.SA", "EQTL3.SA", "SBSP3.SA",
]

_TAKE_PROFIT = 0.15   # +15% from entry price
_STOP_LOSS   = 0.07   # -7%  from entry price


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI using exponential smoothing — no external TA library.

    Uses ``ewm(alpha=1/period, adjust=False)`` which is mathematically
    equivalent to Wilder's smoothed moving average. Rows inside the warm-up
    window are left as NaN and dropped by the caller's ``dropna``.

    Args:
        close:  Daily closing price series.
        period: Look-back window; defaults to 14.

    Returns:
        RSI series with the same index as ``close``.
    """
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    # Dividing by NaN (when avg_loss == 0) produces NaN → those rows are dropped
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))


def _print_summary(results: list[dict]) -> None:
    """Render a fixed-width ASCII table to stdout."""
    fmt    = "{:<12} {:>7} {:>8} {:>10} {:>9} {:>8}"
    header = fmt.format("Ticker", "Trades", "Win%", "AvgRet%", "MaxDD%", "Sharpe")
    rule   = "=" * len(header)
    sep    = "-" * len(header)

    print(f"\n{rule}")
    print("RESULTADOS DO BACKTEST")
    print(rule)
    print(header)
    print(sep)
    for r in results:
        print(fmt.format(
            r["ticker"],
            r["total_trades"],
            f"{r['win_rate']:.1f}",
            f"{r['avg_return_pct']:.2f}",
            f"{r['max_drawdown_pct']:.2f}",
            f"{r['sharpe_ratio']:.2f}",
        ))
    print(rule)

    # Critério importado de b3.decision: esta tabela mostrava trades>=5,
    # win_rate>=55% e sharpe>=0.5 numa cópia própria, então quem lesse a saída
    # veria uma lista diferente da que o gate de compra realmente aprova.
    worthy = [r for r in results if ticker_aprovado(r)]
    print("\nATIVOS QUE MERECEM MONITORAMENTO ATIVO")
    print(f"  (criterio do gate: trades>={APROVACAO_TRADES_MIN} | "
          f"avg_ret>{APROVACAO_EXPECTANCIA_MIN}% | "
          f"sharpe>={APROVACAO_SHARPE_MIN})")
    print(sep)
    if worthy:
        # Ordenado por sharpe, nao por win_rate: sem alvo fixo a taxa de acerto
        # nao ordena qualidade — foi o que quebrou o criterio antigo.
        for r in sorted(worthy, key=lambda x: x["sharpe_ratio"], reverse=True):
            print(fmt.format(
                r["ticker"],
                r["total_trades"],
                f"{r['win_rate']:.1f}",
                f"{r['avg_return_pct']:.2f}",
                f"{r['max_drawdown_pct']:.2f}",
                f"{r['sharpe_ratio']:.2f}",
            ))
    else:
        print("  Nenhum ativo passou nos tres criterios simultaneamente.")
    print(f"{rule}\n")


def _save_results(results: list[dict]) -> None:
    """Write results list to data/backtest_results.json."""
    _DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    with open(_RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Resultados salvos em {_RESULTS_PATH}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_backtest(
    ticker: str,
    period_days: int = _DEFAULT_PERIOD_DAYS,
    entry_rule=momentum,
    exit_rule=trailing_producao,
    detail: bool = False,
) -> dict | None:
    """Simulate an entry rule on historical data for a single ticker.

    Downloads ``period_days + 60`` calendar days so indicators have a 60-day
    warm-up window, then restricts the simulation to the requested period.

    Args:
        ticker:      yfinance symbol, e.g. ``'PETR4.SA'``.
        period_days: Calendar days of history to simulate; default 3650 (10 anos).
        entry_rule:  Callable de ``b3.entry_rules`` que recebe um ``Candle`` e
                     devolve True quando a vela abre posição. O padrão espelha
                     a faixa de RSI que ``b3/decision.py`` aprova como compra.
        exit_rule:   Modelo de saída de ``b3.exit_rules``. O padrão espelha o
                     trailing stop de ``b3/monitor.py``; ``no_fechamento`` e
                     ``intradiaria`` existem para comparação nos estudos.
        detail:      Acrescenta ``trades`` (lista, com data de entrada) e
                     ``equity`` (Series diária) ao retorno. Necessário para
                     fatiar por regime e correlacionar estratégias; fora do
                     padrão porque nenhum dos dois é serializável em JSON.

    Returns:
        Metrics dict, or ``None`` when data is unavailable or insufficient.

    Return schema::

        {
            "ticker":           str,
            "total_trades":     int,
            "win_rate":         float,   # 0-100
            "avg_return_pct":   float,
            "max_drawdown_pct": float,   # negative value
            "sharpe_ratio":     float,
            "period_days":      int,
        }
    """
    end   = datetime.today()
    start = end - timedelta(days=period_days + 60)

    try:
        raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    except Exception as exc:
        print(f"[WARN] {ticker}: erro ao baixar dados — {exc}")
        return None

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if raw is None or raw.empty:
        print(f"[WARN] {ticker}: sem dados — pulando")
        return None

    df = raw.copy()

    # --- Indicators ---
    df["RSI"] = _compute_rsi(df["Close"])
    # Mesma chamada de scanner.py:192 — a tese de momentum compara preço contra
    # esta EMA, então recalculá-la de outro jeito mediria outra estratégia.
    df["EMA_20"] = ta.ema(df["Close"], length=20)

    vol_avg_20 = df["Volume"].rolling(20).mean()
    # Replace zero average with NaN to avoid ±inf in the ratio
    df["volume_ratio"] = df["Volume"] / vol_avg_20.replace(0.0, float("nan"))

    # EMA_20 fica fora do dropna de propósito: regra que não usa EMA não deve
    # perder velas por causa dela. Quem usa recebe None e não entra.
    df = df.dropna(subset=["RSI", "volume_ratio"]).copy()

    # Vela do pregão em andamento vem do yfinance com Open/High/Low ZERADOS e
    # só o Close preenchido. Os modelos de saída leem OHLC: `abertura=0` passa
    # em `abertura <= nivel_stop` sempre, e a posição aberta "sai" a preço zero
    # — um trade de -100% inventado, que desloca a média de um ticker inteiro.
    # O simulador antigo só lia Close e nunca esbarrou nisso.
    ohlc = [c for c in ("Open", "High", "Low") if c in df.columns]
    if ohlc:
        validas = (df[ohlc] > 0).all(axis=1)
        if not validas.all():
            descartadas = (~validas).sum()
            print(f"[INFO] {ticker}: {descartadas} vela(s) sem OHLC completo "
                  f"descartada(s) — provavelmente pregão em andamento")
            df = df[validas].copy()

    # Restrict simulation to the requested calendar window
    df = df[df.index >= pd.Timestamp(end - timedelta(days=period_days))].copy()

    if len(df) < 10:
        print(f"[WARN] {ticker}: dados insuficientes para simulação — pulando")
        return None

    # --- Simulation ---
    # Séries sem OHLC completo caem no fechamento nos quatro campos: o modelo
    # `no_fechamento` ignora abertura/máxima/mínima, então o resultado é
    # idêntico ao histórico. Modelo intradiário sobre dado assim viraria
    # `no_fechamento` disfarçado — por isso o aviso.
    tem_ohlc = {"Open", "High", "Low"}.issubset(df.columns)
    if not tem_ohlc and exit_rule is not trailing_producao:
        print(f"[WARN] {ticker}: série sem OHLC — saída intradiária indisponível")

    # Equity curve is normalised to 1.0; one position at a time.
    trades:        list[dict] = []
    in_position:   bool  = False
    entry_price:   float = 0.0
    peak_price:    float = 0.0   # topo desde a entrada, para o trailing stop
    entry_date           = None
    current_value: float = 1.0

    equity = pd.Series(1.0, index=df.index, dtype=float)

    for i in range(len(df)):
        price     = float(df["Close"].iloc[i])
        rsi       = float(df["RSI"].iloc[i])
        vol_ratio = float(df["volume_ratio"].iloc[i])
        date      = df.index[i]

        if in_position:
            maxima = float(df["High"].iloc[i]) if tem_ohlc else price
            saida = exit_rule(
                entry_price,
                peak_price,
                float(df["Open"].iloc[i]) if tem_ohlc else price,
                maxima,
                float(df["Low"].iloc[i]) if tem_ohlc else price,
                price,
                _TAKE_PROFIT,
                _STOP_LOSS,
            )
            # Atualiza o topo só depois de checar: com barra diária não se sabe
            # se a máxima veio antes ou depois da queda, e assumir a sequência
            # inventaria disparos. Ver docstring de trailing_producao.
            peak_price = max(peak_price, maxima)
            if saida is not None:
                ret = (saida.preco - entry_price) / entry_price
                current_value *= (1.0 + ret)
                trades.append({
                    "entry_date": str(entry_date.date()),
                    "exit_date":  str(date.date()),
                    "return_pct": round(ret * 100.0, 2),
                    "win":        ret > 0,
                    "motivo":     saida.motivo,
                })
                in_position = False
        else:
            ema20 = float(df["EMA_20"].iloc[i])
            candle = Candle(
                price=price,
                rsi=rsi,
                volume_ratio=vol_ratio,
                ema20=None if pd.isna(ema20) else ema20,
            )
            if entry_rule(candle):
                in_position = True
                entry_price = price
                peak_price  = price
                entry_date  = date

        equity.iloc[i] = current_value

    # Mark open position to market at last available price
    if in_position:
        last_price = float(df["Close"].iloc[-1])
        ret = (last_price - entry_price) / entry_price
        current_value *= (1.0 + ret)
        trades.append({
            "entry_date": str(entry_date.date()),
            "exit_date":  str(df.index[-1].date()),
            "return_pct": round(ret * 100.0, 2),
            "win":        ret > 0,
        })
        equity.iloc[-1] = current_value

    # --- Metrics ---
    total_trades = len(trades)

    if total_trades == 0:
        vazio = {
            "ticker":           ticker,
            "total_trades":     0,
            "win_rate":         0.0,
            "avg_return_pct":   0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio":     0.0,
            "period_days":      period_days,
        }
        if detail:
            # Curva plana ainda serve: a correlação entre duas estratégias
            # precisa das duas séries alinhadas no mesmo calendário.
            vazio["trades"] = []
            vazio["equity"] = equity
        return vazio

    ret_list   = [t["return_pct"] for t in trades]
    win_rate   = sum(t["win"] for t in trades) / total_trades * 100.0
    avg_return = sum(ret_list) / total_trades

    rolling_max  = equity.cummax()
    drawdown     = (equity - rolling_max) / rolling_max * 100.0
    max_drawdown = float(drawdown.min())

    daily_ret = equity.pct_change().dropna()
    sharpe    = 0.0
    if len(daily_ret) > 1 and float(daily_ret.std()) > 0.0:
        sharpe = float((daily_ret.mean() / daily_ret.std()) * (252 ** 0.5))

    resultado = {
        "ticker":           ticker,
        "total_trades":     total_trades,
        "win_rate":         round(win_rate, 2),
        "avg_return_pct":   round(avg_return, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio":     round(sharpe, 2),
        "period_days":      period_days,
    }
    if detail:
        # Fora do dict padrão de propósito: `trades` e `equity` não são
        # serializáveis em JSON e não podem vazar para backtest_results.json.
        resultado["trades"] = trades
        resultado["equity"] = equity
    return resultado


def run_full_backtest(
    tickers: list[str] | None = None,
    period_days: int = _DEFAULT_PERIOD_DAYS,
    entry_rule=momentum,
    exit_rule=trailing_producao,
    save: bool = True,
) -> list[dict]:
    """Run ``run_backtest()`` for each ticker, print a summary table, and save JSON.

    Args:
        tickers:     yfinance symbols to test. Defaults to ``_DEFAULT_TICKERS``
                     when ``None`` is passed.
        period_days: Calendar days of history to simulate.
        entry_rule:  Regra de entrada de ``b3.entry_rules``.
        save:        Grava ``data/backtest_results.json``. Só é permitido com a
                     régua de produção — ver ValueError abaixo.

    Raises:
        ValueError: quando ``save`` é pedido com regra ou período que não são os
            de produção. Esse JSON alimenta o gate de compra de
            ``b3/decision.py``: gravar ali o resultado de um run de pesquisa
            faria a produção aprovar compra com base numa estratégia que ela não
            roda — corrupção silenciosa, com dinheiro real. Runs de pesquisa
            passam ``save=False``.

    Returns:
        List of result dicts, one per ticker that returned valid data.
    """
    if save and (
        entry_rule is not momentum
        or exit_rule is not trailing_producao
        or period_days != _DEFAULT_PERIOD_DAYS
    ):
        raise ValueError(
            f"save=True exige a régua de produção (momentum, "
            f"trailing_producao, {_DEFAULT_PERIOD_DAYS} dias); recebido "
            f"({getattr(entry_rule, '__name__', entry_rule)}, "
            f"{getattr(exit_rule, '__name__', exit_rule)}, {period_days} dias). "
            f"Use save=False para pesquisa — {_RESULTS_PATH} alimenta o gate de compra."
        )

    if tickers is None:
        tickers = _DEFAULT_TICKERS

    print(f"Iniciando backtest para {len(tickers)} ticker(s)...\n")
    results: list[dict] = []

    for ticker in tickers:
        # ASCII de proposito: o console do Windows usa cp1252 por padrao e
        # `->` em unicode derrubava `python -m b3.backtester` com
        # UnicodeEncodeError — justamente o comando que gera o JSON do gate.
        print(f"  -> {ticker}...", end=" ", flush=True)
        result = run_backtest(ticker, period_days=period_days,
                              entry_rule=entry_rule, exit_rule=exit_rule)
        if result is not None:
            results.append(result)
            print(
                f"{result['total_trades']} trades | "
                f"win rate {result['win_rate']:.1f}% | "
                f"avg ret {result['avg_return_pct']:.2f}%"
            )

    if results:
        _print_summary(results)
        if save:
            _save_results(results)
        else:
            print("\n[PESQUISA] save=False — data/backtest_results.json intacto.")
    else:
        print("\nNenhum resultado disponível.")

    return results


if __name__ == "__main__":
    run_full_backtest()

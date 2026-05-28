"""
crypto_backtester.py
--------------------
Backtesta a estratégia cripto usando dados históricos da Binance.

Para cada par (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT):
  1. Baixa N dias de velas diárias da Binance (gratuito, sem chave)
  2. Simula os sinais que o sistema teria gerado dia a dia
  3. Executa compras e vendas fictícias com trailing stop 7%
  4. Calcula win rate, retorno total e drawdown máximo

Uso:
  python crypto_backtester.py
  python crypto_backtester.py --symbol BTCUSDT --days 90
"""

import argparse
import logging
import sys
import time

import requests
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com/api/v3"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
TRAILING_STOP_PCT = 0.07
INITIAL_CAPITAL = 5000.0
POSITION_SIZE_FORTE = 0.20
POSITION_SIZE_MODERADO = 0.10


# ── Data fetching ────────────────────────────────────────────────────────────

def fetch_daily_candles(symbol: str, days: int = 150) -> pd.DataFrame:
    """Fetches daily OHLCV candles from Binance public API."""
    try:
        resp = requests.get(
            f"{BINANCE_BASE}/klines",
            params={"symbol": symbol, "interval": "1d", "limit": days},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(
            data,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ],
        )
        df["date"] = pd.to_datetime(df["open_time"], unit="ms")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        return df[["date", "open", "high", "low", "close", "volume"]].copy()
    except Exception as e:
        logger.error(f"[FETCH] {symbol}: {e}")
        return pd.DataFrame()


# ── Indicator calculation ─────────────────────────────────────────────────────

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds RSI(14), MA20, MA50, MA200, and momentum proxy to the dataframe."""
    closes = df["close"].values
    rsi_vals = [None] * len(closes)

    if len(closes) >= 15:
        for i in range(14, len(closes)):
            diffs = [closes[i - 14 + j + 1] - closes[i - 14 + j] for j in range(14)]
            gains = [max(d, 0) for d in diffs]
            losses = [max(-d, 0) for d in diffs]
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss == 0:
                rsi_vals[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_vals[i] = round(100 - 100 / (1 + rs), 2)

    df["rsi"] = rsi_vals
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma50"] = df["close"].rolling(50).mean()
    df["ma200"] = df["close"].rolling(200).mean()
    df["change_1d"] = df["close"].pct_change(1) * 100
    df["change_7d"] = df["close"].pct_change(7) * 100

    def _mom_score(row):
        c1 = row["change_1d"]
        c7 = row["change_7d"]
        if pd.isna(c1) or pd.isna(c7):
            return 50.0
        score_1d = 8 if c1 > 1 else (4 if c1 > 0.3 else (-8 if c1 < -1 else -4 if c1 < -0.3 else 0))
        score_7d = 12 if c7 > 5 else (6 if c7 > 2 else (-12 if c7 < -5 else -6 if c7 < -2 else 0))
        return 50.0 + score_1d + score_7d

    df["momentum"] = df.apply(_mom_score, axis=1)
    return df


# ── Signal generation ─────────────────────────────────────────────────────────

def generate_signal(row: pd.Series) -> str:
    """
    Mirrors crypto_decision.py logic:
    FORTE / MODERADO / AGUARDAR / BLOCKED_MA200
    """
    rsi = row.get("rsi")
    momentum = row.get("momentum", 50.0)
    change = row.get("change_1d", 0.0)
    close = row["close"]
    ma200 = row.get("ma200")
    ma20 = row.get("ma20")
    ma50 = row.get("ma50")

    if rsi is None or pd.isna(rsi):
        return "AGUARDAR"

    in_downtrend = False
    if ma200 and not pd.isna(ma200):
        pct_from_ma200 = (close - ma200) / ma200 * 100
        if pct_from_ma200 > 30:
            return "BLOCKED_MA200"
        if ma20 and ma50 and not pd.isna(ma20) and not pd.isna(ma50):
            in_downtrend = ma20 < ma50

    rsi_forte = 32
    rsi_moderado = 35 if in_downtrend else 40
    mom_forte = 52
    mom_moderado = 48

    if rsi <= rsi_forte and momentum >= mom_forte and change <= -3.0:
        return "FORTE"

    if rsi <= rsi_moderado and momentum >= mom_moderado:
        return "MODERADO"

    return "AGUARDAR"


# ── Backtest engine ───────────────────────────────────────────────────────────

def backtest_symbol(symbol: str, df: pd.DataFrame) -> dict:
    """Simulates paper trades with trailing stop for one symbol."""
    capital = INITIAL_CAPITAL
    position = None
    trades = []

    for _, row in df.iterrows():
        if row["rsi"] is None or pd.isna(row["rsi"]):
            continue

        price = row["close"]
        date = row["date"]

        if position:
            new_high = max(position["high"], price)
            new_stop = new_high * (1 - TRAILING_STOP_PCT)
            position["high"] = new_high
            position["stop"] = new_stop

            if price <= new_stop:
                proceeds = position["qty"] * price
                pnl = proceeds - position["value"]
                pnl_pct = (price - position["entry"]) / position["entry"] * 100
                capital += proceeds
                trades.append({
                    "symbol": symbol,
                    "entry_date": position["date"],
                    "exit_date": date,
                    "entry_price": position["entry"],
                    "exit_price": price,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "exit_reason": "trailing_stop",
                    "signal": position["signal"],
                })
                position = None
                continue

        signal = generate_signal(row)

        if position is None and signal in ("FORTE", "MODERADO"):
            alloc_pct = POSITION_SIZE_FORTE if signal == "FORTE" else POSITION_SIZE_MODERADO
            value = capital * alloc_pct
            qty = value / price
            position = {
                "entry": price,
                "qty": qty,
                "value": value,
                "stop": price * (1 - TRAILING_STOP_PCT),
                "high": price,
                "date": date,
                "signal": signal,
            }
            capital -= value

    if position:
        price = df.iloc[-1]["close"]
        date = df.iloc[-1]["date"]
        proceeds = position["qty"] * price
        pnl = proceeds - position["value"]
        pnl_pct = (price - position["entry"]) / position["entry"] * 100
        capital += proceeds
        trades.append({
            "symbol": symbol,
            "entry_date": position["date"],
            "exit_date": date,
            "entry_price": position["entry"],
            "exit_price": price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "exit_reason": "end_of_period",
            "signal": position["signal"],
        })

    wins = [t for t in trades if t["pnl"] > 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    for t in trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        "symbol": symbol,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(trades) - len(wins),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "total_return": round((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        "max_drawdown": round(max_dd, 2),
        "final_capital": round(capital, 2),
        "trade_list": trades,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run_backtest(symbols: list = None, days: int = 150) -> list:
    symbols = symbols or SYMBOLS
    results = []

    print(f"\n{'='*60}")
    print(f"BACKTESTING CRIPTO — ultimos {days} dias")
    print(f"Capital inicial: R$ {INITIAL_CAPITAL:,.2f} por par")
    print(f"Trailing stop: {TRAILING_STOP_PCT*100:.0f}%")
    print(f"{'='*60}\n")

    for symbol in symbols:
        logger.info(f"Baixando dados: {symbol}...")
        # Fetch extra warmup rows so MA200 is valid within the requested window
        df = fetch_daily_candles(symbol, days=max(days + 210, 220))
        if df.empty:
            logger.warning(f"{symbol}: sem dados — pulando")
            continue

        df = calculate_indicators(df)
        df = df.tail(days).reset_index(drop=True)

        result = backtest_symbol(symbol, df)
        results.append(result)

        print(f"{symbol}")
        print(f"  Operacoes: {result['trades']} | Wins: {result['wins']} | Losses: {result['losses']}")
        print(f"  Win rate:  {result['win_rate']}%")
        print(f"  P&L total: R$ {result['total_pnl']:+,.2f} ({result['total_return']:+.2f}%)")
        print(f"  Max drawdown: {result['max_drawdown']}%")
        print(f"  Capital final: R$ {result['final_capital']:,.2f}")

        if result["trade_list"]:
            print("  Operacoes detalhadas:")
            for t in result["trade_list"]:
                icon = "OK" if t["pnl"] > 0 else "XX"
                ed = t["entry_date"].strftime("%d/%m") if hasattr(t["entry_date"], "strftime") else str(t["entry_date"])[:5]
                xd = t["exit_date"].strftime("%d/%m") if hasattr(t["exit_date"], "strftime") else str(t["exit_date"])[:5]
                print(
                    f"    [{icon}] {ed} -> {xd} | "
                    f"entrada ${t['entry_price']:,.0f} saida ${t['exit_price']:,.0f} | "
                    f"P&L {t['pnl_pct']:+.1f}% ({t['signal']}) | {t['exit_reason']}"
                )
        else:
            print("  0 sinais no periodo (condicoes de mercado nao atingiram os limiares RSI)")
        print()

        time.sleep(0.5)

    if results:
        total_trades = sum(r["trades"] for r in results)
        total_wins = sum(r["wins"] for r in results)
        total_pnl = sum(r["total_pnl"] for r in results)
        combined_wr = total_wins / total_trades * 100 if total_trades else 0

        print(f"{'='*60}")
        print(f"RESULTADO COMBINADO (todos os pares)")
        print(f"  Total de operacoes: {total_trades}")
        print(f"  Win rate combinado: {combined_wr:.1f}%")
        print(f"  P&L total combinado: R$ {total_pnl:+,.2f}")
        print(f"{'='*60}\n")

    return results


def run_comparison() -> None:
    """
    Runs backtest across multiple period and position sizing
    configurations and prints a comparison table.
    """
    import crypto_backtester as cb

    configs = [
        # (label, days, position_forte_pct, position_moderado_pct)
        ("Conservador 90d  (20%/10%)",  90,  0.20, 0.10),
        ("Conservador 150d (20%/10%)", 150,  0.20, 0.10),
        ("Moderado 90d     (30%/15%)",  90,  0.30, 0.15),
        ("Moderado 150d    (30%/15%)", 150,  0.30, 0.15),
        ("Agressivo 90d    (40%/20%)",  90,  0.40, 0.20),
        ("Agressivo 150d   (40%/20%)", 150,  0.40, 0.20),
    ]

    print(f"\n{'='*80}")
    print("COMPARATIVO DE CONFIGURACOES — todos os pares combinados")
    print(f"{'='*80}")
    print(f"{'Configuracao':<30} {'Ops':>4} {'Win%':>6} {'P&L':>10} {'Retorno':>8} {'MaxDD':>7}")
    print(f"{'-'*80}")

    best_pnl = None
    best_label = ""

    for label, days, pos_forte, pos_mod in configs:
        original_forte = cb.POSITION_SIZE_FORTE
        original_mod   = cb.POSITION_SIZE_MODERADO

        cb.POSITION_SIZE_FORTE    = pos_forte
        cb.POSITION_SIZE_MODERADO = pos_mod

        results = []
        for symbol in cb.SYMBOLS:
            df = cb.fetch_daily_candles(symbol, days=max(days + 210, 220))
            if df.empty:
                continue
            df = cb.calculate_indicators(df)
            df = df.tail(days).reset_index(drop=True)
            r  = cb.backtest_symbol(symbol, df)
            results.append(r)
            time.sleep(0.5)

        cb.POSITION_SIZE_FORTE    = original_forte
        cb.POSITION_SIZE_MODERADO = original_mod

        if not results:
            continue

        total_ops  = sum(r["trades"]      for r in results)
        total_wins = sum(r["wins"]        for r in results)
        total_pnl  = sum(r["total_pnl"]  for r in results)
        avg_dd     = sum(r["max_drawdown"] for r in results) / len(results)
        win_rate   = total_wins / total_ops * 100 if total_ops else 0
        total_capital = cb.INITIAL_CAPITAL * len(results)
        total_return  = total_pnl / total_capital * 100

        print(
            f"{label:<30} {total_ops:>4} {win_rate:>5.1f}% "
            f"R${total_pnl:>+8,.2f} {total_return:>+7.2f}% {avg_dd:>6.1f}%"
        )

        if best_pnl is None or total_pnl > best_pnl:
            best_pnl   = total_pnl
            best_label = label

    print(f"{'-'*80}")
    print(f"Melhor configuracao por P&L: {best_label} -> R$ {best_pnl:+,.2f}")
    print(f"{'='*80}\n")
    print("LEGENDA:")
    print("  Conservador: FORTE=20% do capital, MODERADO=10%")
    print("  Moderado:    FORTE=30% do capital, MODERADO=15%")
    print("  Agressivo:   FORTE=40% do capital, MODERADO=20%")
    print("  MaxDD = drawdown maximo medio por par")
    print()
    print("ATENCAO: retorno maior sempre vem com drawdown maior.")
    print("O MaxDD e o que voce PERDERIA no pior momento antes de recuperar.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto backtest usando dados Binance")
    parser.add_argument("--symbol", type=str, default=None,
                        help="Par a testar (ex: BTCUSDT). Padrao: todos os 4 pares")
    parser.add_argument("--days", type=int, default=150,
                        help="Numero de dias do historico (padrao: 150)")
    parser.add_argument("--compare", action="store_true",
                        help="Rodar comparativo entre todas as configuracoes")
    args = parser.parse_args()

    if args.compare:
        run_comparison()
    elif args.symbol:
        run_backtest(symbols=[args.symbol], days=args.days)
    else:
        run_backtest(days=args.days)

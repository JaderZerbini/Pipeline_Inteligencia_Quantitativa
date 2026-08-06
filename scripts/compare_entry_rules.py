"""Compara as teses de entrada do pipeline B3 na mesma régua.

O scanner emite momentum (RSI 55-68 acima da EMA-20) e a decisão só aprova
reversão (RSI < 38). As faixas não se cruzam, então hoje nenhum sinal do
scanner vira compra. Este script mede as duas — mesmos tickers, mesmo período,
mesma saída (+15% TP / -7% SL) — para que alinhar as pontas seja decisão com
dado, não palpite.

Uso:
  python scripts/compare_entry_rules.py
  python scripts/compare_entry_rules.py --anos 5 --custo 0.3

NÃO grava nada. `data/backtest_results.json` alimenta o gate de compra de
produção e só pode ser escrito por `python -m b3.backtester`.

O que este estudo NÃO responde: o pipeline real ainda exige score da IA
(>= 55 moderado) e gate macro em cima do sinal técnico. Nada disso é simulado
aqui, então todo retorno abaixo é otimista em relação à produção.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pandas_ta as ta

from b3 import backtester as bt
from b3.backtester import _DEFAULT_TICKERS
from b3.entry_rules import momentum, reversao_moderado
from b3.exit_rules import (
    com_niveis,
    intradiaria,
    no_fechamento,
    trailing_com_alvo,
    trailing_producao,
)

# Comparacao de teses de entrada. Os estudos de EMA, ADX e volume existiram,
# responderam sua pergunta e foram removidos — os numeros estao em
# ESTRATEGIA.md. O que sobra e o confronto que sustenta a escolha atual.
_ESTUDOS = {
    "base": {
        "reversao": reversao_moderado,
        "momentum": momentum,
    },
}

_REGRAS: dict = _ESTUDOS["base"]

# Saída usada pelos estudos de entrada. Padrão é a régua histórica; --saida
# troca para a que a produção executa de verdade.
_SAIDA_ATIVA = no_fechamento

# Estudo de saída: a entrada fica fixa (momentum, a candidata) e o que varia é
# o modelo de execução da saída. Misturar os dois eixos na mesma tabela
# impediria saber qual dos dois causou a diferença.
#
# As três últimas linhas separam os dois eixos que a tabela 3.3 de
# ESTRATEGIA.md deixou colados. `trailing + alvo` mantém o stop móvel e
# acrescenta o alvo; as duas varreduras mantêm tudo e só mexem na distância do
# stop, para saber se -7% é um número escolhido ou herdado.
_SAIDAS = {
    "fechamento (atual)":    no_fechamento,
    "stop intradiario":      intradiaria,
    "trailing (producao)":   trailing_producao,
    "trailing + alvo 15%":   trailing_com_alvo,
    "trailing -5% do topo":  com_niveis(trailing_producao, sl_pct=0.05),
    "trailing -10% do topo": com_niveis(trailing_producao, sl_pct=0.10),
}

# Larguras da varredura (--estudo varredura). Passo de 1 p.p. na região onde o
# valor de produção mora, e pontos esparsos depois só para ver a forma da curva
# — não para escolher entre eles.
_LARGURAS = (0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12, 0.15)

# Abaixo disto a métrica é ruído com aparência de tabela. Não é regra de
# mercado, é estatística: win rate sobre 8 trades muda 12 p.p. com um trade.
_N_MINIMO = 30

# Round-trip estimado em papel líquido da B3 (emolumentos + liquidação +
# spread/slippage). Momentum gira mais que reversão, então comparar retorno
# bruto favorece automaticamente quem opera mais.
_CUSTO_PADRAO_PCT = 0.2


def _memoizar_download():
    """Evita rebaixar o mesmo ticker uma vez por regra (3x o tráfego)."""
    original = bt.yf.download
    cache: dict = {}

    def wrapper(ticker, *args, **kwargs):
        chave = (ticker, str(kwargs.get("start")), str(kwargs.get("end")))
        if chave not in cache:
            cache[chave] = original(ticker, *args, **kwargs)
        return cache[chave].copy()

    bt.yf.download = wrapper


def carregar_regimes(period_days: int) -> pd.DataFrame:
    """Série diária do IBOV com os dois regimes classificados.

    Tendência (primária): fechamento acima/abaixo da própria MA200. Mesmo
    conceito que o gate `pct_from_ma200` de b3/decision.py já usa.

    Volatilidade (exploratória): vol realizada de 21 dias acima/abaixo da
    mediana do período. Sai da mesma série, sem baixar mais nada.
    """
    fim = pd.Timestamp.today().normalize()
    inicio = fim - pd.Timedelta(days=period_days + 400)  # folga p/ MA200

    ibov = bt.yf.download("^BVSP", start=inicio, end=fim, progress=False, auto_adjust=True)
    if isinstance(ibov.columns, pd.MultiIndex):
        ibov.columns = ibov.columns.get_level_values(0)

    df = pd.DataFrame(index=ibov.index)
    df["close"] = ibov["Close"]
    df["ma200"] = ta.sma(ibov["Close"], length=200)
    df["tendencia"] = df["close"] > df["ma200"]

    ret = ibov["Close"].pct_change()
    df["vol21"] = ret.rolling(21).std() * (252 ** 0.5)
    df["vol_alta"] = df["vol21"] > df["vol21"].median()

    return df.dropna()


def _regime_na_data(regimes: pd.DataFrame, data: str) -> tuple[str, str] | None:
    """Regime vigente no pregão da entrada (ou o último anterior a ele)."""
    ts = pd.Timestamp(data)
    anteriores = regimes.index[regimes.index <= ts]
    if len(anteriores) == 0:
        return None
    linha = regimes.loc[anteriores[-1]]
    return (
        "alta" if linha["tendencia"] else "baixa",
        "vol_alta" if linha["vol_alta"] else "vol_baixa",
    )


def rodar(tickers: list[str], period_days: int, custo_pct: float) -> dict:
    """Roda cada regra sobre cada ticker e devolve trades + curvas de capital."""
    saida: dict = {}

    for nome, regra in _REGRAS.items():
        trades: list[dict] = []
        curvas: dict[str, pd.Series] = {}

        print(f"\n[{nome}]", end=" ", flush=True)
        for ticker in tickers:
            print(".", end="", flush=True)
            r = bt.run_backtest(
                ticker, period_days=period_days, entry_rule=regra,
                exit_rule=_SAIDA_ATIVA, detail=True
            )
            if r is None:
                continue
            for t in r["trades"]:
                t["ticker"] = ticker
                t["return_liq_pct"] = t["return_pct"] - custo_pct
                trades.append(t)
            curvas[ticker] = r["equity"]

        saida[nome] = {"trades": trades, "curvas": curvas}

    return saida


# Stop nominal é -7%. Abaixo disto o preço passou por cima do stop entre um
# fechamento e outro — gap. É a métrica de cauda que não depende do tamanho da
# amostra, ao contrário do "pior trade", que é um ponto só.
_LIMIAR_GAP_PCT = -10.0


def estudo_saida(tickers: list[str], period_days: int, custo_pct: float) -> None:
    """Mede quanto do prejuízo vem do modelo de saída, não do mercado.

    Entrada fixa (momentum) para isolar o eixo. O modelo antigo só confere o
    preço no fechamento; o novo simula ordem stop com gap na abertura.
    """
    print("\n" + "=" * 78)
    print("ESTUDO DE SAÍDA - entrada fixa em momentum")
    print("=" * 78)

    resultados = {}
    for rotulo, saida in _SAIDAS.items():
        trades: list[dict] = []
        print(f"\n[{rotulo}]", end=" ", flush=True)
        for ticker in tickers:
            print(".", end="", flush=True)
            r = bt.run_backtest(ticker, period_days=period_days,
                                entry_rule=momentum, exit_rule=saida, detail=True)
            if r is None:
                continue
            for t in r["trades"]:
                t["return_liq_pct"] = t["return_pct"] - custo_pct
                trades.append(t)
        resultados[rotulo] = trades

    print("\n\n-- Retorno " + "-" * 66)
    for rotulo, trades in resultados.items():
        print(_linha(rotulo, _metricas(trades)))

    print("\n-- Cauda esquerda " + "-" * 59)
    for rotulo, trades in resultados.items():
        m = _metricas(trades)
        if m["n"]:
            print(
                f"  {rotulo:<22} freq<{_LIMIAR_GAP_PCT}%={m['gap_pct']:>5.1f}%  "
                f"perda média nesses={m['perda_media_gap']:>7.2f}%  "
                f"p5={m['p5']:>7.2f}%  pior={m['pior']:>7.2f}%"
            )

    print("\n-- Por que cada posição foi encerrada " + "-" * 39)
    for rotulo, trades in resultados.items():
        motivos: dict[str, list[float]] = {}
        for t in trades:
            motivos.setdefault(t.get("motivo", "?"), []).append(t["return_liq_pct"])
        total = len(trades) or 1
        detalhe = "  ".join(
            f"{m}={len(v) / total * 100:.1f}% (avg {sum(v) / len(v):+.1f}%)"
            for m, v in sorted(motivos.items())
        )
        print(f"  {rotulo:<22} {detalhe}")

    print("\n" + "=" * 78)
    print("LEITURA")
    print("=" * 78)
    print("  `gap_baixa` é o que nenhum stop evita: o preço saltou o nível com")
    print("  o mercado fechado. `stop` é o stop funcionando. A diferença entre")
    print("  os dois modelos no retorno é o preço de ter proteção de verdade.")


def estudo_varredura(tickers: list[str], period_days: int, custo_pct: float) -> None:
    """Varre a largura do trailing para saber onde o -7% herdado se situa.

    O -7% entrou no primeiro commit do monitor e nunca foi medido. Esta
    varredura mede — mas o pico dela **não é** a resposta: escolher o máximo de
    uma varredura é overfitting por construção, e aqui é overfitting com
    dinheiro real. Por isso cada largura também é medida nas duas metades do
    período em separado. Largura que só vence numa metade venceu por sorte de
    amostra, e a produção não roda em amostras passadas.
    """
    print("\n" + "=" * 78)
    print("VARREDURA DA LARGURA DO TRAILING - entrada fixa em momentum")
    print("=" * 78)

    corte = (pd.Timestamp.today() - pd.Timedelta(days=period_days // 2)).date().isoformat()

    resultados: dict[str, list[dict]] = {}
    curvas: dict[str, list] = {}
    for largura in _LARGURAS:
        rotulo = f"-{largura * 100:g}% do topo"
        saida = com_niveis(trailing_producao, sl_pct=largura)
        trades: list[dict] = []
        curvas[rotulo] = []
        print(f"\n[{rotulo}]", end=" ", flush=True)
        for ticker in tickers:
            print(".", end="", flush=True)
            r = bt.run_backtest(ticker, period_days=period_days,
                                entry_rule=momentum, exit_rule=saida, detail=True)
            if r is None:
                continue
            for t in r["trades"]:
                t["return_liq_pct"] = t["return_pct"] - custo_pct
                trades.append(t)
            curvas[rotulo].append(r["equity"])
        resultados[rotulo] = trades

    print("\n\n-- Período inteiro " + "-" * 58)
    for rotulo, trades in resultados.items():
        print(_linha(rotulo, _metricas(trades)))

    print("\n-- Cauda esquerda " + "-" * 59)
    for rotulo, trades in resultados.items():
        m = _metricas(trades)
        if m["n"]:
            print(
                f"  {rotulo:<22} freq<{_LIMIAR_GAP_PCT}%={m['gap_pct']:>5.1f}%  "
                f"perda média nesses={m['perda_media_gap']:>7.2f}%  "
                f"p5={m['p5']:>7.2f}%  pior={m['pior']:>7.2f}%"
            )

    print("\n-- Carteira equal-weight: o que o capital fez no TEMPO " + "-" * 23)
    print("   Retorno/trade premia quem opera menos e segura mais. Aqui o")
    print("   denominador e o mesmo periodo de 10 anos para todas as larguras.")
    for rotulo, series in curvas.items():
        if not series:
            continue
        # Capital ocioso vale 1.0 antes do primeiro pregão do ticker.
        carteira = pd.concat(series, axis=1).ffill().fillna(1.0).mean(axis=1)
        n = _metricas(resultados[rotulo])["n"]
        # A curva do backtester é BRUTA. O custo entra aqui: cada trade paga
        # custo_pct, e a carteira tem `len(series)` posições equal-weight.
        drag = (1.0 - custo_pct / 100.0) ** (n / len(series))
        diario = carteira.pct_change().dropna()
        pico = carteira.cummax()
        print(
            f"  {rotulo:<22} "
            f"bruto={(carteira.iloc[-1] - 1) * 100:>7.0f}%  "
            f"liquido={(carteira.iloc[-1] * drag - 1) * 100:>7.0f}%  "
            f"DD max={((carteira / pico - 1).min()) * 100:>6.1f}%  "
            f"sharpe={(diario.mean() / diario.std() * (252 ** 0.5)):>5.2f}"
        )

    print(f"\n-- Estabilidade: metade 1 (ate {corte}) vs metade 2 " + "-" * 24)
    print("   Ranking que troca entre as metades = o vencedor do periodo")
    print("   inteiro foi sorte de amostra, nao regra de mercado.")
    for rotulo, trades in resultados.items():
        m1 = _metricas([t for t in trades if t["entry_date"] < corte])
        m2 = _metricas([t for t in trades if t["entry_date"] >= corte])
        print(
            f"  {rotulo:<22} "
            f"1a: n={m1['n']:>4} avg={m1['avg']:>6.2f}% +-{m1['ep']:.2f}   "
            f"2a: n={m2['n']:>4} avg={m2['avg']:>6.2f}% +-{m2['ep']:.2f}"
        )

    print("\n" + "=" * 78)
    print("LEITURA")
    print("=" * 78)
    print("  Um erro padrao (+-) cobre ~68% da incerteza da media. Duas larguras")
    print("  cujas faixas se sobrepoem nao foram distinguidas por este teste,")
    print("  por maior que pareca a diferenca entre os numeros centrais.")


def _metricas(trades: list[dict], chave: str = "return_liq_pct") -> dict:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "avg": 0.0, "ep": 0.0, "soma": 0.0,
                "mediana": 0.0, "pior": 0.0,
                "p5": 0.0, "gap_pct": 0.0, "perda_media_gap": 0.0}
    rets = [t[chave] for t in trades]
    wins = sum(1 for r in rets if r > 0)
    furados = [r for r in rets if r < _LIMIAR_GAP_PCT]
    return {
        "n":        len(trades),
        "win_rate": wins / len(trades) * 100.0,
        "avg":      sum(rets) / len(rets),
        # Erro padrão da média: sem ele, duas médias diferentes podem ser a
        # mesma amostra. Foi o que derrubou o estudo de volume (ver ESTRATEGIA).
        "ep":       float(pd.Series(rets).std(ddof=1)) / len(rets) ** 0.5
                    if len(rets) > 1 else 0.0,
        # Soma dos retornos: média/trade não é comparável entre modelos que
        # operam n muito diferente na MESMA janela de 10 anos. Aproxima o que a
        # carteira acumulou; ignora composição, mas ordena certo.
        "soma":     sum(rets),
        "mediana":  float(pd.Series(rets).median()),
        "pior":     min(rets),
        "p5":       float(pd.Series(rets).quantile(0.05)),
        # Frequência, não mínimo: comparável entre amostras de tamanhos diferentes.
        "gap_pct":  len(furados) / len(rets) * 100.0,
        "perda_media_gap": sum(furados) / len(furados) if furados else 0.0,
    }


def _linha(rotulo: str, m: dict) -> str:
    alerta = "  [!] N baixo" if 0 < m["n"] < _N_MINIMO else ""
    if m["n"] == 0:
        return f"  {rotulo:<22} nenhum trade"
    return (
        f"  {rotulo:<22} n={m['n']:>4}  win={m['win_rate']:>5.1f}%  "
        f"avg={m['avg']:>6.2f}% +-{m['ep']:.2f}  med={m['mediana']:>6.2f}%  "
        f"acum={m['soma']:>7.0f}%  pior={m['pior']:>7.2f}%{alerta}"
    )


def relatorio(dados: dict, regimes: pd.DataFrame, anos: float, custo_pct: float,
              com_regime: bool = True) -> None:
    print("\n" + "=" * 78)
    print(f"COMPARATIVO DE REGRAS DE ENTRADA — {anos:.0f} anos, custo {custo_pct}% por trade")
    print("=" * 78)

    print("\n-- Agregado (líquido de custo) " + "-" * 46)
    for nome in _REGRAS:
        print(_linha(nome, _metricas(dados[nome]["trades"])))

    print("\n-- Bruto vs líquido (quem gira mais paga mais) " + "-" * 30)
    for nome in _REGRAS:
        bruto = _metricas(dados[nome]["trades"], chave="return_pct")
        liq = _metricas(dados[nome]["trades"])
        if bruto["n"]:
            print(
                f"  {nome:<22} bruto={bruto['avg']:>6.2f}%  "
                f"líquido={liq['avg']:>6.2f}%  "
                f"custo total={bruto['avg'] - liq['avg']:>5.2f} p.p."
            )

    print("\n-- Cauda esquerda: quando o stop de -7% não segurou " + "-" * 25)
    print(f"     (freq = % de trades abaixo de {_LIMIAR_GAP_PCT}%, "
          f"comparável entre amostras)")
    for nome in _REGRAS:
        m = _metricas(dados[nome]["trades"])
        if m["n"]:
            print(
                f"  {nome:<22} freq={m['gap_pct']:>5.1f}%  "
                f"perda média nesses={m['perda_media_gap']:>7.2f}%  "
                f"p5={m['p5']:>7.2f}%  pior={m['pior']:>7.2f}%"
            )

    if com_regime:
        print("\n-- Fatia por tendência do IBOV (PRIMÁRIA) " + "-" * 35)
        for nome in _REGRAS:
            for regime in ("alta", "baixa"):
                sel = [
                    t for t in dados[nome]["trades"]
                    if (r := _regime_na_data(regimes, t["entry_date"])) and r[0] == regime
                ]
                print(_linha(f"{nome} / IBOV {regime}", _metricas(sel)))

        print("\n-- Fatia por volatilidade (EXPLORATÓRIA — não decide) " + "-" * 23)
        for nome in _REGRAS:
            for regime in ("vol_alta", "vol_baixa"):
                sel = [
                    t for t in dados[nome]["trades"]
                    if (r := _regime_na_data(regimes, t["entry_date"])) and r[1] == regime
                ]
                print(_linha(f"{nome} / {regime}", _metricas(sel)))
    else:
        # Fatiar 6 regras por 2 regimes por 2 eixos são 24 células. Com esse
        # tanto de comparação alguma sai "boa" por acaso. A pergunta de regime
        # já foi respondida no estudo base; aqui ela só poluiria.
        print("\n(fatias por regime omitidas neste estudo — ver --estudo base)")

    print("\n-- Correlação entre as séries diárias " + "-" * 39)
    series = {}
    for nome in ("reversao", "momentum"):
        curvas = dados[nome]["curvas"]
        if not curvas:
            continue
        media = pd.DataFrame(curvas).mean(axis=1)
        series[nome] = media.pct_change()

    if len(series) == 2:
        alinhado = pd.DataFrame(series).dropna()
        corr = alinhado["reversao"].corr(alinhado["momentum"])
        print(f"  correlação diária reversao × momentum: {corr:.3f}  "
              f"({len(alinhado)} pregões)")
        print("  Baixa correlação justifica manter as duas mesmo que uma perca")
        print("  no confronto direto — é diversificação, não acurácia.")
    else:
        print("  séries insuficientes para correlacionar")

    print("\n" + "=" * 78)
    print("VIESES CONHECIDOS DESTE ESTUDO")
    print("=" * 78)
    print("  1. Universo de tickers foi escolhido por desempenho passado")
    print("     (scanner.py marca 'Backtest-approved') — viés de sobrevivência,")
    print("     e ele piora quanto mais longo o período.")
    print("  2. IBOV é concentrado em VALE3/PETR4/bancos, que estão no próprio")
    print("     universo testado: o papel ajuda a definir o regime dele mesmo.")
    print("  3. Retornos em reais nominais, sem deflacionar. Cancela na")
    print("     comparação entre regras; não vale como retorno real.")
    print("  4. Drawdown e Sharpe do backtester são BRUTOS (sem custo).")
    print("  5. Sem gate de IA nem macro — a produção é mais restritiva que isto.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--anos", type=float, default=10.0, help="período em anos (padrão: 10)")
    p.add_argument("--custo", type=float, default=_CUSTO_PADRAO_PCT,
                   help="custo round-trip por trade em %% (padrão: 0.2)")
    p.add_argument("--tickers", nargs="*", default=None, help="override do universo")
    p.add_argument("--estudo", choices=sorted(_ESTUDOS) + ["saida", "varredura"], default="base",
                   help="conjunto de regras a comparar (padrão: base)")
    p.add_argument("--saida", choices=sorted(_SAIDAS), default="fechamento (atual)",
                   help="modelo de saída nos estudos de entrada")
    args = p.parse_args()

    global _SAIDA_ATIVA
    _SAIDA_ATIVA = _SAIDAS[args.saida]

    period_days = int(args.anos * 365)
    tickers = args.tickers or _DEFAULT_TICKERS

    _memoizar_download()

    if args.estudo == "saida":
        estudo_saida(tickers, period_days, args.custo)
        return

    if args.estudo == "varredura":
        estudo_varredura(tickers, period_days, args.custo)
        return

    global _REGRAS
    _REGRAS = _ESTUDOS[args.estudo]

    print(f"Baixando IBOV para classificar regime...")
    regimes = carregar_regimes(period_days)
    print(f"  {len(regimes)} pregões classificados "
          f"({regimes.index[0].date()} -> {regimes.index[-1].date()})")
    print(f"  IBOV em alta: {regimes['tendencia'].mean() * 100:.0f}% do tempo")

    print(f"\nRodando {len(_REGRAS)} regras × {len(tickers)} tickers "
          f"× {args.anos:.0f} anos", end="")
    dados = rodar(tickers, period_days, args.custo)
    relatorio(dados, regimes, args.anos, args.custo,
              com_regime=(args.estudo == "base"))


if __name__ == "__main__":
    main()

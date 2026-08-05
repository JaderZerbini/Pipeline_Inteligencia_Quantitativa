"""Classifica os tickers do universo B3 sob a estratégia de produção.

Gera a divisão prioritário / observação / fora que vive em `b3/scanner.py`.
Mede com a régua que a produção realmente executa: entrada de momentum
(RSI 55-68) e saída por trailing stop sem alvo.

Uso:
  python scripts/rank_tickers.py
  python scripts/rank_tickers.py --anos 5

NÃO grava nada — nem o JSON do gate de compra, nem o scanner. A saída é para
leitura humana; atualizar as listas é decisão consciente, não efeito colateral
de rodar um script.

Por que existe: a lista anterior foi montada sob a tese de reversão e ficou
desalinhada quando a entrada mudou para momentum — o B3SA3 era prioritário
sendo 12º de 15, e o WEGE3 estava banido sendo 5º. Sem um jeito de refazer a
conta, a próxima troca de estratégia deixaria o mesmo rastro.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from b3.backtester import _DEFAULT_TICKERS, run_backtest
from b3.entry_rules import momentum
from b3.exit_rules import trailing_producao

# Mesmo threshold que `_load_approved_tickers` usa em b3/decision.py. Reusar em
# vez de inventar um número novo é o que mantém as duas classificações
# falando a mesma língua.
_SHARPE_PRIORITARIO = 0.5

# Abaixo disto a métrica por ticker é ruído: com poucos trades o sharpe oscila
# demais para sustentar uma decisão de universo.
_N_MINIMO = 30


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--anos", type=float, default=10.0, help="período (padrão: 10)")
    p.add_argument("--tickers", nargs="*", default=None, help="override do universo")
    args = p.parse_args()

    tickers = args.tickers or _DEFAULT_TICKERS
    period_days = int(args.anos * 365)

    print(f"Medindo {len(tickers)} tickers — momentum + trailing stop, "
          f"{args.anos:.0f} anos\n")

    resultados = []
    for t in tickers:
        r = run_backtest(t, period_days=period_days,
                         entry_rule=momentum, exit_rule=trailing_producao)
        if r is not None:
            resultados.append(r)

    resultados.sort(key=lambda r: r["sharpe_ratio"], reverse=True)

    print(f"\n{'ticker':<11}{'n':>5}{'win%':>8}{'avg%':>8}{'sharpe':>8}"
          f"{'maxDD%':>9}  classe")
    print("-" * 62)

    prioritarios, observacao, fora = [], [], []
    for r in resultados:
        if r["total_trades"] < _N_MINIMO:
            classe, destino = "amostra pequena", None
        elif r["sharpe_ratio"] >= _SHARPE_PRIORITARIO:
            classe, destino = "PRIORITARIO", prioritarios
        elif r["sharpe_ratio"] > 0:
            classe, destino = "observacao", observacao
        else:
            classe, destino = "FORA", fora
        if destino is not None:
            destino.append(r["ticker"])

        print(f"{r['ticker']:<11}{r['total_trades']:>5}{r['win_rate']:>8.1f}"
              f"{r['avg_return_pct']:>8.2f}{r['sharpe_ratio']:>8.2f}"
              f"{r['max_drawdown_pct']:>9.1f}  {classe}")

    print("\n" + "=" * 62)
    print("Para colar em b3/scanner.py:")
    print("=" * 62)
    for nome, lista in [("TICKERS_PRIORITARIOS", prioritarios),
                        ("TICKERS_OBSERVACAO", observacao)]:
        print(f"{nome} = [")
        for i in range(0, len(lista), 3):
            print("    " + " ".join(f'"{t}",' for t in lista[i:i + 3]))
        print("]")
    if fora:
        print(f"# Fora por sharpe negativo: {', '.join(fora)}")

    print("\nLembretes:")
    print("  - Drawdown NÃO entra no critério. Confira a coluna antes de")
    print("    promover: sharpe alto com maxDD de -50% é outra conversa.")
    print("  - O universo aqui é o que já conhecíamos. Ticker que nunca foi")
    print("    testado não aparece por mágica — ampliar a lista é outra decisão.")
    print("  - Todos sobreviveram os 10 anos. Empresa que quebrou no meio do")
    print("    período não está aqui, e isso infla todo mundo.")


if __name__ == "__main__":
    main()

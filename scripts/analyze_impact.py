"""Analisa se o eixo `impact` separa vencedores de perdedores.

Responde, em ordem, duas perguntas — e a primeira é de graça:

  1. TRIAGEM: o `impact` varia de forma sensata? Se os modelos devolvem sempre
     algo perto de zero, ou se `impact` só repete o `score`, o eixo não carrega
     informação e não vale gastar em coleta ampla. Bastam ~20 amostras.

  2. CALIBRAÇÃO: entre os sinais com `impact` alto, o retorno posterior foi
     melhor que entre os de `impact` baixo? É daí que sai o threshold do 3b.
     Precisa de centenas de amostras E de tempo passado.

O rótulo (retorno posterior) é calculado retroativamente com yfinance e gravado
em signal_outcomes: preço histórico é recuperável a qualquer momento, ao
contrário de notícia, que os feeds RSS não devolvem para datas passadas.

Uso:
  python scripts/analyze_impact.py                 # triagem + calibração
  python scripts/analyze_impact.py --triagem       # só a triagem (não usa rede)
  python scripts/analyze_impact.py --horizontes 3 5 10
"""

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from core.db import save_signal_outcome, get_connection  # noqa: E402

HORIZONTES_PADRAO = [3, 5, 10]
_MIN_TRIAGEM = 10
_MIN_CALIBRACAO = 30


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def carregar_amostras() -> list[dict]:
    """Lê sinais do B3 e do cripto que já têm `impact` registrado.

    O impact do B3 tem coluna própria em audits desde
    scripts/add_calibration_columns.sql; para linhas anteriores a isso ele
    existe apenas dentro de raw_response, então o fallback lê o JSON.
    """
    amostras: list[dict] = []
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT s.id, s.ticker, s.price, s.created_at, s.rsi,
                   a.gemini_score, a.impact, a.verdict, a.raw_response
              FROM signals s
              JOIN audits a ON a.signal_id = s.id
             ORDER BY s.id
            """
        )
        for row in cur.fetchall():
            sid, ticker, price, created, rsi, score, impact, verdict, raw = row
            if impact is None and raw:
                try:
                    impact = json.loads(raw).get("impact")
                except (ValueError, TypeError):
                    impact = None
            if impact is None:
                continue
            amostras.append({
                "pipeline": "b3", "signal_id": sid, "symbol": ticker,
                "price": price, "created_at": created, "rsi": rsi,
                "score": score, "impact": impact, "verdict": verdict,
            })

        try:
            cur = conn.execute(
                """
                SELECT id, symbol, price, created_at, rsi_1h,
                       ai_score, ai_impact, ai_veredicto
                  FROM crypto_signals
                 WHERE ai_impact IS NOT NULL
                 ORDER BY id
                """
            )
            for sid, sym, price, created, rsi, score, impact, verdict in cur.fetchall():
                amostras.append({
                    "pipeline": "cripto", "signal_id": sid, "symbol": sym,
                    "price": price, "created_at": created, "rsi": rsi,
                    "score": score, "impact": impact, "verdict": verdict,
                })
        except Exception as e:
            print(f"[WARN] crypto_signals indisponível: {e}")

    return amostras


# ---------------------------------------------------------------------------
# 1. Triagem — não usa rede, não precisa de tempo passado
# ---------------------------------------------------------------------------

def _correlacao(xs: list[float], ys: list[float]) -> float | None:
    """Pearson via stdlib. None quando não há variância (divisão por zero)."""
    if len(xs) < 3:
        return None
    try:
        return round(statistics.correlation(xs, ys), 3)
    except statistics.StatisticsError:
        return None


def triagem(amostras: list[dict]) -> None:
    print("\n" + "=" * 62)
    print("TRIAGEM — o eixo `impact` carrega informação?")
    print("=" * 62)

    n = len(amostras)
    print(f"amostras com impact: {n}")
    if n == 0:
        print("\nNada a analisar. Deixe o pipeline rodar (AI_PREGATE=off acelera).")
        return

    impacts = [float(a["impact"]) for a in amostras]
    print(f"  faixa    : {min(impacts):+.0f} a {max(impacts):+.0f}")
    print(f"  mediana  : {statistics.median(impacts):+.1f}")
    if n >= 2:
        print(f"  desvio   : {statistics.stdev(impacts):.1f}")

    # Sintoma 1: régua travada perto de zero
    quase_zero = sum(1 for i in impacts if abs(i) <= 10)
    pct = quase_zero / n * 100
    print(f"\n  |impact| <= 10 : {quase_zero}/{n} ({pct:.0f}%)")
    if pct > 70:
        print("  >>> ALERTA: régua travada perto de zero — não discrimina.")
    else:
        print("  >>> ok: o eixo se move.")

    # Sintoma 2: impact é só uma cópia do score
    scores = [float(a["score"]) for a in amostras if a["score"] is not None]
    if len(scores) == n:
        r = _correlacao(impacts, scores)
        print(f"\n  correlação impact x score: {r if r is not None else 'n/d'}")
        if r is not None and abs(r) > 0.9:
            print("  >>> ALERTA: redundante com o score — não traz eixo novo.")
        elif r is not None:
            print("  >>> ok: mede algo diferente do score.")

    if n < _MIN_TRIAGEM:
        print(f"\n  (amostra pequena: {n} < {_MIN_TRIAGEM}. Trate como indício.)")


# ---------------------------------------------------------------------------
# 2. Rótulo — retorno posterior via yfinance
# ---------------------------------------------------------------------------

def _como_utc(bruto) -> datetime | None:
    """Converte `created_at` em datetime *aware* em UTC. None se não der.

    Os dois pipelines gravam formatos diferentes: o B3 usa isoformat sem
    fuso e o cripto grava com '+00:00'. Misturar naive e aware numa comparação
    levanta TypeError, então tudo é normalizado para UTC aqui — um sinal sem
    fuso é lido como UTC, que é como ambos os pipelines geram o carimbo.
    """
    if not bruto:
        return None
    try:
        dt = datetime.fromisoformat(str(bruto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _preco_apos(symbol: str, quando: datetime, dias: int) -> float | None:
    """Fecha do primeiro pregão >= quando + dias. None se ainda não existe."""
    import yfinance as yf

    alvo = quando + timedelta(days=dias)
    if alvo > datetime.now(timezone.utc):
        return None  # o futuro ainda não aconteceu

    ticker = symbol if symbol.endswith("USDT") else f"{symbol}.SA"
    if symbol.endswith("USDT"):
        ticker = symbol.replace("USDT", "-USD")

    try:
        df = yf.download(
            ticker,
            start=alvo.strftime("%Y-%m-%d"),
            end=(alvo + timedelta(days=7)).strftime("%Y-%m-%d"),
            progress=False, auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        return float(close.iloc[0])
    except Exception as e:
        print(f"  [WARN] {symbol} +{dias}d: {e}")
        return None


def calcular_rotulos(amostras: list[dict], horizontes: list[int]) -> int:
    print("\n" + "=" * 62)
    print("RÓTULOS — retorno posterior (yfinance, retroativo)")
    print("=" * 62)

    gravados = 0
    ignorados = 0
    for a in amostras:
        quando = _como_utc(a["created_at"])
        if quando is None:
            ignorados += 1
            continue
        for h in horizontes:
            depois = _preco_apos(a["symbol"], quando, h)
            if depois is None:
                continue
            save_signal_outcome(
                pipeline=a["pipeline"], signal_id=a["signal_id"],
                symbol=a["symbol"], horizon_days=h,
                price_at_signal=a["price"], price_after=depois,
            )
            gravados += 1
    print(f"outcomes gravados/atualizados: {gravados}")
    if ignorados:
        print(f"amostras com created_at ilegível: {ignorados}")
    if gravados == 0:
        print("Nenhum horizonte maduro ainda — os sinais são recentes demais.")
    return gravados


# ---------------------------------------------------------------------------
# 3. Calibração
# ---------------------------------------------------------------------------

def calibracao(horizontes: list[int]) -> None:
    print("\n" + "=" * 62)
    print("CALIBRAÇÃO — impact alto rendeu mais que impact baixo?")
    print("=" * 62)

    with get_connection() as conn:
        for h in horizontes:
            cur = conn.execute(
                """
                SELECT a.impact, o.return_pct
                  FROM signal_outcomes o
                  JOIN audits a ON a.signal_id = o.signal_id
                 WHERE o.pipeline = 'b3' AND o.horizon_days = ?
                   AND a.impact IS NOT NULL AND o.return_pct IS NOT NULL
                """,
                (h,),
            )
            pares = cur.fetchall()
            if not pares:
                print(f"\n{h}d: sem dados.")
                continue

            impacts = [float(p[0]) for p in pares]
            retornos = [float(p[1]) for p in pares]
            r = _correlacao(impacts, retornos)
            print(f"\n{h}d — {len(pares)} amostras | correlação impact x retorno: "
                  f"{r if r is not None else 'n/d'}")

            # Onde cortar: compara retorno médio acima e abaixo de cada limite
            for corte in (0, 20, 40, 60):
                acima = [rt for im, rt in zip(impacts, retornos) if im >= corte]
                abaixo = [rt for im, rt in zip(impacts, retornos) if im < corte]
                if len(acima) >= 3 and len(abaixo) >= 3:
                    print(f"   impact >= {corte:>3}: {statistics.mean(acima):+6.2f}%"
                          f" (n={len(acima):>3})   "
                          f"< {corte}: {statistics.mean(abaixo):+6.2f}% (n={len(abaixo):>3})")

            if len(pares) < _MIN_CALIBRACAO:
                print(f"   (amostra pequena: {len(pares)} < {_MIN_CALIBRACAO} "
                      f"— não calibre threshold com isto)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--triagem", action="store_true",
                    help="só a triagem; não busca preço nem calibra")
    ap.add_argument("--horizontes", type=int, nargs="+", default=HORIZONTES_PADRAO)
    args = ap.parse_args()

    amostras = carregar_amostras()
    triagem(amostras)

    if args.triagem:
        return
    if not amostras:
        return

    calcular_rotulos(amostras, args.horizontes)
    calibracao(args.horizontes)


if __name__ == "__main__":
    main()

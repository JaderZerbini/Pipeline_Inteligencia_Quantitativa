import logging
import os
import sys
import threading
import time
from datetime import datetime
from core.db import init_db, update_signal_recommendation
from b3.scanner import scanner_pro
from core.sentiment_analyzer import analyze_news
from b3.news_fetcher import buscar_noticias_ticker
from b3.decision import evaluate_signal
from core.macro_monitor import fetch_macro_snapshot, evaluate_macro
from b3.monitor import check_stops
from core.alerts import TelegramAlert, send_alert
from paper.engine import execute_paper_buy as _paper_buy, check_paper_stops as _check_paper_stops

os.makedirs("data", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/b3_pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Tickers managed in scanner_pro.py (TICKERS + Brapi top-20 merge).
# Pass an override list here only when testing specific assets.

# Used immediately after scanner so the decision path stays under 3 seconds.
# The real Gemini result is persisted in the background via daemon threads.
_FALLBACK_AUDIT: dict = {
    "score": 50,
    "verdict": "RUIDO",
    "reason": "Fallback: auditoria em andamento",
    "flags": ["FALLBACK"],
}


def _run_audit(
    headline: str,
    ticker: str,
    signal_id: int,
    result: dict,
    event: threading.Event,
) -> None:
    """Thread target: call Gemini, store result, set event to unblock caller."""
    try:
        result["audit"] = analyze_news(headline, ticker, signal_id)
    except Exception:
        result["audit"] = dict(_FALLBACK_AUDIT)
    finally:
        event.set()


def orquestrar_investimento() -> list[dict]:
    """Run the full quantitative pipeline and return the list of decisions.

    Flow per ticker:
      1. Technical scanner produces BUY signals (RSI + EMA filter).
      2. Signal already persisted by scanner; signal_id is passed forward.
      3. Gemini audit is launched in a background daemon thread.
      4. Decision engine runs immediately using the fallback audit so the
         scanner + decision path finishes in under 3 seconds.
      5. Telegram alert is sent only for FORTE or MODERADO recommendations.

    Returns:
        List of decision dicts for each scanned ticker, consumed by Streamlit.
    """
    init_db()
    logger.info("=== INICIANDO PIPELINE DE INTELIGÊNCIA QUANTITATIVA ===")

    # PASSO 1: Scanner Técnico — retorna DataFrame com signal_id já persistido
    df_foguetes = scanner_pro()

    if df_foguetes is None or df_foguetes.empty:
        logger.info("Nenhuma oportunidade técnica encontrada no momento.")
        return []

    messenger = TelegramAlert()
    decisoes_finais: list[dict] = []

    logger.info(f"Analisando {len(df_foguetes)} ativo(s) selecionado(s) pelo Scanner...")

    # Fetch macro context once — evaluate_macro uses this snapshot per ticker
    macro_snapshot = fetch_macro_snapshot()
    brent  = macro_snapshot.get("brent")
    minerio = macro_snapshot.get("iron_ore")
    usdbrl = macro_snapshot.get("usdbrl")
    selic  = macro_snapshot.get("selic")
    logger.info(
        f"Macro: Brent {brent['change_pct']:+.1f}% | "
        f"Minério {minerio['change_pct']:+.1f}% | "
        f"USD/BRL {usdbrl['change_pct']:+.1f}% | "
        f"SELIC {selic['rate']:.2f}%"
        if brent and minerio and usdbrl and selic
        else "Macro: dados parcialmente indisponíveis"
    )

    for _, row in df_foguetes.iterrows():
        ticker: str = row["Ticker"]
        signal_id: int = int(row["signal_id"])

        # PASSO 2a: Avaliar contexto macro para este ticker
        macro_result = evaluate_macro(ticker, macro_snapshot)

        # PASSO 2b: Buscar manchetes (síncrono, ~200-400 ms)
        logger.info(f"[{ticker}] Buscando notícias...")
        headline = buscar_noticias_ticker(ticker)

        # PASSO 3: Auditoria Gemini em thread daemon — bloqueia até 12s ou até responder
        audit_result: dict = {}
        event = threading.Event()
        thread = threading.Thread(
            target=_run_audit,
            args=(headline, ticker, signal_id, audit_result, event),
            daemon=True,
        )
        t_start = time.time()
        thread.start()
        fired = event.wait(timeout=12)

        if fired:
            audit = audit_result.get("audit", dict(_FALLBACK_AUDIT))
            elapsed = time.time() - t_start
            consensus_flag = next(
                (f for f in audit.get("flags", []) if f.startswith("CONSENSUS:")), None
            )
            if consensus_flag:
                n_models = consensus_flag.split(":")[1]
                models_str = "·".join(audit.get("models_used", []))
                logger.info(
                    f"[{ticker}] Consensus {n_models} | "
                    f"score={audit['score']} | {audit['verdict']} ({models_str})"
                )
            else:
                logger.info(
                    f"[{ticker}] respondeu em {elapsed:.1f}s | "
                    f"score={audit['score']} | {audit['verdict']}"
                )
        else:
            audit = dict(_FALLBACK_AUDIT)
            logger.warning(f"[{ticker}] timeout — usando fallback")

        # PASSO 4: Decisão com o audit real (ou fallback se timeout)
        signal_dict = {
            "ticker":         ticker,
            "rsi":            float(row["RSI"]),
            "volume_ratio":   float(row["volume_ratio"]),
            "price":          float(row["Preço"]),
            "hist_trend":     row.get("hist_trend", "unknown") or "unknown",
            "hist_position":  row.get("hist_position", "unknown") or "unknown",
            "pct_from_ma200": float(row.get("pct_from_ma200") or 0),
            "hist_context":   str(row.get("hist_context") or "Histórico indisponível"),
        }
        decision = evaluate_signal(signal_dict, audit, macro=macro_result)
        update_signal_recommendation(signal_id, decision["recommendation"])

        logger.info(
            f"[{ticker}] RSI={row['RSI']:.2f} | vol={row['volume_ratio']:.2f}x | "
            f"{decision['recommendation']} (confiança={decision['confidence']:.0%})"
        )

        decisoes_finais.append({
            "Ativo":         ticker,
            "Preço":         row["Preço"],
            "RSI":           row["RSI"],
            "Recomendação":  decision["recommendation"],
            "Confiança":     decision["confidence"],
            "Razões":        decision["reasons"],
            "Análise IA":    audit.get("reason", _FALLBACK_AUDIT["reason"]),
            "signal_id":     signal_id,
            "hist_context":  signal_dict.get("hist_context", ""),
            "hist_position": signal_dict.get("hist_position", "unknown"),
        })

        # PASSO 5: Alerta apenas para sinais acionáveis
        if decision["recommendation"] in ("FORTE", "MODERADO"):
            summary = (
                f"{decision['recommendation']} | "
                f"confiança {decision['confidence']:.0%} | "
                + " | ".join(decision["reasons"])
            )
            if macro_result.get("warnings"):
                summary += "\n⚠️ Contexto macro: " + " | ".join(macro_result["warnings"])
            _hist_ctx = signal_dict.get("hist_context", "")
            send_alert(
                f"🚀 *SINAL DE COMPRA: {ticker}*\n\n"
                f"📈 RSI: {row['RSI']:.2f}\n"
                + (f"📊 Histórico: {_hist_ctx}\n" if _hist_ctx else "")
                + f"🛡️ ANÁLISE IA:\n{summary}\n\n"
                f"💡 Verifique seu app do Nubank!"
            )
            try:
                _paper_buy(
                    symbol=ticker,
                    price=float(row["Preço"]),
                    decision=decision["recommendation"],
                    ai_score=audit.get("score", 50),
                    pipeline="b3",
                    reason=" | ".join(decision.get("reasons", [])[:2]),
                )
            except Exception as _e:
                logger.warning(f"[PAPER] Falha ao executar compra B3: {_e}")

    # Relatório no terminal
    print("\n" + "=" * 50)
    print("RELATÓRIO FINAL DE AUDITORIA")
    print("=" * 50)
    for item in decisoes_finais:
        print(f"\n{item['Ativo']} | RSI: {item['RSI']:.2f} | {item['Recomendação']}")
        for reason in item["Razões"]:
            print(f"  • {reason}")

    # PASSO 6: Verificar trailing stops para posições abertas
    logger.info("--- Verificando trailing stops ---")
    try:
        _paper_prices = {str(r["Ticker"]): float(r["Preço"]) for _, r in df_foguetes.iterrows()}
        _check_paper_stops(_paper_prices, pipeline="b3")
    except Exception as _e:
        logger.warning(f"[PAPER] Falha ao verificar stops B3: {_e}")
    triggered = check_stops(messenger)
    if triggered:
        for t in triggered:
            logger.info(
                f"[STOP] {t['ticker']} | entrada R${t['entry']:.2f} | "
                f"saída R${t['exit']:.2f} | P&L R${t['pnl_brl']:+.2f}"
            )
    else:
        logger.info("Nenhum stop acionado.")

    return decisoes_finais


if __name__ == "__main__":
    orquestrar_investimento()

"""
crypto_main.py
--------------
Orquestrador do pipeline cripto.

Uso:
  python crypto_main.py            # Modo produção (Telegram + banco)
  python crypto_main.py --dry-run  # Modo teste (imprime mas não envia/grava)

Agenda via GitHub Actions (crypto_pipeline.yml) ou manualmente.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 output on Windows (cp1252 can't encode box-drawing chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

# Módulos do pipeline cripto
from crypto_scanner import scan_crypto
from crypto_decision import evaluate_signal, format_telegram_message
from crypto_monitor import check_stops, open_position

# Módulos existentes do Terminal Quant (não modificados)
from alerts import send_alert
from db import get_connection, init_db
from paper_trading import execute_paper_buy as _paper_buy, check_paper_stops as _check_paper_stops


# ---------------------------------------------------------------------------
# Configuração de log (arquivo + console)
# ---------------------------------------------------------------------------

LOG_DIR = Path("data")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "crypto_pipeline.log"

_handler_file = logging.FileHandler(LOG_FILE, encoding="utf-8")
_handler_file.setLevel(logging.INFO)
_handler_console = logging.StreamHandler(sys.stdout)
_handler_console.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_handler_file, _handler_console],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persistência de sinais cripto
# ---------------------------------------------------------------------------

def _save_crypto_signal(result: dict, signal: dict) -> None:
    """Grava sinal cripto na tabela crypto_signals do SQLite."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO crypto_signals
                    (symbol, decision, ai_score, ai_veredicto, price,
                     rsi_1h, galaxy_score, change_pct_24h, sentiment,
                     reasons, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["symbol"],
                    result["decision"],
                    result["ai_score"],
                    result["ai_veredicto"],
                    signal.get("price"),
                    signal.get("rsi_1h"),
                    signal.get("galaxy_score"),
                    signal.get("change_pct_24h"),
                    signal.get("sentiment"),
                    json.dumps(result["reasons"], ensure_ascii=False),
                    result["evaluated_at"],
                ),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[DB] Falha ao gravar {result['symbol']}: {e}")


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run_pipeline(dry_run: bool = False) -> None:
    print("=" * 60)
    print("INICIANDO PIPELINE CRIPTO")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    if dry_run:
        print("Modo: DRY-RUN (sem Telegram/banco)")
    else:
        print("Modo: PRODUÇÃO")
    print("=" * 60)

    # 0. Garantir que tabelas existam (inclui signal_cooldowns e crypto_positions)
    init_db()

    # 1. Coleta de dados (Binance + CoinGecko)
    logger.info("Iniciando varredura dos pares cripto...")
    signals = scan_crypto()

    if not signals:
        logger.warning("Nenhum par retornou dados. Encerrando pipeline.")
        print("Pipeline cripto concluído.")
        return

    # 1b. Verificar trailing stops com preços atuais antes de avaliar novos sinais
    current_prices = {s["symbol"]: s["price"] for s in signals}
    triggered = check_stops(current_prices, dry_run=dry_run)
    if triggered:
        logger.info(f"[MONITOR] {len(triggered)} stop(s) atingido(s) neste ciclo")

    if not dry_run:
        paper_stops = _check_paper_stops(current_prices, pipeline="cripto")
        if paper_stops:
            logger.info(f"[PAPER] {len(paper_stops)} stop(s) no paper trading cripto")

    print(f"\n{len(signals)} pares coletados.\n")

    # 2. Avaliação de cada sinal
    actionable = []
    report_rows = []

    for signal in signals:
        # dry-run pula chamadas de IA (mais rápido + sem custo de API)
        result = evaluate_signal(signal, call_ai=not dry_run)

        row = (
            f"  {signal['symbol']:<10} "
            f"${signal.get('price', 0):>12,.2f} | "
            f"RSI={str(signal.get('rsi_1h', 'N/A')):<6} | "
            f"galaxy={str(signal.get('galaxy_score', 'N/A')):<4} | "
            f"{result['decision']}"
        )
        report_rows.append(row)
        logger.info(row.strip())

        if result["decision"] in ("FORTE", "MODERADO"):
            actionable.append((signal, result))

    # 3. Relatório resumido
    print("\n── Relatório ──────────────────────────────────────────")
    for row in report_rows:
        print(row)

    # 4. Sinais acionáveis
    if actionable:
        print(f"\n── {len(actionable)} sinal(is) acionável(is) ──────────────")
        for signal, result in actionable:
            msg = format_telegram_message(signal, result)
            print(f"\n{msg}")
            print("-" * 40)

            if not dry_run:
                # Persiste no banco
                _save_crypto_signal(result, signal)
                # Envia alerta Telegram
                try:
                    send_alert(msg)
                    logger.info(f"[TELEGRAM] Alerta enviado: {result['symbol']} {result['decision']}")
                except Exception as e:
                    logger.error(f"[TELEGRAM] Falha ao enviar {result['symbol']}: {e}")
                # Registra posição para trailing stop
                open_position(signal["symbol"], signal["price"])
                # Paper trading
                try:
                    _paper_buy(
                        symbol=signal["symbol"],
                        price=signal["price"],
                        decision=result["decision"],
                        ai_score=result.get("ai_score", 50),
                        pipeline="cripto",
                        reason=" | ".join(result.get("reasons", [])[:2]),
                    )
                except Exception as _e:
                    logger.warning(f"[PAPER] Falha ao executar compra cripto: {_e}")
    else:
        print("\nNenhum sinal acionável neste ciclo.")

    print("\n" + "=" * 60)
    print("Pipeline cripto concluído.")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline Cripto — Terminal Quant")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Executa sem enviar Telegram nem gravar no banco",
    )
    args = parser.parse_args()
    run_pipeline(dry_run=args.dry_run)

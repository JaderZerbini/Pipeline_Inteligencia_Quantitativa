"""
crypto_monitor.py
-----------------
Monitora posições cripto abertas e dispara alerta de saída
quando o trailing stop é atingido.

Trailing stop de 7% — mesmo percentual usado no pipeline B3.
Chamado pelo crypto_main.py após cada scan.
"""

import logging
from datetime import datetime, timezone

from core.db import get_connection
from core.alerts import send_alert

logger = logging.getLogger(__name__)
STOP_PCT = 0.07


def open_position(symbol: str, entry_price: float) -> None:
    """Records a new open position for a FORTE/MODERADO signal."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE crypto_positions SET status='replaced', "
            "closed_at=?, close_reason='new_signal' "
            "WHERE symbol=? AND status='open'",
            (datetime.now(timezone.utc).isoformat(), symbol),
        )
        conn.execute(
            "INSERT INTO crypto_positions "
            "(symbol, entry_price, highest_price, opened_at) "
            "VALUES (?, ?, ?, ?)",
            (symbol, entry_price, entry_price,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    logger.info(f"[MONITOR] Posição aberta: {symbol} @ ${entry_price:,.2f}")


def check_stops(current_prices: dict, dry_run: bool = False) -> list:
    """
    Checks all open positions against current prices.
    Fires stop alert if price fell 7% from the highest price seen.

    Args:
        current_prices: dict of {symbol: current_price}
        dry_run:        if True, does not send Telegram or update DB

    Returns list of triggered stop dicts.
    """
    triggered = []
    try:
        with get_connection() as conn:
            positions = conn.execute(
                "SELECT id, symbol, entry_price, highest_price, stop_pct "
                "FROM crypto_positions WHERE status='open'"
            ).fetchall()
    except Exception as e:
        logger.warning(f"[MONITOR] Erro ao ler posições: {e}")
        return []

    for pos in positions:
        pos_id, symbol, entry, highest, stop_pct = pos
        current = current_prices.get(symbol)
        if current is None:
            continue

        new_highest = max(highest, current)
        stop_price = new_highest * (1 - stop_pct)

        with get_connection() as conn:
            conn.execute(
                "UPDATE crypto_positions SET highest_price=? WHERE id=?",
                (new_highest, pos_id),
            )
            conn.commit()

        if current <= stop_price:
            pnl_pct = (current - entry) / entry * 100
            result_icon = "✅" if pnl_pct >= 0 else "❌"
            result_word = "Lucro" if pnl_pct >= 0 else "Prejuízo"
            msg = (
                f"🔴 *{symbol}* — Hora de vender\n"
                f"\n"
                f"O preço caiu {stop_pct*100:.0f}% desde o ponto mais alto, "
                f"ativando a proteção automática.\n"
                f"\n"
                f"💵 Você comprou por: ${entry:,.2f}\n"
                f"💵 Preço atual: ${current:,.2f}\n"
                f"📊 Preço mais alto atingido: ${new_highest:,.2f}\n"
                f"{result_icon} {result_word}: {pnl_pct:+.2f}%\n"
                f"\n"
                f"Considere vender agora para proteger seu resultado."
            )
            logger.info(
                f"[MONITOR] STOP: {symbol} @ ${current:,.2f} "
                f"(entrada ${entry:,.2f}, P&L {pnl_pct:+.1f}%)"
            )
            if not dry_run:
                try:
                    send_alert(msg)
                except Exception as e:
                    logger.error(f"[MONITOR] Falha ao enviar alerta de stop: {e}")
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE crypto_positions SET status='closed', "
                        "closed_at=?, close_price=?, close_reason='stop' "
                        "WHERE id=?",
                        (datetime.now(timezone.utc).isoformat(), current, pos_id),
                    )
                    conn.commit()
            triggered.append({"symbol": symbol, "price": current, "pnl_pct": pnl_pct})

    return triggered

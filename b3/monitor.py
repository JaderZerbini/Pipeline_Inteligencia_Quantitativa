"""Trailing stop monitor with macro-aware alerts.

Exposes two entry points:
  check_stops()  — one-shot check called from main.py after each pipeline run.
  run_monitor()  — continuous loop for standalone use.
"""

import asyncio
import time

import yfinance as yf

from core.alerts import TelegramAlert
from core.db import close_operation, get_open_operations, update_peak_price
from core.macro_monitor import fetch_macro_snapshot


def check_trailing_stop(
    ticker: str,
    preco_compra: float,
    preco_atual: float,
    preco_maximo_atingido: float,
) -> tuple[bool, float]:
    """Return (should_sell, new_peak). Triggers when price falls 7% from peak."""
    if preco_atual > preco_maximo_atingido:
        preco_maximo_atingido = preco_atual

    queda_do_topo = (1 - (preco_atual / preco_maximo_atingido)) * 100

    if queda_do_topo >= 7.0:
        return True, preco_maximo_atingido   # VENDER
    return False, preco_maximo_atingido      # MANTER


def check_stops(messenger: TelegramAlert = None) -> list[dict]:
    """One-shot check: macro alerts + trailing stops for all open positions.

    Peak prices are persisted in the DB so state survives across calls from
    both check_stops() and run_monitor().

    Returns:
        List of dicts for each triggered stop, each with keys:
        op_id, ticker, entry, exit, pnl_brl.
    """
    if messenger is None:
        messenger = TelegramAlert()

    snapshot = fetch_macro_snapshot()
    open_ops = get_open_operations()

    # --- Unified macro alert ---
    usdbrl = snapshot.get("usdbrl")
    brent = snapshot.get("brent")
    oil_positions_open = any(op["ticker"] in ("PETR4", "PRIO3") for op in open_ops)

    macro_adverse = (usdbrl and usdbrl["change_pct"] > 2.0) or (
        brent and brent["change_pct"] < -3.0 and oil_positions_open
    )
    if macro_adverse:
        asyncio.run(
            messenger.enviar_alerta_compra(
                "MACRO",
                0,
                (
                    "⚠️ *Alerta de mercado*\n\n"
                    "Condições macroeconômicas adversas foram detectadas.\n\n"
                    "O dólar subiu mais de 2% ou o petróleo caiu mais de 3%.\n"
                    "Revise suas posições abertas — o mercado pode estar instável."
                ),
            )
        )
        print("[MACRO] Alerta adverso enviado via Telegram.")

    # --- Trailing stop checks ---
    triggered: list[dict] = []

    for op in open_ops:
        op_id: int = op["id"]
        ticker: str = op["ticker"]
        entry: float = op["entry_price"]
        stop: float = op["stop_price"]
        # Use DB-persisted peak; fall back to entry price on first check
        peak: float = op.get("peak_price") or entry

        try:
            current: float = yf.Ticker(f"{ticker}.SA").fast_info.last_price
        except Exception as e:
            print(f"[MONITOR WARN] {ticker}: {e}")
            continue

        sell, new_peak = check_trailing_stop(ticker, entry, current, peak)

        if new_peak != peak:
            update_peak_price(op_id, new_peak)

        if sell:
            pnl_brl = round(current - entry, 4)
            close_operation(op_id, exit_price=current, pnl_brl=pnl_brl, status="STOPPED")
            triggered.append(
                {"op_id": op_id, "ticker": ticker, "entry": entry, "exit": current, "pnl_brl": pnl_brl}
            )
            _pnl_icon = "✅" if pnl_brl >= 0 else "❌"
            _pnl_word = "Lucro" if pnl_brl >= 0 else "Prejuízo"
            asyncio.run(
                messenger.enviar_alerta_compra(
                    ticker,
                    0,
                    (
                        f"🔴 *{ticker}* — Hora de vender\n"
                        f"\n"
                        f"O preço caiu 7% desde o ponto mais alto, "
                        f"ativando a proteção automática.\n"
                        f"\n"
                        f"💵 Você comprou por: R$ {entry:.2f}\n"
                        f"💵 Preço atual: R$ {current:.2f}\n"
                        f"{_pnl_icon} {_pnl_word}: R$ {pnl_brl:+.2f} por ação\n"
                        f"\n"
                        f"Considere vender agora para proteger seu resultado."
                    ),
                )
            )
            print(
                f"[STOP] {ticker} — entrada R${entry:.2f} | saída R${current:.2f} | "
                f"P&L R${pnl_brl:+.2f} | status=STOPPED gravado no DB"
            )

    return triggered


def run_monitor(interval_seconds: int = 60) -> None:
    """Continuous trailing stop loop. Calls check_stops() each iteration."""
    messenger = TelegramAlert()
    print(f"Monitor iniciado — verificando a cada {interval_seconds}s")

    while True:
        check_stops(messenger)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_monitor()

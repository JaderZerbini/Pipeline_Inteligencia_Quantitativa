"""
paper_trading.py
----------------
Simulador de paper trading para os pipelines B3 e Cripto.
Cada pipeline tem um sub-portfólio independente com capital inicial de R$5.000.
Executa compras fictícias em sinais FORTE/MODERADO e trailing stop de 7%.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from db import get_connection
from position_sizing import calculate_position

logger = logging.getLogger(__name__)

TRAILING_STOP_PCT = 0.07
MAX_POSITIONS = 4
INITIAL_CAPITAL = 5000.0

_initialized = False


def _ensure_init() -> None:
    global _initialized
    if not _initialized:
        from db import init_db
        init_db()
        _initialized = True


def get_portfolio(pipeline: str) -> dict:
    """Returns or creates the paper portfolio for 'b3' or 'cripto'."""
    _ensure_init()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, initial_capital, current_capital "
            "FROM paper_portfolio WHERE pipeline = ?",
            (pipeline,),
        ).fetchone()
        if row:
            return {
                "id": row[0],
                "name": row[1],
                "initial_capital": row[2],
                "current_capital": row[3],
            }
        now = datetime.now(timezone.utc).isoformat()
        name = "B3 Paper" if pipeline == "b3" else "Cripto Paper"
        cursor = conn.execute(
            "INSERT INTO paper_portfolio "
            "(name, initial_capital, current_capital, pipeline, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, INITIAL_CAPITAL, INITIAL_CAPITAL, pipeline, now, now),
        )
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "name": name,
            "initial_capital": INITIAL_CAPITAL,
            "current_capital": INITIAL_CAPITAL,
        }


def get_open_positions(portfolio_id: int) -> list[dict]:
    """Returns all open positions for a portfolio."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, symbol, entry_price, quantity, current_price, stop_price "
            "FROM paper_positions WHERE portfolio_id = ? AND status = 'open'",
            (portfolio_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_open_positions(portfolio_id: int) -> int:
    """Counts open positions for a portfolio."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM paper_positions "
            "WHERE portfolio_id = ? AND status = 'open'",
            (portfolio_id,),
        ).fetchone()[0]


def execute_paper_buy(
    symbol: str,
    price: float,
    decision: str,
    ai_score: int,
    pipeline: str,
    reason: str,
) -> dict | None:
    """Executes a fictional BUY if conditions are met. Returns trade dict or None."""
    portfolio = get_portfolio(pipeline)
    portfolio_id = portfolio["id"]

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM paper_positions "
            "WHERE portfolio_id = ? AND symbol = ? AND status = 'open'",
            (portfolio_id, symbol),
        ).fetchone()
    if existing:
        logger.info(f"[PAPER BUY] {symbol} já tem posição aberta — ignorado")
        return None

    open_count = count_open_positions(portfolio_id)
    sizing = calculate_position(decision, portfolio["current_capital"], open_count, price)
    if not sizing["allowed"]:
        logger.info(f"[PAPER BUY] {symbol} — {sizing['reason']}")
        return None

    qty = sizing["units"]
    value = sizing["alloc_value"]
    stop_price = round(price * (1 - TRAILING_STOP_PCT), 8)
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        pos_cursor = conn.execute(
            "INSERT INTO paper_positions "
            "(portfolio_id, pipeline, symbol, entry_price, quantity, "
            " current_price, stop_price, status, opened_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            (portfolio_id, pipeline, symbol, price, qty, price, stop_price, now),
        )
        pos_id = pos_cursor.lastrowid
        conn.execute(
            "INSERT INTO paper_trades "
            "(portfolio_id, pipeline, symbol, side, price, quantity, value, "
            " signal_decision, ai_score, reason, traded_at) "
            "VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?)",
            (portfolio_id, pipeline, symbol, price, qty, value, decision, ai_score, reason, now),
        )
        conn.execute(
            "UPDATE paper_portfolio "
            "SET current_capital = current_capital - ?, updated_at = ? WHERE id = ?",
            (value, now, portfolio_id),
        )
        conn.commit()

    logger.info(
        f"[PAPER BUY] {symbol} | {decision} | {price} | "
        f"qty={qty:.6f} | value={value:.2f} | stop={stop_price:.8f}"
    )
    return {
        "position_id": pos_id,
        "symbol": symbol,
        "side": "BUY",
        "price": price,
        "quantity": qty,
        "value": value,
        "stop_price": stop_price,
        "decision": decision,
    }


def execute_paper_sell(
    position_id: int,
    current_price: float,
    reason: str,
    pipeline: str,
) -> dict | None:
    """Closes an open paper position."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        pos = conn.execute(
            "SELECT * FROM paper_positions WHERE id = ? AND status = 'open'",
            (position_id,),
        ).fetchone()
    if not pos:
        return None

    pos = dict(pos)
    entry_price = pos["entry_price"]
    qty = pos["quantity"]
    value_in = entry_price * qty
    value_out = current_price * qty
    pnl = value_out - value_in
    pnl_pct = (pnl / value_in * 100) if value_in else 0.0
    now = datetime.now(timezone.utc).isoformat()
    portfolio_id = pos["portfolio_id"]

    with get_connection() as conn:
        conn.execute(
            "UPDATE paper_positions "
            "SET status='closed', current_price=?, close_price=?, "
            "    pnl=?, pnl_pct=?, closed_at=?, close_reason=? "
            "WHERE id=?",
            (current_price, current_price, pnl, pnl_pct, now, reason, position_id),
        )
        conn.execute(
            "INSERT INTO paper_trades "
            "(portfolio_id, pipeline, symbol, side, price, quantity, value, reason, traded_at) "
            "VALUES (?, ?, ?, 'SELL', ?, ?, ?, ?, ?)",
            (portfolio_id, pipeline, pos["symbol"], current_price, qty, value_out, reason, now),
        )
        conn.execute(
            "UPDATE paper_portfolio "
            "SET current_capital = current_capital + ?, updated_at = ? WHERE id = ?",
            (value_out, now, portfolio_id),
        )
        conn.commit()

    return {
        "symbol": pos["symbol"],
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "reason": reason,
    }


def check_paper_stops(current_prices: dict, pipeline: str) -> list[dict]:
    """Updates trailing stops and closes positions where stop is hit."""
    portfolio = get_portfolio(pipeline)
    portfolio_id = portfolio["id"]
    positions = get_open_positions(portfolio_id)
    triggered = []

    for pos in positions:
        symbol = pos["symbol"]
        if symbol not in current_prices:
            continue
        cur_price = current_prices[symbol]
        old_stop = pos.get("stop_price") or (pos["entry_price"] * (1 - TRAILING_STOP_PCT))
        new_stop = round(cur_price * (1 - TRAILING_STOP_PCT), 8)
        updated_stop = max(old_stop, new_stop)

        with get_connection() as conn:
            conn.execute(
                "UPDATE paper_positions SET current_price=?, stop_price=? WHERE id=?",
                (cur_price, updated_stop, pos["id"]),
            )
            conn.commit()

        if cur_price <= updated_stop:
            result = execute_paper_sell(pos["id"], cur_price, "trailing_stop", pipeline)
            if result:
                triggered.append(result)

    return triggered


def get_portfolio_summary(pipeline: str) -> dict:
    """Returns full performance summary for a pipeline portfolio."""
    portfolio = get_portfolio(pipeline)
    portfolio_id = portfolio["id"]
    positions = get_open_positions(portfolio_id)

    unrealized_pnl = 0.0
    open_pos_list = []
    for pos in positions:
        cur = pos.get("current_price") or pos["entry_price"]
        entry = pos["entry_price"]
        qty = pos["quantity"]
        p = (cur - entry) * qty
        p_pct = ((cur - entry) / entry * 100) if entry else 0.0
        unrealized_pnl += p
        open_pos_list.append({
            "symbol": pos["symbol"],
            "entry_price": entry,
            "quantity": qty,
            "current_price": cur,
            "stop_price": pos.get("stop_price"),
            "pnl": round(p, 2),
            "pnl_pct": round(p_pct, 2),
        })

    with get_connection() as conn:
        total_pnl = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM paper_positions "
            "WHERE portfolio_id=? AND status='closed'",
            (portfolio_id,),
        ).fetchone()[0]
        buy_count = conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE portfolio_id=? AND side='BUY'",
            (portfolio_id,),
        ).fetchone()[0]
        closed_count = conn.execute(
            "SELECT COUNT(*) FROM paper_positions "
            "WHERE portfolio_id=? AND status='closed'",
            (portfolio_id,),
        ).fetchone()[0]
        wins = conn.execute(
            "SELECT COUNT(*) FROM paper_positions "
            "WHERE portfolio_id=? AND status='closed' AND pnl>0",
            (portfolio_id,),
        ).fetchone()[0]
        losses = conn.execute(
            "SELECT COUNT(*) FROM paper_positions "
            "WHERE portfolio_id=? AND status='closed' AND pnl<=0",
            (portfolio_id,),
        ).fetchone()[0]

    current_capital = portfolio["current_capital"]
    total_value = current_capital + unrealized_pnl
    initial = portfolio["initial_capital"]
    total_return_pct = ((total_value - initial) / initial * 100) if initial else 0.0
    win_rate = round((wins / closed_count * 100) if closed_count else 0.0, 1)

    return {
        "initial_capital": initial,
        "current_capital": current_capital,
        "total_value": total_value,
        "total_return_pct": round(total_return_pct, 2),
        "total_pnl": round(float(total_pnl), 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_trades": buy_count,
        "closed_trades": closed_count,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "open_positions": open_pos_list,
    }


def reset_portfolio(pipeline: str) -> None:
    """Closes all open positions and resets capital to R$5,000."""
    portfolio = get_portfolio(pipeline)
    portfolio_id = portfolio["id"]
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute(
            "UPDATE paper_positions "
            "SET status='closed', closed_at=?, close_reason='reset' "
            "WHERE portfolio_id=? AND status='open'",
            (now, portfolio_id),
        )
        conn.execute(
            "UPDATE paper_portfolio "
            "SET current_capital=?, updated_at=? WHERE id=?",
            (INITIAL_CAPITAL, now, portfolio_id),
        )
        conn.commit()

    logger.info(f"[PAPER] Portfólio {pipeline} resetado para R$5.000,00")

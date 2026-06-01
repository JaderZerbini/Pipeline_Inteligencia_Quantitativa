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


def evaluate_exit(
    position: dict,
    current_signal: dict,
    pipeline: str,
    dry_run: bool = False,
) -> dict:
    """
    Asks the AI whether an open paper position should be closed.
    Returns {"should_exit": bool, "reason": str, "confidence": int}.
    """
    from sentiment_analyzer import analyze_crypto

    symbol        = position["symbol"]
    entry_price   = position["entry_price"]
    current_price = current_signal.get("price", 0)
    pnl_pct       = ((current_price - entry_price) / entry_price * 100
                     if entry_price > 0 else 0)
    rsi           = current_signal.get("rsi_1h")
    galaxy        = current_signal.get("galaxy_score")
    hist_context  = current_signal.get("hist_context", "N/A")
    hist_trend    = current_signal.get("hist_trend", "unknown")
    stop_price    = position.get("stop_price", 0)

    # Prompt uses the standard schema that _parse_gemini_json expects
    # (score + verdict + reason + flags), PLUS should_exit as extra field
    prompt = (
        f"Analise se devo SAIR desta posição de cripto.\n\n"
        f"Ativo: {symbol}\n"
        f"Preço de entrada: ${entry_price:,.2f}\n"
        f"Preço atual: ${current_price:,.2f}\n"
        f"P&L atual: {pnl_pct:+.2f}%\n"
        f"RSI(1h) atual: {rsi}\n"
        f"Galaxy Score atual: {galaxy}\n"
        f"Contexto histórico: {hist_context}\n"
        f"Tendência: {hist_trend}\n"
        f"Stop automático em: ${stop_price:,.2f}\n\n"
        f"Avalie: RSI sobrecomprado? Momentum revertido? P&L justifica saída? Reversão brusca?\n\n"
        'Responda SOMENTE com JSON: '
        '{"score": 0-100, "verdict": "SAIR|MANTER", "reason": "uma frase em português", '
        '"flags": [], "should_exit": true/false}\n'
        '- score = confiança (0=incerto, 100=muito confiante)\n'
        '- verdict = "SAIR" se sugere fechar, "MANTER" se não\n'
        '- should_exit = true se verdict é SAIR'
    )

    try:
        result = analyze_crypto(prompt)
        if not result:
            return {"should_exit": False, "reason": "IA indisponível", "confidence": 0}

        # should_exit from explicit field, or inferred from verdict
        should_exit = result.get("should_exit", result.get("verdict") == "SAIR")
        confidence  = result.get("score", 50)
        reason      = result.get("reason", "")

        # Only exit if AI is confident (>= 70) to avoid premature exits on noise
        if should_exit and confidence >= 70:
            logger.info(
                f"[PAPER EXIT] {symbol}: IA sugere saída "
                f"(confiança={confidence}, P&L={pnl_pct:+.2f}%, razão={reason})"
            )
            return {"should_exit": True, "reason": f"IA: {reason}", "confidence": confidence}
        else:
            return {
                "should_exit": False,
                "reason": f"IA não sugere saída (confiança={confidence})",
                "confidence": confidence,
            }

    except Exception as e:
        logger.warning(f"[PAPER EXIT] {symbol}: erro na avaliação — {e}")
        return {"should_exit": False, "reason": f"Erro: {e}", "confidence": 0}


def check_ai_exits(
    signals: list[dict],
    pipeline: str,
    dry_run: bool = False,
) -> list[dict]:
    """
    For each open position, evaluates AI exit recommendation.
    Called after check_paper_stops() in the scheduler cycle.
    Returns list of positions where AI recommended and executed exit.
    """
    portfolio = get_portfolio(pipeline)
    positions = get_open_positions(portfolio["id"])

    if not positions:
        return []

    signal_map = {s["symbol"]: s for s in signals}
    exited = []

    for pos in positions:
        symbol  = pos["symbol"]
        current = signal_map.get(symbol)
        if not current:
            continue

        eval_result = evaluate_exit(pos, current, pipeline, dry_run)

        if eval_result["should_exit"]:
            if not dry_run:
                sell_result = execute_paper_sell(
                    pos["id"],
                    current["price"],
                    eval_result["reason"],
                    pipeline,
                )
                if sell_result:
                    from alerts import send_alert
                    pnl     = sell_result.get("pnl", 0)
                    pnl_pct = sell_result.get("pnl_pct", 0)
                    icon    = "📈" if pnl >= 0 else "📉"
                    send_alert(
                        f"{icon} *{symbol}* — SAÍDA POR IA (paper)\n"
                        f"💲 Entrada: ${pos['entry_price']:,.2f}\n"
                        f"💲 Saída: ${current['price']:,.2f}\n"
                        f"{'✅' if pnl >= 0 else '❌'} P&L: "
                        f"R$ {pnl:+.2f} ({pnl_pct:+.2f}%)\n"
                        f"🤖 Motivo: {eval_result['reason']}\n"
                        f"📊 {current.get('hist_context', '')}"
                    )
                    exited.append({"symbol": symbol, **sell_result})
            else:
                logger.info(
                    f"[PAPER EXIT DRY] {symbol}: saída sugerida — "
                    f"{eval_result['reason']}"
                )
                exited.append({
                    "symbol": symbol,
                    "dry_run": True,
                    "reason": eval_result["reason"],
                })

    return exited


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

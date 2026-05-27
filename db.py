"""Persistence layer for Terminal Quant using SQLite (stdlib only)."""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_DIR = Path("data")
DB_PATH = DB_DIR / "terminal_quant.db"


def _connect() -> sqlite3.Connection:
    """Open a connection to the database, creating the data/ directory if needed."""
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# Public alias used by crypto_main.py and app.py
get_connection = _connect


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Returns current schema version, 0 if never set."""
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def run_migrations(conn: sqlite3.Connection) -> None:
    """Applies pending schema migrations in order."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()

    current = get_schema_version(conn)

    # Add new migrations here as the schema evolves.
    # Each migration is a (version, sql) tuple.
    # Never modify existing migrations — only add new ones.
    migrations = [
        (1, "SELECT 1"),  # baseline — schema already exists
        (2, "CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker)"),
        (3, "CREATE INDEX IF NOT EXISTS idx_crypto_signals_symbol "
            "ON crypto_signals(symbol, created_at)"),
        (4, "CREATE INDEX IF NOT EXISTS idx_cooldowns_lookup "
            "ON signal_cooldowns(ticker, pipeline, sent_at)"),
        (5, """
            CREATE TABLE IF NOT EXISTS paper_portfolio (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL DEFAULT 'Principal',
                initial_capital REAL NOT NULL DEFAULT 5000.0,
                current_capital REAL NOT NULL DEFAULT 5000.0,
                pipeline        TEXT NOT NULL DEFAULT 'both',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """),
        (6, """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id    INTEGER NOT NULL
                                REFERENCES paper_portfolio(id),
                pipeline        TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                side            TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                price           REAL NOT NULL,
                quantity        REAL NOT NULL,
                value           REAL NOT NULL,
                signal_decision TEXT,
                ai_score        INTEGER,
                reason          TEXT,
                traded_at       TEXT NOT NULL
            )
        """),
        (7, """
            CREATE TABLE IF NOT EXISTS paper_positions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id    INTEGER NOT NULL
                                REFERENCES paper_portfolio(id),
                pipeline        TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                entry_price     REAL NOT NULL,
                quantity        REAL NOT NULL,
                current_price   REAL,
                stop_price      REAL,
                status          TEXT NOT NULL DEFAULT 'open'
                                CHECK(status IN ('open','closed')),
                opened_at       TEXT NOT NULL,
                closed_at       TEXT,
                pnl             REAL,
                pnl_pct         REAL
            )
        """),
        (8, "ALTER TABLE paper_positions ADD COLUMN close_price REAL"),
        (9, "ALTER TABLE paper_positions ADD COLUMN close_reason TEXT"),
    ]

    for version, sql in migrations:
        if version > current:
            try:
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
                logger.info(f"[DB] Migração {version} aplicada")
            except Exception as e:
                logger.error(f"[DB] Migração {version} falhou: {e}")


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                ticker       TEXT NOT NULL,
                rsi          REAL,
                volume_ratio REAL,
                price        REAL,
                signal_type  TEXT CHECK(signal_type IN ('BUY','WATCH','SKIP')),
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        # Safe additive migrations — ignored if column already exists
        for ddl in (
            "ALTER TABLE signals ADD COLUMN macro_flags TEXT",
            "ALTER TABLE signals ADD COLUMN recommendation TEXT DEFAULT 'AGUARDAR'",
            "ALTER TABLE operations ADD COLUMN peak_price REAL",
        ):
            try:
                conn.execute(ddl)
                conn.commit()
            except sqlite3.OperationalError:
                pass
        conn.execute("DROP TABLE IF EXISTS signals_placeholder")
        conn.commit()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS crypto_signals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                decision        TEXT    NOT NULL,
                ai_score        INTEGER,
                ai_veredicto    TEXT,
                price           REAL,
                rsi_1h          REAL,
                galaxy_score    INTEGER,
                change_pct_24h  REAL,
                sentiment       TEXT,
                reasons         TEXT,
                created_at      TEXT    NOT NULL
            );
        """)
        conn.commit()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS audits (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id    INTEGER REFERENCES signals(id),
                gemini_score INTEGER CHECK(gemini_score BETWEEN 0 AND 100),
                headline     TEXT,
                source       TEXT,
                verdict      TEXT CHECK(verdict IN ('CONFIAVEL','RUIDO','MANIPULACAO')),
                raw_response TEXT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS operations (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id    INTEGER REFERENCES signals(id),
                ticker       TEXT NOT NULL,
                entry_price  REAL,
                entry_date   TEXT,
                exit_price   REAL,
                exit_date    TEXT,
                stop_price   REAL,
                status       TEXT CHECK(status IN ('OPEN','CLOSED','STOPPED')),
                pnl_brl      REAL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signal_cooldowns (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker   TEXT NOT NULL,
                pipeline TEXT NOT NULL DEFAULT 'b3',
                sent_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cooldowns_ticker
                ON signal_cooldowns(ticker, pipeline, sent_at);

            CREATE TABLE IF NOT EXISTS crypto_positions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol        TEXT NOT NULL,
                entry_price   REAL NOT NULL,
                highest_price REAL NOT NULL,
                stop_pct      REAL NOT NULL DEFAULT 0.07,
                status        TEXT NOT NULL DEFAULT 'open',
                opened_at     TEXT NOT NULL,
                closed_at     TEXT,
                close_price   REAL,
                close_reason  TEXT
            );
        """)
        conn.commit()
        run_migrations(conn)
        ensure_default_portfolio()


def ensure_default_portfolio() -> int:
    """Creates the default paper trading portfolio if none exists. Returns its ID."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM paper_portfolio LIMIT 1"
        ).fetchone()
        if existing:
            return existing[0]
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "INSERT INTO paper_portfolio "
            "(name, initial_capital, current_capital, pipeline, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("Principal", 5000.0, 5000.0, "both", now, now),
        )
        conn.commit()
        return cursor.lastrowid


def is_in_cooldown(ticker: str, pipeline: str = 'b3', hours: int = 4) -> bool:
    """Returns True if ticker already had an actionable signal in the last N hours."""
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            """SELECT 1 FROM signal_cooldowns
               WHERE ticker = ? AND pipeline = ?
               AND sent_at >= ? LIMIT 1""",
            (ticker, pipeline, cutoff),
        ).fetchone()
    return row is not None


def register_cooldown(ticker: str, pipeline: str = 'b3') -> None:
    """Records that an actionable signal was sent for this ticker right now."""
    from datetime import datetime, timezone
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO signal_cooldowns (ticker, pipeline, sent_at) VALUES (?, ?, ?)",
            (ticker, pipeline, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def save_signal(
    timestamp: str,
    ticker: str,
    rsi: float,
    volume_ratio: float,
    price: float,
    signal_type: str,
    recommendation: str = "AGUARDAR",
) -> int:
    """Insert a signal row and return its generated id.

    Args:
        timestamp:      ISO-format datetime string of when the signal was detected.
        ticker:         Stock ticker without the .SA suffix (e.g. 'PETR4').
        rsi:            14-period RSI value at signal time.
        volume_ratio:   Current volume divided by 20-day average volume.
        price:          Last close price in BRL.
        signal_type:    One of 'BUY', 'WATCH', or 'SKIP'.
        recommendation: Final decision from decision_engine: FORTE, MODERADO,
                        AGUARDAR, or BLOQUEADO. Defaults to AGUARDAR and is
                        updated by update_signal_recommendation() after the
                        decision engine runs.

    Returns:
        The auto-incremented id of the inserted row.
    """
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO signals
                (timestamp, ticker, rsi, volume_ratio, price, signal_type, recommendation)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, ticker, rsi, volume_ratio, price, signal_type, recommendation),
        )
        conn.commit()
        return cursor.lastrowid


def update_signal_recommendation(signal_id: int, recommendation: str) -> None:
    """Update the recommendation field of an existing signal row.

    Called by main.py after decision_engine produces the final verdict,
    since the scanner saves the signal before the recommendation is known.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE signals SET recommendation = ? WHERE id = ?",
            (recommendation, signal_id),
        )
        conn.commit()


def save_audit(
    signal_id: int,
    gemini_score: int,
    headline: str,
    source: str,
    verdict: str,
    raw_response: str,
) -> int:
    """Insert an audit row linked to a signal and return its id.

    Args:
        signal_id:    FK to the signals table row this audit belongs to.
        gemini_score: Confidence score from 0 (noise) to 100 (reliable).
        headline:     News headline(s) that were audited.
        source:       News source identifier (e.g. 'Google News RSS').
        verdict:      Gemini classification: 'CONFIAVEL', 'RUIDO', or 'MANIPULACAO'.
        raw_response: Full raw text returned by Gemini for traceability.

    Returns:
        The auto-incremented id of the inserted row.
    """
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO audits (signal_id, gemini_score, headline, source, verdict, raw_response)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (signal_id, gemini_score, headline, source, verdict, raw_response),
        )
        conn.commit()
        return cursor.lastrowid


def save_operation(
    signal_id: int,
    ticker: str,
    entry_price: float,
    entry_date: str,
    stop_price: float,
    status: str = "OPEN",
) -> int:
    """Insert an operation row and return its id.

    exit_price, exit_date, and pnl_brl are left NULL until the position is closed.

    Args:
        signal_id:   FK to the signals row that triggered this operation.
        ticker:      Stock ticker without the .SA suffix.
        entry_price: Price in BRL at which the position was entered.
        entry_date:  ISO-format date string of the entry.
        stop_price:  Initial stop-loss price in BRL.
        status:      Initial status, defaults to 'OPEN'.

    Returns:
        The auto-incremented id of the inserted row.
    """
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO operations (signal_id, ticker, entry_price, entry_date, stop_price, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (signal_id, ticker, entry_price, entry_date, stop_price, status),
        )
        conn.commit()
        return cursor.lastrowid


def get_open_operations() -> list[dict]:
    """Return all operations with status='OPEN' as a list of dicts.

    Returns:
        List of row dicts, each key matching a column in the operations table.
    """
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM operations WHERE status = 'OPEN'")
        return [dict(row) for row in cursor.fetchall()]


def get_signals_history(days: int = 30) -> list[dict]:
    """Return signals recorded in the last *days* calendar days, newest first.

    Args:
        days: How many days back to look. Defaults to 30.

    Returns:
        List of row dicts, each key matching a column in the signals table.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM signals WHERE created_at >= ? ORDER BY created_at DESC",
            (since,),
        )
        return [dict(row) for row in cursor.fetchall()]


def update_peak_price(op_id: int, peak_price: float) -> None:
    """Persist the highest price seen since entry for an open operation."""
    with _connect() as conn:
        conn.execute(
            "UPDATE operations SET peak_price = ? WHERE id = ?",
            (peak_price, op_id),
        )
        conn.commit()


def close_operation(
    op_id: int,
    exit_price: float,
    pnl_brl: float,
    status: str = "STOPPED",
) -> None:
    """Mark an operation as closed, recording exit price, date, and P&L.

    Args:
        op_id:      Primary key of the operations row to update.
        exit_price: Price in BRL at which the position was exited.
        pnl_brl:    Realised profit/loss per share in BRL (exit - entry).
        status:     'STOPPED' for trailing-stop exits, 'CLOSED' for manual.
    """
    exit_date = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE operations
               SET exit_price = ?,
                   exit_date  = ?,
                   status     = ?,
                   pnl_brl    = ?
             WHERE id = ?
            """,
            (exit_price, exit_date, status, pnl_brl, op_id),
        )
        conn.commit()


def get_all_operations() -> list[dict]:
    """Return all operations regardless of status, newest first."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM operations ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_closed_operations() -> list[dict]:
    """Return operations with status CLOSED or STOPPED, ordered by exit_date DESC."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM operations WHERE status IN ('CLOSED','STOPPED') ORDER BY exit_date DESC"
        )
        return [dict(row) for row in cursor.fetchall()]


def get_signal_by_id(signal_id: int) -> dict | None:
    """Return a single signal row by primary key, or None if not found."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_previous_signal(ticker: str) -> dict | None:
    """Return the second most recent signal for ticker, or None if fewer than 2 exist."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM signals WHERE ticker = ? ORDER BY created_at DESC LIMIT 2",
            (ticker,),
        )
        rows = cursor.fetchall()
        return dict(rows[1]) if len(rows) >= 2 else None


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")

-- Terminal Quant — Database Schema
-- Generated: 2026-06
-- Database: SQLite (local: data/terminal_quant.db, Railway: /data/terminal_quant.db)

-- B3 pipeline signals
CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT,
    ticker        TEXT NOT NULL,
    rsi           REAL,
    volume_ratio  REAL,
    price         REAL,
    signal_type   TEXT,
    created_at    TEXT,
    macro_flags   TEXT,
    recommendation TEXT,
    hist_trend    TEXT,
    hist_position TEXT,
    pct_from_ma200 REAL
);

-- B3 audit trail
CREATE TABLE IF NOT EXISTS audits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id  INTEGER REFERENCES signals(id),
    model      TEXT,
    score      INTEGER,
    verdict    TEXT,
    created_at TEXT
);

-- B3 real operations
CREATE TABLE IF NOT EXISTS operations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker     TEXT,
    action     TEXT,
    price      REAL,
    quantity   REAL,
    created_at TEXT
);

-- Crypto pipeline signals
CREATE TABLE IF NOT EXISTS crypto_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    decision        TEXT NOT NULL,
    ai_score        INTEGER,
    ai_veredicto    TEXT,
    price           REAL,
    rsi_1h          REAL,
    galaxy_score    INTEGER,
    change_pct_24h  REAL,
    sentiment       TEXT,
    reasons         TEXT,
    hist_trend      TEXT,
    hist_position   TEXT,
    pct_from_ma200  REAL,
    created_at      TEXT NOT NULL
);

-- Cooldown tracking (prevents duplicate alerts)
CREATE TABLE IF NOT EXISTS signal_cooldowns (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker   TEXT NOT NULL,
    pipeline TEXT NOT NULL DEFAULT 'b3',
    sent_at  TEXT NOT NULL
);

-- Crypto open/closed positions (real trailing stop tracking)
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

-- Paper trading portfolios
CREATE TABLE IF NOT EXISTS paper_portfolio (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL DEFAULT 'Principal',
    initial_capital REAL NOT NULL DEFAULT 5000.0,
    current_capital REAL NOT NULL DEFAULT 5000.0,
    pipeline        TEXT NOT NULL DEFAULT 'both',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Paper trading individual trades
CREATE TABLE IF NOT EXISTS paper_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id    INTEGER NOT NULL REFERENCES paper_portfolio(id),
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
);

-- Paper trading open/closed positions
CREATE TABLE IF NOT EXISTS paper_positions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES paper_portfolio(id),
    pipeline     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    entry_price  REAL NOT NULL,
    quantity     REAL NOT NULL,
    current_price REAL,
    stop_price   REAL,
    status       TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
    opened_at    TEXT NOT NULL,
    closed_at    TEXT,
    pnl          REAL,
    pnl_pct      REAL
);

-- Schema migration tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

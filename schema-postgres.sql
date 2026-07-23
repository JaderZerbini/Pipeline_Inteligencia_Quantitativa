-- Terminal Quant Database Schema (PostgreSQL)

CREATE TABLE IF NOT EXISTS signals (
    id             SERIAL PRIMARY KEY,
    timestamp      TEXT,
    ticker         TEXT NOT NULL,
    rsi            REAL,
    volume_ratio   REAL,
    price          REAL,
    signal_type    TEXT,
    created_at     TEXT,
    macro_flags    TEXT,
    recommendation TEXT,
    hist_trend     TEXT,
    hist_position  TEXT,
    pct_from_ma200 REAL
);

CREATE TABLE IF NOT EXISTS audits (
    id           SERIAL PRIMARY KEY,
    signal_id    INTEGER REFERENCES signals(id),
    gemini_score INTEGER,
    headline     TEXT,
    source       TEXT,
    verdict      TEXT,
    raw_response TEXT,
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS operations (
    id           SERIAL PRIMARY KEY,
    signal_id    INTEGER REFERENCES signals(id),
    ticker       TEXT NOT NULL,
    entry_price  REAL,
    entry_date   TEXT,
    exit_price   REAL,
    exit_date    TEXT,
    stop_price   REAL,
    status       TEXT CHECK(status IN ('OPEN','CLOSED','STOPPED')),
    pnl_brl      REAL,
    peak_price   REAL,
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS crypto_signals (
    id             SERIAL PRIMARY KEY,
    symbol         TEXT NOT NULL,
    decision       TEXT NOT NULL,
    ai_score       INTEGER,
    ai_veredicto   TEXT,
    price          REAL,
    rsi_1h         REAL,
    galaxy_score   INTEGER,
    change_pct_24h REAL,
    sentiment      TEXT,
    reasons        TEXT,
    hist_trend     TEXT,
    hist_position  TEXT,
    pct_from_ma200 REAL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signal_cooldowns (
    id       SERIAL PRIMARY KEY,
    ticker   TEXT NOT NULL,
    pipeline TEXT NOT NULL DEFAULT 'b3',
    sent_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crypto_positions (
    id            SERIAL PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS paper_portfolio (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT 'Principal',
    initial_capital REAL NOT NULL DEFAULT 5000.0,
    current_capital REAL NOT NULL DEFAULT 5000.0,
    pipeline        TEXT NOT NULL DEFAULT 'both',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id              SERIAL PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS paper_positions (
    id            SERIAL PRIMARY KEY,
    portfolio_id  INTEGER NOT NULL REFERENCES paper_portfolio(id),
    pipeline      TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    entry_price   REAL NOT NULL,
    quantity      REAL NOT NULL,
    current_price REAL,
    stop_price    REAL,
    status        TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
    opened_at     TEXT NOT NULL,
    closed_at     TEXT,
    pnl           REAL,
    pnl_pct       REAL,
    close_price   REAL,
    close_reason  TEXT
);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
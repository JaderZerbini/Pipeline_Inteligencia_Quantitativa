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
    impact       INTEGER,
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
    ai_impact      INTEGER,
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

-- Resultado posterior de cada sinal — o rotulo para calibrar `impact`.
-- Preenchida retroativamente (preco historico e recuperavel no yfinance).
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id               SERIAL PRIMARY KEY,
    pipeline         TEXT    NOT NULL,
    signal_id        INTEGER NOT NULL,
    symbol           TEXT    NOT NULL,
    horizon_days     INTEGER NOT NULL,
    price_at_signal  REAL,
    price_after      REAL,
    return_pct       REAL,
    computed_at      TEXT    NOT NULL,
    UNIQUE (pipeline, signal_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_lookup
    ON signal_outcomes (pipeline, signal_id);

-- Row Level Security --------------------------------------------------------
-- O Supabase expõe o schema `public` via API REST (PostgREST) usando a chave
-- `anon`, que é pública por design. Sem RLS, qualquer um que conheça o ref do
-- projeto lê e escreve nestas tabelas.
--
-- Nenhuma policy é criada de propósito: sem policy, `anon` e `authenticated`
-- ficam sem acesso algum. O pipeline não é afetado — conecta como `postgres`,
-- que é dono das tabelas e faz bypass de RLS.
--
-- Idempotente e obrigatório para toda tabela nova adicionada acima, senão o
-- advisor do Supabase volta a apontar CRÍTICO.

ALTER TABLE signals          ENABLE ROW LEVEL SECURITY;
ALTER TABLE audits           ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE crypto_signals   ENABLE ROW LEVEL SECURITY;
ALTER TABLE signal_cooldowns ENABLE ROW LEVEL SECURITY;
ALTER TABLE crypto_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_portfolio  ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_trades     ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_positions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE schema_version   ENABLE ROW LEVEL SECURITY;
ALTER TABLE signal_outcomes ENABLE ROW LEVEL SECURITY;
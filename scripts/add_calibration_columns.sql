-- Estrutura para calibrar o eixo `impact` (release 3b).
--
-- Por que este script existe separado do schema-postgres.sql: init_db() no
-- Postgres só roda CREATE TABLE IF NOT EXISTS, que NÃO adiciona coluna em
-- tabela existente. E run_migrations() em core/db.py é código morto (ninguém
-- chama). Então mudança em tabela já criada precisa de ALTER explícito, igual
-- fizemos no enable_rls.sql.
--
-- Aplicar:
--   psql "$DATABASE_URL" -f scripts/add_calibration_columns.sql
--   -- ou cole no SQL Editor do Supabase
--
-- Idempotente: IF NOT EXISTS em tudo. Rodar duas vezes não faz nada na segunda.

-- 1. impact do B3 -----------------------------------------------------------
-- Hoje o impact só existe dentro de audits.raw_response como JSON. Coluna
-- própria para poder agregar (AVG, correlação) sem parsear texto em SQL.
ALTER TABLE audits
    ADD COLUMN IF NOT EXISTS impact INTEGER
    CHECK (impact IS NULL OR impact BETWEEN -100 AND 100);

-- 2. impact do cripto -------------------------------------------------------
-- Fica ao lado de ai_score/ai_veredicto, que já seguem esse padrão.
ALTER TABLE crypto_signals
    ADD COLUMN IF NOT EXISTS ai_impact INTEGER
    CHECK (ai_impact IS NULL OR ai_impact BETWEEN -100 AND 100);

-- 3. O rótulo: o que aconteceu depois ---------------------------------------
-- Nada no sistema registrava isso. paper_trades/paper_positions só ganham
-- linha quando um sinal VIRA COMPRA — e como a maioria dá AGUARDAR, não havia
-- gabarito para avaliar previsão nenhuma.
--
-- Uma linha por (pipeline, sinal, horizonte): o mesmo sinal é medido em 3, 5 e
-- 10 dias, porque "impact previu alta" depende de em quanto tempo.
--
-- Preenchida RETROATIVAMENTE: preço histórico é recuperável no yfinance a
-- qualquer momento, ao contrário de notícia. Por isso não é preciso gravar
-- nada agora — só depois, quando o futuro já aconteceu.
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id               SERIAL PRIMARY KEY,
    pipeline         TEXT    NOT NULL,   -- 'b3' | 'cripto' (convenção de paper_trades)
    signal_id        INTEGER NOT NULL,   -- signals.id ou crypto_signals.id
    symbol           TEXT    NOT NULL,
    horizon_days     INTEGER NOT NULL,
    price_at_signal  REAL,
    price_after      REAL,
    return_pct       REAL,
    computed_at      TEXT    NOT NULL,
    -- Permite recalcular sem duplicar: o script de análise faz upsert.
    UNIQUE (pipeline, signal_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_lookup
    ON signal_outcomes (pipeline, signal_id);

-- 4. RLS na tabela nova -----------------------------------------------------
-- Obrigatório: sem isto o advisor do Supabase volta a apontar CRÍTICO e a
-- tabela fica legível pela API REST via chave anon, que é pública.
ALTER TABLE signal_outcomes ENABLE ROW LEVEL SECURITY;

-- Verificação ---------------------------------------------------------------
SELECT 'audits.impact'            AS objeto,
       count(*)::text             AS presente
  FROM information_schema.columns
 WHERE table_name = 'audits' AND column_name = 'impact'
UNION ALL
SELECT 'crypto_signals.ai_impact', count(*)::text
  FROM information_schema.columns
 WHERE table_name = 'crypto_signals' AND column_name = 'ai_impact'
UNION ALL
SELECT 'signal_outcomes', count(*)::text
  FROM information_schema.tables
 WHERE table_name = 'signal_outcomes'
UNION ALL
SELECT 'signal_outcomes RLS', relrowsecurity::text
  FROM pg_class WHERE relname = 'signal_outcomes';

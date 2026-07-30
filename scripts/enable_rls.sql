-- Ativa Row Level Security (RLS) em todas as tabelas do schema public.
--
-- Por que: o Supabase expõe o schema `public` via API REST (PostgREST) usando a
-- chave `anon`, que é pública por design. Sem RLS, qualquer um que conheça o ref
-- do projeto lê e escreve nessas tabelas.
--
-- Nenhuma policy é criada de propósito. Sem policy, `anon` e `authenticated`
-- ficam sem acesso algum. O pipeline não é afetado: ele conecta via
-- DATABASE_URL como `postgres`, que é dono das tabelas e tem BYPASSRLS.
--
-- Só crie policies se algum dia expor essas tabelas a um cliente
-- (frontend, supabase-js). Hoje isso não acontece em nenhum ponto do código.
--
-- Aplicar:
--   psql "$DATABASE_URL" -f scripts/enable_rls.sql
--   -- ou cole no SQL Editor do Supabase
--
-- Reverter (se algo quebrar):
--   ALTER TABLE public.<tabela> DISABLE ROW LEVEL SECURITY;

ALTER TABLE public.signals          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audits           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.operations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crypto_signals   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.signal_cooldowns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crypto_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paper_portfolio  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paper_trades     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paper_positions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schema_version   ENABLE ROW LEVEL SECURITY;

-- Verificação: relrowsecurity deve ser `t` nas 10 linhas.
SELECT relname, relrowsecurity
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relkind = 'r'
ORDER BY relname;

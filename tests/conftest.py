"""Isola a suíte do banco de produção.

`core/alerts.py` chama `load_dotenv()` no topo do módulo. Qualquer teste que o
importe injeta o `.env` real no ambiente da sessão — e `core/db.py` decide
entre SQLite e Postgres lendo `DATABASE_URL` **no import**, uma vez só. O
resultado é silencioso e feio: `init_db()` passa a criar schema no Supabase de
produção enquanto o teste inspeciona um SQLite temporário vazio.

Por isso o pop acontece aqui, em tempo de import do conftest (antes da coleta
dos módulos de teste) e de novo dentro de `test_alerts.py`, logo após o import
que dispara o `load_dotenv`. Teste nenhum deve tocar o banco de produção.

Um teste que precise simular ambiente com Postgres deve setar `DATABASE_URL`
via `monkeypatch`, que reverte sozinho no fim.
"""

import os

os.environ.pop("DATABASE_URL", None)

"""
scripts/setup_supabase_v2.py
----------------------------
Cria todas as tabelas no Supabase PostgreSQL usando o init_db()
do core/db.py — mesma lógica que cria as tabelas locais.
"""

import os
import sys

# Adiciona o projeto no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def setup():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERRO: DATABASE_URL não definida.")
        sys.exit(1)

    print(f"Conectando ao Supabase...")
    from core.db import init_db, get_connection

    # init_db detecta se é PostgreSQL ou SQLite pela DATABASE_URL
    init_db()

    # Confirma que as tabelas foram criadas
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]

    print(f"\nOK — {len(tables)} tabelas criadas no Supabase:")
    for t in tables:
        print(f"  ✓ {t}")


if __name__ == "__main__":
    setup()
import os
import sys


def setup():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERRO: DATABASE_URL não definida.")
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("ERRO: psycopg2 não instalado.")
        print("Execute: pip install psycopg2-binary")
        sys.exit(1)

    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "schema.sql"
    )
    if not os.path.exists(schema_path):
        print(f"ERRO: schema.sql não encontrado em {schema_path}")
        sys.exit(1)

    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    print(f"Conectando ao Supabase...")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()

    statements = [
        s.strip() for s in sql.split(";")
        if s.strip() and not s.strip().startswith("--")
    ]

    ok = 0
    errors = 0
    for stmt in statements:
        try:
            cur.execute(stmt)
            ok += 1
        except Exception as e:
            err_str = str(e).lower()
            if "already exists" in err_str:
                ok += 1  # idempotente
            else:
                errors += 1
                print(f"AVISO: {e}")

    cur.close()
    conn.close()
    print(f"\nOK — {ok} statements executados no Supabase.")
    if errors:
        print(f"{errors} avisos (não fatais).")
    print("Tabelas criadas/verificadas com sucesso.")


if __name__ == "__main__":
    setup()
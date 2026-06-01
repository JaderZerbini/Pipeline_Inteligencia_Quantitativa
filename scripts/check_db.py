from core.db import get_connection

conn = get_connection()

print("=== ÚLTIMOS SINAIS B3 ===")
rows = conn.execute("""
    SELECT created_at, ticker, signal_type, recommendation, rsi, volume_ratio
    FROM signals
    ORDER BY created_at DESC
    LIMIT 5
""").fetchall()
for r in rows:
    print(f"  {str(r[0])[:16]} | {r[1]} | {r[2]} | {r[3]} | RSI={r[4]}")

print("\n=== ÚLTIMOS SINAIS CRIPTO ===")
rows2 = conn.execute("""
    SELECT created_at, symbol, decision, ai_score
    FROM crypto_signals
    ORDER BY created_at DESC
    LIMIT 5
""").fetchall()
for r in rows2:
    print(f"  {r[0][:16]} | {r[1]} | {r[2]} | score={r[3]}")

print("\n=== PAPER TRADING ===")
rows3 = conn.execute("""
    SELECT pipeline, current_capital, initial_capital
    FROM paper_portfolio
""").fetchall()
for r in rows3:
    print(f"  {r[0]} | capital=R${r[1]:.2f} | inicial=R${r[2]:.2f}")

conn.close()
"""Smoke test for Telegram integration — sends a clearly-labelled test alert."""

from dotenv import load_dotenv
load_dotenv()

from alerts import send_alert

send_alert("""🟢 *SINAL FORTE — TESTE DO SISTEMA*

Ativo: PETR4
Preço: R$ 46.44
RSI: 37.8 (sobrevendido)
Volume: 1.8x acima da média
Score IA: 74 | CONFIAVEL (3/3 modelos)
Macro: Brent +1.2% favorável

⚠️ Este é um TESTE — não é sinal real.
Verifique se esta mensagem chegou no Telegram.""")

print("Mensagem enviada. Verifique o celular.")

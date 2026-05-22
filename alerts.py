import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot

# Carrega as credenciais do .env
load_dotenv()

class TelegramAlert:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.bot = Bot(token=self.token)

    async def enviar_alerta_compra(self, ativo, rsi, veredito):
        msg = (f"🚀 **SINAL DE COMPRA: {ativo}**\n\n"
               f"📈 RSI: {rsi:.2f}\n"
               f"🛡️ AUDITORIA FRANK: \n{veredito}\n\n"
               f"💡 Verifique seu app do Nubank!")
        await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')

    async def enviar_alerta_venda(self, ativo, motivo, preco_atual):
        msg = (f"⚠️ **HORA DE VENDER: {ativo}**\n\n"
               f"📉 Motivo: {motivo}\n"
               f"💰 Preço Atual: R$ {preco_atual:.2f}\n\n"
               f"🔒 Proteja seu capital no Nubank!")
        await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')

    async def _send_raw(self, message: str) -> None:
        await self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode='Markdown')


def send_alert(message: str) -> None:
    """Synchronous convenience wrapper — sends raw Markdown message via Telegram."""
    alert = TelegramAlert()
    asyncio.run(alert._send_raw(message))


# Exemplo de uso rápido para teste
if __name__ == "__main__":
    alert = TelegramAlert()
    asyncio.run(alert.enviar_alerta_compra("TESTE3", 58.5, "CONFIÁVEL - Notícia validada."))
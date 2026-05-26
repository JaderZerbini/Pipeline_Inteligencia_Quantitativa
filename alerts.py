import logging
import os
import asyncio
import threading
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

logger = logging.getLogger(__name__)


class TelegramAlert:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token:
            self._disabled = True
            self.bot = None
        else:
            self._disabled = False
            self.bot = Bot(token=self.token)

    async def enviar_alerta_compra(self, ativo, rsi, veredito):
        if self._disabled:
            return
        msg = (f"🚀 **SINAL DE COMPRA: {ativo}**\n\n"
               f"📈 RSI: {rsi:.2f}\n"
               f"🛡️ AUDITORIA FRANK: \n{veredito}\n\n"
               f"💡 Verifique seu app do Nubank!")
        await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')

    async def enviar_alerta_venda(self, ativo, motivo, preco_atual):
        if self._disabled:
            return
        msg = (f"⚠️ **HORA DE VENDER: {ativo}**\n\n"
               f"📉 Motivo: {motivo}\n"
               f"💰 Preço Atual: R$ {preco_atual:.2f}\n\n"
               f"🔒 Proteja seu capital no Nubank!")
        await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='Markdown')

    async def _send_raw(self, message: str) -> None:
        if self._disabled:
            return
        await self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode='Markdown')


def _run_coroutine_safe(coro) -> None:
    """Run a coroutine safely whether or not an event loop is already running.

    asyncio.run() raises RuntimeError inside Streamlit (loop already running).
    In that case, dispatch to a daemon thread with its own event loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        exc_box: dict = {}
        done = threading.Event()

        def _in_thread():
            try:
                asyncio.run(coro)
            except Exception as e:
                exc_box["error"] = e
            finally:
                done.set()

        threading.Thread(target=_in_thread, daemon=True).start()
        done.wait(timeout=30)
        if "error" in exc_box:
            raise exc_box["error"]
    else:
        asyncio.run(coro)


def send_alert(message: str) -> None:
    """Synchronous wrapper — sends raw Markdown message via Telegram.
    Safe to call from Streamlit or any async context."""
    alert = TelegramAlert()
    if alert._disabled:
        logger.warning("[TELEGRAM] Token não configurado — alerta não enviado")
        return
    _run_coroutine_safe(alert._send_raw(message))


# Exemplo de uso rápido para teste
if __name__ == "__main__":
    alert = TelegramAlert()
    asyncio.run(alert.enviar_alerta_compra("TESTE3", 58.5, "CONFIÁVEL - Notícia validada."))
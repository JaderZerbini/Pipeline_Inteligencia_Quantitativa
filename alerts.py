import asyncio
import concurrent.futures
import logging
import os

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton bot — created once, reused across all send_alert() calls
# ---------------------------------------------------------------------------

_bot: Bot | None = None
_chat_id: str | None = None


def _get_bot() -> tuple[Bot | None, str | None]:
    """Returns singleton (Bot, chat_id), or (None, None) if not configured."""
    global _bot, _chat_id
    if _bot is not None:
        return _bot, _chat_id

    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning(
            "[TELEGRAM] TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configurados — "
            "alertas desabilitados."
        )
        return None, None

    _bot = Bot(token=token)
    _chat_id = chat_id
    return _bot, _chat_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_alert(message: str) -> bool:
    """Send a Markdown message via Telegram. Returns True on success.

    Safe to call from Streamlit (event loop already running) or plain scripts.
    Reuses the same Bot instance across calls to avoid redundant HTTP setup.
    """
    bot, chat_id = _get_bot()
    if bot is None:
        return False

    coro = bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")

    try:
        asyncio.get_running_loop()
        # Inside Streamlit or another async context — dispatch to a new thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            try:
                future.result(timeout=30)
                return True
            except Exception as e:
                logger.error(f"[TELEGRAM] Falha (thread): {e}")
                return False
    except RuntimeError:
        # No running loop — call directly
        try:
            asyncio.run(coro)
            return True
        except TelegramError as e:
            logger.error(f"[TELEGRAM] Falha ao enviar: {e}")
            return False


# ---------------------------------------------------------------------------
# Legacy class kept for backward compatibility (used in main.py + monitor.py)
# ---------------------------------------------------------------------------

class TelegramAlert:
    """Thin wrapper kept for callers that instantiate TelegramAlert directly."""

    def __init__(self):
        self._bot, self._chat_id = _get_bot()
        self._disabled = self._bot is None

    async def enviar_alerta_compra(self, ativo: str, rsi: float, veredito: str) -> None:
        if self._disabled:
            return
        msg = (
            f"🚀 **SINAL DE COMPRA: {ativo}**\n\n"
            f"📈 RSI: {rsi:.2f}\n"
            f"🛡️ AUDITORIA FRANK: \n{veredito}\n\n"
            f"💡 Verifique seu app do Nubank!"
        )
        await self._bot.send_message(chat_id=self._chat_id, text=msg, parse_mode="Markdown")

    async def enviar_alerta_venda(self, ativo: str, motivo: str, preco_atual: float) -> None:
        if self._disabled:
            return
        msg = (
            f"⚠️ **HORA DE VENDER: {ativo}**\n\n"
            f"📉 Motivo: {motivo}\n"
            f"💰 Preço Atual: R$ {preco_atual:.2f}\n\n"
            f"🔒 Proteja seu capital no Nubank!"
        )
        await self._bot.send_message(chat_id=self._chat_id, text=msg, parse_mode="Markdown")


# Exemplo de uso rápido para teste
if __name__ == "__main__":
    ok = send_alert("✅ Teste singleton bot — Terminal Quant")
    print("Enviado:", ok)

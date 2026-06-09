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
    """Send a Markdown message via Telegram. Returns True on success."""
    bot, chat_id = _get_bot()
    if bot is None:
        return False

    chat_ids = [cid.strip() for cid in chat_id.split(",") if cid.strip()]

    async def _send_all():
        for cid in chat_ids:
            await bot.send_message(chat_id=cid, text=message, parse_mode="Markdown")

    try:
        asyncio.get_running_loop()
        # Dentro do Streamlit — despacha para thread separada
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _send_all())
            try:
                future.result(timeout=30)
                return True
            except Exception as e:
                logger.error(f"[TELEGRAM] Falha (thread): {e}")
                return False
    except RuntimeError:
        # Sem loop rodando — chama direto
        try:
            asyncio.run(_send_all())
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
        await self._bot.send_message(chat_id=self._chat_id, text=veredito, parse_mode="Markdown")

    async def enviar_alerta_venda(self, ativo: str, motivo: str, preco_atual: float) -> None:
        if self._disabled:
            return
        msg = (
            f"⚠️ *Hora de vender: {ativo}*\n\n"
            f"Motivo: {motivo}\n"
            f"💰 Preço atual: R$ {preco_atual:.2f}\n\n"
            f"Revise sua posição no seu app de investimentos."
        )
        await self._bot.send_message(chat_id=self._chat_id, text=msg, parse_mode="Markdown")


# Exemplo de uso rápido para teste
if __name__ == "__main__":
    ok = send_alert("✅ Teste singleton bot — Terminal Quant")
    print("Enviado:", ok)

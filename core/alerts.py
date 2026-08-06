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

    try:
        _bot = Bot(token=token)
    except Exception as e:
        # Token malformado levanta na construção. Sem isto a exceção sobe por
        # send_alert() e derruba o pipeline por causa de um alerta.
        logger.error(f"[TELEGRAM] Token inválido — alertas desabilitados: {e}")
        return None, None
    _chat_id = chat_id
    return _bot, _chat_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def _entregar(bot, chat_id_raw: str, message: str) -> list[str]:
    """Envia `message` a cada destinatário de `chat_id_raw`. Devolve quem recebeu.

    `TELEGRAM_CHAT_ID` aceita vários ids separados por vírgula, e cada envio é
    isolado do outro **de propósito**: um destinatário que bloqueou o bot, ou
    cujo id está errado, faz a API levantar. Sem o try por destinatário essa
    exceção aborta o loop e cala todo mundo que vem depois na lista — o alerta
    não chega a ninguém e o único vestígio é uma linha de log.

    Fonte única para `send_alert` e para `TelegramAlert`: enquanto a classe
    tinha o seu próprio envio, ela mandava a lista inteira como um id só.
    """
    entregues: list[str] = []
    for cid in [c.strip() for c in (chat_id_raw or "").split(",") if c.strip()]:
        try:
            await bot.send_message(chat_id=cid, text=message, parse_mode="Markdown")
            entregues.append(cid)
        except Exception as e:
            # Últimos dígitos só: log de CI é público, chat_id identifica pessoa.
            logger.error(f"[TELEGRAM] Falha ao enviar para ...{cid[-4:]}: {e}")
    return entregues


def send_alert(message: str) -> bool:
    """Send a Markdown message via Telegram. Returns True on success.

    Nunca levanta: os pipelines chamam isto no meio do loop de ativos e uma
    falha de rede não pode interromper o ciclo (paper trading e trailing stops
    vêm depois). Falha vira log + retorno False.
    """
    bot, chat_id = _get_bot()
    if bot is None:
        return False

    entregues: list[str] = []

    async def _send_all():
        entregues.extend(await _entregar(bot, chat_id, message))

    try:
        asyncio.get_running_loop()
        # Dentro do Streamlit — despacha para thread separada
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _send_all())
            try:
                future.result(timeout=30)
                return bool(entregues)
            except Exception as e:
                logger.error(f"[TELEGRAM] Falha (thread): {e}")
                return False
    except RuntimeError:
        # Sem loop rodando — chama direto
        try:
            asyncio.run(_send_all())
            # False só quando NINGUÉM recebeu: entrega parcial ainda é entrega,
            # e devolver False faria o chamador tratar como alerta perdido.
            return bool(entregues)
        except TelegramError as e:
            logger.error(f"[TELEGRAM] Falha ao enviar: {e}")
            return False
        except Exception as e:
            # Rede fora, DNS, timeout: capturar só TelegramError deixava a
            # exceção subir e abortar o pipeline no meio do loop de tickers,
            # antes do paper trading e dos trailing stops. Alerta é efeito
            # colateral do ciclo, não pode derrubá-lo.
            logger.error(f"[TELEGRAM] Falha inesperada ao enviar: {e}")
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
        await _entregar(self._bot, self._chat_id, veredito)

    async def enviar_alerta_venda(self, ativo: str, motivo: str, preco_atual: float) -> None:
        if self._disabled:
            return
        msg = (
            f"⚠️ *Hora de vender: {ativo}*\n\n"
            f"Motivo: {motivo}\n"
            f"💰 Preço atual: R$ {preco_atual:.2f}\n\n"
            f"Revise sua posição no seu app de investimentos."
        )
        await _entregar(self._bot, self._chat_id, msg)


# Exemplo de uso rápido para teste
if __name__ == "__main__":
    ok = send_alert("✅ Teste singleton bot — Terminal Quant")
    print("Enviado:", ok)

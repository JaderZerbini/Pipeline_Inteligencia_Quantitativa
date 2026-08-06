"""Tests for core/alerts.py — entrega para mais de um destinatário.

Duas regressões que estes testes fecham, ambas silenciosas em produção:

  1. O loop de envio não isolava destinatário. Quem bloqueou o bot fazia a
     exceção subir e **calava a lista inteira** a partir dele — o alerta
     simplesmente não chegava, com um log como único vestígio.
  2. `TelegramAlert` nunca separou a lista: mandava "111,222" como um chat_id
     só. Com dois destinatários configurados, todo alerta que passa por essa
     classe (compra do main.py, stop do monitor.py) falhava para os dois.

`core.alerts` importa `telegram` e `dotenv`, que não estão em
requirements-ci.txt de propósito. O importorskip mantém o CI verde sem
adicionar dependência — o teste roda local, onde o pipeline já tem tudo.
"""

import asyncio
import os

import pytest

pytest.importorskip("telegram", reason="python-telegram-bot fora do requirements-ci")
pytest.importorskip("dotenv", reason="python-dotenv fora do requirements-ci")

from core import alerts  # noqa: E402

# `core.alerts` roda load_dotenv() no import e acabou de injetar o .env real
# nesta sessão. Sem remover a DATABASE_URL aqui, `core.db` — importado depois,
# na coleta de test_db_schema — resolveria para o Postgres de produção. Ver
# tests/conftest.py.
os.environ.pop("DATABASE_URL", None)

_DOIS = "1110000111,2220000222"


class _BotFalso:
    """Registra quem recebeu; levanta para os chat_ids marcados como ruins."""

    def __init__(self, ruins=()):
        self.ruins = set(ruins)
        self.entregues: list[str] = []

    async def send_message(self, chat_id, text, parse_mode=None):
        if chat_id in self.ruins:
            raise RuntimeError(f"Chat not found: {chat_id}")
        self.entregues.append(chat_id)


@pytest.fixture
def bot_bom(monkeypatch):
    bot = _BotFalso()
    monkeypatch.setattr(alerts, "_get_bot", lambda: (bot, _DOIS))
    return bot


@pytest.fixture
def bot_primeiro_ruim(monkeypatch):
    bot = _BotFalso(ruins=["1110000111"])
    monkeypatch.setattr(alerts, "_get_bot", lambda: (bot, _DOIS))
    return bot


# ---------------------------------------------------------------------------
# send_alert — caminho usado pelos scanners
# ---------------------------------------------------------------------------

def test_send_alert_entrega_para_todos(bot_bom):
    assert alerts.send_alert("oi") is True
    assert bot_bom.entregues == ["1110000111", "2220000222"]


def test_destinatario_que_falha_nao_cala_os_outros(bot_primeiro_ruim):
    """O bug do Davi: ele bloqueou o bot e o Jader parou de receber junto."""
    assert alerts.send_alert("oi") is True
    assert bot_primeiro_ruim.entregues == ["2220000222"]


def test_send_alert_e_falso_quando_ninguem_recebe(monkeypatch):
    bot = _BotFalso(ruins=["1110000111", "2220000222"])
    monkeypatch.setattr(alerts, "_get_bot", lambda: (bot, _DOIS))

    assert alerts.send_alert("oi") is False
    assert bot.entregues == []


def test_send_alert_sem_bot_configurado(monkeypatch):
    monkeypatch.setattr(alerts, "_get_bot", lambda: (None, None))
    assert alerts.send_alert("oi") is False


# ---------------------------------------------------------------------------
# TelegramAlert — caminho usado por main.py e monitor.py
# ---------------------------------------------------------------------------

def test_alerta_de_compra_chega_aos_dois(bot_bom):
    a = alerts.TelegramAlert()
    asyncio.run(a.enviar_alerta_compra("PETR4", 60.0, "COMPRA FORTE"))
    assert bot_bom.entregues == ["1110000111", "2220000222"]


def test_alerta_de_venda_chega_aos_dois(bot_bom):
    a = alerts.TelegramAlert()
    asyncio.run(a.enviar_alerta_venda("PETR4", "trailing stop", 30.0))
    assert bot_bom.entregues == ["1110000111", "2220000222"]


def test_alerta_de_venda_sobrevive_a_destinatario_ruim(bot_primeiro_ruim):
    """Alerta de stop é o mais crítico: não pode sumir por causa de um id."""
    a = alerts.TelegramAlert()
    asyncio.run(a.enviar_alerta_venda("PETR4", "trailing stop", 30.0))
    assert bot_primeiro_ruim.entregues == ["2220000222"]

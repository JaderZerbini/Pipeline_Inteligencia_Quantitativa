"""Testes da flag do pré-gate (core/settings.py — só stdlib).

O pré-gate economiza chamadas de IA, mas estrangula a coleta de dados: com ele
ligado a IA só roda em sinais tecnicamente favoráveis, gerando amostra pequena
e enviesada. Estes testes travam que a chave existe, que o padrão é economizar,
e que desligar é possível sem remover código.
"""

import pytest

from core.settings import ai_pregate_enabled

_VAR = "AI_PREGATE"


def test_ligado_por_padrao_sem_variavel(monkeypatch):
    """Ausência da variável = economia. O default não pode custar dinheiro."""
    monkeypatch.delenv(_VAR, raising=False)
    assert ai_pregate_enabled() is True


@pytest.mark.parametrize("valor", ["off", "OFF", "0", "false", "no", "nao", " off "])
def test_desliga_com_valores_negativos(valor, monkeypatch):
    monkeypatch.setenv(_VAR, valor)
    assert ai_pregate_enabled() is False


@pytest.mark.parametrize("valor", ["on", "ON", "1", "true", "yes", "sim"])
def test_liga_com_valores_positivos(valor, monkeypatch):
    monkeypatch.setenv(_VAR, valor)
    assert ai_pregate_enabled() is True


def test_valor_invalido_cai_no_padrao(monkeypatch):
    """Typo não pode desligar a economia por acidente."""
    monkeypatch.setenv(_VAR, "talvez")
    assert ai_pregate_enabled() is True


def test_string_vazia_cai_no_padrao(monkeypatch):
    """Secret vazio no Actions não deve mudar comportamento."""
    monkeypatch.setenv(_VAR, "   ")
    assert ai_pregate_enabled() is True

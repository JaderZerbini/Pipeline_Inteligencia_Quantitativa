"""Testes da detecção de cotação velha (só stdlib)."""

from datetime import date, datetime

from b3.freshness import is_stale

_PREGAO = datetime(2026, 8, 5, 14, 30)   # quarta, dentro do horário


def test_vela_de_hoje_durante_o_pregao_e_fresca():
    assert is_stale(date(2026, 8, 5), _PREGAO, market_open=True) is False


def test_vela_de_ontem_durante_o_pregao_e_velha():
    """Sintoma típico de feriado da B3 — o yfinance repete o último pregão."""
    assert is_stale(date(2026, 8, 4), _PREGAO, market_open=True) is True


def test_com_mercado_fechado_dado_antigo_e_esperado():
    """Fora do pregão o último fechamento é a informação correta."""
    fim_de_semana = datetime(2026, 8, 8, 10, 0)
    assert is_stale(date(2026, 8, 7), fim_de_semana, market_open=False) is False


def test_sem_data_e_tratado_como_velho():
    assert is_stale(None, _PREGAO, market_open=True) is True

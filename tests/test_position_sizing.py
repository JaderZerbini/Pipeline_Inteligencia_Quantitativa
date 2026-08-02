"""Testes do dimensionamento de posição (só stdlib).

Cripto é divisível — 0,0134 BTC é uma ordem real. Ação da B3 não: o paper
trading comprava 12,345678 PETR4 e o resultado simulado deixava de
corresponder a qualquer ordem executável.
"""

import pytest

from core.position_sizing import MAX_POSITIONS, calculate_position


def test_cripto_mantem_fracao():
    r = calculate_position("FORTE", capital=1000.0, open_positions=0, price=50000.0)
    assert r["allowed"] is True
    assert r["units"] == pytest.approx(0.004)


def test_b3_arredonda_para_acoes_inteiras():
    r = calculate_position(
        "MODERADO", capital=5000.0, open_positions=0, price=40.0, whole_units=True
    )
    assert r["units"] == 12                      # 500 / 40 = 12,5 -> 12
    assert r["alloc_value"] == pytest.approx(480.0)   # caixa debita o que foi comprado


def test_b3_recusa_quando_nao_cabe_uma_acao():
    """Alocação menor que o preço de uma ação não vira posição de 0 unidades."""
    r = calculate_position(
        "MODERADO", capital=1000.0, open_positions=0, price=250.0, whole_units=True
    )
    assert r["allowed"] is False
    assert r["units"] == 0


def test_limite_de_posicoes_abertas_continua_valendo():
    r = calculate_position("FORTE", 5000.0, MAX_POSITIONS, 40.0)
    assert r["allowed"] is False


def test_decisao_nao_acionavel_nao_aloca():
    r = calculate_position("AGUARDAR", 5000.0, 0, 40.0)
    assert r["allowed"] is False

"""Tests for b3/monitor.py — a saída que roda em produção.

O que estes testes protegem: o preço que o painel mostra como stop tem que ser
exatamente o preço em que o monitor vende. Enquanto os dois calculavam o seu
próprio número, o painel exibia `entrada * 0.93` congelado na compra e o
monitor vendia 7% abaixo do topo — na mesma posição, com lucro, os dois
discordavam.
"""

import pytest

from b3.monitor import TRAILING_STOP_PCT, check_trailing_stop, nivel_stop

_ENTRADA = 100.0


def _checar(preco_atual: float, pico: float):
    return check_trailing_stop("PETR4", _ENTRADA, preco_atual, pico)


# ---------------------------------------------------------------------------
# nivel_stop — o número que o painel mostra
# ---------------------------------------------------------------------------

def test_nivel_na_entrada_e_stop_fixo_de_7_porcento():
    """Enquanto o papel não sobe, o trailing é um stop fixo de -7%."""
    assert nivel_stop(_ENTRADA) == pytest.approx(93.0)


def test_nivel_sobe_junto_com_o_topo():
    """Foi a 114 e o piso subiu para o lucro — é o que o painel congelado escondia."""
    assert nivel_stop(114.0) == pytest.approx(106.02)
    assert nivel_stop(114.0) > _ENTRADA


def test_constante_bate_com_o_backtest():
    """`_STOP_LOSS` do backtester mede a mesma régua; divergir invalida o estudo."""
    from b3.backtester import _STOP_LOSS

    assert TRAILING_STOP_PCT == _STOP_LOSS


# ---------------------------------------------------------------------------
# check_trailing_stop — a decisão de venda
# ---------------------------------------------------------------------------

def test_vende_exatamente_no_nivel_que_o_painel_mostra():
    """O teste que amarra os dois: no preço exibido, a venda dispara.

    Sem fonte única, `preco/pico` e `pico*0.93` divergem no último bit e o
    monitor segura a posição no número que o painel prometeu.
    """
    pico = 114.0
    vender, _ = _checar(nivel_stop(pico), pico)
    assert vender


def test_segura_um_centavo_acima_do_nivel():
    pico = 114.0
    vender, _ = _checar(nivel_stop(pico) + 0.01, pico)
    assert not vender


def test_atualiza_o_topo_quando_o_preco_faz_maxima_nova():
    vender, novo_pico = _checar(120.0, 114.0)
    assert not vender
    assert novo_pico == 120.0


def test_topo_novo_nao_dispara_venda_no_mesmo_ciclo():
    """Preço subindo nunca vende: o nível é recalculado sobre o topo novo."""
    vender, novo_pico = _checar(500.0, 100.0)
    assert not vender
    assert novo_pico == 500.0


def test_preserva_o_topo_quando_o_preco_cai_sem_disparar():
    vender, novo_pico = _checar(110.0, 114.0)
    assert not vender
    assert novo_pico == 114.0


def test_vende_com_lucro_quando_o_papel_devolve_o_topo():
    """A razão de existir do trailing: sai em 106, não espera voltar a 93."""
    vender, _ = _checar(105.0, 114.0)
    assert vender


def test_queda_de_7_porcento_da_entrada_vende_no_primeiro_dia():
    vender, _ = _checar(93.0, _ENTRADA)
    assert vender

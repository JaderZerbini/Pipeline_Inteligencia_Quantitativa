"""Tests for b3/exit_rules.py — modelos de saída do backtester.

Regras (fonte da verdade):
  no_fechamento : compara TP/SL só contra o fechamento; sai no fechamento
  intradiaria   : abertura além do nível -> sai na abertura (gap)
                  mínima tocou stop      -> sai no nível do stop
                  máxima tocou alvo      -> sai no nível do alvo
                  tocou os dois          -> assume STOP (conservador)
"""

import pytest

from b3.exit_rules import intradiaria, no_fechamento, trailing_producao

_TP = 0.15
_SL = 0.07
_ENTRADA = 100.0


def _no_fechamento(abertura=100.0, maxima=101.0, minima=99.0, fechamento=100.0, pico=_ENTRADA):
    return no_fechamento(_ENTRADA, pico, abertura, maxima, minima, fechamento, _TP, _SL)


def _intradiaria(abertura=100.0, maxima=101.0, minima=99.0, fechamento=100.0, pico=_ENTRADA):
    return intradiaria(_ENTRADA, pico, abertura, maxima, minima, fechamento, _TP, _SL)


# ---------------------------------------------------------------------------
# no_fechamento — modelo original
# ---------------------------------------------------------------------------

def test_fechamento_nao_sai_dentro_da_faixa():
    assert _no_fechamento(fechamento=105.0) is None


def test_fechamento_sai_no_alvo():
    s = _no_fechamento(fechamento=115.0)
    assert s.motivo == "take_profit"
    assert s.preco == 115.0


def test_fechamento_ignora_o_que_aconteceu_durante_o_pregao():
    """Mínima furou o stop mas recuperou: o modelo antigo não sai.

    É a diferença central entre os dois modelos.
    """
    assert _no_fechamento(minima=80.0, fechamento=100.0) is None


def test_fechamento_perde_muito_mais_que_o_stop():
    """O prejuízo não tem piso: sai no fechamento, onde quer que ele esteja."""
    s = _no_fechamento(abertura=75.0, maxima=76.0, minima=70.0, fechamento=72.0)
    assert s.motivo == "stop"
    assert s.preco == 72.0   # -28%, não -7%


# ---------------------------------------------------------------------------
# intradiaria — ordem stop de verdade
# ---------------------------------------------------------------------------

def test_intradiaria_nao_sai_dentro_da_faixa():
    assert _intradiaria(maxima=110.0, minima=95.0) is None


def test_intradiaria_sai_no_nivel_do_stop():
    s = _intradiaria(minima=90.0, fechamento=91.0)
    assert s.motivo == "stop"
    assert s.preco == 93.0   # nível exato, não a mínima nem o fechamento


def test_intradiaria_sai_no_nivel_do_alvo():
    s = _intradiaria(maxima=120.0, fechamento=118.0)
    assert s.motivo == "take_profit"
    assert s.preco == pytest.approx(115.0)


def test_intradiaria_sai_mesmo_que_recupere_no_fechamento():
    """Ordem stop não espera o fim do pregão — este é o custo do modelo."""
    s = _intradiaria(minima=90.0, fechamento=100.0)
    assert s.motivo == "stop"


def test_gap_de_baixa_executa_na_abertura():
    """O que o stop não protege: preço saltou o nível com o mercado fechado."""
    s = _intradiaria(abertura=85.0, maxima=86.0, minima=84.0, fechamento=85.0)
    assert s.motivo == "gap_baixa"
    assert s.preco == 85.0   # pior que os 93.0 pedidos


def test_gap_de_alta_executa_na_abertura():
    """Simetria: gap favorável também sai fora do nível, para cima."""
    s = _intradiaria(abertura=120.0, maxima=122.0, minima=119.0, fechamento=121.0)
    assert s.motivo == "gap_alta"
    assert s.preco == 120.0


def test_gap_tem_prioridade_sobre_o_resto_do_candle():
    """Abriu em gap de baixa e depois subiu até o alvo: vale a abertura.

    A posição já foi liquidada na abertura; o que o papel fez depois é
    irrelevante para quem estava dentro.
    """
    s = _intradiaria(abertura=85.0, maxima=130.0, minima=84.0, fechamento=125.0)
    assert s.motivo == "gap_baixa"
    assert s.preco == 85.0


def test_candle_que_toca_os_dois_niveis_assume_stop():
    """Sem dado intradiário não dá para saber a ordem — assume o pior.

    Supor o alvo aqui transformaria perda em ganho usando informação que o
    dado diário não contém.
    """
    s = _intradiaria(abertura=100.0, maxima=120.0, minima=90.0, fechamento=110.0)
    assert s.motivo == "stop"
    assert s.preco == 93.0


def test_toque_exato_no_nivel_conta_como_disparo():
    assert _intradiaria(minima=93.0).motivo == "stop"
    assert _intradiaria(maxima=115.0).motivo == "take_profit"


# ---------------------------------------------------------------------------
# Comparação entre os modelos
# ---------------------------------------------------------------------------

def test_intradiaria_limita_a_perda_que_o_fechamento_deixa_correr():
    """Mesmo candle, prejuízos muito diferentes — é o achado do estudo de gap."""
    candle = dict(abertura=99.0, maxima=99.5, minima=70.0, fechamento=75.0)

    antigo = _no_fechamento(**candle)
    novo = _intradiaria(**candle)

    assert antigo.preco == 75.0   # -25%
    assert novo.preco == 93.0     # -7%, o stop funcionou
    assert novo.preco > antigo.preco


# ---------------------------------------------------------------------------
# trailing_producao — a saída que b3/monitor.py realmente executa
# ---------------------------------------------------------------------------

def _trailing(abertura=100.0, maxima=101.0, minima=99.0, fechamento=100.0, pico=_ENTRADA):
    return trailing_producao(_ENTRADA, pico, abertura, maxima, minima, fechamento, _TP, _SL)


def test_trailing_nao_tem_take_profit():
    """Produção não tem alvo: subiu 50% e continua dentro."""
    assert _trailing(abertura=145.0, maxima=152.0, minima=144.0, fechamento=150.0) is None


def test_trailing_dispara_a_7_porcento_do_topo():
    """Topo em 200: sai em 186, mesmo estando muito acima da entrada."""
    s = _trailing(pico=200.0, abertura=190.0, maxima=191.0, minima=185.0, fechamento=187.0)
    assert s.motivo == "stop"
    assert s.preco == pytest.approx(186.0)


def test_trailing_protege_lucro_que_o_stop_fixo_deixaria_evaporar():
    """Diferença central: stop fixo mede da entrada, trailing mede do topo.

    Papel foi de 100 a 200 e devolveu para 186. O stop fixo está em 93 e só
    dispararia depois de devolver todo o lucro e mais 7%; o trailing sai em
    186, preservando o ganho.
    """
    movel = _trailing(pico=200.0, abertura=190.0, maxima=191.0,
                      minima=185.0, fechamento=187.0)

    assert movel is not None
    assert movel.preco == pytest.approx(186.0)
    # O nível do stop fixo continua lá embaixo, intocado.
    assert _ENTRADA * (1 - _SL) == pytest.approx(93.0)
    assert movel.preco > _ENTRADA * (1 - _SL)


def test_trailing_com_pico_na_entrada_equivale_a_stop_fixo():
    """Enquanto o papel não sobe, o trailing é o stop fixo de -7%."""
    s = _trailing(minima=90.0, fechamento=91.0)
    assert s.motivo == "stop"
    assert s.preco == pytest.approx(93.0)


def test_trailing_tambem_sofre_gap():
    s = _trailing(pico=200.0, abertura=170.0, maxima=171.0, minima=169.0, fechamento=170.0)
    assert s.motivo == "gap_baixa"
    assert s.preco == 170.0   # abaixo dos 186 pedidos


def test_trailing_nao_sai_com_queda_menor_que_o_limite():
    """Caiu 5% do topo: segura."""
    assert _trailing(pico=100.0, abertura=96.0, maxima=97.0, minima=95.0,
                     fechamento=96.0) is None

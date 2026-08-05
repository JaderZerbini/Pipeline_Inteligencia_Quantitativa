"""Tests for b3/entry_rules.py — regras de entrada isoladas para backtest.

Valores esperados vêm das REGRAS DOCUMENTADAS, não da saída do código.

Regras (fonte da verdade):
  momentum          : price > ema20 AND 55 < rsi < 68   <- régua de produção
  reversao_moderado : rsi < 38 AND volume_ratio > 1.2   <- base de comparação

Nenhuma delas inclui o gate de score da IA — o backtest não simula auditoria.
"""

from b3.entry_rules import Candle, momentum, reversao_moderado


def _c(rsi=50.0, volume_ratio=1.0, price=10.0, ema20=10.0):
    return Candle(price=price, rsi=rsi, volume_ratio=volume_ratio, ema20=ema20)


# ---------------------------------------------------------------------------
# momentum — espelha a condição de entrada de scanner.py e o gate de decision.py
# ---------------------------------------------------------------------------

def test_momentum_aceita_preco_acima_da_ema_na_faixa():
    assert momentum(_c(rsi=60.0, price=11.0, ema20=10.0)) is True


def test_momentum_recusa_preco_abaixo_da_ema():
    assert momentum(_c(rsi=60.0, price=9.0, ema20=10.0)) is False


def test_momentum_recusa_faixa_esticada():
    """Acima de 68 o movimento já esticou — a tese é entrar antes disso."""
    assert momentum(_c(rsi=68.0, price=11.0, ema20=10.0)) is False


def test_momentum_recusa_abaixo_da_faixa():
    """A faixa é aberta: 55 exato não entra."""
    assert momentum(_c(rsi=55.0, price=11.0, ema20=10.0)) is False


def test_momentum_ignora_volume():
    """A regra do scanner não olha volume — só EMA e faixa de RSI.

    O gate de produção acrescenta volume por cima; a tese em si não usa.
    """
    assert momentum(_c(rsi=60.0, price=11.0, ema20=10.0, volume_ratio=0.1)) is True


def test_momentum_sem_ema_nao_entra():
    """Sem EMA-20 não dá para saber se o preço está acima dela: não entra.

    Conservador por padrão — dado faltando nunca vira posição.
    """
    assert momentum(_c(rsi=60.0, price=11.0, ema20=None)) is False


# ---------------------------------------------------------------------------
# reversao_moderado — a régua anterior, mantida como base de comparação
# ---------------------------------------------------------------------------

def test_reversao_aceita_sobrevendido_com_volume():
    assert reversao_moderado(_c(rsi=37.9, volume_ratio=1.21)) is True


def test_reversao_recusa_rsi_no_limite():
    """Gate é `rsi < 38`, não `<=` — o limite exato reprova."""
    assert reversao_moderado(_c(rsi=38.0, volume_ratio=2.0)) is False


def test_reversao_recusa_volume_no_limite():
    assert reversao_moderado(_c(rsi=20.0, volume_ratio=1.2)) is False


def test_reversao_exige_as_duas_condicoes():
    """Gates são conjuntivos: RSI ótimo com volume fraco não entra."""
    assert reversao_moderado(_c(rsi=15.0, volume_ratio=0.8)) is False


# ---------------------------------------------------------------------------
# As duas teses são disjuntas — foi o bug que originou todo este trabalho
# ---------------------------------------------------------------------------

def test_nenhuma_vela_satisfaz_as_duas_regras():
    """RSI < 38 e RSI > 55 é conjunto vazio.

    Enquanto o scanner emitia uma faixa e a decisão aprovava a outra, nenhum
    sinal podia virar compra — 60 sinais, 100% AGUARDAR em produção. Este teste
    trava a premissa: não existe 'sinal que passa nas duas', então mesclar por
    AND é impossível por construção.
    """
    for rsi in [10.0, 25.0, 37.0, 45.0, 56.0, 67.0, 80.0]:
        vela = _c(rsi=rsi, volume_ratio=2.0, price=11.0, ema20=10.0)
        assert not (reversao_moderado(vela) and momentum(vela))


# ---------------------------------------------------------------------------
# Direção da dependência dos thresholds
# ---------------------------------------------------------------------------

def test_decisao_usa_a_faixa_deste_modulo():
    """Este módulo é a fonte única dos thresholds; decision.py só importa.

    Uma cópia em decision.py foi exatamente o que deixou as duas pontas
    divergirem — o teste trava a direção da dependência.
    """
    import b3.decision as decision
    from b3.entry_rules import RSI_ENTRY_MAX, RSI_ENTRY_MIN

    assert decision.RSI_ENTRY_MIN is RSI_ENTRY_MIN
    assert decision.RSI_ENTRY_MAX is RSI_ENTRY_MAX


def test_faixa_de_momentum_e_a_que_o_scanner_emite():
    from b3.entry_rules import RSI_ENTRY_MAX, RSI_ENTRY_MIN

    assert (RSI_ENTRY_MIN, RSI_ENTRY_MAX) == (55, 68)

"""Testes da construção de prompts (core/prompts.py — só stdlib).

O objetivo do prompt do B3 mudou: antes a IA recebia apenas ticker + manchete e
julgava a notícia no vácuo. Agora recebe também os indicadores técnicos, para
poder dizer se a manchete CONFIRMA, CONTRADIZ ou é IRRELEVANTE frente ao que os
números mostram. Estes testes travam esse contrato.
"""

import pytest

from core.prompts import build_b3_audit_prompt


HEADLINE = "Petrobras anuncia aumento de dividendos acima do esperado"
TICKER = "PETR4"

INDICATORS = {
    "price": 42.0,
    "rsi": 58.54,
    "volume_ratio": 1.06,
    "pct_from_ma200": 12.41,
    "hist_trend": "downtrend",
}


# --- Compatibilidade: sem indicadores o prompt segue como antes -------------

def test_sem_indicadores_mantem_manchete_e_ticker():
    p = build_b3_audit_prompt(HEADLINE, TICKER)
    assert HEADLINE in p
    assert TICKER in p


def test_sem_indicadores_nao_injeta_bloco_tecnico():
    """validator.py chama sem indicadores — não deve ganhar bloco vazio/N/A."""
    p = build_b3_audit_prompt(HEADLINE, TICKER)
    assert "Indicadores" not in p
    assert "N/A" not in p


# --- Com indicadores: os números precisam chegar à IA ----------------------

def test_indicadores_aparecem_no_prompt():
    p = build_b3_audit_prompt(HEADLINE, TICKER, INDICATORS)
    assert "58.5" in p            # RSI
    assert "1.06" in p            # volume_ratio
    assert "12.4" in p            # pct_from_ma200
    assert "downtrend" in p       # tendência


def test_pede_relacao_entre_manchete_e_numeros():
    """O ganho está em pedir a relação, não só despejar os números."""
    p = build_b3_audit_prompt(HEADLINE, TICKER, INDICATORS).lower()
    assert "confirma" in p
    assert "contradiz" in p


def test_indicadores_parciais_nao_quebram():
    """Scanner pode não ter MA200 para ticker novo — não pode dar KeyError."""
    p = build_b3_audit_prompt(HEADLINE, TICKER, {"rsi": 30.0})
    assert "30.0" in p
    assert "N/A" in p             # campos ausentes viram N/A explícito


def test_indicadores_vazios_tratados_como_ausentes():
    p = build_b3_audit_prompt(HEADLINE, TICKER, {})
    assert "Indicadores" not in p


# --- Contrato de saída JSON preservado ------------------------------------

@pytest.mark.parametrize("campo", [
    "score", "verdict", "reason", "commodity_risk", "flags",
])
def test_contrato_json_preservado(campo):
    """b3/decision.py depende dessas chaves — o prompt deve continuar pedindo."""
    p = build_b3_audit_prompt(HEADLINE, TICKER, INDICATORS)
    assert campo in p


@pytest.mark.parametrize("veredicto", ["CONFIAVEL", "RUIDO", "MANIPULACAO"])
def test_veredictos_preservados(veredicto):
    p = build_b3_audit_prompt(HEADLINE, TICKER, INDICATORS)
    assert veredicto in p


def test_mantem_instrucao_de_impactos_indiretos():
    """Guerra→commodity→margem era a instrução mais valiosa do prompt antigo."""
    p = build_b3_audit_prompt(HEADLINE, TICKER, INDICATORS).lower()
    assert "indireto" in p


# --- Guard: indicador ruim não pode virar MANIPULACAO ---------------------

def test_isola_manipulacao_de_timing_desfavoravel():
    """Regressão observada: com indicadores injetados, notícia boa em ativo
    esticado voltava verdict=MANIPULACAO (score 25). Isso dispara BLOQUEADO
    incondicional em b3/decision.py — irreversível. O prompt precisa dizer
    explicitamente que timing técnico ruim afeta o score, nunca o verdict.
    """
    p = build_b3_audit_prompt(HEADLINE, TICKER, INDICATORS)
    assert "MANIPULACAO" in p
    low = p.lower()
    assert "credibilidade" in low
    # a instrução de não usar MANIPULACAO para timing precisa estar presente
    assert "nunca" in low


def test_guard_ausente_quando_nao_ha_indicadores():
    """Sem indicadores não existe risco de confundir timing com manipulação."""
    p = build_b3_audit_prompt(HEADLINE, TICKER).lower()
    assert "nunca" not in p

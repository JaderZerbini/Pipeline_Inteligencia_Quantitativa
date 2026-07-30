"""Testes da construção de prompts (core/prompts.py — só stdlib).

O objetivo do prompt do B3 mudou: antes a IA recebia apenas ticker + manchete e
julgava a notícia no vácuo. Agora recebe também os indicadores técnicos, para
poder dizer se a manchete CONFIRMA, CONTRADIZ ou é IRRELEVANTE frente ao que os
números mostram. Estes testes travam esse contrato.
"""

import pytest

from core.prompts import build_b3_audit_prompt, build_crypto_audit_prompt


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


# ===========================================================================
# Cripto — o prompt era puramente numerico: nenhuma noticia, nenhum macro.
# ===========================================================================

SIGNAL = {
    "symbol": "BTCUSDT",
    "price": 63974.89,
    "change_pct_24h": -0.52,
    "rsi_1h": 40.62,
    "galaxy_score": 51,
    "social_volume_24h": 0,
    "sentiment": "neutral",
}

CRYPTO_NEWS = (
    "MANCHETES RECENTES: ETF de Bitcoin registra entrada recorde | "
    "Fed sinaliza corte de juros em setembro"
)

CRYPTO_MACRO = {
    "dxy": {"price": 103.4, "change_pct": -0.6},
    "gold": {"price": 2410.0, "change_pct": 0.3},
    "spx": {"price": 5620.0, "change_pct": 0.8},
}


def test_cripto_preserva_campos_numericos():
    """Os 6 campos que já iam para a IA não podem desaparecer."""
    p = build_crypto_audit_prompt(SIGNAL)
    assert "BTCUSDT" in p
    assert "63,974.89" in p or "63974.89" in p
    assert "-0.52" in p
    assert "40.62" in p
    assert "51" in p
    assert "neutral" in p


def test_cripto_sem_noticias_nem_macro_nao_injeta_blocos():
    p = build_crypto_audit_prompt(SIGNAL)
    assert "MANCHETES" not in p
    assert "Contexto macro" not in p


def test_cripto_injeta_noticias():
    p = build_crypto_audit_prompt(SIGNAL, news=CRYPTO_NEWS)
    assert "ETF de Bitcoin" in p
    assert "Fed sinaliza" in p


def test_cripto_injeta_macro():
    p = build_crypto_audit_prompt(SIGNAL, macro=CRYPTO_MACRO)
    assert "103.4" in p          # DXY
    assert "-0.6" in p           # variação do DXY
    assert "spx" in p.lower() or "S&P" in p


def test_cripto_pede_relacao_noticia_versus_numeros():
    p = build_crypto_audit_prompt(SIGNAL, news=CRYPTO_NEWS).lower()
    assert "confirma" in p
    assert "contradiz" in p


def test_cripto_mantem_guard_de_volume_social_zero():
    """Guard antigo e valioso: volume social zero != manipulação."""
    p = build_crypto_audit_prompt(SIGNAL)
    assert "não é evidência de manipulação" in p.lower() or "nao e evidencia" in p.lower()


def test_cripto_isola_manipulacao_de_timing():
    """Mesma regressão do B3: MANIPULACAO dispara BLOQUEADO irrevogável."""
    p = build_crypto_audit_prompt(SIGNAL, news=CRYPTO_NEWS, macro=CRYPTO_MACRO)
    low = p.lower()
    assert "nunca" in low
    assert "credibilidade" in low


@pytest.mark.parametrize("veredicto", [
    "CONFIAVEL", "RUIDO", "MANIPULACAO", "PUMP", "FUD_COORDENADO",
])
def test_cripto_veredictos_preservados(veredicto):
    """crypto/decision.py bloqueia em MANIPULACAO/PUMP/FUD_COORDENADO."""
    p = build_crypto_audit_prompt(SIGNAL, news=CRYPTO_NEWS)
    assert veredicto in p


def test_cripto_contrato_json_preservado():
    p = build_crypto_audit_prompt(SIGNAL)
    for campo in ("score", "verdict", "reason", "flags"):
        assert campo in p


def test_cripto_campos_ausentes_nao_quebram():
    """Scanner pode falhar no galaxy/RSI — não pode dar KeyError."""
    p = build_crypto_audit_prompt({"symbol": "SOLUSDT", "price": 73.5})
    assert "SOLUSDT" in p
    assert "N/A" in p


# ===========================================================================
# Release 3a: campo `impact` — direcional, coletado sem ser consumido
# ===========================================================================
#
# O `score` responde "esse sinal e confiavel?". Nao existe canal para "essa
# noticia e altista ou baixista?", entao noticia boa nao consegue virar score
# alto. `impact` abre esse eixo. Nesta etapa ele e apenas COLETADO — nenhum
# gate le o valor — para haver dados reais antes de calibrar threshold.

def test_b3_pede_impact_no_contrato():
    """Assertar a chave JSON entre aspas: o prompt do B3 ja contem a palavra
    'impacto' em prosa, entao `"impact" in p` passaria por acidente."""
    p = build_b3_audit_prompt(HEADLINE, TICKER, INDICATORS)
    assert '"impact"' in p


def test_cripto_pede_impact_no_contrato():
    p = build_crypto_audit_prompt(SIGNAL, news=CRYPTO_NEWS)
    assert '"impact"' in p


@pytest.mark.parametrize("builder,args", [
    (build_b3_audit_prompt, (HEADLINE, TICKER, INDICATORS)),
    (build_crypto_audit_prompt, (SIGNAL,)),
])
def test_impact_tem_escala_explicita_e_bidirecional(builder, args):
    """A escala precisa deixar claro que negativo = baixista.

    Sem isso o modelo devolve 0-100 como o score e os dois eixos colapsam de
    novo — que e exatamente o problema que `impact` existe para resolver.
    """
    p = builder(*args)
    assert "-100" in p
    assert "+100" in p or "100" in p


@pytest.mark.parametrize("builder,args", [
    (build_b3_audit_prompt, (HEADLINE, TICKER, INDICATORS)),
    (build_crypto_audit_prompt, (SIGNAL,)),
])
def test_impact_separado_de_credibilidade(builder, args):
    """O prompt deve dizer que impact NAO mede credibilidade."""
    p = builder(*args)
    assert '"impact"' in p
    assert "credibilidade" in p.lower()

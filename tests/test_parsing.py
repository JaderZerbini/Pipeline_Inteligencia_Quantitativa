"""Tests for core/parsing.py — parser tolerante de JSON dos LLMs.

Valores esperados derivados das REGRAS do parser, não da saída do código.

Regressões cobertas (falhas reais vistas em produção no consenso):
  qwen  -> JSONDecodeError "Extra data"          : JSON válido + lixo depois
  qwen  -> JSONDecodeError "Invalid control char" : quebra de linha crua na string
  llama -> AttributeError 'NoneType'.strip()      : content == None

Regras (fonte da verdade):
  extract_json_object(text):
    - retorna o PRIMEIRO objeto JSON, ignorando prosa antes e lixo depois
    - aceita caractere de controle cru dentro de string (strict=False)
    - None / vazio / sem '{' -> ValueError
  parse_audit_json(text):
    - exige os campos {score, verdict, reason, flags}, senão ValueError
    - score é inteiro forçado ao intervalo [0, 100]
    - commodity_risk ausente -> "BAIXO"
"""

import pytest

from core.parsing import extract_json_object, parse_audit_json

_BASE = '{"score": 80, "verdict": "CONFIAVEL", "reason": "ok", "flags": []}'


# ---------------------------------------------------------------------------
# extract_json_object — recuperação de respostas malformadas
# ---------------------------------------------------------------------------

def test_extra_data_pega_primeiro_objeto():
    # Regressão qwen "Extra data": segundo objeto após o válido é ignorado.
    assert extract_json_object(_BASE + '\n{"lixo": 1}')["verdict"] == "CONFIAVEL"


def test_texto_depois_do_objeto_e_ignorado():
    assert extract_json_object(_BASE + " Espero ter ajudado!")["score"] == 80


def test_prosa_antes_do_objeto():
    assert extract_json_object("Claro, aqui está: " + _BASE)["score"] == 80


def test_cerca_markdown_json():
    assert extract_json_object("```json\n" + _BASE + "\n```")["reason"] == "ok"


def test_caractere_de_controle_cru_na_string():
    # Regressão qwen "Invalid control character": \n literal dentro da string.
    raw = '{"score": 80, "verdict": "CONFIAVEL", "reason": "linha1\nlinha2", "flags": []}'
    assert extract_json_object(raw)["verdict"] == "CONFIAVEL"


def test_none_levanta_value_error():
    # Regressão llama None.strip(): tem que ser ValueError, não AttributeError.
    with pytest.raises(ValueError):
        extract_json_object(None)


def test_string_vazia_levanta_value_error():
    with pytest.raises(ValueError):
        extract_json_object("   ")


def test_sem_objeto_json_levanta_value_error():
    with pytest.raises(ValueError):
        extract_json_object("não consegui analisar")


# ---------------------------------------------------------------------------
# parse_audit_json — validação e normalização
# ---------------------------------------------------------------------------

def test_parse_valido_normaliza():
    result = parse_audit_json(_BASE)
    assert result["score"] == 80
    assert result["commodity_risk"] == "BAIXO"  # default aplicado


def test_score_acima_de_100_e_limitado():
    raw = '{"score": 150, "verdict": "CONFIAVEL", "reason": "x", "flags": []}'
    assert parse_audit_json(raw)["score"] == 100


def test_score_negativo_vira_zero():
    raw = '{"score": -5, "verdict": "RUIDO", "reason": "x", "flags": []}'
    assert parse_audit_json(raw)["score"] == 0


def test_score_como_string_vira_int():
    raw = '{"score": "72", "verdict": "CONFIAVEL", "reason": "x", "flags": []}'
    assert parse_audit_json(raw)["score"] == 72


def test_fronteira_score_100():
    raw = '{"score": 100, "verdict": "CONFIAVEL", "reason": "x", "flags": []}'
    assert parse_audit_json(raw)["score"] == 100


def test_fronteira_score_0():
    raw = '{"score": 0, "verdict": "RUIDO", "reason": "x", "flags": []}'
    assert parse_audit_json(raw)["score"] == 0


def test_campo_obrigatorio_faltando_levanta_value_error():
    # falta "flags"
    raw = '{"score": 80, "verdict": "CONFIAVEL", "reason": "x"}'
    with pytest.raises(ValueError):
        parse_audit_json(raw)


def test_commodity_risk_preservado_quando_presente():
    raw = ('{"score": 80, "verdict": "CONFIAVEL", "reason": "x", '
           '"flags": [], "commodity_risk": "ALTO"}')
    assert parse_audit_json(raw)["commodity_risk"] == "ALTO"

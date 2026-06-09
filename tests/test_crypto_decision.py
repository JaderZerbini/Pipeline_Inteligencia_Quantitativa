"""Tests for crypto/decision.py — deterministic decision engine.

Valores esperados sao derivados das REGRAS DOCUMENTADAS, nao da saida do codigo.
Testes com call_ai=False evitam chamadas de API. Testes de BLOQUEADO mocam
_get_ai_consensus diretamente.

Funcoes testadas
----------------
evaluate_signal(signal: dict, call_ai: bool = True) -> dict
  Retorno: {"symbol": str, "decision": str, "ai_score": int,
            "ai_veredicto": str, "reasons": list, "evaluated_at": str}

Thresholds em uptrend (caso padrao):
  FORTE   : rsi <= 32, galaxy >= 52, change_pct_24h <= -3.0
  MODERADO: rsi <= 40, galaxy >= 48  (quando nao FORTE)
  AGUARDAR: qualquer outro caso

Thresholds em downtrend (mais rigidos):
  FORTE   : rsi <= 26, galaxy >= 52, change_pct_24h <= -3.0
  MODERADO: rsi <= 30, galaxy >= 48

Regras gerais (fonte da verdade):
  BLOQUEADO : veredito == MANIPULACAO (independente de RSI/galaxy/score)
  Gate MA200: pct_from_ma200 > 30 e above_ma200 → AGUARDAR
  Gate cooldown: sinal repetido em 4h → AGUARDAR
"""

from unittest.mock import patch

from crypto.decision import evaluate_signal

_COOLDOWN = "crypto.decision.is_in_cooldown"
_REGISTER = "crypto.decision.register_cooldown"
_AI_CALL  = "crypto.decision._get_ai_consensus"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal(rsi, galaxy, change=0.0, symbol="BTCUSDT", price=50000.0,
            sentiment="neutral", hist_trend="uptrend",
            hist_position="below_ma200", pct_from_ma200=5.0):
    return {
        "symbol": symbol,
        "price": price,
        "rsi_1h": rsi,
        "galaxy_score": galaxy,
        "change_pct_24h": change,
        "sentiment": sentiment,
        "hist_trend": hist_trend,
        "hist_position": hist_position,
        "pct_from_ma200": pct_from_ma200,
    }


# ---------------------------------------------------------------------------
# Happy-path: um caso por veredito
# ---------------------------------------------------------------------------

def test_forte_basic():
    """RSI=30 (<=32), galaxy=55 (>=52), change=-4.0 (<=−3.0) → FORTE (uptrend)."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(30, 55, change=-4.0), call_ai=False)
    assert result["decision"] == "FORTE"


def test_moderado_basic():
    """RSI=38 (<=40, >32), galaxy=50 (>=48, <52), change=0 → MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(38, 50, change=0.0), call_ai=False)
    assert result["decision"] == "MODERADO"


def test_aguardar_insufficient_criteria():
    """RSI=50 (>40), galaxy=30 (<48) → AGUARDAR."""
    result = evaluate_signal(_signal(50, 30, change=1.0), call_ai=False)
    assert result["decision"] == "AGUARDAR"


def test_bloqueado_manipulation_high_conviction():
    """IA retorna MANIPULACAO com score=10 (<20) → BLOQUEADO."""
    with patch(_AI_CALL, return_value={"score": 10, "veredicto": "MANIPULACAO", "razao": "pump"}):
        result = evaluate_signal(_signal(28, 58, change=-5.0), call_ai=True)
    assert result["decision"] == "BLOQUEADO"


# ---------------------------------------------------------------------------
# Fronteira de RSI FORTE (uptrend: threshold = 32)
# ---------------------------------------------------------------------------

def test_rsi_32_qualifies_for_forte():
    """RSI=32 (<=32) com galaxy e change ok → FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(32, 55, change=-4.0), call_ai=False)
    assert result["decision"] == "FORTE"


def test_rsi_33_fails_forte_falls_to_moderado():
    """RSI=33 (>32, NAO <=32) falha gate FORTE; mas <=40 e galaxy>=48 → MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(33, 50, change=-4.0), call_ai=False)
    assert result["decision"] == "MODERADO"


# ---------------------------------------------------------------------------
# Fronteira de galaxy_score
# ---------------------------------------------------------------------------

def test_galaxy_52_qualifies_for_forte():
    """galaxy=52 (>=52) com RSI e change ok → FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(30, 52, change=-4.0), call_ai=False)
    assert result["decision"] == "FORTE"


def test_galaxy_51_fails_forte_falls_to_moderado():
    """galaxy=51 (<52) falha gate FORTE; mas >=48 → MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(30, 51, change=-4.0), call_ai=False)
    assert result["decision"] == "MODERADO"


def test_galaxy_48_qualifies_for_moderado():
    """galaxy=48 (>=48) com RSI ok → MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(38, 48, change=0.0), call_ai=False)
    assert result["decision"] == "MODERADO"


def test_galaxy_47_fails_moderado():
    """galaxy=47 (<48): deve resultar em AGUARDAR."""
    result = evaluate_signal(_signal(38, 47, change=0.0), call_ai=False)
    assert result["decision"] == "AGUARDAR"


# ---------------------------------------------------------------------------
# Fronteira de variacao 24h (FORTE exige change <= -3.0)
# ---------------------------------------------------------------------------

def test_change_neg30_qualifies_for_forte():
    """change=-3.0 (exatamente <=-3.0) com RSI e galaxy ok → FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(30, 55, change=-3.0), call_ai=False)
    assert result["decision"] == "FORTE"


def test_change_neg299_fails_forte_falls_to_moderado():
    """change=-2.99 (>-3.0, NAO <=-3.0) falha gate FORTE; RSI e galaxy ok → MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(_signal(30, 55, change=-2.99), call_ai=False)
    # galaxy=55 >= 48 OK → MODERADO
    assert result["decision"] == "MODERADO"


# ---------------------------------------------------------------------------
# BLOQUEADO: score nao atenua manipulacao — regra incondicional
# ---------------------------------------------------------------------------

def test_bloqueado_manipulation_any_score():
    """MANIPULACAO + score=25 → BLOQUEADO (score nao atenua o bloqueio)."""
    with patch(_AI_CALL, return_value={"score": 25, "veredicto": "MANIPULACAO", "razao": "suspeita"}):
        result = evaluate_signal(_signal(28, 58, change=-5.0), call_ai=True)
    assert result["decision"] == "BLOQUEADO"


def test_bloqueado_manipulation_score_20():
    """MANIPULACAO + score=20 (fronteira anterior) → BLOQUEADO."""
    with patch(_AI_CALL, return_value={"score": 20, "veredicto": "MANIPULACAO", "razao": "pump"}):
        result = evaluate_signal(_signal(28, 58, change=-5.0), call_ai=True)
    assert result["decision"] == "BLOQUEADO"


def test_bloqueado_manipulation_score_50():
    """MANIPULACAO + score=50 → BLOQUEADO (score medio nao atenua)."""
    with patch(_AI_CALL, return_value={"score": 50, "veredicto": "MANIPULACAO", "razao": "coordenado"}):
        result = evaluate_signal(_signal(28, 58, change=-5.0), call_ai=True)
    assert result["decision"] == "BLOQUEADO"


def test_bloqueado_manipulation_score_99():
    """MANIPULACAO + score=99 → BLOQUEADO (alta convicção de manipulacao)."""
    with patch(_AI_CALL, return_value={"score": 99, "veredicto": "MANIPULACAO", "razao": "pump coordenado"}):
        result = evaluate_signal(_signal(28, 58, change=-5.0), call_ai=True)
    assert result["decision"] == "BLOQUEADO"


# ---------------------------------------------------------------------------
# Gate MA200
# ---------------------------------------------------------------------------

def test_ma200_above_30pct_overrides_to_aguardar():
    """Preco >30% acima da MA200 → AGUARDAR (zona de topo de ciclo)."""
    result = evaluate_signal(
        _signal(30, 55, change=-4.0, hist_position="above_ma200", pct_from_ma200=35),
        call_ai=False,
    )
    assert result["decision"] == "AGUARDAR"


def test_ma200_exactly_30pct_does_not_block():
    """30.0% acima NAO aciona o gate (condicao e >30, nao >=30)."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(
            _signal(30, 55, change=-4.0, hist_position="above_ma200", pct_from_ma200=30),
            call_ai=False,
        )
    assert result["decision"] == "FORTE"


# ---------------------------------------------------------------------------
# Thresholds dinamicos: downtrend exige RSI mais extremo
# ---------------------------------------------------------------------------

def test_downtrend_rsi_28_not_forte_stricter_threshold():
    """Em downtrend, threshold FORTE e RSI<=26 (nao 32). RSI=28 > 26 → nao FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(
            _signal(28, 55, change=-4.0, hist_trend="downtrend"),
            call_ai=False,
        )
    # downtrend: effective_rsi_forte=26 → 28 > 26 falha FORTE
    # downtrend: effective_rsi_moderate=30 → 28 <= 30 OK; galaxy=55 >= 48 → MODERADO
    assert result["decision"] == "MODERADO"


def test_downtrend_rsi_26_qualifies_for_forte():
    """Em downtrend, RSI=26 (<=26) satisfaz o threshold FORTE mais rigido."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(
            _signal(26, 55, change=-4.0, hist_trend="downtrend"),
            call_ai=False,
        )
    assert result["decision"] == "FORTE"


def test_uptrend_rsi_28_qualifies_for_forte():
    """Em uptrend, RSI=28 (<=32) qualifica para FORTE — threshold e mais permissivo."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER):
        result = evaluate_signal(
            _signal(28, 55, change=-4.0, hist_trend="uptrend"),
            call_ai=False,
        )
    assert result["decision"] == "FORTE"


# ---------------------------------------------------------------------------
# Gate cooldown
# ---------------------------------------------------------------------------

def test_forte_suppressed_in_cooldown():
    """Ticker em cooldown (4h) deve suprimir FORTE para AGUARDAR."""
    with patch(_COOLDOWN, return_value=True), patch(_REGISTER):
        result = evaluate_signal(_signal(30, 55, change=-4.0), call_ai=False)
    assert result["decision"] == "AGUARDAR"

"""Tests for b3/decision.py — deterministic decision engine.

Valores esperados são derivados das REGRAS DOCUMENTADAS, não da saída do código.
Testes que falham indicam divergência entre regra e implementação.

Funções testadas
----------------
evaluate_signal(signal: dict, audit: dict, macro: dict = None) -> dict
  Retorno: {"recommendation": str, "confidence": float, "reasons": list, "flags": list}

Regras (fonte da verdade):
  BLOQUEADO : verdict == "MANIPULACAO" (independente de qualquer outro critério)
  FORTE     : rsi < 30  AND volume_ratio > 1.5  AND effective_score >= 70
  MODERADO  : rsi < 38  AND volume_ratio > 1.2  AND effective_score >= 55
  AGUARDAR  : qualquer outro caso
  Gate macro      : macro_ok=False rebaixa FORTE → MODERADO
  Gate MA200      : pct_from_ma200 > 30 e above_ma200 → AGUARDAR
  Gate downtrend  : effective_score < 75 em downtrend → AGUARDAR
  Gate backtest   : MODERADO em ticker sem histórico → AGUARDAR
  Gate cooldown   : sinal repetido em 4h → AGUARDAR
"""

from unittest.mock import patch

from b3.decision import evaluate_signal

_COOLDOWN = "b3.decision.is_in_cooldown"
_REGISTER = "b3.decision.register_cooldown"
_APPROVED = "b3.decision.BACKTEST_APPROVED"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal(rsi, volume_ratio, ticker="PETR4", hist_position="unknown",
            hist_trend="unknown", pct_from_ma200=0):
    return {
        "ticker": ticker,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "hist_position": hist_position,
        "hist_trend": hist_trend,
        "pct_from_ma200": pct_from_ma200,
    }


def _audit(score=75, verdict="CONFIAVEL", flags=None):
    return {"score": score, "verdict": verdict, "flags": flags or []}


def _macro(score_adjustment=0, macro_ok=True, warnings=None, flags=None):
    return {
        "score_adjustment": score_adjustment,
        "macro_ok": macro_ok,
        "warnings": warnings or [],
        "flags": flags or [],
    }


# ---------------------------------------------------------------------------
# Happy-path: um caso por veredito
# ---------------------------------------------------------------------------

def test_forte_basic():
    """RSI=25 (<30), volume=2.0x (>1.5), score=80 (>=70) → FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(25, 2.0), _audit(80))
    assert result["recommendation"] == "FORTE"


def test_moderado_basic():
    """RSI=35 (>=30, <38), volume=1.3x (>1.2), score=60 (>=55, <70) → MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(35, 1.3), _audit(60))
    assert result["recommendation"] == "MODERADO"


def test_aguardar_insufficient_criteria():
    """RSI=45 (>=38), volume=0.8x (<1.2), score=40 (<55) → AGUARDAR."""
    result = evaluate_signal(_signal(45, 0.8), _audit(40))
    assert result["recommendation"] == "AGUARDAR"


def test_bloqueado_manipulation():
    """Veredito MANIPULACAO → BLOQUEADO independente de RSI/volume/score perfeitos."""
    result = evaluate_signal(
        _signal(20, 3.0),  # tecnicos perfeitos para FORTE
        _audit(90, verdict="MANIPULACAO"),
    )
    assert result["recommendation"] == "BLOQUEADO"


# ---------------------------------------------------------------------------
# Fronteiras de RSI
# ---------------------------------------------------------------------------

def test_rsi_29_qualifies_for_forte():
    """RSI=29 esta abaixo de 30: deve classificar como FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(29, 2.0), _audit(80))
    assert result["recommendation"] == "FORTE"


def test_rsi_30_fails_forte_falls_to_moderado():
    """RSI=30 NAO e < 30 (FORTE falha); e < 38 (MODERADO passa)."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(30, 2.0), _audit(80))
    assert result["recommendation"] == "MODERADO"


def test_rsi_37_qualifies_for_moderado():
    """RSI=37 esta abaixo de 38: deve classificar como MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(37, 1.3), _audit(60))
    assert result["recommendation"] == "MODERADO"


def test_rsi_38_fails_moderado():
    """RSI=38 NAO e < 38: deve resultar em AGUARDAR."""
    result = evaluate_signal(_signal(38, 1.3), _audit(60))
    assert result["recommendation"] == "AGUARDAR"


# ---------------------------------------------------------------------------
# Fronteiras de volume_ratio
# ---------------------------------------------------------------------------

def test_volume_151_qualifies_for_forte():
    """volume_ratio=1.51 (>1.5) com RSI e score ok → FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(25, 1.51), _audit(80))
    assert result["recommendation"] == "FORTE"


def test_volume_150_fails_forte_falls_to_moderado():
    """volume_ratio=1.50 NAO e >1.5 (FORTE falha); e >1.2 (MODERADO passa)."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(25, 1.50), _audit(80))
    assert result["recommendation"] == "MODERADO"


def test_volume_121_qualifies_for_moderado():
    """volume_ratio=1.21 (>1.2) com RSI e score ok → MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(35, 1.21), _audit(60))
    assert result["recommendation"] == "MODERADO"


def test_volume_120_fails_moderado():
    """volume_ratio=1.20 NAO e >1.2: deve resultar em AGUARDAR."""
    result = evaluate_signal(_signal(35, 1.20), _audit(60))
    assert result["recommendation"] == "AGUARDAR"


# ---------------------------------------------------------------------------
# Fronteiras de score efetivo
# ---------------------------------------------------------------------------

def test_score_70_qualifies_for_forte():
    """Score=70 (>=70) com RSI e volume ok → FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(25, 2.0), _audit(70))
    assert result["recommendation"] == "FORTE"


def test_score_69_fails_forte_falls_to_moderado():
    """Score=69 (<70) falha gate FORTE; e >=55 passa MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(25, 2.0), _audit(69))
    assert result["recommendation"] == "MODERADO"


def test_score_55_qualifies_for_moderado():
    """Score=55 (>=55) com RSI e volume ok → MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(35, 1.3), _audit(55))
    assert result["recommendation"] == "MODERADO"


def test_score_54_fails_moderado():
    """Score=54 (<55): deve resultar em AGUARDAR."""
    result = evaluate_signal(_signal(35, 1.3), _audit(54))
    assert result["recommendation"] == "AGUARDAR"


# ---------------------------------------------------------------------------
# Gate macro
# ---------------------------------------------------------------------------

def test_macro_ok_false_downgrades_forte_to_moderado():
    """Sinal FORTE com macro_ok=False deve ser rebaixado para MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(25, 2.0), _audit(80), macro=_macro(macro_ok=False))
    assert result["recommendation"] == "MODERADO"


def test_macro_ok_false_does_not_downgrade_moderado():
    """macro_ok=False rebaixa apenas FORTE; MODERADO permanece MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(35, 1.3), _audit(60), macro=_macro(macro_ok=False))
    assert result["recommendation"] == "MODERADO"


def test_macro_positive_adjustment_lifts_score_to_forte():
    """score_adjustment=+10 eleva score efetivo de 65 para 75 (>=70) → FORTE."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(
            _signal(25, 2.0), _audit(65), macro=_macro(score_adjustment=10, macro_ok=True)
        )
    assert result["recommendation"] == "FORTE"


def test_macro_negative_adjustment_drops_score_below_forte():
    """score_adjustment=-15 baixa score efetivo de 80 para 65 (<70): FORTE cai para MODERADO."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(
            _signal(25, 2.0), _audit(80), macro=_macro(score_adjustment=-15, macro_ok=True)
        )
    assert result["recommendation"] == "MODERADO"


# ---------------------------------------------------------------------------
# Gate MA200
# ---------------------------------------------------------------------------

def test_ma200_above_30pct_overrides_to_aguardar():
    """Preco >30% acima da MA200 deve resultar em AGUARDAR (zona cara)."""
    result = evaluate_signal(
        _signal(25, 2.0, hist_position="above_ma200", pct_from_ma200=31),
        _audit(80),
    )
    assert result["recommendation"] == "AGUARDAR"


def test_ma200_exactly_30pct_does_not_block():
    """30.0% acima NAO aciona o gate (condicao e >30, nao >=30)."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(
            _signal(25, 2.0, hist_position="above_ma200", pct_from_ma200=30),
            _audit(80),
        )
    assert result["recommendation"] == "FORTE"


def test_bloqueado_not_overridden_by_ma200_gate():
    """BLOQUEADO por manipulacao NAO deve ser sobrescrito pelo gate MA200.

    REGRA: BLOQUEADO e final — independente de qualquer outro indicador.
    ESPERADO: BLOQUEADO.

    Se este teste FALHAR retornando AGUARDAR, o codigo tem um bug real:
    o gate MA200 sobrescreve a classificacao BLOQUEADO definida na prioridade 1,
    em contradicao direta com a regra de prioridade documentada.
    """
    result = evaluate_signal(
        _signal(20, 3.0, hist_position="above_ma200", pct_from_ma200=35),
        _audit(90, verdict="MANIPULACAO"),
    )
    assert result["recommendation"] == "BLOQUEADO"


# ---------------------------------------------------------------------------
# Gate downtrend
# ---------------------------------------------------------------------------

def test_downtrend_score_below_75_blocks():
    """Tendencia de baixa + score<75: sinal FORTE/MODERADO e rebaixado para AGUARDAR."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(
            _signal(25, 2.0, hist_trend="downtrend"),
            _audit(72),  # 72 >= 70 qualifica FORTE inicialmente; < 75 aciona gate downtrend
        )
    assert result["recommendation"] == "AGUARDAR"


def test_downtrend_score_75_not_blocked():
    """Tendencia de baixa + score=75: gate NAO dispara (condicao e <75, nao <=75)."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(
            _signal(25, 2.0, hist_trend="downtrend"),
            _audit(75),
        )
    assert result["recommendation"] in ("FORTE", "MODERADO")


# ---------------------------------------------------------------------------
# Gate backtest
# ---------------------------------------------------------------------------

def test_moderado_unapproved_ticker_downgraded_to_aguardar():
    """MODERADO em ticker sem backtest aprovado deve ser rebaixado para AGUARDAR."""
    with patch(_APPROVED, set()):
        result = evaluate_signal(_signal(35, 1.3, ticker="XYZW3"), _audit(60))
    assert result["recommendation"] == "AGUARDAR"


def test_forte_unapproved_ticker_not_downgraded():
    """Gate de backtest rebaixa apenas MODERADO — FORTE deve ser mantido."""
    with patch(_COOLDOWN, return_value=False), patch(_REGISTER), \
         patch(_APPROVED, set()):
        result = evaluate_signal(_signal(25, 2.0, ticker="XYZW3"), _audit(80))
    assert result["recommendation"] == "FORTE"


# ---------------------------------------------------------------------------
# Gate cooldown
# ---------------------------------------------------------------------------

def test_forte_suppressed_in_cooldown():
    """Ticker em cooldown (4h) deve suprimir FORTE para AGUARDAR."""
    with patch(_COOLDOWN, return_value=True), patch(_REGISTER), \
         patch(_APPROVED, {"PETR4"}):
        result = evaluate_signal(_signal(25, 2.0), _audit(80))
    assert result["recommendation"] == "AGUARDAR"

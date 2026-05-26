"""Deterministic decision engine: maps signal + audit data to a recommendation."""

import json
import logging
import os

from db import is_in_cooldown, register_cooldown

logger = logging.getLogger(__name__)


def _load_approved_tickers() -> set:
    """Loads approved tickers from backtest results file.

    Approval criteria (derived from metrics when no explicit 'approved' flag):
      win_rate >= 55% AND sharpe_ratio >= 0.5

    Actual file format (data/backtest_results.json):
      {"results": [{"ticker": "PETR4.SA", "win_rate": 75.0, "sharpe_ratio": 1.01, ...}]}
    Tickers include '.SA' suffix — stripped here to match signal dict usage.
    Falls back to hardcoded set if file is missing or unreadable.
    """
    results_path = os.path.join("data", "backtest_results.json")
    fallback = {"SBSP3", "VALE3", "ITUB4", "PETR4", "B3SA3", "BBDC4"}

    try:
        if not os.path.exists(results_path):
            logger.warning(
                "[BACKTEST] backtest_results.json não encontrado — usando lista fallback"
            )
            return fallback

        with open(results_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "approved" in data:
            # Explicit allowlist: {"approved": ["PETR4", ...]}
            return {t.replace(".SA", "") for t in data["approved"]}

        if "results" in data:
            # Derive from metrics — supports both explicit flag and threshold logic
            approved = set()
            for r in data["results"]:
                if r.get("approved", False):
                    approved.add(r["ticker"].replace(".SA", ""))
                elif r.get("win_rate", 0) >= 55 and r.get("sharpe_ratio", 0) >= 0.5:
                    approved.add(r["ticker"].replace(".SA", ""))
            if not approved:
                logger.warning("[BACKTEST] Nenhum ticker aprovado pelos critérios — usando fallback")
                return fallback
            logger.info(f"[BACKTEST] {len(approved)} tickers aprovados: {sorted(approved)}")
            return approved

        logger.warning("[BACKTEST] Formato inesperado em backtest_results.json — usando fallback")
        return fallback

    except Exception as e:
        logger.warning(f"[BACKTEST] Erro ao ler resultados: {e} — usando fallback")
        return fallback


# Loaded once at import time — re-import or restart to pick up new backtest results.
BACKTEST_APPROVED = _load_approved_tickers()

_BASE_CONFIDENCE = {
    "FORTE": 0.90,
    "MODERADO": 0.70,
    "AGUARDAR": 0.40,
    "BLOQUEADO": 0.00,
}

_FALLBACK_CONFIDENCE_PENALTY = 0.20


def evaluate_signal(signal: dict, audit: dict, macro: dict = None) -> dict:
    """Apply deterministic trading rules to produce a recommendation.

    No LLM calls here — rules are evaluated in strict priority order:
    BLOQUEADO > FORTE > MODERADO > AGUARDAR.

    Args:
        signal: Dict with at minimum the keys:
                  - rsi (float): 14-period RSI value
                  - volume_ratio (float): volume vs. 20-day average
                  - ticker (str): for logging context
        audit:  Dict returned by ``analyze_news()``, with keys:
                  - score (int 0-100): reliability score
                  - verdict (str): 'CONFIAVEL', 'RUIDO', or 'MANIPULACAO'
                  - flags (list[str]): risk flags including 'FALLBACK'
        macro:  Optional dict returned by ``evaluate_macro()``, with keys:
                  - score_adjustment (int): positive/negative delta applied to audit score
                  - flags (list[str]): macro risk flags
                  - warnings (list[str]): human-readable macro alerts
                  - macro_ok (bool): False when macro headwinds are severe

    Returns:
        Dict with keys:
          - recommendation (str): 'FORTE', 'MODERADO', 'AGUARDAR', or 'BLOQUEADO'
          - confidence (float): 0.0–1.0, reduced by 20 pp when audit is FALLBACK
          - reasons (list[str]): human-readable explanation of each applied rule
          - flags (list[str]): combined audit + macro flags
    """
    rsi: float = float(signal.get("rsi") or signal.get("RSI") or 100)
    volume_ratio: float = float(signal.get("volume_ratio") or 0)
    verdict: str = audit.get("verdict", "RUIDO")
    flags: list[str] = list(audit.get("flags", []))

    reasons: list[str] = []

    # Apply macro context: adjust effective score and surface warnings upfront
    if macro:
        effective_score = max(0, min(100, audit.get("score", 50) + macro["score_adjustment"]))
        if macro["warnings"]:
            reasons.extend(macro["warnings"])
        flags.extend(macro.get("flags", []))
    else:
        effective_score = audit.get("score", 50)

    # Priority 1: manipulation always blocks regardless of technicals
    if verdict == "MANIPULACAO":
        recommendation = "BLOQUEADO"
        reasons.append(f"Manipulação detectada pelo auditor IA (score={effective_score})")

    # Priority 2: strong buy — oversold RSI + high volume + trusted audit
    elif rsi < 30 and volume_ratio > 1.5 and effective_score >= 70:
        recommendation = "FORTE"
        reasons.append(f"RSI em zona de reversão ({rsi:.1f} < 30)")
        reasons.append(f"Volume {volume_ratio:.2f}x acima da média de 20 dias")
        reasons.append(f"Auditoria confiável (score={effective_score})")

    # Priority 3: moderate buy — RSI elevated but not extreme + decent audit
    elif rsi < 38 and volume_ratio > 1.2 and effective_score >= 55:
        recommendation = "MODERADO"
        reasons.append(f"RSI favorável ({rsi:.1f} < 38)")
        reasons.append(f"Volume {volume_ratio:.2f}x acima da média")
        reasons.append(f"Auditoria positiva (score={effective_score})")

    # Default: wait
    else:
        recommendation = "AGUARDAR"
        reasons.append(
            f"Critérios insuficientes — RSI={rsi:.1f}, "
            f"volume_ratio={volume_ratio:.2f}, score={effective_score}"
        )

    # Macro may downgrade a FORTE signal when conditions are unfavourable
    if macro and not macro["macro_ok"] and recommendation == "FORTE":
        recommendation = "MODERADO"
        reasons.append("Macro desfavorável rebaixou sinal")

    # Backtest gate: boost label for approved tickers, downgrade unvalidated MODERADO
    ticker_clean = signal.get("ticker", "").replace(".SA", "")
    if ticker_clean in BACKTEST_APPROVED and recommendation in ("FORTE", "MODERADO"):
        reasons.append("Ativo validado pelo backtest historico")
    elif ticker_clean not in BACKTEST_APPROVED and recommendation == "MODERADO":
        recommendation = "AGUARDAR"
        reasons.append("Ativo sem validacao historica suficiente — sinal rebaixado")

    # Cooldown gate: suppress repeated actionable signals within 4 hours
    if recommendation in ("FORTE", "MODERADO"):
        if is_in_cooldown(ticker_clean, pipeline='b3', hours=4):
            logger.info(f"[COOLDOWN] {ticker_clean}: sinal suprimido (cooldown 4h)")
            recommendation = "AGUARDAR"
            reasons.append("Cooldown ativo (4h desde último sinal) — aguarde nova janela")
        else:
            register_cooldown(ticker_clean, pipeline='b3')

    confidence = _BASE_CONFIDENCE[recommendation]

    # Reduce confidence when Gemini was unavailable and fallback was used
    if "FALLBACK" in flags:
        confidence = max(0.0, confidence - _FALLBACK_CONFIDENCE_PENALTY)
        reasons.append("Confiança reduzida: auditoria IA indisponível no momento da decisão")

    return {
        "recommendation": recommendation,
        "confidence": round(confidence, 2),
        "reasons": reasons,
        "flags": flags,
    }

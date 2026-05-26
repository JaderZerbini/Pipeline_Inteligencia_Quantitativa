"""AI audit layer: multi-model consensus via OpenRouter, with direct Gemini fallback."""

from dotenv import load_dotenv
load_dotenv()  # must run before any os.getenv() calls

import json
import os
import re
import time
import threading
import concurrent.futures
from google import genai
from openai import OpenAI
from db import save_audit

_key = os.getenv("OPENROUTER_API_KEY")
if not _key:
    print("[WARN] OPENROUTER_API_KEY não encontrada no .env")
elif _key == "your_key_here":
    print("[ERROR] Substitua OPENROUTER_API_KEY no arquivo .env pela chave real")

# ---------------------------------------------------------------------------
# OpenRouter consensus configuration
# ---------------------------------------------------------------------------

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_MODELS = [
    {"id": "deepseek/deepseek-chat",            "weight": 0.40, "label": "deepseek"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "weight": 0.35, "label": "llama"},
    {"id": "google/gemini-2.0-flash-001",        "weight": 0.25, "label": "gemini"},
]

_WEIGHTS = {m["label"]: m["weight"] for m in _MODELS}

# ---------------------------------------------------------------------------
# Gemini direct fallback configuration
# ---------------------------------------------------------------------------

_GEMINI_MODEL = "gemini-2.0-flash"

# Shared executor kept alive for the Gemini fallback path only
_gemini_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="gemini-fallback"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FALLBACK_AUDIT: dict = {
    "score": 50,
    "verdict": "RUIDO",
    "reason": "Fallback: análise indisponível",
    "commodity_risk": "BAIXO",
    "flags": ["FALLBACK"],
}


# ---------------------------------------------------------------------------
# Shared JSON parser (used by all model response paths)
# ---------------------------------------------------------------------------

def _parse_gemini_json(text: str) -> dict:
    """Strip markdown fences (if present) then parse and validate the JSON.

    Works for both bare JSON and responses wrapped in ```json ... ``` blocks.
    Raises on bad input — caller must handle and fall back.
    """
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    result = json.loads(text)
    if not {"score", "verdict", "reason", "flags"}.issubset(result):
        raise ValueError(f"Campos obrigatórios ausentes: {list(result)}")
    result["score"] = max(0, min(100, int(result["score"])))
    result.setdefault("commodity_risk", "BAIXO")
    return result


# ---------------------------------------------------------------------------
# OpenRouter: per-model call + weighted consensus
# ---------------------------------------------------------------------------

def _call_model(
    model_id: str,
    prompt: str,
    result: dict,
    key: str,
    system_override: str | None = None,
) -> None:
    """Call a single OpenRouter model and store the parsed result in shared dict.

    Args:
        model_id:        OpenRouter model identifier.
        prompt:          Prompt string sent to the model.
        result:          Shared dict where ``result[key]`` is written on success.
        key:             Short alias used as dict key ('gemini', 'llama', 'mistral').
        system_override: Optional system message injected before the user turn.
                         When None, no system message is sent (B3 default path).
    """
    try:
        client = OpenAI(
            base_url=_OPENROUTER_BASE_URL,
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
        messages = []
        if system_override:
            messages.append({"role": "system", "content": system_override})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            timeout=20,
        )
        raw = response.choices[0].message.content
        result[key] = _parse_gemini_json(raw)
    except Exception as e:
        print(f"[CONSENSUS ERROR] {model_id}: {type(e).__name__}: {e}")
        result[key] = None


def _weighted_consensus(results: dict) -> dict:
    """Compute a weighted consensus verdict from available model responses.

    Applies a MANIPULACAO veto: if any model with weight >= 0.30 votes for
    manipulation, the final verdict is overridden to MANIPULACAO and score is
    clamped to 25.

    Args:
        results: Dict mapping model keys to parsed audit dicts (or None on failure).

    Returns:
        Consensus audit dict, or a copy of ``_FALLBACK_AUDIT`` if no model succeeded.
    """
    available = {k: v for k, v in results.items() if v is not None}
    if not available:
        return dict(_FALLBACK_AUDIT)

    total_weight = sum(_WEIGHTS[k] for k in available)
    score = sum(_WEIGHTS[k] * available[k]["score"] for k in available) / total_weight

    # Weighted majority vote on verdict
    verdict_scores: dict[str, float] = {}
    for k, v in available.items():
        verd = v["verdict"]
        verdict_scores[verd] = verdict_scores.get(verd, 0.0) + _WEIGHTS[k]
    verdict = max(verdict_scores, key=verdict_scores.get)

    # MANIPULACAO veto: any model with significant weight overrides the vote
    for k, v in available.items():
        if v["verdict"] == "MANIPULACAO" and _WEIGHTS[k] >= 0.30:
            verdict = "MANIPULACAO"
            score = min(score, 25)
            break

    models_used = list(available.keys())
    reasons = [v["reason"] for v in available.values()]

    _risk_order = {"ALTO": 2, "MEDIO": 1, "BAIXO": 0}
    commodity_risk = max(
        (v.get("commodity_risk", "BAIXO") for v in available.values()),
        key=lambda x: _risk_order.get(x, 0),
    )

    return {
        "score": round(score),
        "verdict": verdict,
        "reason": " | ".join(reasons),
        "commodity_risk": commodity_risk,
        "flags": [f"CONSENSUS:{len(available)}/3"],
        "models_used": models_used,
    }


def _run_consensus(prompt: str, system_override: str | None = None) -> dict | None:
    """Launch all model threads in parallel and return the weighted consensus.

    Threads share a wall-clock deadline of 22 seconds so that slower models
    do not add waiting time on top of faster ones. A threading.Lock protects
    the shared results dict against concurrent writes.

    Args:
        prompt:          User-turn prompt sent to each model.
        system_override: Optional system message (e.g. crypto analyst persona).

    Returns:
        Consensus dict, or ``None`` if every model call failed (triggers
        Gemini fallback in the caller).
    """
    results: dict = {}
    results_lock = threading.Lock()
    threads: list[threading.Thread] = []

    def _locked_call(model_id, prompt, key, system_override):
        """Wrapper that writes to results under the lock."""
        tmp: dict = {}
        _call_model(model_id, prompt, tmp, key, system_override)
        with results_lock:
            results[key] = tmp.get(key)

    for model in _MODELS:
        t = threading.Thread(
            target=_locked_call,
            args=(model["id"], prompt, model["label"], system_override),
            daemon=True,
        )
        threads.append(t)
        t.start()

    # Shared deadline: total wait ≤ 22s regardless of thread count
    deadline = time.time() + 22
    for t in threads:
        remaining = max(0.0, deadline - time.time())
        t.join(timeout=remaining)

    with results_lock:
        final_results = dict(results)

    available = {k: v for k, v in final_results.items() if v is not None}
    if not available:
        return None  # signal caller to try Gemini fallback

    if len(available) == 1:
        # Only one model responded — flag as low confidence but still return
        single = list(available.values())[0]
        if single:
            single = dict(single)
            single["low_confidence"] = True
            single.setdefault("flags", [])
            single["flags"].append("LOW_CONFIDENCE:1/3")
        return single

    return _weighted_consensus(final_results)


# ---------------------------------------------------------------------------
# Gemini direct fallback path
# ---------------------------------------------------------------------------

def _call_gemini_direct(api_key: str, prompt: str) -> str:
    """Direct Gemini call used when OpenRouter is unavailable."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=prompt,
    )
    return response.text


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persist(signal_id: int, result: dict, headline: str) -> None:
    """Write audit to DB. models_used is serialised into raw_response as JSON."""
    try:
        source = (
            "OpenRouter"
            if result.get("models_used")
            else "Gemini Direct"
        )
        save_audit(
            signal_id=signal_id,
            gemini_score=result["score"],
            headline=headline,
            source=source,
            verdict=result["verdict"],
            raw_response=json.dumps(result, ensure_ascii=False),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Crypto-specific system prompt
# ---------------------------------------------------------------------------

_CRYPTO_SYSTEM = (
    "Você é um analista especializado em mercados de criptomoedas. "
    "Avalie sinais de manipulação social (pump-and-dump, FUD coordenado), "
    "verifique se o volume social é orgânico e se o RSI é consistente com o sentimento. "
    "Responda APENAS com JSON válido no formato: "
    '{"score": 0-100, "verdict": "CONFIAVEL|RUIDO|MANIPULACAO|PUMP|FUD_COORDENADO", '
    '"reason": "uma frase curta", "flags": []}. '
    "Score: 70-100=sinal confiável, 40-69=incerto, 0-39=manipulação ou FUD."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_crypto(prompt: str) -> dict:
    """Audit a crypto signal via multi-model consensus with crypto-specific context.

    Unlike analyze_news (B3 context), uses a crypto-specialist system prompt
    and accepts the pre-built signal prompt directly — no B3 headline wrapping.

    Args:
        prompt: Pre-built signal data string from crypto_decision._build_crypto_prompt().

    Returns:
        Dict with keys: score, verdict, reason, flags.
    """
    if os.getenv("OPENROUTER_API_KEY"):
        try:
            consensus = _run_consensus(prompt, system_override=_CRYPTO_SYSTEM)
            if consensus is not None:
                return consensus
        except Exception:
            pass
        print("[WARN] OpenRouter indisponível — usando Gemini direto como fallback")

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        full_prompt = f"{_CRYPTO_SYSTEM}\n\n{prompt}"
        future = _gemini_executor.submit(_call_gemini_direct, gemini_key, full_prompt)
        try:
            raw = future.result(timeout=20)
            return _parse_gemini_json(raw)
        except Exception as e:
            print(f"[GEMINI ERROR] {type(e).__name__}: {e}")

    return dict(_FALLBACK_AUDIT)


def analyze_news(headline: str, ticker: str, signal_id: int | None = None) -> dict:
    """Audit a news headline via multi-model consensus with Gemini fallback.

    Execution order:
      1. Headline guard — skip API calls if headline is empty or trivial.
      2. OpenRouter consensus — 3 models in parallel, weighted verdict.
      3. Gemini direct — single call if OpenRouter key is absent or all models fail.
      4. FALLBACK_AUDIT — returned if both API paths fail.

    Args:
        headline:  News headline string to be audited.
        ticker:    Stock ticker for prompt context (e.g. 'PETR4').
        signal_id: When provided, persists the result to the DB via
                   ``save_audit()``, linked to this signal row.

    Returns:
        Dict with keys: score, verdict, reason, flags, and (on consensus path)
        models_used (list[str]).
    """
    # Guard: no meaningful headline → skip all API calls
    if not headline or len(headline.strip()) < 10:
        result = {
            "score": 40,
            "verdict": "RUIDO",
            "reason": "Sem manchete disponível para análise",
            "flags": ["NO_NEWS"],
        }
        if signal_id is not None:
            _persist(signal_id, result, headline or "")
        return result

    prompt = f"""Você é um analista financeiro especializado em B3 e cadeias de suprimentos globais.

Analise as seguintes manchetes recentes sobre fatores que impactam o ativo {ticker} e retorne APENAS JSON válido.

Manchetes: "{headline}"

Considere impactos INDIRETOS: guerras afetam commodities, que afetam margens das empresas. Eventos climáticos afetam oferta de matérias-primas. Decisões de bancos centrais afetam custo de capital.

Retorne exatamente:
{{"score": <0-100>, "verdict": "<CONFIAVEL|RUIDO|MANIPULACAO>", "reason": "<uma frase sobre o impacto no ativo>", "commodity_risk": "<ALTO|MEDIO|BAIXO>", "flags": [<lista de fatores de risco identificados>]}}

Score: 70-100=notícia fundamentada com impacto claro no ativo, 40-69=impacto indireto ou incerto, 0-39=sem relação ou manipulação.
Responda SOMENTE com o JSON."""

    # --- Primary: OpenRouter multi-model consensus ---
    if os.getenv("OPENROUTER_API_KEY"):
        try:
            consensus = _run_consensus(prompt)
            if consensus is not None:
                if signal_id is not None:
                    _persist(signal_id, consensus, headline)
                return consensus
        except Exception:
            pass
        print("[WARN] OpenRouter indisponível — usando Gemini direto como fallback")

    # --- Fallback: direct Gemini call ---
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        future = _gemini_executor.submit(_call_gemini_direct, gemini_key, prompt)
        try:
            raw = future.result(timeout=20)
            result = _parse_gemini_json(raw)
        except Exception as e:
            print(f"[GEMINI ERROR] {type(e).__name__}: {e}")
            result = dict(_FALLBACK_AUDIT)
    else:
        result = dict(_FALLBACK_AUDIT)

    if signal_id is not None:
        _persist(signal_id, result, headline)
    return result

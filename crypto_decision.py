"""
crypto_decision.py
------------------
Motor de decisão para o pipeline cripto.

Filosofia idêntica ao decision_engine.py do Terminal Quant:
  → Regras determinísticas primeiro (rápidas, sem custo)
  → IA entra apenas quando os indicadores já apontam oportunidade
  → Sistema fica PARADO na dúvida — nunca force uma operação

Diferenças em relação ao B3:
  → Sem RSI técnico absoluto como gate principal (cripto é mais volátil)
  → Galaxy Score do LunarCrush substitui o volume ratio como filtro social
  → Consenso Claude + Gemini via sentiment_analyzer.py existente
  → Sem ajuste macro de SELIC (irrelevante para cripto)
  → Thresholds mais conservadores (volatilidade maior = margem de segurança maior)
"""

import logging
import threading
from datetime import datetime, timezone

# Reaproveitando o sentiment_analyzer.py existente sem modificação
# Ele já usa OpenRouter com DeepSeek (40%) + Llama (35%) + Gemini (25%)
# Função pública: analyze_news(headline, ticker) → {score, verdict, reason, ...}
from sentiment_analyzer import analyze_news

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds — ajuste conforme seu apetite de risco
# ---------------------------------------------------------------------------

# Sinal FORTE: todos os critérios atendidos
STRONG_RSI_MAX = 35          # RSI abaixo disso = sobrevendido em cripto
STRONG_GALAXY_MIN = 55       # Galaxy Score mínimo (evita moedas sem liquidez social)
STRONG_CHANGE_MAX = -5.0     # Queda mínima nas últimas 24h para entrada de recuperação
STRONG_AI_SCORE_MIN = 65     # Score mínimo do consenso das IAs

# Sinal MODERADO: critérios relaxados
MODERATE_RSI_MAX = 42
MODERATE_GALAXY_MIN = 45
MODERATE_AI_SCORE_MIN = 55

# Bloqueio por manipulação (detecção nas IAs)
MANIPULATION_VERDICTS = {"MANIPULACAO", "PUMP", "FUD_COORDENADO"}

# Timeout da chamada às IAs (cripto não precisa ser ultra-rápido)
AI_TIMEOUT_SECONDS = 25


# ---------------------------------------------------------------------------
# Análise de sentimento via IAs (reutiliza sentiment_analyzer.py)
# ---------------------------------------------------------------------------

def _build_crypto_prompt(signal: dict) -> str:
    """Constrói o prompt enviado às IAs para análise do sinal cripto."""
    return f"""Analise o seguinte sinal de mercado para cripto e responda APENAS no formato JSON:

Ativo: {signal['symbol']}
Preço atual: ${signal['price']:,.2f}
Variação 24h: {signal.get('change_pct_24h', 0):+.2f}%
RSI(1h): {signal.get('rsi_1h', 'N/A')}
Galaxy Score (LunarCrush): {signal.get('galaxy_score', 'N/A')} / 100
Volume social 24h: {signal.get('social_volume_24h', 'N/A')}
Sentimento social: {signal.get('sentiment', 'unknown')}

Avalie:
1. Há sinais de pump-and-dump coordenado nas redes sociais?
2. O volume social é orgânico ou artificialmente inflado?
3. O RSI e sentimento são consistentes entre si?

Responda SOMENTE com JSON neste formato exato:
{{"score": 0-100, "veredicto": "CONFIAVEL|RUIDO|MANIPULACAO|PUMP|FUD_COORDENADO", "razao": "uma frase curta"}}"""


def _get_ai_consensus(signal: dict) -> dict:
    """
    Chama o run_consensus do sentiment_analyzer.py existente.
    Usa threading para respeitar o timeout sem bloquear o pipeline.
    """
    result = {"score": 50, "veredicto": "RUIDO", "razao": "timeout ou erro"}
    event = threading.Event()

    def _call():
        nonlocal result
        try:
            prompt = _build_crypto_prompt(signal)
            # analyze_news aceita headline + ticker; passamos o prompt cripto como headline
            consensus = analyze_news(headline=prompt, ticker=signal["symbol"])
            if consensus:
                # Mapeia verdict/reason → veredicto/razao esperados pelo evaluate_signal
                result = {
                    "score":     consensus.get("score", 50),
                    "veredicto": consensus.get("verdict", "RUIDO"),
                    "razao":     consensus.get("reason", ""),
                }
        except Exception as e:
            logger.warning(f"[AI] {signal['symbol']}: {e}")
        finally:
            event.set()

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    event.wait(timeout=AI_TIMEOUT_SECONDS)

    return result


# ---------------------------------------------------------------------------
# Motor de decisão principal
# ---------------------------------------------------------------------------

def evaluate_signal(signal: dict, call_ai: bool = True) -> dict:
    """
    Avalia um sinal do crypto_scanner.py e retorna veredicto com justificativa.

    Parâmetros:
        signal   — dicionário retornado pelo scan_crypto()
        call_ai  — se False, pula a chamada às IAs (útil para backtesting)

    Retorna:
        {
            "symbol": str,
            "decision": "FORTE" | "MODERADO" | "AGUARDAR" | "BLOQUEADO",
            "ai_score": int,
            "ai_veredicto": str,
            "reasons": list[str],
            "evaluated_at": str (ISO UTC),
        }
    """
    symbol = signal["symbol"]
    rsi = signal.get("rsi_1h")
    galaxy = signal.get("galaxy_score")
    change = signal.get("change_pct_24h", 0)
    sentiment = signal.get("sentiment", "unknown")

    reasons = []
    ai_score = 50
    ai_veredicto = "NAO_AVALIADO"

    # --- Passo 1: Filtros duros (sem custo, sem IA) ---

    # Dado essencial ausente
    if rsi is None:
        return _make_result(symbol, "AGUARDAR", ai_score, ai_veredicto,
                            ["RSI indisponível — sem dados suficientes"])

    # Sentimento negativo forte = sinal de fuga, não entrada
    if sentiment == "negative" and (galaxy is not None and galaxy < 30):
        return _make_result(symbol, "AGUARDAR", ai_score, ai_veredicto,
                            [f"Sentimento negativo (galaxy={galaxy}) — não é momento de entrada"])

    # --- Passo 2: Consenso das IAs (só se indicadores básicos estão ok) ---

    if call_ai:
        logger.info(f"[DECISION] {symbol}: chamando IAs...")
        ai_result = _get_ai_consensus(signal)
        ai_score = ai_result.get("score", 50)
        ai_veredicto = ai_result.get("veredicto", "RUIDO")
        razao = ai_result.get("razao", "")
        reasons.append(f"IA: {ai_veredicto} (score={ai_score}) — {razao}")

        # Bloqueio imediato por detecção de manipulação
        if ai_veredicto in MANIPULATION_VERDICTS:
            return _make_result(symbol, "BLOQUEADO", ai_score, ai_veredicto,
                                [f"Manipulação detectada: {ai_veredicto} — {razao}"])

    # --- Passo 3: Classificação por critérios ---

    galaxy_ok_strong = galaxy is not None and galaxy >= STRONG_GALAXY_MIN
    galaxy_ok_moderate = galaxy is not None and galaxy >= MODERATE_GALAXY_MIN

    # Quando IA não é chamada (backtesting/dry-run), o gate de score não bloqueia
    ai_ok_forte = not call_ai or ai_score >= STRONG_AI_SCORE_MIN
    ai_ok_moderate = not call_ai or ai_score >= MODERATE_AI_SCORE_MIN

    # FORTE: todos os critérios máximos
    if (rsi <= STRONG_RSI_MAX
            and galaxy_ok_strong
            and change <= STRONG_CHANGE_MAX
            and ai_ok_forte):
        reasons.append(f"RSI={rsi} (≤{STRONG_RSI_MAX})")
        reasons.append(f"Galaxy={galaxy} (≥{STRONG_GALAXY_MIN})")
        reasons.append(f"Queda 24h={change:+.1f}% (≤{STRONG_CHANGE_MAX}%)")
        return _make_result(symbol, "FORTE", ai_score, ai_veredicto, reasons)

    # MODERADO: critérios relaxados
    if (rsi <= MODERATE_RSI_MAX
            and galaxy_ok_moderate
            and ai_ok_moderate):
        reasons.append(f"RSI={rsi} (≤{MODERATE_RSI_MAX})")
        reasons.append(f"Galaxy={galaxy} (≥{MODERATE_GALAXY_MIN})")
        return _make_result(symbol, "MODERADO", ai_score, ai_veredicto, reasons)

    # AGUARDAR: critérios insuficientes
    reasons.append(
        f"Critérios insuficientes — RSI={rsi}, galaxy={galaxy}, "
        f"change={change:+.1f}%, ai_score={ai_score}"
    )
    return _make_result(symbol, "AGUARDAR", ai_score, ai_veredicto, reasons)


def _make_result(symbol, decision, ai_score, ai_veredicto, reasons) -> dict:
    logger.info(f"[DECISION] {symbol}: {decision} | ai={ai_score} | {' | '.join(reasons[:2])}")
    return {
        "symbol": symbol,
        "decision": decision,
        "ai_score": ai_score,
        "ai_veredicto": ai_veredicto,
        "reasons": reasons,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Formatar mensagem para o Telegram
# ---------------------------------------------------------------------------

def format_telegram_message(signal: dict, result: dict) -> str:
    """Formata o alerta que será enviado via alerts.py existente."""
    emoji = {"FORTE": "🟢", "MODERADO": "🟡", "AGUARDAR": "⬜", "BLOQUEADO": "🔴"}
    icon = emoji.get(result["decision"], "⬜")

    lines = [
        f"{icon} *{result['symbol']}* — {result['decision']}",
        f"💲 Preço: ${signal['price']:,.2f}",
        f"📉 24h: {signal.get('change_pct_24h', 0):+.2f}%",
        f"📊 RSI(1h): {signal.get('rsi_1h', 'N/A')}",
        f"🌕 Galaxy Score: {signal.get('galaxy_score', 'N/A')}",
        f"🤖 IA Score: {result['ai_score']} | {result['ai_veredicto']}",
        "",
        *[f"• {r}" for r in result["reasons"][:3]],
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    # Teste rápido com dados sintéticos (sem chamar APIs)
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    test_signal = {
        "symbol": "BTCUSDT",
        "price": 98500.0,
        "change_pct_24h": -6.5,
        "volume_usdt_24h": 2_500_000_000,
        "rsi_1h": 31.2,
        "galaxy_score": 62,
        "alt_rank": 1,
        "social_volume_24h": 45000,
        "sentiment": "positive",
    }

    result = evaluate_signal(test_signal, call_ai=False)
    print("\nResultado do teste (sem IA):")
    print(f"  Decisão: {result['decision']}")
    print(f"  Razões: {result['reasons']}")
    print("\nMensagem Telegram:")
    msg = format_telegram_message(test_signal, result)
    # Encoding-safe output (Windows cp1252 não suporta alguns emojis)
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))

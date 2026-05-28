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

from db import is_in_cooldown, register_cooldown
from sentiment_analyzer import analyze_crypto

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds — ajuste conforme seu apetite de risco
# ---------------------------------------------------------------------------

# Sinal FORTE: todos os critérios atendidos
STRONG_RSI_MAX = 32          # RSI abaixo disso = sobrevendido em cripto
STRONG_GALAXY_MIN = 52       # Composite momentum score — exige momentum positivo
STRONG_CHANGE_MAX = -3.0     # Queda mínima 24h para entrada de recuperação
STRONG_AI_SCORE_MIN = 65     # Score mínimo do consenso das IAs

# Sinal MODERADO: critérios relaxados
MODERATE_RSI_MAX = 40
MODERATE_GALAXY_MIN = 48
MODERATE_AI_SCORE_MIN = 55

# Bloqueio por manipulação (detecção nas IAs)
MANIPULATION_VERDICTS = {"MANIPULACAO", "PUMP", "FUD_COORDENADO"}

# Timeout da chamada às IAs (cripto não precisa ser ultra-rápido)
AI_TIMEOUT_SECONDS = 25


# ---------------------------------------------------------------------------
# Análise de sentimento via IAs (reutiliza sentiment_analyzer.py)
# ---------------------------------------------------------------------------

def _build_crypto_prompt(signal: dict) -> str:
    """Constrói o prompt de dados enviado às IAs (contexto vem do system message)."""
    social_vol = signal.get("social_volume_24h", 0) or 0
    social_note = (
        "Nota: volume social é proxy de comunidade (seguidores Twitter+Reddit), "
        "NÃO volume de negociação. Zero indica dado indisponível, não manipulação."
    )
    return (
        f"Ativo: {signal['symbol']}\n"
        f"Preço: ${signal['price']:,.2f}\n"
        f"Variação 24h: {signal.get('change_pct_24h', 0):+.2f}%\n"
        f"RSI(1h): {signal.get('rsi_1h', 'N/A')}\n"
        f"Galaxy Score: {signal.get('galaxy_score', 'N/A')} / 100\n"
        f"Volume social (proxy comunidade): {social_vol:,}\n"
        f"{social_note}\n"
        f"Sentimento: {signal.get('sentiment', 'unknown')}\n\n"
        "IMPORTANTE: volume social zero NÃO é evidência de manipulação — "
        "indica apenas que dados de comunidade não estão disponíveis. "
        "Baseie a avaliação de manipulação APENAS em padrões de preço "
        "(pump súbito, dump rápido, variação >20% em 1h).\n\n"
        'Responda SOMENTE com JSON: '
        '{"score": 0-100, "verdict": "CONFIAVEL|RUIDO|MANIPULACAO|PUMP|FUD_COORDENADO", '
        '"reason": "uma frase curta", "flags": []}'
    )


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
            consensus = analyze_crypto(prompt)
            if consensus:
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

    # --- Passo 1b: Filtro de tendência histórica ---

    hist_position = signal.get("hist_position", "unknown")
    hist_trend    = signal.get("hist_trend", "unknown")
    pct_ma200     = signal.get("pct_from_ma200") or 0

    # Bloqueia entrada se preço está >30% acima da MA200 (topo de ciclo)
    if hist_position == "above_ma200" and pct_ma200 > 30:
        reasons.append(
            f"Preço {pct_ma200:.1f}% acima da MA200 "
            f"— zona historicamente cara, risco elevado"
        )
        return _make_result(symbol, "AGUARDAR", ai_score, ai_veredicto, reasons)

    # Thresholds dinâmicos de RSI e score IA baseados na tendência histórica
    if hist_trend == "downtrend":
        effective_rsi_forte    = 26   # só entra muito sobrevendido em baixa
        effective_rsi_moderate = 30
        ai_score_min_override  = STRONG_AI_SCORE_MIN + 15  # exige 80
        reasons.append("Tendência de baixa — thresholds mais rígidos (RSI forte≤26, mod≤30)")
    elif hist_trend == "uptrend":
        effective_rsi_forte    = STRONG_RSI_MAX    # 32 normal
        effective_rsi_moderate = MODERATE_RSI_MAX  # 40 normal
        ai_score_min_override  = None
    else:  # neutral ou unknown
        effective_rsi_forte    = 30
        effective_rsi_moderate = 37
        ai_score_min_override  = STRONG_AI_SCORE_MIN + 5  # exige 70

    # --- Passo 2: Consenso das IAs (só se indicadores básicos estão ok) ---

    if call_ai:
        logger.info(f"[DECISION] {symbol}: chamando IAs...")
        ai_result = _get_ai_consensus(signal)
        ai_score = ai_result.get("score", 50)
        ai_veredicto = ai_result.get("veredicto", "RUIDO")
        razao = ai_result.get("razao", "")
        reasons.append(f"IA: {ai_veredicto} (score={ai_score}) — {razao}")

        # Bloqueio por manipulação — só bloqueia se score < 20 (alta convicção)
        if ai_veredicto in MANIPULATION_VERDICTS:
            if ai_score < 20:
                return _make_result(symbol, "BLOQUEADO", ai_score, ai_veredicto,
                                    [f"Manipulação detectada: {ai_veredicto} — {razao}"])
            else:
                # Suspeita fraca — rebaixa para AGUARDAR sem bloquear
                logger.info(f"[DECISION] {symbol}: manipulação fraca (score={ai_score}) — AGUARDAR")
                reasons.append(
                    f"IA: suspeita fraca de {ai_veredicto} (score={ai_score}) "
                    "— aguardando confirmação"
                )
                return _make_result(symbol, "AGUARDAR", ai_score, ai_veredicto, reasons)

    # --- Passo 3: Classificação por critérios ---

    galaxy_ok_strong = galaxy is not None and galaxy >= STRONG_GALAXY_MIN
    galaxy_ok_moderate = galaxy is not None and galaxy >= MODERATE_GALAXY_MIN

    # Quando IA não é chamada (backtesting/dry-run), o gate de score não bloqueia
    _forte_threshold = ai_score_min_override if ai_score_min_override else STRONG_AI_SCORE_MIN
    ai_ok_forte   = not call_ai or ai_score >= _forte_threshold
    ai_ok_moderate = not call_ai or ai_score >= MODERATE_AI_SCORE_MIN

    # FORTE: todos os critérios máximos (thresholds dinâmicos por tendência)
    if (rsi <= effective_rsi_forte
            and galaxy_ok_strong
            and change <= STRONG_CHANGE_MAX
            and ai_ok_forte):
        reasons.append(f"RSI={rsi} (≤{effective_rsi_forte})")
        reasons.append(f"Galaxy={galaxy} (≥{STRONG_GALAXY_MIN})")
        reasons.append(f"Queda 24h={change:+.1f}% (≤{STRONG_CHANGE_MAX}%)")
        final_decision = "FORTE"

    # MODERADO: critérios relaxados (thresholds dinâmicos por tendência)
    elif (rsi <= effective_rsi_moderate
            and galaxy_ok_moderate
            and ai_ok_moderate):
        reasons.append(f"RSI={rsi} (≤{effective_rsi_moderate})")
        reasons.append(f"Galaxy={galaxy} (≥{MODERATE_GALAXY_MIN})")
        final_decision = "MODERADO"

    # AGUARDAR: critérios insuficientes
    else:
        reasons.append(
            f"Critérios insuficientes — RSI={rsi}, galaxy={galaxy}, "
            f"change={change:+.1f}%, ai_score={ai_score}"
        )
        final_decision = "AGUARDAR"

    # Cooldown gate: suprime sinais repetidos para o mesmo ativo em 4 horas
    if final_decision in ("FORTE", "MODERADO"):
        if is_in_cooldown(symbol, pipeline='cripto', hours=4):
            logger.info(f"[COOLDOWN] {symbol}: sinal suprimido (cooldown 4h)")
            reasons.insert(0, "Cooldown ativo (4h desde último sinal)")
            final_decision = "AGUARDAR"
        else:
            register_cooldown(symbol, pipeline='cripto')

    return _make_result(symbol, final_decision, ai_score, ai_veredicto, reasons)


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

def _count_open_crypto_positions() -> int:
    """Retorna número de posições cripto abertas no banco."""
    try:
        from db import get_connection
        with get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM crypto_positions WHERE status='open'"
            ).fetchone()[0]
    except Exception:
        return 0


def format_telegram_message(signal: dict, result: dict) -> str:
    """Formata o alerta que será enviado via alerts.py existente."""
    from position_sizing import calculate_position

    emoji = {"FORTE": "🟢", "MODERADO": "🟡", "AGUARDAR": "⬜", "BLOQUEADO": "🔴"}
    icon = emoji.get(result["decision"], "⬜")

    lines = [
        f"{icon} *{result['symbol']}* — {result['decision']}",
        f"💲 Preço: ${signal['price']:,.2f}",
        f"📉 24h: {signal.get('change_pct_24h', 0):+.2f}%",
        f"📊 RSI(1h): {signal.get('rsi_1h', 'N/A')}",
        f"🌕 Galaxy Score: {signal.get('galaxy_score', 'N/A')}",
        f"🤖 IA Score: {result['ai_score']} | {result['ai_veredicto']}",
        f"📈 Histórico: {signal.get('hist_context', 'N/A')}",
        "",
        *[f"• {r}" for r in result["reasons"][:3]],
    ]

    if result["decision"] in ("FORTE", "MODERADO"):
        open_pos = _count_open_crypto_positions()
        sizing = calculate_position(result["decision"], 1000.0, open_pos, signal["price"])
        if sizing["allowed"]:
            lines += [
                "",
                f"💰 Sugestão: ${sizing['alloc_value']:.2f} "
                f"({sizing['alloc_pct']*100:.0f}% de $1.000)",
                f"   = {sizing['units']:.4f} unidades",
                "   ⚠️ Capital padrão: ajuste no dashboard",
            ]
        else:
            lines += ["", f"⛔ Sizing: {sizing['reason']}"]

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

"""
crypto_scanner.py
-----------------
Coleta dados de preço (Binance API) e sentimento social (LunarCrush)
para os pares cripto configurados. Retorna sinais estruturados prontos
para o crypto_decision.py consumir.

Não requer dependências pagas — usa tiers gratuitos de ambas as APIs.
"""

import os
import time
import logging
import requests
import certifi
from datetime import datetime, timezone
from dotenv import load_dotenv

# Sessão com CA bundle explícito — necessário em alguns ambientes Windows
_session = requests.Session()
_session.verify = certifi.where()

load_dotenv()

logger = logging.getLogger(__name__)

# Pares monitorados — ajuste conforme preferência
CRYPTO_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
]

# LunarCrush: mapeamento símbolo → coin (para busca via API)
LUNARCRUSH_MAP = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "BNBUSDT": "binancecoin",
    "SOLUSDT": "solana",
}

BINANCE_BASE = "https://api.binance.com/api/v3"
LUNARCRUSH_BASE = "https://lunarcrush.com/api4/public"


# ---------------------------------------------------------------------------
# Binance — dados de mercado (sem autenticação para dados públicos)
# ---------------------------------------------------------------------------

def get_binance_ticker(symbol: str) -> dict | None:
    """Retorna preço atual, variação 24h e volume do par."""
    try:
        url = f"{BINANCE_BASE}/ticker/24hr"
        resp = _session.get(url, params={"symbol": symbol}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "symbol": symbol,
            "price": float(data["lastPrice"]),
            "change_pct_24h": float(data["priceChangePercent"]),
            "volume_usdt_24h": float(data["quoteVolume"]),
            "high_24h": float(data["highPrice"]),
            "low_24h": float(data["lowPrice"]),
        }
    except Exception as e:
        logger.warning(f"[BINANCE] {symbol}: {e}")
        return None


def get_binance_rsi(symbol: str, interval: str = "1h", periods: int = 14) -> float | None:
    """Calcula RSI(14) usando velas horárias da Binance."""
    try:
        url = f"{BINANCE_BASE}/klines"
        resp = _session.get(url, params={
            "symbol": symbol,
            "interval": interval,
            "limit": periods + 1,
        }, timeout=10)
        resp.raise_for_status()
        klines = resp.json()

        closes = [float(k[4]) for k in klines]  # índice 4 = preço de fechamento
        if len(closes) < periods + 1:
            return None

        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))

        avg_gain = sum(gains) / periods
        avg_loss = sum(losses) / periods

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    except Exception as e:
        logger.warning(f"[BINANCE RSI] {symbol}: {e}")
        return None


# ---------------------------------------------------------------------------
# LunarCrush — sentimento social (tier gratuito: 2.000 créditos/dia)
# ---------------------------------------------------------------------------

def get_lunarcrush_sentiment(coin: str) -> dict | None:
    """
    Retorna score de sentimento social do LunarCrush para a moeda.
    Usa o endpoint /coins/:coin/v1 que consome 1 crédito por chamada.

    Retorna um dicionário com galaxy_score (0-100), alt_rank,
    social_volume_24h e sentiment (positive/negative/neutral).
    """
    api_key = os.getenv("LUNARCRUSH_API_KEY", "")
    if not api_key:
        logger.warning("[LUNARCRUSH] LUNARCRUSH_API_KEY não configurada — pulando sentimento social")
        return None

    try:
        url = f"{LUNARCRUSH_BASE}/coins/{coin}/v1"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = _session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", {})

        galaxy_score = data.get("galaxy_score", 0)
        alt_rank = data.get("alt_rank", 9999)
        social_volume = data.get("social_volume_24h", 0)

        # Sentiment: galaxy_score > 60 = positivo, < 40 = negativo
        if galaxy_score >= 60:
            sentiment = "positive"
        elif galaxy_score <= 40:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "galaxy_score": galaxy_score,
            "alt_rank": alt_rank,
            "social_volume_24h": social_volume,
            "sentiment": sentiment,
        }

    except Exception as e:
        logger.warning(f"[LUNARCRUSH] {coin}: {e}")
        return None


# ---------------------------------------------------------------------------
# Orquestrador do scanner
# ---------------------------------------------------------------------------

def scan_crypto() -> list[dict]:
    """
    Varre todos os CRYPTO_PAIRS e retorna lista de sinais enriquecidos.

    Cada sinal contém:
      - symbol, price, change_pct_24h, volume_usdt_24h
      - rsi_1h
      - galaxy_score, sentiment (LunarCrush, se disponível)
      - scan_ts (ISO UTC)
    """
    signals = []

    for symbol in CRYPTO_PAIRS:
        logger.info(f"[SCANNER] Coletando {symbol}...")

        ticker = get_binance_ticker(symbol)
        if ticker is None:
            logger.warning(f"[SCANNER] {symbol}: sem dados de ticker — pulando")
            continue

        rsi = get_binance_rsi(symbol)

        coin_name = LUNARCRUSH_MAP.get(symbol)
        social = get_lunarcrush_sentiment(coin_name) if coin_name else None

        signal = {
            "symbol": symbol,
            "price": ticker["price"],
            "change_pct_24h": ticker["change_pct_24h"],
            "volume_usdt_24h": ticker["volume_usdt_24h"],
            "rsi_1h": rsi,
            "galaxy_score": social["galaxy_score"] if social else None,
            "alt_rank": social["alt_rank"] if social else None,
            "social_volume_24h": social["social_volume_24h"] if social else None,
            "sentiment": social["sentiment"] if social else "unknown",
            "scan_ts": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"[SCANNER] {symbol} | preço=${signal['price']:,.2f} | "
            f"RSI={signal['rsi_1h']} | galaxy={signal['galaxy_score']} | {signal['sentiment']}"
        )

        signals.append(signal)

        # Pausa entre requisições para não estourar rate limit
        time.sleep(0.5)

    return signals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    results = scan_crypto()
    print(f"\n{len(results)} pares escaneados.")
    for s in results:
        print(
            f"  {s['symbol']:<10} ${s['price']:>12,.2f} | "
            f"RSI={str(s['rsi_1h']):<6} | "
            f"galaxy={str(s['galaxy_score']):<4} | {s['sentiment']}"
        )

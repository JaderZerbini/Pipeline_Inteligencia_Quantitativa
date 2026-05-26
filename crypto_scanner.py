"""
crypto_scanner.py
-----------------
Coleta dados de preço (Binance API) e sentimento social (CoinGecko)
para os pares cripto configurados. Retorna sinais estruturados prontos
para o crypto_decision.py consumir.

Não requer chaves de API — ambas as APIs são públicas e gratuitas.
"""

import os
import platform
import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone
from dotenv import load_dotenv


def _build_session() -> requests.Session:
    """Creates a requests session with retry logic and correct SSL certs."""
    session = requests.Session()

    # Retry on transient server errors (429 handled separately in get_coingecko_data)
    retry = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))

    # SSL: certifi bundle on Windows, system certs on Linux (GitHub Actions)
    if platform.system() == "Windows":
        try:
            import certifi
            session.verify = certifi.where()
        except ImportError:
            pass  # fall back to system certs

    return session


_session = _build_session()

load_dotenv()

logger = logging.getLogger(__name__)

# Pares monitorados — ajuste conforme preferência
CRYPTO_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
]

COINGECKO_MAP = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "BNBUSDT": "binancecoin",
    "SOLUSDT": "solana",
}

BINANCE_BASE = "https://api.binance.com/api/v3"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"


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
# CoinGecko — dados de mercado e proxy de sentimento (API pública gratuita)
# ---------------------------------------------------------------------------

def get_coingecko_data(coin_id: str) -> dict | None:
    """
    Fetches market data from CoinGecko free API (no key required).
    Returns sentiment proxy built from price change metrics.

    Endpoint: /api/v3/coins/{id}
    Free tier: 10-30 calls/minute — sufficient for 4 coins 2x/day.
    """
    try:
        url = f"{COINGECKO_BASE}/coins/{coin_id}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true",
            "developer_data": "false",
        }
        data = None
        for attempt in range(3):
            try:
                resp = _session.get(url, params=params, timeout=15)
                if resp.status_code == 429:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"[COINGECKO] {coin_id}: rate limit (429) — aguardando {wait}s (tentativa {attempt+1}/3)")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                logger.warning(f"[COINGECKO] {coin_id}: {e}")
                return None

        if data is None:
            logger.warning(f"[COINGECKO] {coin_id}: falhou após 3 tentativas")
            return None

        market = data.get("market_data", {})
        community = data.get("community_data", {})

        # Price change metrics as sentiment proxy
        change_1h  = market.get("price_change_percentage_1h_in_currency",  {}).get("usd", 0) or 0
        change_24h = market.get("price_change_percentage_24h", 0) or 0
        change_7d  = market.get("price_change_percentage_7d", 0) or 0

        # Community size as social volume proxy
        twitter_followers  = community.get("twitter_followers", 0) or 0
        reddit_subscribers = community.get("reddit_subscribers", 0) or 0
        social_volume = twitter_followers + reddit_subscribers

        # Market cap rank as quality filter (lower rank = better)
        market_cap_rank = data.get("market_cap_rank", 999) or 999

        # --- Composite momentum score (0-100) ---
        # Uses multiple independent signals to reduce constant-55 problem

        score = 50.0  # neutral baseline

        # Signal 1: short-term momentum (1h) — weight 15
        if change_1h > 1.0:    score += 8
        elif change_1h > 0.3:  score += 4
        elif change_1h < -1.0: score -= 8
        elif change_1h < -0.3: score -= 4

        # Signal 2: medium-term momentum (24h) — weight 25
        if change_24h > 5.0:    score += 15
        elif change_24h > 2.0:  score += 8
        elif change_24h > 0.5:  score += 3
        elif change_24h < -5.0: score -= 15
        elif change_24h < -2.0: score -= 8
        elif change_24h < -0.5: score -= 3

        # Signal 3: trend momentum (7d) — weight 20
        if change_7d > 15.0:    score += 12
        elif change_7d > 5.0:   score += 6
        elif change_7d < -15.0: score -= 12
        elif change_7d < -5.0:  score -= 6

        # Signal 4: market cap quality — weight 10
        if market_cap_rank <= 5:    score += 8
        elif market_cap_rank <= 20: score += 5
        elif market_cap_rank <= 50: score += 2
        elif market_cap_rank > 200: score -= 5

        # Signal 5: community size relative proxy — weight 10
        if social_volume > 5_000_000:   score += 5
        elif social_volume > 1_000_000: score += 2

        momentum_score = round(max(0, min(100, score)))

        if momentum_score >= 60:
            sentiment = "positive"
        elif momentum_score <= 40:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "momentum_score": momentum_score,
            "alt_rank": market_cap_rank,
            "social_volume_24h": social_volume,
            "sentiment": sentiment,
            "change_1h": change_1h,
            "change_7d": change_7d,
        }

    except Exception as e:
        logger.warning(f"[COINGECKO] {coin_id}: {e}")
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
      - galaxy_score, sentiment (CoinGecko, se disponível)
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

        coin_id = COINGECKO_MAP.get(symbol)
        social = get_coingecko_data(coin_id) if coin_id else None

        signal = {
            "symbol": symbol,
            "price": ticker["price"],
            "change_pct_24h": ticker["change_pct_24h"],
            "volume_usdt_24h": ticker["volume_usdt_24h"],
            "rsi_1h": rsi,
            "galaxy_score": social["momentum_score"] if social else None,
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

        # Pausa entre requisições para respeitar rate limit do CoinGecko
        time.sleep(3.0)

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

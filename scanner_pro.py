import logging
import requests
import pytz
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone
from db import save_signal

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Backtest-approved: win_rate >= 55% AND sharpe >= 0.5 across 2 years
TICKERS_PRIORITARIOS = [
    "SBSP3.SA", "VALE3.SA", "ITUB4.SA",
    "PETR4.SA", "B3SA3.SA", "BBDC4.SA",
]

# Under observation: insufficient trade count or borderline metrics
TICKERS_OBSERVACAO = [
    "VBBR3.SA", "GGBR4.SA", "RDOR3.SA", "EQTL3.SA",
]

# Permanently removed — RSI strategy consistently fails on these:
# CSAN3, RENT3, WEGE3, SUZB3, PRIO3

TICKERS = TICKERS_PRIORITARIOS + TICKERS_OBSERVACAO


def is_market_open() -> bool:
    """Return True when B3 regular session is active (Mon–Fri 10:00–17:30 BRT)."""
    br_tz = pytz.timezone("America/Sao_Paulo")
    now   = datetime.now(br_tz)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=10, minute=0,  second=0, microsecond=0)
    market_close = now.replace(hour=17, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def get_brapi_top_tickers() -> list[str]:
    """Return top-20 most-traded B3 tickers from Brapi this week."""
    try:
        r = requests.get(
            "https://brapi.dev/api/quote/list?sortBy=volume&sortOrder=desc&limit=20",
            timeout=5,
        )
        data = r.json().get("stocks", [])
        return [f"{s['stock']}.SA" for s in data if s.get("stock")]
    except Exception as e:
        print(f"[BRAPI WARN] {e}")
        return []


def scanner_pro(tickers: list[str] | None = None) -> pd.DataFrame:
    """Scan tickers for RSI momentum signals above EMA-20.

    When called without args, merges the curated TICKERS list with the
    Brapi weekly top-20 to produce a live 20-35 ticker universe.
    Accepts tickers with or without the '.SA' suffix.

    Args:
        tickers: Optional override list. Uses curated + Brapi when None.

    Returns:
        DataFrame of BUY signals with columns:
        Ticker, signal_id, Preco, RSI, volume_ratio, Distancia_Media.
        Empty DataFrame when no signals found.
    """
    if tickers is None:
        brapi = get_brapi_top_tickers()
        raw = list({t.replace(".SA", "") for t in TICKERS + brapi})
    else:
        raw = [t.replace(".SA", "") for t in tickers]

    if not is_market_open():
        print("[INFO] Mercado fechado — usando último pregão disponível")
    print(f"Varrendo {len(raw)} tickers em busca de foguetes...")

    sa_list = [t + ".SA" for t in raw]
    data = yf.download(sa_list, period="6mo", group_by="ticker", progress=False, auto_adjust=True)

    oportunidades = []

    for ticker in raw:
        t_sa = ticker + ".SA"
        try:
            df = data[t_sa].copy().dropna()
        except KeyError:
            print(f"[WARN] {ticker}: sem dados — pulando")
            continue

        if df is None or df.empty or len(df) < 30:
            continue

        df["EMA_20"] = ta.ema(df["Close"], length=20)
        df["RSI"]    = ta.rsi(df["Close"], length=14)

        last_row = df.iloc[-1]
        if pd.isna(last_row["EMA_20"]) or pd.isna(last_row["RSI"]):
            continue

        # Use only sessions with actual volume; the current candle may be
        # incomplete (volume=0) when the market is closed or mid-session.
        recent_volumes = df["Volume"].dropna()
        recent_volumes = recent_volumes[recent_volumes > 0]

        if len(recent_volumes) < 5:
            print(f"[SKIP] {ticker}: histórico de volume insuficiente")
            continue

        last_complete_volume = float(recent_volumes.iloc[-1])
        avg_volume_20d       = float(recent_volumes.iloc[-21:-1].mean())

        if avg_volume_20d <= 0:
            print(f"[SKIP] {ticker}: média de volume zerada")
            continue

        volume_ratio = last_complete_volume / avg_volume_20d

        current_price = float(last_row["Close"])
        if current_price < 1.0:
            print(f"[SKIP] {ticker}: preço R${current_price:.2f} abaixo do mínimo")
            continue

        now = datetime.now(timezone.utc).isoformat()

        # Entry signal: price above EMA-20 AND RSI in momentum zone (not exhausted)
        if current_price > last_row["EMA_20"] and 55 < last_row["RSI"] < 68:
            signal_id = save_signal(
                timestamp=now,
                ticker=ticker,
                rsi=float(last_row["RSI"]),
                volume_ratio=volume_ratio,
                price=current_price,
                signal_type="BUY",
            )
            oportunidades.append({
                "Ticker":         ticker,
                "signal_id":      signal_id,
                "Preço":          current_price,
                "RSI":            float(last_row["RSI"]),
                "volume_ratio":   volume_ratio,
                "Distancia_Media": ((current_price / last_row["EMA_20"]) - 1) * 100,
            })

    return pd.DataFrame(oportunidades)


if __name__ == "__main__":
    top_picks = scanner_pro()
    print("\n--- FOGUETES ENCONTRADOS ---")
    if top_picks.empty:
        print("Nenhum sinal no momento.")
    else:
        print(top_picks.sort_values(by="RSI", ascending=False).to_string(index=False))

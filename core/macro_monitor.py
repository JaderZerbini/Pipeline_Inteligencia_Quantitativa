"""Macro-economic context layer for Terminal Quant.

Fetches commodity prices, FX, and SELIC rate, then maps each ticker to
the subset of indicators that actually drive its sector.
"""

import requests
import yfinance as yf
from datetime import datetime

MACRO_DEPENDENCIES = {
    "PETR4":   ["brent", "wti", "usdbrl"],
    "PRIO3":   ["brent", "wti", "usdbrl"],
    "VALE3":   ["iron_ore", "china_etf", "usdbrl"],
    "ITUB4":   ["usdbrl", "selic"],
    "BBDC4":   ["usdbrl", "selic"],
    "WEGE3":   ["usdbrl"],
    "RENT3":   ["usdbrl", "selic"],
    "CASH3":   ["usdbrl", "selic"],
    "DEFAULT": ["usdbrl"],
}

_cache: dict = {"snapshot": None, "fetched_at": None}
CACHE_MINUTES = 15


def fetch_macro_snapshot() -> dict:
    """Fetch live macro indicators, returning a cached copy when fresh enough."""
    now = datetime.now()
    if _cache["fetched_at"] and (now - _cache["fetched_at"]).seconds < CACHE_MINUTES * 60:
        return _cache["snapshot"]

    snapshot: dict = {}
    tickers = {
        "brent":     "BZ=F",
        "wti":       "CL=F",
        "iron_ore":  "VALE3.SA",   # proxy: VALE tracks iron ore closely; TIO=F delisted
        "china_etf": "FXI",
        "usdbrl":    "USDBRL=X",
    }
    for key, symbol in tickers.items():
        try:
            info = yf.Ticker(symbol).fast_info
            price = info.last_price
            prev = info.previous_close
            change_pct = ((price - prev) / prev) * 100 if prev else 0.0
            snapshot[key] = {"price": round(price, 4), "change_pct": round(change_pct, 2)}
        except Exception as e:
            print(f"[MACRO WARN] {key} ({symbol}): {e}")
            snapshot[key] = None

    try:
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
        r = requests.get(url, timeout=5)
        rate = float(r.json()[0]["valor"].replace(",", "."))
        snapshot["selic"] = {"rate": rate}
    except Exception as e:
        print(f"[MACRO WARN] SELIC: {e}")
        snapshot["selic"] = None

    snapshot["fetched_at"] = now.isoformat()
    _cache["snapshot"] = snapshot
    _cache["fetched_at"] = now
    return snapshot


def evaluate_macro(ticker: str, snapshot: dict) -> dict:
    """Score macro headwinds/tailwinds for a ticker based on its sector dependencies."""
    deps = MACRO_DEPENDENCIES.get(ticker.replace(".SA", ""), MACRO_DEPENDENCIES["DEFAULT"])
    score_adjustment = 0
    flags: list[str] = []
    warnings: list[str] = []

    if "brent" in deps and snapshot.get("brent"):
        chg = snapshot["brent"]["change_pct"]
        if chg <= -3.0:
            score_adjustment -= 25
            flags.append("BRENT_QUEDA_FORTE")
            warnings.append(f"Brent -{abs(chg):.1f}% hoje")
        elif chg <= -1.5:
            score_adjustment -= 12
            flags.append("BRENT_QUEDA_MODERADA")
        elif chg >= 2.0:
            score_adjustment += 10
            flags.append("BRENT_ALTA")

    if "iron_ore" in deps and snapshot.get("iron_ore"):
        chg = snapshot["iron_ore"]["change_pct"]
        if chg <= -3.0:
            score_adjustment -= 25
            flags.append("MINERIO_QUEDA_FORTE")
            warnings.append(f"Minério -{abs(chg):.1f}% hoje")
        elif chg <= -1.5:
            score_adjustment -= 12
            flags.append("MINERIO_QUEDA_MODERADA")
        elif chg >= 2.0:
            score_adjustment += 10
            flags.append("MINERIO_ALTA")

    if "usdbrl" in deps and snapshot.get("usdbrl"):
        chg = snapshot["usdbrl"]["change_pct"]
        if chg >= 1.5:
            score_adjustment -= 15
            flags.append("USDBRL_STRESS")
            warnings.append(f"USD/BRL +{chg:.1f}% — risco-off")
        elif chg <= -1.5:
            score_adjustment += 5
            flags.append("USDBRL_ESTAVEL")

    if "selic" in deps and snapshot.get("selic"):
        rate = snapshot["selic"]["rate"]
        if rate >= 13.0:
            score_adjustment -= 10
            flags.append("SELIC_ALTA")
        elif rate <= 10.0:
            score_adjustment += 5
            flags.append("SELIC_FAVORAVEL")

    return {
        "score_adjustment": score_adjustment,
        "flags": flags,
        "warnings": warnings,
        "macro_ok": score_adjustment >= -15,
    }


def _fmt_chg(val: float | None) -> str:
    if val is None:
        return "  —  "
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def _fmt_price(val: float | None) -> str:
    if val is None:
        return "   —   "
    return f"{val:.2f}"


def print_snapshot(snapshot: dict) -> None:
    rows = [
        ("Brent",      snapshot.get("brent")),
        ("WTI",        snapshot.get("wti")),
        ("Minerio Fe", snapshot.get("iron_ore")),
        ("USD/BRL",    snapshot.get("usdbrl")),
    ]

    sep = "+" + "-" * 13 + "+" + "-" * 11 + "+" + "-" * 10 + "+"
    print(sep)
    print(f"| {'Indicador':<11} | {'Preco':>9} | {'Variacao':>8} |")
    print(sep)
    for label, data in rows:
        price = _fmt_price(data["price"] if data else None)
        chg   = _fmt_chg(data["change_pct"] if data else None)
        print(f"| {label:<11} | {price:>9} | {chg:>8} |")

    selic = snapshot.get("selic")
    selic_str = f"{selic['rate']:.2f}%" if selic else "-"
    print(f"| {'SELIC':<11} | {selic_str:>9} | {'--':>8} |")
    print(sep)
    fetched = snapshot.get("fetched_at", "?")
    print(f"  Atualizado: {fetched}")


if __name__ == "__main__":
    snap = fetch_macro_snapshot()
    print_snapshot(snap)

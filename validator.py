"""System validator and calibration tool for Terminal Quant.

Audits each pipeline layer independently:
  1. Price data  — yfinance vs Brapi cross-check
  2. RSI         — pandas_ta vs Wilder's EWM reference
  3. News        — relevance and completeness
  4. AI models   — calibration against known good/bad/manipulation headlines
  5. Macro data  — Brent and SELIC range sanity checks
"""

import argparse

import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf

from news_fetcher import buscar_noticias_ticker
from sentiment_analyzer import analyze_news

# ---------------------------------------------------------------------------
# Keyword map: used to evaluate news relevance per ticker
# ---------------------------------------------------------------------------

_TICKER_KEYWORDS: dict[str, list[str]] = {
    "PETR4": ["petr4", "petrobras", "petroleo", "petróleo", "brent", "wti", "oil", "opec", "crude"],
    "VALE3": ["vale3", "vale", "minerio", "minério", "iron ore", "china", "aço", "aco", "steel"],
    "ITUB4": ["itub4", "itaú", "itau", "selic", "banco", "juros", "ipca"],
    "BBDC4": ["bbdc4", "bradesco", "selic", "juros", "banco"],
    "WEGE3": ["wege3", "weg", "eolica", "eólica", "solar", "energia"],
    "PRIO3": ["prio3", "petrio", "petrorio", "offshore", "pre-sal", "pré-sal"],
    "SUZB3": ["suzb3", "suzano", "celulose", "pulp", "papel"],
    "RENT3": ["rent3", "localiza", "locadora", "aluguel"],
    "B3SA3": ["b3sa3", "b3 ", " b3", "bolsa", "exchange"],
}


# ---------------------------------------------------------------------------
# 1. Price data validation
# ---------------------------------------------------------------------------

def validate_price_data(ticker: str) -> dict:
    """Compare last price from yfinance vs Brapi; flag divergence > 2%."""
    ticker_clean = ticker.replace(".SA", "")
    ticker_sa    = ticker_clean + ".SA"
    result: dict = {
        "ticker":         ticker_clean,
        "yfinance_price": None,
        "brapi_price":    None,
        "divergence_pct": None,
        "status":         "ERROR",
    }

    try:
        result["yfinance_price"] = round(float(yf.Ticker(ticker_sa).fast_info.last_price), 2)
    except Exception as e:
        result["error"] = f"yfinance: {e}"
        return result

    try:
        r = requests.get(f"https://brapi.dev/api/quote/{ticker_clean}", timeout=6)
        data = r.json().get("results", [{}])[0]
        result["brapi_price"] = round(float(data["regularMarketPrice"]), 2)
    except Exception as e:
        result["error"] = f"brapi: {e}"
        return result

    yf_p = result["yfinance_price"]
    br_p = result["brapi_price"]
    div  = abs(yf_p - br_p) / yf_p * 100
    result["divergence_pct"] = round(div, 2)
    result["status"]         = "DIVERGENCE" if div > 2.0 else "OK"
    return result


# ---------------------------------------------------------------------------
# 2. RSI validation
# ---------------------------------------------------------------------------

def _rsi_wilder(close: pd.Series, period: int = 14) -> float:
    """Wilder's EWM RSI — independent reference implementation."""
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs       = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs.iloc[-1])))


def validate_rsi(ticker: str) -> dict:
    """Compare pandas_ta RSI (system) against Wilder's EWM RSI (reference)."""
    ticker_clean = ticker.replace(".SA", "")
    ticker_sa    = ticker_clean + ".SA"
    result: dict = {
        "ticker":        ticker_clean,
        "rsi_system":    None,
        "rsi_reference": None,
        "delta":         None,
        "status":        "ERROR",
    }

    try:
        hist = yf.Ticker(ticker_sa).history(period="3mo")
        if hist.empty or len(hist) < 20:
            result["error"] = "Dados insuficientes"
            return result

        close   = hist["Close"].squeeze()
        rsi_sys = float(ta.rsi(close, length=14).iloc[-1])
        rsi_ref = _rsi_wilder(close, period=14)
        delta   = abs(rsi_sys - rsi_ref)

        result.update({
            "rsi_system":    round(rsi_sys, 2),
            "rsi_reference": round(rsi_ref, 2),
            "delta":         round(delta, 2),
            "status":        "WARNING" if delta > 3.0 else "OK",
        })
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# 3. News relevance validation
# ---------------------------------------------------------------------------

def validate_news_relevance(ticker: str) -> dict:
    """Check that fetched headlines are non-empty and relevant to the ticker."""
    ticker_clean = ticker.replace(".SA", "")
    headlines    = buscar_noticias_ticker(ticker_clean)
    char_count   = len(headlines)

    keywords     = _TICKER_KEYWORDS.get(ticker_clean, [ticker_clean.lower()])
    has_mention  = any(kw in headlines.lower() for kw in keywords)

    if headlines.strip() == "Nenhuma notícia recente encontrada." or char_count < 20:
        status = "EMPTY"
    elif char_count < 50:
        status = "TOO_SHORT"
    elif not has_mention:
        status = "IRRELEVANT"
    else:
        status = "OK"

    return {
        "ticker":             ticker_clean,
        "headlines_fetched":  headlines,
        "char_count":         char_count,
        "has_ticker_mention": has_mention,
        "status":             status,
    }


# ---------------------------------------------------------------------------
# 4. AI calibration validation
# ---------------------------------------------------------------------------

def validate_ai_consensus(ticker: str, test_headline: str = "") -> dict:
    """Send known-good, known-bad, and manipulation headlines; verify scores.

    Expected: good >= 65, bad <= 40, manipulation <= 25.
    Status:
      BROKEN — good < 50 OR manipulation > 50
      WEAK   — good < 65 OR manipulation > 35
      OK     — all thresholds met
    """
    ticker_clean = ticker.replace(".SA", "")

    good_hl  = (
        f"{ticker_clean} reporta lucro acima do esperado com crescimento de 25% "
        f"na receita, segundo resultado publicado no RI da empresa"
    )
    bad_hl   = (
        f"BOMBA: {ticker_clean} vai EXPLODIR amanhã, fonte confiável "
        f"garante ganhos de 500%"
    )
    manip_hl = f"Insiders revelam: compre {ticker_clean} AGORA antes do anúncio secreto"

    good_r  = analyze_news(good_hl,  ticker_clean)
    bad_r   = analyze_news(bad_hl,   ticker_clean)
    manip_r = analyze_news(manip_hl, ticker_clean)

    good_score  = good_r.get("score", 0)
    bad_score   = bad_r.get("score", 100)
    manip_score = manip_r.get("score", 100)

    if good_score < 50 or manip_score > 50:
        cal_status = "BROKEN"
    elif good_score < 65 or manip_score > 35:
        cal_status = "WEAK"
    else:
        cal_status = "OK"

    return {
        "good_headline_score":  good_score,
        "bad_headline_score":   bad_score,
        "manipulation_score":   manip_score,
        "good_verdict":         good_r.get("verdict", "?"),
        "bad_verdict":          bad_r.get("verdict", "?"),
        "manipulation_verdict": manip_r.get("verdict", "?"),
        "calibration_status":   cal_status,
    }


# ---------------------------------------------------------------------------
# 5. Macro data validation
# ---------------------------------------------------------------------------

def validate_macro_data() -> dict:
    """Validate Brent and SELIC against known plausible ranges."""
    result: dict = {"brent": None, "selic": None, "flags": [], "status": "ERROR"}
    flags: list[str] = []

    try:
        brent = round(float(yf.Ticker("BZ=F").fast_info.last_price), 2)
        result["brent"] = brent
        if not (50 <= brent <= 120):
            flags.append(f"BRENT_SUSPEITO ({brent})")
    except Exception as e:
        flags.append(f"BRENT_ERRO ({e})")

    try:
        r = requests.get(
            "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json",
            timeout=5,
        )
        selic = float(r.json()[0]["valor"].replace(",", "."))
        result["selic"] = selic
        if not (6.0 <= selic <= 16.0):
            flags.append(f"SELIC_SUSPEITO ({selic}%)")
    except Exception as e:
        flags.append(f"SELIC_ERRO ({e})")

    result["flags"]  = flags
    result["status"] = "SUSPICIOUS" if flags else "OK"
    return result


# ---------------------------------------------------------------------------
# 6. Full validation report
# ---------------------------------------------------------------------------

def run_full_validation(tickers: list[str] | None = None) -> None:
    """Run all validations and print a formatted report to stdout."""
    if tickers is None:
        tickers = ["PETR4.SA", "VALE3.SA", "ITUB4.SA"]

    W      = 52   # inner content width (between "|| " and " ||")
    border = "=" * (W + 2)

    def row(text: str) -> None:
        print(f"║ {text:<{W}} ║")

    def blank() -> None:
        row("")

    print(f"╔{border}╗")
    title = "RELATORIO DE VALIDACAO DO SISTEMA"
    print(f"║{title:^{W + 2}}║")
    print(f"╠{border}╣")

    # ── Price ──────────────────────────────────────────────────────────────
    row("DADOS DE PRECO")
    for t in tickers:
        pr = validate_price_data(t)
        lbl = pr["ticker"]
        if pr["status"] == "ERROR":
            row(f"  {lbl}: ERRO — {pr.get('error', '')}")
        elif pr["status"] == "OK":
            row(f"  {lbl}: yfinance=R${pr['yfinance_price']} | brapi=R${pr['brapi_price']} [OK]")
        else:
            row(f"  {lbl}: yfinance=R${pr['yfinance_price']} | brapi=R${pr['brapi_price']} [DIVERGENCIA {pr['divergence_pct']:.1f}%]")
    blank()

    # ── RSI ────────────────────────────────────────────────────────────────
    row("CALCULO RSI")
    for t in tickers:
        rr = validate_rsi(t)
        lbl = rr["ticker"]
        if rr["status"] == "ERROR":
            row(f"  {lbl}: ERRO — {rr.get('error', '')}")
        elif rr["status"] == "OK":
            row(f"  {lbl}: sistema={rr['rsi_system']} | ref={rr['rsi_reference']} [OK] (delta {rr['delta']})")
        else:
            row(f"  {lbl}: sistema={rr['rsi_system']} | ref={rr['rsi_reference']} [AVISO] (delta {rr['delta']})")
    blank()

    # ── News ───────────────────────────────────────────────────────────────
    row("NOTICIAS BUSCADAS")
    for t in tickers:
        nr    = validate_news_relevance(t)
        lbl   = nr["ticker"]
        n_items = nr["headlines_fetched"].count("|") + 1 if nr["status"] != "EMPTY" else 0
        status_lbl = "OK" if nr["status"] == "OK" else nr["status"]
        row(f"  {lbl}: {n_items} manchete(s) | {status_lbl}")
        hl = nr["headlines_fetched"]
        chunk_size = W - 4
        for chunk in [hl[i:i + chunk_size] for i in range(0, min(len(hl), chunk_size * 3), chunk_size)]:
            row(f"    {chunk}")
    blank()

    # ── AI calibration ─────────────────────────────────────────────────────
    row("CALIBRACAO DA IA")
    cal = validate_ai_consensus(tickers[0])
    g_lbl = "OK"    if cal["good_headline_score"] >= 65  else "FRACO"
    b_lbl = "OK"    if cal["bad_headline_score"]  <= 40  else "FRACO"
    m_lbl = "OK"    if cal["manipulation_score"]  <= 25  else "FRACO"
    row(f"  Manchete boa:  score={cal['good_headline_score']} {cal['good_verdict']} [{g_lbl}]")
    row(f"  Manchete ruim: score={cal['bad_headline_score']} {cal['bad_verdict']} [{b_lbl}]")
    row(f"  Manipulacao:   score={cal['manipulation_score']} {cal['manipulation_verdict']} [{m_lbl}]")
    row(f"  Status: {cal['calibration_status']}")
    blank()

    # ── Macro ──────────────────────────────────────────────────────────────
    row("DADOS MACRO")
    mr = validate_macro_data()
    brent_str = f"${mr['brent']:.2f}" if mr.get("brent") else "ERRO"
    selic_str = f"{mr['selic']:.2f}%" if mr.get("selic") else "ERRO"
    macro_lbl = "OK" if mr["status"] == "OK" else "SUSPEITO"
    row(f"  Brent: {brent_str} | SELIC: {selic_str} | {macro_lbl}")
    for flag in mr.get("flags", []):
        row(f"  AVISO: {flag}")

    print(f"╚{border}╝")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Terminal Quant — validacao do sistema")
    parser.add_argument("--ticker", default=None, help="Ticker a validar (ex: PETR4.SA)")
    args = parser.parse_args()

    run_full_validation(tickers=[args.ticker] if args.ticker else None)

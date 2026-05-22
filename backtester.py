"""Historical strategy backtester aligned with the MODERADO rule in decision_engine.py.

Entry:  RSI(14) < 38  AND  volume_ratio > 1.2
Exit:   +15% take-profit  OR  -7% fixed stop loss from entry price

RSI is computed with Wilder's exponential smoothing — no TA-Lib or pandas_ta.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

_DATA_DIR    = Path("data")
_RESULTS_PATH = _DATA_DIR / "backtest_results.json"

_DEFAULT_TICKERS = [
    "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA",
    "WEGE3.SA", "RENT3.SA", "B3SA3.SA", "SUZB3.SA",
    "RDOR3.SA", "GGBR4.SA", "VBBR3.SA", "PRIO3.SA",
    "CPLE6.SA", "CSAN3.SA", "EQTL3.SA", "SBSP3.SA",
]

_TAKE_PROFIT = 0.15   # +15% from entry price
_STOP_LOSS   = 0.07   # -7%  from entry price


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI using exponential smoothing — no external TA library.

    Uses ``ewm(alpha=1/period, adjust=False)`` which is mathematically
    equivalent to Wilder's smoothed moving average. Rows inside the warm-up
    window are left as NaN and dropped by the caller's ``dropna``.

    Args:
        close:  Daily closing price series.
        period: Look-back window; defaults to 14.

    Returns:
        RSI series with the same index as ``close``.
    """
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    # Dividing by NaN (when avg_loss == 0) produces NaN → those rows are dropped
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))


def _print_summary(results: list[dict]) -> None:
    """Render a fixed-width ASCII table to stdout."""
    fmt    = "{:<12} {:>7} {:>8} {:>10} {:>9} {:>8}"
    header = fmt.format("Ticker", "Trades", "Win%", "AvgRet%", "MaxDD%", "Sharpe")
    rule   = "=" * len(header)
    sep    = "-" * len(header)

    print(f"\n{rule}")
    print("RESULTADOS DO BACKTEST")
    print(rule)
    print(header)
    print(sep)
    for r in results:
        print(fmt.format(
            r["ticker"],
            r["total_trades"],
            f"{r['win_rate']:.1f}",
            f"{r['avg_return_pct']:.2f}",
            f"{r['max_drawdown_pct']:.2f}",
            f"{r['sharpe_ratio']:.2f}",
        ))
    print(rule)

    # ── Recommended tickers (minimum viability threshold) ──────────────────
    worthy = [
        r for r in results
        if r["total_trades"] >= 5
        and r["win_rate"]    >= 55.0
        and r["sharpe_ratio"] >= 0.5
    ]
    print("\nATIVOS QUE MERECEM MONITORAMENTO ATIVO")
    print("  (criterio: trades>=5 | win_rate>=55% | sharpe>=0.5)")
    print(sep)
    if worthy:
        for r in sorted(worthy, key=lambda x: x["win_rate"], reverse=True):
            print(fmt.format(
                r["ticker"],
                r["total_trades"],
                f"{r['win_rate']:.1f}",
                f"{r['avg_return_pct']:.2f}",
                f"{r['max_drawdown_pct']:.2f}",
                f"{r['sharpe_ratio']:.2f}",
            ))
    else:
        print("  Nenhum ativo passou nos tres criterios simultaneamente.")
    print(f"{rule}\n")


def _save_results(results: list[dict]) -> None:
    """Write results list to data/backtest_results.json."""
    _DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "results": results,
    }
    with open(_RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Resultados salvos em {_RESULTS_PATH}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_backtest(ticker: str, period_days: int = 730) -> dict | None:
    """Simulate the MODERADO entry rule on historical data for a single ticker.

    Downloads ``period_days + 60`` calendar days so indicators have a 60-day
    warm-up window, then restricts the simulation to the requested period.

    Args:
        ticker:      yfinance symbol, e.g. ``'PETR4.SA'``.
        period_days: Calendar days of history to simulate; default 730 (2 years).

    Returns:
        Metrics dict, or ``None`` when data is unavailable or insufficient.

    Return schema::

        {
            "ticker":           str,
            "total_trades":     int,
            "win_rate":         float,   # 0-100
            "avg_return_pct":   float,
            "max_drawdown_pct": float,   # negative value
            "sharpe_ratio":     float,
            "period_days":      int,
        }
    """
    end   = datetime.today()
    start = end - timedelta(days=period_days + 60)

    try:
        raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    except Exception as exc:
        print(f"[WARN] {ticker}: erro ao baixar dados — {exc}")
        return None

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if raw is None or raw.empty:
        print(f"[WARN] {ticker}: sem dados — pulando")
        return None

    df = raw.copy()

    # --- Indicators ---
    df["RSI"] = _compute_rsi(df["Close"])

    vol_avg_20 = df["Volume"].rolling(20).mean()
    # Replace zero average with NaN to avoid ±inf in the ratio
    df["volume_ratio"] = df["Volume"] / vol_avg_20.replace(0.0, float("nan"))

    df = df.dropna(subset=["RSI", "volume_ratio"]).copy()

    # Restrict simulation to the requested calendar window
    df = df[df.index >= pd.Timestamp(end - timedelta(days=period_days))].copy()

    if len(df) < 10:
        print(f"[WARN] {ticker}: dados insuficientes para simulação — pulando")
        return None

    # --- Simulation ---
    # Equity curve is normalised to 1.0; one position at a time.
    trades:        list[dict] = []
    in_position:   bool  = False
    entry_price:   float = 0.0
    entry_date           = None
    current_value: float = 1.0

    equity = pd.Series(1.0, index=df.index, dtype=float)

    for i in range(len(df)):
        price     = float(df["Close"].iloc[i])
        rsi       = float(df["RSI"].iloc[i])
        vol_ratio = float(df["volume_ratio"].iloc[i])
        date      = df.index[i]

        if in_position:
            ret = (price - entry_price) / entry_price
            if ret >= _TAKE_PROFIT or ret <= -_STOP_LOSS:
                current_value *= (1.0 + ret)
                trades.append({
                    "entry_date": str(entry_date.date()),
                    "exit_date":  str(date.date()),
                    "return_pct": round(ret * 100.0, 2),
                    "win":        ret > 0,
                })
                in_position = False
        else:
            # Entry rule mirrors decision_engine MODERADO conditions
            if rsi < 38.0 and vol_ratio > 1.2:
                in_position = True
                entry_price = price
                entry_date  = date

        equity.iloc[i] = current_value

    # Mark open position to market at last available price
    if in_position:
        last_price = float(df["Close"].iloc[-1])
        ret = (last_price - entry_price) / entry_price
        current_value *= (1.0 + ret)
        trades.append({
            "entry_date": str(entry_date.date()),
            "exit_date":  str(df.index[-1].date()),
            "return_pct": round(ret * 100.0, 2),
            "win":        ret > 0,
        })
        equity.iloc[-1] = current_value

    # --- Metrics ---
    total_trades = len(trades)

    if total_trades == 0:
        return {
            "ticker":           ticker,
            "total_trades":     0,
            "win_rate":         0.0,
            "avg_return_pct":   0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio":     0.0,
            "period_days":      period_days,
        }

    ret_list   = [t["return_pct"] for t in trades]
    win_rate   = sum(t["win"] for t in trades) / total_trades * 100.0
    avg_return = sum(ret_list) / total_trades

    rolling_max  = equity.cummax()
    drawdown     = (equity - rolling_max) / rolling_max * 100.0
    max_drawdown = float(drawdown.min())

    daily_ret = equity.pct_change().dropna()
    sharpe    = 0.0
    if len(daily_ret) > 1 and float(daily_ret.std()) > 0.0:
        sharpe = float((daily_ret.mean() / daily_ret.std()) * (252 ** 0.5))

    return {
        "ticker":           ticker,
        "total_trades":     total_trades,
        "win_rate":         round(win_rate, 2),
        "avg_return_pct":   round(avg_return, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio":     round(sharpe, 2),
        "period_days":      period_days,
    }


def run_full_backtest(tickers: list[str] | None = None) -> list[dict]:
    """Run ``run_backtest()`` for each ticker, print a summary table, and save JSON.

    Args:
        tickers: yfinance symbols to test. Defaults to ``_DEFAULT_TICKERS`` when
                 ``None`` is passed.

    Returns:
        List of result dicts, one per ticker that returned valid data.
    """
    if tickers is None:
        tickers = _DEFAULT_TICKERS

    print(f"Iniciando backtest para {len(tickers)} ticker(s)...\n")
    results: list[dict] = []

    for ticker in tickers:
        print(f"  → {ticker}...", end=" ", flush=True)
        result = run_backtest(ticker)
        if result is not None:
            results.append(result)
            print(
                f"{result['total_trades']} trades | "
                f"win rate {result['win_rate']:.1f}% | "
                f"avg ret {result['avg_return_pct']:.2f}%"
            )

    if results:
        _print_summary(results)
        _save_results(results)
    else:
        print("\nNenhum resultado disponível.")

    return results


if __name__ == "__main__":
    run_full_backtest()

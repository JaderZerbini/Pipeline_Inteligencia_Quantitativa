"""
b3_backtester.py
----------------
Backtesta a estratégia B3 usando dados históricos do Yahoo Finance.

Para cada ativo aprovado (PETR4, VALE3, ITUB4, BBDC4, ABEV3, WEGE3):
  1. Baixa dados históricos via yfinance (gratuito)
  2. Simula sinais RSI + Volume + MA200 dia a dia
  3. Executa compras/vendas fictícias com trailing stop 7%
  4. Calcula win rate, retorno total e drawdown máximo

Uso:
  python b3_backtester.py
  python b3_backtester.py --ticker PETR4 --days 150
  python b3_backtester.py --compare
"""

import argparse
import logging
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

B3_TICKERS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "ABEV3", "WEGE3"]
TRAILING_STOP_PCT = 0.07
INITIAL_CAPITAL = 5000.0
POSITION_SIZE_FORTE = 0.20
POSITION_SIZE_MODERADO = 0.10


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_b3_candles(ticker: str, days: int = 200) -> pd.DataFrame:
    """Downloads daily OHLCV from Yahoo Finance for a B3 ticker."""
    try:
        yf_ticker = f"{ticker}.SA"
        period = f"{max(days + 100, 365)}d"
        df = yf.download(yf_ticker, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            logger.warning(f"[B3] {ticker}: sem dados no Yahoo Finance")
            return pd.DataFrame()
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df["date"] = df.index
        df = df.reset_index(drop=True)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except Exception as e:
        logger.error(f"[B3] {ticker}: {e}")
        return pd.DataFrame()


# ── Indicator calculation ─────────────────────────────────────────────────────

def calculate_b3_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds RSI(14), MA20, MA50, MA200, volume_ratio to dataframe."""
    closes = df["close"].values

    rsi_vals = [None] * len(closes)
    for i in range(14, len(closes)):
        diffs  = [closes[i - 13 + j] - closes[i - 14 + j] for j in range(14)]
        gains  = [max(d, 0) for d in diffs]
        losses = [max(-d, 0) for d in diffs]
        avg_g  = sum(gains) / 14
        avg_l  = sum(losses) / 14
        rsi_vals[i] = 100.0 if avg_l == 0 else round(100 - 100 / (1 + avg_g / avg_l), 2)

    df["rsi"]    = rsi_vals
    df["ma20"]   = df["close"].rolling(20).mean()
    df["ma50"]   = df["close"].rolling(50).mean()
    df["ma200"]  = df["close"].rolling(200).mean()
    df["vol_ma20"]     = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["vol_ma20"]

    return df


# ── Signal generation ─────────────────────────────────────────────────────────

def generate_b3_signal(row: pd.Series) -> str:
    """
    Mirrors decision_engine.py logic with dynamic downtrend thresholds.
    RSI + volume_ratio + MA200 gate.
    """
    rsi   = row.get("rsi")
    vol_r = row.get("volume_ratio")
    close = row["close"]
    ma200 = row.get("ma200")
    ma20  = row.get("ma20")
    ma50  = row.get("ma50")

    if rsi is None or pd.isna(rsi):
        return "AGUARDAR"
    if vol_r is None or pd.isna(vol_r):
        return "AGUARDAR"

    in_downtrend = False
    in_uptrend   = False
    if ma200 and not pd.isna(ma200):
        pct_from_ma200 = (close - ma200) / ma200 * 100
        if pct_from_ma200 > 30:
            return "BLOCKED_MA200"
        if ma20 and ma50 and not pd.isna(ma20) and not pd.isna(ma50):
            in_downtrend = ma20 < ma50
            in_uptrend   = ma20 > ma50

    if in_downtrend:
        rsi_forte    = 25
        rsi_moderado = 28
        vol_forte    = 2.0
        vol_mod      = 1.8
    elif in_uptrend:
        rsi_forte    = 30
        rsi_moderado = 35
        vol_forte    = 1.5
        vol_mod      = 1.2
    else:
        rsi_forte    = 28
        rsi_moderado = 32
        vol_forte    = 1.7
        vol_mod      = 1.4

    if rsi <= rsi_forte and vol_r >= vol_forte:
        return "FORTE"
    if rsi <= rsi_moderado and vol_r >= vol_mod:
        return "MODERADO"
    return "AGUARDAR"


# ── Backtest engine ───────────────────────────────────────────────────────────

def backtest_b3_ticker(ticker: str, df: pd.DataFrame,
                       pos_forte: float = POSITION_SIZE_FORTE,
                       pos_mod: float = POSITION_SIZE_MODERADO) -> dict:
    """Runs full backtest simulation for one B3 ticker."""
    capital  = INITIAL_CAPITAL
    position = None
    trades   = []

    for _, row in df.iterrows():
        if row["rsi"] is None or pd.isna(row["rsi"]):
            continue
        price = row["close"]
        date  = row["date"]

        if position:
            new_high = max(position["high"], price)
            new_stop = new_high * (1 - TRAILING_STOP_PCT)
            position["high"] = new_high
            position["stop"] = new_stop

            if price <= new_stop:
                proceeds = position["qty"] * price
                pnl      = proceeds - position["value"]
                pnl_pct  = (price - position["entry"]) / position["entry"] * 100
                capital  += proceeds
                trades.append({
                    "ticker":      ticker,
                    "entry_date":  position["date"],
                    "exit_date":   date,
                    "entry_price": position["entry"],
                    "exit_price":  price,
                    "pnl":         round(pnl, 2),
                    "pnl_pct":     round(pnl_pct, 2),
                    "exit_reason": "trailing_stop",
                    "signal":      position["signal"],
                })
                position = None
                continue

        signal = generate_b3_signal(row)
        if position is None and signal in ("FORTE", "MODERADO"):
            alloc   = pos_forte if signal == "FORTE" else pos_mod
            value   = capital * alloc
            qty     = value / price
            position = {
                "entry": price,
                "qty":   qty,
                "value": value,
                "stop":  price * (1 - TRAILING_STOP_PCT),
                "high":  price,
                "date":  date,
                "signal": signal,
            }
            capital -= value

    if position:
        price = df.iloc[-1]["close"]
        proceeds = position["qty"] * price
        pnl      = proceeds - position["value"]
        pnl_pct  = (price - position["entry"]) / position["entry"] * 100
        capital  += proceeds
        trades.append({
            "ticker":      ticker,
            "entry_date":  position["date"],
            "exit_date":   df.iloc[-1]["date"],
            "entry_price": position["entry"],
            "exit_price":  price,
            "pnl":         round(pnl, 2),
            "pnl_pct":     round(pnl_pct, 2),
            "exit_reason": "end_of_period",
            "signal":      position["signal"],
        })

    wins   = [t for t in trades if t["pnl"] > 0]
    total_pnl    = sum(t["pnl"] for t in trades)
    win_rate     = len(wins) / len(trades) * 100 if trades else 0
    total_return = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    equity = INITIAL_CAPITAL
    peak   = INITIAL_CAPITAL
    max_dd = 0.0
    for t in trades:
        equity += t["pnl"]
        peak    = max(peak, equity)
        dd      = (peak - equity) / peak * 100
        max_dd  = max(max_dd, dd)

    return {
        "ticker":        ticker,
        "trades":        len(trades),
        "wins":          len(wins),
        "losses":        len(trades) - len(wins),
        "win_rate":      round(win_rate, 1),
        "total_pnl":     round(total_pnl, 2),
        "total_return":  round(total_return, 2),
        "max_drawdown":  round(max_dd, 2),
        "final_capital": round(capital, 2),
        "trade_list":    trades,
    }


# ── Main runner ───────────────────────────────────────────────────────────────

def run_b3_backtest(tickers: list = None, days: int = 150,
                    pos_forte: float = POSITION_SIZE_FORTE,
                    pos_mod: float = POSITION_SIZE_MODERADO) -> list:
    tickers = tickers or B3_TICKERS
    results = []

    print(f"\n{'='*60}")
    print(f"BACKTESTING B3 — ultimos {days} dias")
    print(f"Capital inicial: R$ {INITIAL_CAPITAL:,.2f} por ativo")
    print(f"Position sizing: FORTE={pos_forte*100:.0f}%  MODERADO={pos_mod*100:.0f}%")
    print(f"{'='*60}\n")

    for ticker in tickers:
        logger.info(f"Baixando dados: {ticker}...")
        df = fetch_b3_candles(ticker, days=days + 210)
        if df.empty:
            continue
        df = calculate_b3_indicators(df)
        df = df.tail(days).reset_index(drop=True)
        r  = backtest_b3_ticker(ticker, df, pos_forte, pos_mod)
        results.append(r)

        print(f"{ticker}")
        print(f"  Operacoes: {r['trades']} | Wins: {r['wins']} | Losses: {r['losses']}")
        print(f"  Win rate:  {r['win_rate']}%")
        print(f"  P&L total: R$ {r['total_pnl']:+,.2f} ({r['total_return']:+.2f}%)")
        print(f"  Max drawdown: {r['max_drawdown']}%")

        if r["trade_list"]:
            print("  Operacoes detalhadas:")
            for t in r["trade_list"]:
                icon = "OK" if t["pnl"] > 0 else "XX"
                ed = t["entry_date"].strftime("%d/%m") if hasattr(t["entry_date"], "strftime") else str(t["entry_date"])[:5]
                xd = t["exit_date"].strftime("%d/%m")  if hasattr(t["exit_date"],  "strftime") else str(t["exit_date"])[:5]
                print(
                    f"    [{icon}] {ed}->{xd} | "
                    f"R${t['entry_price']:.2f}->R${t['exit_price']:.2f} | "
                    f"P&L {t['pnl_pct']:+.1f}% ({t['signal']}) | {t['exit_reason']}"
                )
        else:
            print("  0 sinais no periodo (condicoes de mercado nao atingiram os limiares)")
        print()
        time.sleep(1)

    if results:
        total_trades = sum(r["trades"]    for r in results)
        total_wins   = sum(r["wins"]      for r in results)
        total_pnl    = sum(r["total_pnl"] for r in results)
        wr = total_wins / total_trades * 100 if total_trades else 0
        print(f"{'='*60}")
        print(f"RESULTADO B3 COMBINADO")
        print(f"  Total operacoes: {total_trades} | Win rate: {wr:.1f}%")
        print(f"  P&L combinado:   R$ {total_pnl:+,.2f}")
        print(f"{'='*60}\n")

    return results


def run_b3_comparison() -> None:
    """Runs B3 backtest across multiple configurations and prints comparison table."""
    configs = [
        ("Conservador 90d  (20%/10%)",  90,  0.20, 0.10),
        ("Conservador 150d (20%/10%)", 150,  0.20, 0.10),
        ("Moderado    90d  (30%/15%)",  90,  0.30, 0.15),
        ("Moderado    150d (30%/15%)", 150,  0.30, 0.15),
        ("Agressivo   90d  (40%/20%)",  90,  0.40, 0.20),
        ("Agressivo   150d (40%/20%)", 150,  0.40, 0.20),
    ]

    print(f"\n{'='*80}")
    print("COMPARATIVO B3 — todos os ativos combinados")
    print(f"{'='*80}")
    print(f"{'Configuracao':<30} {'Ops':>4} {'Win%':>6} {'P&L':>10} {'Retorno':>8} {'MaxDD':>7}")
    print(f"{'-'*80}")

    best_pnl   = None
    best_label = ""

    for label, days, pf, pm in configs:
        results = []
        for ticker in B3_TICKERS:
            df = fetch_b3_candles(ticker, days=days + 210)
            if df.empty:
                continue
            df = calculate_b3_indicators(df)
            df = df.tail(days).reset_index(drop=True)
            r  = backtest_b3_ticker(ticker, df, pf, pm)
            results.append(r)
            time.sleep(0.5)

        if not results:
            continue

        total_ops  = sum(r["trades"]       for r in results)
        total_wins = sum(r["wins"]         for r in results)
        total_pnl  = sum(r["total_pnl"]   for r in results)
        avg_dd     = sum(r["max_drawdown"] for r in results) / len(results)
        wr         = total_wins / total_ops * 100 if total_ops else 0
        ret        = total_pnl / (INITIAL_CAPITAL * len(results)) * 100

        print(
            f"{label:<30} {total_ops:>4} {wr:>5.1f}% "
            f"R${total_pnl:>+8,.2f} {ret:>+7.2f}% {avg_dd:>6.1f}%"
        )

        if best_pnl is None or total_pnl > best_pnl:
            best_pnl   = total_pnl
            best_label = label

    print(f"{'-'*80}")
    if best_pnl is not None:
        print(f"Melhor configuracao por P&L: {best_label} -> R$ {best_pnl:+,.2f}")
    print(f"{'='*80}\n")
    print("LEGENDA:")
    print("  Conservador: FORTE=20% do capital, MODERADO=10%")
    print("  Moderado:    FORTE=30% do capital, MODERADO=15%")
    print("  Agressivo:   FORTE=40% do capital, MODERADO=20%")
    print("  MaxDD = drawdown maximo medio por ativo")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest B3 usando dados Yahoo Finance")
    parser.add_argument("--ticker",  type=str, default=None,
                        help="Ticker B3 (ex: PETR4). Padrao: todos os 6 ativos")
    parser.add_argument("--days",    type=int, default=150,
                        help="Numero de dias do historico (padrao: 150)")
    parser.add_argument("--compare", action="store_true",
                        help="Rodar comparativo entre todas as configuracoes")
    args = parser.parse_args()

    if args.compare:
        run_b3_comparison()
    elif args.ticker:
        run_b3_backtest(tickers=[args.ticker], days=args.days)
    else:
        run_b3_backtest(days=args.days)

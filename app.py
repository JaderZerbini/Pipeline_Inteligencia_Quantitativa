import json
from datetime import datetime
from pathlib import Path

import sys
import pandas as pd
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

from db import (
    get_all_operations,
    get_closed_operations,
    get_connection,
    get_open_operations,
    get_previous_signal,
    get_signal_by_id,
    get_signals_history,
    save_operation,
)
from decision_engine import BACKTEST_APPROVED
from main import orquestrar_investimento

st.set_page_config(page_title="Terminal Quant - Auditoria Automática", layout="wide")


# ---------------------------------------------------------------------------
# Cached DB helpers (TTL 5 min)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def _cached_signals(days: int = 30):
    return get_signals_history(days)


@st.cache_data(ttl=300)
def _cached_open_ops():
    return get_open_operations()


@st.cache_data(ttl=300)
def _cached_all_ops():
    return get_all_operations()


@st.cache_data(ttl=300)
def _cached_closed_ops():
    return get_closed_operations()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 📊 Desempenho")
    signals    = _cached_signals(30)
    ops_open   = _cached_open_ops()
    ops_closed = [op for op in _cached_all_ops() if op["status"] in ("CLOSED", "STOPPED")]

    col1, col2 = st.columns(2)
    col1.metric("Sinais (30d)", len(signals))
    col2.metric("Posições abertas", len(ops_open))

    if ops_closed:
        win       = sum(1 for o in ops_closed if o.get("pnl_brl") and o["pnl_brl"] > 0)
        win_rate  = (win / len(ops_closed)) * 100
        total_pnl = sum(o.get("pnl_brl") or 0.0 for o in ops_closed)
        st.metric("Win rate", f"{win_rate:.0f}%")
        st.metric("P&L total", f"R$ {total_pnl:+.2f}")

    st.caption(f"🔄 Atualização automática ativa — última: {datetime.now().strftime('%H:%M:%S')}")
    st.markdown("---")

    # FIX 4 — Metrics glossary
    with st.expander("📖 Guia de leitura"):
        st.markdown("""
**RSI:** Mede se o ativo está caro ou barato.
- Abaixo de 38 → possível ponto de compra
- Acima de 60 → caro, evitar

**Volume ratio:** Interesse do mercado hoje vs média.
- Acima de 1.2x → movimento com convicção
- Abaixo de 0.8x → pouco interesse

**Score IA (0-100):** Qualidade das notícias.
- 70-100 → fonte confiável
- 40-69 → ruído, sem fonte primária
- 0-39 → possível manipulação

**Win rate:** % de operações lucrativas no histórico.
- Acima de 55% → estratégia com edge
- Abaixo de 50% → evitar esse ativo

**Sharpe ratio:** Lucro ajustado pelo risco.
- Acima de 1.0 → bom
- Abaixo de 0 → estratégia perde dinheiro
        """)

# ---------------------------------------------------------------------------
# Main area — tabs
# ---------------------------------------------------------------------------

st.title("Auditoria em Tempo Real (Método Frank)")

tab_scanner, tab_sinais, tab_ops, tab_bt, tab_validation, tab_cripto = st.tabs(
    ["🔍 Scanner", "📈 Sinais", "💼 Operações", "🔬 Backtesting", "🧪 Validação", "🪙 Cripto"]
)

# ── Tab 1: Scanner ────────────────────────────────────────────────────────
# FIX 1: recommendation uses evaluate_signal() result from orquestrar_investimento(),
# never independently computed. FIX 3: auto-refresh every 60 s.

with tab_scanner:
    st_autorefresh(interval=300_000, key="scanner_refresh")

    with st.expander("📘 Como ler este painel:", expanded=False):
        st.markdown("""
- **RSI abaixo de 38:** ativo possivelmente subvalorizado
- **Volume acima de 1.2x:** há interesse real no mercado
- **Score IA acima de 70:** notícias verificadas como confiáveis
- **Todos os critérios verdes = sinal válido para análise manual**
        """)

    if "resultados" not in st.session_state:
        with st.spinner("Varrendo mercado e auditando com IA..."):
            st.session_state.resultados = orquestrar_investimento()

    resultados = st.session_state.resultados

    if resultados:
        cols = st.columns(min(len(resultados), 4))
        for i, item in enumerate(resultados):
            with cols[i % len(cols)]:
                rec        = item["Recomendação"]
                confianca  = item.get("Confiança", 0)
                razoes     = item.get("Razões", [])
                analise_ia = item.get("Análise IA", "")

                # Ticker header
                cor_map = {"FORTE": "green", "MODERADO": "orange",
                           "AGUARDAR": "gray", "BLOQUEADO": "red"}
                cor = cor_map.get(rec, "gray")
                st.markdown(f"### :{cor}[{item['Ativo']}]")
                _t = item["Ativo"].replace(".SA", "")
                if _t in BACKTEST_APPROVED:
                    st.caption(":green[✅ validado]")
                else:
                    st.caption(":gray[⚠️ sem histórico]")

                st.metric("Preço Atual",    f"R$ {item.get('Preço', 0):.2f}")
                st.metric("RSI",            f"{item['RSI']:.2f}")
                st.metric("Confiança IA",   f"{confianca:.0%}")

                # FIX 3: delta vs previous scan
                _prev = get_previous_signal(item["Ativo"])
                _curr = get_signal_by_id(item.get("signal_id"))
                if _prev and _curr:
                    _rsi_delta = (_curr.get("rsi") or 0) - (_prev.get("rsi") or 0)
                    _vol_now   = _curr.get("volume_ratio") or 0
                    _vol_delta = _vol_now - (_prev.get("volume_ratio") or 0)
                    _prev_ts   = (_prev.get("created_at") or "")[:16]

                    _rsi_arrow = f"↓ {abs(_rsi_delta):.1f}" if _rsi_delta < 0 else f"↑ {abs(_rsi_delta):.1f}"
                    _rsi_color = "red" if _rsi_delta < 0 else "green"
                    _vol_arrow = f"↑ {abs(_vol_delta):.2f}" if _vol_delta > 0 else f"↓ {abs(_vol_delta):.2f}"
                    _vol_color = "green" if _vol_delta > 0 else "red"

                    st.markdown(
                        f"RSI **{_curr.get('rsi', 0):.2f}** :{_rsi_color}[{_rsi_arrow}]"
                        f"&nbsp;&nbsp; Vol **{_vol_now:.2f}x** :{_vol_color}[{_vol_arrow}]"
                    )
                    st.caption(f"vs varredura anterior ({_prev_ts})")

                    _rsi_falling = _rsi_delta < 0 and (_curr.get("rsi") or 100) < 45
                    _vol_rising  = _vol_delta > 0 and _vol_now > 0.8
                    if _rsi_falling and _vol_rising:
                        st.warning("⚡ Sinal em desenvolvimento")
                    elif _rsi_falling:
                        st.warning("📉 RSI caindo — monitorar")
                    elif _vol_rising:
                        st.success("📈 Volume crescendo")

                # FIX 1: recommendation box driven by decision_engine result
                if rec == "FORTE":
                    st.success(
                        "🟢 SINAL FORTE — Condições técnicas e informacionais favoráveis. "
                        "RSI sobrevendido com volume e notícias verificadas."
                    )
                elif rec == "MODERADO":
                    st.warning(
                        "🟡 SINAL MODERADO — Condições parcialmente favoráveis. "
                        "Analise com cautela."
                    )
                elif rec == "BLOQUEADO":
                    st.error(
                        "🔴 BLOQUEADO — Auditoria detectou possível manipulação. "
                        "Não operar."
                    )
                else:
                    st.info(
                        "⏸ AGUARDAR — Condições insuficientes para entrada. "
                        "RSI ou volume fora dos critérios."
                    )

                with st.expander("🛡️ Ver Relatório Frank"):
                    if razoes:
                        for r in razoes:
                            st.markdown(f"- {r}")
                    if analise_ia:
                        st.caption(analise_ia)
    else:
        st.info("Nenhuma oportunidade técnica encontrada no momento.")

    if st.button("🔄 Varrer agora", key="rescan"):
        st.session_state.pop("resultados", None)
        st.rerun()

# ── Tab 2: Signal history ─────────────────────────────────────────────────

with tab_sinais:
    # FIX 3: auto-refresh every 2 min
    st_autorefresh(interval=300_000, key="sinais_refresh")

    st.subheader("Histórico de Sinais — últimos 30 dias")
    data = _cached_signals(30)

    if data:
        df = pd.DataFrame(data)
        tickers_list    = ["Todos"] + sorted(df["ticker"].unique().tolist())
        selected_ticker = st.selectbox("Filtrar por ativo", tickers_list, key="sinais_filter")
        if selected_ticker != "Todos":
            df = df[df["ticker"] == selected_ticker]

        _ORDERED_COLS = ["recommendation", "timestamp", "ticker", "rsi", "volume_ratio", "price"]
        display_cols = [c for c in _ORDERED_COLS if c in df.columns]
        _COL_RENAME = {
            "recommendation": "Decisão Final",
            "timestamp":      "Data/Hora",
            "ticker":         "Ativo",
            "rsi":            "RSI",
            "volume_ratio":   "Volume (ratio)",
            "price":          "Preço (R$)",
        }
        _SIGNAL_STYLE = {
            "FORTE":    "background-color: #1a3a1a; color: #4caf82",
            "MODERADO": "background-color: #3a2a00; color: #ffc107",
            "AGUARDAR": "background-color: #1a1a2a; color: #888888",
            "BLOQUEADO":"background-color: #3a0a0a; color: #ef5350",
        }
        df_display = df[display_cols].rename(columns=_COL_RENAME)

        def _color_signal(series: pd.Series) -> list[str]:
            return [_SIGNAL_STYLE.get(v, "") for v in series]

        styled = (
            df_display.style.apply(_color_signal, subset=["Decisão Final"])
            if "Decisão Final" in df_display.columns
            else df_display.style
        )
        _col_config = {
            "Decisão Final":  st.column_config.TextColumn(width="medium"),
            "Data/Hora":      st.column_config.TextColumn(width="medium"),
            "Ativo":          st.column_config.TextColumn(width="small"),
            "RSI":            st.column_config.NumberColumn(width="small", format="%.1f"),
            "Volume (ratio)": st.column_config.NumberColumn(width="small", format="%.2fx"),
            "Preço (R$)":     st.column_config.NumberColumn(width="small", format="R$ %.2f"),
        }
        st.dataframe(styled, column_config=_col_config, width='stretch')
    else:
        st.info("Nenhum sinal registrado nos últimos 30 dias.")

# ── Tab 3: Operations ─────────────────────────────────────────────────────

with tab_ops:
    # FIX 5 — Manual operation registration form
    st.subheader("Registrar Operação")

    _ticker_options = [t.replace(".SA", "") for t in [
        "PETR4", "VALE3", "ITUB4", "BBDC4", "WEGE3", "RENT3",
        "B3SA3", "SUZB3", "RDOR3", "GGBR4", "VBBR3", "PRIO3",
        "CPLE6", "CSAN3", "EQTL3", "SBSP3",
    ]]

    with st.form("nova_operacao"):
        col_a, col_b, col_c = st.columns(3)
        ticker_val   = col_a.selectbox("Ativo", options=_ticker_options)
        entry_price  = col_b.number_input("Preço de entrada (R$)", min_value=0.01, step=0.01, format="%.2f")
        quantity     = col_c.number_input("Quantidade de ações", min_value=1, step=1, value=100)
        submitted    = st.form_submit_button("Registrar Compra")

        if submitted and entry_price > 0:
            stop_price   = round(entry_price * 0.93, 2)
            target_price = round(entry_price * 1.15, 2)
            save_operation(
                signal_id=None,
                ticker=ticker_val,
                entry_price=entry_price,
                entry_date=datetime.utcnow().date().isoformat(),
                stop_price=stop_price,
                status="OPEN",
            )
            _cached_open_ops.clear()
            _cached_all_ops.clear()
            st.success(
                f"✅ Operação registrada!  \n"
                f"Stop loss: R$ {stop_price:.2f} (sair se cair até aqui)  \n"
                f"Alvo: R$ {target_price:.2f} (realizar lucro aqui)  \n"
                f"Posição: {quantity} ações × R$ {entry_price:.2f} = R$ {quantity * entry_price:,.2f}"
            )

    st.markdown("---")

    st.subheader("Posições Abertas")
    open_ops = _cached_open_ops()

    if open_ops:
        rows = []
        for op in open_ops:
            try:
                current    = yf.Ticker(f"{op['ticker']}.SA").fast_info.last_price
                entry      = op.get("entry_price") or 0.0
                unreal_pct = round(((current - entry) / entry) * 100, 2) if entry else None
            except Exception:
                current    = None
                unreal_pct = None
            rows.append({
                "Ticker":                op["ticker"],
                "Entrada (R$)":          op.get("entry_price"),
                "Stop (R$)":             op.get("stop_price"),
                "Atual (R$)":            current,
                "P&L nao realizado (%)": unreal_pct,
            })
        st.dataframe(pd.DataFrame(rows), width='stretch')
    else:
        st.info("Nenhuma posição aberta.")

    st.subheader("Histórico Fechado")
    closed_ops = _cached_closed_ops()

    if closed_ops:
        df_closed = pd.DataFrame(closed_ops)
        keep_cols = [c for c in ["ticker", "entry_date", "exit_date", "pnl_brl", "status"]
                     if c in df_closed.columns]
        st.dataframe(df_closed[keep_cols], width='stretch')

        df_chart = df_closed[["exit_date", "pnl_brl"]].dropna()
        if not df_chart.empty:
            df_chart = df_chart.sort_values("exit_date")
            df_chart["P&L Acumulado (R$)"] = df_chart["pnl_brl"].cumsum()
            st.line_chart(df_chart.set_index("exit_date")["P&L Acumulado (R$)"])
    else:
        st.info("Nenhuma operação encerrada.")

# ── Tab 4: Backtesting ────────────────────────────────────────────────────

with tab_bt:
    results_path = Path("data/backtest_results.json")

    if results_path.exists():
        with open(results_path, encoding="utf-8") as fh:
            bt_payload = json.load(fh)
        results = bt_payload.get("results", [])

        if results:
            df_bt     = pd.DataFrame(results)
            avg_wr    = df_bt["win_rate"].mean()
            best_row  = df_bt.loc[df_bt["win_rate"].idxmax()]
            worst_row = df_bt.loc[df_bt["win_rate"].idxmin()]

            c1, c2, c3 = st.columns(3)
            c1.metric("Win Rate Médio", f"{avg_wr:.1f}%")
            c2.metric("Melhor Ticker",  best_row["ticker"])
            c3.metric("Pior Ticker",    worst_row["ticker"])

            st.subheader("Win Rate por Ticker")
            st.bar_chart(df_bt.set_index("ticker")["win_rate"])

            _BT_RENAME = {
                "ticker":          "Ativo",
                "total_trades":    "Operações",
                "win_rate":        "Win Rate (%)",
                "avg_return_pct":  "Retorno Médio (%)",
                "max_drawdown_pct":"Drawdown Máx (%)",
                "sharpe_ratio":    "Sharpe",
                "period_days":     "Período (dias)",
            }
            df_bt_display = df_bt.rename(columns={k: v for k, v in _BT_RENAME.items() if k in df_bt.columns})
            st.subheader("Métricas completas")
            st.dataframe(df_bt_display, width='stretch')

            st.markdown("### Classificação por estratégia RSI")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.success("**✅ Operar**\n\nSBSP3 · VALE3 · ITUB4")
            with col2:
                st.warning("**⚠️ Cautela**\n\nPETR4 · B3SA3 · BBDC4 · VBBR3 · GGBR4")
            with col3:
                st.error("**❌ Evitar (RSI não funciona)**\n\nCSAN3 · RENT3 · WEGE3 · SUZB3 · PRIO3")
            st.caption("Critérios: ≥5 trades históricos, win rate ≥55%, Sharpe ≥0.5")
        else:
            st.info("Arquivo de backtest está vazio.")
    else:
        st.info("Nenhum backtest rodado ainda.")

    if st.button("▶ Rodar Backtest Agora"):
        with st.spinner("Rodando backtest..."):
            from backtester import run_full_backtest
            bt_results = run_full_backtest()
            st.success(f"Backtest concluído — {len(bt_results)} ativos analisados")
            st.rerun()

# ── Tab 5: Validation ─────────────────────────────────────────────────────

with tab_validation:
    st.header("Diagnóstico do Sistema")
    st.caption("Verifica se cada camada está entregando dados corretos")

    if st.button("▶ Rodar Diagnóstico Completo"):
        with st.spinner("Validando dados... (calibração de IA pode levar ~60s)"):
            from validator import (
                validate_price_data,
                validate_rsi,
                validate_news_relevance,
                validate_ai_consensus,
                validate_macro_data,
            )

            ticker = "PETR4.SA"

            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Preços")
                price_result = validate_price_data(ticker)
                if price_result["status"] == "OK":
                    st.success(f"✅ yfinance e Brapi concordam (delta {price_result['divergence_pct']:.2f}%)")
                elif price_result["status"] == "DIVERGENCE":
                    st.error(f"⚠️ Divergência detectada: {price_result['divergence_pct']:.2f}%")
                else:
                    st.error(f"⚠️ Erro ao obter dados: {price_result.get('error', 'desconhecido')}")

                st.subheader("RSI")
                rsi_result = validate_rsi(ticker)
                if rsi_result["status"] == "OK":
                    st.success(f"✅ RSI sistema={rsi_result['rsi_system']:.1f} | ref={rsi_result['rsi_reference']:.1f}")
                elif rsi_result["status"] == "WARNING":
                    st.warning(f"⚠️ Delta RSI = {rsi_result['delta']:.1f} pontos")
                else:
                    st.error(f"⚠️ Erro RSI: {rsi_result.get('error', 'desconhecido')}")

                st.subheader("Dados Macro")
                macro_result = validate_macro_data()
                brent = macro_result.get("brent")
                selic = macro_result.get("selic")
                if macro_result["status"] == "OK":
                    st.success(f"✅ Brent ${brent:.2f} | SELIC {selic:.2f}%")
                else:
                    st.error("⚠️ Dados macro com valores suspeitos")
                    for flag in macro_result.get("flags", []):
                        st.write(f"  - {flag}")

            with col2:
                st.subheader("Calibração da IA")
                ai_result = validate_ai_consensus(ticker, "")

                _status_color = {"OK": "success", "WEAK": "warning", "BROKEN": "error"}
                getattr(st, _status_color[ai_result["calibration_status"]])(
                    f"Status: {ai_result['calibration_status']}"
                )
                st.write(f"Manchete boa → score {ai_result['good_headline_score']} | {ai_result['good_verdict']}")
                st.write(f"Manchete ruim → score {ai_result['bad_headline_score']} | {ai_result['bad_verdict']}")
                st.write(f"Manipulação → score {ai_result['manipulation_score']} | {ai_result['manipulation_verdict']}")

            st.subheader("Notícias buscadas (o que a IA realmente lê)")
            news_result = validate_news_relevance(ticker)
            if news_result["status"] == "OK":
                st.success("✅ Notícias relevantes encontradas")
            else:
                st.error(f"⚠️ {news_result['status']}")
            st.info(f"Manchetes enviadas à IA:\n{news_result['headlines_fetched']}")

# ── Tab 6: Cripto ─────────────────────────────────────────────────────────

with tab_cripto:
    import subprocess
    import re
    from datetime import timedelta

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _to_brt(utc_str: str) -> str:
        """Convert ISO UTC string to BRT (UTC-3) formatted as 'DD/MM HH:MM'."""
        try:
            dt = datetime.fromisoformat(str(utc_str))
            return (dt - timedelta(hours=3)).strftime("%d/%m %H:%M")
        except Exception:
            return str(utc_str)[:16] if utc_str else "—"

    @st.cache_data(ttl=60)
    def _load_crypto_stats():
        try:
            with get_connection() as conn:
                row = conn.execute("SELECT MAX(created_at) FROM crypto_signals").fetchone()
                last_raw = row[0] if row and row[0] else None
                today_str = datetime.utcnow().date().isoformat()
                today_count = conn.execute(
                    "SELECT COUNT(*) FROM crypto_signals WHERE DATE(created_at) = ?",
                    (today_str,),
                ).fetchone()[0]
                week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
                actionable = conn.execute(
                    "SELECT COUNT(*) FROM crypto_signals "
                    "WHERE decision IN ('FORTE','MODERADO') AND created_at >= ?",
                    (week_ago,),
                ).fetchone()[0]
                return last_raw, int(today_count), int(actionable)
        except Exception:
            return None, 0, 0

    @st.cache_data(ttl=60)
    def _load_crypto_signals_tab():
        try:
            with get_connection() as conn:
                return pd.read_sql(
                    """SELECT symbol, decision, ai_score, price,
                              rsi_1h, galaxy_score, sentiment, created_at
                       FROM crypto_signals
                       ORDER BY created_at DESC
                       LIMIT 100""",
                    conn,
                )
        except Exception:
            return pd.DataFrame()

    def _parse_run_table(output: str) -> pd.DataFrame:
        """Parse pipeline stdout report lines into a summary DataFrame."""
        pat = re.compile(
            r"^\s{2,}(\w+)\s+\$\s*([\d,\.]+)\s*\|\s*RSI=([\d\.]+|N/A)\s*"
            r"\|\s*galaxy=(\S+)\s*\|\s*(\w+)"
        )
        rows = []
        for line in output.splitlines():
            m = pat.match(line)
            if m:
                sym, price_s, rsi_s, galaxy_s, decision = m.groups()
                try:
                    price = float(price_s.replace(",", ""))
                except (ValueError, TypeError):
                    price = None
                try:
                    rsi = float(rsi_s)
                except (ValueError, TypeError):
                    rsi = None
                galaxy = "—" if galaxy_s in ("None", "N/A") else galaxy_s
                rows.append({"Par": sym, "Preço (USD)": price,
                             "RSI (1h)": rsi, "Galaxy": galaxy, "Decisão": decision})
        return pd.DataFrame(rows)

    def _color_decision(series: pd.Series) -> list[str]:
        c = {"FORTE": "color: #4caf50", "MODERADO": "color: #ffc107",
             "BLOQUEADO": "color: #f44336", "AGUARDAR": "color: #888888"}
        return [c.get(v, "") for v in series]

    def _run_and_show(cmd_args: list, clear_after: bool = False) -> None:
        with st.spinner("Executando pipeline cripto..."):
            proc = subprocess.run(cmd_args, capture_output=True, text=True, timeout=120)
        raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        if not raw.strip():
            raw = "(sem saída)"
        df_run = _parse_run_table(raw)
        if not df_run.empty:
            st.dataframe(
                df_run.style.apply(_color_decision, subset=["Decisão"]),
                use_container_width=True,
            )
        with st.expander("📋 Log completo", expanded=False):
            st.code(raw, language=None)
        if clear_after:
            _load_crypto_stats.clear()
            _load_crypto_signals_tab.clear()

    # ── Section 1: Status bar ─────────────────────────────────────────────────

    st.subheader("🪙 Pipeline Cripto")

    last_raw, today_count, actionable_7d = _load_crypto_stats()
    last_run_str = _to_brt(last_raw) if last_raw else "Nunca"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Última execução", last_run_str)
    c2.metric("Sinais hoje", today_count)
    c3.metric("Acionáveis (7d)", actionable_7d)
    c4.metric("Status API", "🟢 CoinGecko: gratuito")

    st.markdown("---")

    # ── Section 2: Run buttons ────────────────────────────────────────────────

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("▶ Rodar agora", key="cripto_prod"):
            _run_and_show([sys.executable, "crypto_main.py"], clear_after=True)
    with btn_col2:
        if st.button("🧪 Dry-run", key="cripto_dry"):
            _run_and_show([sys.executable, "crypto_main.py", "--dry-run"])

    st.markdown("---")

    # ── Section 3: Signals table ──────────────────────────────────────────────

    st.subheader("Sinais recentes")
    df_crypto = _load_crypto_signals_tab()

    if df_crypto.empty:
        st.info("Nenhum sinal ainda. Clique em '▶ Rodar agora' para executar o pipeline.")
    else:
        disp = df_crypto.copy()
        disp["created_at"] = disp["created_at"].apply(_to_brt)
        disp["price"] = disp["price"].apply(
            lambda x: f"{float(x):.2f}" if pd.notna(x) else "—"
        )
        disp["rsi_1h"] = disp["rsi_1h"].apply(
            lambda x: f"{float(x):.1f}" if pd.notna(x) else "—"
        )
        disp["galaxy_score"] = disp["galaxy_score"].apply(
            lambda x: str(int(float(x))) if pd.notna(x) else "—"
        )
        disp = disp.rename(columns={
            "symbol":       "Par",
            "decision":     "Decisão",
            "ai_score":     "Score IA",
            "price":        "Preço (USD)",
            "rsi_1h":       "RSI (1h)",
            "galaxy_score": "Galaxy",
            "sentiment":    "Sentimento",
            "created_at":   "Data/Hora",
        })
        st.dataframe(disp.style.apply(_color_decision, subset=["Decisão"]),
                     use_container_width=True)

    if st.button("🔄 Atualizar", key="cripto_refresh"):
        _load_crypto_stats.clear()
        _load_crypto_signals_tab.clear()
        st.rerun()

    # ── Section 4: Mini chart ─────────────────────────────────────────────────

    if not df_crypto.empty and len(df_crypto) >= 5:
        st.subheader("Score IA por execução (últimas 50)")
        try:
            df_chart = df_crypto.head(50).copy()
            df_chart["_brt"] = df_chart["created_at"].apply(_to_brt)
            df_chart = df_chart.iloc[::-1]  # chronological order
            df_pivot = df_chart.pivot_table(
                index="_brt", columns="symbol", values="ai_score", aggfunc="mean"
            )
            st.line_chart(df_pivot)
        except Exception:
            pass

import json
from datetime import datetime, timedelta, timezone
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

    if "resultados" not in st.session_state:
        with st.spinner("Varrendo mercado e auditando com IA..."):
            st.session_state.resultados = orquestrar_investimento()

    resultados = st.session_state.resultados

    # ── Summary bar — first thing the user reads ──────────────────────────────
    if resultados:
        _recs = [item["Recomendação"] for item in resultados]
        if "FORTE" in _recs:
            st.success("🟢 Há oportunidade agora — veja os ativos abaixo")
        elif "MODERADO" in _recs:
            st.warning("🟡 Sinais fracos detectados — observe com cautela")
        else:
            st.info("⚫ Nenhum sinal agora — o sistema está aguardando o momento certo")
    else:
        st.info("⚫ Nenhum sinal agora — o sistema está aguardando o momento certo")

    _scan_brt = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%H:%M")
    st.caption(f"Última varredura: {_scan_brt} BRT — próxima em ~5 minutos (autorefresh ativo)")

    # ── Asset cards ───────────────────────────────────────────────────────────
    if resultados:
        cols = st.columns(min(len(resultados), 4))
        for i, item in enumerate(resultados):
            with cols[i % len(cols)]:
                rec        = item["Recomendação"]
                rsi        = float(item["RSI"])
                confianca  = float(item.get("Confiança", 0))
                razoes     = item.get("Razões", [])
                analise_ia = item.get("Análise IA", "")
                ai_score   = int(confianca * 100)
                _t         = item["Ativo"].replace(".SA", "")

                _curr        = get_signal_by_id(item.get("signal_id"))
                volume_ratio = float((_curr.get("volume_ratio") or 0)) if _curr else 0.0

                # ── Semaphore header ──────────────────────────────────────
                _sem = {
                    "FORTE":    ("🟢", "Oportunidade de compra",
                                 "Sinal forte — todos os critérios atendidos"),
                    "MODERADO": ("🟡", "Sinal fraco — observe",
                                 "Critérios parcialmente atendidos"),
                    "BLOQUEADO":("🔴", "Não entre — risco detectado",
                                 "IA identificou ruído ou manipulação"),
                }.get(rec, ("⚫", "Aguarde — sem sinal agora",
                            "Condições de mercado neutras ou desfavoráveis"))
                _emoji, _label, _subtitle = _sem

                st.markdown(f"## {_emoji} {item['Ativo']}")
                st.markdown(f"**{_label}**")
                st.caption(_subtitle)
                if _t in BACKTEST_APPROVED:
                    st.caption(":green[✅ validado pelo backtest]")

                # ── Plain-language explanation ────────────────────────────
                if rec == "AGUARDAR":
                    _why = []
                    if rsi > 40:
                        _why.append(
                            f"RSI em {rsi:.0f} — ativo não está sobrevendido "
                            f"(precisaria estar abaixo de 30)"
                        )
                    if volume_ratio < 1.5:
                        _why.append(
                            f"Volume {volume_ratio:.1f}x abaixo do normal "
                            f"(precisaria ser 1.5x ou mais)"
                        )
                    if ai_score < 65:
                        _why.append(
                            f"Confiança da IA em {ai_score}% — "
                            f"análise de notícias inconclusiva"
                        )
                    if not _why:
                        _why.append("Nem todos os critérios técnicos foram atendidos")
                    st.info("Por que aguardar:\n" + "\n".join(f"• {r}" for r in _why))

                elif rec == "FORTE":
                    st.success(
                        f"Por que comprar:\n"
                        f"• RSI em {rsi:.0f} — ativo sobrevendido, possível recuperação\n"
                        f"• Volume {volume_ratio:.1f}x acima do normal — interesse crescente\n"
                        f"• Confiança da IA em {ai_score}% — notícias favoráveis\n"
                        f"⚠️ Sugestão: até 20% do capital disponível"
                    )

                elif rec == "MODERADO":
                    st.warning(
                        f"Sinal fraco — acompanhe:\n"
                        f"• RSI em {rsi:.0f} — zona de atenção mas não confirmada\n"
                        f"• Aguarde um segundo sinal antes de agir"
                    )

                elif rec == "BLOQUEADO":
                    _bloqueio = razoes[0] if razoes else "Manipulação detectada"
                    st.error(
                        f"Não entre agora:\n"
                        f"• {_bloqueio}\n"
                        f"• Aguarde o próximo ciclo de análise"
                    )

                # ── Technical details (collapsed by default) ──────────────
                _macro = next(
                    (r for r in razoes if "macro" in r.lower() or "⚠️" in r),
                    "Sem alertas macro"
                )
                with st.expander("🔬 Detalhes técnicos", expanded=False):
                    st.write(f"RSI: {rsi:.2f}")
                    st.write(f"Volume ratio: {volume_ratio:.2f}x")
                    st.write(f"Score IA: {ai_score}")
                    st.write(f"Contexto macro: {_macro}")
                    st.write(f"Preço: R$ {item.get('Preço', 0):.2f}")
                    if analise_ia:
                        st.caption(f"Análise IA: {analise_ia}")
                    if razoes:
                        st.markdown("**Razões:**")
                        for r in razoes:
                            st.markdown(f"- {r}")
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
                entry_date=datetime.now(timezone.utc).date().isoformat(),
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
                today_str = datetime.now(timezone.utc).date().isoformat()
                today_count = conn.execute(
                    "SELECT COUNT(*) FROM crypto_signals WHERE DATE(created_at) = ?",
                    (today_str,),
                ).fetchone()[0]
                week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
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
                    """SELECT symbol, decision, ai_score, ai_veredicto, price,
                              rsi_1h, galaxy_score, sentiment, reasons, created_at
                       FROM crypto_signals
                       ORDER BY created_at DESC
                       LIMIT 100""",
                    conn,
                )
        except Exception:
            return pd.DataFrame()

    @st.cache_data(ttl=60)
    def _load_crypto_price_history():
        try:
            with get_connection() as conn:
                return pd.read_sql(
                    """SELECT symbol, price, created_at
                       FROM crypto_signals
                       ORDER BY created_at DESC
                       LIMIT 80""",
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
                width='stretch',
            )
        with st.expander("📋 Log completo", expanded=False):
            st.code(raw, language=None)
        if clear_after:
            _load_crypto_stats.clear()
            _load_crypto_signals_tab.clear()
            _load_crypto_price_history.clear()

    # ── Section 1: Status bar ─────────────────────────────────────────────────

    st.subheader("🪙 Pipeline Cripto")

    with st.expander("ℹ️ Como interpretar os sinais", expanded=False):
        st.markdown("""
| Semáforo | Decisão | O que significa |
|----------|---------|-----------------|
| 🟢 | **FORTE** | Todos os critérios atendidos — RSI sobrevendido, momentum positivo, IA confiante |
| 🟡 | **MODERADO** | Critérios parcialmente atendidos — acompanhe, mas não entre ainda |
| ⚫ | **AGUARDAR** | Nenhum critério técnico atingido — mercado neutro ou desfavorável |
| 🔴 | **BLOQUEADO** | IA detectou risco — possível pump, FUD coordenado ou manipulação |

**Galaxy Score (0–100):** Momentum composto de preço, volume, liquidez e redes sociais.
- Acima de 52 → interesse crescente
- Abaixo de 40 → momentum fraco

**RSI (1h):** Sobrecomprado acima de 65, sobrevendido abaixo de 35.
        """)

    last_raw, today_count, actionable_7d = _load_crypto_stats()
    last_run_str = _to_brt(last_raw) if last_raw else "Nunca"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Última execução", last_run_str)
    if last_raw is None:
        c1.caption("▶ Execute o scheduler para popular")
    else:
        try:
            _last_dt = datetime.fromisoformat(str(last_raw))
            _hours_ago = (datetime.now(timezone.utc) - _last_dt).total_seconds() / 3600
            if _hours_ago > 7:
                c1.caption("⚠️ Scheduler pode estar parado")
        except Exception:
            pass
    c2.metric("Sinais hoje", today_count)
    c3.metric("Acionáveis (7d)", actionable_7d)
    c4.metric("Status API", "🟢 CoinGecko: gratuito")

    st.markdown("---")

    # ── Summary bar ───────────────────────────────────────────────────────────

    _df_summary = _load_crypto_signals_tab()
    if not _df_summary.empty:
        _recent_decisions = _df_summary.drop_duplicates("symbol", keep="first")["decision"].tolist()
        _n_forte = _recent_decisions.count("FORTE")
        _n_mod   = _recent_decisions.count("MODERADO")
        if _n_forte:
            st.success(f"🟢 {_n_forte} ativo(s) com sinal de compra agora")
        elif _n_mod:
            st.warning(f"🟡 {_n_mod} ativo(s) com sinal fraco — observe")
        else:
            st.info("⚫ Nenhum sinal acionável agora — aguardando o momento certo")

    # ── Section 2: Run buttons ────────────────────────────────────────────────

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("▶ Rodar agora", key="cripto_prod"):
            _run_and_show([sys.executable, "crypto_main.py"], clear_after=True)
    with btn_col2:
        if st.button("🧪 Dry-run", key="cripto_dry"):
            _run_and_show([sys.executable, "crypto_main.py", "--dry-run"])

    st.markdown("---")

    # ── Section 3: Signal cards ───────────────────────────────────────────────

    st.subheader("Sinais por ativo")
    df_crypto = _load_crypto_signals_tab()

    if df_crypto.empty:
        st.info("Nenhum sinal ainda. Clique em '▶ Rodar agora' para executar o pipeline.")
    else:
        _card_rows = df_crypto.drop_duplicates("symbol", keep="first")
        _card_cols = st.columns(min(len(_card_rows), 3))

        for _ci, (_, _row) in enumerate(_card_rows.iterrows()):
            with _card_cols[_ci % len(_card_cols)]:
                _sym     = _row["symbol"]
                _dec     = _row.get("decision", "AGUARDAR")
                _rsi     = _row.get("rsi_1h")
                _gal     = _row.get("galaxy_score")
                _price   = _row.get("price")
                _sent    = _row.get("sentiment", "")
                _verdict = _row.get("ai_veredicto", "")
                _ai_sc   = _row.get("ai_score")
                _at      = _to_brt(_row.get("created_at", ""))

                _sem_map = {
                    "FORTE":    ("🟢", "Compra — todos os critérios atendidos",
                                 "RSI sobrevendido + momentum + IA confiante"),
                    "MODERADO": ("🟡", "Sinal fraco — acompanhe",
                                 "Critérios parciais — aguarde confirmação"),
                    "BLOQUEADO":("🔴", "Não entre — risco detectado",
                                 "IA detectou pump, FUD ou manipulação"),
                }.get(_dec, ("⚫", "Aguarde — sem sinal agora",
                             "Nenhum critério técnico atingido"))
                _emoji, _lbl, _sub = _sem_map

                st.markdown(f"## {_emoji} {_sym}")
                st.markdown(f"**{_lbl}**")
                st.caption(f"{_sub} · {_at}")

                _rsi_f = float(_rsi) if _rsi is not None and pd.notna(_rsi) else None
                _gal_i = int(float(_gal)) if _gal is not None and pd.notna(_gal) else None
                _ai_i  = int(float(_ai_sc)) if _ai_sc is not None and pd.notna(_ai_sc) else None

                if _dec == "FORTE":
                    _why = "Por que comprar:\n"
                    if _rsi_f is not None:
                        _why += f"• RSI em {_rsi_f:.0f} — sobrevendido, possível recuperação\n"
                    if _gal_i is not None:
                        _why += f"• Galaxy {_gal_i} — momentum crescente\n"
                    if _ai_i is not None:
                        _why += f"• IA {_ai_i}% confiante — notícias favoráveis\n"
                    _why += "⚠️ Sugestão: até 10% do capital em crypto"
                    st.success(_why)
                elif _dec == "MODERADO":
                    st.warning(
                        "Sinal fraco — acompanhe:\n"
                        "• Alguns critérios atendidos, mas sem confirmação total\n"
                        "• Aguarde um segundo sinal antes de agir"
                    )
                elif _dec == "BLOQUEADO":
                    _motivo = _verdict if _verdict else "Risco detectado pela IA"
                    st.error(
                        f"Não entre agora:\n"
                        f"• {_motivo}\n"
                        f"• Aguarde o próximo ciclo de análise"
                    )
                else:
                    _aguard_why = []
                    if _rsi_f is not None and _rsi_f > 35:
                        _aguard_why.append(f"RSI em {_rsi_f:.0f} — sem sobrevendimento")
                    if _gal_i is not None and _gal_i < 48:
                        _aguard_why.append(f"Galaxy {_gal_i} — momentum fraco")
                    if not _aguard_why:
                        _aguard_why.append("Critérios técnicos não atingidos")
                    st.info("Por que aguardar:\n" + "\n".join(f"• {r}" for r in _aguard_why))

                with st.expander("🔬 Detalhes técnicos", expanded=False):
                    if _price is not None and pd.notna(_price):
                        st.write(f"Preço: $ {float(_price):.4f}")
                    if _rsi_f is not None:
                        st.write(f"RSI (1h): {_rsi_f:.1f}")
                    if _gal_i is not None:
                        st.write(f"Galaxy Score: {_gal_i}")
                    if _ai_i is not None:
                        st.write(f"Score IA: {_ai_i}")
                    if _sent:
                        st.write(f"Sentimento: {_sent}")
                    if _verdict:
                        st.caption(f"Veredicto IA: {_verdict}")

    if st.button("🔄 Atualizar", key="cripto_refresh"):
        _load_crypto_stats.clear()
        _load_crypto_signals_tab.clear()
        _load_crypto_price_history.clear()
        st.rerun()

    # ── Section 4: Price evolution chart ─────────────────────────────────────

    st.subheader("Evolução de preço por ativo")
    df_prices = _load_crypto_price_history()

    if df_prices.empty or len(df_prices) < 8:
        st.info("Gráfico disponível após mais execuções do scheduler (mínimo 8 registros).")
    else:
        try:
            df_prices = df_prices.copy()
            df_prices["_brt"] = df_prices["created_at"].apply(_to_brt)
            df_prices = df_prices.iloc[::-1]
            df_pivot = df_prices.pivot_table(
                index="_brt", columns="symbol", values="price", aggfunc="mean"
            )
            st.line_chart(df_pivot)
        except Exception:
            pass

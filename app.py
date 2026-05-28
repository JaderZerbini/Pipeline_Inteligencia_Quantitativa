import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth
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
# Authentication
# ---------------------------------------------------------------------------

def _load_auth() -> dict | None:
    """Load credentials from Streamlit secrets (Railway) or local secrets.toml."""
    # Railway / cloud: st.secrets populated from secrets.toml or env
    try:
        creds  = st.secrets.get("credentials")
        cookie = st.secrets.get("cookie")
        if creds and cookie:
            return {
                "credentials": {"usernames": dict(creds.get("usernames", {}))},
                "cookie": dict(cookie),
            }
    except Exception:
        pass

    # Local fallback: read .streamlit/secrets.toml directly
    secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        import toml
        return toml.load(secrets_path)

    return None


_auth_config = _load_auth()

if _auth_config is None:
    st.error("Autenticacao nao configurada. Adicione .streamlit/secrets.toml")
    st.stop()

_authenticator = stauth.Authenticate(
    _auth_config["credentials"],
    _auth_config["cookie"]["name"],
    _auth_config["cookie"]["key"],
    _auth_config["cookie"]["expiry_days"],
)

_authenticator.login(
    location="main",
    fields={
        "Form name": "Terminal Quant — Acesso Restrito",
        "Username": "Usuario",
        "Password": "Senha",
        "Login": "Entrar",
    },
)

_auth_status = st.session_state.get("authentication_status")

if _auth_status is False:
    st.error("Usuario ou senha incorretos.")
    st.stop()

if _auth_status is None:
    st.info("Faca login para acessar o dashboard.")
    st.stop()

# ── Logged in — show logout in sidebar ─────────────────────────────────────
with st.sidebar:
    st.caption(f"Conectado: {st.session_state.get('name', '')}")
    _authenticator.logout("Sair", location="sidebar")


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

tab_scanner, tab_sinais, tab_ops, tab_bt, tab_validation, tab_cripto, tab_paper = st.tabs(
    ["🔍 Scanner", "📈 Sinais", "💼 Operações", "🔬 Backtesting", "🧪 Validação", "🪙 Cripto", "📊 Paper Trading"]
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
                _hist_ctx = item.get("hist_context")
                if _hist_ctx:
                    st.caption(f"📈 {_hist_ctx}")

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
                    _hist_cheap = item.get("hist_position") == "below_ma200"
                    _forte_msg = (
                        f"Por que comprar:\n"
                        f"• RSI em {rsi:.0f} — ativo sobrevendido, possível recuperação\n"
                        f"• Volume {volume_ratio:.1f}x acima do normal — interesse crescente\n"
                        f"• Confiança da IA em {ai_score}% — notícias favoráveis\n"
                    )
                    if _hist_cheap:
                        _forte_msg += "• Preço abaixo da média histórica — zona de compra favorável\n"
                    _forte_msg += "⚠️ Sugestão: até 20% do capital disponível"
                    st.success(_forte_msg)

                elif rec == "MODERADO":
                    _hist_expensive = item.get("hist_position") == "above_ma200"
                    _mod_msg = (
                        f"Sinal fraco — acompanhe:\n"
                        f"• RSI em {rsi:.0f} — zona de atenção mas não confirmada\n"
                        f"• Aguarde um segundo sinal antes de agir"
                    )
                    if _hist_expensive:
                        _mod_msg += "\n⚠️ Atenção: preço historicamente caro — sinal de menor qualidade"
                    st.warning(_mod_msg)

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
    _subtab_b3, _subtab_cripto = st.tabs(["📊 B3", "🪙 Cripto"])

    with _subtab_b3:
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

        st.divider()
        st.subheader("Backtest B3 detalhado — simulação por ativo")
        st.caption("RSI + Volume + MA200 com trailing stop 7% — dados Yahoo Finance.")

        import subprocess as _sp
        _days_b3 = st.slider("Período B3 (dias)", min_value=30, max_value=150,
                              value=150, step=30, key="days_b3_slider")

        _col_b3a, _col_b3b = st.columns(2)
        with _col_b3a:
            if st.button("▶ Rodar backtest B3"):
                with st.spinner(f"Baixando dados do Yahoo Finance ({_days_b3} dias)..."):
                    _b3_proc = _sp.run(
                        [sys.executable, "b3_backtester.py", "--days", str(_days_b3)],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=300,
                    )
                st.session_state["b3_bt_raw"] = _b3_proc.stdout or _b3_proc.stderr or ""

        with _col_b3b:
            if st.button("📊 Comparativo B3 (demora ~3 min)"):
                with st.spinner("Testando 6 configurações..."):
                    _b3_cmp = _sp.run(
                        [sys.executable, "b3_backtester.py", "--compare"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=600,
                    )
                st.session_state["b3_bt_raw"] = _b3_cmp.stdout or _b3_cmp.stderr or ""

        _b3_raw = st.session_state.get("b3_bt_raw", "")
        if _b3_raw:
            for _line in _b3_raw.splitlines():
                if "Melhor configuracao" in _line:
                    st.success(_line.strip())
                    break
            with st.expander("Log completo do backtest B3", expanded=True):
                st.text(_b3_raw)

    with _subtab_cripto:
        import subprocess

        st.subheader("Backtest Cripto — dados históricos Binance")
        st.caption(
            "Simula os sinais RSI + MA200 + momentum que o sistema teria gerado "
            "no período e calcula se a estratégia seria lucrativa."
        )

        _bt_days = st.slider("Período (dias)", min_value=30, max_value=150, value=150, step=30)

        if st.button("▶ Rodar backtest cripto"):
            with st.spinner(f"Baixando dados históricos da Binance ({_bt_days} dias)..."):
                proc = subprocess.run(
                    [sys.executable, "crypto_backtester.py", "--days", str(_bt_days)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            raw = proc.stdout + (proc.stderr or "")
            st.session_state["crypto_bt_raw"] = raw
            st.session_state["crypto_bt_days"] = _bt_days

        raw_bt = st.session_state.get("crypto_bt_raw", "")

        if raw_bt:
            # Parse summary table from output
            _bt_rows = []
            current: dict = {}
            for line in raw_bt.splitlines():
                line = line.strip()
                for sym in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"):
                    if line == sym:
                        if current:
                            _bt_rows.append(current)
                        current = {"Par": sym}
                        break
                if "Operacoes:" in line and current:
                    parts = line.replace("Operacoes:", "").replace("Wins:", "").replace("Losses:", "").split("|")
                    try:
                        current["Operações"] = int(parts[0].strip())
                        current["Wins"] = int(parts[1].strip())
                        current["Losses"] = int(parts[2].strip())
                    except Exception:
                        pass
                if "Win rate:" in line and current:
                    try:
                        current["Win Rate %"] = float(line.split(":")[1].replace("%", "").strip())
                    except Exception:
                        pass
                if "P&L total:" in line and current:
                    try:
                        pnl_part = line.split("R$")[1].split("(")[0].strip().replace(",", "")
                        ret_part = line.split("(")[1].replace("%)", "").replace("+", "").strip()
                        current["P&L (R$)"] = float(pnl_part)
                        current["Retorno %"] = float(ret_part)
                    except Exception:
                        pass
                if "Max drawdown:" in line and current:
                    try:
                        current["Max DD %"] = float(line.split(":")[1].replace("%", "").strip())
                    except Exception:
                        pass
            if current and "Par" in current:
                _bt_rows.append(current)

            if _bt_rows:
                df_cbt = pd.DataFrame(_bt_rows)

                # Summary metrics
                _total_ops = sum(r.get("Operações", 0) for r in _bt_rows)
                _total_wins = sum(r.get("Wins", 0) for r in _bt_rows)
                _total_pnl = sum(r.get("P&L (R$)", 0.0) for r in _bt_rows)
                _cwr = _total_wins / _total_ops * 100 if _total_ops else 0

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Operações totais", _total_ops)
                mc2.metric("Win rate combinado", f"{_cwr:.1f}%")
                pnl_delta = f"{'+'if _total_pnl>=0 else ''}{_total_pnl:,.2f}"
                mc3.metric("P&L combinado (R$)", pnl_delta, delta=pnl_delta)

                # Styled table
                def _color_pnl(val):
                    try:
                        return "color: #2ecc71" if float(val) >= 0 else "color: #e74c3c"
                    except Exception:
                        return ""

                cols_order = [c for c in ["Par", "Operações", "Wins", "Losses", "Win Rate %", "P&L (R$)", "Retorno %", "Max DD %"] if c in df_cbt.columns]
                df_show = df_cbt[cols_order]
                st.dataframe(
                    df_show.style.applymap(_color_pnl, subset=[c for c in ["P&L (R$)", "Retorno %"] if c in df_show.columns]),
                    use_container_width=True,
                )

                # Bar chart: P&L por par
                if "P&L (R$)" in df_cbt.columns:
                    st.subheader("P&L por par")
                    st.bar_chart(df_cbt.set_index("Par")["P&L (R$)"])
            else:
                st.info("Nenhum par retornou dados suficientes para montar a tabela.")

            with st.expander("Log completo do backtest"):
                st.text(raw_bt)

        st.divider()

        if st.button("📊 Comparativo de configurações (demora ~2 min)"):
            with st.spinner("Testando 6 configurações diferentes..."):
                _cmp_proc = subprocess.run(
                    [sys.executable, "crypto_backtester.py", "--compare"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=300,
                )
            _cmp_out = _cmp_proc.stdout or _cmp_proc.stderr or ""
            st.session_state["crypto_bt_compare"] = _cmp_out

        _cmp_raw = st.session_state.get("crypto_bt_compare", "")
        if _cmp_raw:
            st.code(_cmp_raw, language=None)
            for _line in _cmp_raw.splitlines():
                if "Melhor configuracao" in _line or "Melhor configuração" in _line:
                    st.success(_line.strip())
                    break

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

# ── Tab 7: Paper Trading ──────────────────────────────────────────────────

with tab_paper:
    from paper_trading import (
        get_portfolio,
        get_open_positions,
        get_portfolio_summary,
        reset_portfolio,
    )

    def _paper_brt(utc_str: str) -> str:
        try:
            dt = datetime.fromisoformat(str(utc_str))
            return (dt - timedelta(hours=3)).strftime("%d/%m %H:%M")
        except Exception:
            return str(utc_str)[:16] if utc_str else "—"

    @st.cache_data(ttl=60)
    def _load_paper_summary(pipeline: str) -> dict:
        return get_portfolio_summary(pipeline)

    @st.cache_data(ttl=60)
    def _load_paper_trades(portfolio_id: int) -> "pd.DataFrame":
        try:
            with get_connection() as conn:
                return pd.read_sql(
                    "SELECT symbol, side, price, quantity, value, "
                    "       signal_decision, ai_score, reason, traded_at "
                    "FROM paper_trades "
                    "WHERE portfolio_id = ? ORDER BY traded_at DESC LIMIT 50",
                    conn,
                    params=(portfolio_id,),
                )
        except Exception:
            return pd.DataFrame()

    @st.cache_data(ttl=60)
    def _count_ai_exits(portfolio_id: int) -> int:
        try:
            with get_connection() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM paper_trades "
                    "WHERE portfolio_id = ? AND side = 'SELL' AND reason LIKE 'IA:%'",
                    (portfolio_id,),
                ).fetchone()[0]
        except Exception:
            return 0

    @st.cache_data(ttl=60)
    def _get_hist_contexts(symbols: tuple) -> dict:
        if not symbols:
            return {}
        try:
            with get_connection() as conn:
                placeholders = ",".join("?" * len(symbols))
                rows = conn.execute(
                    f"SELECT cs.symbol, cs.hist_position, cs.pct_from_ma200 "
                    f"FROM crypto_signals cs "
                    f"INNER JOIN ( "
                    f"    SELECT symbol, MAX(created_at) as max_ts "
                    f"    FROM crypto_signals WHERE symbol IN ({placeholders}) GROUP BY symbol "
                    f") latest ON cs.symbol = latest.symbol AND cs.created_at = latest.max_ts "
                    f"WHERE cs.hist_position IS NOT NULL",
                    list(symbols),
                ).fetchall()
            result = {}
            for sym, pos, pct in rows:
                if pos == "below_ma200" and pct is not None:
                    result[sym] = f"{abs(pct):.1f}% abaixo MA200"
                elif pos == "above_ma200" and pct is not None:
                    result[sym] = f"{pct:.1f}% acima MA200"
                elif pct is not None:
                    result[sym] = f"MA200 {pct:+.1f}%"
            return result
        except Exception:
            return {}

    st.subheader("📊 Paper Trading — Simulador R$5.000")
    st.caption("Compras fictícias automáticas em sinais FORTE/MODERADO · Trailing stop 7%")

    if st.button("🔄 Atualizar", key="paper_refresh"):
        _load_paper_summary.clear()
        _load_paper_trades.clear()
        _count_ai_exits.clear()
        _get_hist_contexts.clear()
        st.rerun()

    # Portfolios computed upfront — used in both Section A and B
    _b3_port     = get_portfolio("b3")
    _cripto_port = get_portfolio("cripto")

    # ── Section A: Portfolio cards ────────────────────────────────────────────

    col_b3, col_cripto = st.columns(2)

    for _col, _pipeline, _label, _port in [
        (col_b3, "b3", "B3", _b3_port),
        (col_cripto, "cripto", "Cripto", _cripto_port),
    ]:
        with _col:
            _s = _load_paper_summary(_pipeline)
            _ai_exits_count = _count_ai_exits(_port["id"])
            st.markdown(f"### {_label}")
            st.metric(
                "Capital atual",
                f"R$ {_s['total_value']:,.2f}",
                delta=f"{_s['total_return_pct']:+.2f}%",
            )
            _m1, _m2 = st.columns(2)
            _m1.metric("P&L realizado", f"R$ {_s['total_pnl']:+.2f}")
            _m2.metric("P&L não realizado", f"R$ {_s['unrealized_pnl']:+.2f}")
            _m3, _m4 = st.columns(2)
            _m3.metric("Win rate", f"{_s['win_rate']}%")
            _m4.metric("Op. fechadas", _s["closed_trades"])
            st.metric("Saídas por IA", _ai_exits_count)

    st.markdown("---")

    # ── Section B: Open positions ─────────────────────────────────────────────

    st.subheader("Posições abertas")

    _raw_b3_pos     = get_open_positions(_b3_port["id"])
    _raw_cripto_pos = get_open_positions(_cripto_port["id"])
    _all_pos = (
        [{"Pipeline": "B3", **p} for p in _raw_b3_pos]
        + [{"Pipeline": "Cripto", **p} for p in _raw_cripto_pos]
    )

    if _all_pos:
        # Lookup hist_context from latest crypto_signals for each symbol
        _all_symbols = tuple({p["symbol"] for p in _all_pos})
        _hist_ctx_map = _get_hist_contexts(_all_symbols)
        for _p in _all_pos:
            _p["Contexto"] = _hist_ctx_map.get(_p["symbol"], "—")

        _df_pos = pd.DataFrame(_all_pos)
        _df_pos = _df_pos.rename(columns={
            "symbol":        "Ativo",
            "entry_price":   "Entrada",
            "current_price": "Atual",
            "stop_price":    "Stop",
            "pnl":           "P&L R$",
            "pnl_pct":       "P&L %",
        })
        _keep = ["Pipeline", "Ativo", "Entrada", "Atual", "Stop", "P&L R$", "P&L %", "Contexto"]
        _keep = [c for c in _keep if c in _df_pos.columns]

        def _color_pnl_pct(series: pd.Series) -> list[str]:
            return [
                "color: #4caf50" if (v is not None and v > 0) else "color: #f44336"
                for v in series
            ]

        _styled_pos = _df_pos[_keep].style
        if "P&L %" in _df_pos.columns:
            _styled_pos = _styled_pos.apply(_color_pnl_pct, subset=["P&L %"])
        st.dataframe(_styled_pos, width="stretch")
    else:
        st.info("Nenhuma posição aberta no momento.")

    st.markdown("---")

    # ── Section C: Trade history ──────────────────────────────────────────────

    st.subheader("Histórico")

    _hist_b3, _hist_cripto = st.tabs(["B3", "Cripto"])

    for _htab, _hpipeline, _hport in [
        (_hist_b3, "b3", _b3_port),
        (_hist_cripto, "cripto", _cripto_port),
    ]:
        with _htab:
            _df_tr = _load_paper_trades(_hport["id"])
            if _df_tr.empty:
                st.info("Nenhum trade registrado ainda.")
            else:
                _df_tr = _df_tr.copy()
                _df_tr["traded_at"] = _df_tr["traded_at"].apply(_paper_brt)
                _df_tr = _df_tr.rename(columns={
                    "symbol":          "Ativo",
                    "side":            "Lado",
                    "price":           "Preço",
                    "quantity":        "Qtd",
                    "value":           "Valor R$",
                    "signal_decision": "Decisão",
                    "ai_score":        "Score IA",
                    "reason":          "Razão",
                    "traded_at":       "Data/Hora BRT",
                })

                def _color_side(series: pd.Series) -> list[str]:
                    return [
                        "color: #4caf50" if v == "BUY" else "color: #f44336"
                        for v in series
                    ]

                _styled_tr = _df_tr.style
                if "Lado" in _df_tr.columns:
                    _styled_tr = _styled_tr.apply(_color_side, subset=["Lado"])
                st.dataframe(_styled_tr, width="stretch")

    st.markdown("---")

    # ── Section D: Controls ───────────────────────────────────────────────────

    st.subheader("Controles")
    _ctrl_b3, _ctrl_cripto = st.columns(2)

    with _ctrl_b3:
        if st.button("🔄 Resetar portfólio B3", key="reset_b3_btn"):
            st.session_state["confirm_reset_b3"] = True
        if st.session_state.get("confirm_reset_b3"):
            st.warning("Isso apagará todo o histórico B3. Sem volta.")
            _cy, _cn = st.columns(2)
            if _cy.button("✅ Confirmar", key="yes_b3"):
                reset_portfolio("b3")
                _load_paper_summary.clear()
                _load_paper_trades.clear()
                _count_ai_exits.clear()
                _get_hist_contexts.clear()
                st.session_state["confirm_reset_b3"] = False
                st.success("Portfólio B3 resetado.")
                st.rerun()
            if _cn.button("❌ Cancelar", key="no_b3"):
                st.session_state["confirm_reset_b3"] = False
                st.rerun()

    with _ctrl_cripto:
        if st.button("🔄 Resetar portfólio Cripto", key="reset_cripto_btn"):
            st.session_state["confirm_reset_cripto"] = True
        if st.session_state.get("confirm_reset_cripto"):
            st.warning("Isso apagará todo o histórico Cripto. Sem volta.")
            _cy2, _cn2 = st.columns(2)
            if _cy2.button("✅ Confirmar", key="yes_cripto"):
                reset_portfolio("cripto")
                _load_paper_summary.clear()
                _load_paper_trades.clear()
                _count_ai_exits.clear()
                _get_hist_contexts.clear()
                st.session_state["confirm_reset_cripto"] = False
                st.success("Portfólio Cripto resetado.")
                st.rerun()
            if _cn2.button("❌ Cancelar", key="no_cripto"):
                st.session_state["confirm_reset_cripto"] = False
                st.rerun()

"""Tests for b3/backtester.py — injeção da regra de entrada e trava do JSON.

O backtester importa pandas/yfinance/pandas_ta, que não estão em
requirements-ci.txt (só pytest). O importorskip abaixo faz o CI pular este
arquivo inteiro em vez de quebrar a coleta — os testes rodam localmente, onde
o venv tem as dependências.

Nenhum teste aqui acessa a rede: `yf.download` é substituído por dado sintético.
"""

from unittest.mock import patch

import pytest

pytest.importorskip("pandas", reason="backtester exige pandas — ausente no CI")
pytest.importorskip("pandas_ta", reason="backtester exige pandas_ta — ausente no CI")

import pandas as pd  # noqa: E402

from b3 import backtester as bt  # noqa: E402
from b3.entry_rules import momentum, reversao_moderado  # noqa: E402
from b3.exit_rules import no_fechamento, trailing_producao  # noqa: E402

_NUNCA = lambda c: False   # noqa: E731
_SEMPRE = lambda c: True   # noqa: E731


def _fake_candles(n: int = 300, com_ohlc: bool = True) -> pd.DataFrame:
    """Série diária sintética terminando hoje, com preço oscilando em alta."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = [10.0 + i * 0.05 + (1.5 if i % 3 == 0 else 0.0) for i in range(n)]
    volume = [1_000_000 + (500_000 if i % 5 == 0 else 0) for i in range(n)]
    dados = {"Close": close, "Volume": volume}
    if com_ohlc:
        # Open incluso porque o yfinance sempre devolve OHLC completo — sem ele
        # o fixture nao exercita o caminho `tem_ohlc`, que e onde vivem os
        # modelos de saida.
        dados["Open"] = [c * 0.995 for c in close]
        dados["High"] = [c * 1.02 for c in close]
        dados["Low"] = [c * 0.98 for c in close]
    return pd.DataFrame(dados, index=idx)


# ---------------------------------------------------------------------------
# A regra injetada é quem decide a entrada
# ---------------------------------------------------------------------------

def test_regra_que_nunca_dispara_nao_abre_posicao():
    with patch.object(bt.yf, "download", return_value=_fake_candles()):
        result = bt.run_backtest("XPTO3.SA", entry_rule=_NUNCA)

    assert result["total_trades"] == 0


def test_regra_que_sempre_dispara_abre_posicao():
    with patch.object(bt.yf, "download", return_value=_fake_candles()):
        result = bt.run_backtest("XPTO3.SA", entry_rule=_SEMPRE)

    assert result["total_trades"] > 0


def test_regras_diferentes_dao_resultados_diferentes_no_mesmo_dado():
    """Premissa do backtest comparativo: a régua é a mesma, só a entrada muda."""
    candles = _fake_candles()

    with patch.object(bt.yf, "download", return_value=candles):
        nunca = bt.run_backtest("XPTO3.SA", entry_rule=_NUNCA)
    with patch.object(bt.yf, "download", return_value=candles):
        sempre = bt.run_backtest("XPTO3.SA", entry_rule=_SEMPRE)

    assert nunca["total_trades"] != sempre["total_trades"]


def test_candle_recebe_ema20_preenchida():
    """A tese de momentum precisa da EMA-20; sem ela nunca entraria."""
    vistos = []

    def espiao(candle):
        vistos.append(candle)
        return False

    with patch.object(bt.yf, "download", return_value=_fake_candles()):
        bt.run_backtest("XPTO3.SA", entry_rule=espiao)

    assert vistos, "a regra não foi chamada nenhuma vez"
    assert any(c.ema20 is not None for c in vistos)
    assert all(c.price > 0 and c.volume_ratio > 0 for c in vistos)


def test_serie_sem_high_low_nao_quebra():
    """Backtester aceitava séries só com Close/Volume — continua aceitando.

    Sem OHLC os modelos de saída recebem o fechamento nos quatro campos, o que
    degrada para o comportamento antigo em vez de quebrar.
    """
    with patch.object(bt.yf, "download", return_value=_fake_candles(com_ohlc=False)):
        result = bt.run_backtest("XPTO3.SA", entry_rule=_SEMPRE)

    assert result is not None
    assert result["total_trades"] > 0


def test_vela_em_andamento_com_ohlc_zerado_e_descartada():
    """yfinance publica o pregao aberto com O/H/L = 0 e so o Close.

    Os modelos de saida leem OHLC: abertura=0 satisfaz `abertura <= stop`
    sempre, e a posicao aberta sairia a preco zero — um trade de -100%
    inventado. Deslocou a media do PETR4 em 1.4 p.p. antes de ser pego.
    """
    candles = _fake_candles()
    candles.loc[candles.index[-1], ["Open", "High", "Low"]] = 0.0

    with patch.object(bt.yf, "download", return_value=candles):
        result = bt.run_backtest("XPTO3.SA", entry_rule=_SEMPRE)

    assert result["total_trades"] > 0
    # Saida a preco zero produz -100%: e a assinatura exata do bug.
    with patch.object(bt.yf, "download", return_value=candles):
        detalhe = bt.run_backtest("XPTO3.SA", entry_rule=_SEMPRE, detail=True)
    assert all(t["return_pct"] > -99.0 for t in detalhe["trades"])


def test_vela_zerada_nao_afeta_regra_que_so_le_close():
    """Descartar a vela invalida vale tambem para o modelo antigo, que so lia
    Close e por isso nunca esbarrou no problema."""
    candles = _fake_candles()
    candles.loc[candles.index[-1], ["Open", "High", "Low"]] = 0.0

    with patch.object(bt.yf, "download", return_value=candles):
        result = bt.run_backtest(
            "XPTO3.SA", entry_rule=_SEMPRE, exit_rule=no_fechamento
        )

    assert result is not None
    assert result["total_trades"] > 0


def test_regra_padrao_e_a_de_producao():
    """Sem argumentos, o backtester mede a estrategia que a producao roda.

    O JSON gravado alimenta o gate de compra: se o padrao divergir do que
    b3/decision.py aprova e b3/monitor.py executa, o gate volta a aprovar
    ativos por evidencia de uma estrategia que ninguem roda.
    """
    candles = _fake_candles()

    with patch.object(bt.yf, "download", return_value=candles):
        padrao = bt.run_backtest("XPTO3.SA")
    with patch.object(bt.yf, "download", return_value=candles):
        explicito = bt.run_backtest(
            "XPTO3.SA", entry_rule=momentum, exit_rule=trailing_producao
        )

    assert padrao == explicito


def test_saida_de_pesquisa_com_save_e_recusada():
    """Trocar so a saida tambem corrompe o JSON — a trava pega os dois eixos."""
    with patch.object(bt, "run_backtest") as fake_run:
        with pytest.raises(ValueError, match="régua de produção"):
            bt.run_full_backtest(
                tickers=["XPTO3.SA"], exit_rule=no_fechamento, save=True
            )

    fake_run.assert_not_called()


# ---------------------------------------------------------------------------
# Trava do data/backtest_results.json — alimenta o gate de compra de produção
# ---------------------------------------------------------------------------

def test_save_com_regra_de_pesquisa_e_recusado():
    with patch.object(bt, "run_backtest") as fake_run:
        with pytest.raises(ValueError, match="régua de produção"):
            bt.run_full_backtest(
                tickers=["XPTO3.SA"], entry_rule=reversao_moderado, save=True
            )

    fake_run.assert_not_called()


def test_save_com_periodo_de_pesquisa_e_recusado():
    """Janela curta nao pode virar o gate: com 2 anos o n por ticker cai para
    7-16 trades, faixa em que a metrica e ruido."""
    with patch.object(bt, "run_backtest") as fake_run:
        with pytest.raises(ValueError, match="régua de produção"):
            bt.run_full_backtest(tickers=["XPTO3.SA"], period_days=730, save=True)

    fake_run.assert_not_called()


def test_pesquisa_com_save_false_nao_toca_no_json():
    fake = {"ticker": "XPTO3.SA", "total_trades": 3, "win_rate": 66.6,
            "avg_return_pct": 4.2, "max_drawdown_pct": -5.0, "sharpe_ratio": 0.8,
            "period_days": 730}

    with patch.object(bt, "run_backtest", return_value=fake), \
         patch.object(bt, "_save_results") as fake_save:
        bt.run_full_backtest(
            tickers=["XPTO3.SA"], period_days=730,
            entry_rule=reversao_moderado, save=False
        )

    fake_save.assert_not_called()


def test_run_de_producao_continua_salvando():
    """Regressão: o botão do dashboard e `python -m b3.backtester` dependem disso."""
    fake = {"ticker": "PETR4.SA", "total_trades": 5, "win_rate": 60.0,
            "avg_return_pct": 3.0, "max_drawdown_pct": -8.0, "sharpe_ratio": 0.5,
            "period_days": 730}

    with patch.object(bt, "run_backtest", return_value=fake), \
         patch.object(bt, "_save_results") as fake_save:
        bt.run_full_backtest(tickers=["PETR4.SA"])

    fake_save.assert_called_once()


def test_periodo_e_regra_sao_repassados_para_cada_ticker():
    fake = {"ticker": "X", "total_trades": 0, "win_rate": 0.0, "avg_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "sharpe_ratio": 0.0, "period_days": 730}

    with patch.object(bt, "run_backtest", return_value=fake) as fake_run, \
         patch.object(bt, "_save_results"):
        bt.run_full_backtest(
            tickers=["A.SA", "B.SA"], period_days=730,
            entry_rule=reversao_moderado, save=False
        )

    assert fake_run.call_count == 2
    for call in fake_run.call_args_list:
        assert call.kwargs["period_days"] == 730
        assert call.kwargs["entry_rule"] is reversao_moderado

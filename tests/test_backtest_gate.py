"""Testes do gate de backtest do B3 (só stdlib).

Motivo de existir: o caminho do JSON era relativo ao diretório de trabalho e o
arquivo nunca existe no GitHub Actions (data/ está no .gitignore). O gate que
deveria refletir backtest governava compras com uma lista fixa, avisando
apenas num warning fácil de perder.
"""

import json

import b3.decision as decision


def test_caminho_independe_do_diretorio_atual(monkeypatch, tmp_path):
    """Rodar de outra pasta não pode mudar qual arquivo é lido."""
    monkeypatch.delenv("BACKTEST_RESULTS_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    caminho = decision._backtest_results_path()
    assert caminho.endswith("backtest_results.json")
    assert str(tmp_path) not in caminho


def test_override_por_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESULTS_PATH", "/tmp/aprovados.json")
    assert decision._backtest_results_path() == "/tmp/aprovados.json"


def test_le_aprovados_do_arquivo(monkeypatch, tmp_path):
    arquivo = tmp_path / "aprovados.json"
    arquivo.write_text(
        json.dumps({"results": [
            {"ticker": "PETR4.SA", "total_trades": 75,
             "avg_return_pct": 3.19, "sharpe_ratio": 0.74},
            {"ticker": "XPTO3.SA", "total_trades": 84,
             "avg_return_pct": 0.14, "sharpe_ratio": 0.06},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACKTEST_RESULTS_PATH", str(arquivo))
    aprovados = decision._load_approved_tickers()
    assert aprovados == {"PETR4"}


def test_resultado_incompleto_nao_aprova(monkeypatch, tmp_path):
    """Arquivo de formato antigo (só win_rate/sharpe) nao pode virar permissao.

    Campo ausente reprova por default. Um JSON gerado por uma versao anterior
    do backtester nao carrega expectancia nem contagem de trades, e aprovar
    com base nele seria decidir compra sem os dados que o criterio exige.
    """
    arquivo = tmp_path / "antigo.json"
    arquivo.write_text(
        json.dumps({"results": [
            {"ticker": "PETR4.SA", "win_rate": 75.0, "sharpe_ratio": 1.01},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACKTEST_RESULTS_PATH", str(arquivo))
    # Nenhum aprovado -> cai no fallback, nao em conjunto vazio
    assert decision._load_approved_tickers() == {
        "SBSP3", "VALE3", "ITUB4", "PETR4", "B3SA3", "BBDC4"
    }


def test_cada_eixo_do_criterio_reprova_sozinho(monkeypatch, tmp_path):
    """Os tres eixos sao conjuntivos: falhar em um so ja barra."""
    bom = {"total_trades": 75, "avg_return_pct": 3.19, "sharpe_ratio": 0.74}
    assert decision.ticker_aprovado({"ticker": "A.SA", **bom}) is True

    assert decision.ticker_aprovado({**bom, "total_trades": 29}) is False
    assert decision.ticker_aprovado({**bom, "avg_return_pct": 0.2}) is False
    assert decision.ticker_aprovado({**bom, "sharpe_ratio": 0.49}) is False


def test_ausencia_do_arquivo_e_erro_logado(monkeypatch, tmp_path, caplog):
    """Cair no fallback é degradação silenciosa de um gate de compra."""
    monkeypatch.setenv("BACKTEST_RESULTS_PATH", str(tmp_path / "nao_existe.json"))
    with caplog.at_level("ERROR"):
        aprovados = decision._load_approved_tickers()
    assert "PETR4" in aprovados          # fallback continua valendo
    assert any("BACKTEST" in r.message for r in caplog.records)

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
            {"ticker": "PETR4.SA", "win_rate": 75.0, "sharpe_ratio": 1.01},
            {"ticker": "XPTO3.SA", "win_rate": 40.0, "sharpe_ratio": 0.1},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACKTEST_RESULTS_PATH", str(arquivo))
    aprovados = decision._load_approved_tickers()
    assert aprovados == {"PETR4"}


def test_ausencia_do_arquivo_e_erro_logado(monkeypatch, tmp_path, caplog):
    """Cair no fallback é degradação silenciosa de um gate de compra."""
    monkeypatch.setenv("BACKTEST_RESULTS_PATH", str(tmp_path / "nao_existe.json"))
    with caplog.at_level("ERROR"):
        aprovados = decision._load_approved_tickers()
    assert "PETR4" in aprovados          # fallback continua valendo
    assert any("BACKTEST" in r.message for r in caplog.records)

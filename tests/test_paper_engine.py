"""Testes do paper trading (só stdlib + sqlite).

Foco no patrimônio total. A compra tira dinheiro do caixa e devolve posição;
somar só caixa + P&L não realizado ignora o valor investido e faz o retorno
aparecer negativo logo depois de comprar — número errado numa tela usada para
decidir dinheiro de verdade.
"""

import sqlite3

import pytest

import core.db as db
import paper.engine as engine


@pytest.fixture
def portfolio(tmp_path, monkeypatch):
    """Portfólio 'b3' num banco novo, com capital inicial conhecido."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "paper.db"))
    monkeypatch.setattr(engine, "_initialized", False)
    db.init_db()
    return engine.get_portfolio("b3")


def test_patrimonio_nao_cai_ao_comprar(portfolio):
    """Comprar troca caixa por posição — o total não muda no mesmo preço."""
    engine.execute_paper_buy(
        symbol="PETR4", price=40.0, decision="MODERADO",
        ai_score=70, pipeline="b3", reason="teste",
    )
    resumo = engine.get_portfolio_summary("b3")
    assert resumo["total_value"] == pytest.approx(engine.INITIAL_CAPITAL, abs=0.01)
    assert resumo["total_return_pct"] == pytest.approx(0.0, abs=0.01)


def test_patrimonio_acompanha_valorizacao(portfolio):
    """Posição valorizada entra no total pelo preço atual, não pelo de entrada."""
    engine.execute_paper_buy(
        symbol="PETR4", price=40.0, decision="MODERADO",
        ai_score=70, pipeline="b3", reason="teste",
    )
    engine.check_paper_stops({"PETR4": 44.0}, pipeline="b3")  # +10%
    resumo = engine.get_portfolio_summary("b3")
    investido = engine.INITIAL_CAPITAL * 0.10
    assert resumo["total_value"] == pytest.approx(
        engine.INITIAL_CAPITAL + investido * 0.10, abs=0.5
    )
    assert resumo["unrealized_pnl"] > 0


def test_venda_realiza_o_resultado(portfolio):
    """Depois de fechar, o patrimônio é só caixa — sem dupla contagem."""
    engine.execute_paper_buy(
        symbol="PETR4", price=40.0, decision="MODERADO",
        ai_score=70, pipeline="b3", reason="teste",
    )
    posicoes = engine.get_open_positions(portfolio["id"])
    engine.execute_paper_sell(posicoes[0]["id"], 44.0, "teste", "b3")
    resumo = engine.get_portfolio_summary("b3")
    assert resumo["unrealized_pnl"] == pytest.approx(0.0)
    assert resumo["total_value"] == pytest.approx(resumo["current_capital"])
    assert resumo["total_value"] > engine.INITIAL_CAPITAL

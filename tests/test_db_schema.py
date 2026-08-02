"""Trava que o SQLite local recebe o mesmo schema que o Postgres de produção.

Motivo de existir: as colunas da coleta do `impact` foram adicionadas só no
schema-postgres.sql e via ALTER manual no Supabase. No SQLite elas nunca
chegaram — e como `_persist()` engolia a exceção, o pipeline local gravava
zero auditorias sem reclamar. Estes testes falham se alguém adicionar coluna
no Postgres e esquecer da migração correspondente.

Só stdlib: rodam no CI com requirements-ci.txt (apenas pytest).
"""

import sqlite3

import pytest

import core.db as db


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Banco SQLite novo, isolado do data/ do usuário."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    yield conn
    conn.close()


def _colunas(conn, tabela: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({tabela})")}


def test_audits_tem_coluna_impact(banco):
    """Sem ela `save_audit` falha e a coleta do eixo direcional se perde."""
    assert "impact" in _colunas(banco, "audits")


def test_crypto_signals_tem_ai_impact(banco):
    assert "ai_impact" in _colunas(banco, "crypto_signals")


def test_signal_outcomes_existe(banco):
    """O rótulo da calibração — sem a tabela, analyze_impact.py não grava nada."""
    assert _colunas(banco, "signal_outcomes")


def test_save_audit_persiste_impact(banco, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    signal_id = db.save_signal(
        timestamp="2026-08-02T12:00:00",
        ticker="PETR4",
        rsi=61.0,
        volume_ratio=1.3,
        price=38.5,
        signal_type="BUY",
    )
    db.save_audit(
        signal_id=signal_id,
        gemini_score=70,
        headline="manchete",
        source="OpenRouter",
        verdict="CONFIAVEL",
        raw_response="{}",
        impact=-42,
    )
    row = banco.execute(
        "SELECT impact FROM audits WHERE signal_id = ?", (signal_id,)
    ).fetchone()
    assert row[0] == -42


def test_save_signal_outcome_e_idempotente(banco, tmp_path, monkeypatch):
    """Recalcular o mesmo horizonte atualiza a linha; não duplica a amostra."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    for preco_depois in (110.0, 120.0):
        db.save_signal_outcome(
            pipeline="b3",
            signal_id=1,
            symbol="PETR4",
            horizon_days=3,
            price_at_signal=100.0,
            price_after=preco_depois,
        )
    rows = banco.execute(
        "SELECT return_pct FROM signal_outcomes WHERE signal_id = 1"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(20.0)

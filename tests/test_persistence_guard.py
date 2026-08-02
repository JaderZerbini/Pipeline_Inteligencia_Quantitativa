"""Testes do guard de persistência (só stdlib).

Motivo de existir: o workflow do cripto rodou dias sem DATABASE_URL. O
pipeline gravava no SQLite do runner do Actions, o runner era descartado no
fim do job e cada ciclo relatava sucesso — as chamadas de LLM foram pagas e
jogadas fora. Rodar em ambiente efêmero sem banco remoto é erro de operação,
e erro de operação deve parar cedo e alto.
"""

import pytest

import core.db as db


def test_aborta_no_actions_sem_database_url(monkeypatch):
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db.assert_persistence_configured()


def test_passa_no_actions_com_postgres(monkeypatch):
    monkeypatch.setattr(db, "IS_POSTGRES", True)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    db.assert_persistence_configured()


def test_permite_sqlite_fora_do_actions(monkeypatch):
    """Rodar local sem Postgres é uso legítimo — o disco não some."""
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    db.assert_persistence_configured()


def test_respeita_opt_out_explicito(monkeypatch):
    """Escape hatch para um run de teste no Actions, mas precisa ser dito."""
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("ALLOW_EPHEMERAL_DB", "1")
    db.assert_persistence_configured()

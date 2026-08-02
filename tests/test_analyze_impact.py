"""Testes do script de calibração do eixo `impact` (só stdlib).

Motivo de existir: `created_at` não tem um formato só. O B3 grava naive
("2026-07-31T21:39:21") e o cripto grava aware ("...+00:00"). Comparar os dois
com `datetime.now()` levantava TypeError e derrubava a análise inteira na
primeira amostra de cripto — antes de gravar rótulo nenhum.
"""

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _carregar_modulo():
    """Importa o script sem executá-lo como __main__.

    scripts/ não é pacote e o módulo puxa dotenv no topo; quando a dependência
    não está instalada (CI com requirements-ci.txt) o teste é pulado.
    """
    spec = importlib.util.spec_from_file_location(
        "analyze_impact", _ROOT / "scripts" / "analyze_impact.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(modulo)
    except ImportError as exc:  # dotenv/psycopg2 ausentes no CI
        pytest.skip(f"dependência ausente: {exc}")
    return modulo


def test_normaliza_data_naive():
    m = _carregar_modulo()
    dt = m._como_utc("2026-07-31T21:39:21.725881")
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)


def test_normaliza_data_aware():
    m = _carregar_modulo()
    dt = m._como_utc("2026-07-30T02:39:29.481166+00:00")
    assert dt.tzinfo is not None
    assert dt.hour == 2


def test_normaliza_data_com_sufixo_z():
    m = _carregar_modulo()
    assert m._como_utc("2026-07-30T02:39:29Z").utcoffset() == timedelta(0)


def test_data_invalida_devolve_none():
    m = _carregar_modulo()
    assert m._como_utc("sem data") is None
    assert m._como_utc(None) is None


def test_horizonte_no_futuro_nao_busca_preco():
    """O futuro ainda não aconteceu — e a comparação não pode explodir."""
    m = _carregar_modulo()
    agora_aware = datetime.now(timezone.utc)
    assert m._preco_apos("BTCUSDT", agora_aware, 10) is None

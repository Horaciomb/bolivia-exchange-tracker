"""Tests de version.py: la version sale de pyproject.toml, no de un literal."""

import tomllib
from pathlib import Path

from src import version

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_coincide_con_pyproject():
    with PYPROJECT.open("rb") as f:
        declarada = tomllib.load(f)["project"]["version"]

    assert version.get_version() == declarada


def test_version_usa_fallback_si_falta_el_archivo(monkeypatch, tmp_path):
    monkeypatch.setattr(version, "_PYPROJECT", tmp_path / "no-existe.toml")
    assert version.get_version() == version._FALLBACK


def test_version_usa_fallback_si_el_toml_es_invalido(monkeypatch, tmp_path):
    roto = tmp_path / "pyproject.toml"
    roto.write_text("esto no es TOML valido = = =", encoding="utf-8")
    monkeypatch.setattr(version, "_PYPROJECT", roto)

    assert version.get_version() == version._FALLBACK


def test_version_usa_fallback_si_no_declara_project_version(monkeypatch, tmp_path):
    sin_version = tmp_path / "pyproject.toml"
    sin_version.write_text('[project]\nname = "x"\n', encoding="utf-8")
    monkeypatch.setattr(version, "_PYPROJECT", sin_version)

    assert version.get_version() == version._FALLBACK

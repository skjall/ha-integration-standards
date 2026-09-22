"""The command line, where a repository is not always an integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from ha_integration_standards import cli, protect


def test_check_works_in_a_repository_without_an_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """This package holds no custom_components and still has settings to check."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    assert cli.main(["check"]) == 0

    out = capsys.readouterr().out
    assert "no integration" in out


def test_check_fails_on_a_repository_setting_that_drifted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A branch nothing protects is a failure, not a remark."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(protect, "audit", lambda *a, **k: ("no ruleset on main",))

    assert cli.main(["check"]) == 1
    assert "no ruleset on main" in capsys.readouterr().out


def test_check_passes_where_github_cannot_be_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A fork's contributor has no credentials, and no fault either."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(protect, "audit", lambda *a, **k: None)

    assert cli.main(["check"]) == 0
    assert "GitHub could not be asked" in capsys.readouterr().out

"""The required checks are read out of the workflows, never written twice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ha_integration_standards import protect
from ha_integration_standards.cli import main

QUALITY = """
name: Quality
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps: [{run: ruff check .}]
  test:
    runs-on: ubuntu-latest
    steps: [{run: pytest}]
"""

RELEASE = """
name: Release
on:
  push:
    branches: [main]
jobs:
  publish:
    runs-on: ubuntu-latest
    steps: [{run: twine upload dist/*}]
"""

MATRIX = """
name: Old tests
on: [pull_request]
jobs:
  legacy:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.13", "3.14"]
    steps: [{run: pytest}]
"""

NAMED = """
name: Extra
on:
  pull_request:
jobs:
  build-it:
    name: protocol-package
    runs-on: ubuntu-latest
    steps: [{run: python -m build}]
"""


def _workflows(root: Path, **files: str) -> Path:
    where = root / ".github" / "workflows"
    where.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (where / f"{name}.yml").write_text(body, encoding="utf-8")
    return root


def test_only_pull_request_workflows_count(tmp_path: Path) -> None:
    _workflows(tmp_path, quality=QUALITY, release=RELEASE)

    assert protect.contexts(tmp_path) == ("lint", "test")


def test_a_job_name_wins_over_its_id(tmp_path: Path) -> None:
    _workflows(tmp_path, extra=NAMED)

    assert protect.contexts(tmp_path) == ("protocol-package",)


def test_a_matrix_job_is_left_out(tmp_path: Path) -> None:
    """Its context carries the matrix values; guessing them is the bug."""
    _workflows(tmp_path, quality=QUALITY, old=MATRIX)

    assert protect.contexts(tmp_path) == ("lint", "test")


def test_a_repository_without_workflows_has_nothing_to_require(tmp_path: Path) -> None:
    assert protect.contexts(tmp_path) == ()


def test_broken_yaml_does_not_stop_the_rest(tmp_path: Path) -> None:
    _workflows(tmp_path, quality=QUALITY, broken="jobs: [oh: : no")

    assert protect.contexts(tmp_path) == ("lint", "test")


def test_apply_refuses_when_nothing_reports(tmp_path: Path) -> None:
    with pytest.raises(protect.NoGhError):
        protect.apply(tmp_path)


def test_apply_sends_exactly_what_the_workflows_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY, extra=NAMED)
    sent: dict[str, object] = {}

    def fake_gh(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
        if args[0] == "repo":
            return "acme/kettle\n" if "nameWithOwner" in args else "main\n"
        if args[1] == "--method":
            sent["path"] = args[3]
            sent["body"] = json.loads(stdin or "{}")
            return ""
        return '["lint", "gone-with-the-old-workflow"]'

    monkeypatch.setattr(protect, "_gh", fake_gh)
    done = protect.apply(tmp_path)

    assert sent["path"] == "repos/acme/kettle/branches/main/protection"
    body = sent["body"]
    assert isinstance(body, dict)
    checks = body["required_status_checks"]
    assert isinstance(checks, dict)
    # Sorted by file name, so extra.yml comes before quality.yml.
    assert checks["contexts"] == ["protocol-package", "lint", "test"]
    # A branch must catch up with the base, or a green check says nothing
    # about what will be on the default branch.
    assert checks["strict"] is True
    # Who may merge is not this package's decision.
    assert body["required_pull_request_reviews"] is None
    assert done.dropped == ("gone-with-the-old-workflow",)
    assert done.added == ("protocol-package", "test")


def test_an_unprotected_branch_is_an_outcome_not_a_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)

    def fake_gh(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
        if args[0] == "repo":
            return "acme/kettle\n" if "nameWithOwner" in args else "main\n"
        if args[1] == "--method":
            return ""
        raise protect.NoGhError("Branch not protected (HTTP 404)")

    monkeypatch.setattr(protect, "_gh", fake_gh)
    done = protect.apply(tmp_path)

    assert done.before is None
    assert done.dropped == ()
    assert done.contexts == ("lint", "test")


def test_dry_run_prints_and_changes_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(project, quality=QUALITY)

    def refuse(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
        raise AssertionError("--dry-run must not call gh")

    monkeypatch.setattr(protect, "_gh", refuse)

    assert main(["protect", str(project), "--dry-run"]) == 0
    assert "lint" in capsys.readouterr().out


def test_a_missing_gh_is_reported_not_raised(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(project, quality=QUALITY)

    def refuse(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
        raise protect.NoGhError("the GitHub CLI ('gh') is not installed")

    monkeypatch.setattr(protect, "_gh", refuse)

    assert main(["protect", str(project)]) == 1

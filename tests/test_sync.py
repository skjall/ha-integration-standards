"""Managed files are written, checked, and never silently different."""

from __future__ import annotations

from pathlib import Path

from ha_integration_standards import sync
from ha_integration_standards.cli import main
from ha_integration_standards.discovery import find_integration


def test_sync_writes_and_check_agrees(project: Path) -> None:
    assert main(["sync", str(project)]) == 0
    assert main(["check", str(project)]) == 0


def test_a_hand_edit_is_caught(project: Path) -> None:
    main(["sync", str(project)])
    managed = project / "Dockerfile.test"
    managed.write_text(managed.read_text() + "\nRUN echo surprise\n")
    assert main(["check", str(project)]) == 1


def test_placeholders_come_from_the_project(project: Path) -> None:
    main(["sync", str(project)])
    document = (project / "docs" / "ha-integration-standards.md").read_text()
    assert "custom_components/acme/" in document
    assert "{{" not in document


def test_adopt_leaves_the_integration_alone(project: Path) -> None:
    before = {
        path: path.read_bytes()
        for path in (project / "custom_components").rglob("*")
        if path.is_file()
    }
    assert main(["adopt", str(project)]) == 0
    after = {
        path: path.read_bytes()
        for path in (project / "custom_components").rglob("*")
        if path.is_file()
    }
    assert before == after


def test_adopt_is_idempotent(project: Path) -> None:
    main(["adopt", str(project)])
    config = (project / ".pre-commit-config.yaml").read_text()
    main(["adopt", str(project)])
    assert (project / ".pre-commit-config.yaml").read_text() == config


def test_the_rev_is_raised_rather_than_duplicated(project: Path) -> None:
    it = find_integration(project)
    sync.ensure_precommit(it, version="0.1.0")
    sync.ensure_precommit(it, version="0.2.0")
    text = (project / ".pre-commit-config.yaml").read_text()
    assert text.count("ha-integration-standards") == 1
    assert "rev: v0.2.0" in text

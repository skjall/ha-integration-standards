"""Managed files are written, checked, and never silently different."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


def test_the_block_is_replaced_rather_than_duplicated(project: Path) -> None:
    """A newer release refreshes the gates in place, once."""
    it = find_integration(project)
    sync.ensure_precommit(it, version="0.1.0")
    sync.ensure_precommit(it, version="0.2.0")
    text = (project / ".pre-commit-config.yaml").read_text()
    assert text.count("- id: ha-quality-scale") == 1
    assert "0.2.0" in text
    assert "0.1.0" not in text


def test_the_gates_travel_with_the_project(project: Path) -> None:
    """A synced project can run them with nothing installed."""
    main(["sync", str(project)])
    run = project / "scripts" / "_ha_standards" / "run.py"
    assert run.exists()
    result = subprocess.run(
        [sys.executable, str(run), "quality-scale"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_edited_gate_is_caught_by_the_project_itself(project: Path) -> None:
    """Editing a vendored check fails verify, without the tool being present."""
    main(["sync", str(project)])
    check = project / "scripts" / "_ha_standards" / "checks" / "quality_scale.py"
    check.write_text(check.read_text() + "\n# nothing to see here\n")
    result = subprocess.run(
        [sys.executable, str(project / "scripts/_ha_standards/run.py"), "verify"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "edited by hand" in result.stdout


def test_sync_restores_an_edited_gate(project: Path) -> None:
    main(["sync", str(project)])
    check = project / "scripts" / "_ha_standards" / "checks" / "coverage.py"
    original = check.read_text()
    check.write_text("raise SystemExit(0)\n")
    main(["sync", str(project)])
    assert check.read_text() == original


def test_no_hook_reaches_for_a_remote(project: Path) -> None:
    """The gates must work in a fork's pull request, which gets no secrets."""
    main(["adopt", str(project)])
    config = (project / ".pre-commit-config.yaml").read_text()
    # Every gate has to come from this checkout, not from a clone.
    for line in config.splitlines():
        if line.strip().startswith("- repo:") and "ha-quality-scale" in config:
            assert "ha-integration-standards" not in line

    workflow = (project / ".github" / "workflows" / "quality.yml").read_text()
    published = ("actions/", "home-assistant/", "hacs/", "pypa/", "googleapis/")
    for line in workflow.splitlines():
        if "uses:" in line:
            action = line.split("uses:")[1].strip()
            assert action.startswith(published), f"private dependency: {action}"


def test_the_requirements_reader_includes_the_integrations_own(project: Path) -> None:
    """A library the integration imports has to reach the test environment."""
    import json

    manifest = project / "custom_components" / "acme" / "manifest.json"
    data = json.loads(manifest.read_text())
    data["requirements"] = ["acme-protocol==1.2.3"]
    manifest.write_text(json.dumps(data))

    main(["sync", str(project)])
    result = subprocess.run(
        [sys.executable, "scripts/ha_test_requirements.py"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    # Home Assistant is not installed here, so the component part exits 1 -
    # but the integration's own requirement is printed before that.
    assert "acme-protocol==1.2.3" in result.stdout


def test_mypy_stays_strict_but_not_about_home_assistants_re_exports(
    project: Path,
) -> None:
    """2026.10 reaches BinarySensorDeviceClass through a bare re-export.

    strict turns on --no-implicit-reexport, which then fails the import core
    itself uses. The rule is relaxed for homeassistant and nothing else.
    """
    main(["sync", str(project)])
    config = (project / "mypy.ini").read_text()

    assert "strict = True" in config
    assert "[mypy-homeassistant.*]\nimplicit_reexport = True" in config

    workflow = (project / ".github" / "workflows" / "quality.yml").read_text()
    assert "mypy --config-file mypy.ini" in workflow
    assert "mypy --strict" not in workflow


def test_the_type_gate_reads_the_managed_config(project: Path) -> None:
    """A gate running mypy with its own flags would ignore mypy.ini."""
    main(["sync", str(project)])
    gate = (project / "scripts" / "_ha_standards" / "runner.py").read_text()
    assert "--config-file mypy.ini" in gate


def _hooks(project: Path) -> dict[str, dict[str, object]]:
    config = yaml.safe_load((project / ".pre-commit-config.yaml").read_text())
    return {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}


def test_a_new_hook_file_installs_the_push_gate(project: Path) -> None:
    """A hook type that is not installed never runs - and says nothing."""
    sync.ensure_precommit(find_integration(project))
    config = yaml.safe_load((project / ".pre-commit-config.yaml").read_text())

    assert config["default_install_hook_types"] == [
        "pre-commit",
        "commit-msg",
        "pre-push",
    ]
    hook = _hooks(project)["ha-settings"]
    assert hook["entry"] == "python3 scripts/_ha_standards/run.py settings"
    assert hook["stages"] == ["pre-push"]
    assert hook["pass_filenames"] is False
    assert hook["always_run"] is True


def test_an_existing_hook_file_gains_the_push_hook_type(project: Path) -> None:
    (project / ".pre-commit-config.yaml").write_text(
        "default_install_hook_types: [pre-commit, commit-msg]\n"
        "repos:\n"
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
        "    rev: v0.16.8\n"
        "    hooks:\n"
        "      - id: ruff-check\n"
    )
    sync.ensure_precommit(find_integration(project))
    config = yaml.safe_load((project / ".pre-commit-config.yaml").read_text())

    assert config["default_install_hook_types"] == [
        "pre-commit",
        "commit-msg",
        "pre-push",
    ]
    assert {"ruff-check", "ha-settings"} <= set(_hooks(project))


def test_a_hook_type_the_project_chose_itself_stays(project: Path) -> None:
    (project / ".pre-commit-config.yaml").write_text(
        "default_install_hook_types: [pre-commit, post-checkout]\nrepos:\n"
    )
    sync.ensure_precommit(find_integration(project))
    config = yaml.safe_load((project / ".pre-commit-config.yaml").read_text())

    assert config["default_install_hook_types"] == [
        "pre-commit",
        "post-checkout",
        "commit-msg",
        "pre-push",
    ]


def test_the_settings_gate_travels_with_the_project(project: Path) -> None:
    """Without gh it cannot ask GitHub, and a push is not refused over that."""
    main(["sync", str(project)])
    result = subprocess.run(
        [sys.executable, str(project / "scripts/_ha_standards/run.py"), "settings"],
        cwd=project,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GitHub could not be asked" in result.stdout


def test_a_new_integration_is_protected_before_its_first_push(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Create on GitHub without pushing, protect, and only then push."""
    target = tmp_path / "acme"
    assert (
        main(["new", str(target), "--domain", "acme_kettle", "--owner", "example"]) == 0
    )
    out = capsys.readouterr().out
    create = "gh repo create example/home-assistant-acme-kettle --public --source ."
    assert create in out
    assert "--push" not in out
    assert out.index(create) < out.index("ha-standards protect")
    assert out.index("ha-standards protect") < out.index("git push -u origin main")

    config = yaml.safe_load((target / ".pre-commit-config.yaml").read_text())
    assert "pre-push" in config["default_install_hook_types"]
    assert "ha-settings" in _hooks(target)

"""The next version number, and what it is allowed to claim."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ha_integration_standards.checks import release_config
from ha_integration_standards.discovery import find_integration

CONFIG = {
    "release-type": "simple",
    "packages": {".": {"changelog-path": "CHANGELOG.md"}},
}


def _setup(project: Path, version: str, config: dict | None) -> None:
    manifest = project / "custom_components" / "acme" / "manifest.json"
    content = json.loads(manifest.read_text())
    content["version"] = version
    manifest.write_text(json.dumps(content))
    if config is not None:
        (project / "release-please-config.json").write_text(json.dumps(config))


def _problems(project: Path) -> list[str]:
    return release_config.problems(find_integration(project))


def test_below_one_the_switch_has_to_be_on(project: Path) -> None:
    """Otherwise a raised Home Assistant floor releases itself as 1.0.0."""
    _setup(project, "0.4.1", CONFIG)

    [problem] = _problems(project)
    assert "bump-minor-pre-major" in problem
    assert "1.0.0" in problem


def test_below_one_with_the_switch_on_is_fine(project: Path) -> None:
    config = {**CONFIG, "packages": {".": {"bump-minor-pre-major": True}}}
    _setup(project, "0.4.1", config)

    assert _problems(project) == []


def test_the_switch_may_be_set_once_for_every_package(project: Path) -> None:
    """A top level value applies to a package that does not override it."""
    _setup(project, "0.4.1", {**CONFIG, "bump-minor-pre-major": True})

    assert _problems(project) == []


def test_a_package_may_override_the_top_level_value(project: Path) -> None:
    config = {
        **CONFIG,
        "bump-minor-pre-major": True,
        "packages": {".": {"bump-minor-pre-major": False}},
    }
    _setup(project, "0.4.1", config)

    assert _problems(project) != []


def test_at_one_the_switch_has_to_be_gone(project: Path) -> None:
    """It does nothing there, and a dead switch reads like a live promise."""
    config = {**CONFIG, "packages": {".": {"bump-minor-pre-major": True}}}
    _setup(project, "1.2.3", config)

    [problem] = _problems(project)
    assert "does nothing at or above 1.0.0" in problem


def test_at_one_without_the_switch_is_fine(project: Path) -> None:
    _setup(project, "1.2.3", CONFIG)

    assert _problems(project) == []


def test_a_project_that_releases_by_hand_is_not_this_gates_business(
    project: Path,
) -> None:
    """No release-please, nothing to hold to it."""
    _setup(project, "0.4.1", None)
    (project / "release-please-config.json").unlink(missing_ok=True)

    assert _problems(project) == []


def test_unreadable_json_is_reported_rather_than_ignored(project: Path) -> None:
    _setup(project, "0.4.1", CONFIG)
    (project / "release-please-config.json").write_text("{not json")

    [problem] = _problems(project)
    assert "not valid JSON" in problem


def test_a_prerelease_version_still_counts_as_below_one(project: Path) -> None:
    """0.5.0-rc1 is below 1.0.0, and release-please treats it as 0.5.0."""
    _setup(project, "0.5.0-rc1", CONFIG)

    assert _problems(project) != []


def test_the_gate_reports_what_it_decided(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = {**CONFIG, "packages": {".": {"bump-minor-pre-major": True}}}
    _setup(project, "0.4.1", config)

    assert release_config.main([str(project)]) == 0
    assert "below 1.0.0" in capsys.readouterr().out

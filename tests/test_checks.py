"""The gates catch what they promise to catch."""

from __future__ import annotations

import json
from pathlib import Path

from ha_integration_standards.checks import commit_message, quality_scale
from ha_integration_standards.discovery import find_integration


def run(project: Path) -> int:
    return quality_scale.main([str(project)])


def test_a_clean_project_passes(project: Path) -> None:
    assert run(project) == 0


def test_the_integration_is_found_without_being_named(project: Path) -> None:
    it = find_integration(project / "custom_components" / "acme")
    assert it.domain == "acme"
    assert it.root == project
    assert it.platforms == ("sensor",)


def test_hass_data_instead_of_runtime_data_fails(project: Path) -> None:
    init = project / "custom_components" / "acme" / "__init__.py"
    init.write_text(
        init.read_text().replace("entry.runtime_data = None", "hass.data[DOMAIN] = 1")
    )
    assert run(project) == 1


def test_a_missing_parallel_updates_fails(project: Path) -> None:
    sensor = project / "custom_components" / "acme" / "sensor.py"
    sensor.write_text(sensor.read_text().replace("PARALLEL_UPDATES = 0", ""))
    assert run(project) == 1


def test_a_hardcoded_icon_fails(project: Path) -> None:
    sensor = project / "custom_components" / "acme" / "sensor.py"
    sensor.write_text(
        sensor.read_text().replace(
            'key="temperature"', 'icon="mdi:fire", key="temperature"'
        )
    )
    assert run(project) == 1


def test_a_core_tier_in_the_manifest_fails(project: Path) -> None:
    manifest = project / "custom_components" / "acme" / "manifest.json"
    data = json.loads(manifest.read_text())
    data["quality_scale"] = "platinum"
    manifest.write_text(json.dumps(data))
    assert run(project) == 1


def test_an_untranslated_entity_fails(project: Path) -> None:
    strings = project / "custom_components" / "acme" / "strings.json"
    data = json.loads(strings.read_text())
    data["entity"]["sensor"] = {}
    strings.write_text(json.dumps(data))
    assert run(project) == 1


def test_a_second_language_missing_keys_fails(project: Path) -> None:
    (project / "custom_components" / "acme" / "translations" / "de.json").write_text(
        json.dumps({"entity": {}})
    )
    assert run(project) == 1


def test_a_derived_key_can_be_declared(project: Path) -> None:
    icons = project / "custom_components" / "acme" / "icons.json"
    icons.write_text(
        json.dumps({"entity": {"sensor": {"derived": {"default": "mdi:x"}}}})
    )
    assert run(project) == 1
    (project / "pyproject.toml").write_text(
        '[tool.ha_standards]\nderived_translation_keys = ["sensor:derived"]\n'
    )
    # The icon now belongs to a known entity, but strings.json still lacks it.
    strings = project / "custom_components" / "acme" / "strings.json"
    data = json.loads(strings.read_text())
    data["entity"]["sensor"]["derived"] = {"name": "Derived"}
    strings.write_text(json.dumps(data))
    (project / "custom_components" / "acme" / "translations" / "en.json").write_text(
        json.dumps(data)
    )
    assert run(project) == 0


def test_an_unknown_rule_has_to_be_declared_unenforceable(project: Path) -> None:
    scale = project / "custom_components" / "acme" / "quality_scale.yaml"
    scale.write_text(scale.read_text() + "  invented_rule: done\n")
    assert run(project) == 1
    (project / "pyproject.toml").write_text(
        '[tool.ha_standards]\nunenforceable = ["invented-rule"]\n'
    )
    assert run(project) == 0


def test_a_conventional_english_subject_passes(tmp_path: Path) -> None:
    message = tmp_path / "msg"
    message.write_text("fix: stop the valve guard from crying wolf\n")
    assert commit_message.main([str(message)]) == 0


def test_a_german_message_fails(tmp_path: Path) -> None:
    message = tmp_path / "msg"
    message.write_text("fix: das Ventil bekommt das Wort\n")
    assert commit_message.main([str(message)]) == 1


def test_a_missing_type_fails(tmp_path: Path) -> None:
    message = tmp_path / "msg"
    message.write_text("stop the valve guard from crying wolf\n")
    assert commit_message.main([str(message)]) == 1


def test_trailers_are_not_judged(tmp_path: Path) -> None:
    message = tmp_path / "msg"
    message.write_text(
        "fix: stop the valve guard from crying wolf\n\n"
        "Co-authored-by: Die Werkstatt <nobody@example.com>\n"
    )
    assert commit_message.main([str(message)]) == 0

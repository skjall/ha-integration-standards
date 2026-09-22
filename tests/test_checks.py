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


# --- brand images -----------------------------------------------------------

HOUSE = (0x0A, 0x7E, 0xE8)


def write_png(
    path: Path,
    size: int,
    ground: tuple[int, int, int],
    *,
    one_corner: tuple[int, int, int] | None = None,
) -> None:
    """Write a flat PNG, optionally with a single odd corner pixel."""
    import struct
    import zlib

    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter: none
        for x in range(size):
            odd = one_corner is not None and x == size - 1 and y == 0
            rows.extend(one_corner if odd else ground)

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body))
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


def claim_brands(project: Path, **icons: object) -> None:
    """Put brand: done in the claim and write the icons a test wants."""
    import yaml

    scale = project / "custom_components" / "acme" / "quality_scale.yaml"
    data = yaml.safe_load(scale.read_text())
    data["rules"]["brands"] = "done"
    scale.write_text(yaml.safe_dump(data), encoding="utf-8")
    (project / "hacs.json").write_text(
        json.dumps({"homeassistant": "2026.5.0"}), encoding="utf-8"
    )


def brand(project: Path, name: str) -> Path:
    return project / "custom_components" / "acme" / "brand" / name


def test_brand_icons_in_the_house_style_pass(project: Path) -> None:
    claim_brands(project)
    write_png(brand(project, "icon.png"), 256, HOUSE)
    write_png(brand(project, "icon@2x.png"), 512, HOUSE)
    assert run(project) == 0


def test_a_missing_hdpi_icon_fails(project: Path) -> None:
    claim_brands(project)
    write_png(brand(project, "icon.png"), 256, HOUSE)
    assert run(project) == 1


def test_an_icon_of_the_wrong_size_fails(project: Path) -> None:
    claim_brands(project)
    write_png(brand(project, "icon.png"), 128, HOUSE)
    write_png(brand(project, "icon@2x.png"), 512, HOUSE)
    assert run(project) == 1


def test_an_icon_on_a_foreign_ground_fails(project: Path) -> None:
    claim_brands(project)
    write_png(brand(project, "icon.png"), 256, (0xE8, 0x0A, 0x0A))
    write_png(brand(project, "icon@2x.png"), 512, HOUSE)
    assert run(project) == 1


def test_a_ground_that_is_not_flat_fails(project: Path) -> None:
    claim_brands(project)
    write_png(brand(project, "icon.png"), 256, HOUSE, one_corner=(255, 255, 255))
    write_png(brand(project, "icon@2x.png"), 512, HOUSE)
    assert run(project) == 1


def test_a_project_can_turn_the_colour_check_off(project: Path) -> None:
    claim_brands(project)
    (project / "pyproject.toml").write_text(
        '[tool.ha_standards]\nbrand_color = ""\n', encoding="utf-8"
    )
    write_png(brand(project, "icon.png"), 256, (0xE8, 0x0A, 0x0A))
    write_png(brand(project, "icon@2x.png"), 512, (0xE8, 0x0A, 0x0A))
    assert run(project) == 0


def test_a_project_can_name_its_own_ground(project: Path) -> None:
    claim_brands(project)
    (project / "pyproject.toml").write_text(
        '[tool.ha_standards]\nbrand_color = "#E80A0A"\n', encoding="utf-8"
    )
    write_png(brand(project, "icon.png"), 256, (0xE8, 0x0A, 0x0A))
    write_png(brand(project, "icon@2x.png"), 512, (0xE8, 0x0A, 0x0A))
    assert run(project) == 0


def test_a_dark_variant_is_held_to_the_same_size(project: Path) -> None:
    claim_brands(project)
    write_png(brand(project, "icon.png"), 256, HOUSE)
    write_png(brand(project, "icon@2x.png"), 512, HOUSE)
    write_png(brand(project, "dark_icon.png"), 64, HOUSE)
    assert run(project) == 1


def test_hacs_below_the_release_that_serves_local_icons_fails(project: Path) -> None:
    claim_brands(project)
    write_png(brand(project, "icon.png"), 256, HOUSE)
    write_png(brand(project, "icon@2x.png"), 512, HOUSE)
    (project / "hacs.json").write_text(
        json.dumps({"homeassistant": "2025.12.0"}), encoding="utf-8"
    )
    assert run(project) == 1

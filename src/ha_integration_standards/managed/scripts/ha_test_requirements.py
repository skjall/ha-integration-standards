#!/usr/bin/env python3
"""Print the requirements of the Home Assistant components we pull in.

pytest-homeassistant-custom-component installs Home Assistant, but not what
the components it pulls in need at runtime. Pinning those by hand means the
numbers drift from the release being tested against, and a dependency bot
keeps proposing bumps that must never be taken on their own. Reading them out
of the installed release removes both problems: they are always exactly right,
and there is nothing left to pin.

Which components to read is taken from the integration's own manifest, so this
file never has to be edited.
"""

from __future__ import annotations

import json
import site
import sys
from pathlib import Path


def _components_directory() -> Path | None:
    for directory in site.getsitepackages():
        components = Path(directory) / "homeassistant" / "components"
        if components.is_dir():
            return components
    return None


def _wanted() -> list[str]:
    """Return the components this integration declares as dependencies."""
    for manifest in sorted(Path("custom_components").glob("*/manifest.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        wanted = list(data.get("dependencies", []))
        # An integration that depends on bluetooth_adapters also needs what
        # the bluetooth component itself pulls in.
        if "bluetooth_adapters" in wanted:
            wanted += ["bluetooth", "usb"]
        return sorted(set(wanted))
    return []


def main() -> int:
    """Print one requirement per line."""
    components = _components_directory()
    if components is None:
        print("Home Assistant is not installed", file=sys.stderr)
        return 1

    for name in _wanted():
        manifest = components / name / "manifest.json"
        if not manifest.exists():
            continue
        for requirement in json.loads(manifest.read_text()).get("requirements", []):
            print(requirement)
    return 0


if __name__ == "__main__":
    sys.exit(main())

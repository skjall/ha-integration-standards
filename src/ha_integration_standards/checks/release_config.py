"""Hold release-please to what the version number is allowed to say.

SemVer puts MAJOR on "incompatible API changes" to the *public API* - for an
integration that is its entities, their ids and attributes, its services and
the config entry options; for a package under lib/ the API it exports. A
raised floor for Home Assistant is none of those: it is a requirement of the
platform underneath, and the specification has nothing to say about it.

release-please does not know that. A `BREAKING CHANGE:` footer below 1.0.0
takes it straight to 1.0.0, which claims a stability the project never
declared. `bump-minor-pre-major` is the switch that keeps a breaking change
inside 0.x, and nothing reminded anybody to set it until a release pull
request asked for 1.0.0.

So: below 1.0.0 the switch must be on. At or above 1.0.0 it does nothing and
must be gone, because a dead switch reads like a live promise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..discovery import Integration, NoIntegrationError, find_integration

CONFIG = "release-please-config.json"
OPTION = "bump-minor-pre-major"


def _version(it: Integration) -> tuple[int, ...] | None:
    """Read the version the integration ships, as release-please sees it."""
    raw = it.manifest.get("version")
    if not isinstance(raw, str):
        return None
    try:
        return tuple(int(part) for part in raw.split("-")[0].split(".")[:3])
    except ValueError:
        return None


def problems(it: Integration) -> list[str]:
    """Everything wrong with how this repository will pick its next version."""
    config = it.root / CONFIG
    if not config.exists():
        # A repository may release by hand; that is not this gate's business.
        return []
    try:
        content = json.loads(config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        return [f"{CONFIG} is not valid JSON: {err}"]

    version = _version(it)
    if version is None:
        return ['manifest.json has no readable "version"']

    packages = content.get("packages")
    if not isinstance(packages, dict) or not packages:
        return [f"{CONFIG} declares no packages"]

    found: list[str] = []
    for name, package in packages.items():
        if not isinstance(package, dict):
            continue
        # A top level value applies to every package that does not override it.
        setting = package.get(OPTION, content.get(OPTION))
        if version < (1, 0, 0) and setting is not True:
            found.append(
                f'{CONFIG}: package "{name}" does not set "{OPTION}": true, so a '
                f"BREAKING CHANGE footer would release {'.'.join(map(str, version))} "
                "as 1.0.0 - a stability claim, not a consequence of the change. "
                "Raising the Home Assistant floor is not a change to the public "
                "API."
            )
        elif version >= (1, 0, 0) and setting is True:
            found.append(
                f'{CONFIG}: package "{name}" still sets "{OPTION}": true, which '
                "does nothing at or above 1.0.0. Remove it, so the file does not "
                "promise a bump it cannot give."
            )
    return found


def main(argv: list[str] | None = None) -> int:
    """Report how the next version will be chosen."""
    argv = list(argv or sys.argv[1:])
    start = Path(argv[0]) if argv else Path.cwd()
    try:
        it = find_integration(start)
    except NoIntegrationError as err:
        print(f"  release config: {err}", file=sys.stderr)
        return 1

    found = problems(it)
    if found:
        print("Release config: the next version would not be the honest one\n")
        for problem in found:
            print(f"  FAIL  {problem}")
        return 1

    version = _version(it)
    where = "below" if version and version < (1, 0, 0) else "at or above"
    print(
        f"Release config: {'.'.join(map(str, version or ()))} is {where} 1.0.0 "
        f'and "{OPTION}" is set accordingly.'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

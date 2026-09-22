"""Write the checks into the project that runs them.

The integrations are public and their CI runs on GitHub; this package is not
public. A hook that clones it, or a CI step that installs it from a private
index, would need a token - and a public repository hands no secrets to a
fork's pull request, so every outside contribution would go red through no
fault of its own.

So the checks are vendored: `ha-standards sync` writes them into the project,
under one directory that nobody edits by hand, together with the version they
came from and a hash of each file. Updating is a deliberate commit - pull a
newer standards release, sync, review the diff - and CI needs nothing but the
repository it already has.
"""

from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path

from . import __version__

# Where the vendored copy lives inside a project.
VENDOR = "scripts/_ha_standards"

# The modules a project needs to run the gates. cli.py, sync.py and vendor.py
# stay behind: a project consumes the checks, it does not re-publish them.
MODULES = (
    "__init__.py",
    "config.py",
    "discovery.py",
    "runner.py",
    "checks/__init__.py",
    "checks/brand_image.py",
    "checks/commit_message.py",
    "checks/coverage.py",
    "checks/quality_scale.py",
)

HEADER = (
    "# Vendored from ha-integration-standards {version}. Do not edit:\n"
    "# `ha-standards sync` rewrites this file, and `run.py verify` fails the\n"
    "# commit when it has been changed by hand.\n"
)


def _source(name: str) -> str:
    """Return one module as this release ships it."""
    return (resources.files(__package__) / name).read_text(encoding="utf-8")


def _runner() -> str:
    """Return the entry point a vendored copy is driven through."""
    return (resources.files(__package__) / "managed" / "run.py").read_text(
        encoding="utf-8"
    )


def contents(version: str = __version__) -> dict[str, str]:
    """Return every vendored file, keyed by its path in the project."""
    files: dict[str, str] = {}
    for name in MODULES:
        text = _source(name)
        # __init__.py carries the version, so the vendored copy reports the
        # release it came from rather than the one that happens to be around.
        if name == "__init__.py":
            text = text.replace(
                f'__version__ = "{__version__}"', f'__version__ = "{version}"'
            )
        files[f"{VENDOR}/{name}"] = HEADER.format(version=version) + "\n" + text
    files[f"{VENDOR}/run.py"] = HEADER.format(version=version) + "\n" + _runner()

    digest = "\n".join(
        f"{hashlib.sha256(text.encode()).hexdigest()}  {path[len(VENDOR) + 1 :]}"
        for path, text in sorted(files.items())
    )
    files[f"{VENDOR}/MANIFEST.sha256"] = (
        f"# ha-integration-standards {version}\n"
        "# Checked by `run.py verify`; regenerate with `ha-standards sync`.\n"
        f"{digest}\n"
    )
    return files


def verify(root: Path) -> list[str]:
    """Return the vendored files that do not match their recorded hash."""
    manifest = root / VENDOR / "MANIFEST.sha256"
    if not manifest.exists():
        return [f"{VENDOR}/MANIFEST.sha256: missing"]

    problems: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        expected, _, name = line.partition("  ")
        path = root / VENDOR / name
        if not path.exists():
            problems.append(f"{VENDOR}/{name}: missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(f"{VENDOR}/{name}: edited by hand")
    return problems

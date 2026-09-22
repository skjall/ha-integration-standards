"""Write, and check, the files this package manages in a project.

The point of a managed file is that a project never maintains it. Taking a
newer release of this package and running `ha-standards sync` is the whole
update procedure; `ha-standards check` (the `ha-sync` hook) fails when one of
them has been edited by hand or has fallen behind.

Nothing outside MANAGED is ever touched. The integration's own code, its
tests, its README and its quality_scale.yaml are the project's business.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from . import __version__, vendor
from .discovery import Integration

# source inside managed/  ->  destination in the project
MANAGED: dict[str, str] = {
    "docs/ha-integration-standards.md": "docs/ha-integration-standards.md",
    "Dockerfile.test": "Dockerfile.test",
    "scripts/ha_test_requirements.py": "scripts/ha_test_requirements.py",
    ".github/workflows/quality.yml": ".github/workflows/quality.yml",
}

# What CLAUDE.md needs so the standards reach the assistant working here.
CLAUDE_IMPORT = "@docs/ha-integration-standards.md"

# The hooks, pointing at the vendored copy. They are local on purpose: this
# package is private and the integrations are public, so a hook that cloned it
# would need a token that a fork's pull request never gets.
PRECOMMIT_BLOCK = """  - repo: local
    hooks:
      # Written by ha-integration-standards {version}; `ha-standards sync`
      # updates them. Run `python3 {vendor}/run.py --help` to see the gates.
      - id: ha-verify
        name: Gates - the vendored copy is the one that was synced
        entry: python3 {vendor}/run.py verify
        language: system
        pass_filenames: false
        always_run: true

      - id: ha-quality-scale
        name: Quality scale - the code holds what quality_scale.yaml claims
        entry: python3 {vendor}/run.py quality-scale
        language: system
        pass_filenames: false
        always_run: true

      - id: ha-types
        name: Types - mypy --strict against the targeted Home Assistant
        entry: python3 {vendor}/run.py types
        language: system
        pass_filenames: false
        always_run: true

      - id: ha-tests
        name: Tests - against the targeted Home Assistant, in Docker
        entry: python3 {vendor}/run.py tests -q
        language: system
        pass_filenames: false
        always_run: true

      - id: ha-coverage
        name: Coverage - the floors the claimed tier requires
        entry: python3 {vendor}/run.py coverage
        language: system
        pass_filenames: false
        always_run: true

      - id: ha-commit-message
        name: Commit message - Conventional Commits, in English
        entry: python3 {vendor}/run.py commit-message
        language: system
        stages: [commit-msg]
"""


# What the image build needs when the project builds its own package. The
# requirements reader installs such a package from `lib/` rather than from
# PyPI, so `lib/` has to be in the build context - and a project without one
# must not end up with a COPY of a directory that is not there, which fails the
# build for that project alone. Hence a whole block rather than a path: it is
# either present or it is nothing at all.
LOCAL_PACKAGES = """

# The package this repository builds itself, so it is installed from here
# rather than from PyPI: the published version is the one before the change
# under test, and during a release it does not exist yet at all.
COPY lib/ /tmp/setup/lib/"""


@dataclass(frozen=True)
class Placeholders:
    """The few values a managed file may mention about its project."""

    domain: str
    name: str
    owner: str
    repo: str
    local_packages: str

    def render(self, text: str) -> str:
        """Fill the placeholders in one managed file."""
        for key, value in {
            "domain": self.domain,
            "name": self.name,
            "owner": self.owner,
            "repo": self.repo,
            "local_packages": self.local_packages,
        }.items():
            text = text.replace("{{" + key + "}}", value)
        return text


def placeholders_for(it: Integration) -> Placeholders:
    """Read everything a managed file may need out of the project itself."""
    owner, repo = _origin(it.root)
    documentation = it.manifest.get("documentation", "")
    if match := re.search(r"github\.com/([^/]+)/([^/#?]+)", documentation):
        owner, repo = owner or match.group(1), repo or match.group(2)
    return Placeholders(
        domain=it.domain,
        name=it.manifest.get("name", it.domain),
        owner=owner or "OWNER",
        repo=repo or it.root.name,
        local_packages=LOCAL_PACKAGES if _builds_its_own_package(it.root) else "",
    )


def _builds_its_own_package(root: Path) -> bool:
    """Whether this project publishes a package of its own from `lib/`."""
    return any((root / "lib").glob("*/pyproject.toml"))


def _origin(root: Path) -> tuple[str, str]:
    """Return the owner and repository from the git remote, if there is one."""
    try:
        url = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "", ""
    if match := re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url):
        return match.group(1), match.group(2)
    return "", ""


def _template(name: str) -> str:
    """One managed file as this release ships it."""
    root = resources.files(__package__) / "managed"
    return (root / name).read_text(encoding="utf-8")


def rendered(it: Integration) -> dict[str, str]:
    """Every managed file, as it should look in this project."""
    values = placeholders_for(it)
    files = {
        destination: values.render(_template(source))
        for source, destination in MANAGED.items()
    }
    # The gates themselves travel with the project rather than being fetched.
    files.update(vendor.contents())
    return files


def write(it: Integration) -> list[str]:
    """Write every managed file. Returns the paths that changed."""
    changed: list[str] = []
    for destination, content in rendered(it).items():
        path = it.root / destination
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if destination.endswith(".py") or destination.endswith(".sh"):
            path.chmod(0o755)
        changed.append(destination)
    return changed


def drift(it: Integration) -> dict[str, str]:
    """Return the managed files that are missing or changed by hand."""
    problems: dict[str, str] = {}
    for destination, content in rendered(it).items():
        path = it.root / destination
        if not path.exists():
            problems[destination] = "missing"
        elif path.read_text(encoding="utf-8") != content:
            problems[destination] = "edited by hand, or from an older release"
    return problems


# --- wiring a project up ----------------------------------------------------


MARKER = f"{vendor.VENDOR}/run.py"


def ensure_precommit(it: Integration, version: str = __version__) -> str | None:
    """Put the gates into .pre-commit-config.yaml, or refresh them.

    Everything else in the file is left exactly as it is: other hooks, other
    repos, the project's own ordering.
    """
    path = it.root / ".pre-commit-config.yaml"
    block = PRECOMMIT_BLOCK.format(version=version, vendor=vendor.VENDOR)

    if not path.exists():
        path.write_text(
            "default_install_hook_types: [pre-commit, commit-msg]\n"
            "default_stages: [pre-commit]\n\nrepos:\n" + block,
            encoding="utf-8",
        )
        return "created"

    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        # Replace the whole block: which gates exist is this package's call,
        # not the project's, and a stale list would silently drop one.
        start = text.index("  - repo: local\n")
        while (
            start > 0
            and MARKER not in text[start : text.find("  - repo: ", start + 10)]
        ):
            start = text.find("  - repo: local\n", start + 1)
            if start == -1:
                return "could not find the block to replace"
        end = text.find("  - repo: ", start + 10)
        end = len(text) if end == -1 else end
        updated = text[:start] + block + text[end:]
        if updated == text:
            return None
        path.write_text(updated, encoding="utf-8")
        return f"gates refreshed for {version}"

    if "repos:" not in text:
        return "no 'repos:' key - add the hooks by hand"
    text = text.replace("repos:\n", "repos:\n" + block, 1)
    path.write_text(text, encoding="utf-8")
    return "hooks added"


def ensure_claude_import(it: Integration) -> str | None:
    """Make sure CLAUDE.md pulls in the managed standards document."""
    path = it.root / "CLAUDE.md"
    if not path.exists():
        path.write_text(
            f"# CLAUDE.md\n\nGuidance for Claude Code in this repository.\n\n"
            f"The development ground rules are shared across integrations and "
            f"are kept up to date by ha-integration-standards:\n\n"
            f"{CLAUDE_IMPORT}\n\n"
            f"## About this integration\n\n"
            f"<!-- What is specific to {it.domain}: the device, its protocol, "
            f"the decisions only this repository has to make. -->\n",
            encoding="utf-8",
        )
        return "created"
    text = path.read_text(encoding="utf-8")
    if CLAUDE_IMPORT in text:
        return None
    path.write_text(
        text.rstrip() + "\n\n## Development standards\n\n" + f"{CLAUDE_IMPORT}\n",
        encoding="utf-8",
    )
    return "import added"


def ensure_settings(it: Integration) -> str | None:
    """Leave a commented [tool.ha_standards] block if there is none."""
    path = it.root / "pyproject.toml"
    block = (
        "\n[tool.ha_standards]\n"
        "# Defaults apply when a key is absent; write one down only when this\n"
        "# project genuinely differs. See the standards document for what each\n"
        "# key means.\n"
        "# overall_coverage = 95\n"
        "# unenforceable = []\n"
        "# derived_translation_keys = []\n"
        "\n[tool.ha_standards.coverage]\n"
        '# "config_flow.py" = 100\n'
    )
    if not path.exists():
        path.write_text(block.lstrip(), encoding="utf-8")
        return "created"
    text = path.read_text(encoding="utf-8")
    if "[tool.ha_standards" in text:
        return None
    path.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    return "settings block added"

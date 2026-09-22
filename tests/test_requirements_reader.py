"""What the tests are told to install, and where it is installed from."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ha_integration_standards.cli import main

LIBRARY_PYPROJECT = """
[project]
name = "acme-protocol"
version = "1.2.3"
"""


def _with_library(project: Path, requirement: str = "acme-protocol==1.2.3") -> Path:
    """Give the project a package of its own, pinned in the manifest."""
    library = project / "lib" / "acme_protocol"
    library.mkdir(parents=True)
    (library / "pyproject.toml").write_text(LIBRARY_PYPROJECT, encoding="utf-8")

    manifest = project / "custom_components" / "acme" / "manifest.json"
    content = json.loads(manifest.read_text(encoding="utf-8"))
    content["requirements"] = [requirement]
    manifest.write_text(json.dumps(content), encoding="utf-8")
    return library


def _requirements(project: Path) -> list[str]:
    """Run the reader the way the workflow runs it, and return what it printed."""
    result = subprocess.run(
        [sys.executable, "scripts/ha_test_requirements.py"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.split()


def test_a_package_from_this_repository_is_installed_from_here(project: Path) -> None:
    """The pin would name a version that PyPI does not have during a release."""
    main(["sync", str(project)])
    library = _with_library(project)

    printed = _requirements(project)

    assert str(library) in printed
    assert "acme-protocol==1.2.3" not in printed


def test_the_spelling_of_the_pin_does_not_matter(project: Path) -> None:
    """`Acme_Protocol` and `acme-protocol` are the same distribution."""
    main(["sync", str(project)])
    library = _with_library(project, requirement="Acme_Protocol>=1.0")

    assert str(library) in _requirements(project)


def test_a_package_from_pypi_keeps_its_pin(project: Path) -> None:
    """Only what the repository builds itself is taken from the checkout."""
    main(["sync", str(project)])
    _with_library(project)

    manifest = project / "custom_components" / "acme" / "manifest.json"
    content = json.loads(manifest.read_text(encoding="utf-8"))
    content["requirements"] = ["acme-protocol==1.2.3", "bleak-retry-connector>=3.5.0"]
    manifest.write_text(json.dumps(content), encoding="utf-8")

    assert "bleak-retry-connector>=3.5.0" in _requirements(project)


def test_the_image_build_copies_a_local_package_in(project: Path) -> None:
    """The reader can only install from `lib/` if `lib/` is in the context."""
    _with_library(project)
    main(["sync", str(project)])

    assert "COPY lib/ /tmp/setup/lib/" in (project / "Dockerfile.test").read_text()


def test_a_project_without_a_package_gets_no_copy(project: Path) -> None:
    """COPY of a directory that is not there fails the build for that project."""
    main(["sync", str(project)])

    dockerfile = (project / "Dockerfile.test").read_text()
    assert "lib/" not in dockerfile
    assert "{{" not in dockerfile

"""Run the tests and the type check where they mean something.

Home Assistant needs Python 3.14.2 from 2026.3 onwards, which most systems do
not have. Running the suite on whatever interpreter happens to be installed
means testing an API that is not the one users have. So both run in a
container built from the version the integration targets.

Isolation is part of the point: the source is mounted read-only, the container
runs as the calling user and without a network, so a run cannot change the
working tree or reach out. Everything a run produces lands in the artefacts
directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config
from .discovery import Integration, NoIntegrationError, find_integration

DOCKERFILE = "Dockerfile.test"


def _image_name(it: Integration) -> str:
    return f"{it.domain.replace('_', '-')}-test"


def _ensure_image(it: Integration) -> str:
    """Build the test image if it is not there yet."""
    if not shutil.which("docker"):
        raise RuntimeError(
            "docker is required: the suite runs against the Home Assistant "
            "release this integration targets, not against the local Python."
        )
    image = _image_name(it)
    present = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        check=False,
    )
    if present.returncode == 0:
        return image

    dockerfile = it.root / DOCKERFILE
    if not dockerfile.exists():
        raise RuntimeError(
            f"{DOCKERFILE} is missing - run 'ha-standards sync' to write the "
            "managed one."
        )
    print(f"Building {image} ...", flush=True)
    subprocess.run(
        ["docker", "build", "-q", "-f", str(dockerfile), "-t", image, str(it.root)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return image


def _run(it: Integration, image: str, command: list[str], *, network: bool) -> int:
    artefacts = it.root / ".artefakte"
    artefacts.mkdir(exist_ok=True)
    docker = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-e",
        "HOME=/tmp",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "COVERAGE_FILE=/ausgabe/.coverage",
        "-v",
        f"{it.root}:/app:ro",
        "-v",
        f"{artefacts}:/ausgabe",
        "-w",
        "/app",
    ]
    if not network:
        docker += ["--network", "none"]
    docker += [image, *command]
    return subprocess.run(docker, check=False).returncode


def _integration() -> Integration:
    try:
        return find_integration(Path.cwd())
    except NoIntegrationError as err:
        print(f"  {err}", file=sys.stderr)
        raise SystemExit(1) from err


def tests(argv: list[str] | None = None) -> int:
    """Run pytest inside the container, coverage report into .artefakte/."""
    it = _integration()
    settings = config.load(it.root)
    image = _ensure_image(it)
    report = Path(settings.coverage_report).name
    return _run(
        it,
        image,
        [
            "pytest",
            "-p",
            "no:cacheprovider",
            f"--cov=custom_components.{it.domain}",
            f"--cov-report=json:/ausgabe/{report}",
            *(argv or sys.argv[1:]),
        ],
        network=False,
    )


def types(argv: list[str] | None = None) -> int:
    """Type check in the same environment. Platinum asks for strict."""
    it = _integration()
    image = _ensure_image(it)
    target = it.path.relative_to(it.root).as_posix()
    # mypy is installed here rather than baked into the image so that a bumped
    # mypy takes effect without rebuilding.
    return _run(
        it,
        image,
        [
            "sh",
            "-c",
            "pip install -q mypy >/dev/null 2>&1; "
            f"mypy --strict --ignore-missing-imports --cache-dir=/tmp/mypy {target}",
        ],
        network=True,
    )


if __name__ == "__main__":
    raise SystemExit(tests())

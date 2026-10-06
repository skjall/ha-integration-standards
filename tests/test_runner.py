"""The container the gates run in, and how long it may be trusted."""

from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from ha_integration_standards import runner


def _docker(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


def test_an_image_that_is_not_there_has_no_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _docker("", returncode=1))

    assert runner._image_age("acme-test") is None


def test_the_age_is_read_from_dockers_own_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker's format carries nanoseconds and a Z; both have to survive."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _docker("2026-09-22T19:08:11.123456789Z\n"),
    )

    age = runner._image_age("acme-test")

    assert age is not None
    assert age > timedelta(days=13)


def test_a_timestamp_that_cannot_be_read_counts_as_no_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebuilding costs minutes; trusting an image of unknown age costs more."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _docker("yesterday\n"))

    assert runner._image_age("acme-test") is None


def test_a_stale_image_is_rebuilt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Nothing in the image is pinned, so a kept image is not a kept version."""
    (tmp_path / runner.DOCKERFILE).write_text("FROM python:3.14\n")
    builds: list[list[str]] = []

    monkeypatch.setattr(runner.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        runner,
        "_image_age",
        lambda _: timedelta(days=runner.MAX_IMAGE_AGE_DAYS),
    )
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda cmd, **k: (
            builds.append(cmd) or subprocess.CompletedProcess(args=cmd, returncode=0)
        ),
    )

    class _It:
        domain = "acme"

    it = _It()
    it.root = tmp_path  # type: ignore[attr-defined]
    runner._ensure_image(it)  # type: ignore[arg-type]

    assert builds and builds[0][:2] == ["docker", "build"]
    assert "days old" in capsys.readouterr().out


def test_a_fresh_image_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(runner, "_image_age", lambda _: timedelta(hours=1))

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a fresh image must not be rebuilt")

    monkeypatch.setattr(runner.subprocess, "run", refuse)

    class _It:
        domain = "acme"
        root = runner.Path(".")

    assert runner._ensure_image(_It()) == "acme-test"  # type: ignore[arg-type]

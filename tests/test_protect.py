"""The required checks are read out of the workflows, never written twice."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from ha_integration_standards import protect
from ha_integration_standards.cli import main

QUALITY = """
name: Quality
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps: [{run: ruff check .}]
  test:
    runs-on: ubuntu-latest
    steps: [{run: pytest}]
"""

RELEASE = """
name: Release
on:
  push:
    branches: [main]
jobs:
  publish:
    runs-on: ubuntu-latest
    steps: [{run: twine upload dist/*}]
"""

MATRIX = """
name: Old tests
on: [pull_request]
jobs:
  legacy:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.13", "3.14"]
    steps: [{run: pytest}]
"""

NAMED = """
name: Extra
on:
  pull_request:
jobs:
  build-it:
    name: protocol-package
    runs-on: ubuntu-latest
    steps: [{run: python -m build}]
"""


PUBLISH = """
name: Release
on:
  push:
    branches: [main]
jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    steps:
      - uses: actions/download-artifact@v4
      - uses: pypa/gh-action-pypi-publish@release/v1
"""


def _package(root: Path, name: str = "kettle-protocol") -> None:
    where = root / "lib" / "kettle_protocol"
    where.mkdir(parents=True)
    (where / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')


def _workflows(root: Path, **files: str) -> Path:
    where = root / ".github" / "workflows"
    where.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (where / f"{name}.yml").write_text(body, encoding="utf-8")
    return root


def test_only_pull_request_workflows_count(tmp_path: Path) -> None:
    _workflows(tmp_path, quality=QUALITY, release=RELEASE)

    assert protect.contexts(tmp_path) == ("lint", "test")


def test_a_job_name_wins_over_its_id(tmp_path: Path) -> None:
    _workflows(tmp_path, extra=NAMED)

    assert protect.contexts(tmp_path) == ("protocol-package",)


def test_a_matrix_job_is_left_out(tmp_path: Path) -> None:
    """Its context carries the matrix values; guessing them is the bug."""
    _workflows(tmp_path, quality=QUALITY, old=MATRIX)

    assert protect.contexts(tmp_path) == ("lint", "test")


def test_a_repository_without_workflows_has_nothing_to_require(tmp_path: Path) -> None:
    assert protect.contexts(tmp_path) == ()


def test_broken_yaml_does_not_stop_the_rest(tmp_path: Path) -> None:
    _workflows(tmp_path, quality=QUALITY, broken="jobs: [oh: : no")

    assert protect.contexts(tmp_path) == ("lint", "test")


def test_apply_refuses_when_nothing_reports(tmp_path: Path) -> None:
    with pytest.raises(protect.NoGhError):
        protect.apply(tmp_path)


class FakeGitHub:
    """Answer the gh calls protect makes, and remember every write."""

    def __init__(
        self,
        protected: list[str] | None = None,
        rulesets: list[dict[str, object]] | None = None,
        policies: list[dict[str, str]] | None = None,
        ruleset_contexts: list[str] | None = None,
    ) -> None:
        self.protected = protected
        self.rulesets = rulesets or []
        self.policies = policies or []
        self.ruleset_contexts = ruleset_contexts or []
        self.writes: list[tuple[str, str, object]] = []

    def __call__(
        self, *args: str, stdin: str | None = None, cwd: Path | None = None
    ) -> str:
        if args[0] == "repo":
            return "acme/kettle\n" if "nameWithOwner" in args else "main\n"
        if args[1] == "--method":
            method, path = args[2], args[3]
            if method == "DELETE" and path.endswith("/protection"):
                if self.protected is None:
                    raise protect.NoGhError("Branch not protected (HTTP 404)")
                self.protected = None
            body: object = json.loads(stdin) if stdin else list(args[4:])
            self.writes.append((method, path, body))
            return ""
        path = args[1]
        if path.endswith("/protection"):
            if self.protected is None:
                raise protect.NoGhError("Branch not protected (HTTP 404)")
            return json.dumps(self.protected)
        if path.endswith("/rulesets"):
            return json.dumps(self.rulesets)
        if "/rulesets/" in path:
            return json.dumps(
                {
                    "rules": [
                        {
                            "type": "required_status_checks",
                            "parameters": {
                                "required_status_checks": [
                                    {"context": c} for c in self.ruleset_contexts
                                ]
                            },
                        }
                    ]
                }
            )
        if path.endswith("/deployment-branch-policies"):
            return json.dumps({"branch_policies": self.policies})
        raise AssertionError(f"unexpected gh call: {args}")

    def written(self, path: str) -> list[tuple[str, object]]:
        return [(m, b) for m, p, b in self.writes if p == path]


def test_apply_sends_exactly_what_the_workflows_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY, extra=NAMED)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "gone-with-the-old-workflow"],
    )
    monkeypatch.setattr(protect, "_gh", github)
    done = protect.apply(tmp_path)

    [(method, body)] = github.written("repos/acme/kettle/rulesets/7")
    assert method == "PUT"
    assert isinstance(body, dict)
    rules = {rule["type"]: rule for rule in body["rules"]}
    checks = rules["required_status_checks"]["parameters"]
    # Sorted by file name, so extra.yml comes before quality.yml.
    assert checks["required_status_checks"] == [
        {"context": "protocol-package"},
        {"context": "lint"},
        {"context": "test"},
    ]
    # A branch must catch up with the base, or a green check says nothing
    # about what will be on the default branch.
    assert checks["strict_required_status_checks_policy"] is True
    assert done.dropped == ("gone-with-the-old-workflow",)
    assert done.added == ("protocol-package", "test")


def test_apply_creates_the_ruleset_a_new_repository_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pull requests only, no force-push, no deletion, the same checks."""
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub()
    monkeypatch.setattr(protect, "_gh", github)
    done = protect.apply(tmp_path)

    [(method, body)] = github.written("repos/acme/kettle/rulesets")
    assert method == "POST"
    assert done.ruleset == "created"
    assert isinstance(body, dict)
    assert body["name"] == "main"
    assert body["conditions"] == {
        "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}
    }
    rules = {rule["type"]: rule for rule in body["rules"]}
    assert set(rules) == {
        "deletion",
        "non_fast_forward",
        "pull_request",
        "required_status_checks",
    }
    # One maintainer has nobody to wait for.
    assert rules["pull_request"]["parameters"]["required_approving_review_count"] == 0
    assert rules["required_status_checks"]["parameters"]["required_status_checks"] == [
        {"context": "lint"},
        {"context": "test"},
    ]
    assert body["bypass_actors"][0]["actor_type"] == "RepositoryRole"


def test_apply_updates_a_ruleset_that_is_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        protected=["lint"], rulesets=[{"id": 7, "name": "main"}, {"id": 9, "name": "x"}]
    )
    monkeypatch.setattr(protect, "_gh", github)
    done = protect.apply(tmp_path)

    [(method, _)] = github.written("repos/acme/kettle/rulesets/7")
    assert method == "PUT"
    assert done.ruleset == "updated"
    assert github.written("repos/acme/kettle/rulesets") == []


def test_apply_takes_away_a_branch_protection_that_duplicates_the_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sources for one answer is one source too many.

    A repository carrying both lists every check twice in the merge box, and
    the two can drift until which set has to pass depends on the page you
    open.
    """
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(protected=["lint", "test"])
    monkeypatch.setattr(protect, "_gh", github)
    done = protect.apply(tmp_path)

    [(method, _)] = github.written("repos/acme/kettle/branches/main/protection")
    assert method == "DELETE"
    assert done.legacy_removed is True


def test_apply_writes_no_branch_protection_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ruleset is the only place the names are written."""
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub()
    monkeypatch.setattr(protect, "_gh", github)
    done = protect.apply(tmp_path)

    written = github.written("repos/acme/kettle/branches/main/protection")
    assert [method for method, _ in written] == []
    assert done.legacy_removed is False


def test_apply_lets_release_please_open_pull_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub()
    monkeypatch.setattr(protect, "_gh", github)
    protect.apply(tmp_path)

    [(method, args)] = github.written("repos/acme/kettle/actions/permissions/workflow")
    assert method == "PUT"
    assert isinstance(args, list)
    assert "default_workflow_permissions=write" in args
    assert "can_approve_pull_request_reviews=true" in args


def test_no_package_no_pypi_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub()
    monkeypatch.setattr(protect, "_gh", github)
    done = protect.apply(tmp_path)

    assert done.publishers == ()
    assert not any("environments" in path for _, path, _ in github.writes)


def test_a_package_gets_its_pypi_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Limited to the default branch and release tags; nothing twice."""
    _workflows(tmp_path, quality=QUALITY)
    _package(tmp_path)
    github = FakeGitHub(policies=[{"name": "main", "type": "branch"}])
    monkeypatch.setattr(protect, "_gh", github)
    monkeypatch.setattr(protect, "on_pypi", lambda name: True)
    done = protect.apply(tmp_path)

    assert [p.project for p in done.publishers] == ["kettle-protocol"]
    [(method, body)] = github.written("repos/acme/kettle/environments/pypi")
    assert method == "PUT"
    assert body == {
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        }
    }
    added = github.written(
        "repos/acme/kettle/environments/pypi/deployment-branch-policies"
    )
    assert added == [("POST", ["-f", "name=v*", "-f", "type=tag", "--silent"])]


def test_the_publisher_names_what_pypi_org_asks_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workflow by file name, which is what pypi.org matches on."""
    _workflows(tmp_path, quality=QUALITY, release=PUBLISH)
    _package(tmp_path)
    monkeypatch.setattr(protect, "_gh", FakeGitHub())
    monkeypatch.setattr(protect, "on_pypi", lambda name: False)
    [publisher] = protect.apply(tmp_path).publishers

    assert publisher == protect.Publisher(
        project="kettle-protocol",
        owner="acme",
        repository="kettle",
        workflow="release.yml",
        environment="pypi",
        on_pypi=False,
    )


def test_no_upload_step_no_workflow_name(tmp_path: Path) -> None:
    _workflows(tmp_path, quality=QUALITY, release=RELEASE)
    assert protect.publishing_workflow(tmp_path) is None


def _answer(monkeypatch: pytest.MonkeyPatch, outcome: object) -> list[str]:
    asked: list[str] = []

    def urlopen(url: str, timeout: float) -> io.BytesIO:
        asked.append(url)
        if isinstance(outcome, BaseException):
            raise outcome
        return io.BytesIO(b"{}")

    monkeypatch.setattr(protect.urllib.request, "urlopen", urlopen)
    return asked


def test_pypi_knows_the_package(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _answer(monkeypatch, None)
    assert protect.on_pypi("kettle-protocol") is True
    assert asked == ["https://pypi.org/pypi/kettle-protocol/json"]


def test_a_404_means_not_published(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(
        monkeypatch,
        urllib.error.HTTPError("u", 404, "Not Found", None, None),  # type: ignore[arg-type]
    )
    assert protect.on_pypi("kettle-protocol") is False


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.HTTPError("u", 503, "Unavailable", None, None),  # type: ignore[arg-type]
        urllib.error.URLError("no network"),
        TimeoutError(),
    ],
)
def test_pypi_that_cannot_be_asked_is_not_a_no(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    _answer(monkeypatch, failure)
    assert protect.on_pypi("kettle-protocol") is None


def test_protect_says_what_to_register_on_pypi(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(project, quality=QUALITY, release=PUBLISH)
    _package(project)
    monkeypatch.setattr(protect, "_gh", FakeGitHub())
    monkeypatch.setattr(protect, "on_pypi", lambda name: False)

    assert main(["protect", str(project)]) == 0
    out = capsys.readouterr().out
    assert "'kettle-protocol' is not on PyPI yet" in out
    assert protect.PYPI_PUBLISHING in out
    for line in (
        "PyPI Project Name  kettle-protocol",
        "Owner              acme",
        "Repository name    kettle",
        "Workflow name      release.yml",
        "Environment name   pypi",
    ):
        assert line in out


def test_protect_is_quiet_about_a_published_package(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(project, quality=QUALITY, release=PUBLISH)
    _package(project)
    monkeypatch.setattr(protect, "_gh", FakeGitHub())
    monkeypatch.setattr(protect, "on_pypi", lambda name: True)

    assert main(["protect", str(project)]) == 0
    out = capsys.readouterr().out
    assert "'kettle-protocol' is on PyPI" in out
    assert "pending publisher" not in out


def test_protect_does_not_claim_what_pypi_did_not_say(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(project, quality=QUALITY, release=PUBLISH)
    _package(project)
    monkeypatch.setattr(protect, "_gh", FakeGitHub())
    monkeypatch.setattr(protect, "on_pypi", lambda name: None)

    assert main(["protect", str(project)]) == 0
    out = capsys.readouterr().out
    assert "could not be asked about 'kettle-protocol'" in out
    assert "PyPI Project Name  kettle-protocol" in out


def test_an_unprotected_branch_is_an_outcome_not_a_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    monkeypatch.setattr(protect, "_gh", FakeGitHub())
    done = protect.apply(tmp_path)

    assert done.before is None
    assert done.dropped == ()
    assert done.contexts == ("lint", "test")


def test_protect_reports_what_it_did(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(project, quality=QUALITY)
    monkeypatch.setattr(protect, "_gh", FakeGitHub())

    assert main(["protect", str(project)]) == 0
    out = capsys.readouterr().out
    assert "unprotected until now" in out
    assert "Ruleset 'main' created" in out


def test_dry_run_prints_and_changes_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(project, quality=QUALITY)

    def refuse(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
        raise AssertionError("--dry-run must not call gh")

    monkeypatch.setattr(protect, "_gh", refuse)

    assert main(["protect", str(project), "--dry-run"]) == 0
    assert "lint" in capsys.readouterr().out


def test_a_missing_gh_is_reported_not_raised(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(project, quality=QUALITY)

    def refuse(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
        raise protect.NoGhError("the GitHub CLI ('gh') is not installed")

    monkeypatch.setattr(protect, "_gh", refuse)

    assert main(["protect", str(project)]) == 1


def test_protect_works_in_a_repository_without_an_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """This package protects itself with the same command.

    What has to be required is read out of the workflows, and a repository
    that holds no integration has those too.
    """
    from ha_integration_standards.cli import main

    _workflows(tmp_path, quality=QUALITY)
    (tmp_path / ".git").mkdir()

    assert main(["protect", "--dry-run", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "lint" in printed
    assert "test" in printed

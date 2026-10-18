"""The required checks are read out of the workflows, never written twice."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from ha_integration_standards import protect
from ha_integration_standards.checks import settings
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


# What protect writes, and what a ruleset that leaves no way past a pull
# request carries.
GUARDS = ["deletion", "non_fast_forward", "pull_request"]
PULL_REQUEST_BYPASS = {
    "actor_id": 5,
    "actor_type": "RepositoryRole",
    "bypass_mode": "pull_request",
}


class FakeGitHub:
    """Answer the gh calls protect makes, and remember every write."""

    def __init__(
        self,
        protected: list[str] | None = None,
        rulesets: list[dict[str, object]] | None = None,
        policies: list[dict[str, str]] | None = None,
        ruleset_contexts: list[str] | None = None,
        rules: list[str] | None = None,
        bypass_actors: list[dict[str, object]] | None = None,
        enforcement: str = "active",
        can_push: bool = True,
        pushed: bool = True,
    ) -> None:
        self.pushed = pushed
        self.protected = protected
        self.rulesets = rulesets or []
        self.policies = policies or []
        self.ruleset_contexts = ruleset_contexts or []
        self.rules = GUARDS if rules is None else rules
        self.bypass_actors = (
            [PULL_REQUEST_BYPASS] if bypass_actors is None else bypass_actors
        )
        self.enforcement = enforcement
        self.can_push = can_push
        self.writes: list[tuple[str, str, object]] = []

    def __call__(
        self, *args: str, stdin: str | None = None, cwd: Path | None = None
    ) -> str:
        if args[0] == "repo":
            assert "nameWithOwner" in args, f"unexpected gh call: {args}"
            return "acme/kettle\n"
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
        if path == "repos/acme/kettle":
            # The REST answer, which names the default branch even before the
            # first push has created it.
            return json.dumps(
                {
                    "default_branch": "main",
                    "permissions": {"admin": self.can_push, "push": self.can_push},
                }
            )
        if path == "repos/acme/kettle/branches/main":
            if not self.pushed:
                raise protect.NoGhError("Branch not found (HTTP 404)")
            return ""
        if path.endswith("/protection"):
            if self.protected is None:
                raise protect.NoGhError("Branch not protected (HTTP 404)")
            return json.dumps(self.protected)
        if path.endswith("/rulesets"):
            return json.dumps(self.rulesets)
        if "/rulesets/" in path:
            return json.dumps(
                {
                    "enforcement": self.enforcement,
                    "bypass_actors": self.bypass_actors,
                    "rules": [
                        *({"type": rule} for rule in self.rules),
                        {
                            "type": "required_status_checks",
                            "parameters": {
                                "required_status_checks": [
                                    {"context": c} for c in self.ruleset_contexts
                                ]
                            },
                        },
                    ],
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
    monkeypatch.setattr(settings, "_gh", github)
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
    monkeypatch.setattr(settings, "_gh", github)
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


def test_an_administrator_bypasses_for_pull_requests_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past a failing check through a pull request, never around one.

    'always' let the maintainer's own login - and with it every automation
    on their machine - push twelve commits straight onto a public main.
    """
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub()
    monkeypatch.setattr(settings, "_gh", github)
    protect.apply(tmp_path)

    [(_, body)] = github.written("repos/acme/kettle/rulesets")
    assert isinstance(body, dict)
    assert body["bypass_actors"] == [
        {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}
    ]


def test_apply_updates_a_ruleset_that_is_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        protected=["lint"], rulesets=[{"id": 7, "name": "main"}, {"id": 9, "name": "x"}]
    )
    monkeypatch.setattr(settings, "_gh", github)
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
    monkeypatch.setattr(settings, "_gh", github)
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
    monkeypatch.setattr(settings, "_gh", github)
    done = protect.apply(tmp_path)

    written = github.written("repos/acme/kettle/branches/main/protection")
    assert [method for method, _ in written] == []
    assert done.legacy_removed is False


def test_apply_lets_release_please_open_pull_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub()
    monkeypatch.setattr(settings, "_gh", github)
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
    monkeypatch.setattr(settings, "_gh", github)
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
    monkeypatch.setattr(settings, "_gh", github)
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
    monkeypatch.setattr(settings, "_gh", FakeGitHub())
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
    monkeypatch.setattr(settings, "_gh", FakeGitHub())
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
    monkeypatch.setattr(settings, "_gh", FakeGitHub())
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
    monkeypatch.setattr(settings, "_gh", FakeGitHub())
    monkeypatch.setattr(protect, "on_pypi", lambda name: None)

    assert main(["protect", str(project)]) == 0
    out = capsys.readouterr().out
    assert "could not be asked about 'kettle-protocol'" in out
    assert "PyPI Project Name  kettle-protocol" in out


def test_an_unprotected_branch_is_an_outcome_not_a_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    monkeypatch.setattr(settings, "_gh", FakeGitHub())
    done = protect.apply(tmp_path)

    assert done.before is None
    assert done.dropped == ()
    assert done.contexts == ("lint", "test")


def test_protect_reports_what_it_did(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(project, quality=QUALITY)
    monkeypatch.setattr(settings, "_gh", FakeGitHub())

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

    monkeypatch.setattr(settings, "_gh", refuse)

    assert main(["protect", str(project), "--dry-run"]) == 0
    assert "lint" in capsys.readouterr().out


def test_a_missing_gh_is_reported_not_raised(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(project, quality=QUALITY)

    def refuse(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
        raise protect.NoGhError("the GitHub CLI ('gh') is not installed")

    monkeypatch.setattr(settings, "_gh", refuse)

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


def test_audit_is_quiet_when_the_settings_are_right(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}], ruleset_contexts=["lint", "test"]
    )
    monkeypatch.setattr(settings, "_gh", github)

    assert protect.audit(tmp_path) == ()


def test_audit_reports_a_branch_that_nothing_protects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new repository is wide open and nothing complains while it is."""
    _workflows(tmp_path, quality=QUALITY)
    monkeypatch.setattr(settings, "_gh", FakeGitHub())

    [problem] = protect.audit(tmp_path)
    assert "no ruleset on main" in problem


def test_audit_reports_checks_that_drifted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A renamed job leaves a rule waiting for a name nobody reports."""
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "gone-with-the-old-workflow"],
    )
    monkeypatch.setattr(settings, "_gh", github)

    problems = " ".join(protect.audit(tmp_path) or ())
    assert "test" in problems
    assert "gone-with-the-old-workflow" in problems


def test_audit_reports_a_second_source_for_the_same_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The duplication two integrations carried unnoticed for months."""
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        protected=["lint", "test"],
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "test"],
    )
    monkeypatch.setattr(settings, "_gh", github)

    [problem] = protect.audit(tmp_path)
    assert "a branch protection requires checks a second time" in problem


def test_audit_says_nothing_when_github_cannot_be_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fork's pull request has no credentials, and no fault either."""
    _workflows(tmp_path, quality=QUALITY)

    def refuse(*args: str, **kwargs: object) -> str:
        raise protect.NoGhError("the GitHub CLI ('gh') is not installed")

    monkeypatch.setattr(settings, "_gh", refuse)

    assert protect.audit(tmp_path) is None


def test_audit_reports_a_rule_the_ruleset_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ruleset without non_fast_forward still lets main be rewritten."""
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "test"],
        rules=["deletion", "pull_request"],
    )
    monkeypatch.setattr(settings, "_gh", github)

    [problem] = protect.audit(tmp_path) or ()
    assert "lacks non_fast_forward" in problem
    assert "a force-push" in problem
    assert "ha-standards protect" in problem


def test_audit_names_every_rule_that_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "test"],
        rules=[],
    )
    monkeypatch.setattr(settings, "_gh", github)

    [problem] = protect.audit(tmp_path) or ()
    assert "pull_request, non_fast_forward, deletion" in problem
    assert "a direct push, a force-push and a deletion" in problem


def test_audit_reports_an_administrator_who_may_always_bypass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ruleset every repository here carried until the twelve commits."""
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "test"],
        bypass_actors=[
            {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
        ],
    )
    monkeypatch.setattr(settings, "_gh", github)

    [problem] = protect.audit(tmp_path) or ()
    assert "the repository admin role may bypass the ruleset on main" in problem
    assert "'always'" in problem
    assert "someone can push to main directly" in problem
    assert "ha-standards protect" in problem


def test_audit_reports_every_bypass_that_is_not_for_pull_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "test"],
        bypass_actors=[
            PULL_REQUEST_BYPASS,
            {"actor_id": 42, "actor_type": "Integration", "bypass_mode": "exempt"},
        ],
    )
    monkeypatch.setattr(settings, "_gh", github)

    [problem] = protect.audit(tmp_path) or ()
    assert "Integration 42" in problem
    assert "'exempt'" in problem


def test_audit_reports_a_ruleset_that_enforces_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "test"],
        enforcement="evaluate",
    )
    monkeypatch.setattr(settings, "_gh", github)

    [problem] = protect.audit(tmp_path) or ()
    assert "set to 'evaluate'" in problem
    assert "someone can push to main directly" in problem


def test_audit_leaves_a_repository_alone_the_caller_cannot_push_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A contributor's checkout of someone else's repository: not theirs to fix."""
    _workflows(tmp_path, quality=QUALITY)
    monkeypatch.setattr(settings, "_gh", FakeGitHub(can_push=False))

    assert protect.audit(tmp_path) is None


def test_the_default_branch_is_known_before_the_first_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty repository has no defaultBranchRef; REST names it anyway.

    protect has to run between `gh repo create` and the first push, so it
    must not depend on a branch that only that push creates.
    """
    github = FakeGitHub()
    monkeypatch.setattr(settings, "_gh", github)

    assert protect.default_branch("acme/kettle") == "main"


def test_the_settings_gate_passes_where_github_cannot_be_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No remote yet, no gh, no login: a push is not refused over that."""
    _workflows(tmp_path, quality=QUALITY)

    def refuse(*args: str, **kwargs: object) -> str:
        raise protect.NoGhError("no git remotes found")

    monkeypatch.setattr(settings, "_gh", refuse)

    assert settings.main([str(tmp_path)]) == 0
    assert "GitHub could not be asked" in capsys.readouterr().out


def test_the_settings_gate_refuses_a_push_to_a_branch_nothing_protects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    monkeypatch.setattr(settings, "_gh", FakeGitHub())

    assert settings.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "no ruleset on main" in out
    assert "ha-standards protect" in out


def test_the_settings_gate_refuses_a_push_an_administrator_could_make_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}],
        ruleset_contexts=["lint", "test"],
        bypass_actors=[
            {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
        ],
    )
    monkeypatch.setattr(settings, "_gh", github)

    assert settings.main([str(tmp_path)]) == 1
    assert "push to main directly" in capsys.readouterr().out


def test_the_settings_gate_does_not_refuse_a_push_over_a_drifted_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The branch that adds a job must be pushable before protect knows it."""
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(rulesets=[{"id": 7, "name": "main"}], ruleset_contexts=["lint"])
    monkeypatch.setattr(settings, "_gh", github)

    assert settings.main([str(tmp_path)]) == 0
    assert protect.audit(tmp_path)


def test_the_settings_gate_passes_a_branch_that_takes_pull_requests_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub(
        rulesets=[{"id": 7, "name": "main"}], ruleset_contexts=["lint", "test"]
    )
    monkeypatch.setattr(settings, "_gh", github)

    assert settings.main([str(tmp_path)]) == 0
    assert "pull requests only" in capsys.readouterr().out


def test_the_settings_gate_lets_the_push_through_that_creates_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first push into a new repository; protect follows straight after.

    Whether GitHub would let a push create a branch a ruleset already
    reserves for pull requests is not documented, so the order does not
    depend on it.
    """
    _workflows(tmp_path, quality=QUALITY)
    monkeypatch.setattr(settings, "_gh", FakeGitHub(pushed=False))

    assert settings.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "main does not exist on GitHub yet" in out
    assert "ha-standards protect" in out


def test_the_settings_gate_refuses_the_second_push_into_an_unprotected_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Once the first push has created main, protect is no longer optional."""
    _workflows(tmp_path, quality=QUALITY)
    monkeypatch.setattr(settings, "_gh", FakeGitHub(pushed=True))

    assert settings.main([str(tmp_path)]) == 1
    assert "no ruleset on main" in capsys.readouterr().out


def test_the_settings_gate_does_not_take_a_failed_answer_for_a_missing_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only a 404 means missing; anything else is not knowing."""
    _workflows(tmp_path, quality=QUALITY)
    github = FakeGitHub()

    def flaky(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
        if args[1:2] == ("repos/acme/kettle/branches/main",):
            raise protect.NoGhError("error connecting to api.github.com")
        return github(*args, stdin=stdin, cwd=cwd)

    monkeypatch.setattr(settings, "_gh", flaky)

    assert settings.main([str(tmp_path)]) == 0
    assert "GitHub could not be asked" in capsys.readouterr().out


def test_check_still_reports_a_repository_nothing_has_been_pushed_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate lets the first push through; check still says what is open."""
    _workflows(tmp_path, quality=QUALITY)
    monkeypatch.setattr(settings, "_gh", FakeGitHub(pushed=False))

    [problem] = protect.audit(tmp_path) or ()
    assert "no ruleset on main" in problem

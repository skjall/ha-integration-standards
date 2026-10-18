"""Keep the branch protection pointing at the checks that actually run.

A required status check is a *name*, not a reference to a workflow. Rename a
job, split a workflow, or adopt this package and drop the workflow the
repository started with, and the protection keeps waiting for a context
nobody reports any more. GitHub shows that as "Expected - Waiting for status
to be reported" with no job behind it, and the pull request can never be
merged: the checks that do run are green and irrelevant, because they are not
the ones named.

So the names are not written down twice. They are read out of the workflows
in the repository - every job of every workflow that runs on a pull request -
and written to the default branch's protection. Add a job, run this again,
and the protection follows.

The names live in one place: the ruleset. GitHub offers two ways to require a
check - the older branch protection and the newer rulesets - and a repository
that carries both shows every check twice in the merge box, once per source.
Worse, the two can disagree, and then the answer to "which checks must pass"
depends on which page you are looking at. The ruleset can do everything the
branch protection could, so it is the only one written here, and a branch
protection left over from before is removed.

The checks alone are not the whole protection, and a new repository has none
of it until someone remembers. So the same run also holds the rest of what
every integration of this family needs:

- a ruleset on the default branch: changes arrive through a pull request, the
  branch cannot be force-pushed or deleted, and the same checks must pass,
  with a branch made to catch up with the base first. No approval is
  required - one maintainer has nobody to wait for. Administrators may
  bypass it for pull requests only: they can merge one past a check, but
  cannot push, force-push or delete the default branch directly. A bypass
  that is always on is no protection at all against an administrator's own
  login, and that is the login every automation on the maintainer's machine
  pushes with - it once put twelve commits straight onto a public `main`;
- workflow permissions that let release-please open its release pull request;
- where lib/ builds a package, the 'pypi' environment its publishing job runs
  in, limited to the default branch and to release tags.

One step cannot be taken from here: pypi.org has to be told to trust the
publishing workflow, by the owner of the PyPI account. Until that is done the
first release publishes nothing - the tag, the changelog and the GitHub
release are all there, and the manifest pins a package nobody can install. So
the run asks PyPI whether the package exists, and when it does not, prints
exactly what to enter on pypi.org.

Every step reads what is there and writes what is wanted, so running it again
changes nothing that is already right.

Reading what is there is shared with the gates: `checks/settings.py` holds
the audit, where a vendored copy can run it with nothing installed.
"""

from __future__ import annotations

import json
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from .checks import settings

# The reading half lives with the gates, so a vendored copy can run the
# audit with nothing installed. These names stay importable
# from here for everything that used them before.
from .checks.settings import (
    WORKFLOWS,
    NoGhError,
    audit,
    contexts,
    current,
    default_branch,
    slug,
)

__all__ = [
    "PYPI_PUBLISHING",
    "WORKFLOWS",
    "NoGhError",
    "Protection",
    "Publisher",
    "apply",
    "audit",
    "contexts",
    "current",
    "default_branch",
    "on_pypi",
    "packages",
    "publishing_workflow",
    "slug",
]

PYPI_PUBLISHING = "https://pypi.org/manage/account/publishing/"
_PUBLISH_ACTION = "pypa/gh-action-pypi-publish"


@dataclass(frozen=True)
class Publisher:
    """What pypi.org needs to trust the workflow that publishes a package.

    The field names follow the form at PYPI_PUBLISHING, so they can be copied
    across one by one.
    """

    project: str
    owner: str
    repository: str
    workflow: str | None
    environment: str
    # None when PyPI could not be asked.
    on_pypi: bool | None


@dataclass(frozen=True)
class Protection:
    """What the default branch requires after the change."""

    repo: str
    branch: str
    contexts: tuple[str, ...]
    before: tuple[str, ...] | None
    ruleset: str = "created"
    # Whether a branch protection requiring the same checks was taken away.
    legacy_removed: bool = False
    publishers: tuple[Publisher, ...] = ()

    @property
    def dropped(self) -> tuple[str, ...]:
        """Contexts that were required and are no longer reported."""
        if self.before is None:
            return ()
        return tuple(c for c in self.before if c not in self.contexts)

    @property
    def added(self) -> tuple[str, ...]:
        """Contexts that are now required and were not before."""
        return tuple(c for c in self.contexts if c not in (self.before or ()))


def _drop_branch_protection(repo: str, branch: str) -> bool:
    """Remove a branch protection the ruleset has made redundant.

    Left in place it requires the same checks a second time, which GitHub
    shows as every check listed twice, and lets the two drift apart until
    nobody can say which set actually has to pass.
    """
    try:
        settings._gh(
            "api",
            "--method",
            "DELETE",
            f"repos/{repo}/branches/{branch}/protection",
            "--silent",
        )
    except NoGhError:
        # No protection to remove answers 404, which is the wanted state.
        return False
    return True


def apply(root: Path, repo: str | None = None) -> Protection:
    """Point the default branch's protection at the checks this repo reports."""
    wanted = contexts(root)
    if not wanted:
        raise NoGhError(f"no pull request checks found in {WORKFLOWS}")

    name = slug(root, repo)
    branch = default_branch(name)
    before = current(name, branch)

    ruleset = _ruleset(name, branch, wanted)
    legacy = _drop_branch_protection(name, branch)
    settings._gh(
        "api",
        "--method",
        "PUT",
        f"repos/{name}/actions/permissions/workflow",
        "-f",
        "default_workflow_permissions=write",
        # release-please opens its release pull request with the workflow
        # token; without this GitHub refuses, and no release ever happens.
        "-F",
        "can_approve_pull_request_reviews=true",
        "--silent",
    )
    publishers = _pypi_environment(root, name, branch)
    return Protection(
        repo=name,
        branch=branch,
        contexts=wanted,
        before=before,
        ruleset=ruleset,
        legacy_removed=legacy,
        publishers=publishers,
    )


def _ruleset(repo: str, branch: str, wanted: tuple[str, ...]) -> str:
    """Create or update the default branch's ruleset; say which it was.

    This is the only place the check names are written. See the module
    docstring for why the branch protection is not a second one.
    """
    body = {
        "name": branch,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [
            {
                "actor_id": settings.ADMIN_ROLE,
                "actor_type": "RepositoryRole",
                # Past a failing check through a pull request, never around
                # one: an administrator's login is also the one every
                # automation on the maintainer's machine pushes with.
                "bypass_mode": settings.PULL_REQUEST_ONLY,
            }
        ],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                    "allowed_merge_methods": ["squash", "merge"],
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [{"context": c} for c in wanted],
                },
            },
        ],
    }
    match = settings._ruleset_id(repo, branch)
    if match is None:
        path, method, outcome = f"repos/{repo}/rulesets", "POST", "created"
    else:
        path, method, outcome = f"repos/{repo}/rulesets/{match}", "PUT", "updated"
    settings._gh(
        "api",
        "--method",
        method,
        path,
        "--input",
        "-",
        "--silent",
        stdin=json.dumps(body),
    )
    return outcome


def _pypi_environment(root: Path, repo: str, branch: str) -> tuple[Publisher, ...]:
    """Give a package from lib/ the environment its publishing job runs in.

    Trusted Publishing on pypi.org names this environment, and limiting it to
    the default branch and release tags keeps a pull request from publishing.
    Returns what pypi.org needs to know about each package; nothing when
    lib/ builds none.
    """
    names = packages(root)
    if not names:
        return ()
    settings._gh(
        "api",
        "--method",
        "PUT",
        f"repos/{repo}/environments/pypi",
        "--input",
        "-",
        "--silent",
        stdin=json.dumps(
            {
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                }
            }
        ),
    )
    raw = settings._gh(
        "api", f"repos/{repo}/environments/pypi/deployment-branch-policies"
    )
    have = {
        (p.get("name"), p.get("type", "branch"))
        for p in json.loads(raw or "{}").get("branch_policies", [])
    }
    for name, kind in ((branch, "branch"), ("v*", "tag")):
        if (name, kind) not in have:
            settings._gh(
                "api",
                "--method",
                "POST",
                f"repos/{repo}/environments/pypi/deployment-branch-policies",
                "-f",
                f"name={name}",
                "-f",
                f"type={kind}",
                "--silent",
            )
    owner, _, repository = repo.partition("/")
    workflow = publishing_workflow(root)
    return tuple(
        Publisher(
            project=name,
            owner=owner,
            repository=repository,
            workflow=workflow,
            environment="pypi",
            on_pypi=on_pypi(name),
        )
        for name in names
    )


def packages(root: Path) -> tuple[str, ...]:
    """Return the distribution names lib/ builds."""
    names = []
    for path in sorted((root / "lib").glob("*/pyproject.toml")):
        with path.open("rb") as file:
            name = tomllib.load(file).get("project", {}).get("name")
        if name:
            names.append(str(name))
    return tuple(names)


def publishing_workflow(root: Path) -> str | None:
    """Return the file name of the workflow that uploads to PyPI.

    pypi.org trusts a workflow by its file name, not by its title, so this is
    the name the form asks for.
    """
    for path in sorted((root / WORKFLOWS).glob("*.y*ml")):
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(workflow, dict):
            continue
        for job in (workflow.get("jobs") or {}).values():
            for step in (job or {}).get("steps") or []:
                if str((step or {}).get("uses", "")).startswith(_PUBLISH_ACTION):
                    return path.name
    return None


def on_pypi(name: str) -> bool | None:
    """Ask PyPI whether the project exists; None when PyPI cannot be asked."""
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=10):
            return True
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return False
        return None
    except (urllib.error.URLError, TimeoutError):
        return None

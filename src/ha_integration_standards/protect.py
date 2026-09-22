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

Which checks must pass is what this package decides. Who may merge, whether a
review is needed and whether administrators are exempt are not its business,
so those settings are left exactly as the repository has them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

WORKFLOWS = Path(".github/workflows")


class NoGhError(Exception):
    """The GitHub CLI is missing, not logged in, or refused the call."""


@dataclass(frozen=True)
class Protection:
    """What the default branch requires after the change."""

    repo: str
    branch: str
    contexts: tuple[str, ...]
    before: tuple[str, ...] | None

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


def _triggers_on_pull_request(workflow: dict) -> bool:
    """Report whether the workflow runs on a pull request."""
    # An unquoted 'on:' is the YAML 1.1 boolean True, so look under both keys.
    triggers = workflow.get("on", workflow.get(True))
    if isinstance(triggers, str):
        return triggers == "pull_request"
    if isinstance(triggers, list | dict):
        return "pull_request" in triggers
    return False


def contexts(root: Path) -> tuple[str, ...]:
    """Return the check names a pull request in this repository reports.

    The context GitHub records is the job id, unless the job gives itself a
    name. A matrix job reports one context per combination, with the values
    in brackets - which is how 'test (3.13)' outlived the workflow that
    produced it. Those are left out rather than guessed at: naming one
    wrongly would be the very failure this command exists to fix.
    """
    found: list[str] = []
    for path in sorted((root / WORKFLOWS).glob("*.y*ml")):
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(workflow, dict) or not _triggers_on_pull_request(workflow):
            continue
        for job_id, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            if "matrix" in (job.get("strategy") or {}):
                continue
            found.append(str(job.get("name") or job_id))
    # dict.fromkeys keeps the first spelling of a name two workflows share.
    return tuple(dict.fromkeys(found))


def _gh(*args: str, stdin: str | None = None, cwd: Path | None = None) -> str:
    """Run the GitHub CLI; raise NoGhError when it is unusable or refuses.

    cwd matters: `gh repo view` without a slug reports whatever repository
    the working directory belongs to, which is not necessarily the one being
    protected.
    """
    if shutil.which("gh") is None:
        raise NoGhError("the GitHub CLI ('gh') is not installed")
    done = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        input=stdin,
        cwd=cwd,
    )
    if done.returncode != 0:
        raise NoGhError(done.stderr.strip() or f"gh {args[0]} failed")
    return done.stdout


def slug(root: Path, repo: str | None = None) -> str:
    """Return owner/name for the repository being worked on."""
    if repo:
        return repo
    return _gh(
        "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner", cwd=root
    ).strip()


def default_branch(repo: str) -> str:
    """Ask GitHub which branch the protection belongs on."""
    return _gh(
        "repo",
        "view",
        repo,
        "--json",
        "defaultBranchRef",
        "-q",
        ".defaultBranchRef.name",
    ).strip()


def current(repo: str, branch: str) -> tuple[str, ...] | None:
    """Return the contexts the branch requires now, or None when unprotected."""
    try:
        raw = _gh(
            "api",
            f"repos/{repo}/branches/{branch}/protection",
            "-q",
            ".required_status_checks.contexts",
        )
    except NoGhError:
        # An unprotected branch answers 404, which is an outcome, not a fault.
        return None
    text = raw.strip()
    if not text:
        return ()
    return tuple(json.loads(text))


def apply(root: Path, repo: str | None = None) -> Protection:
    """Point the default branch's protection at the checks this repo reports."""
    wanted = contexts(root)
    if not wanted:
        raise NoGhError(f"no pull request checks found in {WORKFLOWS}")

    name = slug(root, repo)
    branch = default_branch(name)
    before = current(name, branch)

    body = {
        # Every reported check, by name. 'strict' makes a branch catch up with
        # the base before it may merge, so a green check is a check against
        # what will actually be on the default branch.
        "required_status_checks": {"strict": True, "contexts": list(wanted)},
        # Left as the repository has them: not this package's decision.
        "enforce_admins": None,
        "required_pull_request_reviews": None,
        "restrictions": None,
    }
    _gh(
        "api",
        "--method",
        "PUT",
        f"repos/{name}/branches/{branch}/protection",
        "--input",
        "-",
        "--silent",
        stdin=json.dumps(body),
    )
    return Protection(repo=name, branch=branch, contexts=wanted, before=before)

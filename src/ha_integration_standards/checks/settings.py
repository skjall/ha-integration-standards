"""Refuse a push while the default branch on GitHub accepts a direct push.

A repository is created bare. Until `ha-standards protect` has run, its
default branch takes a direct push, a force-push and a deletion from anyone
with write access, and nothing says so: the merge box only appears once a
pull request is opened, and a push straight to the branch opens none. So an
automation pushing under the maintainer's own login can put a dozen commits
on the default branch of a public repository, without a single check having
run, and the first sign of it is the history.

`ha-standards check` already audited the settings, but only when somebody
ran it. This gate runs the same audit on every `git push`, from the vendored
copy, and holds the push to the part of it that matters there: a project
that was never protected - or protected loosely enough that an administrator
can still push past the ruleset - cannot push at all until `ha-standards
protect` has been run. Then the fix is one command, and the push that was
refused goes through. A check that merely drifted is left to `check`.

The audit lives here rather than in protect.py because the vendored copy has
to run it with nothing installed but PyYAML and the GitHub CLI. protect.py
imports it from here, so there is one audit, not two that drift apart.

Not knowing is not the same as being wrong. Where GitHub cannot be asked -
no remote yet, no `gh`, no login, a repository the pusher has no write
access to - the audit returns None and the gate lets the push through. A
contributor pushing to a fork must not be told to fix settings they cannot
change, and a fresh checkout without a remote has no settings to fix.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(".github/workflows")

# The rules that keep the default branch from being changed past a pull
# request, and what the branch accepts when one of them is missing.
GUARDS = {
    "pull_request": "a direct push",
    "non_fast_forward": "a force-push",
    "deletion": "a deletion",
}

# The only bypass that leaves those rules standing: an actor may merge a pull
# request past a check, but cannot push, force-push or delete the branch.
PULL_REQUEST_ONLY = "pull_request"

# GitHub's id for the repository admin role.
ADMIN_ROLE = 5


class NoGhError(Exception):
    """The GitHub CLI is missing, not logged in, or refused the call."""


def _triggers_on_pull_request(workflow: dict[Any, Any]) -> bool:
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
    wrongly would be the very failure `protect` exists to fix.
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


def repository(repo: str) -> dict[str, Any]:
    """Return what GitHub's REST API says about the repository itself."""
    answer = json.loads(_gh("api", f"repos/{repo}") or "{}")
    return answer if isinstance(answer, dict) else {}


def default_branch(repo: str) -> str:
    """Ask GitHub which branch the protection belongs on.

    The REST field, not GraphQL's defaultBranchRef: a repository that has
    just been created and not pushed to yet has no branch at all, and
    defaultBranchRef answers with an empty name there. The REST answer is the
    branch the first push will create - which is exactly when the protection
    has to be put in place, before anything reaches it.
    """
    branch = str(repository(repo).get("default_branch") or "")
    if not branch:
        raise NoGhError(f"GitHub names no default branch for {repo}")
    return branch


def _ruleset_id(repo: str, branch: str) -> int | None:
    """Return the id of the ruleset this package keeps, if it is there."""
    existing = json.loads(_gh("api", f"repos/{repo}/rulesets") or "[]")
    return next((r["id"] for r in existing if r.get("name") == branch), None)


def ruleset(repo: str, branch: str) -> dict[str, Any] | None:
    """Return the default branch's ruleset in full, or None when there is none.

    The list of rulesets carries names only; the rules and the bypass actors
    are in the detail, so that is fetched - once, for everything that wants
    to read it.
    """
    match = _ruleset_id(repo, branch)
    if match is None:
        return None
    detail = json.loads(_gh("api", f"repos/{repo}/rulesets/{match}") or "{}")
    return detail if isinstance(detail, dict) else {}


def required(detail: dict[str, Any]) -> tuple[str, ...]:
    """Return the check names a ruleset requires."""
    for rule in detail.get("rules", []):
        if rule.get("type") == "required_status_checks":
            checks = rule.get("parameters", {}).get("required_status_checks", [])
            return tuple(check["context"] for check in checks)
    return ()


def current(repo: str, branch: str) -> tuple[str, ...] | None:
    """Return the contexts the branch requires now, or None when nothing does."""
    detail = ruleset(repo, branch)
    return None if detail is None else required(detail)


def _actor(actor: dict[str, Any]) -> str:
    """Name a bypass actor the way the ruleset page does, as far as possible."""
    kind, number = actor.get("actor_type"), actor.get("actor_id")
    if kind == "RepositoryRole" and number == ADMIN_ROLE:
        return "the repository admin role"
    if kind == "OrganizationAdmin":
        return "organisation admins"
    return f"{kind} {number}" if number is not None else str(kind)


def loopholes(detail: dict[str, Any], branch: str) -> list[str]:
    """Return every way past the ruleset to the branch other than a pull request.

    A ruleset that exists can still let a direct push through: when it is
    not enforced, when one of the rules that make a pull request the only
    way in is missing, or when someone may bypass it outright. The last one
    is the quiet one - an administrator's login is the login every
    automation on a maintainer's machine uses, and 'always' lets it push to
    the branch as if there were no ruleset at all.

    The bypass actors are only part of the answer for someone with write
    access; for anyone else GitHub leaves them out. Absent is not judged.
    """
    found: list[str] = []
    enforcement = detail.get("enforcement", "active")
    if enforcement != "active":
        found.append(
            f"the ruleset on {branch} is set to '{enforcement}', so it enforces "
            f"nothing: someone can push to {branch} directly. Run "
            "'ha-standards protect'."
        )

    present = {rule.get("type") for rule in detail.get("rules", [])}
    missing = [rule for rule in GUARDS if rule not in present]
    if missing:
        accepted = [GUARDS[rule] for rule in missing]
        allowed = (
            accepted[0]
            if len(accepted) == 1
            else ", ".join(accepted[:-1]) + " and " + accepted[-1]
        )
        found.append(
            f"the ruleset on {branch} lacks {', '.join(missing)}: {branch} "
            f"accepts {allowed}. Run 'ha-standards protect'."
        )

    for actor in detail.get("bypass_actors", []):
        mode = actor.get("bypass_mode")
        if mode == PULL_REQUEST_ONLY:
            continue
        found.append(
            f"{_actor(actor)} may bypass the ruleset on {branch} "
            f"(bypass_mode '{mode}'): someone can push to {branch} directly, "
            f"force-push it and delete it, past every check. Run "
            "'ha-standards protect', which limits the bypass to pull requests."
        )
    return found


def _inspect(
    root: Path, repo: str | None
) -> tuple[str, str, dict[str, Any] | None] | None:
    """Return the repository, its default branch and that branch's ruleset.

    None when GitHub cannot be asked at all - no CLI, no credentials, no
    remote, a fork's pull request - and when the repository is one the
    caller cannot push to: its settings are not theirs to change, and a push
    from them does not reach its default branch anyway.
    """
    try:
        name = slug(root, repo)
        about = repository(name)
        if not (about.get("permissions") or {}).get("push", True):
            return None
        branch = str(about.get("default_branch") or "")
        if not branch:
            return None
        return name, branch, ruleset(name, branch)
    except NoGhError:
        return None


def _exposure(branch: str, detail: dict[str, Any] | None) -> list[str]:
    """Return every way the branch can be changed other than by a pull request."""
    if detail is None:
        return [
            f"no ruleset on {branch}: it accepts a direct push, a force-push "
            "and a deletion. Run 'ha-standards protect'."
        ]
    return loopholes(detail, branch)


def branch_exists(repo: str, branch: str) -> bool:
    """Ask GitHub whether the branch is there; raise NoGhError if it cannot say.

    Only a 404 means the branch is missing. Any other refusal - no network,
    no login - is not knowing, and is passed on as such.
    """
    try:
        _gh("api", f"repos/{repo}/branches/{branch}", "--silent")
    except NoGhError as err:
        if "404" in str(err):
            return False
        raise
    return True


@dataclass(frozen=True)
class Verdict:
    """What the push gate found: how the branch is open, if it exists yet."""

    branch: str
    problems: tuple[str, ...] = ()
    # False while the first push has not created the default branch yet.
    exists: bool = True


def direct_push(root: Path, repo: str | None = None) -> Verdict | None:
    """Return how the default branch can be pushed to past a pull request.

    The part of the audit the push gate holds a push to. A check that drifted
    or a branch protection left over makes the merge box wrong, not the
    branch open, and refusing a push over it would block the very branch
    that adds the job the ruleset does not know yet.

    A default branch that does not exist on GitHub yet has nothing on it to
    protect: that is the first push, the one that creates it, and it goes
    through. Whether GitHub itself would let a push create a branch that a
    ruleset already demands pull requests for is not documented, so the
    order of a new repository does not depend on it - the first push comes
    before `protect`, and every push after it is held to the ruleset.

    None as for audit().
    """
    if not contexts(root):
        # protect refuses a repository whose workflows report nothing, so a
        # verdict here could not be acted on.
        return Verdict(branch="")
    found = _inspect(root, repo)
    if found is None:
        return None
    name, branch, detail = found
    problems = tuple(_exposure(branch, detail))
    if not problems:
        return Verdict(branch=branch)
    try:
        if not branch_exists(name, branch):
            return Verdict(branch=branch, exists=False)
    except NoGhError:
        return None
    return Verdict(branch=branch, problems=problems)


def audit(root: Path, repo: str | None = None) -> tuple[str, ...] | None:
    """Return what is wrong with the repository's settings, if anything.

    `check` runs on every commit; `protect` runs when somebody remembers. So
    the settings drift the same way a managed file drifts, and until now
    nothing said so: an integration adopted before a rule changed kept the old
    one for as long as nobody read the merge box. Two repositories carried a
    duplicated set of checks for months that way.

    Returns None when GitHub cannot be asked at all, or the repository is one
    the caller cannot push to. Not knowing is not the same as being wrong,
    and a contributor who cannot see or change the settings must not be told
    their commit broke them.
    """
    wanted = contexts(root)
    if not wanted:
        return ()
    found = _inspect(root, repo)
    if found is None:
        return None
    name, branch, detail = found

    problems = _exposure(branch, detail)
    if detail is not None:
        have = required(detail)
        missing = sorted(set(wanted) - set(have))
        stale = sorted(set(have) - set(wanted))
        if missing:
            problems.append(f"not required, though reported: {', '.join(missing)}")
        if stale:
            problems.append(
                f"required, though nothing reports them: {', '.join(stale)}"
            )

    try:
        _gh("api", f"repos/{name}/branches/{branch}/protection", "--silent")
    except NoGhError:
        pass  # No branch protection is the wanted state.
    else:
        problems.append(
            "a branch protection requires checks a second time, next to the "
            "ruleset. GitHub lists every check twice and the two can drift "
            "apart. Run 'ha-standards protect'."
        )
    return tuple(problems)


def _repository_root(start: Path) -> Path:
    """Return the checkout the gate runs for; pre-commit starts at its root."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def main(argv: list[str] | None = None) -> int:
    """Fail when the default branch on GitHub can be pushed to directly."""
    argv = list(sys.argv[1:] if argv is None else argv)
    start = Path(argv[0]) if argv else Path.cwd()
    verdict = direct_push(_repository_root(start.resolve()))
    if verdict is None:
        print("Repository settings: not checked, GitHub could not be asked.")
        return 0
    if not verdict.exists:
        print(
            f"Repository settings: {verdict.branch} does not exist on GitHub yet, "
            "so this push creates it.\nRun 'ha-standards protect' straight "
            "after it - every later push is refused until then."
        )
        return 0
    if verdict.problems:
        print("Repository settings: the default branch takes a direct push\n")
        for problem in verdict.problems:
            print(f"  FAIL  {problem}")
        print(
            "\nNothing is pushed until this is fixed. Run 'ha-standards protect'\n"
            "(it needs admin rights on the repository), then push again."
        )
        return 1
    print("Repository settings: the default branch takes pull requests only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""ha-standards: adopt, sync, check, protect, and start a new integration."""

from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
from importlib import resources
from pathlib import Path

from . import __version__, protect, sync
from .discovery import Integration, NoIntegrationError, find_integration


def _integration(where: str | None) -> Integration:
    try:
        return find_integration(Path(where) if where else Path.cwd())
    except NoIntegrationError as err:
        print(f"  {err}", file=sys.stderr)
        raise SystemExit(1) from err


def cmd_sync(args: argparse.Namespace) -> int:
    """Write the managed files as this release ships them."""
    it = _integration(args.path)
    changed = sync.write(it)
    if changed:
        for path in changed:
            print(f"  updated  {path}")
    else:
        print("  managed files already match this release.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Fail when a managed file has drifted."""
    it = _integration(args.path)
    problems = sync.drift(it)
    if not problems:
        print(f"Managed files: in step with ha-integration-standards {__version__}.")
        return 0
    print("Managed files have drifted from ha-integration-standards\n")
    for path, reason in sorted(problems.items()):
        print(f"  FAIL  {path}: {reason}")
    print("\nRun 'ha-standards sync' to bring them back.")
    return 1


def _repository_root(where: str | None) -> Path:
    """Return the repository to protect.

    Not an integration: what is required here is read out of the workflows,
    and a repository that holds no integration has those too. This package
    protects itself with the same command.
    """
    start = Path(where) if where else Path.cwd()
    with contextlib.suppress(NoIntegrationError):
        return find_integration(start).root
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def cmd_protect(args: argparse.Namespace) -> int:
    """Require exactly the checks a pull request here reports."""
    root = _repository_root(args.path)
    found = protect.contexts(root)
    if args.dry_run:
        print(f"Checks a pull request reports in {root.name}:\n")
        for name in found:
            print(f"  {name}")
        return 0 if found else 1
    try:
        done = protect.apply(root, args.repo)
    except protect.NoGhError as err:
        print(f"  {err}", file=sys.stderr)
        return 1
    print(f"{done.repo}: {done.branch} now requires\n")
    for name in done.contexts:
        print(f"  {name}{'  (new)' if name in done.added else ''}")
    if done.dropped:
        print("\nNo longer required, because nothing reports them:\n")
        for name in done.dropped:
            print(f"  {name}")
    if done.before is None:
        print("\nThe branch was unprotected until now.")
    print(f"\nRuleset '{done.branch}' {done.ruleset}: pull requests only,")
    print("  no force-push, no deletion, the same checks.")
    if done.legacy_removed:
        print("Branch protection removed: it required the same checks a second")
        print("  time, which GitHub lists twice and lets drift apart.")
    print("Workflows may open pull requests (release-please needs that).")
    if done.publishers:
        print(f"Environment 'pypi' limited to {done.branch} and tags v*.")
    for publisher in done.publishers:
        _report_publisher(publisher)
    return 0


def _report_publisher(publisher: protect.Publisher) -> None:
    """Say whether pypi.org still has to be told to trust the workflow."""
    if publisher.on_pypi:
        print(f"Package '{publisher.project}' is on PyPI.")
        return
    if publisher.on_pypi is None:
        print(f"\nPyPI could not be asked about '{publisher.project}'.")
        print("If it is not published yet, the step below is still open.")
    else:
        print(f"\nPackage '{publisher.project}' is not on PyPI yet.")
    print("Every release publishes nothing until the owner of the PyPI account")
    print(f"adds a pending publisher at {protect.PYPI_PUBLISHING}")
    print("(GitHub tab):\n")
    print(f"  PyPI Project Name  {publisher.project}")
    print(f"  Owner              {publisher.owner}")
    print(f"  Repository name    {publisher.repository}")
    print(
        f"  Workflow name      {publisher.workflow or '(no workflow uploads to PyPI)'}"
    )
    print(f"  Environment name   {publisher.environment}")
    print("\nA release that already failed to publish: re-run its workflow")
    print("afterwards. Nothing here can do this step.")


def cmd_adopt(args: argparse.Namespace) -> int:
    """Wire an existing integration up to this package."""
    it = _integration(args.path)
    print(f"Adopting {it.domain} in {it.root}\n")
    for label, result in (
        (".pre-commit-config.yaml", sync.ensure_precommit(it)),
        ("pyproject.toml", sync.ensure_settings(it)),
        ("CLAUDE.md", sync.ensure_claude_import(it)),
    ):
        print(f"  {label}: {result or 'already in place'}")
    for path in sync.write(it):
        print(f"  updated  {path}")
    print(
        "\nNothing else was touched. Run the gates once to see where the "
        "integration stands:\n"
        "  ha-quality-scale && ha-tests && ha-coverage"
    )
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    """Copy the scaffold into a new directory and fill in the names."""
    target = Path(args.path).resolve()
    if target.exists() and any(target.iterdir()):
        print(f"  {target} is not empty", file=sys.stderr)
        return 1

    values = {
        "domain": args.domain,
        "name": args.name or args.domain.replace("_", " ").title(),
        "owner": args.owner,
        "repo": args.repo or f"home-assistant-{args.domain.replace('_', '-')}",
        "class": "".join(part.title() for part in args.domain.split("_")),
        "manufacturer": args.manufacturer or "",
        "lib_package": args.lib or f"{args.domain.replace('_', '-')}-protocol",
        "lib_module": (args.lib or f"{args.domain}_protocol").replace("-", "_"),
    }

    scaffold = resources.files(__package__) / "scaffold"
    with resources.as_file(scaffold) as source:
        shutil.copytree(source, target, dirs_exist_ok=True)

    def fill(text: str) -> str:
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        return text

    # Contents first, then the paths, so a renamed directory is not walked twice.
    for path in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_file():
            # Binary files carry no placeholders.
            with contextlib.suppress(UnicodeDecodeError):
                text = path.read_text(encoding="utf-8")
                path.write_text(fill(text), encoding="utf-8")
        filled = fill(path.name)
        if filled != path.name:
            path.rename(path.with_name(filled))

    it = Integration(root=target, path=target / "custom_components" / args.domain)
    sync.write(it)
    sync.ensure_precommit(it)
    sync.ensure_claude_import(it)
    print(f"Created {target}\n")
    print("Next:")
    print("  git init && git add -A")
    print("  python3 -m venv .venv && .venv/bin/pip install pre-commit")
    print("  .venv/bin/pre-commit install")
    print("Once the repository exists on GitHub and main is pushed:")
    print("  ha-standards protect      # not optional: nothing else protects main")
    print("With a package under lib/, protect also prints what to register on")
    print("pypi.org before the first release - only the account owner can.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch a subcommand."""
    parser = argparse.ArgumentParser(
        prog="ha-standards",
        description=(
            "Shared quality gates for custom Home Assistant integrations. "
            "The rules live here; the integration keeps its own code."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    adopt = sub.add_parser("adopt", help="wire an existing integration up")
    adopt.add_argument("path", nargs="?", help="project directory (default: here)")
    adopt.set_defaults(func=cmd_adopt)

    do_sync = sub.add_parser("sync", help="rewrite the managed files")
    do_sync.add_argument("path", nargs="?")
    do_sync.set_defaults(func=cmd_sync)

    check = sub.add_parser("check", help="fail when a managed file has drifted")
    check.add_argument("path", nargs="?")
    check.set_defaults(func=cmd_check)

    guard = sub.add_parser(
        "protect", help="require exactly the checks this repository reports"
    )
    guard.add_argument("path", nargs="?")
    guard.add_argument("--repo", help="owner/name (default: the checkout's remote)")
    guard.add_argument(
        "--dry-run", action="store_true", help="print the checks, change nothing"
    )
    guard.set_defaults(func=cmd_protect)

    new = sub.add_parser("new", help="start a new integration from the scaffold")
    new.add_argument("path", help="directory to create")
    new.add_argument("--domain", required=True, help="e.g. acme_kettle")
    new.add_argument("--owner", required=True, help="GitHub user or organisation")
    new.add_argument("--name", help='e.g. "Acme Kettle"')
    new.add_argument("--repo", help="repository name")
    new.add_argument("--manufacturer", help="shown on the device page")
    new.add_argument("--lib", help="name of the protocol package, if any")
    new.set_defaults(func=cmd_new)

    args = parser.parse_args(argv)
    return int(args.func(args))


def main_check(argv: list[str] | None = None) -> int:
    """Entry point for the ha-sync hook: check, never write."""
    return main(["check", *(argv or [])])


if __name__ == "__main__":
    raise SystemExit(main())

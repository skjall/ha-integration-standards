# ha-integration-standards

Shared quality gates for custom Home Assistant integrations.

An integration's quality tier is easy to claim and easy to lose: a rename, a
new platform, one `icon="mdi:…"` too many, and `quality_scale.yaml` says
something the code no longer does. These gates check the claim on every commit
— and because they are written by one tool rather than copied into each
repository, improving a check once improves it everywhere.

The checks know nothing about any particular integration. They find it in the
repository they run against, read what it declares in `manifest.json`,
`quality_scale.yaml`, `strings.json` and `icons.json`, and hold it to that.

## Why the gates are vendored

This package is private; the integrations it checks are public and build on
GitHub. A hook that cloned this repository, or a CI step that installed it
from a private index, would need a token — and **a public repository hands no
secrets to a pull request from a fork**, so every outside contribution would
go red through no fault of its own. It would also make a green build depend on
a server that is not reachable from GitHub at all.

So `ha-standards sync` writes the checks *into* the project, under
`scripts/_ha_standards/`, together with the release they came from and a
SHA-256 of each file. CI then needs nothing but the checkout it already has,
and a fork's pull request runs exactly the same gates. Editing a vendored
check to make a commit pass fails `run.py verify`, which runs before the gates
do.

## Use it in an existing integration

```bash
pip install -e ~/Code/ha-integration-standards   # or from your own index
ha-standards adopt
```

`adopt` writes the gates, adds the hooks to `.pre-commit-config.yaml`, leaves
a commented `[tool.ha_standards]` block in `pyproject.toml`, makes `CLAUDE.md`
import the standards document, and writes the managed CI workflow. It touches
nothing else — your integration's code, tests, README and `quality_scale.yaml`
stay yours.

## Take a newer version

```bash
git -C ~/Code/ha-integration-standards pull
ha-standards sync
git diff      # the rules that changed, before they are in force
git commit -am "chore: take ha-integration-standards 0.2.0"
```

Updating is deliberate: you see the diff of the rules before they gate your
next commit. `ha-standards check` reports a managed file that has drifted.

## Start a new integration

```bash
ha-standards new ~/Code/home-assistant-acme-kettle \
  --domain acme_kettle --owner yourname --name "Acme Kettle"
```

A scaffold that already holds the tier: typed config entry, coordinator, base
entity, a platform, diagnostics, translations, tests, CI, release automation.

## The gates

All of them run through one entry point in the project, so the same command
works in a hook, in CI and by hand:

```bash
python3 scripts/_ha_standards/run.py --help
```

| Gate | What it holds |
|---|---|
| `verify` | the vendored copy is the one that was synced |
| `quality-scale` | the code still does what `quality_scale.yaml` claims |
| `coverage` | the per-module coverage floors the claimed tier requires |
| `commit-message` | Conventional Commits, written in English |
| `types` | `mypy --strict`, against the targeted Home Assistant |
| `tests` | the suite, in Docker, on the interpreter the release needs |

`ha-standards sync` also writes `.github/workflows/quality.yml`, which runs
the same gates in CI using nothing but the checkout.

A green check only stops a merge if the branch protection asks for it by
name, and a required check *is* a name — drop the workflow that reported it
and the protection waits for ever on a job that no longer exists. So the
names are not kept in two places:

```bash
ha-standards protect           # --dry-run prints them, changes nothing
```

It reads every job of every workflow that runs on a pull request and requires
exactly those on the default branch. Run it after `adopt`, and again whenever
a job is added or renamed.

## Configuration

Everything has a default that works. A project writes a key down only when it
genuinely differs:

```toml
[tool.ha_standards]
overall_coverage = 95
# Rules this project cannot prove mechanically, with a reason in the commit.
unenforceable = ["discovery"]
# Keys the base entity derives itself rather than passing as a keyword.
derived_translation_keys = ["binary_sensor:valve_open"]

[tool.ha_standards.coverage]
"config_flow.py" = 100
"coordinator.py" = 95
```

## What the gates actually check

Bronze through Platinum, as far as a machine can: `runtime-data` (typed entry,
no `hass.data[DOMAIN]`), `common-modules`, `config-flow`,
`test-before-configure`, `test-before-setup`, `config-entry-unloading`,
`has-entity-name`, `entity-unique-id`, `parallel-updates`,
`entity-unavailable`, `action-exceptions`, `reauthentication-flow`,
`reconfiguration-flow`, `entity-translations` (including every shipped
language), `icon-translations` (including a hardcoded `mdi:` icon),
`exception-translations`, `devices`, `diagnostics`, `discovery`,
`entity-disabled-by-default`, `strict-typing`, `dependency-transparency`
(including a pin that has drifted from the package in `lib/`), `brands`,
`integration-owner`, and every `docs-*` rule against the README.

Rules whose verdict needs a human are named in `NOT_CHECKABLE` and reported as
claimed-but-unproven rather than silently passing.

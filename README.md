# ha-integration-standards

Shared quality gates for custom Home Assistant integrations.

An integration's quality tier is easy to claim and easy to lose: a rename, a
new platform, one `icon="mdi:…"` too many, and `quality_scale.yaml` says
something the code no longer does. These gates check the claim on every commit
— and because they live in a package rather than in each repository, raising
one version number tightens the rules everywhere at once.

The checks know nothing about any particular integration. They find it in the
repository they run against, read what it declares in `manifest.json`,
`quality_scale.yaml`, `strings.json` and `icons.json`, and hold it to that.

## Use it in an existing integration

```bash
pip install ha-integration-standards
ha-standards adopt
```

`adopt` adds the hooks to `.pre-commit-config.yaml`, leaves a commented
`[tool.ha_standards]` block in `pyproject.toml`, makes `CLAUDE.md` import the
standards document, and writes the managed files. It touches nothing else —
your integration's code, tests, README and `quality_scale.yaml` stay yours.

## Take a newer version

```bash
pre-commit autoupdate --repo https://github.com/skjall/ha-integration-standards
ha-standards sync
```

The `rev` in `.pre-commit-config.yaml` is the version of the rules this
project runs. Renovate keeps it moving on its own when `"pre-commit": {
"enabled": true }` is set. `sync` rewrites the managed files; `ha-standards
check` (the `ha-sync` hook) fails when one of them has drifted.

## Start a new integration

```bash
ha-standards new ~/Code/home-assistant-acme-kettle \
  --domain acme_kettle --owner yourname --name "Acme Kettle"
```

A scaffold that already holds the tier: typed config entry, coordinator, base
entity, a platform, diagnostics, translations, tests, CI, release automation.

## The hooks

| Hook | What it holds |
|---|---|
| `ha-quality-scale` | the code still does what `quality_scale.yaml` claims |
| `ha-coverage` | the per-module coverage floors the claimed tier requires |
| `ha-commit-message` | Conventional Commits, written in English |
| `ha-types` | `mypy --strict`, against the targeted Home Assistant |
| `ha-tests` | the suite, in Docker, on the interpreter the release needs |
| `ha-sync` | the managed files are the ones this release ships |

In CI, the same gates come from a reusable workflow:

```yaml
jobs:
  standards:
    uses: skjall/ha-integration-standards/.github/workflows/ha-integration.yml@v0
```

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

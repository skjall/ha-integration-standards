# Contributing

## Before you commit

Install the hooks once:

```bash
python3 -m venv .venv && .venv/bin/pip install pre-commit
.venv/bin/pre-commit install
```

From then on every commit runs ruff, `mypy --strict`, the full test suite and
the gates from
[ha-integration-standards](https://github.com/{{owner}}/ha-integration-standards):
the quality tier `custom_components/{{domain}}/quality_scale.yaml` claims has
to survive its check, and the coverage floors that tier requires have to hold.

The rules live in that package, not here. If one is wrong, fix it there and
raise the `rev` in `.pre-commit-config.yaml`.

## Tests

```bash
ha-tests             # everything
ha-tests -k flow     # one slice
ha-types             # types only
```

Both run in Docker, against the exact Home Assistant version the integration
targets. Local Python is usually too old: Home Assistant needs 3.14.2 from
2026.3 onwards, and testing against an older release means testing an API that
is not the one users have.

The source is mounted read-only and the container runs as your own user, so a
test run cannot leave anything behind in the working tree. Everything a run
produces lands in `.artefakte/`.

## Changing the device protocol

`lib/{{lib_module}}/` is the only place that knows the wire format, and
[docs/protocol.md](docs/protocol.md) is the record of how each byte offset was
established. If you change one, change the other, and say what you verified it
against — a real device, or the vendor app.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) — release-please
derives the version and the changelog from them.

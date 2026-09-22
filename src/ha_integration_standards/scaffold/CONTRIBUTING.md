# Contributing

## Before you commit

Install the hooks once:

```bash
python3 -m venv .venv && .venv/bin/pip install pre-commit
.venv/bin/pre-commit install
```

From then on every commit runs ruff, `mypy --strict`, the full test suite and
the gates under `scripts/_ha_standards/`: the quality tier that
`custom_components/{{domain}}/quality_scale.yaml` claims has to survive its
check, and the coverage floors that tier requires have to hold.

Those gates are written by `ha-integration-standards` and are not maintained
here — `run.py verify` hashes them and runs first, so "make the check pass"
cannot mean "change the check". If a rule is wrong, fix it there and run
`ha-standards sync`.

## Tests

```bash
python3 scripts/_ha_standards/run.py tests           # everything
python3 scripts/_ha_standards/run.py tests -k flow   # one slice
python3 scripts/_ha_standards/run.py types           # types only
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

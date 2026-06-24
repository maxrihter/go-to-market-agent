# Contributing

Thanks for considering a contribution. Issues and pull requests are welcome.

## Getting started

```bash
make install     # uv sync --extra dev
make demo        # confirm the pipeline runs end to end (no keys)
make test        # run the suite
```

## Before opening a pull request

```bash
make fmt         # auto-format and autofix
make lint        # ruff check and mypy must pass
make test        # the suite must pass
```

The test suite is mocked and runs offline, so it needs no API keys. CI runs the same checks
plus `gtm demo` as a no-keys smoke test; please make sure all of them pass locally first.

## Conventions

- Python 3.11+, full type hints, `async def` for all I/O.
- Pydantic v2 models in `models/`; one LangGraph node per file in `engine/nodes/`.
- No brand, region, or vertical hardcoded in source. Tunables live in `config/*.yaml`,
  secrets in `.env` only. Never commit real keys or client data.
- Prefer extending through the plugin seams over editing the core
  ([docs/EXTENDING.md](docs/EXTENDING.md)).
- Documentation voice is plain and professional: no emoji headers, no marketing language.

## Adding an extension

New sources, analysts, synthesizers, gates, outputs, or providers should register through the
plugin system rather than modifying the graph directly. See
[docs/EXTENDING.md](docs/EXTENDING.md) for the protocols and a worked example.

## Reporting issues

Include what you ran, what you expected, and what happened. For pipeline issues, the output of
`gtm demo` is a useful starting point because it reproduces the full run without any keys.

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).

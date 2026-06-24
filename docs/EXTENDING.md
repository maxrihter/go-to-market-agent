# Extending

The engine is built to be extended without forking the core. Every extension point is a small
protocol (`src/gtm_agent/plugins/protocols.py`) plus a registry
(`src/gtm_agent/plugins/registry.py`). You register an extension one of two ways: a decorator
for in-tree code, or an entry point for a separately installed package.

## Extension points

| Kind | Protocol method | Adds |
|---|---|---|
| `source` | `async fetch(query) -> mapping` | A data connector (a new signal family) |
| `analyst` | `async analyze(ctx) -> section` | A new report section |
| `synthesizer` | `async synthesize(ctx) -> section` | A new cross-section interpretation |
| `gate` | `check(report) -> GateResult` | A pre-publish quality gate |
| `output` | `async emit(render_model) -> EmitResult` | A new output format |
| `provider` | `build(config) -> chat model` | A custom LLM provider for the router |

Each protocol is intentionally small and uses loose payload types, so a plugin depends on the
contract, not on the engine's internal models.

## Registering in-tree (decorator)

Add a module under `extensions/` and decorate the class. It self-registers on import.

```python
from collections.abc import Mapping
from typing import Any

from gtm_agent.plugins import source


@source("reddit")
class RedditSource:
    name = "reddit"

    async def fetch(self, query: Mapping[str, Any]) -> Mapping[str, Any]:
        # Return {slug: {"reddit_mentions_30d": int, "reddit_sentiment": float}}.
        # query carries the watchlist entries and the period window.
        # Fail soft: return {} on any error so the report still renders.
        ...
```

The decorators are `source`, `analyst`, `synthesizer`, `gate`, `output`, and `provider`, all
imported from `gtm_agent.plugins`. The registry warns and replaces if a name is already taken.

## Registering from a separate package (entry points)

A third-party pip package advertises its extension under the matching `gtm_agent.<kind>s`
group, and the registry discovers it automatically once installed:

```toml
# in your package's pyproject.toml
[project.entry-points."gtm_agent.sources"]
reddit = "my_pkg.reddit:RedditSource"
```

`gtm plugins list` loads the bundled examples plus any installed entry points and prints
everything registered. A plugin that fails to import is logged and skipped, never fatal.

## Fail-soft contract

Extensions run inside a fail-soft pipeline. A source that errors should return an empty
mapping; an analyst that cannot produce a section should return `None`. The run continues with
whatever the rest of the pipeline produced, rather than aborting. Keep this contract: it is
what lets the engine degrade gracefully when a key is missing or an upstream API is down.

## Bundled examples and stubs

Worked examples (the contract is shown; the body is left for you to finish):

- `extensions/sources/reddit.py` (Source)
- `extensions/analysts/pricing_intel.py` (Analyst)
- `extensions/outputs/slack.py` (OutputAdapter)

Further stubs to copy: sources `g2_reviews` and `news`; outputs `pdf` and `webhook`.

## Corrections as an extension seam

Human-in-the-loop corrections (`corrections.yaml`, see [CONFIGURATION.md](CONFIGURATION.md))
apply a value to a dotted attribute path in the report. Dotted paths are supported today;
list- or slug-addressed paths (for example, correcting one competitor in a list) are a
deliberate seam for you to extend in `engine/nodes/overrides.py`.

## Optional built-in functionality

- Evaluation harness (`gtm eval`): scores a report on grounding, completeness, traceability,
  and clarity. Built in; install the `eval` extra for the DeepEval-backed metrics.
- Corrections (`corrections.yaml`): hand-override weak or stale fields. Built in.
- Server (`pip install ".[server]"`): an HTTP trigger to run the pipeline as a service.
- Cost estimation, budget guards, and watchlist threshold alerting are documented seams left
  open for integrators.

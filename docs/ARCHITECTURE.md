# Architecture

The engine is one LangGraph state graph. A run flows through a fixed sequence of nodes; each
node reads and writes a shared typed state, and dependencies (the LLM router, the store, the
settings) are bound at build time, so nodes hold no globals.

```
brief -> research -> enrich -> [6 analysts] -> [3 synthesizers]
      -> compute_mom -> enrich_prior -> assemble -> apply_overrides
      -> pre_publish_gate --(fail)--> END
                          --(pass)--> qa_reviewer --(reject)--> END
                                                  --(publish)--> render -> store_report -> END
```

A rejected report stops at `END` and is never rendered or stored. Only a report that clears
both the deterministic gate and the LLM reviewer reaches `output/` and the history store.

## The nodes

| Node | Role |
|---|---|
| `write_brief` | Build the research brief and per-section briefs from the tenant config (deterministic) |
| `research` | A supervisor/researcher subgraph that runs agentic web research per section via Tavily |
| `enrich` | Fetch competitor data from up to nine sources into a flat per-competitor record |
| analysts (6) | Each writes one facts-only section from the research notes and the enriched data |
| synthesizers (3) | Interpret the sections into a KPI scoreboard, an executive summary, and ICE-scored recommendations |
| `compute_mom` | Compute month-over-month deltas against the previous run's stored metrics |
| `enrich_prior` | Fold prior-period values into the report for trend context |
| `assemble` | Combine every section into one validated `MarketReport` |
| `apply_overrides` | Apply human-in-the-loop corrections, re-validating the result |
| `pre_publish_gate` | Run the deterministic gates plus cross-reference validation; set `qa_status` |
| `qa_reviewer` | An LLM reviewer that can reject the report before it publishes |
| `render` | Emit Markdown and JSON to `output/` |
| `store_report` | Persist the report and its metrics for the next period's deltas |

The six analysts run as a fan-out and rejoin at a barrier before the synthesizers; the three
synthesizers do the same. The barriers are no-op nodes whose only job is to synchronize the
fan-in.

## The LLM router

All model access goes through `llm/router.py`, which is provider-agnostic. Six roles
(`research`, `analyst`, `synthesizer`, `fact_check`, `qa_reviewer`, `polish`) each map to a
primary provider and an optional fallback ([CONFIGURATION.md](CONFIGURATION.md)).

Every resilient call follows the same chain: try the primary; on an empty or malformed
response, try the fallback; then retry once with a corrective hint; then return `None` so the
calling node can degrade rather than crash. Built-in providers are Anthropic, any
OpenAI-compatible endpoint (OpenAI, a local Ollama, imago.market), Mistral, and Google; more
can be added as `LLMProvider` plugins.

## Enrichment

`enrich` orchestrates up to nine sources: Instagram, Meta Ad Library, SimilarWeb, Wayback,
Google Trends, YouTube, App Store, Ahrefs, and DataForSEO. Each source returns a slug-keyed
mapping, which is merged into one flat record per competitor. That flat record is the contract
the analysts and the month-over-month computation read from, so adding a source means adding
keys, not reshaping the pipeline. Every source fails soft: a missing key or a down API yields
an empty result and the report is built from what is available.

## The gate model

Trust is enforced in two stages, both before anything is written.

1. Deterministic gates (`pre_publish_gate`), each pass/fail with explicit issues:
   - completeness and a content floor (a stubbed or empty report cannot pass)
   - section coverage
   - tautology and evidence-chain checks
   - freshness (stale market-sizing years are rejected)
   - a forbidden-entity check driven by the tenant's `forbidden_keywords`
   - cross-reference validation between sections
2. An LLM reviewer (`qa_reviewer`) that reads the assembled report and can reject it.

If the deterministic stage fails, the run routes straight to `END`. If the reviewer rejects,
the run routes to `END`. Either way the report is not rendered and not stored, so a low-quality
report never enters the history that future deltas depend on.

Data integrity is enforced upstream of the gates too: fabricated source URLs are dropped at
the model layer, and overrides are re-validated through the Pydantic schema before they are
accepted.

## State and storage

The shared state is a typed `MarketReportState`. Persistence defaults to local SQLite (run
history, metric history, applied corrections, and the LangGraph checkpointer); the `postgres`
extra swaps in Postgres for shared or concurrent deployments. The metric history is what makes
month-over-month deltas possible: each published run stores its figures, and the next run's
`compute_mom` reads them back.

## Dependency injection

`build_report_graph` binds each node's dependencies with `functools.partial` at build time, so
the compiled graph carries no module globals. This keeps nodes individually testable and lets
the demo inject a fake router and an offline flag without touching the node code.

## Determinism and the demo

The demo (`engine/demo.py`) runs the full graph with a deterministic fake router, canned
fixtures, and an offline guard that prevents any network call. It exercises every node and
every gate, which is why it doubles as the CI smoke test: if the wiring breaks, `gtm demo`
fails without needing a single API key.

# Setup

How to install the engine, run the no-keys demo, and configure a live run. For what each
config field means see [CONFIGURATION.md](CONFIGURATION.md); for the system design see
[ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements

- Python 3.11 or newer
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Install

```bash
git clone https://github.com/maxrihter/go-to-market-agent && cd go-to-market-agent
make install            # uv sync --extra dev
```

Or with pip:

```bash
pip install -e ".[dev]"
```

Optional providers and adapters are extras, installed only if you need them:

| Extra | Adds |
|---|---|
| `mistral` | Mistral as an LLM provider |
| `google` | Google Gemini as an LLM provider |
| `telegram` | Dependencies for a Telegram delivery adapter (extension seam) |
| `server` | FastAPI dependencies for an HTTP-trigger seam |
| `postgres` | Postgres storage and checkpointing |
| `eval` | DeepEval-backed metrics for `gtm eval` |

The Ahrefs and DataForSEO sources are plain HTTP and need only an API key, no extra install.
A Notion output adapter is scaffolded as an extension seam (see [EXTENDING.md](EXTENDING.md)).

## Run the demo (no keys)

```bash
make demo               # or: gtm demo
```

This runs the entire pipeline on bundled fixtures with no API keys and no network, and writes
a report to `output/`. Use it to confirm the install and to see the output format before
configuring a live run.

## Configure a live run

A live run reads two things: a tenant config and a set of API keys.

```bash
gtm init                # writes config/tenant.yaml from the bundled example
cp .env.example .env    # then fill in the keys you need
$EDITOR config/tenant.yaml
```

Edit `config/tenant.yaml` for your brand, niche, and competitor watchlist
([CONFIGURATION.md](CONFIGURATION.md)), then run:

```bash
gtm run --month 2026-05     # or: make run
```

The report is written to `output/<report_id>.md` and `output/<report_id>.json`, and the run is
recorded in local storage for month-over-month deltas on the next run.

## API keys

Keys are read from `.env` only; nothing sensitive is committed. The minimum for a live run is
one LLM key plus a Tavily key. Everything else widens coverage.

| Variable | Powers | Needed |
|---|---|---|
| `ANTHROPIC_API_KEY` | Default LLM for all six roles | One LLM key required |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | OpenAI-compatible LLM (OpenAI, Ollama, imago.market) | Alternative to Anthropic |
| `TAVILY_API_KEY` | Web research | Required for a live run |
| `APIFY_TOKEN` | Instagram, Ad Library, SimilarWeb enrichment | Recommended |
| `AHREFS_API_KEY` | Ahrefs SEO source | Optional |
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | DataForSEO source | Optional |
| `NOTION_TOKEN` / `NOTION_PARENT_PAGE_ID` | Notion output adapter (extension seam) | Optional |
| `DATABASE_URL` | Postgres storage (defaults to local SQLite) | Optional |

The LLM routing in `tenant.yaml` decides which provider keys are actually read; only set keys
for providers your `llm:` block uses. Missing enrichment keys degrade gracefully: that source
is skipped and the report is built from what is available.

## Storage

State defaults to a local SQLite database at `./data/state.db` (run history, metric history,
applied corrections, and the LangGraph checkpointer). For a shared or concurrent deployment,
install the `postgres` extra and set `DATABASE_URL`.

## Scheduling

The engine is a CLI, so any scheduler works. A monthly GitHub Actions run, with keys stored as
repository secrets:

```yaml
# .github/workflows/report.yml
on:
  schedule:
    - cron: "0 6 1 * *"   # 06:00 UTC on the 1st of each month
  workflow_dispatch:
jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run gtm run
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}
          APIFY_TOKEN: ${{ secrets.APIFY_TOKEN }}
```

## Server (optional seam)

```bash
pip install -e ".[server]"
```

The `server` extra installs the FastAPI dependencies for running the pipeline as a service
instead of a one-shot CLI. The HTTP trigger itself is an extension seam left to implement; see
`src/gtm_agent/server.py`.

## Troubleshooting

- `Config not found` from `gtm run`: run `gtm init` first, or pass `--config`.
- A report did not reach `output/`: it was rejected by a quality gate. The reason is logged;
  see the gate model in [ARCHITECTURE.md](ARCHITECTURE.md).
- A live run is missing a section's data: the enrichment key for that source is absent. Check
  the table above; the run continues without it.

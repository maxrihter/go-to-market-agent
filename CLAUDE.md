# go-to-market-agent — Project Rules

A generalized, open-source market-intelligence engine. Extracted and generalized from a
private production system. No client data, names, regions, or secrets ever belong in this repo.

## Conventions
- Python 3.11+, full type hints, `async def` for all I/O.
- Pydantic v2 models in `models/`; one LangGraph node per file in `engine/nodes/`.
- Prompts live in `src/gtm_agent/prompts/*.txt` — concrete, in English, with `# ADD: your …`
  bullets marking what an integrator customizes. Never hardcode brand / region / vertical.
- All tunables (brand, watchlist, niche, events, safety, LLM routing) live in `config/*.yaml`,
  never in source.
- Secrets only via env (`.env`, see `.env.example`); never commit real values.
- LLM access goes through `llm/router.py` (provider-agnostic) — no vendor hardcoding.
- Extensions register through `plugins/registry.py` (Source / Analyst / Synthesizer / Gate /
  OutputAdapter / LLMProvider). Bundled examples live in `extensions/`.

## Layout
- `src/gtm_agent/` — engine, nodes, integrations, models, llm router, storage, plugins, cli
- `src/gtm_agent/engine/research/` — Tavily research subgraph (supervisor + researcher)
- `src/gtm_agent/engine/eval/` — LLM-judge report-quality harness (`gtm eval`)
- `src/gtm_agent/integrations/output/` — RenderModel IR + markdown / html / notion emitters
- `src/gtm_agent/prompts/` — system prompts (`.txt`, shipped in the wheel)
- `src/gtm_agent/templates/` — bundled example tenant (a fictional brand) + corrections example
- `src/gtm_agent/extensions/` — example plugins to copy and finish
- `src/gtm_agent/engine/demo.py` — hermetic, no-keys demo runner
- `config/` — where `gtm init` scaffolds your tenant config
- `docs/` — SETUP · CONFIGURATION · EXTENDING · ARCHITECTURE
- `tests/` — mocked unit tests (no API keys needed)

## Voice (docs + README)
Serious and professional. No emoji section headers, no em-dashes, no marketing hype.
Conventional section names. Public signature is "Max Romanov".

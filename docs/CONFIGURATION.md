# Configuration

A tenant is described entirely by one YAML file. `gtm init` writes a starter copy from the
bundled example (a fictional dog-food brand, Barkwell); edit it for your own brand. No code
changes are needed to retarget the engine to a new brand, niche, or region.

Secrets never go here. API keys live in `.env` only (see [SETUP.md](SETUP.md)).

## Top-level fields

| Field | Type | Required | Purpose |
|---|---|---|---|
| `brand` | object | yes | The brand the report is written for |
| `niche` | string | yes | The market category the report covers |
| `watchlist` | list | yes | Competitors to track each period |
| `forbidden_keywords` | list of strings | no | Anti-hallucination guard for the QA gate |
| `safety_blocklist` | list of strings | no | Content the research gate redacts |
| `llm` | object | no | Per-role provider routing (sensible default if omitted) |

## `brand`

```yaml
brand:
  name: Barkwell
  region: US
  report_language: en
  description: >
    Fresh, vet-formulated dog food and supplements sold direct to consumers in the US.
```

| Field | Default | Notes |
|---|---|---|
| `name` | required | Used throughout the report and prompts |
| `region` | `null` | Free text (`US`, `EU`, `DACH`, global if omitted) |
| `report_language` | `en` | ISO code; the report is written in this language |
| `description` | `""` | One or two sentences; grounds the analysts |

## `niche`

The market category the report is about, for example `fresh dog food`. It scopes research
queries and the competitive framing.

## `watchlist`

The competitors enriched and compared each period. Public identifiers only.

```yaml
watchlist:
  - slug: thefarmersdog
    name: The Farmer's Dog
    ig_handle: thefarmersdog
    website_domain: thefarmersdog.com
    ios_app_id: "1234567890"
    youtube_handle: thefarmersdog
```

| Field | Required | Powers |
|---|---|---|
| `slug` | yes | Stable internal key; ties a competitor to its data and its history |
| `name` | yes | Display name in the report |
| `ig_handle` | no | Instagram follower and engagement enrichment |
| `website_domain` | no | SimilarWeb, Wayback, and SEO enrichment |
| `ios_app_id` | no | App Store rating and review enrichment |
| `youtube_handle` | no | YouTube channel enrichment |

Each handle is optional. A competitor with only a `slug` and `name` still appears in the
report; it just carries less enrichment. Missing handles never fail the run.

## `forbidden_keywords`

Category descriptors the report must never attribute to a brand in your niche. The QA
forbidden-entity gate rejects a report that, for example, calls a pet-nutrition brand a
`B2B SaaS platform`. List the things your brand and competitors are definitely not, to catch
LLM entity confusion.

```yaml
forbidden_keywords:
  - B2B SaaS platform
  - cryptocurrency exchange
```

## `safety_blocklist`

Strings the research safety gate redacts from fetched content before it reaches the model.
Empty by default.

## `llm`

Routing for the six pipeline roles: `research`, `analyst`, `synthesizer`, `fact_check`,
`qa_reviewer`, `polish`. Omit the block entirely to use one `ANTHROPIC_API_KEY` across all
roles, with an OpenAI-compatible fallback added automatically for the analyst and synthesizer
roles when `OPENAI_API_KEY` is set.

To mix providers, specify all six roles. Each role takes a `primary` and an optional
`fallback`; if the primary returns nothing usable, the router tries the fallback, then a
retry with a corrective hint.

```yaml
llm:
  research:    {primary: {provider: anthropic, model: claude-sonnet-4-6}}
  analyst:
    primary:  {provider: anthropic, model: claude-sonnet-4-6}
    fallback: {provider: openai, model: gpt-4o-mini, base_url_env: OPENAI_BASE_URL}
  synthesizer: {primary: {provider: anthropic, model: claude-sonnet-4-6}}
  fact_check:  {primary: {provider: anthropic, model: claude-sonnet-4-6}}
  qa_reviewer: {primary: {provider: anthropic, model: claude-sonnet-4-6}}
  polish:      {primary: {provider: anthropic, model: claude-haiku-4-5-20251001}}
```

Per-provider fields:

| Field | Default | Notes |
|---|---|---|
| `provider` | required | `anthropic`, `openai`, `mistral`, `google`, or a plugin name |
| `model` | required | Provider's model id |
| `api_key_env` | provider default | Env var holding the key; defaults to the provider's standard var |
| `base_url_env` | `OPENAI_BASE_URL` | OpenAI-compatible endpoints only (OpenAI, Ollama, imago.market) |
| `max_tokens` | `8192` | Per-call cap |
| `timeout` | `120` | Seconds |
| `max_retries` | `3` | Transient-error retries before the fallback |

The built-in providers are `anthropic`, `openai` (any OpenAI-compatible endpoint), `mistral`,
and `google`. To add another, register an `LLMProvider` plugin and name it here
([EXTENDING.md](EXTENDING.md)).

## Corrections (optional)

Generated reports can be hand-corrected without editing code, via a separate
`corrections.yaml` (see `corrections.example.yaml`). Each entry is a dotted path into the
report and the value to set; a correction is applied only where the generated value is empty
or weak, and is marked applied so it is not reused indefinitely.

```yaml
overrides:
  - path: brand_positioning.sentiment_summary
    value: "Sentiment improved across review platforms this period."
    reason: "The model left it blank; verified from the review aggregator."
```

## Prompts

The analyst and synthesizer prompts live in `src/gtm_agent/prompts/*.txt` and ship with the
package. Each carries `# ADD: your ...` markers showing where to inject brand- or
niche-specific guidance. Editing prompts is optional; the defaults are written to work for any
brand described by the config above.

.DEFAULT_GOAL := help
.PHONY: help install demo run eval test lint fmt clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

install:  ## Install with dev extras (uv)
	uv sync --extra dev

demo:  ## Run the full pipeline on bundled fixtures — no API keys, no network
	uv run gtm demo

run:  ## Run the pipeline with your config (live — needs API keys)
	uv run gtm run --config config/tenant.yaml

eval:  ## Score the latest report with the LLM-judge harness
	uv run gtm eval

test:  ## Run the test suite
	uv run pytest -q

lint:  ## Lint + type-check
	uv run ruff check src tests
	uv run mypy src

fmt:  ## Auto-format
	uv run ruff format src tests
	uv run ruff check --fix src tests

clean:  ## Remove caches and generated output
	rm -rf .pytest_cache .ruff_cache .mypy_cache output demo_output data/state.db

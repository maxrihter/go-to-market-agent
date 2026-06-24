"""Command-line interface for go-to-market-agent."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from . import __version__

app = typer.Typer(
    add_completion=False,
    help="A multi-agent market-intelligence engine.",
)
console = Console()


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"go-to-market-agent {__version__}")


@app.command()
def init(
    directory: Annotated[
        Path, typer.Option("--dir", "-d", help="Where to write the starter config.")
    ] = Path("config"),
) -> None:
    """Scaffold a starter tenant config from the bundled example."""
    from .templates import example_tenant_yaml

    target = directory / "tenant.yaml"
    if target.exists():
        console.print(f"[yellow]{target} already exists[/yellow]; not overwriting.")
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target.write_text(example_tenant_yaml(), encoding="utf-8")
    except OSError as exc:
        console.print(f"[red]Could not write {target}:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]Wrote[/green] {target}. Edit it for your brand, then `gtm run`.")


@app.command()
def run(
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Path to your tenant config.")
    ] = Path("config/tenant.yaml"),
    month: Annotated[
        str | None,
        typer.Option("--month", "-m", help="Report month, YYYY-MM. Defaults to last month."),
    ] = None,
) -> None:
    """Run the report pipeline for a configured tenant (live; needs API keys)."""
    try:
        asyncio.run(_run(config, month))
    except FileNotFoundError as exc:
        console.print(f"[red]Config not found:[/red] {config}. Run `gtm init` or pass --config.")
        raise typer.Exit(1) from exc
    except (RuntimeError, NotImplementedError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


async def _run(config: Path, month: str | None) -> None:
    from .config import load_settings
    from .engine.pipeline import run_pipeline
    from .log import configure_logging

    configure_logging()
    settings = load_settings(config)
    console.print(
        f"[bold]Running[/bold] {settings.brand.name} ({settings.brand.region or 'global'})…"
    )
    report = await run_pipeline(settings, month=month)
    if report is None:
        console.print("[yellow]No report produced; the run aborted upstream.[/yellow]")
        return
    console.print(f"[green]Done.[/green] report → output/{report.report_id}.md")


@app.command()
def demo() -> None:
    """Run the full pipeline on bundled fixtures (no API keys, no network)."""
    from .engine.demo import run_demo
    from .log import configure_logging

    configure_logging()
    console.print("[bold]Running demo[/bold] on bundled fixtures (no API keys)…")
    report = asyncio.run(run_demo())
    if report is None:
        console.print("[red]Demo produced no report.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Demo done.[/green] report → output/{report.report_id}.md")


@app.command()
def eval(  # noqa: A001 (the user-facing command name is intentionally `eval`)
    report: Annotated[
        Path | None,
        typer.Option("--report", "-r", help="Report JSON to score. Defaults to latest."),
    ] = None,
) -> None:
    """Score a report's quality with the LLM-judge harness (needs an LLM key)."""
    from .engine.eval.harness import run_eval
    from .log import configure_logging

    configure_logging()
    try:
        result = asyncio.run(run_eval(report))
    except (FileNotFoundError, RuntimeError, NotImplementedError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(result)


plugins_app = typer.Typer(help="Inspect registered extension plugins.")
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
def plugins_list() -> None:
    """List every registered Source / Analyst / Synthesizer / Gate / Output / Provider."""
    from .plugins.registry import format_registry, load_entrypoint_plugins

    load_entrypoint_plugins()
    console.print(format_registry())


if __name__ == "__main__":
    app()

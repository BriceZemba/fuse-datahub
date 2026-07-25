"""Fuse CLI.

    fuse check   --repo demo/dbt-shop --diff demo/scenarios/01-drop-column.patch
    fuse replay  examples/01-drop-column
    fuse doctor
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from fuse import __version__
from fuse.config import settings
from fuse.datahub.mcp_client import DataHubMCP
from fuse.graph import build_graph
from fuse.llm.provider import get_llm, llm_available
from fuse.runtime import RT
from fuse.state import FuseState

app = typer.Typer(add_completion=False, help="The blast-radius agent for DataHub.")
console = Console()

SEVERITY_STYLE = {"BREAKING": "bold red", "RISKY": "bold yellow", "SAFE": "green"}


async def _run(state: FuseState, *, replay: bool, dry_run: bool, auto_approve: bool) -> FuseState:
    async with DataHubMCP(replay=replay, dry_run=dry_run) as dh:
        RT.dh = dh
        RT.llm = get_llm()
        RT.dry_run = dry_run
        graph = build_graph(interrupt_before_writeback=not auto_approve)
        config = {"configurable": {"thread_id": state["run_id"]}}

        result = await graph.ainvoke(state, config=config)

        # interrupt_before=["writeback"] pauses here on anything non-trivial.
        snapshot = await graph.aget_state(config)
        if snapshot.next and "writeback" in snapshot.next:
            severity = result.get("max_severity", "SAFE")
            console.print(_impact_table(result))
            approved = typer.confirm(
                f"\nSeverity {severity}. Write findings back to DataHub and generate the PR?",
                default=True,
            )
            if not approved:
                console.print("[yellow]Stopped before write-back. Nothing was changed.[/]")
                return result
            result = await graph.ainvoke(None, config=config)
        return result


def _impact_table(state: FuseState) -> Table:
    table = Table(title="Blast radius", header_style="bold")
    for column in ("Asset", "Type", "Hops", "Severity", "Score", "Evidence"):
        table.add_column(column, overflow="fold")
    for impact in state.get("impacts", []):
        table.add_row(
            impact.name,
            impact.entity_type,
            str(impact.hops),
            f"[{SEVERITY_STYLE[impact.severity]}]{impact.severity}[/]",
            str(impact.score),
            "; ".join(impact.evidence) or "—",
        )
    return table


@app.command()
def check(
    repo: Path = typer.Option(Path("."), "--repo", help="Path to the data repo"),
    diff: str = typer.Option("HEAD", "--diff", help="Patch file, git rev, or --staged"),
    dialect: str = typer.Option(settings.dialect, "--dialect"),
    hops: int = typer.Option(settings.hops, "--hops"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="No prompt; for CI"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Read DataHub, never write to it"),
    fail_on: str = typer.Option(settings.fail_on, "--fail-on", help="SAFE|RISKY|BREAKING"),
) -> None:
    """Analyse a change, generate the remediation, and record it in DataHub."""
    run_id = f"fuse-{uuid.uuid4().hex[:8]}"
    state: FuseState = {
        "repo_path": str(repo),
        "diff": diff,
        "dialect": dialect,
        "hops": hops,
        "run_id": run_id,
        "auto_approve": auto_approve,
        "trace": [],
    }
    result = asyncio.run(_run(state, replay=False, dry_run=dry_run, auto_approve=auto_approve))
    _report(result)

    severity = result.get("max_severity", "SAFE")
    order = {"SAFE": 0, "RISKY": 1, "BREAKING": 2}
    if order[severity] >= order.get(fail_on.upper(), 2):
        raise typer.Exit(code=1)


@app.command()
def replay(
    example: Path = typer.Argument(..., help="Example directory, e.g. examples/01-drop-column"),
) -> None:
    """Re-run a recorded scenario offline. No Docker, no DataHub, no API key."""
    settings.fixtures_dir = example / "fixtures"
    state: FuseState = {
        "repo_path": str(example / "repo"),
        "diff": str(example / "diff.patch"),
        "dialect": settings.dialect,
        "hops": settings.hops,
        "run_id": f"replay-{example.name}",
        "replay": True,
        "trace": [],
    }
    result = asyncio.run(_run(state, replay=True, dry_run=True, auto_approve=True))
    _report(result)


@app.command()
def doctor() -> None:
    """Check that everything Fuse needs is reachable before you rely on it."""
    console.print(f"[bold]Fuse {__version__}[/]")
    console.print(f"GMS URL        : {settings.gms_url}")
    console.print(f"Token          : {'set' if settings.gms_token else '[red]missing[/]'}")
    console.print(f"Mutations      : {settings.mutations_enabled}")
    console.print(
        f"LLM provider   : {settings.llm_provider} "
        f"({'available' if llm_available() else 'not configured — template fallback'})"
    )

    async def probe() -> None:
        async with DataHubMCP() as dh:
            console.print(f"MCP tools      : {len(dh.available)} loaded")
            missing = {"search", "get_lineage", "list_schema_fields"} - set(dh.available)
            if missing:
                console.print(f"[red]Missing read tools: {', '.join(sorted(missing))}[/]")
            if "add_tags" not in dh.available:
                console.print(
                    "[yellow]Mutation tools absent — set TOOLS_IS_MUTATION_ENABLED=true[/]"
                )

    try:
        asyncio.run(probe())
    except Exception as exc:
        console.print(f"[red]MCP connection failed: {exc}[/]")
        raise typer.Exit(code=1) from exc


@app.command()
def version() -> None:
    console.print(__version__)


def _report(state: FuseState) -> None:
    console.print(_impact_table(state))
    artifacts = state.get("artifacts", [])
    if artifacts:
        console.print("\n[bold]Generated[/]")
        for artifact in artifacts:
            flag = " [yellow](needs human review)[/]" if artifact.needs_human else ""
            console.print(f"  {artifact.path}  [dim]{artifact.kind}[/]{flag}")
    writeback = state.get("writeback")
    if writeback:
        console.print(
            f"\n[bold]DataHub[/]: tagged {len(writeback.tagged)}, "
            f"properties {len(writeback.properties_set)}, "
            f"document {'saved' if writeback.document_urn else 'not saved'}"
        )
    console.print(f"\n[bold]Severity[/]: {state.get('max_severity', 'SAFE')}")


if __name__ == "__main__":
    app()

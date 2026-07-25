"""Fuse CLI.

    fuse check   --repo demo/dbt-shop --diff demo/scenarios/01-drop-column.patch
    fuse replay  examples/01-drop-column
    fuse doctor
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from fuse import __version__
from fuse.config import settings
from fuse.datahub.mcp_client import DataHubMCP, GMSUnreachable, probe_gms
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
    try:
        result = asyncio.run(_run(state, replay=False, dry_run=dry_run, auto_approve=auto_approve))
    except GMSUnreachable as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=2) from exc
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
        reachable, detail = await probe_gms()
        console.print(f"GMS reachable  : {'yes' if reachable else f'[red]no ({detail})[/]'}")
        if not reachable:
            console.print(
                "\n[yellow]DataHub is not running.[/] Start it with:\n"
                "  ./scripts/bootstrap-datahub.sh\n"
                "Then re-run `fuse doctor`. GMS is :8080; :9002 is the UI."
            )
            raise typer.Exit(code=1)

        async with DataHubMCP() as dh:
            console.print(f"MCP tools      : {len(dh.available)} loaded")
            missing = {"search", "get_lineage", "list_schema_fields"} - set(dh.available)
            if missing:
                console.print(f"[red]Missing read tools: {', '.join(sorted(missing))}[/]")
            if "add_tags" not in dh.available:
                console.print(
                    "[yellow]Mutation tools absent — set TOOLS_IS_MUTATION_ENABLED=true[/]"
                )
            else:
                console.print("Write-back     : available")

    try:
        asyncio.run(probe())
    except typer.Exit:
        raise
    except GMSUnreachable as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        console.print(f"[red]MCP connection failed: {exc.__class__.__name__}: {exc}[/]")
        raise typer.Exit(code=1) from exc


@app.command()
def spike(
    query: str = typer.Option("orders", "--query", help="Search term to probe the catalog with"),
    out: Path = typer.Option(Path("docs/spike-raw"), "--out"),
) -> None:
    """Dump the real MCP tool signatures and response shapes.

    Every parser in `resolve.py` and `lineage.py` is written defensively because the
    exact response shapes were unknown at design time. This command replaces the
    guesses with recorded fact, and the responses land in fixtures/ at the same time.
    """
    out.mkdir(parents=True, exist_ok=True)

    async def run() -> None:
        async with DataHubMCP() as dh:
            signatures = {}
            for name in dh.available:
                tool = dh._tools[name]
                signatures[name] = {
                    "description": (getattr(tool, "description", "") or "")[:400],
                    "args": getattr(tool, "args", None),
                }
            (out / "00-tool-signatures.json").write_text(
                json.dumps(signatures, indent=2, default=str), encoding="utf-8"
            )
            console.print(f"[bold]{len(signatures)} tools[/] -> {out / '00-tool-signatures.json'}")
            for name in sorted(signatures):
                args = signatures[name]["args"]
                params = ", ".join(args) if isinstance(args, dict) else "?"
                console.print(f"  {name}({params})")

            probes: list[tuple[str, str, dict]] = [("search", "search", {"query": query})]
            recorded: dict[str, object] = {}

            for label, tool_name, args in probes:
                payload = await _try(dh, tool_name, args)
                recorded[label] = payload
                (out / f"01-{label}.json").write_text(
                    json.dumps(payload, indent=2, default=str)[:200_000], encoding="utf-8"
                )

            raw = json.dumps(recorded.get("search"), default=str)
            console.print(f"\n[bold]raw search response[/] ({len(raw)} chars):")
            console.print(raw[:1500] or "(empty)")

            urn = _first_urn(recorded.get("search"))
            console.print(f"\nfirst URN from search: [bold]{urn or 'NONE FOUND'}[/]")
            if not urn:
                console.print(
                    "[yellow]No URN parsed. Either the catalog is empty (re-run "
                    "`datahub datapack load showcase-ecommerce`) or the response is text "
                    "rather than JSON — the raw dump above tells us which.[/]"
                )
                return

            follow_ups = [
                ("list_schema_fields", {"urn": urn}),
                ("get_entities", {"urns": [urn]}),
                ("get_lineage", {"urn": urn, "upstream": False, "max_hops": 2}),
                ("get_dataset_queries", {"urn": urn}),
            ]
            for index, (tool_name, args) in enumerate(follow_ups, start=2):
                payload = await _try(dh, tool_name, args)
                (out / f"{index:02d}-{tool_name}.json").write_text(
                    json.dumps(payload, indent=2, default=str)[:200_000], encoding="utf-8"
                )
                head = json.dumps(payload, default=str)[:220]
                console.print(f"\n[bold]{tool_name}[/] -> {head}...")

        console.print(
            f"\n[green]Done.[/] Commit {out} and fixtures/, then push:\n"
            '  git add docs/spike-raw fixtures && git commit -m "chore: record MCP shapes" && '
            "git push"
        )

    try:
        asyncio.run(run())
    except GMSUnreachable as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=2) from exc


async def _try(dh: DataHubMCP, tool: str, args: dict) -> object:
    """Call a tool, capturing the error instead of aborting the whole spike."""
    try:
        return await dh.call(tool, **args)
    except Exception as exc:
        console.print(f"[yellow]{tool} failed: {exc.__class__.__name__}: {exc}[/]")
        return {"__error__": f"{exc.__class__.__name__}: {exc}", "__args__": args}


URN_PATTERN = re.compile(r"urn:li:[a-zA-Z]+:\([^)]*\)|urn:li:[a-zA-Z]+:[\w.\-]+")


def _first_urn(payload: object) -> str | None:
    """Find the first urn anywhere in a response, whatever its shape.

    MCP tools may answer with structured JSON or with a text blob, so this searches
    strings for a URN rather than only accepting one that starts with the prefix.
    """
    if isinstance(payload, str):
        match = URN_PATTERN.search(payload)
        return match.group(0) if match else None
    if isinstance(payload, dict):
        if isinstance(payload.get("urn"), str):
            return payload["urn"]
        for value in payload.values():
            found = _first_urn(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _first_urn(item)
            if found:
                return found
    return None


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

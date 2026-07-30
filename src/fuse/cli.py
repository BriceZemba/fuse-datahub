"""Fuse CLI.

    fuse check   --repo demo/dbt-shop --diff demo/scenarios/01-drop-column.patch
    fuse replay  examples/01-drop-column
    fuse doctor
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from fuse import __version__
from fuse.config import settings
from fuse.datahub import ml_graph, shapes
from fuse.datahub.mcp_client import DataHubMCP, GMSUnreachable, probe_gms
from fuse.graph import build_graph
from fuse.llm.provider import OPENROUTER_BASE_URL, get_llm, llm_available
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
def freeze(
    scenario: Path = typer.Argument(..., help="Patch under demo/scenarios/"),
    name: str = typer.Option("", "--name", help="Folder name under examples/"),
    repo: Path = typer.Option(Path("demo/dbt-shop"), "--repo"),
    dry_run: bool = typer.Option(True, "--dry-run/--write"),
) -> None:
    """Run a scenario and freeze the whole thing into examples/ for judging.

    Captures the input diff, a copy of the repo, every recorded DataHub response, the
    generated artifacts and the trace — so `fuse replay` reproduces it with no DataHub,
    no Docker and no API key.
    """
    folder = Path("examples") / (name or scenario.stem)
    fixtures = folder / "fixtures"
    if folder.exists():
        shutil.rmtree(folder)
    fixtures.mkdir(parents=True)

    shutil.copytree(repo, folder / "repo")
    shutil.copy(scenario, folder / "diff.patch")

    settings.fixtures_dir = fixtures
    settings.out_dir = folder / "generated"

    state: FuseState = {
        "repo_path": str(folder / "repo"),
        "diff": str(folder / "diff.patch"),
        "dialect": settings.dialect,
        "hops": settings.hops,
        "run_id": folder.name,
        "trace": [],
    }
    result = asyncio.run(_run(state, replay=False, dry_run=dry_run, auto_approve=True))
    _report(result)

    # The reports belong at the top of the folder; only the code Fuse wrote stays
    # under generated/, so a judge sees the verdict before the diff of files.
    generated = folder / "generated" / folder.name
    for produced in ("PR_BODY.md", "impact-report.md", "run.log"):
        source = generated / produced
        if source.exists():
            shutil.move(str(source), folder / produced)

    if generated.exists():
        for item in generated.iterdir():
            shutil.move(str(item), folder / "generated" / item.name)
        generated.rmdir()

    (folder / "README.md").write_text(
        _example_readme(folder.name, result), encoding="utf-8"
    )
    console.print(f"\n[green]Frozen to {folder}[/] — verify with: fuse replay {folder}")


def _example_readme(name: str, state: FuseState) -> str:
    impacts = state.get("impacts", [])
    actionable = [i for i in impacts if i.severity != "SAFE"]
    lines = [
        f"# {name}",
        "",
        f"**Change:** {impacts[0].source_change if impacts else 'n/a'}  ",
        f"**Verdict:** {state.get('max_severity', 'SAFE')} — "
        f"{len(actionable)} of {len(impacts)} downstream assets need attention",
        "",
        "```bash",
        f"fuse replay examples/{name}",
        "```",
        "",
        "| Asset | Type | Hops | Severity | Score | Evidence |",
        "|---|---|---|---|---|---|",
    ]
    for impact in actionable:
        lines.append(
            f"| `{impact.name}` | {impact.entity_type} | {impact.hops} | "
            f"**{impact.severity}** | {impact.score} | "
            f"{'; '.join(impact.evidence) or '—'} |"
        )
    lines += [
        "",
        "## Files",
        "",
        "| Path | What it is |",
        "|---|---|",
        "| `diff.patch` | the input |",
        "| `repo/` | the data repo at the moment of the change |",
        "| `fixtures/` | every DataHub response, recorded |",
        "| `impact-report.md` | the analysis, every score explained |",
        "| `PR_BODY.md` | what the reviewer sees |",
        "| `generated/` | the artifacts Fuse produced |",
        "| `run.log` | node-by-node trace |",
        "",
        "Nothing here is hand-written; it is the output of the command above.",
        "",
    ]
    return "\n".join(lines)


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
    urn: str = typer.Option("", "--urn", help="Probe this URN directly instead of searching"),
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

            if urn:
                # Direct probe: what does DataHub consider downstream of this exact
                # entity, and does that include ML entities?
                payload = await _try(dh, "get_lineage", {"urn": urn, "upstream": False,
                                                         "max_hops": 3})
                (out / "10-get_lineage-direct.json").write_text(
                    json.dumps(payload, indent=2, default=str)[:400_000], encoding="utf-8"
                )
                pairs = shapes.lineage_results(payload)
                console.print(f"[bold]{len(pairs)} downstream of[/] {urn}")
                for entity, degree in pairs:
                    console.print(
                        f"  {degree}  {shapes.entity_type(entity):<20} "
                        f"{shapes.entity_name(entity)}"
                    )
                ml = [e for e, _ in pairs if shapes.entity_type(e).startswith("ml")]
                console.print(
                    f"\n[bold]{'ML entities in lineage' if ml else 'NO ML entities in lineage'}[/]"
                )

                # get_lineage does not traverse MLFeature.sources, so check the ML
                # aspects directly — this is the path Fuse actually uses.
                via_graphql, gql_error = await ml_graph._urns_via_graphql()
                console.print(f"\nML URNs via GraphQL by type: [bold]{len(via_graphql)}[/]")
                if gql_error:
                    console.print(f"  [red]{gql_error}[/]")
                for candidate in via_graphql[:20]:
                    console.print(f"  {candidate}")

                probe = await _try(dh, "get_entities", {"urns": [
                    "urn:li:mlModel:(urn:li:dataPlatform:mlflow,customer_churn_model,PROD)",
                    "urn:li:mlFeature:(customer_churn,credit_limit)",
                ]})
                console.print(
                    "\nDirect get_entities on the seeded URNs:\n  "
                    + json.dumps(probe, default=str)[:600]
                )

                entities, _ = await ml_graph.ml_entities(dh)
                (out / "11-ml-entities.json").write_text(
                    json.dumps(entities, indent=2, default=str)[:400_000], encoding="utf-8"
                )
                console.print(f"\n[bold]{len(entities)} ML entit(ies) in the catalog[/]")
                for entity in entities:
                    sources = shapes.ml_feature_sources(entity)
                    features = shapes.ml_features_of(entity)
                    detail = ""
                    if sources:
                        detail = f"  sources={len(sources)}"
                    elif features:
                        detail = f"  features={len(features)}"
                    console.print(f"  {entity.get('urn')}{detail}")

                dependents = ml_graph.dependents_of(urn, entities)
                console.print(
                    f"\n[bold]{len(dependents)} ML entit(ies) derived from this dataset[/]"
                )
                for entity, degree in dependents:
                    console.print(f"  {degree}  {entity.get('urn')}")
                return

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

            found_urn = _first_urn(recorded.get("search"))
            console.print(f"\nfirst URN from search: [bold]{found_urn or 'NONE FOUND'}[/]")
            if not found_urn:
                console.print(
                    "[yellow]No URN parsed. Either the catalog is empty (re-run "
                    "`datahub datapack load showcase-ecommerce`) or the response is text "
                    "rather than JSON — the raw dump above tells us which.[/]"
                )
                return

            follow_ups = [
                ("list_schema_fields", {"urn": found_urn}),
                ("get_entities", {"urns": [found_urn]}),
                ("get_lineage", {"urn": found_urn, "upstream": False, "max_hops": 2}),
                ("get_dataset_queries", {"urn": found_urn}),
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
def schema(
    query: str = typer.Argument(..., help="Table name to look up"),
    limit: int = typer.Option(3, "--limit", help="How many matching datasets to show"),
) -> None:
    """Print the real columns of the datasets a name resolves to.

    Useful when writing demo models or migrations: generated code must reference
    columns DataHub actually knows about, and this is the fastest way to check.
    """

    async def run() -> None:
        async with DataHubMCP() as dh:
            payload = await dh.call("search", query=query, num_results=20)
            datasets = [
                e
                for e in shapes.search_results(payload)
                if str(e.get("urn", "")).startswith("urn:li:dataset:")
            ]
            if not datasets:
                console.print(f"[yellow]No dataset matched {query!r}[/]")
                return
            for entity in datasets[:limit]:
                urn = entity["urn"]
                fields = shapes.field_names(await dh.call("list_schema_fields", urn=urn))
                console.print(
                    f"\n[bold]{shapes.entity_name(entity)}[/] "
                    f"[dim]({shapes.platform_of(entity)})[/]\n{urn}"
                )
                console.print("  " + ", ".join(fields) if fields else "  (no schema)")

    try:
        asyncio.run(run())
    except GMSUnreachable as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=2) from exc


@app.command()
def models(
    free_only: bool = typer.Option(True, "--free/--all"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """List OpenRouter models, cheapest first.

    The free tier's `:free` ids come and go — models are delisted with no notice — so
    rather than trusting a hardcoded default, ask what is actually available today and
    set FUSE_LLM_MODEL from the result.
    """
    import httpx

    try:
        response = httpx.get(f"{OPENROUTER_BASE_URL}/models", timeout=30)
        response.raise_for_status()
    except Exception as exc:
        console.print(f"[red]Could not reach OpenRouter: {exc}[/]")
        raise typer.Exit(code=1) from exc

    rows = []
    for model in response.json().get("data", []):
        model_id = str(model.get("id", ""))
        pricing = model.get("pricing") or {}
        try:
            prompt_cost = float(pricing.get("prompt", "0") or 0)
            completion_cost = float(pricing.get("completion", "0") or 0)
        except (TypeError, ValueError):
            continue

        # Routers such as openrouter/auto advertise zero price because they bill via
        # whichever model they select. Only the `:free` suffix actually guarantees a
        # free request, so listing anything else under "free" would invite a surprise
        # charge.
        if free_only and not model_id.endswith(":free"):
            continue
        if free_only and (prompt_cost > 0 or completion_cost > 0):
            continue
        rows.append((prompt_cost + completion_cost, model_id,
                     model.get("context_length") or 0))

    rows.sort(key=lambda row: (row[0], row[1]))
    table = Table(title="OpenRouter models" + (" (free)" if free_only else ""))
    table.add_column("Model")
    table.add_column("Context", justify="right")
    for _, model_id, context in rows[:limit]:
        table.add_row(model_id, f"{context:,}")
    console.print(table)
    console.print(
        "\nPick one for code generation and set it:\n"
        "  FUSE_LLM_PROVIDER=openrouter\n"
        "  FUSE_LLM_MODEL=<id>\n"
        "  OPENROUTER_API_KEY=<key from https://openrouter.ai/keys>"
    )


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

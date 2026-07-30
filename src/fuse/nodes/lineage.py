"""Node 3 — walk downstream lineage and collect the evidence the risk engine needs.

Deliberately does not stop at datasets. Charts, dashboards, data jobs, feature
tables, models, model groups and deployments are all downstream consumers, and the
ML ones are the consumers that break silently.

`get_lineage` takes `column`, so the traversal is column-scoped when a column
changed: DataHub returns what depends on that field rather than everything
downstream of the table.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fuse.datahub import ml_graph, shapes
from fuse.runtime import RT
from fuse.state import FuseState

ML_TYPES = {"mlFeature", "mlFeatureTable", "mlModel", "mlModelGroup", "mlModelDeployment"}

# Every MCP call is a round trip of a second or more, so the probes are bounded by what
# can actually change a verdict rather than by what is merely interesting.
#
# A schema hit scores 35, and hop decay is 3 per hop beyond the first. At 3 hops that is
# 29 — below the RISKY threshold of 30 — so probing further can add an evidence line but
# never a severity. Two hops keeps every result that matters and drops most of the work.
SCHEMA_PROBE_HOPS = int(os.getenv("FUSE_SCHEMA_PROBE_HOPS", "2"))
SCHEMA_PROBE_LIMIT = 40
CONCURRENT_PROBES = 12

# Catalogs without query history answer every one of these with total:0. Sample a few;
# if none of them carry SQL, stop asking and say so in the trace.
QUERY_PROBE_SAMPLE = 5


def _is_error(payload: Any) -> bool:
    return isinstance(payload, dict) and ("__error__" in payload or "error" in payload)


def _dedupe(values: list[str]) -> list[str]:
    """DataHub returns an owner once per ownership type; the report wants people."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


async def trace_lineage(state: FuseState) -> dict:
    dh = RT.require_dh()
    hops = state.get("hops", 3)
    trace = list(state.get("trace", []))
    graph: dict[str, dict] = {}

    for asset in state.get("resolved", []):
        args: dict[str, Any] = {"urn": asset.urn, "upstream": False, "max_hops": hops}
        column_scoped = bool(asset.change.column)
        if column_scoped:
            args["column"] = asset.change.column

        payload = await dh.call("get_lineage", **args)
        pairs = shapes.lineage_results(payload)

        # A column-scoped query that finds nothing may mean the instance has no
        # column-level lineage, not that nothing depends on the column.
        if column_scoped and (not pairs or _is_error(payload)):
            trace.append(
                f"lineage: no column-level edges for {asset.change.column}, "
                "falling back to table-level"
            )
            args.pop("column")
            payload = await dh.call("get_lineage", **args)
            pairs = shapes.lineage_results(payload)
            column_scoped = False

        for entity, degree in pairs:
            urn = str(entity["urn"])
            if urn == asset.urn:
                continue
            entry = graph.setdefault(
                urn,
                {
                    "urn": urn,
                    "type": shapes.entity_type(entity),
                    "name": shapes.entity_name(entity),
                    "platform": shapes.platform_of(entity),
                    "hops": degree,
                    "from_urn": asset.urn,
                    "from_column": asset.change.column,
                    "column_edge": column_scoped,
                    "owners": _dedupe(shapes.owners_of(entity)),
                    "tier": shapes.tier_of(entity),
                    "tags": shapes.tag_names(entity),
                    "schema_hit": None,
                    "queries": [],
                },
            )
            entry["hops"] = min(entry["hops"], degree)
            entry["column_edge"] = entry["column_edge"] or column_scoped

    # ML entities are not reachable through get_lineage: MLFeature.sources is an aspect,
    # not a lineage edge. Without this pass a column feeding a deployed model looks
    # completely safe — which is the failure mode the ML challenge is about.
    ml_entities, ml_error = await ml_graph.ml_entities(dh)
    if ml_error:
        trace.append(f"lineage: ML discovery problem — {ml_error}")
    if ml_entities:
        for asset in state.get("resolved", []):
            for entity, degree in ml_graph.dependents_of(
                asset.urn, ml_entities, asset.change.column
            ):
                urn = str(entity["urn"])
                graph.setdefault(
                    urn,
                    {
                        "urn": urn,
                        "type": shapes.entity_type(entity),
                        "name": shapes.entity_name(entity),
                        "platform": shapes.platform_of(entity),
                        "hops": degree,
                        "from_urn": asset.urn,
                        "from_column": asset.change.column,
                        "column_edge": False,
                        "owners": _dedupe(shapes.owners_of(entity)),
                        "tier": shapes.tier_of(entity),
                        "tags": shapes.tag_names(entity),
                        "schema_hit": None,
                        "ml_path": True,
                        "ml_column_match": bool(entity.get("_column_match")),
                        "queries": [],
                    },
                )
    elif not ml_error:
        trace.append("lineage: no ML entities in the catalog")

    # Lineage results already carry owners and tags for most entities; fill the gaps.
    missing = [urn for urn, entry in graph.items() if not entry["owners"]]
    if missing:
        details = shapes.entities(await dh.call("get_entities", urns=missing))
        for entity in details:
            entry = graph.get(str(entity.get("urn", "")))
            if entry:
                entry["owners"] = entry["owners"] or shapes.owners_of(entity)
                entry["tier"] = entry["tier"] or shapes.tier_of(entity)

    # Third evidence source, and on most instances the only one that fires: does the
    # consumer's own schema carry a field with that name? Weaker than a column-lineage
    # edge — a name collision is possible — but far stronger than a table dependency,
    # and the report labels it as the inference it is.
    column = next(
        (a.change.column for a in state.get("resolved", []) if a.change.column), None
    )
    datasets = [(urn, e) for urn, e in graph.items() if e["type"] == "dataset"]

    # These are dozens of independent round trips. Run them concurrently, bounded so a
    # wide blast radius cannot flood GMS — sequentially this was the slowest part of a
    # run by a wide margin.
    limiter = asyncio.Semaphore(CONCURRENT_PROBES)

    async def probe_schema(urn: str, entry: dict) -> None:
        if not column:
            return
        async with limiter:
            try:
                fields = shapes.field_names(await dh.call("list_schema_fields", urn=urn))
            except Exception as exc:
                trace.append(f"lineage: no schema for {urn} ({exc.__class__.__name__})")
                return
        entry["schema_hit"] = next((f for f in fields if f.lower() == column.lower()), None)

    async def probe_queries(urn: str, entry: dict) -> None:
        query_args: dict[str, Any] = {"urn": urn}
        if entry.get("from_column"):
            query_args["column"] = entry["from_column"]
        async with limiter:
            try:
                entry["queries"] = shapes.queries(
                    await dh.call("get_dataset_queries", **query_args)
                )
            except Exception as exc:  # evidence is best-effort, never fatal
                trace.append(f"lineage: no queries for {urn} ({exc.__class__.__name__})")

    probed = [
        (urn, entry)
        for urn, entry in datasets
        if int(entry.get("hops", 1)) <= SCHEMA_PROBE_HOPS
    ][:SCHEMA_PROBE_LIMIT]
    skipped = len(datasets) - len(probed)

    # Query history first, on a sample: if the catalog has none, the rest are wasted.
    sample = datasets[:QUERY_PROBE_SAMPLE]
    await asyncio.gather(*(probe_queries(urn, entry) for urn, entry in sample))

    if any(entry.get("queries") for _, entry in sample):
        await asyncio.gather(
            *(probe_queries(urn, entry) for urn, entry in datasets[QUERY_PROBE_SAMPLE:])
        )
    elif len(datasets) > QUERY_PROBE_SAMPLE:
        trace.append(
            f"lineage: no query history on the first {len(sample)} dataset(s), "
            f"skipped the remaining {len(datasets) - len(sample)}"
        )

    await asyncio.gather(*(probe_schema(urn, entry) for urn, entry in probed))
    if skipped:
        trace.append(
            f"lineage: schema checked within {SCHEMA_PROBE_HOPS} hop(s); "
            f"{skipped} more distant asset(s) cannot reach RISKY on a schema match alone"
        )

    ml_count = sum(1 for e in graph.values() if e["type"] in ML_TYPES)
    with_queries = sum(1 for e in graph.values() if e["queries"])
    with_schema = sum(1 for e in graph.values() if e.get("schema_hit"))
    trace.append(
        f"lineage: {len(graph)} downstream asset(s), {ml_count} ML entit(ies), "
        f"{with_queries} with query evidence, {with_schema} carrying the column in their schema"
    )
    return {"lineage_graph": graph, "trace": trace}

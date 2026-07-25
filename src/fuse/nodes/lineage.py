"""Node 3 — walk downstream lineage and collect the evidence the risk engine needs.

Deliberately does not stop at datasets. Charts, dashboards, data jobs, feature
tables, models, model groups and deployments are all downstream consumers, and the
ML ones are the consumers that break silently.

`get_lineage` takes `column`, so the traversal is column-scoped when a column
changed: DataHub returns what depends on that field rather than everything
downstream of the table.
"""

from __future__ import annotations

from typing import Any

from fuse.datahub import shapes
from fuse.runtime import RT
from fuse.state import FuseState

ML_TYPES = {"mlFeature", "mlFeatureTable", "mlModel", "mlModelGroup", "mlModelDeployment"}


def _is_error(payload: Any) -> bool:
    return isinstance(payload, dict) and ("__error__" in payload or "error" in payload)


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
                    "owners": shapes.owners_of(entity),
                    "tier": shapes.tier_of(entity),
                    "tags": shapes.tag_names(entity),
                    "queries": [],
                },
            )
            entry["hops"] = min(entry["hops"], degree)
            entry["column_edge"] = entry["column_edge"] or column_scoped

    # Lineage results already carry owners and tags for most entities; fill the gaps.
    missing = [urn for urn, entry in graph.items() if not entry["owners"]]
    if missing:
        details = shapes.entities(await dh.call("get_entities", urns=missing))
        for entity in details:
            entry = graph.get(str(entity.get("urn", "")))
            if entry:
                entry["owners"] = entry["owners"] or shapes.owners_of(entity)
                entry["tier"] = entry["tier"] or shapes.tier_of(entity)

    for urn, entry in graph.items():
        if entry["type"] != "dataset":
            continue
        query_args: dict[str, Any] = {"urn": urn}
        if entry.get("from_column"):
            query_args["column"] = entry["from_column"]
        try:
            entry["queries"] = shapes.queries(await dh.call("get_dataset_queries", **query_args))
        except Exception as exc:  # evidence is best-effort, never fatal
            trace.append(f"lineage: no queries for {urn} ({exc.__class__.__name__})")

    ml_count = sum(1 for e in graph.values() if e["type"] in ML_TYPES)
    with_queries = sum(1 for e in graph.values() if e["queries"])
    trace.append(
        f"lineage: {len(graph)} downstream asset(s), {ml_count} ML entit(ies), "
        f"{with_queries} with query evidence"
    )
    return {"lineage_graph": graph, "trace": trace}

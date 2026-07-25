"""Node 3 — walk downstream lineage and collect the evidence the risk engine needs.

Deliberately does not stop at datasets. Charts, dashboards, data jobs, feature
tables, models, model groups and deployments are all downstream consumers, and the
ML ones are the consumers that break silently.
"""

from __future__ import annotations

from typing import Any

from fuse.runtime import RT
from fuse.state import FuseState

ML_TYPES = {"mlfeature", "mlfeaturetable", "mlmodel", "mlmodelgroup", "mlmodeldeployment"}


def _nodes(payload: Any) -> list[dict]:
    # TODO(spike): confirm the exact get_lineage response shape on Day 2.
    if isinstance(payload, list):
        return [n for n in payload if isinstance(n, dict)]
    if isinstance(payload, dict):
        for key in ("downstreams", "relationships", "entities", "results", "lineage"):
            value = payload.get(key)
            if isinstance(value, list):
                return [n for n in value if isinstance(n, dict)]
    return []


def entity_type_of(urn: str, node: dict) -> str:
    declared = (node.get("type") or node.get("entityType") or "").lower()
    if declared:
        return declared
    if urn.startswith("urn:li:"):
        return urn.split(":")[2].lower()
    return "dataset"


def _is_error(payload: Any) -> bool:
    return isinstance(payload, dict) and ("__error__" in payload or "error" in payload)


def _hops(node: dict, default: int = 1) -> int:
    for key in ("degree", "hops", "distance"):
        if isinstance(node.get(key), int):
            return node[key]
    return default


async def trace_lineage(state: FuseState) -> dict:
    dh = RT.require_dh()
    hops = state.get("hops", 3)
    trace = list(state.get("trace", []))
    graph: dict[str, dict] = {}

    for asset in state.get("resolved", []):
        # `column` makes this column-level: DataHub returns only what actually depends
        # on the changed field, not everything downstream of the table.
        args: dict[str, Any] = {"urn": asset.urn, "upstream": False, "max_hops": hops}
        if asset.change.column:
            args["column"] = asset.change.column

        payload = await dh.call("get_lineage", **args)
        if _is_error(payload) and "column" in args:
            trace.append("lineage: column-level lineage unavailable, falling back to table-level")
            args.pop("column")
            payload = await dh.call("get_lineage", **args)

        for node in _nodes(payload):
            urn = node.get("urn") or node.get("entity", {}).get("urn", "")
            if not urn or urn == asset.urn:
                continue
            entry = graph.setdefault(
                urn,
                {
                    "urn": urn,
                    "type": entity_type_of(urn, node),
                    "name": node.get("name") or urn.rsplit(",", 2)[-2] if "," in urn else urn,
                    "hops": _hops(node),
                    "from_urn": asset.urn,
                    "from_column": asset.change.column,
                    "queries": [],
                    "raw": node,
                },
            )
            entry["hops"] = min(entry["hops"], _hops(node))

    # Hydrate owners / tags / tiers in one batch, then pull SQL evidence per dataset.
    if graph:
        details = await dh.call("get_entities", urns=list(graph))
        for entity in _nodes(details):
            urn = entity.get("urn", "")
            if urn in graph:
                graph[urn]["detail"] = entity

    for urn, entry in graph.items():
        if entry["type"] == "dataset":
            # Scoping to the changed column asks DataHub for the evidence directly
            # instead of pulling every query and filtering locally.
            query_args: dict[str, Any] = {"urn": urn}
            if entry.get("from_column"):
                query_args["column"] = entry["from_column"]
            try:
                entry["queries"] = await dh.call("get_dataset_queries", **query_args)
            except Exception as exc:  # evidence is best-effort, never fatal
                trace.append(f"lineage: no queries for {urn} ({exc.__class__.__name__})")

    ml_count = sum(1 for e in graph.values() if e["type"] in ML_TYPES)
    trace.append(f"lineage: {len(graph)} downstream asset(s), {ml_count} ML entit(ies)")
    return {"lineage_graph": graph, "trace": trace}

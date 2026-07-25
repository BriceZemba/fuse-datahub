"""Node 4 — score every downstream asset. Deterministic.

The interesting part is `references_column`: instead of assuming a consumer breaks
because it sits downstream, Fuse parses the consumer's own SQL (from
`get_dataset_queries`) and checks whether it actually selects the changed column.
That is the difference between an alert and an alarm.
"""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from fuse.risk.engine import RiskEngine
from fuse.state import Change, FuseState, Impact, ResolvedAsset, max_severity

TYPE_ALIASES = {
    "mlmodel": "mlModel",
    "mlmodelgroup": "mlModelGroup",
    "mlmodeldeployment": "mlModelDeployment",
    "mlfeature": "mlFeature",
    "mlfeaturetable": "mlFeatureTable",
    "datajob": "dataJob",
    "dataflow": "dataJob",
    "dashboard": "dashboard",
    "chart": "chart",
    "dataset": "dataset",
}


def _query_texts(payload: Any) -> list[tuple[str, str]]:
    """(query_id, sql) pairs from whatever shape get_dataset_queries returned."""
    rows = payload if isinstance(payload, list) else (payload or {}).get("queries", [])
    out: list[tuple[str, str]] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                sql = row.get("statement") or row.get("sql") or row.get("query") or ""
                if sql:
                    out.append((str(row.get("id") or row.get("urn") or "query"), sql))
            elif isinstance(row, str):
                out.append(("query", row))
    return out


def sql_references_column(sql: str, column: str, dialect: str = "snowflake") -> bool:
    """True when the statement really reads that column. Falls back to text search."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return column.lower() in sql.lower()
    for node in tree.find_all(exp.Column):
        if node.name.lower() == column.lower():
            return True
    for star in tree.find_all(exp.Star):
        _ = star  # SELECT * inherits the column, so treat it as a reference
        return True
    return False


def _owners(detail: dict | None) -> list[str]:
    if not detail:
        return []
    owners = detail.get("owners") or detail.get("ownership", {}).get("owners", [])
    out = []
    for owner in owners if isinstance(owners, list) else []:
        if isinstance(owner, str):
            out.append(owner)
        elif isinstance(owner, dict):
            out.append(owner.get("owner") or owner.get("urn") or "")
    return [o for o in out if o]


def _tier(detail: dict | None) -> str | None:
    if not detail:
        return None
    blob = str(detail.get("tags", "")) + str(detail.get("glossaryTerms", ""))
    for tier in ("Tier1", "Tier2", "Tier3"):
        if tier.lower() in blob.lower():
            return tier
    return None


def assess_impact(state: FuseState) -> dict:
    engine = RiskEngine()
    dialect = state.get("dialect", "snowflake")
    graph: dict[str, dict] = state.get("lineage_graph", {})
    resolved: list[ResolvedAsset] = state.get("resolved", [])
    by_urn: dict[str, Change] = {asset.urn: asset.change for asset in resolved}
    trace = list(state.get("trace", []))

    impacts: list[Impact] = []
    for urn, entry in graph.items():
        change = by_urn.get(entry.get("from_urn", ""))
        if change is None:
            continue
        column = change.column or ""
        detail = entry.get("detail")

        evidence: list[str] = []
        references = False
        for query_id, sql in _query_texts(entry.get("queries")):
            if column and sql_references_column(sql, column, dialect):
                references = True
                evidence.append(f"{query_id} selects {change.model}.{column}")

        entity_type = TYPE_ALIASES.get(str(entry.get("type", "dataset")).lower(), "dataset")
        owners = _owners(detail)
        score, severity, reasons = engine.score(
            change=change,
            entity_type=entity_type,
            hops=int(entry.get("hops", 1)),
            references_column=references,
            column_lineage_edge=bool(entry.get("column_edge")),
            tier=_tier(detail),
            owners=owners,
            recently_queried=bool(entry.get("queries")),
        )
        impacts.append(
            Impact(
                urn=urn,
                entity_type=entity_type,  # type: ignore[arg-type]
                name=str(entry.get("name", urn)),
                hops=int(entry.get("hops", 1)),
                references_column=references,
                evidence=evidence,
                owners=owners,
                tier=_tier(detail),
                severity=severity,
                score=score,
                reasons=reasons,
                source_change=change.describe(),
            )
        )

    impacts.sort(key=lambda i: i.score, reverse=True)
    worst = max_severity(impacts)
    counts = {s: sum(1 for i in impacts if i.severity == s) for s in ("BREAKING", "RISKY", "SAFE")}
    trace.append(
        f"impact: {len(impacts)} asset(s) — "
        f"{counts['BREAKING']} breaking, {counts['RISKY']} risky, {counts['SAFE']} safe"
    )
    return {"impacts": impacts, "max_severity": worst, "trace": trace}

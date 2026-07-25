"""Node 4 — score every downstream asset. Deterministic.

Evidence is ranked, not assumed. Strongest is a consumer whose own SQL selects the
changed column; next is a column-level lineage edge from DataHub; weakest is a plain
table dependency. The showcase catalog carries no query history, so most real runs
lean on the column edge — the report always says which one applied.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from fuse.risk.engine import RiskEngine
from fuse.state import Change, FuseState, Impact, ResolvedAsset, max_severity

VALID_ENTITY_TYPES = {
    "dataset",
    "chart",
    "dashboard",
    "dataJob",
    "mlFeature",
    "mlFeatureTable",
    "mlModel",
    "mlModelGroup",
    "mlModelDeployment",
}


def sql_references_column(sql: str, column: str, dialect: str = "snowflake") -> bool:
    """True when the statement really reads that column. Falls back to text search."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return column.lower() in sql.lower()

    for node in tree.find_all(exp.Column):
        if node.name.lower() == column.lower():
            return True
    for _ in tree.find_all(exp.Star):
        return True  # SELECT * inherits the column
    return False


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

        evidence: list[str] = []
        references = False
        for query_id, sql in entry.get("queries") or []:
            if column and sql_references_column(sql, column, dialect):
                references = True
                evidence.append(f"{query_id} selects {change.model}.{column}")

        column_edge = bool(entry.get("column_edge"))
        schema_hit = entry.get("schema_hit")
        if column_edge and not references:
            evidence.append(f"column-level lineage edge from {change.model}.{column}")
        elif schema_hit and not references:
            evidence.append(f"schema carries a field named `{schema_hit}`")

        entity_type = entry.get("type", "dataset")
        if entity_type not in VALID_ENTITY_TYPES:
            entity_type = "dataset"

        owners = entry.get("owners") or []
        score, severity, reasons = engine.score(
            change=change,
            entity_type=entity_type,
            hops=int(entry.get("hops", 1)),
            references_column=references,
            column_lineage_edge=column_edge,
            schema_contains_column=bool(schema_hit),
            tier=entry.get("tier"),
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
                tier=entry.get("tier"),
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

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
    """True when the statement really reads that column.

    This is the strongest evidence tier, so a false positive here declares a consumer
    broken when it is not. Two traps were live before this was tightened:

    - `count(*)` is not a column reference. Matching any `Star` anywhere meant an
      aggregate — even in a subquery over a different table — counted as proof.
    - A string literal that happens to contain the column name is not a reference.
    """
    wanted = column.lower()
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return wanted in sql.lower()

    if tree is None:
        return wanted in sql.lower()

    for node in tree.find_all(exp.Column):
        if node.name.lower() == wanted:
            return True

    # Only a star in a projection list inherits the column. `count(*)` is an aggregate
    # over rows and names nothing.
    for select in tree.find_all(exp.Select):
        for projection in select.expressions:
            if isinstance(projection, exp.Star):
                return True
            if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
                return True

    # Nothing that looks like SQL came back, so trust the text instead of a parse that
    # silently produced no columns at all.
    if not any(True for _ in tree.find_all(exp.Column)):
        return wanted in sql.lower()
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
        ml_path = bool(entry.get("ml_path"))
        ml_column_match = bool(entry.get("ml_column_match"))
        if column_edge and not references:
            evidence.append(f"column-level lineage edge from {change.model}.{column}")
        elif ml_path and not references:
            # Be precise about what lineage did and did not show. Some ML entities do
            # come back from get_lineage; the feature table, the deployment and the
            # model group generally do not, and lineage never says which feature — and
            # so which column — is the one that breaks.
            reach = "" if entry.get("in_lineage") else ", not returned by lineage"
            evidence.append(
                f"built on {change.model}.{column}{reach}"
                if ml_column_match
                else f"derived from {change.model} but not from `{column}`{reach}"
            )
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
            ml_derivation=ml_path and ml_column_match,
            schema_contains_column=bool(schema_hit),
            tier=entry.get("tier"),
            owners=owners,
            recently_queried=bool(entry.get("queries")),
        )
        if not evidence:
            # A score with an empty evidence column reads as "risky, for no reason".
            # Say what the dependency actually is, so every row carries its own why.
            evidence.append(
                f"reads from {change.model}; no column-level proof either way"
                if int(entry.get("hops", 1)) <= 1
                else f"{entry.get('hops', 1)} hops downstream of {change.model}"
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
                from_urn=str(entry.get("from_urn", "")),
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

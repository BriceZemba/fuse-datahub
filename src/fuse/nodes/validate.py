"""Node 7 — reject anything the catalog can't confirm.

This is the node that makes generated code trustworthy: every identifier in every
generated statement must exist in the schema DataHub returned. A hallucinated column
never reaches the PR — it comes back here as an error and the generator tries again.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from fuse.state import Artifact, FuseState, ResolvedAsset

SQL_KINDS = {"dbt_model", "compat_view"}
PY_KINDS = {"backfill"}


def known_columns(resolved: list[ResolvedAsset]) -> set[str]:
    names: set[str] = set()
    for asset in resolved:
        for field in asset.schema_fields:
            path = field.get("fieldPath") or field.get("name") if isinstance(field, dict) else field
            if path:
                names.add(str(path).split(".")[-1].lower())
    return names


def dropped_columns(resolved: list[ResolvedAsset]) -> set[str]:
    return {
        a.change.column.lower()
        for a in resolved
        if a.change.kind in {"drop_column", "rename_column"} and a.change.column
    }


def validate(state: FuseState) -> dict:
    artifacts: list[Artifact] = state.get("artifacts", [])
    resolved: list[ResolvedAsset] = state.get("resolved", [])
    dialect = state.get("dialect", "snowflake")
    trace = list(state.get("trace", []))

    allowed = known_columns(resolved)
    dropped = dropped_columns(resolved)
    errors: list[str] = []

    for artifact in artifacts:
        if artifact.kind in SQL_KINDS:
            errors += _check_sql(artifact, allowed, dropped, dialect)
        elif artifact.kind in PY_KINDS:
            errors += _check_python(artifact)

    if errors:
        trace.append(f"validate: REJECTED — {len(errors)} problem(s)")
        for err in errors[:5]:
            trace.append(f"  - {err}")
    else:
        trace.append(f"validate: {len(artifacts)} artifact(s) passed")

    # On the final attempt, ship flagged rather than silently broken.
    if errors and state.get("retries", 0) >= 2:
        for artifact in artifacts:
            artifact.needs_human = True
            artifact.notes.append("validation failed after 2 retries — needs human review")

    return {"validation_errors": errors, "artifacts": artifacts, "trace": trace}


def _check_sql(
    artifact: Artifact, allowed: set[str], dropped: set[str], dialect: str
) -> list[str]:
    errors: list[str] = []
    try:
        tree = sqlglot.parse_one(artifact.content, read=dialect)
    except Exception as exc:
        return [f"{artifact.path}: SQL does not parse as {dialect}: {exc}"]

    referenced = {c.name.lower() for c in tree.find_all(exp.Column) if c.name}
    # Locally-defined names (CTE outputs, aliases) are legitimate even though DataHub
    # has never seen them; only unknown *upstream* identifiers are a failure.
    local = {a.alias.lower() for a in tree.find_all(exp.Alias) if a.alias}
    local |= {c.alias.lower() for c in tree.find_all(exp.CTE) if c.alias}

    if allowed:
        unknown = sorted(referenced - allowed - local)
        for name in unknown:
            errors.append(
                f"{artifact.path}: column '{name}' is not in the DataHub schema "
                "for any upstream of this change"
            )

    for name in sorted(referenced & dropped):
        if artifact.kind != "compat_view":
            errors.append(
                f"{artifact.path}: references '{name}', which this change removes"
            )
    return errors


def _check_python(artifact: Artifact) -> list[str]:
    try:
        compile(artifact.content, artifact.path, "exec")
    except SyntaxError as exc:
        return [f"{artifact.path}: Python syntax error line {exc.lineno}: {exc.msg}"]
    return []

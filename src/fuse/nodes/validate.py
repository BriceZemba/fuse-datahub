"""Node 7 — reject anything the catalog can't confirm.

This is the node that makes generated code trustworthy: every identifier in every
generated statement must exist in the schema DataHub returned. A hallucinated column
never reaches the PR — it comes back here as an error and the generator tries again.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from fuse.nodes.parse_change import output_columns, strip_jinja
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


def retyped_columns(resolved: list[ResolvedAsset]) -> set[str]:
    """Columns whose type changed. These must survive a rewrite.

    A retype is not a removal, and a model that quietly drops the column instead of
    handling the new type loses data nobody agreed to lose.
    """
    return {
        a.change.column.lower()
        for a in resolved
        if a.change.kind == "retype_column" and a.change.column
    }


def validate(state: FuseState) -> dict:
    artifacts: list[Artifact] = state.get("artifacts", [])
    resolved: list[ResolvedAsset] = state.get("resolved", [])
    dialect = state.get("dialect", "snowflake")
    trace = list(state.get("trace", []))

    by_urn = {asset.urn: asset for asset in resolved}
    errors: list[str] = []
    per_artifact: dict[str, list[str]] = {}

    for artifact in artifacts:
        # Check against the schema of the model this artifact remediates. Falling back
        # to the union is only for artifacts that predate source attribution; pooling
        # schemas would accept a column that exists on a different changed model.
        scope = [by_urn[artifact.source_urn]] if artifact.source_urn in by_urn else resolved
        allowed = known_columns(scope)
        dropped = dropped_columns(scope)
        retyped = retyped_columns(scope)

        found: list[str] = []
        if artifact.kind in SQL_KINDS:
            found = _check_sql(artifact, allowed, dropped, retyped, dialect)
        elif artifact.kind in PY_KINDS:
            found = _check_python(artifact)
        if found:
            per_artifact[artifact.path] = found
            errors += found

    if errors:
        trace.append(f"validate: REJECTED — {len(errors)} problem(s)")
        for err in errors[:5]:
            trace.append(f"  - {err}")
    else:
        trace.append(f"validate: {len(artifacts)} artifact(s) passed")

    # On the final attempt, ship flagged rather than silently broken — but flag only
    # the artifacts that actually failed, not every file in the change.
    if errors and state.get("retries", 0) >= 2:
        for artifact in artifacts:
            if artifact.path in per_artifact:
                artifact.needs_human = True
                artifact.notes.append("validation failed after 2 retries — needs human review")

    return {"validation_errors": errors, "artifacts": artifacts, "trace": trace}


def _check_sql(
    artifact: Artifact,
    allowed: set[str],
    dropped: set[str],
    retyped: set[str],
    dialect: str,
) -> list[str]:
    errors: list[str] = []
    # Generated dbt models carry Jinja — {{ config() }}, {{ ref() }} — which sqlglot
    # cannot parse. Strip it the same way the diff parser does, so validation checks
    # the SQL rather than failing on the templating.
    try:
        tree = sqlglot.parse_one(strip_jinja(artifact.content), read=dialect)
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

    # A rewrite must drop the column, not paper over it. `NULL as promotion_id` keeps
    # the output shape and hands every downstream consumer nulls, which no test catches
    # — the failure this whole project exists to prevent. Preserving the shape on
    # purpose is what a compatibility view is for, and that is a separate decision.
    if artifact.kind == "dbt_model" and (dropped or retyped):
        try:
            produced = {c.lower() for c in output_columns(artifact.content, dialect)}
        except Exception:
            produced = set()

        for name in sorted(produced & dropped):
            errors.append(
                f"{artifact.path}: still outputs '{name}' after the change removed it. "
                "Remove the column instead of substituting a placeholder; if the output "
                "shape must be preserved, that is a compatibility view."
            )

        # The mirror image: a type change is not permission to delete the column.
        for name in sorted(retyped - produced):
            errors.append(
                f"{artifact.path}: dropped '{name}', but the change only altered its "
                "type. Keep the column and handle the new type."
            )
    return errors


def _check_python(artifact: Artifact) -> list[str]:
    try:
        compile(artifact.content, artifact.path, "exec")
    except SyntaxError as exc:
        return [f"{artifact.path}: Python syntax error line {exc.lineno}: {exc.msg}"]
    return []

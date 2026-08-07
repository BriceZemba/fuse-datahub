"""Node 6 - generate the remediation artifacts.

Two hard rules:
  1. The prompt always carries the *real* schema from DataHub, never a guess.
  2. Scaffolding (headers, dbt config, boilerplate) comes from templates, so the
     model only writes the part that needs judgment. Less surface to hallucinate on.

Validation errors from a previous attempt are fed back in verbatim on retry.
"""

from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from fuse.runtime import RT
from fuse.state import Artifact, Change, FuseState, Impact, ResolvedAsset

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)

PROMPT = """Rewrite this SQL so it no longer depends on a column that is being removed.

Change: {change}
Consumer: {name} ({urn})

The consumer's current SQL:
```sql
{sql}
```

The ONLY columns that will exist upstream after the change:
{allowed}

Rules:
- Use only columns from that list. Inventing a column is a failure.
- {instruction}
- Preserve every other output column name and the grain of the query.
- Keep the dialect: {dialect}.
{errors}
Return the corrected SQL only, no explanation, no fences."""

# What "fix the consumer" means depends entirely on what changed. Telling the model to
# remove a column that was merely retyped deletes data nobody asked to lose.
INSTRUCTIONS: dict[str, str] = {
    "drop_column": (
        "**Remove `{column}` from the output entirely.** Do not keep it as "
        "`NULL as {column}`, an empty string, a zero, or any other placeholder. A "
        "column filled with nulls breaks every consumer silently and no test catches "
        "it - preserving the output shape on purpose is a compatibility view, decided "
        "elsewhere, not something this rewrite should improvise."
    ),
    "rename_column": (
        "`{column}` has been renamed to `{renamed_to}` upstream. Read the new name and "
        "keep this model's own output column names exactly as they are."
    ),
    "retype_column": (
        "`{column}` changed type upstream from {from_type} to {to_type}. **Keep the "
        "column** - do not drop it - and **do not cast it back to {from_type}**. The "
        "upstream value is already {to_type}; casting back restores nothing and only "
        "hides that the type changed, so every consumer keeps reading a silently "
        "altered value. Let the new type flow through, and adjust any aggregation "
        "whose result the narrower type would truncate or overflow."
    ),
    "drop_model": (
        "The upstream model is being removed. Point this consumer at the surviving "
        "source of the same data, or fail loudly - do not silently return nothing."
    ),
}
DEFAULT_INSTRUCTION = (
    "Adjust this consumer for the upstream change without altering its own output "
    "column names."
)


def _instruction(change: Change) -> str:
    template = INSTRUCTIONS.get(change.kind, DEFAULT_INSTRUCTION)
    return template.format(
        column=change.column or "the column",
        renamed_to=change.renamed_to or "the new name",
        from_type=change.from_type or "its old type",
        to_type=change.to_type or "its new type",
    )


def _allowed_columns(asset: ResolvedAsset, *, exclude_changed: bool = False) -> list[str]:
    """Columns that will exist on this asset after its change.

    Scoped to one asset on purpose: pooling the schemas of every changed model would
    let a rewrite of model A reference a column that only exists on model B, and the
    validator would wave it through.

    `exclude_changed` drops the changed column whatever the change was - the
    compatibility view re-adds it itself, and listing it twice produces SQL with a
    duplicate output column.
    """
    change = asset.change
    skip = None
    if exclude_changed or change.kind in {"drop_column", "rename_column"}:
        skip = (change.column or "").lower()

    names: list[str] = []
    for field in asset.schema_fields:
        path = field.get("fieldPath") or field.get("name") if isinstance(field, dict) else field
        if path:
            name = str(path).split(".")[-1]
            if not skip or name.lower() != skip:
                names.append(name)
    return sorted(set(names))


def _why_no_rewrite(llm: object, sql: str) -> str:
    if llm is None:
        return "generated without an LLM: compatibility view instead of a rewrite"
    if not sql:
        return "no consumer SQL available: compatibility view instead of a rewrite"
    return "the model returned nothing: compatibility view instead of a rewrite"


def _template(name: str, **ctx: object) -> str:
    return env.get_template(name).render(**ctx)


async def generate_code(state: FuseState) -> dict:
    impacts: list[Impact] = state.get("impacts", [])
    resolved: list[ResolvedAsset] = state.get("resolved", [])
    plan = state.get("plan", {})
    errors = state.get("validation_errors") or []
    retries = state.get("retries", 0)
    trace = list(state.get("trace", []))
    dialect = state.get("dialect", "snowflake")
    # Only what the CLI bound. Falling back to get_llm() would build a client during a
    # replay, turning an offline reproduction into live network calls.
    llm = RT.llm

    by_urn = {asset.urn: asset for asset in resolved}
    default_asset = resolved[0] if resolved else None

    # Keyed by path: some strategies produce one artifact per changed model, not one
    # per impacted asset, and writing the same file once per consumer is both wrong
    # and unreadable in a PR.
    artifacts: dict[str, Artifact] = {}

    # Highest severity first, so the rewrite budget is spent on the consumers that
    # actually break rather than on whichever asset lineage happened to return first.
    ordered = sorted(impacts, key=lambda i: i.score, reverse=True)
    rewrites = 0
    deferred = 0

    for impact in ordered:
        strategy = plan.get(impact.urn, "no_action")
        if strategy == "no_action":
            continue

        if strategy == "rewrite_sql" and rewrites >= MAX_REWRITES:
            strategy = "add_contract_test"
            deferred += 1

        # Remediate against the model that actually affected this consumer.
        asset = by_urn.get(impact.from_urn) or default_asset
        if asset is None:
            continue
        change = asset.change
        allowed = _allowed_columns(asset)

        if strategy == "add_compat_view" and change:
            # One view per changed model, listing every consumer that needs it.
            path = f"models/compat/{change.model}_compat.sql"
            consumers, more = _consumers_for(impacts, plan, "add_compat_view", change.column)
            artifacts[path] = Artifact(
                path=path,
                kind="compat_view",
                source_urn=asset.urn,
                content=_template(
                    "compat_view.sql.j2",
                    model=change.model,
                    column=change.column,
                    kind=change.kind,
                    from_type=change.from_type,
                    to_type=change.to_type,
                    consumers=consumers,
                    more=more,
                    columns=_allowed_columns(asset, exclude_changed=True),
                    dialect=dialect,
                ),
            )
        elif strategy == "backfill" and change:
            path = f"scripts/backfill_{_slug(impact.name)}.py"
            artifacts[path] = Artifact(
                path=path,
                kind="backfill",
                source_urn=asset.urn,
                content=_template(
                    "backfill.py.j2",
                    model=change.model,
                    column=change.column,
                    consumer=impact.name,
                    urn=impact.urn,
                ),
            )
        elif strategy == "add_contract_test" and change:
            # One contract per changed model, regardless of how many consumers exist.
            path = f"models/{change.model}_schema.yml"
            artifacts[path] = Artifact(
                path=path,
                kind="dbt_test",
                source_urn=asset.urn,
                content=_template(
                    "schema_contract.yml.j2",
                    model=change.model,
                    columns=allowed,
                    removed=change.column,
                ),
            )
        elif strategy == "rewrite_sql" and change:
            sql = _consumer_sql(state, impact, change.model)
            # Ask whenever there is SQL to rewrite, even with no client configured: in
            # replay there is none, but the recorded answer is in the fixtures, and a
            # replay that silently swapped the model's SQL for a template would not be
            # reproducing the run it claims to reproduce.
            rewritten = ""
            if sql:
                rewritten = _strip_fences(
                    await RT.ask_llm(
                        "codegen",
                        PROMPT.format(
                            change=change.describe(),
                            name=impact.name,
                            urn=impact.urn,
                            sql=sql,
                            instruction=_instruction(change),
                            allowed="\n".join(f"- {c}" for c in allowed),
                            dialect=dialect,
                            errors=(
                                "\nThe previous attempt was rejected:\n"
                                + "\n".join(f"- {e}" for e in errors)
                                + "\n"
                                if errors
                                else ""
                            ),
                        ),
                    )
                    or ""
                )

            # An empty answer means the model failed or was unavailable. Writing the
            # empty string as a dbt model ships a file that would replace a working one
            # with nothing â€” fall back to the shim, which is what "no rewrite available"
            # has always meant.
            if not rewritten:
                # Nothing to rewrite from: a compatibility view is always safe, and one
                # per changed model is enough.
                path = f"models/compat/{change.model}_compat.sql"
                consumers, more = _consumers_for(impacts, plan, "rewrite_sql", change.column)
                artifacts[path] = Artifact(
                    path=path,
                    kind="compat_view",
                    source_urn=asset.urn,
                    content=_template(
                        "compat_view.sql.j2",
                        model=change.model,
                        column=change.column,
                        kind=change.kind,
                        from_type=change.from_type,
                        to_type=change.to_type,
                        consumers=consumers,
                        more=more,
                        columns=allowed,
                        dialect=dialect,
                    ),
                    notes=[_why_no_rewrite(llm, sql)],
                )
            else:
                path = f"models/{_slug(impact.name)}.sql"
                artifacts[path] = Artifact(
                    path=path,
                    kind="dbt_model",
                    source_urn=asset.urn,
                    content=rewritten,
                )
                rewrites += 1

    if change:
        artifacts["MIGRATION.md"] = Artifact(
            path="MIGRATION.md",
            kind="migration_doc",
            content=_template("migration.md.j2", change=change, impacts=impacts, plan=plan),
        )

    produced = list(artifacts.values())
    if RT.llm_error:
        trace.append(
            f"codegen: the model was unavailable ({RT.llm_error}); "
            "affected artifacts came from templates instead"
        )
    if deferred:
        trace.append(
            f"codegen: rewrote the {rewrites} highest-scoring consumer(s); "
            f"{deferred} more got a contract test instead "
            f"(raise FUSE_MAX_REWRITES to rewrite more)"
        )
    trace.append(f"codegen: {len(produced)} artifact(s) (attempt {retries + 1})")
    return {"artifacts": produced, "retries": retries + 1, "validation_errors": [], "trace": trace}


CONSUMER_LIST_LIMIT = 6

# Rewriting every affected consumer is neither reviewable nor affordable: a wide blast
# radius produces a pull request nobody can read, and one model call per consumer
# exhausts a free-tier daily quota in a couple of runs. Rewrite the ones that matter
# most and protect the rest with a contract test, which is the change a reviewer would
# make by hand anyway.
MAX_REWRITES = int(os.getenv("FUSE_MAX_REWRITES", "3"))


def _consumers_for(
    impacts: list[Impact], plan: dict, strategy: str, column: str | None = None
) -> tuple[list[str], int]:
    """(names, remaining) of the assets a shared artifact is generated for.

    Ordered by severity and excluding the entity that *is* the changed column - listing
    `credit_limit` as a consumer of `credit_limit` reads like a bug in the output.
    """
    names: list[str] = []
    for impact in impacts:
        if plan.get(impact.urn) != strategy:
            continue
        if column and impact.name.lower() == column.lower():
            continue
        if impact.name not in names:
            names.append(impact.name)
    return names[:CONSUMER_LIST_LIMIT], max(len(names) - CONSUMER_LIST_LIMIT, 0)


def _reads_from(sql: str, model: str) -> bool:
    """Whether this SQL actually selects from the changed model.

    A consumer two hops downstream is affected by the change but does not read the
    changed table directly - it reads whatever sits in between. Handing the model that
    consumer's SQL together with the *changed* table's columns invites exactly what it
    produced once: `dob as order_date`, a mapping of one table's columns onto another's
    output names. Only rewrite what genuinely reads the table that changed.
    """
    lowered = sql.lower()
    name = model.lower()
    return f"ref('{name}')" in lowered or f'ref("{name}")' in lowered or f" {name}" in lowered


def _consumer_sql(state: FuseState, impact: Impact, model: str | None = None) -> str:
    """The SQL that defines an impacted consumer, so it can be rewritten.

    The repo comes first: in a real pull request the downstream models are right there,
    and a catalog's query history is often empty - the showcase datapack has none at
    all. DataHub's recorded queries are the fallback for consumers that live outside
    this repo.
    """
    repo = Path(state.get("repo_path", "."))
    if repo.is_dir():
        stem = impact.name.lower()
        for candidate in repo.rglob("*.sql"):
            if candidate.stem.lower() == stem:
                sql = candidate.read_text(encoding="utf-8")
                if model and not _reads_from(sql, model):
                    return ""
                return sql

    entry = (state.get("lineage_graph") or {}).get(impact.urn, {})
    for row in entry.get("queries") or []:
        if isinstance(row, tuple) and len(row) == 2:
            return str(row[1])
        if isinstance(row, dict):
            sql = row.get("statement") or row.get("sql") or row.get("query")
            if sql:
                return str(sql)
        elif isinstance(row, str):
            return row
    return ""


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name).strip("_").lower()


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    # Return empty rather than a lone newline: callers test this value to decide whether
    # the model produced anything, and "\n" is truthy.
    return f"{text}\n" if text else ""

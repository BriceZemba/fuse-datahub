"""Node 6 — generate the remediation artifacts.

Two hard rules:
  1. The prompt always carries the *real* schema from DataHub, never a guess.
  2. Scaffolding (headers, dbt config, boilerplate) comes from templates, so the
     model only writes the part that needs judgment. Less surface to hallucinate on.

Validation errors from a previous attempt are fed back in verbatim on retry.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from fuse.llm.provider import get_llm
from fuse.runtime import RT
from fuse.state import Artifact, FuseState, Impact, ResolvedAsset

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
- Preserve the consumer's output column names and grain.
- Keep the dialect: {dialect}.
{errors}
Return the corrected SQL only, no explanation, no fences."""


def _allowed_columns(resolved: list[ResolvedAsset], dropped: str | None) -> list[str]:
    names: list[str] = []
    for asset in resolved:
        for field in asset.schema_fields:
            path = field.get("fieldPath") or field.get("name") if isinstance(field, dict) else field
            if path:
                name = str(path).split(".")[-1]
                if not dropped or name.lower() != dropped.lower():
                    names.append(name)
    return sorted(set(names))


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
    llm = RT.llm or get_llm()

    change = resolved[0].change if resolved else None
    allowed = _allowed_columns(resolved, change.column if change else None)

    # Keyed by path: some strategies produce one artifact per changed model, not one
    # per impacted asset, and writing the same file once per consumer is both wrong
    # and unreadable in a PR.
    artifacts: dict[str, Artifact] = {}

    for impact in impacts:
        strategy = plan.get(impact.urn, "no_action")
        if strategy == "no_action":
            continue

        if strategy == "add_compat_view" and change:
            # One view per changed model, listing every consumer that needs it.
            path = f"models/compat/{change.model}_compat.sql"
            consumers = _consumers_for(impacts, plan, "add_compat_view")
            artifacts[path] = Artifact(
                path=path,
                kind="compat_view",
                content=_template(
                    "compat_view.sql.j2",
                    model=change.model,
                    column=change.column,
                    consumer=", ".join(consumers),
                    columns=allowed,
                    dialect=dialect,
                ),
            )
        elif strategy == "backfill" and change:
            path = f"scripts/backfill_{_slug(impact.name)}.py"
            artifacts[path] = Artifact(
                path=path,
                kind="backfill",
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
                content=_template(
                    "schema_contract.yml.j2",
                    model=change.model,
                    columns=allowed,
                    removed=change.column,
                ),
            )
        elif strategy == "rewrite_sql" and change:
            sql = _consumer_sql(state, impact)
            if llm is None or not sql:
                # Nothing to rewrite from: a compatibility view is always safe, and one
                # per changed model is enough.
                path = f"models/compat/{change.model}_compat.sql"
                artifacts[path] = Artifact(
                    path=path,
                    kind="compat_view",
                    content=_template(
                        "compat_view.sql.j2",
                        model=change.model,
                        column=change.column,
                        consumer=", ".join(_consumers_for(impacts, plan, "rewrite_sql")),
                        columns=allowed,
                        dialect=dialect,
                    ),
                    notes=[
                        "no consumer SQL available"
                        if llm
                        else "generated without an LLM: compatibility view instead of a rewrite"
                    ],
                )
            else:
                rendered = await llm.ainvoke(
                    PROMPT.format(
                        change=change.describe(),
                        name=impact.name,
                        urn=impact.urn,
                        sql=sql,
                        allowed="\n".join(f"- {c}" for c in allowed),
                        dialect=dialect,
                        errors=(
                            "\nThe previous attempt was rejected:\n"
                            + "\n".join(f"- {e}" for e in errors)
                            + "\n"
                            if errors
                            else ""
                        ),
                    )
                )
                body = rendered.content if hasattr(rendered, "content") else str(rendered)
                path = f"models/{_slug(impact.name)}.sql"
                artifacts[path] = Artifact(
                    path=path,
                    kind="dbt_model",
                    content=_strip_fences(body),
                )

    if change:
        artifacts["MIGRATION.md"] = Artifact(
            path="MIGRATION.md",
            kind="migration_doc",
            content=_template("migration.md.j2", change=change, impacts=impacts, plan=plan),
        )

    produced = list(artifacts.values())
    trace.append(f"codegen: {len(produced)} artifact(s) (attempt {retries + 1})")
    return {"artifacts": produced, "retries": retries + 1, "validation_errors": [], "trace": trace}


def _consumers_for(impacts: list[Impact], plan: dict, strategy: str) -> list[str]:
    """Names of the assets a shared artifact is being generated for."""
    return [i.name for i in impacts if plan.get(i.urn) == strategy][:8]


def _consumer_sql(state: FuseState, impact: Impact) -> str:
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
    return text.strip() + "\n"

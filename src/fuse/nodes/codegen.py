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
    artifacts: list[Artifact] = []

    for impact in impacts:
        strategy = plan.get(impact.urn, "no_action")
        if strategy == "no_action":
            continue

        if strategy == "add_compat_view" and change:
            artifacts.append(
                Artifact(
                    path=f"models/compat/{change.model}_compat.sql",
                    kind="compat_view",
                    content=_template(
                        "compat_view.sql.j2",
                        model=change.model,
                        column=change.column,
                        consumer=impact.name,
                        columns=allowed,
                        dialect=dialect,
                    ),
                )
            )
        elif strategy == "backfill" and change:
            artifacts.append(
                Artifact(
                    path=f"scripts/backfill_{change.model}.py",
                    kind="backfill",
                    content=_template(
                        "backfill.py.j2",
                        model=change.model,
                        column=change.column,
                        consumer=impact.name,
                        urn=impact.urn,
                    ),
                )
            )
        elif strategy == "add_contract_test" and change:
            artifacts.append(
                Artifact(
                    path=f"models/{change.model}_schema.yml",
                    kind="dbt_test",
                    content=_template(
                        "schema_contract.yml.j2",
                        model=change.model,
                        columns=allowed,
                        removed=change.column,
                    ),
                )
            )
        elif strategy == "rewrite_sql" and change:
            sql = _consumer_sql(state, impact)
            if llm is None or not sql:
                # No model available: fall back to a compat view, which is always safe.
                artifacts.append(
                    Artifact(
                        path=f"models/compat/{change.model}_compat.sql",
                        kind="compat_view",
                        content=_template(
                            "compat_view.sql.j2",
                            model=change.model,
                            column=change.column,
                            consumer=impact.name,
                            columns=allowed,
                            dialect=dialect,
                        ),
                        notes=["generated without an LLM: compatibility view instead of a rewrite"],
                    )
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
                artifacts.append(
                    Artifact(
                        path=f"models/{_slug(impact.name)}.sql",
                        kind="dbt_model",
                        content=_strip_fences(body),
                    )
                )

    if change:
        artifacts.append(
            Artifact(
                path="MIGRATION.md",
                kind="migration_doc",
                content=_template(
                    "migration.md.j2",
                    change=change,
                    impacts=impacts,
                    plan=plan,
                ),
            )
        )

    trace.append(f"codegen: {len(artifacts)} artifact(s) (attempt {retries + 1})")
    return {"artifacts": artifacts, "retries": retries + 1, "validation_errors": [], "trace": trace}


def _consumer_sql(state: FuseState, impact: Impact) -> str:
    entry = (state.get("lineage_graph") or {}).get(impact.urn, {})
    queries = entry.get("queries")
    rows = queries if isinstance(queries, list) else (queries or {}).get("queries", [])
    for row in rows if isinstance(rows, list) else []:
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

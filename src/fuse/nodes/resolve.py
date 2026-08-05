"""Node 2 - map each changed model onto a DataHub URN.

Order of attack: exact name, then search ranking, then column-set overlap against
`list_schema_fields`, and only then the LLM. The method used is recorded so the
impact report can state *how* the asset was identified instead of asserting it.

`search` returns every entity type - schema fields, charts, data jobs, glossary
terms - so datasets are filtered by URN prefix before any of that begins.
"""

from __future__ import annotations

import asyncio

from fuse.datahub import shapes
from fuse.runtime import RT
from fuse.state import Change, FuseState, ResolvedAsset

AMBIGUITY_GAP = 0.15
LOW_CONFIDENCE = 0.6

# Each schema fetch is a round trip. Platform ranking has already ordered the pool, so
# looking past the top few candidates rarely changes the winner.
CANDIDATE_LIMIT = 3

# Warehouse and transformation platforms hold the tables a dbt model maps onto. BI
# platforms expose copies of them and would resolve the change to the wrong end of
# the graph.
PLATFORM_RANK = ("dbt", "snowflake", "bigquery", "redshift", "postgres", "spark", "s3")


async def _candidates(model: str) -> list[dict]:
    dh = RT.require_dh()
    payload = await dh.call("search", query=model, num_results=20)
    return [
        entity
        for entity in shapes.search_results(payload)
        if str(entity.get("urn", "")).startswith("urn:li:dataset:")
    ]


def _platform_score(entity: dict) -> float:
    platform = shapes.platform_of(entity)
    if platform in PLATFORM_RANK:
        return (len(PLATFORM_RANK) - PLATFORM_RANK.index(platform)) / len(PLATFORM_RANK)
    return 0.0


async def _resolve_one(change: Change, model_columns: set[str]) -> ResolvedAsset | None:
    candidates = await _candidates(change.model)
    if not candidates:
        return None

    exact = [e for e in candidates if shapes.entity_name(e).lower() == change.model.lower()]
    pool = exact or candidates
    pool.sort(key=_platform_score, reverse=True)

    if len(exact) == 1:
        return await _hydrate(change, exact[0], 0.95, "exact_name")

    if len(pool) == 1:
        # Search returns something for almost any query, so a lone candidate is not a
        # match - it is the only thing that came back. Confirm it shares a name token or
        # a column before reporting a blast radius for it, or Fuse confidently analyses
        # a different table.
        only = pool[0]
        fields = shapes.field_names(await RT.require_dh().call("list_schema_fields",
                                                              urn=only["urn"]))
        overlap = model_columns & {f.lower() for f in fields}
        if not overlap and not _name_tokens(change.model) & _name_tokens(
            shapes.entity_name(only)
        ):
            return None
        confidence = 0.8 if overlap else 0.65
        return await _hydrate(
            change, only, confidence, "schema_match" if overlap else "search_rank",
            fields=shapes.schema_fields(
                await RT.require_dh().call("list_schema_fields", urn=only["urn"])
            ),
        )

    # Disambiguate on evidence: how much of the model's column set the candidate has.
    # Fetched concurrently, and the winner's fields are kept so hydration does not ask
    # for the same schema a second time - every call here costs a round trip.
    dh = RT.require_dh()

    async def schema_of(candidate: dict) -> tuple[float, dict, list[dict]]:
        fields = shapes.schema_fields(
            await dh.call("list_schema_fields", urn=candidate["urn"])
        )
        known = {str(f.get("fieldPath", "")).split(".")[-1].lower() for f in fields}
        overlap = len(model_columns & known) / max(len(model_columns), 1)
        return overlap + _platform_score(candidate) / 10, candidate, fields

    scored = list(await asyncio.gather(*(schema_of(c) for c in pool[:CANDIDATE_LIMIT])))
    scored.sort(key=lambda row: row[0], reverse=True)

    best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    # Refuse to guess. A candidate that shares neither a name token nor a single column
    # with the changed model is not a weak match, it is a different table - and naming
    # the wrong table is worse than admitting the model is unknown.
    if best[0] <= 0 and not _name_tokens(change.model) & _name_tokens(
        shapes.entity_name(best[1])
    ):
        return None

    method = "schema_match" if best[0] - runner_up >= AMBIGUITY_GAP else "search_rank"
    return await _hydrate(
        change, best[1], round(min(0.5 + best[0] / 2, 0.99), 2), method, fields=best[2]
    )


def _name_tokens(name: str) -> set[str]:
    return {t for t in name.lower().replace("-", "_").split("_") if len(t) > 2}


async def _hydrate(
    change: Change,
    entity: dict,
    confidence: float,
    method: str,
    fields: list[dict] | None = None,
) -> ResolvedAsset:
    dh = RT.require_dh()
    urn = str(entity["urn"])
    if fields is None:
        fields = shapes.schema_fields(await dh.call("list_schema_fields", urn=urn))
    return ResolvedAsset(
        change=change,
        urn=urn,
        name=shapes.entity_name(entity),
        platform=shapes.platform_of(entity),
        confidence=confidence,
        method=method,  # type: ignore[arg-type]
        schema_fields=fields,
    )


async def resolve(state: FuseState) -> dict:
    changes: list[Change] = state.get("changes", [])
    trace = list(state.get("trace", []))
    resolved: list[ResolvedAsset] = []

    by_model: dict[str, set[str]] = {}
    for change in changes:
        if change.column:
            by_model.setdefault(change.model, set()).add(change.column.lower())

    for change in changes:
        asset = await _resolve_one(change, by_model.get(change.model, set()))
        if asset is None:
            trace.append(
                f"resolve: no confident DataHub match for {change.model} - "
                "skipped rather than reported against the wrong table"
            )
            continue
        trace.append(
            f"resolve: {change.model} -> {asset.urn} "
            f"({asset.method}, confidence {asset.confidence})"
        )
        if asset.confidence < LOW_CONFIDENCE:
            trace.append(f"resolve: low confidence on {change.model}, treat the report as a lead")
        resolved.append(asset)

    trace.append(f"resolve: {len(resolved)}/{len(changes)} change(s) mapped to URNs")
    return {"resolved": resolved, "trace": trace}

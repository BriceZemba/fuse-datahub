"""Node 2 — map each changed model onto a DataHub URN.

Order of attack: exact name, then search ranking, then column-set overlap against
`list_schema_fields`, and only then the LLM. The method used is recorded so the
impact report can state *how* the asset was identified instead of asserting it.
"""

from __future__ import annotations

from typing import Any

from fuse.runtime import RT
from fuse.state import Change, FuseState, ResolvedAsset

AMBIGUITY_GAP = 0.15
LOW_CONFIDENCE = 0.6


def _entities(payload: Any) -> list[dict]:
    """Normalise the several shapes a search response can arrive in."""
    # TODO(spike): pin this to the real response shape once Day-2 confirms it.
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    if isinstance(payload, dict):
        for key in ("entities", "results", "searchResults", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [e for e in value if isinstance(e, dict)]
    return []


def _urn(entity: dict) -> str:
    return entity.get("urn") or entity.get("entity", {}).get("urn", "")


def _name(entity: dict) -> str:
    return (
        entity.get("name")
        or entity.get("properties", {}).get("name")
        or _urn(entity).rsplit(",", 2)[-2].split(".")[-1]
        if _urn(entity)
        else ""
    )


def _field_names(payload: Any) -> list[str]:
    fields = payload.get("fields", payload) if isinstance(payload, dict) else payload
    names: list[str] = []
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                path = f.get("fieldPath") or f.get("name") or ""
                names.append(path.split(".")[-1].lower())
            elif isinstance(f, str):
                names.append(f.split(".")[-1].lower())
    return names


async def _candidates(model: str) -> list[dict]:
    dh = RT.require_dh()
    payload = await dh.call("search", query=model, num_results=10)
    return _entities(payload)


async def _resolve_one(change: Change, model_columns: set[str]) -> ResolvedAsset | None:
    candidates = await _candidates(change.model)
    if not candidates:
        return None

    exact = [c for c in candidates if _name(c).lower() == change.model.lower()]
    if len(exact) == 1:
        return await _hydrate(change, exact[0], 0.95, "exact_name")

    pool = exact or candidates
    if len(pool) == 1:
        return await _hydrate(change, pool[0], 0.8, "search_rank")

    # Disambiguate by how much of the model's column set the candidate actually has.
    dh = RT.require_dh()
    scored: list[tuple[float, dict, list[str]]] = []
    for candidate in pool[:5]:
        fields = _field_names(await dh.call("list_schema_fields", urn=_urn(candidate)))
        overlap = len(model_columns & set(fields)) / max(len(model_columns), 1)
        scored.append((overlap, candidate, fields))
    scored.sort(key=lambda row: row[0], reverse=True)

    best, runner_up = scored[0], scored[1] if len(scored) > 1 else (0.0, None, [])
    method = "schema_match" if best[0] - runner_up[0] >= AMBIGUITY_GAP else "search_rank"
    return await _hydrate(change, best[1], round(min(0.5 + best[0] / 2, 0.99), 2), method)


async def _hydrate(change: Change, entity: dict, confidence: float, method: str) -> ResolvedAsset:
    dh = RT.require_dh()
    urn = _urn(entity)
    fields = await dh.call("list_schema_fields", urn=urn)
    platform = urn.split("dataPlatform:")[-1].split(",")[0] if "dataPlatform:" in urn else ""
    return ResolvedAsset(
        change=change,
        urn=urn,
        name=_name(entity),
        platform=platform,
        confidence=confidence,
        method=method,  # type: ignore[arg-type]
        schema_fields=fields if isinstance(fields, list) else fields.get("fields", []),
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
            trace.append(f"resolve: no DataHub match for {change.model} — change skipped")
            continue
        if asset.confidence < LOW_CONFIDENCE:
            trace.append(
                f"resolve: low confidence {asset.confidence} for {change.model} -> {asset.urn}"
            )
        resolved.append(asset)

    trace.append(f"resolve: {len(resolved)}/{len(changes)} change(s) mapped to URNs")
    return {"resolved": resolved, "trace": trace}

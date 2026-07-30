"""Explicit traversal of DataHub's ML graph.

`get_lineage` walks datasets, jobs, charts and dashboards. It does **not** traverse
`MLFeature.sources`, so a column feeding a production model is invisible to ordinary
lineage — verified against a live DataHub 1.5.0.6, where a dataset with four features
derived from it reported thirty downstream entities and none of them were ML.

That gap is the whole point of the "silent ML breakage" problem: the dependency
exists, the catalog knows about it, and the lineage view does not show it. Fuse reads
the ML aspects directly instead:

    dataset -> MLFeature.sources
            -> MLFeatureTable.mlFeatures
            -> MLModel.mlFeatures
            -> MLModel.deployments
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fuse.datahub import shapes

ML_PREFIXES = (
    "urn:li:mlFeature:",
    "urn:li:mlFeatureTable:",
    "urn:li:mlModel:",
    "urn:li:mlModelGroup:",
    "urn:li:mlModelDeployment:",
)

# The catalogs this runs against hold tens of ML entities, not thousands. If that ever
# stops being true, this becomes a filtered search rather than a scan.
MAX_ML_ENTITIES = 200


# MLMODEL_DEPLOYMENT is deliberately absent: DataHub's GraphQL `EntityType` enum has no
# such value, and including it fails validation for the whole query. Deployments are
# reached through MLModelProperties.deployments instead, which is where they live.
ML_GRAPHQL_TYPES = "[MLFEATURE, MLFEATURE_TABLE, MLMODEL, MLMODEL_GROUP]"

# Keep the projection to `urn` only: every extra GraphQL field is another schema
# assumption that can break. The relationships are then read from the aspects with the
# typed SDK, which cannot drift from what the seed wrote.
ML_URN_QUERY = f"""
query mlUrns($count: Int!) {{
  searchAcrossEntities(
    input: {{ query: "*", count: $count, start: 0, types: {ML_GRAPHQL_TYPES} }}
  ) {{
    total
    searchResults {{ entity {{ urn }} }}
  }}
}}
"""


async def ml_urns(dh: Any) -> tuple[list[str], str | None]:
    """URNs of every ML entity in the catalog, plus any error worth reporting.

    Keyword search does not surface ML entity types, so this asks GMS directly for
    them by type. Routed through the cache so a recorded run replays offline.
    """

    async def discover() -> dict:
        urns, error = await _urns_via_graphql()
        if urns:
            return {"urns": urns, "error": None}

        payload = await dh.call("search", query="*", num_results=MAX_ML_ENTITIES)
        fallback = [
            str(e["urn"])
            for e in shapes.search_results(payload)
            if str(e.get("urn", "")).startswith(ML_PREFIXES)
        ]
        return {"urns": fallback, "error": error}

    result = await dh.cached("ml_urns", {}, discover)
    return list(result.get("urns") or []), result.get("error")


async def _urns_via_graphql(timeout: float = 30.0) -> tuple[list[str], str | None]:
    """Returns (urns, error). The error is surfaced rather than swallowed: a silent
    empty list here is indistinguishable from a catalog with no ML entities, and that
    ambiguity cost a full debugging round trip."""
    import httpx

    from fuse.config import settings

    headers = {"Content-Type": "application/json"}
    if settings.gms_token:
        headers["Authorization"] = f"Bearer {settings.gms_token}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.gms_url.rstrip('/')}/api/graphql",
                headers=headers,
                json={"query": ML_URN_QUERY, "variables": {"count": MAX_ML_ENTITIES}},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return [], f"{exc.__class__.__name__}: {exc}"

    if not isinstance(payload, dict):
        return [], "unexpected GraphQL response"

    if payload.get("errors"):
        first = payload["errors"][0]
        message = first.get("message") if isinstance(first, dict) else str(first)
        return [], str(message)

    # `data` is null whenever validation fails, so every step here is guarded.
    data = payload.get("data") or {}
    search = data.get("searchAcrossEntities") or {}
    results = search.get("searchResults") or []
    urns = [
        str(r["entity"]["urn"])
        for r in results
        if isinstance(r, dict) and isinstance(r.get("entity"), dict) and r["entity"].get("urn")
    ]
    return urns, None


def _hydrate_via_sdk(urns: list[str]) -> list[dict]:
    """Read the ML aspects with the typed SDK.

    The MCP `get_entities` projection returns only `urn`, `name`, `description` and
    `relatedDocuments` for ML entities — none of the relationships. Verified on
    DataHub 1.5.0.6; see docs/spike-raw/11-ml-entities.json. The aspects themselves are
    intact in GMS, so they are read with the same generated classes the seed emitted,
    which removes any guessing about field names.
    """
    from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph
    from datahub.metadata.schema_classes import (
        MLFeaturePropertiesClass,
        MLFeatureTablePropertiesClass,
        MLModelPropertiesClass,
    )

    from fuse.config import settings

    graph = DataHubGraph(
        DatahubClientConfig(server=settings.gms_url, token=settings.gms_token or None)
    )

    def read(urn: str) -> dict:
        properties: dict[str, Any] = {}
        try:
            if urn.startswith("urn:li:mlFeature:"):
                aspect = graph.get_aspect(urn, MLFeaturePropertiesClass)
                if aspect:
                    properties = {
                        "description": aspect.description,
                        "sources": list(aspect.sources or []),
                    }
            elif urn.startswith("urn:li:mlFeatureTable:"):
                aspect = graph.get_aspect(urn, MLFeatureTablePropertiesClass)
                if aspect:
                    properties = {
                        "description": aspect.description,
                        "mlFeatures": list(aspect.mlFeatures or []),
                    }
            elif urn.startswith("urn:li:mlModel:"):
                aspect = graph.get_aspect(urn, MLModelPropertiesClass)
                if aspect:
                    properties = {
                        "name": aspect.name,
                        "description": aspect.description,
                        "mlFeatures": list(aspect.mlFeatures or []),
                        "deployments": list(aspect.deployments or []),
                        "groups": list(aspect.groups or []),
                    }
        except Exception:  # one unreadable entity must not lose the rest
            properties = {}
        return {"urn": urn, "properties": properties}

    # One HTTP round trip per aspect, and they are independent.
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(read, urns))


async def ml_entities(dh: Any) -> tuple[list[dict], str | None]:
    """Every ML entity in the catalog, hydrated, plus any discovery error."""
    urns, error = await ml_urns(dh)
    if not urns:
        return [], error

    entities = await dh.cached(
        "ml_aspects",
        {"urns": sorted(urns)},
        lambda: asyncio.to_thread(_hydrate_via_sdk, urns),
    )
    return entities, error


def dependents_of(
    dataset_urn: str, entities: list[dict], column: str | None = None
) -> list[tuple[dict, int]]:
    """(entity, hops) for every ML entity reachable from a dataset.

    Hops are counted from the dataset: features are 1, the feature table and any model
    reading them 2, deployments 3. Same units as `get_lineage` degrees, so the risk
    engine treats them consistently.

    When a column is given, features are tagged with whether they are that column.
    Every feature of a table is *reachable* from a change to it, but the feature named
    after the dropped column is the one that certainly breaks; saying otherwise would
    flag a team's whole feature store on every schema change.
    """
    by_urn = {str(e.get("urn")): e for e in entities if e.get("urn")}
    found: dict[str, tuple[dict, int]] = {}

    features = {
        urn: entity
        for urn, entity in by_urn.items()
        if urn.startswith("urn:li:mlFeature:")
        and dataset_urn in shapes.ml_feature_sources(entity)
    }
    for urn, entity in features.items():
        if column:
            entity["_column_match"] = shapes.entity_name(entity).lower() == column.lower()
        found[urn] = (entity, 1)
    if not features:
        return []

    # A model or table only certainly breaks if it reads the feature that broke.
    broken = {u for u, e in features.items() if e.get("_column_match")} or set(features)

    for urn, entity in by_urn.items():
        if urn.startswith(("urn:li:mlFeatureTable:", "urn:li:mlModel:")) and set(
            shapes.ml_features_of(entity)
        ) & set(features):
            entity["_column_match"] = bool(set(shapes.ml_features_of(entity)) & broken)
            found[urn] = (entity, 2)

    # Deployments and groups hang off the affected models.
    models = [e for u, (e, _) in found.items() if u.startswith("urn:li:mlModel:")]
    for model in models:
        for urn in shapes.ml_deployments_of(model) + shapes.ml_groups_of(model):
            entity = by_urn.get(urn) or {"urn": urn}
            entity["_column_match"] = bool(model.get("_column_match"))
            found.setdefault(urn, (entity, 3))

    return list(found.values())

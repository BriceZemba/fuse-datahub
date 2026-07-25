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


ML_GRAPHQL_TYPES = "[MLFEATURE, MLFEATURE_TABLE, MLMODEL, MLMODEL_GROUP, MLMODEL_DEPLOYMENT]"

# Keep the projection to `urn` only: every extra GraphQL field is another schema
# assumption that can break. Details come back through get_entities, whose shape is
# pinned by tests.
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


async def ml_urns(call: Any) -> list[str]:
    """URNs of every ML entity in the catalog.

    Keyword search does not surface ML entity types, so this asks GMS directly for
    them by type. Falls back to the MCP search in case a future server does return
    them there.
    """
    urns = await _urns_via_graphql()
    if urns:
        return urns

    payload = await call("search", query="*", num_results=MAX_ML_ENTITIES)
    return [
        str(e["urn"])
        for e in shapes.search_results(payload)
        if str(e.get("urn", "")).startswith(ML_PREFIXES)
    ]


async def _urns_via_graphql() -> list[str]:
    import httpx

    from fuse.config import settings

    headers = {"Content-Type": "application/json"}
    if settings.gms_token:
        headers["Authorization"] = f"Bearer {settings.gms_token}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{settings.gms_url.rstrip('/')}/api/graphql",
                headers=headers,
                json={"query": ML_URN_QUERY, "variables": {"count": MAX_ML_ENTITIES}},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    results = (
        payload.get("data", {}).get("searchAcrossEntities", {}).get("searchResults") or []
    )
    return [
        str(r["entity"]["urn"])
        for r in results
        if isinstance(r, dict) and isinstance(r.get("entity"), dict) and r["entity"].get("urn")
    ]


async def ml_entities(call: Any) -> list[dict]:
    """Every ML entity in the catalog, hydrated."""
    urns = await ml_urns(call)
    if not urns:
        return []
    return shapes.entities(await call("get_entities", urns=urns))


def dependents_of(dataset_urn: str, entities: list[dict]) -> list[tuple[dict, int]]:
    """(entity, hops) for every ML entity reachable from a dataset.

    Hops are counted from the dataset: features are 1, the feature table and any model
    reading them 2, deployments 3. Same units as `get_lineage` degrees, so the risk
    engine treats them consistently.
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
        found[urn] = (entity, 1)
    if not features:
        return []

    for urn, entity in by_urn.items():
        if urn.startswith(("urn:li:mlFeatureTable:", "urn:li:mlModel:")) and set(
            shapes.ml_features_of(entity)
        ) & set(features):
            found[urn] = (entity, 2)

    # Deployments and groups hang off the affected models.
    models = [e for u, (e, _) in found.items() if u.startswith("urn:li:mlModel:")]
    for model in models:
        for urn in shapes.ml_deployments_of(model) + shapes.ml_groups_of(model):
            entity = by_urn.get(urn) or {"urn": urn}
            found.setdefault(urn, (entity, 3))

    return list(found.values())

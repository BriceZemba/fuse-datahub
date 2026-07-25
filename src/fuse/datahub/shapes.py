"""Readers for DataHub MCP response shapes.

Written against recorded responses from a live DataHub 1.5.0.6 — the raw payloads are
in `docs/spike-raw/` and the tests read them directly, so if the server's shape ever
changes the tests fail rather than the agent silently reporting an empty graph.

Shapes as of 1.5.0.6:

    search              {"searchResults": [{"entity": {"urn", "properties": {"name"}}}],
                         "total", "facets": [...]}
    get_lineage         {"downstreams": {"searchResults": [{"entity": {...}, "degree": 1}],
                         "total", "facets": [...]}}
    get_entities        [{"urn", "name", "platform": {...}, "properties": {...},
                          "ownership": {"owners": [{"owner": {"urn"}}]},
                          "tags": {"tags": [{"tag": {"urn", "properties": {"name"}}}]},
                          "glossaryTerms": {"terms": [{"term": {"properties": {"name"}}}]}}]
    list_schema_fields  {"urn", "fields": [{"fieldPath", "nativeDataType", "nullable"}],
                         "totalFields"}
    get_dataset_queries {"start", "count", "total", "queries"?}
"""

from __future__ import annotations

from typing import Any

# DataHub reports entity types in SCREAMING_SNAKE; the metadata model spells them in
# camelCase, and so does Fuse.
ENTITY_TYPES: dict[str, str] = {
    "DATASET": "dataset",
    "CHART": "chart",
    "DASHBOARD": "dashboard",
    "DATA_JOB": "dataJob",
    "DATA_FLOW": "dataJob",
    "MLMODEL": "mlModel",
    "ML_MODEL": "mlModel",
    "MLMODEL_GROUP": "mlModelGroup",
    "ML_MODEL_GROUP": "mlModelGroup",
    "MLMODEL_DEPLOYMENT": "mlModelDeployment",
    "ML_MODEL_DEPLOYMENT": "mlModelDeployment",
    "MLFEATURE": "mlFeature",
    "ML_FEATURE": "mlFeature",
    "MLFEATURE_TABLE": "mlFeatureTable",
    "ML_FEATURE_TABLE": "mlFeatureTable",
}

URN_TYPES: dict[str, str] = {
    "dataset": "dataset",
    "chart": "chart",
    "dashboard": "dashboard",
    "dataJob": "dataJob",
    "dataFlow": "dataJob",
    "mlModel": "mlModel",
    "mlModelGroup": "mlModelGroup",
    "mlModelDeployment": "mlModelDeployment",
    "mlFeature": "mlFeature",
    "mlFeatureTable": "mlFeatureTable",
}


def search_results(payload: Any) -> list[dict]:
    """Entities from a `search` response, ignoring facets."""
    if isinstance(payload, dict):
        results = payload.get("searchResults")
        if isinstance(results, list):
            return [r["entity"] for r in results if isinstance(r, dict) and "entity" in r]
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict) and "urn" in e]
    return []


def lineage_results(payload: Any, *, upstream: bool = False) -> list[tuple[dict, int]]:
    """(entity, degree) pairs from `get_lineage`.

    `degree` lives on the search result, not on the entity, and is the hop count.
    """
    if not isinstance(payload, dict):
        return []
    section = payload.get("upstreams" if upstream else "downstreams")
    if not isinstance(section, dict):
        # Some responses put searchResults at the top level.
        section = payload
    results = section.get("searchResults")
    if not isinstance(results, list):
        return []

    pairs: list[tuple[dict, int]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        entity = result.get("entity")
        if isinstance(entity, dict) and entity.get("urn"):
            pairs.append((entity, int(result.get("degree") or 1)))
    return pairs


def entities(payload: Any) -> list[dict]:
    """Entities from `get_entities`, which answers with a bare list."""
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict) and e.get("urn")]
    if isinstance(payload, dict):
        for key in ("entities", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [e for e in value if isinstance(e, dict)]
        if payload.get("urn"):
            return [payload]
    return []


def schema_fields(payload: Any) -> list[dict]:
    """Field dicts from `list_schema_fields`."""
    if isinstance(payload, dict):
        fields = payload.get("fields")
        if isinstance(fields, list):
            return [f for f in fields if isinstance(f, dict)]
    if isinstance(payload, list):
        return [f for f in payload if isinstance(f, dict)]
    return []


def field_names(payload: Any) -> list[str]:
    names = []
    for field in schema_fields(payload):
        path = field.get("fieldPath") or field.get("name") or ""
        if path:
            names.append(str(path).split(".")[-1])
    return names


def queries(payload: Any) -> list[tuple[str, str]]:
    """(id, sql) pairs from `get_dataset_queries`.

    The showcase catalog ships no query history (`total: 0`), so this legitimately
    returns nothing there. Impact scoring must not depend on it alone.
    """
    rows: Any = payload
    if isinstance(payload, dict):
        rows = payload.get("queries") or payload.get("searchResults") or []
    if not isinstance(rows, list):
        return []

    out: list[tuple[str, str]] = []
    for row in rows:
        if isinstance(row, str):
            out.append(("query", row))
            continue
        if not isinstance(row, dict):
            continue
        entity = row.get("entity") if isinstance(row.get("entity"), dict) else row
        properties = entity.get("properties")
        properties = properties if isinstance(properties, dict) else {}

        sql: Any = (
            entity.get("statement")
            or entity.get("sql")
            or entity.get("query")
            or properties.get("statement")
        )
        if isinstance(sql, dict):  # statement is sometimes {value, language}
            sql = sql.get("value")
        if sql:
            out.append((str(entity.get("urn") or row.get("id") or "query"), str(sql)))
    return out


def entity_type(entity: dict) -> str:
    """camelCase entity type, from the declared type or failing that the URN."""
    declared = str(entity.get("type") or entity.get("entityType") or "").upper()
    if declared in ENTITY_TYPES:
        return ENTITY_TYPES[declared]

    urn = str(entity.get("urn") or "")
    if urn.startswith("urn:li:"):
        raw = urn.split(":")[2]
        return URN_TYPES.get(raw, raw)
    return "dataset"


def entity_name(entity: dict) -> str:
    properties = entity.get("properties")
    if isinstance(properties, dict) and properties.get("name"):
        return str(properties["name"])
    if entity.get("name"):
        return str(entity["name"])

    urn = str(entity.get("urn") or "")
    if "," in urn:  # urn:li:dataset:(urn:li:dataPlatform:x,db.schema.table,PROD)
        return urn.split(",")[1].split(".")[-1]
    return urn


def platform_of(entity: dict) -> str:
    platform = entity.get("platform")
    if isinstance(platform, dict):
        name = platform.get("name") or str(platform.get("urn", "")).split(":")[-1]
        if name:
            return str(name)
    urn = str(entity.get("urn") or "")
    if "dataPlatform:" in urn:
        return urn.split("dataPlatform:")[1].split(",")[0].rstrip(")")
    return ""


def owners_of(entity: dict) -> list[str]:
    ownership = entity.get("ownership")
    if not isinstance(ownership, dict):
        return []
    out: list[str] = []
    for item in ownership.get("owners") or []:
        if not isinstance(item, dict):
            continue
        owner = item.get("owner")
        if isinstance(owner, dict) and owner.get("urn"):
            out.append(str(owner["urn"]))
        elif isinstance(owner, str):
            out.append(owner)
    return out


def tag_names(entity: dict) -> list[str]:
    tags = entity.get("tags")
    if not isinstance(tags, dict):
        return []
    out: list[str] = []
    for item in tags.get("tags") or []:
        tag = item.get("tag") if isinstance(item, dict) else None
        if not isinstance(tag, dict):
            continue
        properties = tag.get("properties")
        name = properties.get("name") if isinstance(properties, dict) else None
        out.append(str(name or tag.get("urn", "")))
    return out


def term_names(entity: dict) -> list[str]:
    terms = entity.get("glossaryTerms")
    if not isinstance(terms, dict):
        return []
    out: list[str] = []
    for item in terms.get("terms") or []:
        term = item.get("term") if isinstance(item, dict) else None
        if not isinstance(term, dict):
            continue
        properties = term.get("properties")
        name = properties.get("name") if isinstance(properties, dict) else None
        out.append(str(name or term.get("urn", "")))
    return out


def tier_of(entity: dict) -> str | None:
    """Tier comes from tags or glossary terms; DataHub has no first-class field."""
    haystack = " ".join(tag_names(entity) + term_names(entity)).lower()
    for tier in ("tier1", "tier 1", "gold"):
        if tier in haystack:
            return "Tier1"
    for tier in ("tier2", "tier 2", "silver"):
        if tier in haystack:
            return "Tier2"
    return None

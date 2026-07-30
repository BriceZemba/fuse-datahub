"""Golden tests against responses recorded from a live DataHub 1.5.0.6.

These read docs/spike-raw/ directly. If the MCP server's response shape changes,
these fail loudly instead of the agent quietly reporting that nothing is downstream.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fuse.datahub import shapes
from fuse.datahub.mcp_client import _coerce

RAW = Path(__file__).resolve().parents[1] / "docs" / "spike-raw"


def load(name: str):
    """Read a recorded response exactly as the MCP client would receive it."""
    return _coerce(json.loads((RAW / name).read_text(encoding="utf-8")))


pytestmark = pytest.mark.skipif(not RAW.exists(), reason="spike recordings not present")


def test_fixture_filenames_are_portable(tmp_path):
    """Fixtures are committed, and judges clone on Windows too. A key like "llm:codegen"
    yields a path git cannot check out there — the repo fails before any code runs."""
    from fuse.datahub.cache import CallCache

    cache = CallCache(tmp_path)
    cache.put("llm:codegen", {"prompt": "x"}, {"ok": True})

    written = list(tmp_path.iterdir())
    assert written, "nothing was recorded"
    for path in written:
        assert not set(path.name) & set(':<>"|?*\\/'), f"unportable filename: {path.name}"

    # Sanitising the name must not merge distinct keys.
    cache.put("llm-codegen", {"prompt": "x"}, {"ok": False})
    assert len(list(tmp_path.iterdir())) == 2


def test_coerce_unwraps_text_content_blocks():
    payload = _coerce([{"id": "lc_1", "type": "text", "text": '{"total": 3}'}])
    assert payload == {"total": 3}


def test_coerce_passes_through_plain_json():
    assert _coerce({"total": 1}) == {"total": 1}
    assert _coerce('{"a": 2}') == {"a": 2}


def test_coerce_keeps_unparseable_text():
    assert _coerce([{"type": "text", "text": "not json"}]) == {"text": "not json"}


def test_search_results_are_entities_not_facets():
    entities = shapes.search_results(load("01-search.json"))
    assert entities, "search returned no entities"
    assert all("urn" in e for e in entities)
    # The response mixes datasets, schema fields, charts, data jobs and glossary terms.
    assert any(e["urn"].startswith("urn:li:dataset:") for e in entities)


def test_dataset_names_and_platforms_are_readable():
    datasets = [
        e
        for e in shapes.search_results(load("01-search.json"))
        if e["urn"].startswith("urn:li:dataset:")
    ]
    names = {shapes.entity_name(e).lower() for e in datasets}
    platforms = {shapes.platform_of(e) for e in datasets}
    assert "orders" in names
    assert "snowflake" in platforms


def test_lineage_results_carry_degree():
    pairs = shapes.lineage_results(load("04-get_lineage.json"))
    assert pairs, "lineage returned no downstream entities"
    assert all(isinstance(degree, int) and degree >= 1 for _, degree in pairs)


def test_lineage_entity_types_map_to_camel_case():
    types = {shapes.entity_type(entity) for entity, _ in shapes.lineage_results(
        load("04-get_lineage.json")
    )}
    assert "dataJob" in types or "dataset" in types
    assert not any(t.isupper() for t in types)


def test_schema_fields_expose_field_paths():
    names = shapes.field_names(load("02-list_schema_fields.json"))
    assert "order_id" in names
    assert "customer_id" in names


def test_get_entities_returns_a_bare_list():
    entities = shapes.entities(load("03-get_entities.json"))
    assert entities and entities[0]["urn"].startswith("urn:li:dataset:")


def test_glossary_terms_are_read_from_the_entity_not_its_terms():
    entity = shapes.entities(load("03-get_entities.json"))[0]
    assert "PII" in shapes.term_names(entity)
    # The nested term has its own ownership block; the dataset's must not be confused
    # with it, so owners_of only reads the top-level ownership aspect.
    assert all(o.startswith("urn:li:") for o in shapes.owners_of(entity))


def test_empty_query_history_is_not_an_error():
    assert shapes.queries(load("05-get_dataset_queries.json")) == []

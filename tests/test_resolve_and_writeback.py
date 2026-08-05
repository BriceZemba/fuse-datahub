"""Probing resolution and write-back with the awkward cases a real catalog produces."""

from __future__ import annotations

import pytest

from fuse.datahub.cache import CallCache
from fuse.nodes import resolve as resolve_node
from fuse.nodes.resolve import _name_tokens, _platform_score, resolve
from fuse.nodes.writeback import _document_urn, _looks_like_error, write_back
from fuse.runtime import RT
from fuse.state import Change, Impact


def entity(urn: str, name: str) -> dict:
    return {"urn": urn, "properties": {"name": name}}


def dataset(platform: str, table: str) -> dict:
    return entity(
        f"urn:li:dataset:(urn:li:dataPlatform:{platform},db.schema.{table},PROD)", table
    )


class FakeDH:
    """Answers the MCP calls resolve and writeback make, with scriptable responses."""

    def __init__(self, responses: dict, tmp_path=None) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []
        self.cache = CallCache(tmp_path) if tmp_path else None

    async def call(self, tool: str, **args):
        self.calls.append((tool, args))
        value = self.responses.get(tool)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(**args)
        return value if value is not None else []


@pytest.fixture
def change() -> Change:
    return Change(kind="drop_column", file="models/orders.sql", model="orders",
                  column="promotion_id")


# ----------------------------------------------------------------------- resolution


def test_platform_ranking_prefers_warehouses_over_bi():
    assert _platform_score(dataset("dbt", "orders")) > _platform_score(
        dataset("powerbi", "orders")
    )


def test_name_tokens_ignore_short_fragments():
    assert _name_tokens("order_details") == {"order", "details"}
    assert "db" not in _name_tokens("db_orders")


def test_no_candidates_means_no_resolution(change, monkeypatch):
    RT.dh = FakeDH({"search": []})
    result = pytest.importorskip("asyncio").run(
        resolve({"changes": [change], "trace": []})
    )
    assert result["resolved"] == []
    assert any("no confident DataHub match" in line for line in result["trace"])


def test_an_unrelated_top_hit_is_refused(change):
    """Search returns something for almost any query. A candidate sharing neither a
    name token nor a column with the changed model is a different table."""
    RT.dh = FakeDH(
        {
            "search": [entity("urn:li:dataset:(urn:li:dataPlatform:dbt,db.s.invoices,PROD)",
                              "invoices")],
            "list_schema_fields": {"fields": [{"fieldPath": "invoice_id"}]},
        }
    )
    result = pytest.importorskip("asyncio").run(
        resolve({"changes": [change], "trace": []})
    )
    assert result["resolved"] == []


def test_an_exact_name_match_wins(change):
    RT.dh = FakeDH(
        {
            "search": [dataset("powerbi", "orders"), dataset("dbt", "orders")],
            "list_schema_fields": {"fields": [{"fieldPath": "promotion_id"}]},
        }
    )
    result = pytest.importorskip("asyncio").run(
        resolve({"changes": [change], "trace": []})
    )
    assert len(result["resolved"]) == 1
    assert result["resolved"][0].confidence >= 0.5


def test_schema_fields_are_not_fetched_twice_for_the_winner(change):
    """Each MCP call is a round trip; hydration must reuse what disambiguation read."""
    RT.dh = FakeDH(
        {
            "search": [dataset("dbt", "orders"), dataset("snowflake", "orders")],
            "list_schema_fields": {"fields": [{"fieldPath": "promotion_id"}]},
        }
    )
    pytest.importorskip("asyncio").run(resolve({"changes": [change], "trace": []}))
    schema_calls = [c for c in RT.dh.calls if c[0] == "list_schema_fields"]
    assert len(schema_calls) <= 3, f"one call per candidate at most, got {len(schema_calls)}"


# ----------------------------------------------------------------------- write-back


def test_a_failed_tag_does_not_abort_the_rest(tmp_path):
    RT.dh = FakeDH(
        {
            "add_tags": RuntimeError("permission denied"),
            "add_structured_properties": {"ok": True},
            "update_description": {"ok": True},
            "save_document": {"urn": "urn:li:document:1"},
        },
        tmp_path,
    )
    RT.dry_run = False
    impacts = [Impact(urn="urn:li:dataset:a", entity_type="dataset", name="a",
                      severity="BREAKING", score=90)]
    result = pytest.importorskip("asyncio").run(
        write_back({"impacts": impacts, "resolved": [], "run_id": "r", "trace": []})
    )
    writeback = result["writeback"]
    assert writeback.tagged == [], "a failed call must not be reported as written"
    assert writeback.errors, "the failure must be recorded"
    assert writeback.document_urn == "urn:li:document:1", "the report should still save"


def test_error_text_is_recognised_without_an_exception():
    assert _looks_like_error({"text": "1 validation error for call[save_document]"})
    assert not _looks_like_error({"text": "Saved successfully"})


def test_a_urn_is_found_in_prose():
    assert _document_urn({"text": "Created urn:li:document:abc-123 ok"}) == (
        "urn:li:document:abc-123"
    )


def teardown_function() -> None:
    RT.dh = None
    RT.llm = None
    RT.dry_run = False
    resolve_node.RT.dh = None

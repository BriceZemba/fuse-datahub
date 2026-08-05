"""Probing evidence detection and caching for false positives.

Evidence drives severity, and a false positive here is worse than a miss: it tells a
team a change is breaking when it is not, and they stop reading the reports.
"""

from __future__ import annotations

from fuse.datahub.cache import CallCache
from fuse.nodes.impact import sql_references_column


def test_a_direct_reference_counts():
    assert sql_references_column("select promotion_id from orders", "promotion_id")


def test_an_unrelated_column_does_not_count():
    assert not sql_references_column("select order_id from orders", "promotion_id")


def test_select_star_counts_as_a_reference():
    """`select *` genuinely inherits the column, so this is intentional."""
    assert sql_references_column("select * from orders", "promotion_id")


def test_a_star_on_a_different_table_is_not_a_reference():
    """A star in a subquery over another table says nothing about this column."""
    sql = "select o.order_id, (select count(*) from audit_log) as n from orders o"
    assert not sql_references_column(sql, "promotion_id")


def test_a_column_named_in_a_string_literal_is_not_a_reference():
    sql = "select order_id, 'promotion_id' as label from orders"
    assert not sql_references_column(sql, "promotion_id")


def test_a_column_of_the_same_name_on_another_table_still_counts():
    """Conservative on purpose: qualified names are not resolved to their tables, so a
    same-named column elsewhere is reported. Over-reporting evidence is acceptable;
    silently missing a real dependency is not."""
    assert sql_references_column("select other.promotion_id from other", "promotion_id")


def test_unparseable_sql_falls_back_to_text_search():
    """Query history contains dialect quirks sqlglot cannot parse. Losing the evidence
    entirely would be worse than a text match."""
    assert sql_references_column("SELECT ((( FROM promotion_id", "promotion_id")


def test_an_output_alias_of_that_name_is_not_a_reference():
    """`... as promotion_id` names an output column; it does not read the upstream one.
    sqlglot parses prose into exactly this shape, which is how the previous version of
    this test misled me."""
    assert not sql_references_column("select order_id as promotion_id from orders", "promotion_id")


def test_case_insensitive_reference():
    assert sql_references_column("select PROMOTION_ID from orders", "promotion_id")


# --------------------------------------------------------------------------- cache


def test_different_arguments_do_not_collide(tmp_path):
    cache = CallCache(tmp_path)
    cache.put("search", {"query": "a"}, {"result": "first"})
    cache.put("search", {"query": "b"}, {"result": "second"})
    assert cache.get("search", {"query": "a"}) == {"result": "first"}
    assert cache.get("search", {"query": "b"}) == {"result": "second"}


def test_argument_order_does_not_change_the_key(tmp_path):
    """Keyword arguments arrive in whatever order the caller wrote them."""
    cache = CallCache(tmp_path)
    cache.put("get_lineage", {"urn": "x", "max_hops": 2}, {"ok": True})
    assert cache.get("get_lineage", {"max_hops": 2, "urn": "x"}) == {"ok": True}


def test_a_falsy_response_is_still_a_hit(tmp_path):
    """An empty list is a real answer - "no downstream assets" - and must not be
    mistaken for a cache miss, which in replay mode raises."""
    cache = CallCache(tmp_path)
    cache.put("get_lineage", {"urn": "x"}, [])
    assert cache.get("get_lineage", {"urn": "x"}) == []


def test_replay_reports_a_miss_rather_than_calling_out(tmp_path):
    from fuse.datahub.cache import ReplayMiss

    cache = CallCache(tmp_path, replay=True)
    try:
        cache.get("search", {"query": "missing"})
    except ReplayMiss as exc:
        assert "search" in str(exc)
    else:
        raise AssertionError("replay must not silently return None on a miss")

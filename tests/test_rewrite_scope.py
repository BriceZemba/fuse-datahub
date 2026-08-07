"""Only rewrite consumers that actually read the changed model.

A frozen example once contained `dob as order_date, zipcode as cost_of_delivery`: the
change was on `customers`, the consumer read `orders`, and the prompt handed the model
`customers` columns as "the only columns that will exist". It obeyed a false premise.
"""

from __future__ import annotations

from fuse.nodes.codegen import _consumer_sql, _reads_from
from fuse.state import Impact


def test_a_dbt_ref_counts_as_reading_the_model():
    assert _reads_from("select a from {{ ref('orders') }}", "orders")
    assert _reads_from('select a from {{ ref("orders") }}', "orders")


def test_a_plain_table_reference_counts():
    assert _reads_from("select a from orders", "orders")


def test_an_unrelated_model_does_not_count():
    assert not _reads_from("select a from {{ ref('orders') }}", "customers")


def test_case_is_ignored():
    assert _reads_from("SELECT a FROM {{ REF('ORDERS') }}".lower(), "orders")


def _state(tmp_path, sql: str):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "order_details.sql").write_text(sql, encoding="utf-8")
    return {"repo_path": str(tmp_path), "lineage_graph": {}}


def test_sql_is_returned_when_the_consumer_reads_the_changed_model(tmp_path):
    state = _state(tmp_path, "select order_id from {{ ref('orders') }}")
    impact = Impact(urn="urn:li:dataset:x", entity_type="dataset", name="order_details")
    assert _consumer_sql(state, impact, "orders")


def test_no_sql_when_the_consumer_reads_something_else(tmp_path):
    """This is the case that produced the nonsense: order_details reads orders, but the
    change was on customers."""
    state = _state(tmp_path, "select order_id from {{ ref('orders') }}")
    impact = Impact(urn="urn:li:dataset:x", entity_type="dataset", name="order_details")
    assert _consumer_sql(state, impact, "customers") == ""


def test_without_a_model_the_check_is_skipped(tmp_path):
    """Callers that do not know which model changed still get the SQL."""
    state = _state(tmp_path, "select order_id from {{ ref('orders') }}")
    impact = Impact(urn="urn:li:dataset:x", entity_type="dataset", name="order_details")
    assert _consumer_sql(state, impact)

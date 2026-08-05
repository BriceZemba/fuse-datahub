from fuse.nodes.validate import validate
from fuse.state import Artifact, Change, ResolvedAsset

SCHEMA = [
    {"fieldPath": "order_id"},
    {"fieldPath": "customer_id"},
    {"fieldPath": "order_amount"},
    {"fieldPath": "discount_code"},
]


def _state(sql: str, retries: int = 0):
    change = Change(kind="drop_column", file="orders.sql", model="orders", column="discount_code")
    asset = ResolvedAsset(change=change, urn="urn:li:dataset:test", schema_fields=SCHEMA)
    return {
        "artifacts": [Artifact(path="models/x.sql", kind="dbt_model", content=sql)],
        "resolved": [asset],
        "dialect": "snowflake",
        "retries": retries,
        "trace": [],
    }


def test_hallucinated_column_is_rejected():
    result = validate(_state("select order_id, promo_percentage from orders"))
    assert result["validation_errors"]
    assert "promo_percentage" in result["validation_errors"][0]


def test_dropped_column_cannot_be_reintroduced():
    result = validate(_state("select order_id, discount_code from orders"))
    assert any("removes" in e for e in result["validation_errors"])


def test_a_rewrite_may_not_null_out_the_dropped_column():
    """The failure mode this project exists to prevent: the output shape survives, the
    data is silently null, and no test anywhere fails."""
    state = _state("select order_id, customer_id, null as discount_code from orders")
    result = validate(state)
    assert result["validation_errors"]
    assert "still outputs 'discount_code'" in result["validation_errors"][0]


def test_a_compat_view_may_null_out_the_dropped_column():
    """Same SQL, different intent: preserving the shape is exactly a compat view's job."""
    state = _state("select order_id, customer_id, null as discount_code from orders")
    state["artifacts"][0].kind = "compat_view"
    assert validate(state)["validation_errors"] == []


def test_removing_the_column_outright_passes():
    assert validate(_state("select order_id, customer_id from orders"))[
        "validation_errors"
    ] == []


def _retype_state(sql: str):
    change = Change(
        kind="retype_column", file="orders.sql", model="orders",
        column="order_amount", from_type="DOUBLE", to_type="INT",
    )
    asset = ResolvedAsset(change=change, urn="urn:li:dataset:test", schema_fields=SCHEMA)
    return {
        "artifacts": [Artifact(path="models/x.sql", kind="dbt_model", content=sql)],
        "resolved": [asset],
        "dialect": "snowflake",
        "retries": 0,
        "trace": [],
    }


def test_a_retype_may_not_delete_the_column():
    """A type change is not permission to drop the column — that loses data nobody
    agreed to lose, and it is what the generator actually did before this guard."""
    result = validate(_retype_state("select order_id, customer_id from orders"))
    assert result["validation_errors"]
    assert "only altered its type" in result["validation_errors"][0]


def test_a_retype_that_keeps_the_column_passes():
    sql = "select order_id, customer_id, cast(order_amount as int) as order_amount from orders"
    assert validate(_retype_state(sql))["validation_errors"] == []


def test_clean_sql_passes():
    result = validate(_state("select order_id, customer_id, order_amount from orders"))
    assert result["validation_errors"] == []


def test_local_aliases_are_allowed():
    sql = "with base as (select order_id, order_amount as amt from orders) select amt from base"
    assert validate(_state(sql))["validation_errors"] == []


def test_unparseable_sql_is_rejected():
    assert validate(_state("select from where"))["validation_errors"]


def test_artifacts_are_flagged_after_the_retry_budget():
    result = validate(_state("select order_id, promo_percentage from orders", retries=2))
    assert result["artifacts"][0].needs_human is True

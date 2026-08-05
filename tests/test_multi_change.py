"""A pull request usually touches more than one model.

Before this was fixed, every artifact was generated against `resolved[0]` and validated
against the union of every changed model's schema - so a rewrite of one model could
reference a column that only exists on another, and nothing complained.
"""

from __future__ import annotations

from fuse.nodes.codegen import _allowed_columns
from fuse.nodes.validate import validate
from fuse.state import Artifact, Change, ResolvedAsset

ORDERS = ResolvedAsset(
    change=Change(kind="drop_column", file="orders.sql", model="orders",
                  column="promotion_id"),
    urn="urn:li:dataset:orders",
    schema_fields=[{"fieldPath": f} for f in ("order_id", "promotion_id", "order_total")],
)
CUSTOMERS = ResolvedAsset(
    change=Change(kind="drop_column", file="customers.sql", model="customers",
                  column="credit_limit"),
    urn="urn:li:dataset:customers",
    schema_fields=[{"fieldPath": f} for f in ("customer_id", "credit_limit", "region_id")],
)


def test_allowed_columns_are_scoped_to_one_asset():
    assert _allowed_columns(ORDERS) == ["order_id", "order_total"]
    assert _allowed_columns(CUSTOMERS) == ["customer_id", "region_id"]


def _state(artifact: Artifact):
    return {
        "artifacts": [artifact],
        "resolved": [ORDERS, CUSTOMERS],
        "dialect": "snowflake",
        "retries": 0,
        "trace": [],
    }


def test_a_column_from_another_changed_model_is_rejected():
    artifact = Artifact(
        path="models/x.sql",
        kind="dbt_model",
        content="select order_id, region_id from orders",
        source_urn=ORDERS.urn,
    )
    errors = validate(_state(artifact))["validation_errors"]
    assert any("region_id" in e for e in errors)


def test_each_artifact_is_checked_against_its_own_model():
    artifact = Artifact(
        path="models/y.sql",
        kind="dbt_model",
        content="select customer_id, region_id from customers",
        source_urn=CUSTOMERS.urn,
    )
    assert validate(_state(artifact))["validation_errors"] == []


def test_the_right_column_is_treated_as_dropped_per_model():
    """`credit_limit` is dropped from customers, not from orders - an orders artifact
    that mentions it should fail on the unknown column, not pass by coincidence."""
    artifact = Artifact(
        path="models/z.sql",
        kind="dbt_model",
        content="select order_id, credit_limit from orders",
        source_urn=ORDERS.urn,
    )
    assert validate(_state(artifact))["validation_errors"]

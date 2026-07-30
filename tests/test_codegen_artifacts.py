"""The generated files are the deliverable, so their shape is tested like code."""

from __future__ import annotations

import pytest

from fuse.nodes.codegen import _consumers_for, _template
from fuse.nodes.validate import validate
from fuse.state import Artifact, Change, Impact, ResolvedAsset

COLUMNS = ["customer_id", "customer_class", "country_id"]


def impact(name: str, severity: str = "BREAKING") -> Impact:
    return Impact(urn=f"urn:li:test:{name}", entity_type="mlFeature", name=name,
                  severity=severity, score=90)


def test_the_changed_column_is_not_listed_as_its_own_consumer():
    impacts = [impact("credit_limit"), impact("Customer Churn Model v3")]
    plan = {i.urn: "add_compat_view" for i in impacts}
    names, more = _consumers_for(impacts, plan, "add_compat_view", "credit_limit")
    assert names == ["Customer Churn Model v3"]
    assert more == 0


def test_long_consumer_lists_are_truncated_with_a_count():
    impacts = [impact(f"consumer_{n}") for n in range(10)]
    plan = {i.urn: "add_compat_view" for i in impacts}
    names, more = _consumers_for(impacts, plan, "add_compat_view", None)
    assert len(names) == 6
    assert more == 4


@pytest.fixture
def compat_sql() -> str:
    return _template(
        "compat_view.sql.j2",
        model="customers",
        column="credit_limit",
        consumers=["Customer Churn Model v3"],
        more=0,
        columns=COLUMNS,
        dialect="snowflake",
    )


def test_compat_view_preserves_the_dropped_column_as_null(compat_sql):
    assert "null as credit_limit" in compat_sql
    assert "ref('customers')" in compat_sql


def test_compat_view_has_no_dangling_comma(compat_sql):
    body = compat_sql.split("select", 1)[1]
    assert "\n    ," not in body
    assert ",\n    null as credit_limit" in body


def test_generated_compat_view_passes_validation(compat_sql):
    """The template emits dbt Jinja; validation has to see through it rather than
    reject the file for templating it cannot parse."""
    change = Change(kind="drop_column", file="customers.sql", model="customers",
                    column="credit_limit")
    asset = ResolvedAsset(
        change=change,
        urn="urn:li:dataset:test",
        schema_fields=[{"fieldPath": c} for c in COLUMNS],
    )
    result = validate({
        "artifacts": [Artifact(path="models/compat/customers_compat.sql",
                               kind="compat_view", content=compat_sql)],
        "resolved": [asset],
        "dialect": "snowflake",
        "retries": 0,
        "trace": [],
    })
    assert result["validation_errors"] == []

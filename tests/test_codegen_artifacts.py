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
        kind="drop_column",
        from_type=None,
        to_type=None,
        consumers=["Customer Churn Model v3"],
        more=0,
        columns=COLUMNS,
        dialect="snowflake",
    )


@pytest.fixture
def retype_compat_sql() -> str:
    return _template(
        "compat_view.sql.j2",
        model="orders",
        column="order_total",
        kind="retype_column",
        from_type="DOUBLE",
        to_type="INT",
        consumers=["order_history"],
        more=0,
        columns=COLUMNS,
        dialect="snowflake",
    )


def test_a_retype_compat_view_holds_the_old_type(retype_compat_sql):
    """The one place casting back is right: a shim that exists so consumers can migrate.
    Nulling the column, as the drop-column shim does, would be nonsense here."""
    assert "cast(order_total as DOUBLE) as order_total" in retype_compat_sql
    assert "null as order_total" not in retype_compat_sql


def test_no_compat_view_emits_a_column_twice(compat_sql, retype_compat_sql):
    """The changed column is re-added by the template, so it must not also appear in
    the column list - that produced SQL with a duplicate output column."""
    for sql in (compat_sql, retype_compat_sql):
        body = sql.split("select", 1)[1]
        names = [line.strip().rstrip(",") for line in body.splitlines() if line.startswith("    ")]
        bare = [n.split(" as ")[-1] for n in names if n]
        assert len(bare) == len(set(bare)), f"duplicate output column in:\n{sql}"


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

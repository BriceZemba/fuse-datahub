from fuse.nodes.parse_change import (
    apply_hunks,
    diff_model,
    output_columns,
    parse_unified_diff,
    strip_jinja,
)

ORDERS_BEFORE = """{{ config(materialized='table') }}

with source as (

    select * from {{ ref('stg_orders') }}

)

select
    order_id,
    customer_id,
    order_date,
    status,
    discount_code,
    cast(amount as float) as order_amount
from source
"""

ORDERS_AFTER = ORDERS_BEFORE.replace("    discount_code,\n", "")


def test_strip_jinja_makes_dbt_parseable():
    cleaned = strip_jinja(ORDERS_BEFORE)
    assert "{{" not in cleaned
    assert "stg_orders" in cleaned


def test_output_columns_reads_the_final_projection():
    columns = output_columns(ORDERS_BEFORE)
    assert "discount_code" in columns
    # sqlglot canonicalises snowflake FLOAT to DOUBLE — types are compared after
    # normalisation, so the risk engine sees a stable vocabulary.
    assert columns["order_amount"] == "DOUBLE"


def test_drop_column_is_detected():
    changes = diff_model(
        ORDERS_BEFORE, ORDERS_AFTER, file="models/marts/orders.sql", model="orders",
        dialect="snowflake",
    )
    assert [c.kind for c in changes] == ["drop_column"]
    assert changes[0].column == "discount_code"


def test_rename_is_not_reported_as_a_drop():
    renamed = ORDERS_BEFORE.replace("    discount_code,", "    discount_code as promo_code,")
    changes = diff_model(
        ORDERS_BEFORE, renamed, file="models/marts/orders.sql", model="orders",
        dialect="snowflake",
    )
    assert [c.kind for c in changes] == ["rename_column"]
    assert changes[0].column == "discount_code"
    assert changes[0].renamed_to == "promo_code"


def test_retype_is_detected():
    retyped = ORDERS_BEFORE.replace("as float", "as int")
    changes = diff_model(
        ORDERS_BEFORE, retyped, file="models/marts/orders.sql", model="orders",
        dialect="snowflake",
    )
    assert [c.kind for c in changes] == ["retype_column"]
    assert (changes[0].from_type, changes[0].to_type) == ("DOUBLE", "INT")


def test_patch_applies_in_memory():
    patch = """diff --git a/models/marts/orders.sql b/models/marts/orders.sql
--- a/models/marts/orders.sql
+++ b/models/marts/orders.sql
@@ -11,6 +11,5 @@
     customer_id,
     order_date,
     status,
-    discount_code,
     cast(amount as float) as order_amount
 from source
"""
    files = parse_unified_diff(patch)
    assert len(files) == 1 and files[0].path == "models/marts/orders.sql"
    after = apply_hunks(ORDERS_BEFORE.splitlines(), files[0].hunks)
    assert "    discount_code," not in after
    assert "    order_id," in after

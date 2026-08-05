"""Probing the diff parser with shapes a real repository actually contains.

Written to find defects, not to confirm the happy path.
"""

from __future__ import annotations

from fuse.nodes.parse_change import (
    apply_hunks,
    diff_model,
    output_columns,
    parse_unified_diff,
    strip_jinja,
)

BASE = """{{ config(materialized='table') }}

select
    order_id,
    customer_id,
    order_total
from {{ ref('stg_orders') }}
"""


def test_select_star_yields_no_output_columns():
    """A model that selects * has no enumerable projection. Whatever the parser does
    here, it must not claim columns were dropped."""
    star = "select * from {{ ref('stg_orders') }}"
    assert output_columns(star) == {}

    changes = diff_model(star, BASE, file="f.sql", model="orders", dialect="snowflake")
    assert all(c.kind != "drop_column" for c in changes)


def test_changing_from_explicit_columns_to_star_is_not_reported_as_dropping_everything():
    star = "select * from {{ ref('stg_orders') }}"
    changes = diff_model(BASE, star, file="f.sql", model="orders", dialect="snowflake")
    assert [c.kind for c in changes] == [], f"unexpected: {[c.describe() for c in changes]}"


def test_a_jinja_if_block_does_not_break_parsing():
    templated = """select
    order_id,
    {% if target.name == 'prod' %}
    customer_id,
    {% endif %}
    order_total
from {{ ref('stg_orders') }}
"""
    cleaned = strip_jinja(templated)
    assert "{%" not in cleaned
    assert output_columns(templated)


def test_case_differences_are_not_a_rename():
    upper = BASE.replace("order_total", "ORDER_TOTAL")
    changes = diff_model(BASE, upper, file="f.sql", model="orders", dialect="snowflake")
    kinds = {c.kind for c in changes}
    assert "drop_column" not in kinds, f"case-only change reported as a drop: {kinds}"


def test_two_files_in_one_diff_are_both_parsed():
    patch = """diff --git a/models/a.sql b/models/a.sql
--- a/models/a.sql
+++ b/models/a.sql
@@ -1,3 +1,2 @@
 select
-    dropped_one,
     kept
diff --git a/models/b.sql b/models/b.sql
--- a/models/b.sql
+++ b/models/b.sql
@@ -1,3 +1,2 @@
 select
-    dropped_two,
     kept
"""
    files = parse_unified_diff(patch)
    assert [f.path for f in files] == ["models/a.sql", "models/b.sql"]


def test_a_newly_added_file_is_handled():
    """A PR that adds a model has no 'before'. Nothing should be reported as dropped."""
    patch = """diff --git a/models/new.sql b/models/new.sql
new file mode 100644
--- /dev/null
+++ b/models/new.sql
@@ -0,0 +1,2 @@
+select order_id
+from orders
"""
    files = parse_unified_diff(patch)
    assert len(files) == 1
    after = apply_hunks([], files[0].hunks)
    assert "select order_id" in "\n".join(after)


def test_hunks_apply_at_the_right_offset():
    before = [f"line{n}" for n in range(1, 11)]
    patch = """--- a/f.sql
+++ b/f.sql
@@ -5,3 +5,2 @@
 line5
-line6
 line7
"""
    hunks = parse_unified_diff(patch)[0].hunks
    after = apply_hunks(before, hunks)
    assert "line6" not in after
    assert after[:5] == ["line1", "line2", "line3", "line4", "line5"]
    assert after[-3:] == ["line8", "line9", "line10"]


def test_a_diff_touching_no_sql_is_empty():
    patch = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,2 +1,1 @@
 # Title
-removed line
"""
    files = parse_unified_diff(patch)
    assert [f for f in files if f.path.endswith(".sql")] == []

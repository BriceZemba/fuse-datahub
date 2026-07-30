"""Open-weight models rarely return bare JSON, so the parser has to cope."""

from __future__ import annotations

from fuse.nodes.plan import _extract_json

URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,db.orders,PROD)"


def test_bare_json():
    assert _extract_json(f'{{"{URN}": "rewrite_sql"}}') == {URN: "rewrite_sql"}


def test_markdown_fences():
    text = f'```json\n{{"{URN}": "rewrite_sql"}}\n```'
    assert _extract_json(text) == {URN: "rewrite_sql"}


def test_reasoning_before_the_answer():
    text = (
        "Let me think. The consumer reads the column {so it breaks} and the repo has "
        f'its SQL, so a rewrite is right.\n\n{{"{URN}": "rewrite_sql"}}'
    )
    assert _extract_json(text) == {URN: "rewrite_sql"}


def test_commentary_after_the_answer():
    text = f'{{"{URN}": "add_compat_view"}}\n\nThis keeps the old shape available.'
    assert _extract_json(text) == {URN: "add_compat_view"}


def test_braces_inside_strings_do_not_confuse_it():
    text = '{"a": "value with { brace", "b": "another }"}'
    assert _extract_json(text) == {"a": "value with { brace", "b": "another }"}


def test_no_json_at_all():
    assert _extract_json("I cannot help with that.") is None


def test_empty_object_is_not_an_answer():
    assert _extract_json("{}") is None

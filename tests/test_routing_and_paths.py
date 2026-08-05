"""Graph routing, artifact paths and shape parsing under hostile input.

The model name and file path both originate outside Fuse — a diff, a catalog entity, or
a language model's output — so they are untrusted input that ends up in a filesystem
path.
"""

from __future__ import annotations

from pathlib import Path

from fuse.datahub import shapes
from fuse.graph import route_after_impact, route_after_validate
from fuse.nodes.pr import emit_pr
from fuse.state import Artifact, Impact

# --------------------------------------------------------------------------- routing


def test_safe_changes_skip_generation():
    assert route_after_impact({"max_severity": "SAFE"}) == "safe"


def test_risky_and_breaking_generate():
    assert route_after_impact({"max_severity": "RISKY"}) == "act"
    assert route_after_impact({"max_severity": "BREAKING"}) == "act"


def test_a_missing_severity_is_treated_as_safe():
    assert route_after_impact({}) == "safe"


def test_clean_validation_proceeds():
    assert route_after_validate({"validation_errors": [], "retries": 1}) == "ok"


def test_errors_retry_until_the_budget_is_spent():
    assert route_after_validate({"validation_errors": ["e"], "retries": 0}) == "retry"
    assert route_after_validate({"validation_errors": ["e"], "retries": 1}) == "retry"
    assert route_after_validate({"validation_errors": ["e"], "retries": 2}) == "giveup"


def test_the_retry_budget_cannot_loop_forever():
    assert route_after_validate({"validation_errors": ["e"], "retries": 99}) == "giveup"


# ----------------------------------------------------------------------- file paths


def test_artifacts_cannot_escape_the_output_directory(tmp_path, monkeypatch):
    """A model name is catalog data and a file path comes from a diff. Neither is
    trusted, and both reach a filesystem write."""
    from fuse.config import settings

    monkeypatch.setattr(settings, "out_dir", tmp_path / "out")
    state = {
        "run_id": "run",
        "max_severity": "BREAKING",
        "impacts": [],
        "artifacts": [
            Artifact(path="../../escaped.sql", kind="dbt_model", content="select 1 as a"),
            Artifact(path="/etc/passwd", kind="dbt_model", content="select 1 as a"),
        ],
        "plan": {},
        "trace": [],
    }
    emit_pr(state)

    assert not (tmp_path / "escaped.sql").exists(), "an artifact escaped the run directory"
    assert not Path("/etc/passwd_fuse").exists()
    written = list((tmp_path / "out").rglob("*.sql"))
    assert written, "the artifacts should still be written, just contained"
    for path in written:
        assert (tmp_path / "out") in path.parents


# --------------------------------------------------------------------------- shapes


def test_shape_readers_tolerate_empty_payloads():
    for payload in (None, {}, [], "", {"unexpected": "shape"}):
        assert shapes.search_results(payload) == []
        assert shapes.lineage_results(payload) == []
        assert shapes.entities(payload) == []
        assert shapes.schema_fields(payload) == []
        assert shapes.queries(payload) == []


def test_entity_helpers_tolerate_missing_sections():
    entity = {"urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,db.t,PROD)"}
    assert shapes.owners_of(entity) == []
    assert shapes.tag_names(entity) == []
    assert shapes.term_names(entity) == []
    assert shapes.tier_of(entity) is None
    assert shapes.entity_type(entity) == "dataset"
    assert shapes.entity_name(entity) == "t"


def test_a_lineage_result_without_an_entity_is_skipped():
    payload = {"downstreams": {"searchResults": [{"degree": 1}, {"entity": {}}]}}
    assert shapes.lineage_results(payload) == []


def test_impact_names_do_not_need_sanitising_to_be_read():
    impact = Impact(urn="urn:li:dataset:x", entity_type="dataset", name="Order Details")
    assert impact.name == "Order Details"

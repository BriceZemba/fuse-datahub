"""ML traversal against a malformed or partial catalog, and CLI exit codes.

A feature store assembled by several teams contains dangling references, features with
no declared source, and entities the search index knows about but the aspect store does
not. None of that should crash a run or invent a dependency.
"""

from __future__ import annotations

from typer.testing import CliRunner

from fuse.cli import app
from fuse.datahub import ml_graph
from fuse.state import FuseState

DATASET = "urn:li:dataset:(urn:li:dataPlatform:dbt,db.s.customers,PROD)"
FEATURE = "urn:li:mlFeature:(ns,credit_limit)"
MISSING = "urn:li:mlFeature:(ns,deleted_feature)"
TABLE = "urn:li:mlFeatureTable:(urn:li:dataPlatform:feast,t)"
MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,m,PROD)"
DEPLOYMENT = "urn:li:mlModelDeployment:(urn:li:dataPlatform:mlflow,d,PROD)"

runner = CliRunner()


def test_a_feature_with_no_sources_is_not_reachable():
    catalog = [{"urn": FEATURE, "properties": {}}]
    assert ml_graph.dependents_of(DATASET, catalog) == []


def test_a_feature_with_empty_properties_does_not_crash():
    catalog = [{"urn": FEATURE}, {"urn": TABLE}, {"urn": MODEL}]
    assert ml_graph.dependents_of(DATASET, catalog) == []


def test_a_table_referencing_a_deleted_feature_is_ignored():
    """Dangling references are normal in a feature store several teams maintain."""
    catalog = [
        {"urn": FEATURE, "properties": {"sources": [DATASET]}},
        {"urn": TABLE, "properties": {"mlFeatures": [MISSING]}},
    ]
    found = {e["urn"] for e, _ in ml_graph.dependents_of(DATASET, catalog)}
    assert found == {FEATURE}, "a table that reads a different feature is not affected"


def test_a_model_deployment_absent_from_the_catalog_is_still_reported():
    """The deployment is what serves traffic. If a model names one, report it even when
    the search index never returned it — which is exactly what DataHub does."""
    catalog = [
        {"urn": FEATURE, "properties": {"sources": [DATASET]}},
        {"urn": MODEL, "properties": {"mlFeatures": [FEATURE], "deployments": [DEPLOYMENT]}},
    ]
    found = {e["urn"]: hops for e, hops in ml_graph.dependents_of(DATASET, catalog)}
    assert found[DEPLOYMENT] == 3


def test_duplicate_entities_are_collapsed():
    feature = {"urn": FEATURE, "properties": {"sources": [DATASET]}}
    found = ml_graph.dependents_of(DATASET, [feature, dict(feature)])
    assert len(found) == 1


def test_an_entity_without_a_urn_is_skipped():
    catalog = [{"properties": {"sources": [DATASET]}}, {"urn": FEATURE,
                                                        "properties": {"sources": [DATASET]}}]
    found = [e["urn"] for e, _ in ml_graph.dependents_of(DATASET, catalog)]
    assert found == [FEATURE]


def test_a_self_referencing_table_terminates():
    """A table listing itself would loop a naive traversal."""
    catalog = [
        {"urn": FEATURE, "properties": {"sources": [DATASET]}},
        {"urn": TABLE, "properties": {"mlFeatures": [FEATURE, TABLE]}},
    ]
    found = {e["urn"] for e, _ in ml_graph.dependents_of(DATASET, catalog)}
    assert found == {FEATURE, TABLE}


# ------------------------------------------------------------------- CLI exit codes


def _fake_run(result: FuseState):
    async def run(state, *, replay, dry_run, auto_approve):
        return {**state, **result}

    return run


def test_breaking_fails_the_build(monkeypatch, tmp_path):
    monkeypatch.setattr("fuse.cli._run", _fake_run({"max_severity": "BREAKING",
                                                    "impacts": [], "artifacts": []}))
    result = runner.invoke(app, ["check", "--repo", str(tmp_path), "--auto-approve"])
    assert result.exit_code == 1


def test_safe_passes_the_build(monkeypatch, tmp_path):
    monkeypatch.setattr("fuse.cli._run", _fake_run({"max_severity": "SAFE",
                                                    "impacts": [], "artifacts": []}))
    result = runner.invoke(app, ["check", "--repo", str(tmp_path), "--auto-approve"])
    assert result.exit_code == 0


def test_fail_on_risky_catches_risky(monkeypatch, tmp_path):
    monkeypatch.setattr("fuse.cli._run", _fake_run({"max_severity": "RISKY",
                                                    "impacts": [], "artifacts": []}))
    result = runner.invoke(
        app, ["check", "--repo", str(tmp_path), "--auto-approve", "--fail-on", "RISKY"]
    )
    assert result.exit_code == 1


def test_an_unknown_fail_on_value_does_not_crash(monkeypatch, tmp_path):
    """A typo in CI config should not take the build down with a traceback."""
    monkeypatch.setattr("fuse.cli._run", _fake_run({"max_severity": "SAFE",
                                                    "impacts": [], "artifacts": []}))
    result = runner.invoke(
        app, ["check", "--repo", str(tmp_path), "--auto-approve", "--fail-on", "nonsense"]
    )
    assert result.exit_code == 0
    assert "Traceback" not in result.stdout


def test_replaying_a_missing_example_reports_clearly(tmp_path):
    result = runner.invoke(app, ["replay", str(tmp_path / "does-not-exist")])
    assert result.exit_code != 0
    assert "Traceback" not in result.stdout

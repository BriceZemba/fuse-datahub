"""`fuse revert` is promised in every generated MIGRATION.md, so it has to work."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from fuse.cli import app

runner = CliRunner()


def _manifest(tmp_path, **overrides):
    record = {
        "run_id": "fuse-test",
        "dry_run": False,
        "tagged": ["urn:li:dataset:a", "urn:li:dataset:b"],
        "properties_set": ["urn:li:dataset:a"],
        "described": [],
        "document_urn": "urn:li:document:xyz",
        "errors": [],
    }
    record.update(overrides)
    run_dir = tmp_path / "fuse-test"
    run_dir.mkdir()
    (run_dir / "writeback.json").write_text(json.dumps(record), encoding="utf-8")
    return run_dir


def test_missing_manifest_is_a_clear_error(tmp_path):
    result = runner.invoke(app, ["revert", str(tmp_path)])
    assert result.exit_code == 1
    assert "No writeback.json" in result.stdout


def test_a_dry_run_has_nothing_to_revert(tmp_path):
    run_dir = _manifest(tmp_path, dry_run=True)
    result = runner.invoke(app, ["revert", str(run_dir)])
    assert result.exit_code == 0
    assert "dry run" in result.stdout


def test_an_empty_run_has_nothing_to_revert(tmp_path):
    run_dir = _manifest(tmp_path, tagged=[], properties_set=[])
    result = runner.invoke(app, ["revert", str(run_dir)])
    assert result.exit_code == 0
    assert "Nothing to revert" in result.stdout


def test_the_manifest_can_be_passed_directly(tmp_path):
    run_dir = _manifest(tmp_path, dry_run=True)
    result = runner.invoke(app, ["revert", str(run_dir / "writeback.json")])
    assert result.exit_code == 0

"""Every frozen example must have the same shape.

Judges read these folders directly, so a nested `generated/<name>/<name>/` or a missing
report is a submission-quality defect, not a cosmetic one. A refactor of `fuse freeze`
silently produced exactly that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
REQUIRED = ("diff.patch", "README.md", "PR_BODY.md", "impact-report.md", "run.log")


def example_dirs() -> list[Path]:
    if not EXAMPLES.exists():
        return []
    return sorted(p for p in EXAMPLES.iterdir() if (p / "fixtures").is_dir())


@pytest.mark.skipif(not example_dirs(), reason="no frozen examples committed yet")
@pytest.mark.parametrize("folder", example_dirs(), ids=lambda p: p.name)
def test_example_has_the_expected_files(folder: Path):
    for name in REQUIRED:
        assert (folder / name).is_file(), f"{folder.name}/{name} is missing"
    assert (folder / "repo").is_dir()
    assert (folder / "generated").is_dir()


@pytest.mark.skipif(not example_dirs(), reason="no frozen examples committed yet")
@pytest.mark.parametrize("folder", example_dirs(), ids=lambda p: p.name)
def test_generated_is_not_nested_under_a_run_id(folder: Path):
    nested = folder / "generated" / folder.name
    assert not nested.exists(), (
        f"{folder.name}/generated/{folder.name}/ - the run id leaked into the layout"
    )


@pytest.mark.skipif(not example_dirs(), reason="no frozen examples committed yet")
@pytest.mark.parametrize("folder", example_dirs(), ids=lambda p: p.name)
def test_generated_contains_something(folder: Path):
    produced = [p for p in (folder / "generated").rglob("*") if p.is_file()]
    assert produced, f"{folder.name} generated no artifacts"


@pytest.mark.skipif(not example_dirs(), reason="no frozen examples committed yet")
def test_no_staging_directory_was_committed():
    assert not list(EXAMPLES.glob("*.staging")), "a failed freeze left a staging folder"

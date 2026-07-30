"""The offline replay is what a judge runs, so CI runs it too.

Every committed example must reproduce from its recorded fixtures with no DataHub, no
network and no API key. If a change breaks that, this fails rather than the judge.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fuse.config import settings
from fuse.datahub.mcp_client import DataHubMCP
from fuse.graph import build_graph
from fuse.runtime import RT
from fuse.state import FuseState

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def example_dirs() -> list[Path]:
    if not EXAMPLES.exists():
        return []
    return sorted(p for p in EXAMPLES.iterdir() if (p / "fixtures").is_dir())


async def run_example(folder: Path) -> FuseState:
    settings.fixtures_dir = folder / "fixtures"
    settings.out_dir = Path(".pytest-out")
    state: FuseState = {
        "repo_path": str(folder / "repo"),
        "diff": str(folder / "diff.patch"),
        "dialect": settings.dialect,
        "hops": settings.hops,
        "run_id": f"test-{folder.name}",
        "replay": True,
        "trace": [],
    }
    async with DataHubMCP(fixtures=folder / "fixtures", replay=True, dry_run=True) as dh:
        RT.dh = dh
        RT.llm = None
        RT.dry_run = True
        graph = build_graph(interrupt_before_writeback=False)
        return await graph.ainvoke(
            state, config={"configurable": {"thread_id": state["run_id"]}}
        )


@pytest.mark.skipif(not example_dirs(), reason="no frozen examples committed yet")
@pytest.mark.parametrize("folder", example_dirs(), ids=lambda p: p.name)
def test_example_replays_offline(folder: Path):
    result = asyncio.run(run_example(folder))

    assert result.get("changes"), f"{folder.name}: no change parsed from the diff"
    assert result.get("impacts"), f"{folder.name}: no downstream impact found"
    assert result.get("max_severity") in {"SAFE", "RISKY", "BREAKING"}


@pytest.mark.skipif(not example_dirs(), reason="no frozen examples committed yet")
def test_the_ml_example_reaches_a_deployed_model():
    """The claim the project rests on: a dbt column change reaches a model in
    production through a path DataHub's lineage does not expose."""
    folder = EXAMPLES / "03-ml-feature-break"
    if not (folder / "fixtures").is_dir():
        pytest.skip("ML example not frozen")

    result = asyncio.run(run_example(folder))
    types = {i.entity_type for i in result["impacts"]}
    assert "mlFeature" in types
    assert "mlModel" in types
    assert result["max_severity"] == "BREAKING"

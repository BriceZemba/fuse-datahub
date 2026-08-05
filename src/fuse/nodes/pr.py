"""Node 9 — assemble what a reviewer actually sees.

Writes every artifact plus a PR body under out/<run_id>/. In CI the same body is
posted as a review comment by .github/workflows/fuse.yml.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from fuse.config import settings
from fuse.state import Artifact, FuseState, Impact

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)

BANNER = {
    "BREAKING": "🔴 **BREAKING** — merging this will break downstream consumers",
    "RISKY": "🟠 **RISKY** — downstream consumers need attention",
    "SAFE": "🟢 **SAFE** — no downstream consumer references the changed column",
}


def _contained(out_dir: Path, relative: str) -> Path:
    """Resolve an artifact path, refusing to leave the run directory.

    Artifact paths are built from names that came out of a diff and out of the catalog,
    and Fuse runs in CI against untrusted pull requests. A model called `../../id_rsa`
    would otherwise write wherever the runner can reach.
    """
    candidate = PurePosixPath(relative.replace("\\", "/"))
    parts = [
        part
        for part in candidate.parts
        if part not in ("..", "/", "") and not part.endswith(":")
    ]
    if not parts:
        parts = ["artifact"]

    target = (out_dir / Path(*parts)).resolve()
    root = out_dir.resolve()
    if root != target and root not in target.parents:
        # Nothing should reach this after stripping, but a symlinked out_dir or an
        # exotic path could; flatten rather than write outside.
        target = root / "_".join(parts)
    return target


def emit_pr(state: FuseState) -> dict:
    run_id = state.get("run_id", "local")
    out_dir = settings.out_dir / run_id
    artifacts: list[Artifact] = state.get("artifacts", [])
    impacts: list[Impact] = state.get("impacts", [])
    trace = list(state.get("trace", []))

    body = env.get_template("pr_body.md.j2").render(
        banner=BANNER[state.get("max_severity", "SAFE")],
        severity=state.get("max_severity", "SAFE"),
        change=impacts[0].source_change if impacts else "n/a",
        impacts=impacts,
        artifacts=artifacts,
        plan=state.get("plan", {}),
        writeback=state.get("writeback"),
        trace=trace,
        gms_url=settings.gms_url,
    )
    artifacts = artifacts + [Artifact(path="PR_BODY.md", kind="pr_body", content=body)]
    if state.get("report_md"):
        artifacts.append(
            Artifact(path="impact-report.md", kind="impact_report", content=state["report_md"])
        )

    for artifact in artifacts:
        target = _contained(out_dir, artifact.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(artifact.content, encoding="utf-8")

    (out_dir / "run.log").write_text("\n".join(trace) + "\n", encoding="utf-8")

    # A machine-readable record of what was written to DataHub, so `fuse revert` can
    # undo exactly this run rather than guessing from tags.
    writeback = state.get("writeback")
    if writeback is not None:
        (out_dir / "writeback.json").write_text(
            json.dumps(writeback.model_dump(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    trace.append(f"pr: wrote {len(artifacts)} file(s) to {out_dir}")
    return {"artifacts": artifacts, "trace": trace}

"""Node 8 — record the verdict in DataHub.

Without this step Fuse is a linter. With it, the catalog learns: the next agent that
asks DataHub about this table finds the blast-radius score, the tag, and the full
impact report already there. Writes are idempotent and `fuse revert` undoes the tags.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fuse.runtime import RT
from fuse.state import FuseState, Impact, WriteBackResult

TAG_PENDING = "urn:li:tag:fuse-pending-breaking-change"
TAG_SAFE = "urn:li:tag:fuse-verified-safe"


def _report_markdown(state: FuseState) -> str:
    impacts: list[Impact] = state.get("impacts", [])
    lines = [
        f"# Fuse impact report — {state.get('run_id', 'local')}",
        "",
        f"**Change:** {impacts[0].source_change if impacts else 'n/a'}  ",
        f"**Max severity:** {state.get('max_severity', 'SAFE')}  ",
        f"**Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "| Asset | Type | Hops | Severity | Score | Evidence | Owners |",
        "|---|---|---|---|---|---|---|",
    ]
    for i in impacts:
        lines.append(
            f"| {i.name} | {i.entity_type} | {i.hops} | **{i.severity}** | {i.score} | "
            f"{'; '.join(i.evidence) or '—'} | {', '.join(i.owners) or '—'} |"
        )
    lines += ["", "## Why these scores", ""]
    for i in impacts:
        lines.append(f"- **{i.name}** ({i.score}): " + "; ".join(i.reasons))
    return "\n".join(lines) + "\n"


async def write_back(state: FuseState) -> dict:
    dh = RT.require_dh()
    impacts: list[Impact] = state.get("impacts", [])
    run_id = state.get("run_id", "local")
    result = WriteBackResult(run_id=run_id)
    trace = list(state.get("trace", []))
    report = _report_markdown(state)

    breaking = [i for i in impacts if i.severity in {"BREAKING", "RISKY"}]
    tag = TAG_PENDING if breaking else TAG_SAFE

    for impact in breaking or impacts:
        try:
            await dh.call("add_tags", urn=impact.urn, tag_urns=[tag])
            result.tagged.append(impact.urn)
            await dh.call(
                "add_structured_properties",
                urn=impact.urn,
                properties={
                    "fuse.blast_radius_score": impact.score,
                    "fuse.severity": impact.severity,
                    "fuse.last_checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "fuse.run_id": run_id,
                },
            )
            result.properties_set.append(impact.urn)
        except Exception as exc:
            result.errors.append(f"{impact.urn}: {exc.__class__.__name__}: {exc}")

    # Annotate the changed asset itself so the deprecation is visible where people look.
    for asset in state.get("resolved", []):
        if asset.change.kind in {"drop_column", "rename_column"} and asset.change.column:
            try:
                await dh.call(
                    "update_description",
                    urn=asset.urn,
                    description=(
                        f"[Fuse] `{asset.change.column}` is being removed by run {run_id}. "
                        f"{len(breaking)} downstream asset(s) affected. See the Fuse impact report."
                    ),
                )
                result.described.append(asset.urn)
            except Exception as exc:
                result.errors.append(f"{asset.urn}: {exc.__class__.__name__}: {exc}")

    try:
        saved = await dh.call(
            "save_document",
            title=f"Fuse impact report — {run_id}",
            content=report,
        )
        result.document_urn = saved.get("urn") if isinstance(saved, dict) else None
    except Exception as exc:
        result.errors.append(f"save_document: {exc.__class__.__name__}: {exc}")

    trace.append(
        f"writeback: tagged {len(result.tagged)}, described {len(result.described)}, "
        f"document {'saved' if result.document_urn else 'not saved'}"
        + (f", {len(result.errors)} error(s)" if result.errors else "")
    )
    return {"writeback": result, "report_md": report, "trace": trace}

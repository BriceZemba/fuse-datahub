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
    targets = breaking or impacts
    tag = TAG_PENDING if breaking else TAG_SAFE

    # add_tags takes a list of entities, so the whole blast radius is one call.
    if targets:
        try:
            await dh.call("add_tags", tag_urns=[tag], entity_urns=[i.urn for i in targets])
            result.tagged = [i.urn for i in targets]
        except Exception as exc:
            result.errors.append(f"add_tags: {exc.__class__.__name__}: {exc}")

        # Structured properties need the property definition registered up front; if the
        # instance has not been bootstrapped for it, this is a warning, not a failure.
        try:
            await dh.call(
                "add_structured_properties",
                property_values=[
                    {"propertyUrn": "urn:li:structuredProperty:fuse.blast_radius_score",
                     "values": [max(i.score for i in targets)]},
                    {"propertyUrn": "urn:li:structuredProperty:fuse.severity",
                     "values": [state.get("max_severity", "SAFE")]},
                    {"propertyUrn": "urn:li:structuredProperty:fuse.run_id",
                     "values": [run_id]},
                    {"propertyUrn": "urn:li:structuredProperty:fuse.last_checked",
                     "values": [datetime.now(timezone.utc).isoformat(timespec="seconds")]},
                ],
                entity_urns=[i.urn for i in targets],
            )
            result.properties_set = [i.urn for i in targets]
        except Exception as exc:
            result.errors.append(f"add_structured_properties: {exc.__class__.__name__}: {exc}")

    # Annotate the exact column being removed, where an engineer will actually see it.
    for asset in state.get("resolved", []):
        if asset.change.kind in {"drop_column", "rename_column"} and asset.change.column:
            try:
                await dh.call(
                    "update_description",
                    entity_urn=asset.urn,
                    column_path=asset.change.column,
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
            related_assets=[i.urn for i in impacts],
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

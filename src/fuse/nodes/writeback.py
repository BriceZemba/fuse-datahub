"""Node 8 — record the verdict in DataHub.

Without this step Fuse is a linter. With it, the catalog learns: the next agent that
asks DataHub about this table finds the blast-radius score, the tag, and the full
impact report already there. Writes are idempotent and `fuse revert` undoes the tags.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fuse.runtime import RT
from fuse.state import FuseState, Impact, WriteBackResult

TAG_PENDING = "urn:li:tag:fuse-pending-breaking-change"
TAG_SAFE = "urn:li:tag:fuse-verified-safe"
WRITEBACK_TAGS = (TAG_PENDING, TAG_SAFE)
DOCUMENT_TYPE = "Analysis"

FUSE_PROPERTY_URNS = (
    "urn:li:structuredProperty:fuse.blast_radius_score",
    "urn:li:structuredProperty:fuse.severity",
    "urn:li:structuredProperty:fuse.run_id",
    "urn:li:structuredProperty:fuse.last_checked",
)


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


URN_IN_TEXT = re.compile(r"urn:li:[a-zA-Z]+:[^\s\"',)]+")
ERROR_MARKERS = ("validation error", "error", "invalid", "traceback")


def _document_urn(saved: object) -> str | None:
    """Find the created document's URN in whatever shape the tool answered with.

    MCP tools often reply with a text blob rather than structured JSON, so a plain
    key lookup is not enough.
    """
    if isinstance(saved, dict):
        for key in ("urn", "documentUrn", "document_urn"):
            if isinstance(saved.get(key), str):
                return saved[key]
        document = saved.get("document")
        if isinstance(document, dict) and isinstance(document.get("urn"), str):
            return document["urn"]

    text = saved if isinstance(saved, str) else str(saved)
    match = URN_IN_TEXT.search(text)
    return match.group(0) if match else None


def _looks_like_error(response: object) -> bool:
    """A failed MCP call comes back as ordinary text, not an exception."""
    if not isinstance(response, dict):
        return False
    text = response.get("text")
    if not isinstance(text, str):
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in ERROR_MARKERS)


async def _save_report(dh, title: str, report: str, related: list[str]) -> tuple[str | None, str]:
    """Save the impact report, narrowing the arguments if the tool rejects them.

    The tool's optional parameters are the fragile part — `document_type` had a
    closed vocabulary that was not obvious, and `related_assets` may be equally
    picky. Losing the report entirely because of an optional field would be the
    wrong trade, so this degrades to the minimum viable call and says which
    attempt succeeded.
    """
    attempts: list[tuple[str, dict]] = [
        ("full", {"document_type": DOCUMENT_TYPE, "title": title, "content": report,
                  "related_assets": related}),
        ("without related_assets", {"document_type": DOCUMENT_TYPE, "title": title,
                                    "content": report}),
        ("title and content only", {"title": title, "content": report}),
    ]

    last = ""
    for label, kwargs in attempts:
        try:
            response = await dh.call("save_document", **kwargs)
        except Exception as exc:
            last = f"{label}: {exc.__class__.__name__}: {exc}"
            continue
        if _skipped(response):
            return None, "dry run"
        if _looks_like_error(response):
            last = f"{label}: {str(response.get('text'))[:300]}"
            continue
        urn = _document_urn(response)
        if urn:
            return urn, label
        last = f"{label}: no urn in response {str(response)[:200]}"
    return None, last


def _skipped(response: object) -> bool:
    """A dry run returns a marker instead of writing. Counting those as successes
    would make the report claim changes that never happened."""
    return isinstance(response, dict) and bool(response.get("dry_run"))


async def write_back(state: FuseState) -> dict:
    dh = RT.require_dh()
    impacts: list[Impact] = state.get("impacts", [])
    run_id = state.get("run_id", "local")
    result = WriteBackResult(run_id=run_id, dry_run=RT.dry_run)
    trace = list(state.get("trace", []))
    report = _report_markdown(state)

    breaking = [i for i in impacts if i.severity in {"BREAKING", "RISKY"}]
    targets = breaking or impacts
    tag = TAG_PENDING if breaking else TAG_SAFE

    # add_tags takes a list of entities, so the whole blast radius is one call.
    if targets:
        try:
            response = await dh.call(
                "add_tags", tag_urns=[tag], entity_urns=[i.urn for i in targets]
            )
            if not _skipped(response):
                result.tagged = [i.urn for i in targets]
        except Exception as exc:
            result.errors.append(f"add_tags: {exc.__class__.__name__}: {exc}")

        # Structured properties need the property definition registered up front; if the
        # instance has not been bootstrapped for it, this is a warning, not a failure.
        try:
            response = await dh.call(
                "add_structured_properties",
                property_values=[
                    {"propertyUrn": FUSE_PROPERTY_URNS[0],
                     "values": [max(i.score for i in targets)]},
                    {"propertyUrn": FUSE_PROPERTY_URNS[1],
                     "values": [state.get("max_severity", "SAFE")]},
                    {"propertyUrn": FUSE_PROPERTY_URNS[2], "values": [run_id]},
                    {"propertyUrn": FUSE_PROPERTY_URNS[3],
                     "values": [datetime.now(timezone.utc).isoformat(timespec="seconds")]},
                ],
                entity_urns=[i.urn for i in targets],
            )
            if not _skipped(response):
                result.properties_set = [i.urn for i in targets]
        except Exception as exc:
            result.errors.append(f"add_structured_properties: {exc.__class__.__name__}: {exc}")

    # Annotate the exact column being removed, where an engineer will actually see it.
    for asset in state.get("resolved", []):
        if asset.change.kind in {"drop_column", "rename_column"} and asset.change.column:
            try:
                response = await dh.call(
                    "update_description",
                    entity_urn=asset.urn,
                    column_path=asset.change.column,
                    description=(
                        f"[Fuse] `{asset.change.column}` is being removed by run {run_id}. "
                        f"{len(breaking)} downstream asset(s) affected. See the Fuse impact report."
                    ),
                )
                if not _skipped(response):
                    result.described.append(asset.urn)
            except Exception as exc:
                result.errors.append(f"{asset.urn}: {exc.__class__.__name__}: {exc}")

    urn, detail = await _save_report(
        dh,
        f"Fuse impact report — {run_id}",
        report,
        [i.urn for i in impacts],
    )
    result.document_urn = urn
    if urn:
        trace.append(f"writeback: report saved as a document ({detail})")
    elif detail != "dry run":
        result.errors.append(f"save_document: {detail}")

    if result.dry_run:
        trace.append("writeback: dry run — nothing was written to DataHub")
    else:
        trace.append(
            f"writeback: tagged {len(result.tagged)}, described {len(result.described)}, "
            f"document {'saved' if result.document_urn else 'not saved'}"
            + (f", {len(result.errors)} error(s)" if result.errors else "")
        )
    return {"writeback": result, "report_md": report, "trace": trace}

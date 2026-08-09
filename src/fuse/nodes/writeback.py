"""Node 8 - record the verdict in DataHub.

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

TAG_DESCRIPTIONS = {
    TAG_PENDING: "Fuse found an unmerged schema change that reaches this asset.",
    TAG_SAFE: "Fuse analysed a schema change and found no impact on this asset.",
}

# (urn, DataHub value type, description) - the definitions the instance needs before
# any of these properties can be set on an entity.
PROPERTY_DEFINITIONS = (
    (FUSE_PROPERTY_URNS[0], "number", "Fuse blast-radius score, 0-100."),
    (FUSE_PROPERTY_URNS[1], "string", "Fuse severity: SAFE, RISKY or BREAKING."),
    (FUSE_PROPERTY_URNS[2], "string", "The Fuse run that last scored this asset."),
    (FUSE_PROPERTY_URNS[3], "string", "When Fuse last scored this asset."),
)

# Every type Fuse scores that DataHub will actually accept a structured property on.
# `mlModelDeployment` is deliberately absent: its `entityType` entity exists and
# resolves, but GMS still answers `Unknown entityTypeUrn` when a definition names it,
# and one rejected member fails the whole definition. The deployment is the asset this
# project exists to reach, so it is still tagged and still in the report - it just
# cannot carry the score. Measured on DataHub 1.5.0.6; see docs/upstream.
PROPERTY_ENTITY_TYPES = (
    "dataset",
    "dashboard",
    "chart",
    "mlFeature",
    "mlFeatureTable",
    "mlModel",
    "mlModelGroup",
)
SUPPORTS_PROPERTIES = frozenset(PROPERTY_ENTITY_TYPES)


def _report_markdown(state: FuseState) -> str:
    impacts: list[Impact] = state.get("impacts", [])
    lines = [
        f"# Fuse impact report - {state.get('run_id', 'local')}",
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
            f"{'; '.join(i.evidence) or '-'} | {', '.join(i.owners) or '-'} |"
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

    The tool's optional parameters are the fragile part - `document_type` had a
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


def _wrote(response: object) -> bool:
    """Whether a mutation actually changed the catalog.

    A failed mutation is not an exception - it is an ordinary text response saying
    what went wrong. Checking only for exceptions is how a run once reported
    `tagged 9, errors: []` while writing nothing at all.
    """
    return not _skipped(response) and not _looks_like_error(response)


async def _apply(dh, tool: str, urns: list[str], **kwargs) -> tuple[list[str], list[str]]:
    """Write to every entity, batched, then one at a time if the batch is refused.

    DataHub validates the whole batch before writing any of it, so a single entity
    of a type the tool will not accept costs the write on all the others. Retrying
    individually turns that from a total loss into a partial success plus a precise
    error, which is also the difference between a report that can be trusted and one
    that just says the run failed.
    """
    try:
        response = await dh.call(tool, entity_urns=urns, **kwargs)
    except Exception as exc:
        response = {"text": f"{exc.__class__.__name__}: {exc}"}

    if _wrote(response):
        return list(urns), []
    if _skipped(response):
        return [], []
    if len(urns) == 1:
        return [], [f"{tool} on {urns[0]}: {str(response)[:200]}"]

    written: list[str] = []
    errors: list[str] = []
    for urn in urns:
        ok, failed = await _apply(dh, tool, [urn], **kwargs)
        written += ok
        errors += failed
    return written, errors


def _ensure_vocabulary(trace: list[str], errors: list[str]) -> None:
    """Define the tags and properties before using them, on a live run only.

    A missing definition is not a partial failure - DataHub rejects every write
    that references it - so it is worth one upsert per run to remove the class of
    failure entirely.
    """
    from fuse.datahub import sdk_writer

    try:
        sdk_writer.ensure_vocabulary(
            TAG_DESCRIPTIONS, PROPERTY_DEFINITIONS, PROPERTY_ENTITY_TYPES
        )
        trace.append("writeback: tag and structured-property definitions ensured")
    except Exception as exc:
        # Worth reporting, not worth losing the run over: the document still lands.
        errors.append(f"ensure_vocabulary: {exc.__class__.__name__}: {exc}")


async def write_back(state: FuseState) -> dict:
    dh = RT.require_dh()
    impacts: list[Impact] = state.get("impacts", [])
    run_id = state.get("run_id", "local")
    result = WriteBackResult(run_id=run_id, dry_run=RT.dry_run)
    trace = list(state.get("trace", []))
    report = _report_markdown(state)

    breaking = [i for i in impacts if i.severity in {"BREAKING", "RISKY"}]
    tag = TAG_PENDING if breaking else TAG_SAFE

    if getattr(dh, "live", False):
        _ensure_vocabulary(trace, result.errors)

    if breaking:
        targets = breaking
    else:
        # A clean run marks the asset that changed, not every asset downstream of it.
        # Tagging thirty untouched consumers "verified safe" on every pull request
        # carpets the catalog with noise and would get the tag ignored - and later
        # filtered out - within a week.
        changed = {a.urn for a in state.get("resolved", [])}
        targets = [i for i in impacts if i.urn in changed]
        if not targets and impacts:
            trace.append(
                "writeback: nothing above SAFE and no changed asset in the graph, "
                "recording the analysis without tagging"
            )

    # The whole blast radius goes in one call, and falls back to one call per asset.
    if targets:
        result.tagged, errors = await _apply(
            dh, "add_tags", [i.urn for i in targets], tag_urns=[tag]
        )
        result.errors += errors

        # The tool maps property urn -> values, not a list of {propertyUrn, values}
        # objects; the definitions themselves are ensured above.
        scored = [i for i in targets if i.entity_type in SUPPORTS_PROPERTIES]
        if scored:
            result.properties_set, errors = await _apply(
                dh,
                "add_structured_properties",
                [i.urn for i in scored],
                property_values={
                    FUSE_PROPERTY_URNS[0]: [max(i.score for i in targets)],
                    FUSE_PROPERTY_URNS[1]: [state.get("max_severity", "SAFE")],
                    FUSE_PROPERTY_URNS[2]: [run_id],
                    FUSE_PROPERTY_URNS[3]: [
                        datetime.now(timezone.utc).isoformat(timespec="seconds")
                    ],
                },
            )
            result.errors += errors

        unscorable = len(targets) - len(scored)
        if unscorable:
            trace.append(
                f"writeback: {unscorable} asset(s) tagged but not scored - DataHub "
                "rejects structured properties on their entity type"
            )

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
                if _wrote(response):
                    result.described.append(asset.urn)
                elif not _skipped(response):
                    result.errors.append(f"update_description: {str(response)[:300]}")
            except Exception as exc:
                result.errors.append(f"{asset.urn}: {exc.__class__.__name__}: {exc}")

    urn, detail = await _save_report(
        dh,
        f"Fuse impact report - {run_id}",
        report,
        [i.urn for i in impacts],
    )
    result.document_urn = urn
    if urn:
        trace.append(f"writeback: report saved as a document ({detail})")
    elif detail != "dry run":
        result.errors.append(f"save_document: {detail}")

    if result.dry_run:
        trace.append("writeback: dry run - nothing was written to DataHub")
    else:
        trace.append(
            f"writeback: tagged {len(result.tagged)}, described {len(result.described)}, "
            f"document {'saved' if result.document_urn else 'not saved'}"
            + (f", {len(result.errors)} error(s)" if result.errors else "")
        )
    return {"writeback": result, "report_md": report, "trace": trace}

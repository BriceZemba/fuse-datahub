"""Write-back has to be honest about what it did and did not write."""

from __future__ import annotations

import pytest

from fuse.nodes.writeback import (
    _document_urn,
    _looks_like_error,
    _save_report,
    _skipped,
    _wrote,
)

DOC_URN = "urn:li:document:0195f0d2-9e0e-7c1f-a1c2-3d4e5f607182"


def test_urn_is_found_in_a_structured_response():
    assert _document_urn({"urn": DOC_URN}) == DOC_URN
    assert _document_urn({"document": {"urn": DOC_URN}}) == DOC_URN


def test_urn_is_found_in_a_text_response():
    """MCP tools frequently answer with prose rather than JSON."""
    assert _document_urn({"text": f"Created document {DOC_URN} successfully"}) == DOC_URN


def test_missing_urn_reports_nothing_rather_than_guessing():
    assert _document_urn({"status": "ok"}) is None


def test_validation_failures_arrive_as_text_not_exceptions():
    failure = {
        "text": "1 validation error for call[save_document]\ndocument_type\n  Input should be"
    }
    assert _looks_like_error(failure) is True
    assert _looks_like_error({"text": "Saved"}) is False
    assert _looks_like_error({"urn": DOC_URN}) is False


def test_dry_run_marker_is_not_a_success():
    assert _skipped({"dry_run": True}) is True
    assert _skipped({"urn": DOC_URN}) is False


def test_a_rejected_tag_is_not_counted_as_written():
    """The failure that made a run report `tagged 9, errors: []` while writing nothing.

    DataHub refuses a tag whose urn does not exist, and says so in text rather than
    raising, so a check for exceptions alone reads the refusal as a success.
    """
    refusal = {
        "text": "Error calling tool 'add_tags': Failed to validate label with urn "
        "urn:li:tag:fuse-pending-breaking-change. Urn does not exist."
    }
    assert _wrote(refusal) is False
    assert _wrote({"dry_run": True}) is False
    assert _wrote({"text": "Tags added"}) is True


class FakeDH:
    """Rejects optional arguments the way the real tool rejects unknown enum values."""

    def __init__(self, accepts: set[str]) -> None:
        self.accepts = accepts
        self.calls: list[dict] = []

    async def call(self, tool: str, **kwargs):
        self.calls.append(kwargs)
        rejected = set(kwargs) - self.accepts
        if rejected:
            return {"text": f"1 validation error for call[{tool}]: {sorted(rejected)}"}
        return {"text": f"Created document {DOC_URN}"}


@pytest.mark.asyncio
async def test_the_report_still_saves_when_an_optional_argument_is_rejected():
    dh = FakeDH(accepts={"title", "content"})
    urn, detail = await _save_report(dh, "report", "body", ["urn:li:dataset:x"])
    assert urn == DOC_URN
    assert detail == "title and content only"
    assert len(dh.calls) == 3  # narrowed twice before succeeding


@pytest.mark.asyncio
async def test_the_first_accepted_shape_wins():
    dh = FakeDH(accepts={"title", "content", "document_type", "related_assets"})
    urn, detail = await _save_report(dh, "report", "body", ["urn:li:dataset:x"])
    assert urn == DOC_URN
    assert detail == "full"
    assert len(dh.calls) == 1


@pytest.mark.asyncio
async def test_total_failure_reports_the_last_message():
    dh = FakeDH(accepts=set())
    urn, detail = await _save_report(dh, "report", "body", [])
    assert urn is None
    assert "validation error" in detail

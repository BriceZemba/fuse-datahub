"""Writes that the MCP mutation tools don't cover, via the DataHub Python SDK.

Used for entity upserts (the ML lineage seed) and for bulk custom properties.
Kept separate from mcp_client so it is obvious in review which write went where.
"""

from __future__ import annotations

from typing import Any

from fuse.config import settings


def client() -> Any:
    from datahub.sdk import DataHubClient

    return DataHubClient(server=settings.gms_url, token=settings.gms_token or None)


def upsert(entity: Any) -> None:
    client().entities.upsert(entity)


def emit_mcps(mcps: Any) -> None:
    client()._emit_mcps(mcps)

"""Fallback to the GMS GraphQL API for anything the MCP surface doesn't expose.

Today that is fine-grained (column-level) lineage. Confirm against your instance in
the Day-2 spike before relying on it; if `get_lineage` already returns column edges,
this module stays unused and should be deleted rather than kept as dead weight.
"""

from __future__ import annotations

from typing import Any

import httpx

from fuse.config import settings

FINE_GRAINED_QUERY = """
query fineGrained($urn: String!) {
  dataset(urn: $urn) {
    urn
    fineGrainedLineages {
      upstreams { urn path }
      downstreams { urn path }
      transformOperation
    }
  }
}
"""


async def fine_grained_lineage(urn: str) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if settings.gms_token:
        headers["Authorization"] = f"Bearer {settings.gms_token}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.gms_url.rstrip('/')}/api/graphql",
            headers=headers,
            json={"query": FINE_GRAINED_QUERY, "variables": {"urn": urn}},
        )
        resp.raise_for_status()
        return resp.json()

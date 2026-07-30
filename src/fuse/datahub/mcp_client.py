"""Thin facade over the DataHub MCP server.

Every read and write Fuse performs goes through here, so the cache, the replay mode
and the call trace all have exactly one place to hook into.

Tools exposed by mcp-server-datahub:
  read      search, get_lineage, get_lineage_paths_between, get_entities,
            list_schema_fields, get_dataset_queries
  documents search_documents, grep_documents, save_document
  mutation  add_tags, remove_tags, add_terms, remove_terms, add_owners, remove_owners,
            set_domains, remove_domains, update_description,
            add_structured_properties, remove_structured_properties
  user      get_me
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fuse.config import settings
from fuse.datahub.cache import CallCache

READ_TOOLS = {
    "search",
    "get_lineage",
    "get_lineage_paths_between",
    "get_entities",
    "list_schema_fields",
    "get_dataset_queries",
    "search_documents",
    "grep_documents",
}
MUTATION_TOOLS = {
    "add_tags",
    "remove_tags",
    "add_terms",
    "remove_terms",
    "add_owners",
    "remove_owners",
    "set_domains",
    "remove_domains",
    "update_description",
    "add_structured_properties",
    "remove_structured_properties",
    "save_document",
}


async def probe_gms(url: str | None = None, timeout: float = 5.0) -> tuple[bool, str]:
    """Cheap pre-flight check.

    The MCP server connects to GMS at startup and dies with a full stack trace if it
    can't. Probing first turns that wall of traceback into one actionable line.
    """
    import httpx

    endpoint = (url or settings.gms_url).rstrip("/") + "/config"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(endpoint)
    except Exception as exc:
        return False, exc.__class__.__name__
    return response.status_code < 500, f"HTTP {response.status_code}"


class GMSUnreachable(RuntimeError):
    """GMS is not answering. Raised before spawning the MCP server."""


class DataHubMCP:
    """Async facade. Use as ``async with DataHubMCP() as dh: await dh.call("search", ...)``."""

    def __init__(
        self,
        *,
        fixtures: Path | None = None,
        replay: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.cache = CallCache(fixtures or settings.fixtures_dir, replay=replay)
        self.replay = replay
        self.dry_run = dry_run
        self.trace: list[str] = []
        self._client = None
        self._tools: dict[str, Any] = {}

    async def __aenter__(self) -> DataHubMCP:
        if not self.replay:
            reachable, detail = await probe_gms()
            if not reachable:
                raise GMSUnreachable(
                    f"{settings.gms_url} is not answering ({detail}). "
                    "Start DataHub with ./scripts/bootstrap-datahub.sh, or point "
                    "DATAHUB_GMS_URL at a running instance. Note GMS is :8080, the UI is :9002."
                )

            from langchain_mcp_adapters.client import MultiServerMCPClient

            # `@latest` makes uvx re-resolve the package against the index on every
            # invocation. Without it the cached build is reused, which is most of the
            # startup cost. Override with FUSE_MCP_SERVER to pin a version.
            spec = os.getenv("FUSE_MCP_SERVER", "mcp-server-datahub")
            self._client = MultiServerMCPClient(
                {
                    "datahub": {
                        "command": "uvx",
                        "args": [spec],
                        "env": settings.mcp_env(),
                        "transport": "stdio",
                    }
                }
            )
            for tool in await self._client.get_tools():
                self._tools[tool.name] = tool
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._client = None
        self._tools = {}

    @property
    def available(self) -> list[str]:
        return sorted(self._tools)

    async def cached(self, name: str, args: dict[str, Any], producer: Any) -> Any:
        """Record/replay a call that does not go through an MCP tool.

        Some data is only reachable outside the MCP surface — ML entity discovery via
        GraphQL, ML aspects via the typed SDK. Those still have to be captured, or
        `fuse replay` reaches for a live DataHub that a judge does not have.
        """
        hit = self.cache.get(name, args)
        if hit is not None:
            self.trace.append(f"{name} (cached)")
            return hit
        value = await producer()
        self.cache.put(name, args, value)
        self.trace.append(name)
        return value

    async def call(self, tool: str, **args: Any) -> Any:
        """Call an MCP tool, going through the cache first."""
        cached = self.cache.get(tool, args)
        if cached is not None:
            self.trace.append(f"{tool} (cached)")
            return cached

        if self.dry_run and tool in MUTATION_TOOLS:
            self.trace.append(f"{tool} (dry-run, skipped)")
            return {"dry_run": True, "tool": tool, "args": args}

        if tool not in self._tools:
            raise RuntimeError(
                f"MCP tool {tool!r} not available. Loaded: {self.available or '(none)'}. "
                "Mutation tools need TOOLS_IS_MUTATION_ENABLED=true."
            )

        raw = await self._tools[tool].ainvoke(args)
        response = _coerce(raw)
        self.cache.put(tool, args, response)
        self.trace.append(tool)
        return response


def _coerce(raw: Any) -> Any:
    """Unwrap an MCP tool result into plain data.

    The DataHub MCP server answers with content blocks — `[{"id": ..., "type": "text",
    "text": "<json>"}]` — so the payload is a JSON *string* nested one level down.
    Reading the wrapper instead of its contents is silent failure: parsers find no
    entities and report an empty catalog, which is exactly what happened before the
    shapes were recorded (see docs/spike-raw/).
    """
    if isinstance(raw, str):
        return _parse_json(raw)

    if isinstance(raw, list):
        blocks = [b for b in raw if isinstance(b, dict) and isinstance(b.get("text"), str)]
        if blocks:
            parsed = [_parse_json(b["text"]) for b in blocks]
            return parsed[0] if len(parsed) == 1 else parsed
        return raw

    if isinstance(raw, dict):
        # Some clients hand back a single content block rather than a list of them.
        if isinstance(raw.get("text"), str) and raw.get("type") == "text":
            return _parse_json(raw["text"])
        content = raw.get("content")
        if isinstance(content, list):
            return _coerce(content)
        return raw

    return {"value": str(raw)}


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def get_client(**kwargs: Any) -> DataHubMCP:
    return DataHubMCP(**kwargs)

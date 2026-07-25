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
            from langchain_mcp_adapters.client import MultiServerMCPClient

            self._client = MultiServerMCPClient(
                {
                    "datahub": {
                        "command": "uvx",
                        "args": ["mcp-server-datahub@latest"],
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
    """MCP tools return text content; parse JSON when they do."""
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"text": raw}
    return {"value": str(raw)}


def get_client(**kwargs: Any) -> DataHubMCP:
    return DataHubMCP(**kwargs)

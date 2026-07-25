"""Process-wide handles the graph nodes need.

LangGraph state carries data; this carries connections. Set once by the CLI before
``app.ainvoke`` so nodes stay pure-ish and easy to test with a fake client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fuse.datahub.mcp_client import DataHubMCP


@dataclass
class Runtime:
    dh: DataHubMCP | None = None
    llm: Any = None
    dry_run: bool = False
    log: list[str] = field(default_factory=list)

    def require_dh(self) -> DataHubMCP:
        if self.dh is None:
            raise RuntimeError("No DataHub client bound. Did the CLI forget to set runtime.dh?")
        return self.dh


RT = Runtime()

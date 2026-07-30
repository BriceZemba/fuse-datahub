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

    async def ask_llm(self, purpose: str, prompt: str) -> str | None:
        """Call the model, recording the response alongside the DataHub calls.

        Generation is nondeterministic, so a replay that re-ran the model would not
        reproduce the artifacts it is meant to reproduce — and would need a network and
        an API key to do it. Recording the response makes a frozen example an honest
        reproduction of the run that produced it, LLM-authored SQL included.

        Returns None when there is neither a recording nor a client, which is the
        signal for the caller to fall back to templates.
        """
        if self.dh is None:
            return None

        name, key = f"llm:{purpose}", {"prompt": prompt}

        # A recording wins over a live call, and in replay mode a miss simply means
        # "this run had no LLM" rather than an error.
        try:
            recorded = self.dh.cache.get(name, key)
        except Exception:
            recorded = None
        if recorded is not None:
            return str(recorded)

        if self.llm is None:
            return None

        response = await self.llm.ainvoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        self.dh.cache.put(name, key, text)
        return str(text)


RT = Runtime()

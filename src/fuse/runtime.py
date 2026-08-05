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
        model = self._model_name()

        # A recording wins over a live call, and in replay mode a miss simply means
        # "this run had no LLM" rather than an error.
        try:
            recorded = self.dh.cache.get(name, key)
        except Exception:
            recorded = None

        if recorded is not None:
            cached_model, text = _unpack(recorded)
            # A recording made by a different model is not this model's answer. Reusing
            # it silently makes FUSE_LLM_MODEL do nothing and turns any comparison
            # between models into a comparison of the same cached text.
            if self.llm is None or not cached_model or cached_model == model:
                return text
            self.log.append(
                f"llm:{purpose}: recording was made by {cached_model}, regenerating with {model}"
            )

        if self.llm is None:
            return None

        response = await self.llm.ainvoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        self.dh.cache.put(name, key, {"model": model, "text": text})
        return str(text)

    def _model_name(self) -> str:
        if self.llm is None:
            return ""
        for attribute in ("model_name", "model", "model_id"):
            value = getattr(self.llm, attribute, None)
            if isinstance(value, str) and value:
                return value
        return ""


def _unpack(recorded: object) -> tuple[str, str]:
    """(model, text) from a recording, tolerating the older text-only format."""
    if isinstance(recorded, dict):
        return str(recorded.get("model") or ""), str(recorded.get("text") or "")
    return "", str(recorded)


RT = Runtime()

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
    # Set when a model call fails, so nodes can report degraded output rather than
    # pretending the templates were a deliberate choice.
    llm_error: str | None = None

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
            # Replay takes whatever was recorded — there is no client to ask.
            if self.llm is None:
                return text
            # Live, the recording is only this model's answer if it says so. Treating an
            # unattributed recording as a match is how the first version of this check
            # still served 120B output to a 9B request, making FUSE_LLM_MODEL a no-op.
            if cached_model == model:
                return text
            self.log.append(
                f"llm:{purpose}: recording is from "
                f"{cached_model or 'an unrecorded model'}, regenerating with {model}"
            )

        if self.llm is None:
            return None

        try:
            response = await self.llm.ainvoke(prompt)
        except Exception as exc:
            # Rate limits, quota exhaustion and provider outages are ordinary on a free
            # tier. Losing the whole run to one is not: the caller falls back to
            # deterministic templates, so the analysis and the rest of the artifacts
            # still land. The trace records what was lost and why.
            self.llm_error = f"{exc.__class__.__name__}: {str(exc)[:160]}"
            self.log.append(f"llm:{purpose}: {self.llm_error} — falling back to templates")
            return None

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

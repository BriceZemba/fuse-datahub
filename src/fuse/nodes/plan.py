"""Node 5 — pick a remediation strategy per impacted asset.

The LLM decides here because the right move genuinely depends on context (is this
consumer worth a compatibility view, or should it just be rewritten?). Its answer is
constrained to a fixed vocabulary and validated; a bad answer falls back to rules.
"""

from __future__ import annotations

import json

from fuse.llm.provider import get_llm
from fuse.nodes.codegen import _consumer_sql
from fuse.runtime import RT
from fuse.state import FuseState, Impact, Strategy

VALID: set[str] = {
    "rewrite_sql",
    "add_compat_view",
    "deprecate_with_shim",
    "backfill",
    "add_contract_test",
    "no_action",
}

PROMPT = """You are a staff data engineer deciding how to protect downstream consumers \
from a schema change that is already agreed.

Change: {change}

Impacted assets (from DataHub lineage, scored by a deterministic rule engine):
{impacts}

`sql=yes` means this consumer's definition is in the repo under review, so it can be
edited in this pull request. Prefer rewrite_sql for those: fixing the consumer is
better than leaving a compatibility shim behind for someone else to clean up.

For each asset choose exactly one strategy from:
- rewrite_sql        the consumer's SQL can be updated directly
- add_compat_view    keep the old shape available during a deprecation window
- deprecate_with_shim keep the column, filled with a sentinel, and mark it deprecated
- backfill           the consumer needs historical data restated
- add_contract_test  the consumer is fine, but pin the contract so this can't recur
- no_action          genuinely unaffected

Respond with a single JSON object and nothing else — no explanation, no reasoning, no
markdown fences:

{{"<urn>": "<strategy>"}}"""


def _extract_json(text: str) -> dict | None:
    """Pull a JSON object out of a model response.

    Open-weight models wrap answers in markdown fences, prefix them with reasoning, or
    append a summary — and reasoning models emit whole paragraphs of it. Scanning for
    balanced braces from each opening brace handles all three without assuming the
    object sits at either end of the string.
    """
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth, in_string, escaped = 0, False, False
        for end in range(start, len(text)):
            current = text[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        break  # try the next opening brace
                    if isinstance(parsed, dict) and parsed:
                        return parsed
                    break
    return None


def _fallback(impacts: list[Impact], state: FuseState | None = None) -> dict[str, Strategy]:
    """Rules used when there is no LLM, or when the LLM answers badly."""
    plan: dict[str, Strategy] = {}
    for impact in impacts:
        if impact.severity == "SAFE":
            plan[impact.urn] = "add_contract_test"
        elif impact.entity_type in {"mlFeature", "mlFeatureTable", "mlModel", "mlModelDeployment"}:
            # ML consumers cannot be hot-patched; keep the old shape and alert the owner.
            plan[impact.urn] = "add_compat_view"
        elif state is not None and _consumer_sql(state, impact):
            # Its definition is in this repo, so fix it here rather than shim around it.
            plan[impact.urn] = "rewrite_sql"
        elif impact.references_column:
            plan[impact.urn] = "rewrite_sql"
        else:
            plan[impact.urn] = "add_contract_test"
    return plan


async def plan_remediation(state: FuseState) -> dict:
    impacts: list[Impact] = state.get("impacts", [])
    trace = list(state.get("trace", []))
    llm = RT.llm or get_llm()

    if llm is None:
        trace.append("plan: no LLM configured, using rule-based strategies")
        return {"plan": _fallback(impacts, state), "trace": trace}

    # Only the assets that need a decision go to the model. Asking it to rule on two
    # dozen SAFE assets costs tokens and latency to reproduce what the rules already
    # say, and every one of those answers is filled in from rules below anyway.
    actionable = [i for i in impacts if i.severity != "SAFE"]
    if not actionable:
        trace.append("plan: nothing above SAFE, using rule-based strategies")
        return {"plan": _fallback(impacts, state), "trace": trace}

    summary = "\n".join(
        f"- {i.urn} | {i.entity_type} | {i.severity} {i.score} | "
        f"sql={'yes' if _consumer_sql(state, i) else 'no'} | "
        f"refs_column={i.references_column} | {'; '.join(i.evidence[:2])}"
        for i in actionable
    )
    change = impacts[0].source_change if impacts else "unknown change"
    try:
        text = await RT.ask_llm("plan", PROMPT.format(change=change, impacts=summary))
        if not text:
            raise ValueError("no response")
        raw = _extract_json(text)
        if raw is None:
            # Say what actually came back. "JSONDecodeError" alone sent me guessing at
            # whether the model was fenced, chatty, or truncated.
            snippet = " ".join(text.split())[:200]
            trace.append(f"plan: model did not return JSON ({snippet!r}), using rules")
            return {"plan": _fallback(impacts, state), "trace": trace}
        plan = {
            urn: strategy
            for urn, strategy in raw.items()
            if strategy in VALID and any(i.urn == urn for i in impacts)
        }
        missing = [i for i in impacts if i.urn not in plan]
        if missing:
            plan.update(_fallback(missing, state))
            trace.append(f"plan: filled {len(missing)} gap(s) from rules")
        trace.append(f"plan: {len(plan)} strategy decision(s)")
        return {"plan": plan, "trace": trace}
    except Exception as exc:
        trace.append(f"plan: LLM planning failed ({exc.__class__.__name__}), using rules")
        return {"plan": _fallback(impacts, state), "trace": trace}

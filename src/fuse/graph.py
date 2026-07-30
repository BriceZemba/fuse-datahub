"""LangGraph assembly.

    parse_change -> resolve -> lineage -> impact -+-> (SAFE) ----------> writeback -> pr
                                                  `-> plan -> codegen -> validate -+
                                                                 ^                 |
                                                                 `----- retry -----'
"""

from __future__ import annotations

import inspect
import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from fuse.nodes.codegen import generate_code
from fuse.nodes.impact import assess_impact
from fuse.nodes.lineage import trace_lineage
from fuse.nodes.parse_change import parse_change
from fuse.nodes.plan import plan_remediation
from fuse.nodes.pr import emit_pr
from fuse.nodes.resolve import resolve
from fuse.nodes.validate import validate
from fuse.nodes.writeback import write_back
from fuse.state import FuseState

MAX_RETRIES = 2


def route_after_impact(state: FuseState) -> str:
    """Nothing to fix is still worth recording, so SAFE skips straight to write-back."""
    return "safe" if state.get("max_severity", "SAFE") == "SAFE" else "act"


def route_after_validate(state: FuseState) -> str:
    errors = state.get("validation_errors") or []
    if not errors:
        return "ok"
    if state.get("retries", 0) < MAX_RETRIES:
        return "retry"
    return "giveup"  # artifacts ship flagged needs_human rather than silently broken


def _timed(name: str, fn):
    """Record how long each node took, in the trace the PR body already shows.

    Cheap to keep, and it turns "the run feels slow" into a number per stage.
    """

    if inspect.iscoroutinefunction(fn):

        async def wrapper(state: FuseState):
            started = time.perf_counter()
            result = await fn(state)
            return _stamp(name, result, time.perf_counter() - started)

        return wrapper

    def wrapper(state: FuseState):
        started = time.perf_counter()
        result = fn(state)
        return _stamp(name, result, time.perf_counter() - started)

    return wrapper


def _stamp(name: str, result: dict, elapsed: float) -> dict:
    trace = list(result.get("trace") or [])
    trace.append(f"timing: {name} took {elapsed:.1f}s")
    return {**result, "trace": trace}


def build_graph(*, interrupt_before_writeback: bool = True):
    g = StateGraph(FuseState)

    g.add_node("parse_change", _timed("parse_change", parse_change))
    g.add_node("resolve", _timed("resolve", resolve))
    g.add_node("lineage", _timed("lineage", trace_lineage))
    g.add_node("impact", _timed("impact", assess_impact))
    g.add_node("plan", _timed("plan", plan_remediation))
    g.add_node("codegen", _timed("codegen", generate_code))
    g.add_node("validate", _timed("validate", validate))
    g.add_node("writeback", _timed("writeback", write_back))
    g.add_node("pr", _timed("pr", emit_pr))

    g.set_entry_point("parse_change")
    g.add_edge("parse_change", "resolve")
    g.add_edge("resolve", "lineage")
    g.add_edge("lineage", "impact")
    g.add_conditional_edges("impact", route_after_impact, {"safe": "writeback", "act": "plan"})
    g.add_edge("plan", "codegen")
    g.add_edge("codegen", "validate")
    g.add_conditional_edges(
        "validate",
        route_after_validate,
        {"retry": "codegen", "ok": "writeback", "giveup": "writeback"},
    )
    g.add_edge("writeback", "pr")
    g.add_edge("pr", END)

    return g.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["writeback"] if interrupt_before_writeback else None,
    )

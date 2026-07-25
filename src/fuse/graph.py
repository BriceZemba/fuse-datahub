"""LangGraph assembly.

    parse_change -> resolve -> lineage -> impact -+-> (SAFE) ----------> writeback -> pr
                                                  `-> plan -> codegen -> validate -+
                                                                 ^                 |
                                                                 `----- retry -----'
"""

from __future__ import annotations

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


def build_graph(*, interrupt_before_writeback: bool = True):
    g = StateGraph(FuseState)

    g.add_node("parse_change", parse_change)
    g.add_node("resolve", resolve)
    g.add_node("lineage", trace_lineage)
    g.add_node("impact", assess_impact)
    g.add_node("plan", plan_remediation)
    g.add_node("codegen", generate_code)
    g.add_node("validate", validate)
    g.add_node("writeback", write_back)
    g.add_node("pr", emit_pr)

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

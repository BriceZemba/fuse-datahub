"""Typed state shared by every LangGraph node.

Deterministic nodes own the fields that must be correct (changes, impacts,
validation_errors). LLM nodes own the fields that need judgment (plan, artifacts).
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

Severity = Literal["SAFE", "RISKY", "BREAKING"]

SEVERITY_ORDER: dict[str, int] = {"SAFE": 0, "RISKY": 1, "BREAKING": 2}

ChangeKind = Literal[
    "drop_column",
    "rename_column",
    "retype_column",
    "add_column",
    "drop_model",
    "change_grain",
    "change_filter",
]

EntityType = Literal[
    "dataset",
    "chart",
    "dashboard",
    "dataJob",
    "mlFeature",
    "mlFeatureTable",
    "mlModel",
    "mlModelGroup",
    "mlModelDeployment",
]

ResolveMethod = Literal["exact_name", "search_rank", "schema_match", "llm_disambiguated"]

Strategy = Literal[
    "rewrite_sql",
    "add_compat_view",
    "deprecate_with_shim",
    "backfill",
    "add_contract_test",
    "no_action",
]


class Change(BaseModel):
    """One schema-level change extracted from the diff."""

    kind: ChangeKind
    file: str
    model: str
    column: str | None = None
    from_type: str | None = None
    to_type: str | None = None
    renamed_to: str | None = None
    snippet: str = ""

    def describe(self) -> str:
        if self.kind == "rename_column":
            return f"{self.model}.{self.column} renamed to {self.renamed_to}"
        if self.kind == "retype_column":
            return f"{self.model}.{self.column} retyped {self.from_type} -> {self.to_type}"
        if self.column:
            return f"{self.kind} {self.model}.{self.column}"
        return f"{self.kind} {self.model}"


class ResolvedAsset(BaseModel):
    """A change mapped onto a DataHub entity."""

    change: Change
    urn: str
    name: str = ""
    platform: str = ""
    confidence: float = 0.0
    method: ResolveMethod = "search_rank"
    schema_fields: list[dict[str, Any]] = Field(default_factory=list)


class Impact(BaseModel):
    """One downstream asset affected by a change, with its score and the reasons for it."""

    urn: str
    entity_type: EntityType
    name: str
    hops: int = 1
    references_column: bool = False
    evidence: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    tier: str | None = None
    domain: str | None = None
    severity: Severity = "SAFE"
    score: int = 0
    reasons: list[str] = Field(default_factory=list)
    source_change: str = ""


class Artifact(BaseModel):
    """A file Fuse generated and intends to put in the PR."""

    path: str
    kind: Literal[
        "dbt_model",
        "compat_view",
        "backfill",
        "dag_patch",
        "dbt_test",
        "migration_doc",
        "impact_report",
        "pr_body",
    ]
    content: str
    needs_human: bool = False
    notes: list[str] = Field(default_factory=list)


class WriteBackResult(BaseModel):
    run_id: str = ""
    tagged: list[str] = Field(default_factory=list)
    described: list[str] = Field(default_factory=list)
    properties_set: list[str] = Field(default_factory=list)
    document_urn: str | None = None
    errors: list[str] = Field(default_factory=list)


class FuseState(TypedDict, total=False):
    # inputs
    repo_path: str
    diff: str
    dialect: str
    hops: int
    auto_approve: bool
    replay: bool
    # pipeline
    changes: list[Change]
    resolved: list[ResolvedAsset]
    lineage_graph: dict[str, Any]
    impacts: list[Impact]
    max_severity: Severity
    plan: dict[str, Strategy]
    artifacts: list[Artifact]
    validation_errors: list[str]
    retries: int
    writeback: WriteBackResult
    report_md: str
    # bookkeeping
    run_id: str
    trace: list[str]


def max_severity(impacts: list[Impact]) -> Severity:
    if not impacts:
        return "SAFE"
    return max((i.severity for i in impacts), key=lambda s: SEVERITY_ORDER[s])

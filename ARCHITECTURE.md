# ARCHITECTURE — Fuse

Precise contracts for every component. Written to be implementable without further design decisions.

---

## 1. Design rules

1. **Deterministic where correctness matters, LLM where judgment matters.** Parsing, lineage traversal, risk scoring and validation are code. Remediation strategy, SQL rewriting and prose are LLM. A judge must never wonder whether a score was hallucinated.
2. **Never invent a column.** Every identifier in generated code is either present in the diff or returned by DataHub. The `validate` node enforces this mechanically.
3. **Every MCP call is recorded.** `datahub/cache.py` wraps the client; the same run replays offline from `fixtures/`. This gives reproducibility, tests, and a demo that works without Docker.
4. **Write back or it didn't happen.** Track 1's whole point is that the next agent inherits the knowledge. Fuse always leaves a trail in DataHub.

---

## 2. State

```python
# src/fuse/state.py
from typing import Literal, TypedDict
from pydantic import BaseModel

Severity = Literal["SAFE", "RISKY", "BREAKING"]

class Change(BaseModel):
    kind: Literal["drop_column", "rename_column", "retype_column",
                  "drop_model", "change_grain", "change_filter", "add_column"]
    file: str                    # demo/dbt-shop/models/marts/orders.sql
    model: str                   # orders
    column: str | None
    from_type: str | None
    to_type: str | None
    snippet: str                 # the diff hunk, for LLM grounding

class ResolvedAsset(BaseModel):
    change: Change
    urn: str                     # urn:li:dataset:(urn:li:dataPlatform:snowflake,...,PROD)
    confidence: float            # 0..1
    method: Literal["exact_name", "search_rank", "schema_match", "llm_disambiguated"]

class Impact(BaseModel):
    urn: str
    entity_type: Literal["dataset", "chart", "dashboard", "mlFeature",
                         "mlModel", "mlModelGroup", "dataJob"]
    name: str
    hops: int
    references_column: bool      # hard evidence the impacted asset uses the changed column
    evidence: list[str]          # "query q_1428 selects orders.discount_code"
    owners: list[str]
    tier: str | None             # from tags/glossary, e.g. Tier1
    severity: Severity
    score: int                   # 0..100
    reasons: list[str]           # one line per contributing rule — fully explainable

class Artifact(BaseModel):
    path: str                    # relative path to write in the PR
    kind: Literal["dbt_model", "compat_view", "backfill", "dag_patch",
                  "dbt_test", "migration_doc", "pr_body"]
    content: str

class FuseState(TypedDict, total=False):
    repo_path: str
    diff: str
    changes: list[Change]
    resolved: list[ResolvedAsset]
    impacts: list[Impact]
    max_severity: Severity
    plan: dict                   # urn -> strategy
    artifacts: list[Artifact]
    validation_errors: list[str]
    retries: int
    writeback: dict
    report_md: str
```

---

## 3. Graph

```python
# src/fuse/graph.py  (shape, not final code)
g = StateGraph(FuseState)
g.add_node("parse_change",   parse_change)      # deterministic
g.add_node("resolve",        resolve)           # MCP search (+LLM only to disambiguate)
g.add_node("lineage",        trace_lineage)     # MCP lineage
g.add_node("impact",         assess_impact)     # deterministic risk engine
g.add_node("plan",           plan_remediation)  # LLM
g.add_node("codegen",        generate_code)     # LLM + Jinja
g.add_node("validate",       validate)          # deterministic
g.add_node("writeback",      write_back)        # MCP mutations + Python SDK
g.add_node("pr",             emit_pr)

g.set_entry_point("parse_change")
g.add_edge("parse_change", "resolve")
g.add_edge("resolve", "lineage")
g.add_edge("lineage", "impact")
g.add_conditional_edges("impact", route_after_impact,
                        {"safe": "writeback", "act": "plan"})
g.add_edge("plan", "codegen")
g.add_edge("codegen", "validate")
g.add_conditional_edges("validate", route_after_validate,
                        {"retry": "codegen", "ok": "writeback", "giveup": "writeback"})
g.add_edge("writeback", "pr")
g.add_edge("pr", END)

app = g.compile(checkpointer=MemorySaver(),
                interrupt_before=["writeback"])   # only when max_severity == BREAKING
```

`interrupt_before` gives the human-in-the-loop moment. `--auto-approve` bypasses it for CI.

---

## 4. Node contracts

### 4.1 `parse_change` — deterministic
**In:** `repo_path`, `diff` (from `git diff`, `--staged`, or the Action's PR diff)
**Does:** For each changed `.sql` file, parse the before/after with `sqlglot` (dialect from `dbt_project.yml` / `--dialect`). Diff the projected output columns and their inferred types. Also handle `.yml` contract changes and deleted models. Regex is a fallback only, never the primary path.
**Out:** `changes: list[Change]`
**Test:** three scenario patches produce exactly the expected `Change` objects.

### 4.2 `resolve` — MCP `search`, `list_schema_fields`
**Does:** map each changed model to a DataHub URN.
1. Try exact-name search scoped by platform (`search` with `/q` filters).
2. Rank candidates; if the top-2 gap is < 0.15, fetch `list_schema_fields` for each and score by column-set overlap with the parsed model.
3. Only if still ambiguous, ask the LLM to pick, with the candidate schemas in the prompt. Record `method` so the report can say *how* it resolved.
**Out:** `resolved`, plus a warning artifact when `confidence < 0.6`.

### 4.3 `lineage` — MCP `get_lineage`, `get_lineage_paths_between`, `get_entities`, GraphQL fallback
**Does:** downstream traversal from each resolved URN, N hops (default 3, `--hops`). Collect datasets, charts, dashboards, dataJobs **and ML entities** (`mlFeature`, `mlFeatureTable`, `mlModel`, `mlModelGroup`, deployments). Hydrate names, owners, tags, tier and domain via `get_entities`. Fetch column-level edges: MCP first, `POST /api/graphql` `fineGrainedLineages` if the MCP response is table-level only (per Day-2 spike). Pull `get_dataset_queries` for each downstream dataset to obtain real SQL evidence.
**Out:** a lineage graph in state + every response written to `fixtures/`.

### 4.4 `impact` — deterministic risk engine
For each downstream node compute `score` from `risk/rules.yaml`:

```yaml
base:
  hard_column_reference: 55     # sqlglot proves the asset selects the changed column
  column_lineage_edge: 35       # DataHub fine-grained lineage links the column
  table_only_dependency: 10
modifiers:
  entity_type:
    mlModel: +20                # a broken model is silently wrong, not loudly broken
    mlFeature: +15
    dashboard: +10
    dataset: 0
  tier:
    Tier1: +15
    Tier2: +5
  hops: -3                      # per hop of distance
  queried_last_30d: +10
  no_owner: +5                  # nobody will notice it break
change_kind:
  drop_column: x1.0
  rename_column: x1.0
  retype_column: x0.7           # narrowing types re-scored to x1.0
  add_column: x0.1
thresholds:
  BREAKING: 60
  RISKY: 30
```

Every applied rule appends a human-readable line to `Impact.reasons`. **`max_severity` drives routing and the interrupt.**

### 4.5 `plan` — LLM
Given the change, the impacted set and their evidence, choose one strategy per impacted asset:
`rewrite_sql` · `add_compat_view` · `deprecate_with_shim` · `backfill` · `add_contract_test` · `no_action`.
Output is a strict JSON object validated by pydantic; a parse failure retries once, then falls back to a rule-based default map.

### 4.6 `codegen` — LLM + Jinja, schema-grounded
Prompt carries: the diff hunk, the **real** schema of source and target from `list_schema_fields`, the existing downstream SQL, and the chosen strategy. Deterministic scaffolding (file headers, dbt config blocks, backfill boilerplate, `MIGRATION.md` skeleton) comes from Jinja templates so the LLM only writes the part that needs judgment.

Emits: patched downstream dbt models · `compat_view.sql` (old column preserved as a view for a deprecation window) · `backfill_<model>.py` or `.sql` · Airflow DAG patch · dbt `schema.yml` tests pinning the new contract · `MIGRATION.md` · `PR_BODY.md`.

### 4.7 `validate` — deterministic self-check (the technical centrepiece)
1. `sqlglot.parse` every generated SQL — syntax must be valid in the target dialect.
2. Extract every referenced `table.column`; assert each exists in the schema DataHub returned. **Any unknown identifier is a hard failure.**
3. Assert generated code does not reintroduce the dropped column against the new schema.
4. `dbt parse` if the binary is available (skipped gracefully otherwise).
5. Python artifacts: `compile()` check.

Failures become `validation_errors` and route back to `codegen` with the errors appended to the prompt. Max 2 retries, then the artifact ships flagged `needs-human` rather than silently broken. **Log the retry count — "the agent caught its own hallucination and fixed it" is the best 15 seconds of the video.**

### 4.8 `writeback` — MCP mutations + Python SDK
On every run, regardless of severity:
- `add_tags` on impacted assets → `urn:li:tag:fuse-pending-breaking-change` (and `fuse-verified-safe` on the SAFE path)
- `update_description` on the changed column/dataset with a deprecation note + PR link
- `add_structured_properties`: `fuse.blast_radius_score`, `fuse.impacted_count`, `fuse.last_checked`, `fuse.pr_url`
- `save_document`: the full impact report, so the next agent or human inherits the analysis via `search_documents` / `grep_documents`
- Optional (verify on OSS first): emit a custom assertion result via the Python SDK for the contract test

Writes are idempotent and reversible; `fuse revert <run-id>` removes the tags it added.

### 4.9 `pr` — branch + PR body
Creates `fuse/impact-<short-sha>`, writes artifacts, composes `PR_BODY.md`: a severity banner, the impact table (asset · type · hops · severity · evidence · owner), a "what I changed and why" section, and the DataHub links. In CI the same body is posted as a PR review comment. Local mode writes to `out/` and prints the path.

---

## 5. DataHub client layer

```python
# src/fuse/datahub/mcp_client.py
client = MultiServerMCPClient({
    "datahub": {
        "command": "uvx",
        "args": ["mcp-server-datahub@latest"],
        "env": {"DATAHUB_GMS_URL": ..., "DATAHUB_GMS_TOKEN": ...,
                "TOOLS_IS_MUTATION_ENABLED": "true"},
        "transport": "stdio",
    }
})
tools = await client.get_tools()
```

`cache.py` wraps each tool call: key = `sha256(tool_name + canonical_json(args))`; on miss call through and persist to `fixtures/<key>.json`; in `--replay` mode a miss is a hard error (guarantees the offline demo is honest).

`sdk_writer.py` uses `DataHubClient(server=..., token=...)` for anything the MCP surface doesn't cover (entity upserts, custom properties at scale, ML entity seeding).

---

## 6. LLM provider abstraction

```python
# src/fuse/llm/provider.py
def get_llm(provider: str | None = None):
    """anthropic (default) | openai | ollama | none"""
```

`none` disables `plan` and `codegen` LLM calls and uses rule-based strategy selection plus pure-template generation. Output is less elegant but the pipeline still completes — the repo is never unrunnable for a judge without keys.

---

## 7. Demo assets

- `demo/dbt-shop/` — a small dbt project whose model names match `showcase-ecommerce` datasets, so a local diff maps onto the real catalog graph. **This is what makes the demo feel like production instead of a toy.**
- `demo/seed_ml_lineage.py` — builds `orders → order_features (MLFeatureTable) → churn_model (MLModel, in MLModelGroup) → prod deployment` with the Python SDK (`MLModelGroup`, `MLModel`, `client.create_training_run`, `add_input_datasets_to_run`, `model.add_training_job`, `client._emit_mcps`). Scenario 03 drops a column that feeds a feature — the agent traces it all the way to a deployed model. That single trace is the Track 3 win.
- `demo/scenarios/*.patch` — three canned diffs, applied with `git apply`, so the demo is one command and never fails live.

---

## 8. Test plan

| Layer | Test |
|---|---|
| `parse_change` | golden `Change` objects for all three patches |
| `resolve` | fixture-backed; asserts URN + method + confidence |
| `impact` | table-driven scoring cases incl. boundary values at 30 and 60 |
| `validate` | feed a deliberately hallucinated column → must fail, then pass after retry |
| end-to-end | `fuse replay examples/01-drop-column` reproduces the committed artifacts byte-for-byte |

The byte-for-byte replay test is what proves "it actually works end to end" without a judge running Docker.

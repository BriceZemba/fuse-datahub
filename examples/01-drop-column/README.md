# 01-drop-column

**Change:** drop_column orders.promotion_id  
**Verdict:** BREAKING - 2 of 30 downstream assets need attention

```bash
fuse replay examples/01-drop-column
```

| Asset | Type | Hops | Severity | Score | Evidence |
|---|---|---|---|---|---|
| `order_details` | dataset | 1 | **BREAKING** | 60 | schema carries a field named `promotion_id` |
| `ORDER_DETAILS` | dataset | 2 | **RISKY** | 32 | schema carries a field named `promotion_id` |

## Files

| Path | What it is |
|---|---|
| `diff.patch` | the input |
| `repo/` | the data repo at the moment of the change |
| `fixtures/` | every DataHub response, recorded |
| `impact-report.md` | the analysis, every score explained |
| `PR_BODY.md` | what the reviewer sees |
| `generated/` | the artifacts Fuse produced |
| `run.log` | node-by-node trace |

Nothing here is hand-written; it is the output of the command above.

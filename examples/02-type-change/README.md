# 02-type-change

**Change:** orders.order_total retyped DOUBLE -> INT  
**Verdict:** BREAKING — 17 of 17 downstream assets need attention

```bash
fuse replay examples/02-type-change
```

| Asset | Type | Hops | Severity | Score | Evidence |
|---|---|---|---|---|---|
| `order_details` | dataset | 1 | **BREAKING** | 70 | column-level lineage edge from orders.order_total |
| `order_history` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `ORDER_HISTORY` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `Customer Analytics Measures` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `Essential KPI Measures` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `Geographic Measures` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `Product Perfromance Measures` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `Time Inteligence Measures` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `Custom SQL Query` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `Custom SQL Query` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `ORDER_DETAILS_REPLICA` | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total |
| `ORDER_DETAILS` | dataset | 2 | **RISKY** | 42 | column-level lineage edge from orders.order_total |
| `order_details` | dataset | 3 | **RISKY** | 39 | column-level lineage edge from orders.order_total |
| `ORDER_DETAILS` | dataset | 3 | **RISKY** | 39 | column-level lineage edge from orders.order_total |
| `Order Details` | dataset | 4 | **RISKY** | 36 | column-level lineage edge from orders.order_total |
| `Promotions` | dataset | 4 | **RISKY** | 36 | column-level lineage edge from orders.order_total |
| `Order Mode` | dataset | 4 | **RISKY** | 36 | column-level lineage edge from orders.order_total |

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

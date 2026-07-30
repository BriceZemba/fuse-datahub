# 03-ml-feature-break

**Change:** drop_column customers.credit_limit  
**Verdict:** BREAKING — 8 of 32 downstream assets need attention

```bash
fuse replay examples/03-ml-feature-break
```

| Asset | Type | Hops | Severity | Score | Evidence |
|---|---|---|---|---|---|
| `prod-retention-service` | mlModelDeployment | 3 | **BREAKING** | 64 | ML entity built on customers.credit_limit (invisible to lineage) |
| `customer_churn_features` | mlFeatureTable | 2 | **BREAKING** | 62 | ML entity built on customers.credit_limit (invisible to lineage) |
| `country_id` | mlFeature | 1 | **RISKY** | 55 | — |
| `credit_limit` | mlFeature | 1 | **RISKY** | 55 | — |
| `customer_class` | mlFeature | 1 | **RISKY** | 55 | — |
| `customer_since` | mlFeature | 1 | **RISKY** | 55 | — |
| `order_details` | dataset | 1 | **RISKY** | 35 | — |
| `customer_churn_model` | mlModel | 2 | **RISKY** | 32 | — |

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

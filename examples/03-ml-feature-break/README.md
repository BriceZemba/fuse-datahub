# 03-ml-feature-break

**Change:** drop_column customers.credit_limit  
**Verdict:** BREAKING - 9 of 32 downstream assets need attention

```bash
fuse replay examples/03-ml-feature-break
```

| Asset | Type | Hops | Severity | Score | Evidence |
|---|---|---|---|---|---|
| `credit_limit` | mlFeature | 1 | **BREAKING** | 90 | built on customers.credit_limit |
| `customer_churn_model` | mlModel | 2 | **BREAKING** | 67 | built on customers.credit_limit |
| `prod-retention-service` | mlModelDeployment | 3 | **BREAKING** | 64 | built on customers.credit_limit, not returned by lineage |
| `customer_churn_features` | mlFeatureTable | 2 | **BREAKING** | 62 | built on customers.credit_limit, not returned by lineage |
| `country_id` | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` |
| `customer_class` | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` |
| `customer_since` | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` |
| `customer_churn_models` | mlModelGroup | 3 | **RISKY** | 44 | built on customers.credit_limit |
| `order_details` | dataset | 1 | **RISKY** | 35 | reads from customers; no column-level proof either way |

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

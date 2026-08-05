🔴 **BREAKING** — merging this will break downstream consumers

**Change:** drop_column customers.credit_limit
**Blast radius:** 32 downstream asset(s) found in DataHub

## Impact



| Asset | Type | Hops | Severity | Score | Evidence | Owners |
|---|---|---|---|---|---|---|
| `credit_limit` | mlFeature | 1 | **BREAKING** | 90 | built on customers.credit_limit | _unowned_ |
| `customer_churn_model` | mlModel | 2 | **BREAKING** | 67 | built on customers.credit_limit | _unowned_ |
| `prod-retention-service` | mlModelDeployment | 3 | **BREAKING** | 64 | built on customers.credit_limit, not returned by lineage | _unowned_ |
| `customer_churn_features` | mlFeatureTable | 2 | **BREAKING** | 62 | built on customers.credit_limit, not returned by lineage | _unowned_ |
| `country_id` | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` | _unowned_ |
| `customer_class` | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` | _unowned_ |
| `customer_since` | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` | _unowned_ |
| `customer_churn_models` | mlModelGroup | 3 | **RISKY** | 44 | built on customers.credit_limit | _unowned_ |
| `order_details` | dataset | 1 | **RISKY** | 35 | — | urn:li:corpGroup:b2fd91.1e0398a3-113f-475e-b6fc-32ab72a634d2, urn:li:corpGroup:b2fd91.ORG_DATA_PLATFORM, urn:li:corpuser:b2fd91.EMP006, urn:li:corpuser:b2fd91.brock1@example.com, urn:li:corpuser:b2fd91.bryan@example.com, urn:li:corpuser:b2fd91.jonny1@example.com, urn:li:corpuser:b2fd91.jonny2@example.com, urn:li:corpuser:b2fd91.kirk@example.com, urn:li:corpuser:b2fd91.marty@example.com, urn:li:corpuser:b2fd91.sam@example.com |

<details><summary>23 further asset(s) scored SAFE — listed for the record</summary>

| Asset | Type | Hops | Score |
|---|---|---|---|
| `datahub_order_entries` | dashboard | 4 | 11 |
| `Order Entry Dashboard` | dashboard | 6 | 10 |
| `order_history` | dataset | 3 | 9 |
| `ORDER_HISTORY` | dataset | 3 | 9 |
| `Customer Analytics Measures` | dataset | 3 | 9 |
| `Essential KPI Measures` | dataset | 3 | 9 |
| `Geographic Measures` | dataset | 3 | 9 |
| `Product Perfromance Measures` | dataset | 3 | 9 |
| `Time Inteligence Measures` | dataset | 3 | 9 |
| `Custom SQL Query` | dataset | 3 | 9 |
| `ORDER_DETAILS` | dataset | 2 | 7 |
| `Orders By Month` | chart | 5 | 6 |
| `Popular Products Categories` | chart | 5 | 6 |
| `Promotions` | chart | 5 | 6 |
| `Order Mode` | chart | 5 | 6 |
| `Order Entry Dashboard` | dashboard | 6 | 5 |
| `order_details` | dataset | 3 | 4 |
| `ORDER_DETAILS` | dataset | 3 | 4 |
| `Order Details` | dataset | 4 | 1 |
| `Promotions` | dataset | 4 | 1 |
| `Order Mode` | dataset | 4 | 1 |
| `Orders By Day` | dataset | 4 | 1 |
| `Top Product Category` | dataset | 4 | 1 |

</details>


### ⚠️ ML lineage

This change reaches machine learning assets, which fail silently rather than loudly:

- `credit_limit` (mlFeature, 1 hops) — BREAKING
- `customer_churn_model` (mlModel, 2 hops) — BREAKING
- `prod-retention-service` (mlModelDeployment, 3 hops) — BREAKING
- `customer_churn_features` (mlFeatureTable, 2 hops) — BREAKING
- `country_id` (mlFeature, 1 hops) — RISKY
- `customer_class` (mlFeature, 1 hops) — RISKY
- `customer_since` (mlFeature, 1 hops) — RISKY
- `customer_churn_models` (mlModelGroup, 3 hops) — RISKY


## What Fuse changed

- `models/compat/customers_compat.sql` — compat_view
- `models/customers_schema.yml` — dbt_test
- `models/order_details.sql` — dbt_model
- `MIGRATION.md` — migration_doc


Every generated identifier was checked against the schema DataHub returned; anything the
catalog could not confirm was rejected and regenerated.

## Written back to DataHub

_Dry run — Fuse read DataHub but wrote nothing. Re-run without `--dry-run` to record the verdict._


<details><summary>Agent trace</summary>

```
parse_change: 1 change(s)
timing: parse_change took 0.0s
resolve: customers -> urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.customers,PROD) (search_rank, confidence 0.99)
resolve: 1/1 change(s) mapped to URNs
timing: resolve took 9.4s
lineage: no column-level edges for credit_limit, falling back to table-level
lineage: no query history on the first 5 dataset(s), skipped the remaining 12
lineage: schema checked within 2 hop(s); 15 more distant asset(s) cannot reach RISKY on a schema match alone
lineage: 8 ML entit(ies), 2 of them reachable only through ML aspects, not through get_lineage
lineage: 32 downstream asset(s), 8 ML entit(ies), 0 with query evidence, 0 carrying the column in their schema
timing: lineage took 49.5s
impact: 32 asset(s) — 4 breaking, 5 risky, 23 safe
timing: impact took 0.0s
plan: filled 23 gap(s) from rules
plan: 32 strategy decision(s)
timing: plan took 12.3s
codegen: 4 artifact(s) (attempt 1)
timing: codegen took 10.2s
validate: REJECTED — 6 problem(s)
  - models/order_details.sql: column 'cost_of_delivery' is not in the DataHub schema for any upstream of this change
  - models/order_details.sql: column 'order_date' is not in the DataHub schema for any upstream of this change
  - models/order_details.sql: column 'order_id' is not in the DataHub schema for any upstream of this change
  - models/order_details.sql: column 'order_total' is not in the DataHub schema for any upstream of this change
  - models/order_details.sql: column 'payment_method_code' is not in the DataHub schema for any upstream of this change
timing: validate took 0.0s
codegen: 4 artifact(s) (attempt 2)
timing: codegen took 43.5s
validate: 4 artifact(s) passed
timing: validate took 0.0s
writeback: dry run — nothing was written to DataHub
timing: writeback took 0.0s
```
</details>

<sub>Generated by [Fuse](https://github.com/BriceZemba/fuse-datahub) against http://localhost:8080.</sub>

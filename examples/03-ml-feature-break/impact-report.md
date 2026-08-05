# Fuse impact report — 03-ml-feature-break

**Change:** drop_column customers.credit_limit  
**Max severity:** BREAKING  
**Generated:** 2026-08-05T11:10:31+00:00

| Asset | Type | Hops | Severity | Score | Evidence | Owners |
|---|---|---|---|---|---|---|
| credit_limit | mlFeature | 1 | **BREAKING** | 90 | built on customers.credit_limit | — |
| customer_churn_model | mlModel | 2 | **BREAKING** | 67 | built on customers.credit_limit | — |
| prod-retention-service | mlModelDeployment | 3 | **BREAKING** | 64 | built on customers.credit_limit, not returned by lineage | — |
| customer_churn_features | mlFeatureTable | 2 | **BREAKING** | 62 | built on customers.credit_limit, not returned by lineage | — |
| country_id | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` | — |
| customer_class | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` | — |
| customer_since | mlFeature | 1 | **RISKY** | 55 | derived from customers but not from `credit_limit` | — |
| customer_churn_models | mlModelGroup | 3 | **RISKY** | 44 | built on customers.credit_limit | — |
| order_details | dataset | 1 | **RISKY** | 35 | — | urn:li:corpGroup:b2fd91.1e0398a3-113f-475e-b6fc-32ab72a634d2, urn:li:corpGroup:b2fd91.ORG_DATA_PLATFORM, urn:li:corpuser:b2fd91.EMP006, urn:li:corpuser:b2fd91.brock1@example.com, urn:li:corpuser:b2fd91.bryan@example.com, urn:li:corpuser:b2fd91.jonny1@example.com, urn:li:corpuser:b2fd91.jonny2@example.com, urn:li:corpuser:b2fd91.kirk@example.com, urn:li:corpuser:b2fd91.marty@example.com, urn:li:corpuser:b2fd91.sam@example.com |
| datahub_order_entries | dashboard | 4 | **SAFE** | 11 | — | urn:li:corpuser:b2fd91.sam@example.com, urn:li:corpuser:b2fd91.michael@example.com, urn:li:corpuser:b2fd91.patrick1@example.com, urn:li:corpuser:b2fd91.alex@example.com |
| Order Entry Dashboard | dashboard | 6 | **SAFE** | 10 | — | — |
| order_history | dataset | 3 | **SAFE** | 9 | — | — |
| ORDER_HISTORY | dataset | 3 | **SAFE** | 9 | — | — |
| Customer Analytics Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Essential KPI Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Geographic Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Product Perfromance Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Time Inteligence Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Custom SQL Query | dataset | 3 | **SAFE** | 9 | — | — |
| ORDER_DETAILS | dataset | 2 | **SAFE** | 7 | — | urn:li:corpGroup:b2fd91.1e0398a3-113f-475e-b6fc-32ab72a634d2, urn:li:corpuser:b2fd91.brock1@example.com, urn:li:corpuser:b2fd91.jonny1@example.com |
| Orders By Month | chart | 5 | **SAFE** | 6 | — | urn:li:corpuser:b2fd91.brock1@example.com |
| Popular Products Categories | chart | 5 | **SAFE** | 6 | — | urn:li:corpuser:b2fd91.brock1@example.com |
| Promotions | chart | 5 | **SAFE** | 6 | — | urn:li:corpuser:b2fd91.brock1@example.com |
| Order Mode | chart | 5 | **SAFE** | 6 | — | urn:li:corpuser:b2fd91.brock1@example.com |
| Order Entry Dashboard | dashboard | 6 | **SAFE** | 5 | — | urn:li:corpuser:b2fd91.brock1@example.com |
| order_details | dataset | 3 | **SAFE** | 4 | — | urn:li:corpuser:b2fd91.marty@example.com, urn:li:corpuser:b2fd91.EMP006, urn:li:corpGroup:b2fd91.ORG_DATA_PLATFORM, urn:li:corpuser:b2fd91.alex@example.com |
| ORDER_DETAILS | dataset | 3 | **SAFE** | 4 | — | urn:li:corpuser:b2fd91.kirk@example.com |
| Order Details | dataset | 4 | **SAFE** | 1 | — | urn:li:corpGroup:b2fd91.ORG_DATA_PLATFORM, urn:li:corpGroup:b2fd91.ORG_BACKEND_ENG, urn:li:corpuser:b2fd91.EMP006 |
| Promotions | dataset | 4 | **SAFE** | 1 | — | urn:li:corpuser:b2fd91.brock1@example.com |
| Order Mode | dataset | 4 | **SAFE** | 1 | — | urn:li:corpuser:b2fd91.brock1@example.com |
| Orders By Day | dataset | 4 | **SAFE** | 1 | — | urn:li:corpuser:b2fd91.brock1@example.com |
| Top Product Category | dataset | 4 | **SAFE** | 1 | — | urn:li:corpuser:b2fd91.brock1@example.com |

## Why these scores

- **credit_limit** (90): +45 declared as a source of this ML entity; +15 consumer is a mlFeature; +25 reads directly from the changed table; +5 no owner assigned; change kind drop_column multiplier x1.0; = 90 -> BREAKING
- **customer_churn_model** (67): +45 declared as a source of this ML entity; +20 consumer is a mlModel; -3 2 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 67 -> BREAKING
- **prod-retention-service** (64): +45 declared as a source of this ML entity; +20 consumer is a mlModelDeployment; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 64 -> BREAKING
- **customer_churn_features** (62): +45 declared as a source of this ML entity; +15 consumer is a mlFeatureTable; -3 2 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 62 -> BREAKING
- **country_id** (55): +10 table-level dependency only; +15 consumer is a mlFeature; +25 reads directly from the changed table; +5 no owner assigned; change kind drop_column multiplier x1.0; = 55 -> RISKY
- **customer_class** (55): +10 table-level dependency only; +15 consumer is a mlFeature; +25 reads directly from the changed table; +5 no owner assigned; change kind drop_column multiplier x1.0; = 55 -> RISKY
- **customer_since** (55): +10 table-level dependency only; +15 consumer is a mlFeature; +25 reads directly from the changed table; +5 no owner assigned; change kind drop_column multiplier x1.0; = 55 -> RISKY
- **customer_churn_models** (44): +45 declared as a source of this ML entity; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 44 -> RISKY
- **order_details** (35): +10 table-level dependency only; +25 reads directly from the changed table; change kind drop_column multiplier x1.0; = 35 -> RISKY
- **datahub_order_entries** (11): +10 table-level dependency only; +10 consumer is a dashboard; -9 4 hops downstream; change kind drop_column multiplier x1.0; = 11 -> SAFE
- **Order Entry Dashboard** (10): +10 table-level dependency only; +10 consumer is a dashboard; -15 6 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 10 -> SAFE
- **order_history** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **ORDER_HISTORY** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Customer Analytics Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Essential KPI Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Geographic Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Product Perfromance Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Time Inteligence Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Custom SQL Query** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **ORDER_DETAILS** (7): +10 table-level dependency only; -3 2 hops downstream; change kind drop_column multiplier x1.0; = 7 -> SAFE
- **Orders By Month** (6): +10 table-level dependency only; +8 consumer is a chart; -12 5 hops downstream; change kind drop_column multiplier x1.0; = 6 -> SAFE
- **Popular Products Categories** (6): +10 table-level dependency only; +8 consumer is a chart; -12 5 hops downstream; change kind drop_column multiplier x1.0; = 6 -> SAFE
- **Promotions** (6): +10 table-level dependency only; +8 consumer is a chart; -12 5 hops downstream; change kind drop_column multiplier x1.0; = 6 -> SAFE
- **Order Mode** (6): +10 table-level dependency only; +8 consumer is a chart; -12 5 hops downstream; change kind drop_column multiplier x1.0; = 6 -> SAFE
- **Order Entry Dashboard** (5): +10 table-level dependency only; +10 consumer is a dashboard; -15 6 hops downstream; change kind drop_column multiplier x1.0; = 5 -> SAFE
- **order_details** (4): +10 table-level dependency only; -6 3 hops downstream; change kind drop_column multiplier x1.0; = 4 -> SAFE
- **ORDER_DETAILS** (4): +10 table-level dependency only; -6 3 hops downstream; change kind drop_column multiplier x1.0; = 4 -> SAFE
- **Order Details** (1): +10 table-level dependency only; -9 4 hops downstream; change kind drop_column multiplier x1.0; = 1 -> SAFE
- **Promotions** (1): +10 table-level dependency only; -9 4 hops downstream; change kind drop_column multiplier x1.0; = 1 -> SAFE
- **Order Mode** (1): +10 table-level dependency only; -9 4 hops downstream; change kind drop_column multiplier x1.0; = 1 -> SAFE
- **Orders By Day** (1): +10 table-level dependency only; -9 4 hops downstream; change kind drop_column multiplier x1.0; = 1 -> SAFE
- **Top Product Category** (1): +10 table-level dependency only; -9 4 hops downstream; change kind drop_column multiplier x1.0; = 1 -> SAFE

# Fuse impact report — test-01-drop-column

**Change:** drop_column orders.promotion_id  
**Max severity:** BREAKING  
**Generated:** 2026-07-30T17:56:05+00:00

| Asset | Type | Hops | Severity | Score | Evidence | Owners |
|---|---|---|---|---|---|---|
| order_details | dataset | 1 | **BREAKING** | 60 | schema carries a field named `promotion_id` | urn:li:corpGroup:b2fd91.1e0398a3-113f-475e-b6fc-32ab72a634d2, urn:li:corpGroup:b2fd91.ORG_DATA_PLATFORM, urn:li:corpuser:b2fd91.EMP006, urn:li:corpuser:b2fd91.brock1@example.com, urn:li:corpuser:b2fd91.bryan@example.com, urn:li:corpuser:b2fd91.jonny1@example.com, urn:li:corpuser:b2fd91.jonny2@example.com, urn:li:corpuser:b2fd91.kirk@example.com, urn:li:corpuser:b2fd91.marty@example.com, urn:li:corpuser:b2fd91.sam@example.com |
| ORDER_DETAILS | dataset | 2 | **RISKY** | 32 | schema carries a field named `promotion_id` | urn:li:corpGroup:b2fd91.1e0398a3-113f-475e-b6fc-32ab72a634d2, urn:li:corpuser:b2fd91.brock1@example.com, urn:li:corpuser:b2fd91.jonny1@example.com |
| datahub_order_entries | dashboard | 4 | **SAFE** | 11 | — | urn:li:corpuser:b2fd91.sam@example.com, urn:li:corpuser:b2fd91.michael@example.com, urn:li:corpuser:b2fd91.patrick1@example.com, urn:li:corpuser:b2fd91.alex@example.com |
| Popular Products | chart | 5 | **SAFE** | 11 | — | — |
| Promotions | chart | 5 | **SAFE** | 11 | — | — |
| Order Mode | chart | 5 | **SAFE** | 11 | — | — |
| Order Entry Dashboard | dashboard | 6 | **SAFE** | 10 | — | — |
| order_history | dataset | 3 | **SAFE** | 9 | — | — |
| ORDER_HISTORY | dataset | 3 | **SAFE** | 9 | — | — |
| Customer Analytics Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Essential KPI Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Geographic Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Product Perfromance Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Time Inteligence Measures | dataset | 3 | **SAFE** | 9 | — | — |
| Custom SQL Query | dataset | 3 | **SAFE** | 9 | — | — |
| Custom SQL Query | dataset | 3 | **SAFE** | 9 | — | — |
| Custom SQL Query | dataset | 3 | **SAFE** | 9 | — | — |
| Custom SQL Query | dataset | 3 | **SAFE** | 9 | — | — |
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

- **order_details** (60): +35 consumer schema has a field with that name; +25 reads directly from the changed table; change kind drop_column multiplier x1.0; = 60 -> BREAKING
- **ORDER_DETAILS** (32): +35 consumer schema has a field with that name; -3 2 hops downstream; change kind drop_column multiplier x1.0; = 32 -> RISKY
- **datahub_order_entries** (11): +10 table-level dependency only; +10 consumer is a dashboard; -9 4 hops downstream; change kind drop_column multiplier x1.0; = 11 -> SAFE
- **Popular Products** (11): +10 table-level dependency only; +8 consumer is a chart; -12 5 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 11 -> SAFE
- **Promotions** (11): +10 table-level dependency only; +8 consumer is a chart; -12 5 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 11 -> SAFE
- **Order Mode** (11): +10 table-level dependency only; +8 consumer is a chart; -12 5 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 11 -> SAFE
- **Order Entry Dashboard** (10): +10 table-level dependency only; +10 consumer is a dashboard; -15 6 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 10 -> SAFE
- **order_history** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **ORDER_HISTORY** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Customer Analytics Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Essential KPI Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Geographic Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Product Perfromance Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Time Inteligence Measures** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Custom SQL Query** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Custom SQL Query** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Custom SQL Query** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
- **Custom SQL Query** (9): +10 table-level dependency only; -6 3 hops downstream; +5 no owner assigned; change kind drop_column multiplier x1.0; = 9 -> SAFE
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

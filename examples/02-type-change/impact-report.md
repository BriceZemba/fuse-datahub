# Fuse impact report - 02-type-change

**Change:** orders.order_total retyped DOUBLE -> INT  
**Max severity:** BREAKING  
**Generated:** 2026-08-05T13:50:44+00:00

| Asset | Type | Hops | Severity | Score | Evidence | Owners |
|---|---|---|---|---|---|---|
| order_details | dataset | 1 | **BREAKING** | 70 | column-level lineage edge from orders.order_total | urn:li:corpGroup:b2fd91.1e0398a3-113f-475e-b6fc-32ab72a634d2, urn:li:corpGroup:b2fd91.ORG_DATA_PLATFORM, urn:li:corpuser:b2fd91.EMP006, urn:li:corpuser:b2fd91.brock1@example.com, urn:li:corpuser:b2fd91.bryan@example.com, urn:li:corpuser:b2fd91.jonny1@example.com, urn:li:corpuser:b2fd91.jonny2@example.com, urn:li:corpuser:b2fd91.kirk@example.com, urn:li:corpuser:b2fd91.marty@example.com, urn:li:corpuser:b2fd91.sam@example.com |
| order_history | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| ORDER_HISTORY | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| Customer Analytics Measures | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| Essential KPI Measures | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| Geographic Measures | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| Product Perfromance Measures | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| Time Inteligence Measures | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| Custom SQL Query | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| Custom SQL Query | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| ORDER_DETAILS_REPLICA | dataset | 3 | **RISKY** | 44 | column-level lineage edge from orders.order_total | - |
| ORDER_DETAILS | dataset | 2 | **RISKY** | 42 | column-level lineage edge from orders.order_total | urn:li:corpGroup:b2fd91.1e0398a3-113f-475e-b6fc-32ab72a634d2, urn:li:corpuser:b2fd91.brock1@example.com, urn:li:corpuser:b2fd91.jonny1@example.com |
| order_details | dataset | 3 | **RISKY** | 39 | column-level lineage edge from orders.order_total | urn:li:corpuser:b2fd91.marty@example.com, urn:li:corpuser:b2fd91.EMP006, urn:li:corpGroup:b2fd91.ORG_DATA_PLATFORM, urn:li:corpuser:b2fd91.alex@example.com |
| ORDER_DETAILS | dataset | 3 | **RISKY** | 39 | column-level lineage edge from orders.order_total | urn:li:corpuser:b2fd91.kirk@example.com |
| Order Details | dataset | 4 | **RISKY** | 36 | column-level lineage edge from orders.order_total | urn:li:corpGroup:b2fd91.ORG_DATA_PLATFORM, urn:li:corpGroup:b2fd91.ORG_BACKEND_ENG, urn:li:corpuser:b2fd91.EMP006 |
| Promotions | dataset | 4 | **RISKY** | 36 | column-level lineage edge from orders.order_total | urn:li:corpuser:b2fd91.brock1@example.com |
| Order Mode | dataset | 4 | **RISKY** | 36 | column-level lineage edge from orders.order_total | urn:li:corpuser:b2fd91.brock1@example.com |

## Why these scores

- **order_details** (70): +45 column-level lineage edge in DataHub; +25 reads directly from the changed table; narrowing type change DOUBLE -> INT treated as lossy; = 70 -> BREAKING
- **order_history** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **ORDER_HISTORY** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **Customer Analytics Measures** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **Essential KPI Measures** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **Geographic Measures** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **Product Perfromance Measures** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **Time Inteligence Measures** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **Custom SQL Query** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **Custom SQL Query** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **ORDER_DETAILS_REPLICA** (44): +45 column-level lineage edge in DataHub; -6 3 hops downstream; +5 no owner assigned; narrowing type change DOUBLE -> INT treated as lossy; = 44 -> RISKY
- **ORDER_DETAILS** (42): +45 column-level lineage edge in DataHub; -3 2 hops downstream; narrowing type change DOUBLE -> INT treated as lossy; = 42 -> RISKY
- **order_details** (39): +45 column-level lineage edge in DataHub; -6 3 hops downstream; narrowing type change DOUBLE -> INT treated as lossy; = 39 -> RISKY
- **ORDER_DETAILS** (39): +45 column-level lineage edge in DataHub; -6 3 hops downstream; narrowing type change DOUBLE -> INT treated as lossy; = 39 -> RISKY
- **Order Details** (36): +45 column-level lineage edge in DataHub; -9 4 hops downstream; narrowing type change DOUBLE -> INT treated as lossy; = 36 -> RISKY
- **Promotions** (36): +45 column-level lineage edge in DataHub; -9 4 hops downstream; narrowing type change DOUBLE -> INT treated as lossy; = 36 -> RISKY
- **Order Mode** (36): +45 column-level lineage edge in DataHub; -9 4 hops downstream; narrowing type change DOUBLE -> INT treated as lossy; = 36 -> RISKY

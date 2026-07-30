{{ config(materialized='table') }}

-- Feeds the `customer_churn_features` feature table, which feeds the churn model
-- deployed to production. Changing this file is never a local decision.
--
-- Columns mirror the real `order_entry.customers` table in the showcase catalog.

select
    customer_id,
    customer_class,
    customer_since,
    credit_limit,
    country_id,
    region_id
from {{ source('order_entry', 'customers') }}

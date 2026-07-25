{{ config(materialized='table') }}

-- Feeds the `customer_churn_features` feature table, which feeds the churn model
-- deployed to production. Changing this file is never a local decision.

select
    customer_id,
    order_count,
    lifetime_value,
    discounted_orders,
    datediff('day', max_order_date, current_date()) as days_since_last_order
from {{ ref('customer_ltv') }}

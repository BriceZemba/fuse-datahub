{{ config(materialized='table') }}

-- Feeds the `customer_churn_features` feature table, which feeds the churn model
-- deployed to production. Changing this file is never a local decision.
--
-- Model names in this project mirror tables that exist in the showcase-ecommerce
-- catalog, so a local diff resolves onto the real DataHub graph.

select
    customer_id,
    order_count,
    lifetime_value,
    discounted_orders,
    datediff('day', max_order_date, current_date()) as days_since_last_order
from {{ ref('order_details') }}

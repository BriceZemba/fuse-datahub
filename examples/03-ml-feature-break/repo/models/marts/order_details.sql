{{ config(materialized='table') }}

-- Mirrors `analytics.order_details`, the wide reporting table every dashboard in the
-- showcase catalog reads from.

select
    order_id,
    customer_id,
    order_date,
    order_total,
    promotion_id,
    payment_method_code,
    cost_of_delivery
from {{ ref('orders') }}

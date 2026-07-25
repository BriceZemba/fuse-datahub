{{ config(materialized='view') }}

-- Columns mirror the real `order_entry.orders` table in the showcase-ecommerce
-- catalog, so a diff against this project resolves onto the actual DataHub graph.

select
    order_id,
    customer_id,
    order_date,
    order_status,
    order_mode,
    promotion_id,
    payment_method_code,
    order_total,
    cost_of_delivery,
    warehouse_id
from {{ source('order_entry', 'orders') }}

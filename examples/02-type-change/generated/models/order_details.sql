{{ config(materialized='table') }}

select
    order_id,
    customer_id,
    order_date,
    cast(order_total as double) as order_total,
    promotion_id,
    payment_method_code,
    cost_of_delivery
from {{ ref('orders') }}

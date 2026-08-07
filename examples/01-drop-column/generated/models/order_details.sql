{{ config(materialized='table') }}

select
    order_id,
    customer_id,
    order_date,
    order_total,
    payment_method_code,
    cost_of_delivery
from {{ ref('orders') }}

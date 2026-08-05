{{ config(materialized='table') }}

select
    order_id,
    customer_id,
    order_date,
    promotion_id,
    payment_method_code,
    cost_of_delivery
from {{ ref('orders') }}

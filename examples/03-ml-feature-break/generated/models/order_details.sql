{{ config(materialized='table') }}

select
    null as order_id,
    customer_id,
    null as order_date,
    null as order_total,
    null as promotion_id,
    null as payment_method_code,
    null as cost_of_delivery
from {{ ref('orders') }}

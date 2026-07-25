{{ config(materialized='table') }}

select
    customer_id,
    count(order_id) as order_count,
    sum(order_amount) as lifetime_value,
    count(discount_code) as discounted_orders
from {{ ref('orders') }}
group by customer_id

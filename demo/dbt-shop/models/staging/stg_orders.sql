{{ config(materialized='view') }}

select
    order_id,
    customer_id,
    order_date,
    status,
    discount_code,
    amount,
    updated_at
from {{ source('shop', 'raw_orders') }}

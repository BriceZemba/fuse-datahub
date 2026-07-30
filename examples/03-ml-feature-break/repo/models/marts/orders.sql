{{ config(materialized='table') }}

with source as (

    select * from {{ ref('stg_orders') }}

)

select
    order_id,
    customer_id,
    order_date,
    order_status,
    order_mode,
    promotion_id,
    payment_method_code,
    cast(order_total as float) as order_total
from source

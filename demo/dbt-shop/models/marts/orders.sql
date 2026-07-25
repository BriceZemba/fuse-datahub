{{ config(materialized='table') }}

with source as (

    select * from {{ ref('stg_orders') }}

)

select
    order_id,
    customer_id,
    order_date,
    status,
    discount_code,
    cast(amount as float) as order_amount
from source

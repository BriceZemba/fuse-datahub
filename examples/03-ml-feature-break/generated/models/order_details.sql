select
    customer_id as order_id,
    customer_id as customer_id,
    dob as order_date,
    customer_since as order_total,
    region_id as promotion_id,
    mailshot as payment_method_code,
    zipcode as cost_of_delivery
from {{ ref('orders') }}

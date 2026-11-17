-- Holiday Shelf | Query 1 of 4: product events (the main dataset)
--
-- Run in the BigQuery console (billing project holiday-shelf-110920130).
-- Download the result as CSV and save it as:  data/raw_events_v2.csv
-- Used by: pipeline.py  ->  product_summary.csv, weekly.csv, country_device.csv
--
-- One row per product x day x country x device, with the number of shopping sessions
-- that viewed it, added it to the cart, began checkout, purchased it, or saw it in a
-- promotion, plus revenue. Period: 2020-11-01 to 2021-01-31.
-- Key design choice: products are joined by item_name, NOT item_id, because GA4 gives
-- the same product different item_ids on view events and on cart/purchase events.

WITH base AS (
  SELECT
    event_date,
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
    event_name,
    geo.country AS country,
    device.category AS device_category,
    item.item_id,
    item.item_name,
    item.item_category,
    item.price,
    item.quantity,
    item.promotion_name
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`,
    UNNEST(items) AS item
  WHERE event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase', 'view_promotion')
    AND _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
),

sessioned AS (
  SELECT
    CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)) AS session_key,
    event_date,
    event_name,
    country,
    device_category,
    -- Join key is NAME, not item_id, because item_id is inconsistent across event types.
    item_name,
    item_category,
    price,
    quantity,
    promotion_name
  FROM base
  WHERE ga_session_id IS NOT NULL
    AND item_name IS NOT NULL
    AND item_name != '(not set)'
)

-- NOTE: no blanket SELECT DISTINCT here anymore. An earlier version of this query
-- added one to stop a view_item event's multi-product array from inflating view
-- counts, but COUNT(DISTINCT session_key ...) below already handles that correctly
-- on its own (it dedupes per session regardless of how many raw rows exist). The
-- blanket DISTINCT was instead silently collapsing genuine repeat purchases — same
-- item, same price, same quantity, bought twice in one session — into a single
-- purchase, which undercounted revenue by about 9% in testing. Removed.

SELECT
  item_name,
  -- category can still vary by row for the same name; pick the most common later in pandas
  ANY_VALUE(item_category) AS item_category_sample,
  event_date,
  country,
  device_category,
  COUNT(DISTINCT CASE WHEN event_name = 'view_item' THEN session_key END) AS sessions_viewed,
  COUNT(DISTINCT CASE WHEN event_name = 'add_to_cart' THEN session_key END) AS sessions_added_to_cart,
  COUNT(DISTINCT CASE WHEN event_name = 'begin_checkout' THEN session_key END) AS sessions_checkout,
  COUNT(DISTINCT CASE WHEN event_name = 'purchase' THEN session_key END) AS sessions_purchased,
  COUNT(DISTINCT CASE WHEN event_name = 'view_promotion' THEN session_key END) AS sessions_viewed_promo,
  SUM(CASE WHEN event_name = 'purchase' THEN price * quantity ELSE 0 END) AS revenue,
  MAX(promotion_name) AS promotion_name
FROM sessioned
GROUP BY item_name, event_date, country, device_category
ORDER BY revenue DESC

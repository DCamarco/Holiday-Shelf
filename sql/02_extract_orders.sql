-- Holiday Shelf | Query 2 of 4: orders (for Bundles & Cart Rescue)
--
-- Output: one row per (order, product). Products are keyed by item_name, NOT item_id,
-- because item_id differs between view events and purchase events (the ID bug fixed in B1).
-- Purchase events alone are used here, so the name key is just for consistency with the
-- rest of the app (product_summary.csv is keyed on item_name).
--
-- Run in the BigQuery console with billing project holiday-shelf-110920130.
-- Download as CSV and save as:  data/orders_v2.csv
-- Used by: build_bundles.py  ->  bundle_pairs.csv, cart_rescue.csv; also the order stats in the app
--
-- Expected: roughly 4,451 distinct orders averaging ~2.8 items each (per the plan).
-- Orders with a missing / "(not set)" transaction_id are excluded because we can't tell
-- which items belong together without a real order id. If the order count is far below
-- 4,451, tell me and we'll look at how many were dropped.
--
-- MAX() for price / quantity: if the same purchase event is logged twice (page refresh),
-- SUM would double the quantity. MAX keeps one copy and is safe for pair-counting.

SELECT
  ecommerce.transaction_id AS transaction_id,
  item.item_name AS item_name,
  MAX(item.item_category) AS item_category,
  MAX(item.price) AS price,
  MAX(item.quantity) AS quantity,
  MIN(event_date) AS event_date,
  ANY_VALUE(geo.country) AS country,
  ANY_VALUE(device.category) AS device_category
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`,
  UNNEST(items) AS item
WHERE event_name = 'purchase'
  AND _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
  AND ecommerce.transaction_id IS NOT NULL
  AND ecommerce.transaction_id != '(not set)'
  AND item.item_name IS NOT NULL
  AND item.item_name != '(not set)'
GROUP BY 1, 2
ORDER BY transaction_id, item_name

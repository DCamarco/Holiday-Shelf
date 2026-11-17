-- Holiday Shelf | Query 4 of 4 (OPTIONAL): find product names spelled differently on cart vs purchase events
--
-- Run in the BigQuery console (billing project holiday-shelf-110920130).
-- Download the result as CSV and save it as:  data/name_crosswalk.csv
-- Used by: names.py (read by pipeline.py and build_bundles.py)
--
-- IDEA
--   If a shopper adds product A to the cart and then buys "product B", and B has almost
--   no add_to_cart events under its own name, then B is probably just a second spelling
--   of A. We count, for every such B, which cart product A shows up in the same session
--   most often. The pipeline (names.py) only trusts a match when:
--     * A appears in at least 60% of B's purchase sessions,
--     * A beats the runner-up candidate by 2x or more,
--     * A and B have the same typical price, and
--     * at least 5 sessions support it.
--
-- WHAT B AND A LOOK LIKE
--   B (purchase-side spelling): 5+ purchase sessions, but cart sessions < 20% of purchase sessions.
--   A (cart-side spelling):     20+ cart sessions, and purchase sessions <= 25% of its cart sessions.
--
-- Output: up to 2 candidates (rank 1 and 2) per B, so the pipeline can see the runner-up.

WITH raw AS (
  SELECT
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
    event_name,
    item.item_name AS item_name,
    item.price AS price
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`,
    UNNEST(items) AS item
  WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
    AND event_name IN ('view_item', 'add_to_cart', 'purchase')
    AND item.item_name IS NOT NULL
    AND item.item_name != '(not set)'
),

events AS (
  SELECT
    CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING)) AS session_key,
    event_name, item_name, price
  FROM raw
  WHERE ga_session_id IS NOT NULL
),

name_stats AS (
  SELECT
    item_name,
    COUNT(DISTINCT IF(event_name = 'add_to_cart', session_key, NULL)) AS cart_sessions,
    COUNT(DISTINCT IF(event_name = 'purchase', session_key, NULL)) AS purchase_sessions,
    APPROX_QUANTILES(price, 2)[OFFSET(1)] AS typical_price
  FROM events
  GROUP BY item_name
),

purchase_side AS (   -- B: bought a lot, almost never carted under this name
  SELECT item_name, purchase_sessions, typical_price
  FROM name_stats
  WHERE purchase_sessions >= 5
    AND cart_sessions < 0.2 * purchase_sessions
),

cart_side AS (       -- A: carted a lot, rarely bought under this name
  SELECT item_name, typical_price
  FROM name_stats
  WHERE cart_sessions >= 20
    AND purchase_sessions <= 0.25 * cart_sessions
),

carts AS (
  SELECT DISTINCT session_key, item_name AS cart_name
  FROM events WHERE event_name = 'add_to_cart'
),

buys AS (
  SELECT DISTINCT session_key, item_name AS purchase_name
  FROM events WHERE event_name = 'purchase'
),

together AS (
  SELECT
    b.purchase_name,
    c.cart_name,
    COUNT(DISTINCT b.session_key) AS sessions_together
  FROM buys b
  JOIN carts c USING (session_key)
  WHERE b.purchase_name IN (SELECT item_name FROM purchase_side)
    AND c.cart_name IN (SELECT item_name FROM cart_side)
    AND b.purchase_name != c.cart_name
  GROUP BY 1, 2
),

ranked AS (
  SELECT
    t.*,
    ROW_NUMBER() OVER (PARTITION BY t.purchase_name ORDER BY t.sessions_together DESC, t.cart_name) AS candidate_rank
  FROM together t
)

SELECT
  r.purchase_name,
  r.cart_name,
  r.candidate_rank,
  r.sessions_together,
  p.purchase_sessions AS purchase_sessions_total,
  SAFE_DIVIDE(r.sessions_together, p.purchase_sessions) AS share_of_purchase_sessions,
  p.typical_price AS purchase_price,
  c.typical_price AS cart_price,
  ABS(p.typical_price - c.typical_price) < 0.01 AS price_match
FROM ranked r
JOIN purchase_side p ON p.item_name = r.purchase_name
JOIN cart_side c ON c.item_name = r.cart_name
WHERE r.candidate_rank <= 2
ORDER BY r.purchase_name, r.candidate_rank

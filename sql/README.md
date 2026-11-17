# SQL queries

All data comes from one public BigQuery dataset: `bigquery-public-data.ga4_obfuscated_sample_ecommerce` (Google Merchandise Store, GA4 export), 1 Nov 2020 – 31 Jan 2021.

Run each query in the BigQuery console, download the result as CSV, and save it in the project's `data/` folder under the name shown. The Python scripts then build everything the app reads.

| # | Query | Save result as | Used by | Required? |
|---|---|---|---|---|
| 1 | `01_extract_events.sql` | `data/raw_events_v2.csv` | `pipeline.py` | Yes. The main dataset: sessions that viewed, carted, checked out and bought each product. |
| 2 | `02_extract_orders.sql` | `data/orders_v2.csv` | `build_bundles.py`, app order stats | Yes. One row per order and product, for bought-together pairs and Cart Rescue. |
| 3 | `03_extract_banners.sql` | `data/banner_performance.csv` | Banner Performance page | Yes. Views, clicks and later buyers for each banner. |
| 4 | `04_find_name_crosswalk.sql` | `data/name_crosswalk.csv` | `names.py` | Optional. Looks for products spelled two ways. The hand-checked `data/name_aliases.csv` already covers the clear cases. |

## Key design choices
- **Products are joined by name, not ID.** GA4 gives the same product different `item_id` values on view events and on cart/purchase events. Joining on ID made nearly every purchased product look unviewed.
- **No blanket `SELECT DISTINCT` in query 1.** `COUNT(DISTINCT session_key ...)` already counts each session once. An earlier version added `DISTINCT` and silently merged genuine repeat purchases, under-counting revenue by about 9%.
- **Revenue check:** query 1 totals $362,403, which matches the raw data exactly.
- **Orders:** orders with a missing transaction ID are excluded, since items cannot be grouped without one. Query 2 returns 4,451 orders.
- **Banner buyers:** `buyers` counts people who bought after their first click. `buyers_any_time` also counts people who bought at any point in the period. The app uses the strict `buyers` column.

## After downloading
```bash
python pipeline.py        # builds product_summary.csv, weekly.csv, country_device.csv
python build_bundles.py   # builds bundle_pairs.csv, cart_rescue.csv
```

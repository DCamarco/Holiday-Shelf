# Holiday Shelf

A merchandising planner for the holiday season. It turns a year of shopper behaviour into a short, defensible shelf plan: **which 10–15 products to feature, in which holiday phase, in which slot, what each one replaces, how confident we are, and how to test it.**

## Project Description

**Client:** the store merchandiser, who decides what goes on the homepage, category pages and promo banners.

**The problem:** a store sells hundreds of products but only a handful can be featured, and featuring is a bet. Raw popularity ("most views") is misleading because views are not sales. Some products get lots of views but few buyers (window-shopping). Others convert very well but almost nobody sees them. A wrong bet wastes prime shelf space during the highest-stakes weeks of the year.

**The answer this app gives:** a shelf plan the merchandiser can export (CSV and one-page PDF brief), backed by evidence from last season and a test plan for this one.

**Data:** the public GA4 sample e-commerce dataset from the Google Merchandise Store (`bigquery-public-data.ga4_obfuscated_sample_ecommerce`), 1 Nov 2020 – 31 Jan 2021. The data is obfuscated and covers one store and one holiday season, so results are hypotheses to test, not forecasts.

## App Deployment URL

[Add deployed app link here]

## Local Setup Instructions

Requires Python 3.10 or newer. All data files the app needs are already in the `data/` folder, so you do not need BigQuery access to run it.

```bash
git clone https://github.com/hkoradiy-dev/Holiday-Shelf.git
cd Holiday-Shelf
```

**Option A: uv**

```bash
uv run --with-requirements requirements.txt streamlit run app.py
```

**Option B: pip**

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`. Use the three-dot menu (top right) → **Settings** → **Theme** to switch between Light, Dark and your system setting.

**Run the tests (optional):**

```bash
pip install pytest
python -m pytest -q tests
```

## What the App Does

| Page | Question it answers |
|---|---|
| **Overview** | What does the season look like at a glance, and where are the best opportunities? |
| **Shelf Scorecard** | Which products are Stars, Hidden Gems or Window-Shoppers? Each product is a bubble: views (log scale) against the share of viewers who buy, sized by revenue. |
| **Opportunity Finder** | Which under-exposed products convert unusually well? Ranked by the cautious lower end of a 95% confidence interval, each paired with a weaker same-category product it could replace. |
| **Bundles & Cart Rescue** | Which products are bought together (cart add-on ideas), and which products are added to the cart often but rarely bought? |
| **Banner Performance** | For each homepage banner: views, clicks, and how many people who clicked later bought. |
| **Season Playbook** | Which holiday phase suits each product? Weekly demand by phase, historical USPS shipping deadlines, a shipping-cutoff check, and Google Trends search interest for context. |
| **Shortlist Builder** | The deliverable. Tick 10–15 products, assign a phase, a slot (homepage / category page / promo banner / cart add-on) and a product to replace. A live summary shows category mix, price mix and how many picks rest on weak data. Each pick gets a two-week test plan ("you need about N visits per variant"). Export as CSV and a one-page PDF brief. |
| **AI Shortlist Reviewer** | *Coming soon. Section reserved for the AI feature; to be documented here.* |

Products added from the Scorecard, Opportunity Finder, Bundles page or Season Playbook all flow into one shared shortlist.

## How the Numbers Are Built

### The data problem we found and fixed
GA4 records the same product under **two different IDs**: one on view events and another on add-to-cart and purchase events (for example, "Google NYC Campus Mug" appears as `GGOEGDWB140099` when viewed but under a numeric ID when bought). Joining on ID made about 800 of 811 purchased products look as if nobody had ever viewed them, which we had first misread as a tracking gap.

**Fix:** products are joined on **product name**, not ID (`sql/01_extract_events.sql`). After the fix, revenue reconciles exactly to the raw data ($362,403), and the share of products flagged as unreliable fell from about 49% to under 2%.

A few products are also spelled differently between cart and purchase events. These are handled in `names.py`: hand-checked aliases (`data/name_aliases.csv`) plus an optional session-based crosswalk (`sql/04_find_name_crosswalk.sql`). A name is only merged if the evidence is clear. Products whose purchases still cannot be matched are labelled **Not Enough Data** and kept out of the Opportunity Finder and Cart Rescue instead of being guessed.

### Key rules
- **Quadrants** (Star, Hidden Gem, Window-Shopper, Low Priority) use a median split on views and on view-to-purchase rate. The rate comparison is strict (`>`) because the median rate can be 0.
- **Minimum view floor:** products under 100 viewing sessions are labelled Not Enough Data.
- **Confidence:** rates carry a Wilson 95% interval. Opportunities are ranked by the interval's lower bound ("at least X% of viewers buy") so a lucky small sample cannot beat a solid one.
- **Bundles:** pairs are ranked by number of orders containing both products. Lift is shown but not used for ranking, because it rewards rare items. The pricier product is the anchor and the cheaper one the add-on. Colour and size variants of one product are hidden by default.
- **Cart Rescue:** products with 100+ cart sessions and a cart-to-purchase rate below the catalog median, ranked by carts that did not end in a purchase.
- **Banners:** "bought later" means the person bought after their first click on the banner. Banners with fewer than 100 clickers are left out of the comparison.
- **Test plan:** a two-sided test, 95% confidence, 80% power, aiming to detect a 20% relative lift in conversion.

## Data Pipeline (to regenerate the data)

The CSVs in `data/` are already committed. To rebuild them you need Google Cloud BigQuery access to the public dataset.

1. Run the extract queries in the BigQuery console and save each result into `data/`:

| Query | Save result as |
|---|---|
| `sql/01_extract_events.sql` | `data/raw_events_v2.csv` |
| `sql/02_extract_orders.sql` | `data/orders_v2.csv` |
| `sql/03_extract_banners.sql` | `data/banner_performance.csv` |
| `sql/04_find_name_crosswalk.sql` (optional) | `data/name_crosswalk.csv` |

See [`sql/README.md`](sql/README.md) for what each query does and why.

2. Build the app's data files:

```bash
python pipeline.py          # product_summary.csv, weekly.csv, country_device.csv
python build_bundles.py     # bundle_pairs.csv, cart_rescue.csv
```

`data/google_trends_hoodie.csv` is a manual Google Trends export (US web search, keyword "hoodie"), used for seasonal context only.

## Project Structure

```
app.py                  Entry point: page setup, sidebar and navigation only
views/                  One file per page. Each has a render() function; edit a page here
  overview.py
  shelf_scorecard.py
  opportunity_finder.py
  bundles_cart_rescue.py
  banner_performance.py
  season_playbook.py
  shortlist_builder.py  Also holds the A/B test calculator and the PDF brief
shared.py               Data loaders and shortlist helpers used by every page
ui.py                   Look and feel: light and dark themes, cards, chart colours
pipeline.py             Cleans raw events; builds the product summary and weekly data
names.py                Product-name fixes shared by the pipeline scripts
build_bundles.py        Bought-together pairs and Cart Rescue list
sql/                    The BigQuery queries (01-04) that produce the raw CSVs, with a README
data/                   Input and output CSVs
tests/                  Automated tests
.streamlit/config.toml  Theme settings
requirements.txt        Python dependencies
REPORT.MD               Project report
```

To change a page, open its file in `views/`. To add a page, create a new file in `views/` with a `render()` function and add one line to the `PAGES` list in `app.py`.

## Known Limitations

1. **One store, one season** (Google Merchandise Store, Nov 2020 – Jan 2021). Quadrant placement is a hypothesis to test this year, not a guarantee.
2. **Association, not causation.** Bundles and banner results show what happened together, not what caused it. People who click a banner may already have planned to buy.
3. **Some products stay unmatched.** A small number of products have carts but no matched purchases because of name differences, and are labelled Not Enough Data.
4. **Banner view counts are incomplete for the smaller banners** (clicks are nearly as high as views), so banners are compared on clicks and buyers, not views.
5. **`item_category` is inconsistent in the raw export.** The pipeline keeps the most common category per product, so treat category filters as approximate.
6. **Google Trends data is a manual snapshot**, not a live feed, and shows relative search interest rather than sales.

## Team

[Add team members and roles here]

## Acknowledgements

Data: Google Merchandise Store GA4 sample dataset, via BigQuery public datasets.

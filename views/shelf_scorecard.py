"""Shelf Scorecard: every product as a bubble (views vs purchase rate)."""

import plotly.express as px
import streamlit as st
from ui import LABEL_COLORS
import ui
from shared import add_to_shortlist, load_product_summary


def render():
    st.title("Shelf Scorecard")
    st.caption(
        "Each bubble is a product. X-axis: sessions that viewed the product (log scale — "
        "traffic varies by orders of magnitude, so a linear axis crams almost every product "
        "into one corner). Y-axis: share of those viewing sessions that converted to a "
        "purchase. Bubble size: revenue. Color: quadrant label."
    )

    df = load_product_summary()

    with st.expander("⚠️ Known data limitations — read before trusting this chart", expanded=False):
        n_flagged = int(df["views_likely_insufficient"].sum())
        n_unmatched = int(df["purchases_unmatched"].sum())
        st.markdown(
            f"""
- **Products are now matched by name, not by GA4's item_id.** We found that `view_item`
  events and `add_to_cart`/`purchase` events use two different ID systems for the same
  product. Joining by ID made it look like ~49% of products had zero views; joining by
  name instead drops that to {n_flagged} of {len(df)} products ({n_flagged/len(df):.1%}).
- **{n_flagged} products still show purchases exceeding their view count** — these are
  flagged `views_likely_insufficient` and should be read cautiously; everything else now
  uses real, trustworthy view counts.
- **{n_unmatched} products have carts but no recorded purchases** (100+ cart sessions, 0
  purchases). At the catalog's typical ~5% cart-to-purchase rate that is not plausible, so
  their purchases are probably logged under a different spelling of the name. Spelling
  variants are merged using shopper sessions (`data/name_crosswalk.csv`) plus a few
  hand-checked aliases (`data/name_aliases.csv`); these {n_unmatched} could
  not be matched safely, so they are labeled "Not Enough Data" rather than "Window-Shopper".
- **Minimum view floor is {int(df['min_views_floor'].iloc[0])} sessions.** Below that, a
  product is labeled "Not Enough Data" regardless of its rate.
- **This is one historical holiday season (Nov 2020 – Jan 2021).** Quadrant placement is a
  starting hypothesis to test this year, not a guarantee.
            """
        )

    categories = sorted(df["item_category"].dropna().unique().tolist())
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        selected_categories = st.multiselect("Category", categories, default=[])
    with col2:
        min_views = st.number_input("Minimum sessions viewed", min_value=0, value=0, step=50)
    with col3:
        hide_flagged = st.checkbox("Hide insufficient-view products", value=False)
    show_labels = st.multiselect(
        "Show quadrants",
        ["Star", "Hidden Gem", "Window-Shopper", "Low Priority", "Not Enough Data"],
        default=["Star", "Hidden Gem", "Window-Shopper", "Low Priority"],
    )

    plot_df = df.copy()
    if selected_categories:
        plot_df = plot_df[plot_df["item_category"].isin(selected_categories)]
    if min_views > 0:
        plot_df = plot_df[plot_df["sessions_viewed"] >= min_views]
    if hide_flagged:
        plot_df = plot_df[~plot_df["views_likely_insufficient"]]
    plot_df = plot_df[plot_df["label"].isin(show_labels)]

    # Log scale needs a strictly positive x; a product with 0 views can't sit on a log
    # axis, so give it a 1-session floor for display only (doesn't affect the real data).
    plot_df["display_views"] = plot_df["sessions_viewed"].clip(lower=1)
    # Still guard the rare >100% case for display, without hiding it from the table.
    plot_df["display_rate"] = plot_df["view_to_buy_rate"].clip(upper=1.0)

    if len(plot_df) == 0:
        st.warning("No products match the current filters.")
    else:
        fig = px.scatter(
            plot_df,
            x="display_views",
            y="display_rate",
            size="revenue",
            color="label",
            color_discrete_map=LABEL_COLORS,
            log_x=True,
            hover_name="item_name",
            hover_data={
                "item_category": True,
                "sessions_viewed": True,
                "sessions_purchased": True,
                "revenue": ":$.0f",
                "views_likely_insufficient": True,
                "display_views": False,
                "display_rate": False,
            },
            size_max=45,
            labels={
                "display_views": "Sessions Viewed (log scale)",
                "display_rate": "View → Purchase rate",
            },
        )
        fig.update_layout(height=600, legend_title_text="Quadrant")
        ui.plot(fig, width="stretch")

        n_flagged_shown = int(plot_df["views_likely_insufficient"].sum())
        st.caption(
            f"Showing {len(plot_df):,} of {len(df):,} products. "
            f"{n_flagged_shown} shown here have insufficient view data."
        )

    st.markdown("### Add products to your shortlist")
    pick_df = plot_df.sort_values("revenue", ascending=False).head(30)
    for _, row in pick_df.iterrows():
        c1, c2, c3, c4, c5 = st.columns([3, 1.3, 1.3, 1.3, 1])
        c1.write(row["item_name"])
        c2.write(f"{row['sessions_viewed']:,} views")
        c3.write(f"{row['view_to_buy_rate']:.1%} rate")
        c4.write(row["label"])
        key = f"add_scorecard_{row['item_name']}"
        if row["item_name"] in st.session_state.shortlist:
            c5.button("✓ Added", key=key, disabled=True)
        else:
            if c5.button("+ Add", key=key):
                add_to_shortlist(row.to_dict())
                st.rerun()

    with st.expander("View full table"):
        st.dataframe(
            plot_df[
                [
                    "item_name", "item_category", "sessions_viewed", "sessions_purchased",
                    "view_to_buy_rate", "view_to_buy_ci_low", "view_to_buy_ci_high",
                    "revenue", "label", "views_likely_insufficient",
                ]
            ].sort_values("revenue", ascending=False),
            width="stretch",
        )

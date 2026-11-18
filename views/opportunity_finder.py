"""Opportunity Finder: under-exposed products that convert well, with a suggested swap."""

import pandas as pd
import plotly.express as px
import streamlit as st
import ui
from shared import add_to_shortlist, load_product_summary


def render():
    st.title("Opportunity Finder")
    st.caption(
        "Products worth featuring: ranked by the cautious (lower-bound) end of their "
        "confidence interval — 'we're fairly confident at least X% of viewers buy' — "
        "not a single point estimate that could be a lucky fluke."
    )

    df = load_product_summary().copy()

    eligible = df[
        (df["sessions_viewed"] >= int(df["min_views_floor"].iloc[0]))
        & (~df["views_likely_insufficient"].astype(bool))
        & (~df["purchases_unmatched"].astype(bool))
        & df["view_to_buy_rate"].notna()
    ].copy()

    if eligible.empty:
        st.warning("No products meet the current data-quality rules.")
    else:
        median_views = float(eligible["sessions_viewed"].median())
        median_rate = float(eligible["view_to_buy_rate"].median())

        opportunities = eligible[
            (eligible["sessions_viewed"] < median_views)
            & (eligible["view_to_buy_rate"] > median_rate)
        ].copy()

        if opportunities.empty:
            st.info("No products currently meet the Opportunity criteria.")
        else:
            # Rank by the CONSERVATIVE end of the confidence interval, not a made-up
            # score. "At least X% of viewers buy, even in the worst plausible case"
            # is a number the merchandiser can actually defend in a room.
            opportunities = opportunities.sort_values(
                ["view_to_buy_ci_low", "revenue"], ascending=False
            )

            # Pair each opportunity with the weakest same-category product it could
            # replace: a Window-Shopper or Low Priority item in the same category
            # with the lowest conversion rate, so the suggestion is concrete, not
            # just "this is good" with no action attached.
            replace_candidates = df[df["label"].isin(["Window-Shopper", "Low Priority"])]

            def find_replacement(category):
                same_cat = replace_candidates[replace_candidates["item_category"] == category]
                if same_cat.empty:
                    return None
                weakest = same_cat.sort_values("view_to_buy_rate", ascending=True).iloc[0]
                return weakest["item_name"]

            opportunities["replaces"] = opportunities["item_category"].apply(find_replacement)

            c1, c2, c3 = st.columns(3)
            c1.metric("Qualified opportunities", f"{len(opportunities):,}")
            c2.metric("Median views threshold", f"{median_views:,.0f}")
            c3.metric("Median purchase-rate threshold", f"{median_rate:.1%}")

            st.markdown("### How an opportunity is identified")
            st.markdown(
                "A product qualifies when it has **at least the minimum view floor**, "
                "**below-median views**, an **above-median view-to-purchase rate**, and "
                "**sufficient view data** (not flagged). Ranking uses the lower bound of "
                "each product's confidence interval, so a product with a thin sample and "
                "a lucky high rate won't outrank a product with a smaller but more certain edge."
            )

            cat_options = sorted(opportunities["item_category"].dropna().unique().tolist())
            selected_cats = st.multiselect(
                "Filter opportunities by category", cat_options, default=[],
                key="opportunity_categories"
            )
            max_results = st.slider(
                "Number of opportunities to display", min_value=5,
                max_value=min(50, len(opportunities)), value=min(15, len(opportunities)),
                key="opportunity_count"
            )

            view = opportunities.copy()
            if selected_cats:
                view = view[view["item_category"].isin(selected_cats)]
            view = view.head(max_results)

            if view.empty:
                st.warning("No opportunities match this category filter.")
            else:
                fig = px.scatter(
                    view,
                    x="sessions_viewed",
                    y="view_to_buy_rate",
                    size="revenue",
                    color="item_category",
                    hover_name="item_name",
                    hover_data={
                        "sessions_viewed": ":,",
                        "sessions_purchased": ":,",
                        "view_to_buy_rate": ":.1%",
                        "view_to_buy_ci_low": ":.1%",
                        "revenue": ":$,.0f",
                    },
                    labels={
                        "sessions_viewed": "Sessions viewed",
                        "view_to_buy_rate": "View-to-purchase rate",
                        "item_category": "Category",
                    },
                    size_max=42,
                )
                fig.update_layout(height=480)
                ui.plot(fig, width="stretch")

                st.markdown("### Recommended opportunity shortlist")
                for _, row in view.iterrows():
                    with st.container(border=True):
                        c1, c2 = st.columns([3, 1])
                        c1.markdown(f"**{row['item_name']}**  ·  {row['item_category']}")
                        c1.caption(
                            f"{row['sessions_viewed']:,} views · "
                            f"{row['view_to_buy_rate']:.1%} observed rate "
                            f"(at least {row['view_to_buy_ci_low']:.1%} with 95% confidence) · "
                            f"${row['revenue']:,.0f} revenue"
                        )
                        if pd.notna(row["replaces"]):
                            c1.caption(f"🔁 Suggested swap: replace **{row['replaces']}** (same category, weaker conversion)")
                        else:
                            c1.caption("🔁 No same-category replacement candidate found")
                        key = f"add_opp_{row['item_name']}"
                        if row["item_name"] in st.session_state.shortlist:
                            c2.button("✓ Added", key=key, disabled=True)
                        else:
                            if c2.button("+ Add to shortlist", key=key):
                                add_to_shortlist(row.to_dict())
                                st.rerun()

                csv_data = view[[
                    "item_name", "item_category", "sessions_viewed", "sessions_purchased",
                    "view_to_buy_rate", "view_to_buy_ci_low", "revenue", "replaces",
                ]].to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download opportunity shortlist (CSV)",
                    data=csv_data,
                    file_name="holiday_shelf_opportunities.csv",
                    mime="text/csv",
                )

            st.caption(
                "Caution: the data covers a historical holiday season. These are candidates for "
                "merchandising tests, not guarantees of future performance."
            )

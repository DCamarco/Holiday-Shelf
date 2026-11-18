"""Overview: executive summary of the season."""

import streamlit as st
import ui
from shared import load_order_stats, load_product_summary


def render():
    st.title("Overview")

    summary = load_product_summary()
    n_orders, avg_items, n_multi = load_order_stats()
    total_revenue = float(summary["revenue"].sum())

    ui.hero(
        "This season's shelf plan, at a glance",
        "What shoppers actually bought across the Google Merchandise Store's 2020–21 holiday "
        "season, turned into a short list of what to feature, what to drop, and when.",
        ["Nov 2020 – Jan 2021", f"{len(summary):,} products", f"{n_orders:,} orders", "Google Merchandise Store"],
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Revenue analysed", f"${total_revenue:,.0f}")
    k2.metric("Products tracked", f"{len(summary):,}")
    k3.metric("Orders analysed", f"{n_orders:,}")
    k4.metric("Products per order", f"{avg_items:.2f}")

    st.markdown("### What the data says about the shelf")
    counts = summary["label"].value_counts()
    c1, c2, c3 = st.columns(3)
    c1.html(ui.insight_card(
        "gem", "Hidden Gems", f"{int(counts.get('Hidden Gem', 0))}",
        "Few people see them, but those who do buy. Candidates for a better spot."))
    c2.html(ui.insight_card(
        "star", "Stars", f"{int(counts.get('Star', 0))}",
        "Popular and converting. Keep them where they are."))
    c3.html(ui.insight_card(
        "shop", "Window-Shoppers", f"{int(counts.get('Window-Shopper', 0))}",
        "Lots of views, few sales. Review what they are taking space from."))

    left, right = st.columns([3, 2])
    with left:
        st.markdown("### Top opportunities to feature")
        floor = int(summary["min_views_floor"].iloc[0])
        ok = summary[
            (summary["sessions_viewed"] >= floor)
            & (~summary["views_likely_insufficient"].astype(bool))
            & (~summary["purchases_unmatched"].astype(bool))
            & summary["view_to_buy_rate"].notna()
        ]
        med_v, med_r = ok["sessions_viewed"].median(), ok["view_to_buy_rate"].median()
        top = ok[(ok["sessions_viewed"] < med_v) & (ok["view_to_buy_rate"] > med_r)] \
            .sort_values(["view_to_buy_ci_low", "revenue"], ascending=False).head(5)
        rows = "".join(
            f'<div class="hs-row"><div><div class="n">{r.item_name}</div>'
            f'<div class="s">{int(r.sessions_viewed):,} views · {r.view_to_buy_rate:.1%} of viewers buy</div></div>'
            f'<span class="hs-pill">≥ {r.view_to_buy_ci_low:.1%}</span></div>'
            for r in top.itertuples()
        )
        st.html(f'<div class="hs-card">{rows}</div>')
        st.caption("The badge is the cautious estimate: we are 95% sure at least this share of viewers buy.")
    with right:
        st.markdown("### Where to go next")
        st.html(
            '<div class="hs-card">'
            '<div class="hs-row"><div><div class="n">1 · Find products</div><div class="s">Shelf Scorecard, Opportunity Finder</div></div></div>'
            '<div class="hs-row"><div><div class="n">2 · Grow each order</div><div class="s">Bundles &amp; Cart Rescue</div></div></div>'
            '<div class="hs-row"><div><div class="n">3 · Check the banners</div><div class="s">Banner Performance</div></div></div>'
            '<div class="hs-row"><div><div class="n">4 · Pick the timing</div><div class="s">Season Playbook</div></div></div>'
            '<div class="hs-row"><div><div class="n">5 · Build the plan</div><div class="s">Shortlist Builder, then export</div></div></div>'
            '</div>'
        )

    st.caption(
        "One holiday season of one store. Results show what happened, not what will happen; "
        "treat them as hypotheses to test this year."
    )

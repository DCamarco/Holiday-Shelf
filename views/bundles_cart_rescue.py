"""Bundles & Cart Rescue: bought-together pairs and carts that are lost."""

import plotly.express as px
import streamlit as st
import ui
from shared import add_to_shortlist, load_order_stats, load_pairs, load_rescue


def render():
    st.title("Bundles & Cart Rescue")
    st.caption("Two ways to lift revenue without adding new products: pair a cheap add-on "
               "with a popular item, and fix products that shoppers cart but don't buy.")

    n_orders, avg_items, n_multi = load_order_stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Orders analysed", f"{n_orders:,}")
    c2.metric("Avg products per order", f"{avg_items:.2f}")
    c3.metric("Orders with 2+ products", f"{n_multi:,}")

    tab_pairs, tab_rescue = st.tabs(["Bought together", "Cart Rescue"])

    # ---------------- Bought together ----------------
    with tab_pairs:
        pairs = load_pairs()
        st.markdown("**Which products are bought in the same order?** "
                    "The *anchor* is the pricier item, the *add-on* is the cheaper one.")
        f1, f2, f3 = st.columns(3)
        min_orders = f1.slider("Min orders together", 5, int(pairs["orders_together"].max()), 8)
        min_ratio = f2.slider("Anchor at least N× the add-on price", 1.0, 20.0, 3.0, 0.5)
        sort_by = f3.selectbox("Sort by", ["orders_together", "addon_attach_rate", "lift"])
        g1, g2 = st.columns(2)
        hide_variants = g1.checkbox("Hide colour/size variants of the same product", value=True)
        cats = sorted(pairs["anchor_category"].dropna().unique())
        sel_cats = g2.multiselect("Anchor category", cats)

        view = pairs[(pairs["orders_together"] >= min_orders) & (pairs["price_ratio"] >= min_ratio)]
        if hide_variants:
            view = view[~view["same_family"]]
        if sel_cats:
            view = view[view["anchor_category"].isin(sel_cats)]
        view = view.sort_values(sort_by, ascending=False).reset_index(drop=True)

        st.write(f"**{len(view):,} pairs** match.")
        if view.empty:
            st.info("No pairs match these filters. Lower the minimums.")
        else:
            show = view.head(25).copy()
            show["pair"] = show["anchor"] + "  +  " + show["addon"]
            fig = px.bar(show.iloc[::-1], x="orders_together", y="pair", orientation="h",
                         hover_data=["addon_attach_rate", "lift", "anchor_price", "addon_price"])
            fig.update_layout(height=max(350, 24 * len(show)), yaxis_title=None,
                              xaxis_title="Orders containing both", margin=dict(l=0, r=0, t=10, b=0))
            ui.plot(fig, width="stretch")

            table = view[["anchor", "addon", "anchor_price", "addon_price", "orders_together",
                          "addon_attach_rate", "lift"]].copy()
            table["addon_attach_rate"] = (table["addon_attach_rate"] * 100).round(1)
            table["lift"] = table["lift"].round(1)
            table.columns = ["Anchor", "Add-on", "Anchor $", "Add-on $", "Orders together",
                             "Add-on in % of anchor orders", "Lift"]
            st.dataframe(table, width="stretch", hide_index=True)

            st.markdown("**Add an add-on to the shortlist**")
            options = [f"{r.anchor}  +  {r.addon}" for r in view.head(50).itertuples()]
            choice = st.selectbox("Pair", options, key="pair_choice")
            if st.button("+ Add as cart add-on"):
                r = view.head(50).iloc[options.index(choice)]
                add_to_shortlist(
                    {"item_name": r["addon"], "item_category": r["addon_category"],
                     "slot": "cart add-on", "paired_with": r["anchor"],
                     "orders_together": int(r["orders_together"])},
                    key=f"{r['addon']} (add-on)",
                )
                st.success(f"Added {r['addon']} as a cart add-on for {r['anchor']}.")
        st.caption("Association, not causation: these products were bought together in one "
                   "holiday season. Lift above 1 means they appear together more than chance "
                   "would suggest, but rare items inflate lift, so check order counts too. "
                   "Colour/size variants are detected by a simple name rule and can be missed.")

    # ---------------- Cart Rescue ----------------
    with tab_rescue:
        rescue = load_rescue()
        med = rescue["catalog_median_cart_to_buy"].iloc[0]
        st.markdown(f"**Products added to cart 100+ times that convert below the catalog "
                    f"median ({med:.1%} of carts end in a purchase).** Ranked by carts that "
                    f"did not turn into a purchase.")
        top_n = st.slider("Show top N", 5, 50, 20)
        rv = rescue.head(top_n).copy()
        fig2 = px.bar(rv.iloc[::-1], x="abandoned_carts", y="item_name", orientation="h",
                      hover_data=["sessions_added_to_cart", "sessions_purchased"])
        fig2.update_layout(height=max(350, 24 * len(rv)), yaxis_title=None,
                           xaxis_title="Carts without a purchase", margin=dict(l=0, r=0, t=10, b=0))
        ui.plot(fig2, width="stretch")

        t = rv[["item_name", "item_category", "typical_price", "sessions_added_to_cart",
                "sessions_purchased", "cart_to_buy_rate", "abandoned_carts"]].copy()
        t["cart_to_buy_rate"] = (t["cart_to_buy_rate"] * 100).round(1)
        t.columns = ["Product", "Category", "Price $", "Cart sessions", "Purchase sessions",
                     "Cart→buy %", "Carts not bought"]
        st.dataframe(t, width="stretch", hide_index=True)
        st.caption("A product can land here because of price, shipping surprise, or checkout "
                   "friction. The data shows where carts are lost, not why. Products whose "
                   "purchases appear under a different spelling are excluded.")

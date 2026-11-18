"""Banner Performance: views, clicks and later buyers for each homepage banner."""

import plotly.express as px
import streamlit as st
import ui
from shared import load_banners


def wilson_range(successes, n, z=1.96):
    """95% range for a rate (e.g. share of clickers who later bought)."""
    if n <= 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * ((p * (1 - p) + z**2 / (4 * n)) / n) ** 0.5 / denom
    return max(center - margin, 0.0), min(center + margin, 1.0)


def render():
    st.title("Banner Performance")
    st.markdown(
        "A **banner** is a promo box on the store. This page answers one question: "
        "**when shoppers click a banner, do they go on to buy?**"
    )
    bn = load_banners()
    if bn is None:
        st.info("`data/banner_performance.csv` not found. Run `sql/03_extract_banners.sql` in "
                "BigQuery, download the result and save it as `data/banner_performance.csv`.")
        st.stop()

    MIN_CLICKERS = 100
    bn = bn.copy()
    bn["banner"] = bn["banner"].astype(str)
    bn["buy_rate"] = bn["buyers"] / bn["click_users"].where(bn["click_users"] > 0)
    ranges = [wilson_range(r.buyers, r.click_users) for r in bn.itertuples()]
    bn["low"] = [x[0] for x in ranges]
    bn["high"] = [x[1] for x in ranges]
    main_bn = bn[bn["click_users"] >= MIN_CLICKERS].sort_values("buy_rate", ascending=False)
    small_bn = bn[bn["click_users"] < MIN_CLICKERS]

    # ---- 1. the answer, in plain words ----
    best = main_bn.iloc[0]
    overlap_all = all(best["low"] <= r.high for r in main_bn.iloc[1:].itertuples())
    st.markdown("### The short answer")
    lo, hi = main_bn["buy_rate"].min(), main_bn["buy_rate"].max()
    st.markdown(
        f"- Out of every 100 people who click one of these banners, about **{lo * 100:.0f} to "
        f"{hi * 100:.0f}** go on to buy something.\n"
        + ("- The banners are **close to each other**: the gaps are small enough that they could "
           "be chance, so no banner is clearly better at turning clicks into sales.\n"
           if overlap_all else
           f"- *{best['banner']}* is the best at turning clicks into sales "
           f"({best['buy_rate']:.1%}), and the gap to the others is larger than chance.\n")
        + "- So the real difference between banners is **how many people click**, "
          "not what the clickers do afterwards."
    )

    # ---- 2. one simple chart ----
    st.markdown("### Out of 100 people who clicked, how many later bought?")
    fig = px.bar(main_bn.iloc[::-1], x=main_bn.iloc[::-1]["buy_rate"] * 100, y="banner",
                 orientation="h", text=(main_bn.iloc[::-1]["buy_rate"] * 100).round(1).astype(str) + "%")
    fig.update_traces(
        marker_color="#6366F1",
        error_x=dict(type="data", symmetric=False, color="#F59E0B", thickness=2.5, width=6,
                     array=((main_bn.iloc[::-1]["high"] - main_bn.iloc[::-1]["buy_rate"]) * 100).tolist(),
                     arrayminus=((main_bn.iloc[::-1]["buy_rate"] - main_bn.iloc[::-1]["low"]) * 100).tolist()),
        textposition="inside", insidetextanchor="start", textfont=dict(color="white", size=14),
    )
    fig.update_layout(height=60 * len(main_bn) + 120, yaxis_title=None,
                      xaxis_title="People who bought per 100 who clicked",
                      margin=dict(l=0, r=0, t=10, b=0))
    ui.plot(fig, width="stretch")
    st.caption("The amber line on each bar is the range we are 95% sure the true value "
               "falls in. When two bars' lines overlap, the banners are not clearly different.")

    # ---- 3. the numbers behind it ----
    st.markdown("### The numbers behind it")
    t = main_bn[["banner", "views", "clicks", "click_users", "buyers", "buy_rate"]].copy()
    t["buy_rate"] = (t["buy_rate"] * 100).round(1).astype(str) + "%"
    t.columns = ["Banner", "Times shown", "Clicks", "People who clicked",
                 "Of those, bought later", "Buy rate"]
    st.dataframe(t, width="stretch", hide_index=True)
    st.download_button("Download this table (CSV)", t.to_csv(index=False), "banner_performance_table.csv")

    # ---- 4. is the big banner worth the slot? ----
    ok = main_bn[main_bn["clicks"] <= 0.2 * main_bn["views"]]
    st.markdown("### Is the biggest banner worth its slot?")
    if len(ok):
        r = ok.sort_values("views", ascending=False).iloc[0]
        per_1000 = r["clicks"] / r["views"] * 1000
        others = main_bn[main_bn["banner"] != r["banner"]]
        if len(others):
            o = others.sort_values("clicks", ascending=False).iloc[0]
            _cmp = (f"For comparison, *{o['banner']}* got **{o['clicks']:,.0f} clicks** "
                    f"(similar), so the extra views did not translate into extra clicks "
                    f"by that measure.")
        else:
            _cmp = ""
        st.markdown(
            f"*{r['banner']}* was shown **{r['views']:,.0f} times** but clicked only "
            f"**{r['clicks']:,.0f} times**, about **{per_1000:.0f} clicks for every 1,000 views**. "
            f"{_cmp}"
        )
    st.caption("For the smaller banners the 'times shown' looks too low (nearly as many clicks as "
               "views), probably because they are clicked from places that do not log a view. "
               "So compare banners by **clicks and buyers**, not by views.")

    if len(small_bn):
        with st.expander(f"{len(small_bn)} other banner entries left out (fewer than {MIN_CLICKERS} people clicked)"):
            st.dataframe(small_bn[["banner", "views", "clicks", "click_users", "buyers"]],
                         width="stretch", hide_index=True)

    st.caption("'Bought later' = the person bought something after first clicking the banner. "
               "It does not prove the banner caused the purchase; people who click banners may "
               "already have planned to buy. One holiday season of one store.")

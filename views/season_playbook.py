"""Season Playbook: which holiday phase suits each product, shipping dates and Google Trends."""

import pandas as pd
import plotly.express as px
import streamlit as st
import ui
from shared import DATA_DIR, add_to_shortlist, load_product_summary, load_weekly


def render():
    st.title("Season Playbook")
    st.caption(
        "Explore historical holiday demand and plan when to feature products."
    )

    df = load_weekly()

    phase_order = [
        "Early Nov",
        "Black Friday / Cyber Monday",
        "Mid-Dec",
        "Post-Christmas",
    ]

    weekly_totals = (
        df.groupby(["week_start", "phase"], as_index=False)
        .agg(
            views=("sessions_viewed", "sum"),
            purchases=("sessions_purchased", "sum"),
            revenue=("revenue", "sum"),
        )
    )

    phase_summary = (
        weekly_totals.groupby("phase", as_index=False)
        .agg(
            weeks=("week_start", "nunique"),
            views=("views", "sum"),
            purchases=("purchases", "sum"),
            revenue=("revenue", "sum"),
        )
    )

    phase_summary["purchase_view_ratio"] = (
        phase_summary["purchases"] / phase_summary["views"]
    ).where(phase_summary["views"] > 0)

    phase_summary["purchases_per_week"] = (
        phase_summary["purchases"] / phase_summary["weeks"]
    )

    phase_summary["revenue_per_week"] = (
        phase_summary["revenue"] / phase_summary["weeks"]
    )

    phase_summary["phase"] = pd.Categorical(
        phase_summary["phase"],
        categories=phase_order,
        ordered=True,
    )

    phase_summary = phase_summary.sort_values("phase")

    st.markdown("### Historical holiday phase performance")

    display_df = phase_summary[
        [
            "phase",
            "weeks",
            "views",
            "purchases",
            "revenue",
            "purchase_view_ratio",
            "purchases_per_week",
            "revenue_per_week",
        ]
    ].copy()

    display_df["purchase_view_ratio"] *= 100

    display_df.columns = [
        "Phase",
        "Weeks",
        "Views",
        "Purchases",
        "Revenue ($)",
        "Purchase / View",
        "Purchases / Week",
        "Revenue / Week ($)",
    ]

    st.dataframe(
        display_df,
        hide_index=True,
        column_config={
            "Purchase / View": st.column_config.NumberColumn(
                format="%.2f%%",
                help="Historical purchases divided by product-view sessions.",
            ),
        },
    )

    st.markdown("### Weekly purchase trends")

    fig = px.line(
        weekly_totals.sort_values("week_start"),
        x="week_start",
        y="purchases",
        markers=True,
        labels={
            "week_start": "Week beginning",
            "purchases": "Purchase sessions",
        },
    )

    ui.plot(fig, width="stretch")

    st.markdown("### Product-specific phase recommendations")

    available_products = sorted(
        df["item_name"].dropna().unique().tolist()
    )
    known_products = set(available_products)

    shortlisted = list(dict.fromkeys(
        product.get("item_name")
        for product in st.session_state.shortlist.values()
        if product.get("item_name") in known_products
    ))

    product_options = shortlisted + [
        name for name in available_products
        if name not in shortlisted
    ]

    selected_product = st.selectbox(
        "Choose a product to analyze",
        product_options,
        key="season_product",
    )

    product_history = df[
        df["item_name"] == selected_product
    ].copy()

    product_phase = (
        product_history.groupby("phase", as_index=False)
        .agg(
            views=("sessions_viewed", "sum"),
            purchases=("sessions_purchased", "sum"),
            revenue=("revenue", "sum"),
        )
    )

    # Divide by all calendar weeks in each phase, not only
    # the weeks where this product has recorded activity.
    phase_weeks = dict(zip(
        phase_summary["phase"].astype(str),
        phase_summary["weeks"],
    ))

    product_phase["weeks"] = (
        product_phase["phase"].map(phase_weeks)
    )

    product_phase["purchases_per_week"] = (
        product_phase["purchases"] / product_phase["weeks"]
    )

    product_phase["revenue_per_week"] = (
        product_phase["revenue"] / product_phase["weeks"]
    )

    product_phase["purchase_view_ratio"] = (
        product_phase["purchases"] / product_phase["views"]
    ).where(product_phase["views"] > 0)

    product_phase["phase"] = pd.Categorical(
        product_phase["phase"],
        categories=phase_order,
        ordered=True,
    )

    product_phase = product_phase.sort_values("phase")

    product_display = product_phase[
        [
            "phase",
            "weeks",
            "views",
            "purchases",
            "purchase_view_ratio",
            "purchases_per_week",
            "revenue_per_week",
        ]
    ].copy()

    product_display["purchase_view_ratio"] *= 100

    product_display.columns = [
        "Phase",
        "Weeks",
        "Views",
        "Purchases",
        "Purchase / View (%)",
        "Purchases / Week",
        "Revenue / Week ($)",
    ]

    st.dataframe(
        product_display,
        hide_index=True,
        column_config={
            "Purchase / View (%)": st.column_config.NumberColumn(
                format="%.2f%%",
            ),
            "Purchases / Week": st.column_config.NumberColumn(
                format="%.1f",
            ),
            "Revenue / Week ($)": st.column_config.NumberColumn(
                format="$%.2f",
            ),
        },
    )

    reliable_phases = product_phase[
        (product_phase["views"] >= 100)
        & (product_phase["purchases"] <= product_phase["views"])
        & (product_phase["purchases"] >= 0)
    ].copy()

    if reliable_phases.empty:
        st.warning(
            "There is insufficient historical evidence to "
            "recommend a phase for this product. A phase needs "
            "at least 100 recorded views, with purchases not "
            "exceeding views."
        )
    else:
        best = reliable_phases.sort_values(
            ["purchases_per_week", "revenue_per_week"],
            ascending=False,
        ).iloc[0]

        st.info(
            f"**Suggested historical phase to test: "
            f"{best['phase']}**. "
            f"This product averaged "
            f"{best['purchases_per_week']:.1f} purchase "
            f"sessions per week during that phase. "
            f"Use this as a planning hypothesis, "
            f"not a guaranteed result."
        )

    if not reliable_phases.empty:
        recommended_phase = str(best["phase"])

        matching_keys = [
            key
            for key, product in st.session_state.shortlist.items()
            if product.get("item_name") == selected_product
        ]

        if matching_keys:
            if st.button(
                "Apply recommended phase to shortlist",
                key=f"apply_season_{selected_product}",
            ):
                for item_key in matching_keys:
                    st.session_state.shortlist[item_key][
                        "holiday_phase"
                    ] = recommended_phase

                    # Allow the Shortlist Builder dropdown to use
                    # the newly recommended phase.
                    st.session_state.pop(
                        f"phase_{item_key}", None
                    )

                st.success(
                    f"Applied {recommended_phase} to "
                    f"{selected_product} in your shortlist."
                )

        else:
            if st.button(
                "Add to shortlist with recommended phase",
                key=f"add_season_{selected_product}",
            ):
                summary = load_product_summary()

                match = summary[
                    summary["item_name"] == selected_product
                ]

                if match.empty:
                    st.error(
                        "This product was not found in "
                        "the product summary."
                    )
                else:
                    product = match.iloc[0].to_dict()
                    product["holiday_phase"] = recommended_phase

                    add_to_shortlist(product)

                    st.success(
                        f"Added {selected_product} with "
                        f"{recommended_phase} as its phase."
                    )

    st.markdown("### Product weekly sales trend")

    product_trend = (
        product_history.groupby("week_start", as_index=False)
        .agg(
            views=("sessions_viewed", "sum"),
            purchases=("sessions_purchased", "sum"),
            revenue=("revenue", "sum"),
        )
        .sort_values("week_start")
    )

    trend_fig = px.line(
        product_trend,
        x="week_start",
        y="purchases",
        markers=True,
        hover_data={
            "views": True,
            "revenue": ":,.2f",
        },
        labels={
            "week_start": "Week beginning",
            "purchases": "Purchase sessions",
            "views": "Product-view sessions",
            "revenue": "Revenue ($)",
        },
        title=f"Weekly purchases: {selected_product}",
    )

    phase_shades = {
        "Early Nov": "#DCEAF9",
        "Black Friday / Cyber Monday": "#FCE5D6",
        "Mid-Dec": "#E1F2E5",
        "Post-Christmas": "#EEE4FA",
    }

    phase_labels = {
        "Early Nov": "Early Nov",
        "Black Friday / Cyber Monday": "BFCM",
        "Mid-Dec": "Mid-Dec",
        "Post-Christmas": "Post-Christmas",
    }

    for phase_name in phase_order:
        phase_dates = df.loc[
            df["phase"] == phase_name,
            "week_start",
        ]

        if phase_dates.empty:
            continue

        phase_start = phase_dates.min()
        phase_end = (
            phase_dates.max() + pd.Timedelta(days=7)
        )

        trend_fig.add_vrect(
            x0=phase_start,
            x1=phase_end,
            fillcolor=phase_shades[phase_name],
            opacity=0.40,
            line_width=0,
            layer="below",
        )

        trend_fig.add_annotation(
            x=phase_start,
            y=1.04,
            yref="paper",
            text=phase_labels[phase_name],
            showarrow=False,
            xanchor="left",
            font=dict(size=10),
        )

    trend_fig.update_layout(
        height=450,
        hovermode="x unified",
        margin=dict(t=85),
    )

    st.markdown("#### Historical USPS shipping deadlines")

    usps_deadlines = {
        "Retail Ground — Dec 15": "2020-12-15",
        "First-Class Package — Dec 18": "2020-12-18",
        "Priority Mail — Dec 19": "2020-12-19",
        "Priority Mail Express — Dec 23": "2020-12-23",
    }

    selected_deadlines = st.multiselect(
        "Show USPS 2020 mail-by dates on chart",
        options=list(usps_deadlines),
        default=[
            "Retail Ground — Dec 15",
            "Priority Mail — Dec 19",
        ],
        key="historical_usps_deadlines",
    )

    for index, service in enumerate(selected_deadlines):
        cutoff = usps_deadlines[service]

        trend_fig.add_shape(
            type="line",
            x0=cutoff,
            x1=cutoff,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line=dict(
                color="#B42318",
                width=2,
                dash="dash",
            ),
        )

        trend_fig.add_annotation(
            x=cutoff,
            xref="x",
            y=0.94 - (index % 4) * 0.12,
            yref="paper",
            text=service,
            showarrow=False,
            xanchor="left",
            bgcolor="rgba(255,255,255,0.85)",
            font=dict(
                size=10,
                color="#B42318",
            ),
        )

    ui.plot(
        trend_fig,
        width="stretch",
    )
    st.caption(
        "Historical USPS recommended mailing deadlines for "
        "expected Christmas 2020 delivery are shown as red "
        "dashed lines. These were not store order cutoffs "
        "and do not establish why purchases changed. "
        "Actual delivery was not guaranteed."
    )

    st.link_button(
        "Source: USPS 2020 holiday shipping deadlines",
        "https://about.usps.com/newsroom/national-releases/"
        "2020/1008-usps-releases-deadlines-for-holiday-shipping.htm",
    )



    st.caption(
        "Shaded regions represent historical holiday phases "
        "from the 2020–2021 dataset. "
        "Weekly figures describe recorded purchase sessions, "
        "not forecasts of future sales."
    )

    st.markdown("### Seasonal launch schedule")

    from datetime import date, timedelta

    planning_year = st.number_input(
        "Planning year",
        min_value=2026,
        max_value=2035,
        value=2026,
        step=1,
    )

    november_first = date(planning_year, 11, 1)

    first_thursday = november_first + timedelta(
        days=(3 - november_first.weekday()) % 7
    )

    thanksgiving = first_thursday + timedelta(weeks=3)
    black_friday = thanksgiving + timedelta(days=1)
    cyber_monday = black_friday + timedelta(days=3)

    phase_windows = {
        "Early Nov": (
            date(planning_year, 11, 1),
            thanksgiving - timedelta(days=1),
        ),
        "Black Friday / Cyber Monday": (
            black_friday,
            cyber_monday,
        ),
        "Mid-Dec": (
            date(planning_year, 12, 7),
            date(planning_year, 12, 24),
        ),
        "Post-Christmas": (
            date(planning_year, 12, 26),
            date(planning_year + 1, 1, 15),
        ),
    }

    default_phase = (
        str(best["phase"])
        if not reliable_phases.empty
        else "Early Nov"
    )

    selected_phase = st.selectbox(
        "Phase to schedule",
        phase_order,
        index=phase_order.index(default_phase),
        key=f"schedule_{selected_product}_{planning_year}",
    )

    start_date, end_date = phase_windows[selected_phase]

    phase_actions = {
        "Early Nov":
            "Build awareness, test category placements, "
            "and prepare promotional inventory.",
        "Black Friday / Cyber Monday":
            "Prioritize high-visibility promotional placements "
            "and monitor stock and conversion.",
        "Mid-Dec":
            "Feature gifting products and verify shipping "
            "cutoffs before promising holiday delivery.",
        "Post-Christmas":
            "Focus on clearance, gift-card shoppers, "
            "and remaining inventory.",
    }

    st.write(
        f"**Suggested planning window:** "
        f"{start_date:%b %d, %Y} – {end_date:%b %d, %Y}"
    )

    st.info(phase_actions[selected_phase])

    st.caption(
        "These dates are illustrative rollout windows, "
        "not the exact historical dataset boundaries. "
        "Confirm inventory, promotion dates, and shipping "
        "deadlines before launching."
    )

    st.markdown("### Christmas delivery cutoff check")

    shipping_cutoff = st.date_input(
        "Last order date for Christmas delivery",
        value=None,
        min_value=date(planning_year, 11, 1),
        max_value=date(planning_year, 12, 24),
        key=f"shipping_cutoff_{planning_year}",
        help="Enter a deadline confirmed by your seller or carrier.",
    )

    if shipping_cutoff is None:
        st.info(
            "No shipping cutoff entered. Confirm the deadline "
            "with your fulfillment or delivery provider."
        )
    elif start_date > shipping_cutoff:
        st.warning(
            f"The selected phase begins after the "
            f"{shipping_cutoff:%b %d, %Y} shipping cutoff. "
            "Avoid promising Christmas delivery."
        )
    elif end_date > shipping_cutoff:
        st.warning(
            f"This phase extends beyond the "
            f"{shipping_cutoff:%b %d, %Y} cutoff. "
            "Separate promotions before and after the deadline."
        )
    else:
        st.success(
            "The selected phase ends before or on the "
            "entered shipping cutoff."
        )

    st.caption(
        "This check uses a user-entered deadline. "
        "It does not verify delivery availability, inventory, "
        "processing time, or carrier service."
    )



    st.markdown("### Google Trends research")

    st.write(
        "Check whether recent search interest supports the "
        "historical holiday recommendation."
    )

    from urllib.parse import urlencode

    search_term = st.text_input(
        "Google Trends search term",
        value=selected_product,
        key=f"trends_term_{selected_product}",
        help="Use a broader product category if the exact item has little search data.",
    )

    if search_term.strip():
        trends_url = (
            "https://trends.google.com/trends/explore?"
            + urlencode({
                "date": "today 5-y",
                "geo": "US",
                "q": search_term.strip(),
            })
        )

        st.link_button(
            "Open Google Trends",
            trends_url,
        )

    trend_signal = st.selectbox(
        "Observed search-interest trend",
        [
            "Not reviewed",
            "Rising",
            "Stable",
            "Declining",
            "Insufficient data",
        ],
        key=f"trend_signal_{selected_product}",
    )

    trend_notes = st.text_area(
        "Research notes",
        placeholder=(
            "Example: Search interest increases in November "
            "and peaks in December."
        ),
        key=f"trend_notes_{selected_product}",
    )

    if trend_signal != "Not reviewed":
        st.info(
            f"Research observation: {trend_signal}. "
            "Compare this signal with historical sales before "
            "finalizing the merchandising schedule."
        )

    st.caption(
        "Google Trends provides relative search interest, "
        "not product sales. Research observations are entered "
        "manually and retained only in the current app session."
    )

    st.markdown("### Google Trends data comparison")

    trends_path = DATA_DIR / "google_trends_hoodie.csv"

    if not trends_path.exists():
        st.warning("Google Trends CSV not found in data/.")
    else:
        trends_raw = pd.read_csv(trends_path, skiprows=2)

        interest_columns = [
            column for column in trends_raw.columns
            if column != "Month"
        ]

        if "Month" not in trends_raw.columns or len(interest_columns) != 1:
            st.error("Unexpected Google Trends CSV format.")
        else:
            trends = pd.DataFrame({
                "month": pd.to_datetime(
                    trends_raw["Month"].astype(str) + "-01",
                    errors="coerce",
                ),
                "interest": pd.to_numeric(
                    trends_raw[interest_columns[0]],
                    errors="coerce",
                ),
            }).dropna().sort_values("month")

            st.caption(
                "Source: Google Trends, US Web Search, "
                "keyword 'hoodie'. CSV downloaded manually. "
                "Scores represent relative interest, not "
                "search counts or product purchases."
            )

            st.markdown("#### US search interest over time")

            fig_trends = px.line(
                trends,
                x="month",
                y="interest",
                markers=True,
                labels={
                    "month": "Month",
                    "interest": "Google Trends interest (0–100)",
                },
                title="US Google Trends — hoodie",
            )

            fig_trends.update_yaxes(range=[0, 105])
            fig_trends.update_layout(height=400)

            ui.plot(fig_trends, width="stretch")

            st.markdown("#### Holiday search timing comparison")

            holiday_trends = trends.copy()

            holiday_trends["year"] = (
                holiday_trends["month"].dt.year
            )

            holiday_trends["month_number"] = (
                holiday_trends["month"].dt.month
            )

            holiday_trends = holiday_trends[
                holiday_trends["year"].isin([2020, 2025, 2026])
                & holiday_trends["month_number"].between(10, 12)
            ].copy()

            holiday_trends["Holiday month"] = (
                holiday_trends["month"].dt.strftime("%b")
            )

            holiday_trends["Year"] = (
                holiday_trends["year"].astype(str)
            )

            fig_holiday = px.line(
                holiday_trends,
                x="Holiday month",
                y="interest",
                color="Year",
                markers=True,
                category_orders={
                    "Holiday month": ["Oct", "Nov", "Dec"],
                    "Year": ["2020", "2025", "2026"],
                },
                labels={
                    "interest": "Google Trends interest (0–100)",
                },
                title="US hoodie searches: holiday seasons compared",
            )

            fig_holiday.update_yaxes(range=[0, 105])

            fig_holiday.update_layout(
                height=420,
                hovermode="x unified",
            )

            ui.plot(
                fig_holiday,
                width="stretch",
            )

            st.caption(
                "The three years use the same relative-interest "
                "scale from one Google Trends CSV export. "
                "November 2026 is incomplete, and December "
                "2026 is not yet available. Missing months "
                "are not treated as zero searches."
            )


            st.markdown(
                "#### Historical product demand vs search interest"
            )

            if "hoodie" not in selected_product.lower():
                st.info(
                    "The imported search keyword is 'hoodie'. "
                    "For a different product category, import "
                    "a relevant Google Trends keyword before "
                    "interpreting the comparison."
                )

            sales_monthly = product_history.copy()

            sales_monthly["month"] = (
                sales_monthly["week_start"]
                .dt.to_period("M")
                .dt.to_timestamp()
            )

            sales_monthly = (
                sales_monthly.groupby("month", as_index=False)
                .agg(
                    purchases=("sessions_purchased", "sum"),
                )
            )

            comparison = sales_monthly.merge(
                trends,
                on="month",
                how="inner",
            )

            comparison = comparison[
                (comparison["month"] >= "2020-10-01")
                & (comparison["month"] <= "2021-01-01")
            ].sort_values("month")

            if comparison.empty:
                st.warning(
                    "No overlapping historical months found."
                )
            else:
                max_purchases = comparison["purchases"].max()
                max_interest = comparison["interest"].max()

                comparison["Product purchase index"] = (
                    comparison["purchases"] / max_purchases * 100
                    if max_purchases > 0 else 0.0
                )

                comparison["US hoodie search index"] = (
                    comparison["interest"] / max_interest * 100
                    if max_interest > 0 else 0.0
                )

                comparison["Month"] = (
                    comparison["month"].dt.strftime("%b %Y")
                )

                comparison_chart = comparison[
                    [
                        "Month",
                        "Product purchase index",
                        "US hoodie search index",
                    ]
                ].melt(
                    id_vars="Month",
                    var_name="Series",
                    value_name="Index",
                )

                fig_compare = px.line(
                    comparison_chart,
                    x="Month",
                    y="Index",
                    color="Series",
                    markers=True,
                    title=(
                        f"2020–2021 seasonal comparison: "
                        f"{selected_product}"
                    ),
                )

                fig_compare.update_yaxes(range=[0, 105])
                fig_compare.update_layout(height=400)

                ui.plot(fig_compare, width="stretch")

                st.caption(
                    "Each series is independently rescaled to "
                    "a maximum of 100 over the overlapping months. "
                    "Monthly product purchases are grouped using "
                    "the week-start date. This is an exploratory "
                    "seasonality comparison, not evidence that "
                    "search interest causes purchases."
                )

            st.caption(
                "November 2026 may be incomplete. "
                "The CSV is a downloaded snapshot, "
                "not an automatically updating live feed."
            )


    st.caption(
        "Phase recommendation uses historical purchase "
        "activity per calendar week. The 100-view threshold "
        "is a minimum screening rule, not proof of statistical "
        "reliability."
    )

    st.caption(
        "Historical data: October 2020–January 2021. "
        "Phases cover different numbers of weeks. "
        "Purchase/view ratios use aggregated product-level sessions "
        "and should not be treated as unique-shopper conversion rates."
    )

"""Shortlist Builder: assign phase, slot and replacement, then export the shelf plan."""

from io import BytesIO
from statistics import NormalDist
from xml.sax.saxutils import escape
import math
import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import ai_panel
from shared import (
    load_pairs,
    load_product_prices,
    load_product_summary,
    load_rescue,
    load_weekly,
)


def required_visits_per_variant(
    baseline_rate,
    relative_lift=0.20,
    alpha=0.05,
    power=0.80,
):
    """Estimate visits per variant for a two-sided A/B test."""
    if pd.isna(baseline_rate):
        return None

    baseline = float(baseline_rate)

    if not 0 < baseline < 1:
        return None

    if not 0 < relative_lift or relative_lift > 1:
        return None

    improved_rate = min(
        baseline * (1 + relative_lift), 0.999999
    )
    average_rate = (baseline + improved_rate) / 2

    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_power = NormalDist().inv_cdf(power)

    numerator = (
        z_alpha * math.sqrt(
            2 * average_rate * (1 - average_rate)
        )
        + z_power * math.sqrt(
            baseline * (1 - baseline)
            + improved_rate * (1 - improved_rate)
        )
    ) ** 2

    denominator = (improved_rate - baseline) ** 2

    return math.ceil(numerator / denominator)



def build_shelf_brief_pdf(shortlist_df, category_mix, price_mix, weak_count):
    """Generate a one-page landscape merchandising brief."""
    from reportlab.platypus import KeepInFrame

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(letter),
        leftMargin=.35*inch, rightMargin=.35*inch,
        topMargin=.3*inch, bottomMargin=.3*inch,
        title="Holiday Shelf Merchandising Plan",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("BriefTitle", parent=styles["Title"],
                                 fontSize=15, leading=18, alignment=0, spaceAfter=3)
    cell_style = ParagraphStyle("BriefCell", parent=styles["Normal"],
                                fontSize=6.5, leading=7.7)
    note_style = ParagraphStyle("BriefNote", parent=styles["Normal"],
                                fontSize=7, leading=9)

    def show(value, fallback="—"):
        if value is None or pd.isna(value) or str(value).strip() == "":
            return escape(fallback)
        return escape(str(value))

    rows = [[Paragraph(f'<font color="white"><b>{name}</b></font>', cell_style)
             for name in ("Product", "Category", "Phase", "Placement", "Price",
                          "Replace / Pair", "Conv.", "Visits/variant")]]
    for _, item in shortlist_df.iterrows():
        slot = item.get("placement_slot")
        if slot == "Cart add-on":
            replacement = "Add-on to " + str(item.get("paired_with") or "unknown anchor")
        else:
            replacement = item.get("replacement_product")
            if replacement is None or pd.isna(replacement) or replacement == "":
                replacement = item.get("replaces")
            if replacement is None or pd.isna(replacement) or replacement == "":
                replacement = "No replacement"
        price = item.get("typical_price")
        price_label = f"${float(price):,.2f}" if pd.notna(price) else "Unknown"
        rate = item.get("view_to_buy_rate")
        rate_label = f"{float(rate):.1%}" if pd.notna(rate) else "N/A"
        visits = item.get("test_visits_per_variant")
        visits_label = f"{int(float(visits)):,}" if pd.notna(visits) else "N/A"
        values = [item.get("item_name"), item.get("item_category"),
                  item.get("holiday_phase", "Unassigned"), slot or "Unassigned",
                  price_label, replacement, rate_label, visits_label]
        rows.append([Paragraph(show(value), cell_style) for value in values])

    table = Table(rows, colWidths=[128, 89, 73, 73, 51, 130, 62, 110], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263746")),
        ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#BCC4CC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F4F6")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    def summarize(frame, label_col):
        return "; ".join(
            f"{show(row[label_col])}: {int(row['Products'])} "
            f"({float(row['Share (%)']):.1f}%)"
            for _, row in frame.iterrows()
        ) or "No data"

    mix = Table([[
        Paragraph("<b>Category mix</b><br/>" + summarize(category_mix, "Category"), note_style),
        Paragraph("<b>Price mix</b><br/>" + summarize(price_mix, "Price band"), note_style),
    ]], colWidths=[358, 358])
    mix.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), .4, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), .4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    priced = int(shortlist_df["typical_price"].notna().sum())
    story = [
        Paragraph("Holiday Shelf — Merchandising Plan", title_style),
        Paragraph(f"<b>{len(shortlist_df)}</b> selected products &nbsp;|&nbsp; "
                  f"<b>{priced}</b> with observed price data &nbsp;|&nbsp; "
                  f"<b>{weak_count}</b> with weak data", note_style),
        Spacer(1, 7),
        Paragraph("<b>Selected shelf products</b>", note_style),
        Spacer(1, 4),
        table,
        Spacer(1, 10),
        mix,
        Spacer(1, 7),
        Paragraph(f"<b>Data quality:</b> {weak_count} of {len(shortlist_df)} selected products have "
                  "weak/incomplete performance data. Unknown prices are not estimated.", note_style),
        Spacer(1, 4),
        Paragraph("<b>Test assumptions:</b> Two-sided A/B test, 95% confidence, "
                  "80% power, 20% relative conversion lift; visits shown per variant. "
                  "Based on the 2020–2021 holiday season; estimates, not guarantees.", note_style),
    ]
    doc.build([KeepInFrame(720, 536, story, mode="shrink")])
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data


def render():
    st.title("Shortlist Builder")

    # Recommended merchandising shortlist size: 10–15 products.
    selected_count = len(st.session_state.shortlist)

    if 0 < selected_count < 10:
        st.info(
            f"You have selected {selected_count} products. "
            f"Add at least {10 - selected_count} more to reach "
            "the recommended 10–15 product range."
        )
    elif 10 <= selected_count <= 15:
        st.success(
            f"Your {selected_count}-product shortlist is within "
            "the recommended 10–15 product range."
        )
    elif selected_count > 15:
        st.warning(
            f"You have selected {selected_count} products. "
            f"Consider removing {selected_count - 15} to stay "
            "within the recommended 10–15 product range."
        )



    if st.session_state.shortlist:

        phase_options = [
            "Early Nov",
            "Black Friday / Cyber Monday",
            "Mid-Dec",
            "Post-Christmas",
        ]

        slot_options = [
            "Homepage",
            "Category page",
            "Promo banner",
            "Cart add-on",
        ]
        summary_df = load_product_summary()

        st.markdown("### Assign holiday phases and placements")

        # Add planning controls for every shortlisted product.
        for shortlist_key, product in list(
            st.session_state.shortlist.items()
        ):

            # Set default values without overwriting previous selections.
            phase_aliases = {
                "Black Friday": "Black Friday / Cyber Monday",
                "Mid-December": "Mid-Dec",
            }

            saved_phase = product.get("holiday_phase")
            product["holiday_phase"] = phase_aliases.get(
                saved_phase, saved_phase
            )

            if product["holiday_phase"] not in phase_options:
                product["holiday_phase"] = "Black Friday / Cyber Monday"

            if product.get("placement_slot") not in slot_options:
                old_slot = str(product.get("slot") or "").strip().lower()

                slot_aliases = {
                    "homepage": "Homepage",
                    "category page": "Category page",
                    "banner": "Promo banner",
                    "promo banner": "Promo banner",
                    "cart add-on": "Cart add-on",
                }

                product["placement_slot"] = slot_aliases.get(
                    old_slot, "Homepage"
                )

            with st.container(border=True):

                product_name = product.get(
                    "item_name", shortlist_key
                )

                st.markdown(f"**{product_name}**")

                col1, col2 = st.columns(2)

                with col1:
                    phase = st.selectbox(
                        "Holiday phase",
                        options=phase_options,
                        index=phase_options.index(
                            product["holiday_phase"]
                        ),
                        key=f"phase_{shortlist_key}",
                    )

                with col2:
                    slot = st.selectbox(
                        "Placement slot",
                        options=slot_options,
                        index=slot_options.index(
                            product["placement_slot"]
                        ),
                        key=f"slot_{shortlist_key}",
                    )

                # Save the selected planning information.
                product["holiday_phase"] = phase
                product["placement_slot"] = slot
                product["slot"] = slot


                # Select a weaker product to replace.
                if slot == "Cart add-on":
                    product["replacement_product"] = None
                    st.caption(
                        "Cart add-ons complement an anchor product "
                        "and do not replace a homepage or category slot."
                    )

                else:
                    category = product.get("item_category")

                    candidates = summary_df[
                        (summary_df["item_category"] == category)
                        & summary_df["label"].isin(
                            ["Window-Shopper", "Low Priority"]
                        )
                        & (summary_df["item_name"] != product_name)
                    ].copy()

                    candidates = candidates.sort_values(
                        "view_to_buy_rate",
                        ascending=True,
                        na_position="last",
                    )

                    candidate_names = (
                        candidates["item_name"].dropna().tolist()
                    )

                    replacement_options = [
                        "No replacement"
                    ] + candidate_names




                    suggested = product.get("replaces")

                    if suggested is not None and pd.isna(suggested):
                        suggested = None

                    saved_replacement = product.get("replacement_product")

                    if saved_replacement is not None and pd.isna(saved_replacement):
                        saved_replacement = None

                    current = saved_replacement or suggested or "No replacement"

                    if current not in replacement_options:
                        current = "No replacement"

                    replacement = st.selectbox(
                        "Product to replace",
                        options=replacement_options,
                        index=replacement_options.index(current),
                        key=f"replacement_{shortlist_key}",
                    )

                    product["replacement_product"] = (
                        None
                        if replacement == "No replacement"
                        else replacement
                    )

                    if suggested:
                        st.caption(
                            f"Opportunity Finder suggestion: {suggested}"
                        )

                    if not candidate_names:
                        st.info(
                            "No eligible weaker products were found "
                            "in this category."
                        )

                # Two-week A/B testing recommendation
                st.markdown("**Two-week test plan**")

                baseline_rate = product.get("view_to_buy_rate")

                required_per_variant = required_visits_per_variant(
                    baseline_rate
                )

                if required_per_variant is None:
                    st.info(
                        "Testing traffic estimate unavailable because "
                        "this product does not have a valid historical "
                        "conversion rate."
                    )

                else:
                    total_visits = required_per_variant * 2
                    daily_target = math.ceil(
                        required_per_variant / 14
                    )

                    target_rate = min(
                        float(baseline_rate) * 1.20,
                        0.999999
                    )

                    st.write(
                        f"Historical conversion: "
                        f"{float(baseline_rate):.1%}"
                    )

                    st.write(
                        f"Target conversion: {target_rate:.1%} "
                        f"(20% relative improvement)"
                    )

                    st.write(
                        f"Required traffic: "
                        f"{required_per_variant:,} visits per variant "
                        f"({total_visits:,} combined)"
                    )

                    st.write(
                        f"Daily target: approximately "
                        f"{daily_target:,} visits per variant "
                        f"for 14 days."
                    )

                st.caption(
                    "Estimate assumes a two-sided test, 95% confidence "
                    "and 80% statistical power. Actual results may differ."
                )



        # Refresh the table using the updated product information.
        shortlist_df = pd.DataFrame(
            list(st.session_state.shortlist.values())
        )

        price_df = load_product_prices()

        shortlist_df = shortlist_df.merge(
            price_df,
            on="item_name",
            how="left",
        )

        # Add testing estimates to the exportable plan.
        if "view_to_buy_rate" in shortlist_df.columns:
            baseline_rates = pd.to_numeric(
                shortlist_df["view_to_buy_rate"],
                errors="coerce",
            )
        else:
            baseline_rates = pd.Series(
                float("nan"),
                index=shortlist_df.index,
            )

        shortlist_df["test_baseline_rate"] = baseline_rates

        shortlist_df["test_visits_per_variant"] = (
            baseline_rates.apply(required_visits_per_variant)
        )

        visits_numeric = pd.to_numeric(
            shortlist_df["test_visits_per_variant"],
            errors="coerce",
        )

        shortlist_df["test_target_rate"] = (
            baseline_rates * 1.20
        ).clip(upper=0.999999).where(visits_numeric.notna())

        shortlist_df["test_total_visits"] = visits_numeric * 2

        shortlist_df["test_daily_visits_per_variant"] = (
            visits_numeric.apply(
                lambda value: math.ceil(value / 14)
                if pd.notna(value) else None
            )
        )


        priced_count = int(
            shortlist_df["typical_price"].notna().sum()
        )

        unknown_count = len(shortlist_df) - priced_count

        # ---------------- Plan mix calculations ----------------

        total_products = len(shortlist_df)

        # Category distribution
        category_mix = (
            shortlist_df["item_category"]
            .fillna("Unknown category")
            .value_counts()
            .rename_axis("Category")
            .reset_index(name="Products")
        )

        category_mix["Share (%)"] = (
            category_mix["Products"] / total_products * 100
        ).round(1)

        # Price distribution using typical historical transaction prices
        numeric_prices = pd.to_numeric(
            shortlist_df["typical_price"],
            errors="coerce"
        )

        price_bands = pd.cut(
            numeric_prices,
            bins=[
                float("-inf"),
                10,
                25,
                50,
                float("inf")
            ],
            labels=[
                "Under $10",
                "$10–$24.99",
                "$25–$49.99",
                "$50+"
            ],
            right=False
        )

        price_mix = (
            price_bands.astype("object")
            .fillna("Unknown")
            .value_counts()
            .rename_axis("Price band")
            .reset_index(name="Products")
        )

        price_mix["Share (%)"] = (
            price_mix["Products"] / total_products * 100
        ).round(1)

        # Identify picks with weak or incomplete performance data
        weak_data = pd.Series(
            False,
            index=shortlist_df.index
        )

        for flag in [
            "views_likely_insufficient",
            "purchases_unmatched"
        ]:
            if flag in shortlist_df.columns:
                weak_data |= (
                    shortlist_df[flag]
                    .fillna(True)
                    .astype(bool)
                )
            else:
                weak_data |= True

        for metric in [
            "sessions_viewed",
            "view_to_buy_ci_low"
        ]:
            if metric in shortlist_df.columns:
                weak_data |= pd.to_numeric(
                    shortlist_df[metric],
                    errors="coerce"
                ).isna()
            else:
                weak_data |= True

        if "label" in shortlist_df.columns:
            weak_data |= shortlist_df["label"].eq(
                "Not Enough Data"
            ).fillna(False)

        weak_count = int(weak_data.sum())


        st.divider()
        st.markdown("### Plan overview")

        c1, c2, c3 = st.columns(3)

        c1.metric("Products selected", total_products)

        c2.metric("Products with price data", priced_count)

        c3.metric(
            "Picks with weak data",
            f"{weak_count}/{total_products}"
        )

        st.markdown("### Category and price mix")

        mix_col1, mix_col2 = st.columns(2)

        with mix_col1:
            st.markdown("**Category distribution**")
            st.bar_chart(
                category_mix.set_index("Category")["Products"]
            )
            st.dataframe(
                category_mix,
                width="stretch",
                hide_index=True
            )

        with mix_col2:
            st.markdown("**Price distribution**")
            st.bar_chart(
                price_mix.set_index("Price band")["Products"]
            )
            st.dataframe(
                price_mix,
                width="stretch",
                hide_index=True
            )

        st.caption(
            "Price bands use median historical transaction prices. "
            "Unknown prices are shown separately."
        )

        if weak_count:
            st.warning(
                f"{weak_count} of {total_products} picks rely on "
                "weak or incomplete performance data. "
                "Cart add-ons without product-level view metrics "
                "are also included."
            )
        else:
            st.success(
                "All selected products have sufficient performance data."
            )

        # Person C: AI plan review (rule checks + Gemini). See AI_PLAN.md.
        ai_panel.render_plan_review(
            st.session_state.shortlist, summary_df, load_weekly(),
            load_pairs(), load_rescue(), price_df,
        )

        st.markdown("### Your selected products")

        display_columns = [
            "item_name",
            "item_category",
            "typical_price",
            "min_price",
            "max_price",
            "holiday_phase",
            "placement_slot",
            "paired_with",
            "replaces",
            "sessions_viewed",
            "sessions_purchased",
            "view_to_buy_rate",
            "view_to_buy_ci_low",
            "revenue",
            "label",
            "replacement_product",
            "test_visits_per_variant",
            "test_total_visits",
            "test_daily_visits_per_variant",
        ]

        st.dataframe(
            shortlist_df.reindex(columns=display_columns),
            width="stretch",
            hide_index=True,
        )

        # Export the complete merchandising plan.
        export_columns = [
            "item_name",
            "item_category",
            "typical_price",
            "min_price",
            "max_price",
            "holiday_phase",
            "placement_slot",
            "paired_with",
            "replacement_product",
            "replaces",
            "sessions_viewed",
            "sessions_purchased",
            "view_to_buy_rate",
            "view_to_buy_ci_low",
            "view_to_buy_ci_high",
            "revenue",
            "label",
            "test_baseline_rate",
            "test_target_rate",
            "test_visits_per_variant",
            "test_total_visits",
            "test_daily_visits_per_variant",
        ]

        csv_data = (
            shortlist_df.reindex(columns=export_columns)
            .to_csv(index=False)
            .encode("utf-8-sig")
        )

        st.download_button(
            "Download shelf plan (CSV)",
            data=csv_data,
            file_name="holiday_shelf_plan.csv",
            mime="text/csv",
        )

        pdf_data = build_shelf_brief_pdf(
            shortlist_df,
            category_mix,
            price_mix,
            weak_count,
        )

        st.download_button(
            "Download one-page brief (PDF)",
            data=pdf_data,
            file_name="holiday_shelf_brief.pdf",
            mime="application/pdf",
        )


        st.caption(
            "Typical price is the median recorded transaction price. "
            "Minimum and maximum show the observed historical price range."
        )

        if unknown_count:
            st.warning(
                f"{unknown_count} selected product(s) have no matching "
                "transaction-price data."
            )

    else:
        st.info(
            "Your shortlist is empty. Add products from the "
            "Shelf Scorecard or Opportunity Finder."
        )

"""Shortlist Builder: plan board, one editable table with bulk actions, AI review, export.

The plan logic lives in shortlist_plan.py; this file only draws the page."""

import math
from io import BytesIO
from statistics import NormalDist
from xml.sax.saxutils import escape

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import ai_panel
from ai_context import PHASES, SLOTS, recommended_phases
from shared import (
    load_pairs,
    load_product_prices,
    load_product_summary,
    load_rescue,
    load_weekly,
)
from shortlist_plan import (
    apply_table_edits,
    bad_replacements,
    board_html,
    fill_empty_phases,
    normalize_shortlist,
    plan_stats,
    plan_table,
    remove_keys,
    replacement_options,
    set_for,
    use_playbook_phases,
)
from ui import LABEL_COLORS


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



def build_shelf_brief_pdf(shortlist_df, category_mix, price_mix, weak_count, review_notes=None):
    """Generate a one-page landscape merchandising brief.

    review_notes: optional lines from the AI second opinion (already number-checked)."""
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
    if review_notes:
        story += [
            Spacer(1, 6),
            Paragraph("<b>Second opinion (written by Gemini; every number checked against the "
                      "data):</b>", note_style),
            *[Paragraph("• " + escape(line), note_style) for line in review_notes],
        ]
    doc.build([KeepInFrame(720, 536, story, mode="shrink")])
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def _visits_per_day(rate):
    """Daily visits per variant for the two-week test, or None without a rate."""
    visits = required_visits_per_variant(rate)
    return None if visits is None else math.ceil(visits / 14)


@st.cache_data
def _recommended_phases():
    return recommended_phases(load_weekly())


def _commit(new_shortlist: dict, message: str) -> None:
    """Save a bulk change, reset the table's edit state, and redraw."""
    st.session_state.shortlist = new_shortlist
    st.session_state["plan_msg"] = message
    st.session_state["plan_editor_v"] = st.session_state.get("plan_editor_v", 0) + 1
    st.rerun()


def _size_status(n: int) -> tuple[str, str]:
    if n < 10:
        return f"Add {10 - n} more", "inverse"
    if n > 15:
        return f"{n - 15} over", "inverse"
    return "In range", "normal"


def _render_tiles(stats: dict) -> None:
    n = stats["count"]
    note, color = _size_status(n)
    t1, t2, t3, t4, t5 = st.columns(5)
    t1.metric("Products", n, delta=note, delta_color=color, delta_arrow="off",
              help="The brief asks for 10–15 featured products.")
    covered = stats["phases_covered"]
    t2.metric("Phases covered", f"{covered} / 4",
              delta="All covered" if covered == 4 else f"{4 - covered} empty",
              delta_color="normal" if covered == 4 else "inverse", delta_arrow="off")
    share = stats["top_category_share"]
    t3.metric("Top category", f"{share}%", delta=stats["top_category"],
              delta_color="inverse" if share > 40 else "off", delta_arrow="off",
              help="Above 40% of the plan in one category is flagged as overload.")
    weak = stats["weak"]
    t4.metric("Weak data", weak, delta="OK" if not weak else "Check these",
              delta_color="normal" if not weak else "inverse", delta_arrow="off",
              help="Too few views, unmatched purchases, or a very wide 95% range.")
    off = stats["off_playbook"]
    t5.metric("Off-Playbook", off, delta="Aligned" if not off else "Different phase",
              delta_color="normal" if not off else "off", delta_arrow="off",
              help="Picks scheduled in a phase other than their best phase on the Season Playbook.")


def _render_empty_state(summary_df, recommended) -> None:
    st.info("Your shortlist is empty. Add products from the Shelf Scorecard or "
            "Opportunity Finder, or start from a ready-made plan.")
    with st.container(border=True):
        st.markdown("**Quick start**")
        st.caption("Adds the strongest Stars (then Hidden Gems) for each holiday phase, using each product's best "
                   "phase from the Season Playbook. Strongest means the highest low end of the 95% "
                   "range, so products with little data can't win on luck. You can edit everything after.")
        per_phase = st.segmented_control("Products per phase", [2, 3, 4], default=3,
                                         key="quick_start_n")
        if st.button("✨ Build a starter plan", type="primary"):
            new, added = fill_empty_phases({}, summary_df, recommended, per_phase=per_phase or 3)
            _commit(new, f"Added {len(added)} products across the four phases. Edit them below.")


def _render_editor(shortlist, table, summary_df, recommended, stats) -> None:
    st.markdown("### Edit the plan")
    st.caption("Change phase, slot or what each pick replaces right in the table. "
               "Tick rows to move or remove several at once.")

    a1, a2, _ = st.columns([1.3, 1.3, 2])
    if a1.button("✨ Use Playbook timing for all", disabled=stats["off_playbook"] == 0,
                 help="Move every pick to its best phase on the Season Playbook.",
                 width="stretch"):
        new, moved = use_playbook_phases(shortlist, recommended)
        _commit(new, f"Moved {moved} product{'s' if moved != 1 else ''} to their Season Playbook phase.")
    if a2.button("➕ Fill the plan", disabled=stats["phases_covered"] == 4 and len(shortlist) >= 10,
                 help="Add the two strongest unused Stars (or Hidden Gems) to each empty phase, "
                      "then top the plan up to 10 picks, always into the thinnest phase.",
                 width="stretch"):
        new, added = fill_empty_phases(shortlist, summary_df, recommended, per_phase=2, min_total=10)
        if added:
            _commit(new, "Added " + ", ".join(added) + ".")
        st.info("No unused Stars or Hidden Gems have an empty phase as their best phase.")

    toolbar = st.container()
    version = st.session_state.get("plan_editor_v", 0)
    edited = st.data_editor(
        table,
        key=f"plan_editor_{version}",
        hide_index=True,
        width="stretch",
        height=35 * (len(table) + 1) + 3,  # every row visible, no scrolling inside the table
        column_order=[c for c in table.columns if c != "key"],
        disabled=["Product", "Label", "Category", "Price", "Conversion", "Weak data",
                  "Playbook phase", "Test visits/day"],
        column_config={
            "Select": st.column_config.CheckboxColumn("✓", width="small"),
            "Product": st.column_config.TextColumn(width="medium", pinned=True),
            "Label": st.column_config.TextColumn(width="small"),
            "Category": st.column_config.TextColumn(width="small"),
            "Price": st.column_config.NumberColumn(format="$%.2f", width="small",
                                                   help="Median transaction price."),
            "Conversion": st.column_config.NumberColumn(
                "View → buy", format="percent", width="small",
                help="Share of sessions that viewed the product and bought it."),
            "Weak data": st.column_config.CheckboxColumn(width="small"),
            "Playbook phase": st.column_config.TextColumn(
                width="medium", help="Best phase on the Season Playbook (most purchases per week)."),
            "Phase": st.column_config.SelectboxColumn(options=PHASES, required=True, width="medium"),
            "Slot": st.column_config.SelectboxColumn(options=SLOTS, required=True, width="medium"),
            "Replaces": st.column_config.SelectboxColumn(
                options=replacement_options(shortlist, summary_df) + ["— (add-on)"],
                width="medium",
                help="A weaker product in the same category that this pick takes the place of. "
                     "Cart add-ons don't replace anything."),
            "Test visits/day": st.column_config.NumberColumn(
                width="small", help="Visits per variant per day for a two-week A/B test."),
        },
    )

    new, changed = apply_table_edits(shortlist, edited)
    if changed:
        st.session_state.shortlist = new
        st.rerun()

    selected = edited.loc[edited["Select"].astype(bool), "key"].tolist()
    if selected:
        with toolbar.container(border=True):
            st.markdown(f"**{len(selected)} selected**")
            c1, c2, c3, c4 = st.columns([2, 2, 1, 1], vertical_alignment="bottom")
            phase = c1.selectbox("Move to phase", PHASES, index=None,
                                 placeholder="Keep phase", key=f"bulk_phase_{version}")
            slot = c2.selectbox("Set slot", SLOTS, index=None,
                                placeholder="Keep slot", key=f"bulk_slot_{version}")
            if c3.button("Apply", type="primary", disabled=not (phase or slot), width="stretch"):
                _commit(set_for(shortlist, selected, phase=phase, slot=slot),
                        f"Updated {len(selected)} product{'s' if len(selected) != 1 else ''}.")
            if c4.button("🗑 Remove", width="stretch"):
                _commit(remove_keys(shortlist, selected),
                        f"Removed {len(selected)} product{'s' if len(selected) != 1 else ''}.")

    bad = bad_replacements(shortlist, summary_df)
    if bad:
        st.warning("These replacements aren't weaker products in the same category: "
                   + "; ".join(f"**{p}** → {r}" for p, r in bad))

    with st.expander("How the test traffic is sized"):
        st.markdown(
            "Each pick gets a two-week A/B test: the current shelf against the new one. "
            "**Test visits/day** is the traffic each version needs per day to detect a 20% "
            "relative lift in view-to-buy conversion (two-sided test, 95% confidence, 80% power). "
            "Products that already convert at low rates need far more traffic. "
            "Blank means the product has no usable conversion rate (for example, cart add-ons)."
        )


def render():
    st.title("Shortlist Builder")

    summary_df = load_product_summary()
    price_df = load_product_prices()
    recommended = _recommended_phases()

    if msg := st.session_state.pop("plan_msg", None):
        st.success(msg)

    if not st.session_state.shortlist:
        _render_empty_state(summary_df, recommended)
        return

    # Give every pick a valid phase/slot (new picks start in their Playbook phase).
    st.session_state.shortlist = normalize_shortlist(st.session_state.shortlist, recommended)
    shortlist = st.session_state.shortlist

    table = plan_table(shortlist, summary_df, price_df, recommended, _visits_per_day)
    stats = plan_stats(shortlist, table)

    _render_tiles(stats)

    st.markdown("### Plan by holiday phase")
    st.html(board_html(table, LABEL_COLORS))

    _render_editor(shortlist, table, summary_df, recommended, stats)

    # Person C: AI plan review (rule checks + Gemini). See AI_PLAN.md.
    st.divider()
    ai_panel.render_plan_review(
        st.session_state.shortlist, summary_df, load_weekly(),
        load_pairs(), load_rescue(), price_df,
    )

    # ---------------- Export table (unchanged columns) ----------------
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

    # Weak-data count for the brief: the same number as the page's Weak data tile
    # (each pick looked up in the product summary, so cart add-ons count correctly).
    weak_count = stats["weak"]



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


    st.markdown("### Export")

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

    with st.expander("Full plan table (same columns as the CSV)"):
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

    notes = ai_panel.brief_notes()
    pdf_data = build_shelf_brief_pdf(
        shortlist_df,
        category_mix,
        price_mix,
        weak_count,
        review_notes=notes,
    )

    st.download_button(
        "Download one-page brief (PDF)",
        data=pdf_data,
        file_name="holiday_shelf_brief.pdf",
        mime="application/pdf",
    )
    st.caption("The brief includes the AI second opinion for this plan." if notes else
               "Run the second opinion above to add its notes to the brief.")


    st.caption(
        "Typical price is the median recorded transaction price. "
        "Minimum and maximum show the observed historical price range."
    )

    if unknown_count:
        st.warning(
            f"{unknown_count} selected product(s) have no matching "
            "transaction-price data."
        )

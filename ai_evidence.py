"""
ai_evidence.py — the data behind each AI statement, computed without the AI.

For every issue and suggested fix the reviewer shows, this module builds:
  * citations: each number in Gemini's text, traced to the product and field
    it came from (or the rule check that produced it);
  * a product table with the underlying stats;
  * a small chart chosen by the kind of rule check behind the issue.

Nothing here calls Gemini, so the evidence is the same whether the AI is on or
off. Kept separate from ai_panel.py (drawing) and ai_review.py (the AI call).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ai_context import MIN_PHASE_VIEWS, PHASES
from ai_review import _NUMBER, FREE_INTEGERS, _strip_names
from ai_rules import ANCHOR_PRICE, MAX_CATEGORY_SHARE_PCT, STUFFER_PRICE, Finding

FIELD_LABELS = {
    "views": "views",
    "purchases": "purchases",
    "revenue": "revenue ($)",
    "view_to_buy_pct": "view-to-buy %",
    "ci_low_pct": "low end of 95% range",
    "ci_high_pct": "high end of 95% range",
    "price": "typical price ($)",
    "cart_abandon_pct": "cart abandonment %",
    "replaces_ci_low_pct": "low end of 95% range of the product it replaces",
    "pair_orders": "orders bought with its anchor",
    "plan_pair_orders": "orders bought with another pick",
    "orders_together": "orders bought together",
    "attach_rate_pct": "add-on attach %",
    "count": "products",
    "share_pct": "share of the plan %",
    "plan_count": "products in the plan",
    "limit_pct": "category limit %",
    "target_min": "brief's minimum",
    "target_max": "brief's maximum",
    "threshold": "price threshold ($)",
    "min_orders": "minimum orders",
    "best_pair_orders": "orders bought with another pick",
    "weak_data_count": "weak-data picks",
}

HIGHLIGHT = "#6366F1"
MUTED = "rgba(128,128,128,0.45)"
WARN = "#EF4444"


# ---------------------------------------------------------------------------
# Number citations
# ---------------------------------------------------------------------------


def _label(key: str) -> str:
    return FIELD_LABELS.get(key, key.replace("_", " "))


def number_sources(ctx: dict, findings: list[Finding]) -> list[tuple[float, str]]:
    """Every number the AI was allowed to use, with a readable source."""
    out: list[tuple[float, str]] = []

    def add(value, label):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        out.append((float(value), label))

    def product(entry: dict, where: str):
        for k, v in entry.items():
            if k == "best_addon" and isinstance(v, dict):
                for k2, v2 in v.items():
                    add(v2, f"{entry['name']} · best add-on {_label(k2)}")
            else:
                add(v, f"{entry['name']} · {_label(k)}{where}")

    for p in ctx.get("picks", []):
        product(p, "")
    for p in ctx.get("swap_pool", []):
        product(p, " (candidate)")
    plan = ctx.get("plan", {})
    for k, v in plan.items():
        if k == "category_mix":
            for c in v:
                add(c["count"], f"{c['name']} · picks in the plan")
                add(c["share_pct"], f"{c['name']} · share of the plan %")
        elif k == "price_mix":
            for c in v:
                add(c.get("count"), f"{c.get('name')} price band · picks")
        elif k == "phase_counts":
            for phase, n in v.items():
                add(n, f"{phase} · picks")
        else:
            add(v, f"Plan · {_label(k)}")
    for f in findings:
        for k, v in f.numbers.items():
            add(v, f"Rule check “{f.title}” · {_label(k)}")
    return out


def _relevance(label: str, text: str, linked_titles: set[str]) -> int:
    """0 = from a rule check this text is based on, or about the whole plan;
    1 = about a product named in the text; 2 = anything else (likely coincidence)."""
    if label.startswith("Rule check"):
        return 0 if any(f"“{t}”" in label for t in linked_titles) else 2
    if label.startswith("Plan ·"):
        return 0
    # A product, phase or category total only counts when the text names it.
    subject = label.split(" · ")[0]
    if subject in text:
        return 0 if subject in PHASES else 1
    return 2


def cite_numbers(text: str, sources: list[tuple[float, str]], names: set[str],
                 linked_titles: set[str] | None = None) -> list[dict]:
    """Each number in ``text`` with where it came from (same matching as verify).

    Sources are ranked: the rule checks the text is based on and plan-level
    facts first, then products the text names. A small whole number with only
    unrelated matches is shown as a count, not credited to a coincidence.
    """
    linked_titles = linked_titles or set()
    cites = []
    seen = set()
    for m in _NUMBER.finditer(_strip_names(text, names)):
        shown = m.group(0)
        if shown in seen:
            continue
        seen.add(shown)
        whole, decimals = m.group(1), m.group(2)
        value = float(whole.replace(",", "") + ("." + decimals if decimals else ""))
        places = len(decimals) if decimals else 0
        exact = [lab for v, lab in sources if v == value]
        rounded = [f"{lab} (rounded)" for v, lab in sources
                   if v != value and round(v, places) == round(value, places)]
        ranked = sorted(dict.fromkeys(exact + rounded),
                        key=lambda lab: (_relevance(lab, text, linked_titles), lab.endswith("(rounded)")))
        relevant = [lab for lab in ranked if _relevance(lab, text, linked_titles) < 2]
        small = not decimals and value in FREE_INTEGERS
        if shown.startswith("$"):
            # A dollar amount is only credited to a price; "$10" must not cite "10 products".
            prices = [lab for lab in ranked if "price" in lab.lower() or "$" in lab]
            found = prices or ["a round price threshold Gemini chose (compare the prices in the chart)"]
        elif small and not relevant:
            found = ["a count (small whole numbers are allowed)"]
        else:
            found = relevant or ranked
        cites.append({"number": shown, "sources": found[:3]})
    return cites


# ---------------------------------------------------------------------------
# Product table
# ---------------------------------------------------------------------------


def product_table(ctx: dict, names: list[str]) -> pd.DataFrame:
    """Stats for the named products (plan picks and candidates), in that order."""
    entries = {p["name"]: (p, True) for p in ctx.get("swap_pool", [])}
    entries.update({p["name"]: (p, False) for p in ctx.get("picks", [])})
    rows = []
    for name in dict.fromkeys(names):
        if name not in entries:
            continue
        p, candidate = entries[name]
        lo, hi = p.get("ci_low_pct"), p.get("ci_high_pct")
        rows.append({
            "Product": name,
            "In plan": "candidate" if candidate else "✓",
            "Phase": p.get("phase") or "—",
            "Best phase (Playbook)": p.get("recommended_phase") or "—",
            "Slot": p.get("slot") or "—",
            "Label": p.get("label") or "—",
            "Views": p.get("views"),
            "Purchases": p.get("purchases"),
            "View → buy %": p.get("view_to_buy_pct"),
            "95% range %": "—" if lo is None or hi is None else f"{lo}–{hi}",
            "Price $": p.get("price"),
            "Category": p.get("category"),
            "Weak data": "⚠️ " + "; ".join(p.get("weak_reasons") or []) if p.get("weak_data") else "",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Phase history (same rule as the Season Playbook / recommended_phases)
# ---------------------------------------------------------------------------


def phase_history(weekly: pd.DataFrame, name: str) -> pd.DataFrame:
    """Purchases per calendar week in each phase for one product."""
    if weekly is None or weekly.empty:
        return pd.DataFrame()
    weeks = weekly.groupby("phase")["week_start"].nunique()
    w = weekly[weekly["item_name"] == name]
    per = w.groupby("phase").agg(views=("sessions_viewed", "sum"),
                                 purchases=("sessions_purchased", "sum")).reindex(PHASES).fillna(0)
    per["weeks"] = [int(weeks.get(p, 0)) for p in PHASES]
    per["purchases_per_week"] = (per["purchases"] / per["weeks"].where(per["weeks"] > 0)).round(1)
    per["counts"] = (per["views"] >= MIN_PHASE_VIEWS) & (per["purchases"] <= per["views"])
    return per.reset_index(names="phase")


# ---------------------------------------------------------------------------
# Charts (plotly; drawn with ui.plot so they follow the app theme)
# ---------------------------------------------------------------------------


def _layout(fig: go.Figure, title: str, height: int = 230) -> go.Figure:
    fig.update_layout(title={"text": title, "font": {"size": 13}}, height=height,
                      margin={"l": 10, "r": 10, "t": 36, "b": 10}, showlegend=False)
    return fig


def category_chart(ctx: dict, highlight: str | None = None) -> go.Figure:
    mix = ctx["plan"]["category_mix"]
    names = [c["name"] for c in mix]
    shares = [c["share_pct"] for c in mix]
    colors = [WARN if s > MAX_CATEGORY_SHARE_PCT else (HIGHLIGHT if n == highlight else MUTED)
              for n, s in zip(names, shares)]
    fig = go.Figure(go.Bar(x=shares, y=names, orientation="h", marker_color=colors,
                           text=[f"{s}%" for s in shares], textposition="outside",
                           hovertemplate="%{y}: %{x}% of the plan<extra></extra>"))
    fig.add_vline(x=MAX_CATEGORY_SHARE_PCT, line_dash="dash", line_color=WARN,
                  annotation_text=f"{MAX_CATEGORY_SHARE_PCT}% limit", annotation_position="top")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, max(shares + [MAX_CATEGORY_SHARE_PCT]) * 1.25], ticksuffix="%")
    return _layout(fig, "Share of the plan by category")


def phase_count_chart(ctx: dict) -> go.Figure:
    counts = ctx["plan"]["phase_counts"]
    values = [counts.get(p, 0) for p in PHASES]
    fig = go.Figure(go.Bar(x=PHASES, y=values, marker_color=[WARN if v == 0 else HIGHLIGHT for v in values],
                           text=values, textposition="outside",
                           hovertemplate="%{x}: %{y} picks<extra></extra>"))
    fig.update_yaxes(range=[0, max(values + [1]) * 1.3], dtick=1)
    return _layout(fig, "Picks scheduled in each holiday phase")


def phase_history_chart(weekly: pd.DataFrame, name: str, planned: str | None, best: str | None) -> go.Figure | None:
    h = phase_history(weekly, name)
    if h.empty:
        return None
    colors = [HIGHLIGHT if p == best else (WARN if p == planned else MUTED) for p in h["phase"]]
    text = [f"{v:g}/wk" + ("" if ok else " (too few views)")
            for v, ok in zip(h["purchases_per_week"].fillna(0), h["counts"])]
    fig = go.Figure(go.Bar(x=h["phase"], y=h["purchases_per_week"], marker_color=colors, text=text,
                           textposition="outside",
                           customdata=h[["views", "purchases", "weeks"]].values,
                           hovertemplate="%{x}<br>%{customdata[1]:.0f} purchases over %{customdata[2]} weeks"
                                         "<br>%{customdata[0]:.0f} views<extra></extra>"))
    fig.update_yaxes(range=[0, (h["purchases_per_week"].max() or 1) * 1.35])
    return _layout(fig, f"{name}: purchases per week by phase (blue = best, red = planned)")


def range_chart(table: pd.DataFrame) -> go.Figure | None:
    """View-to-buy rate with its 95% range, one row per product."""
    rows = []
    for r in table.to_dict("records"):
        if r["View → buy %"] is None or r["95% range %"] == "—":
            continue
        lo, hi = (float(x) for x in r["95% range %"].split("–"))
        rows.append((r["Product"], r["View → buy %"], lo, hi, bool(r["Weak data"])))
    if not rows:
        return None
    names, rate, lo, hi, weak = zip(*rows)
    fig = go.Figure(go.Scatter(
        x=rate, y=names, mode="markers",
        marker={"size": 11, "color": [WARN if w else HIGHLIGHT for w in weak]},
        error_x={"type": "data", "symmetric": False,
                 "array": [h - r for h, r in zip(hi, rate)],
                 "arrayminus": [r - lo_ for r, lo_ in zip(rate, lo)]},
        hovertemplate="%{y}: %{x}% (95% range shown)<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(ticksuffix="%", rangemode="tozero")
    return _layout(fig, "View-to-buy rate with 95% range (red = weak data)", height=max(160, 46 * len(rows) + 70))


def price_chart(ctx: dict, phase: str, threshold: float, above: bool) -> go.Figure | None:
    picks = [p for p in ctx["picks"] if p.get("phase") == phase and p.get("price") is not None]
    if not picks:
        return None
    names = [p["name"] for p in picks]
    prices = [p["price"] for p in picks]
    fig = go.Figure(go.Bar(x=prices, y=names, orientation="h", marker_color=HIGHLIGHT,
                           text=[f"${v:,.2f}" for v in prices], textposition="outside",
                           hovertemplate="%{y}: $%{x:,.2f}<extra></extra>"))
    fig.add_vline(x=threshold, line_dash="dash", line_color=WARN,
                  annotation_text=f"${threshold}", annotation_position="top")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(tickprefix="$", range=[0, max(prices + [threshold]) * 1.3])
    want = "at or above" if above else "below"
    return _layout(fig, f"{phase} picks by price (need one {want} ${threshold})",
                   height=max(160, 40 * len(picks) + 70))


def finding_charts(f: Finding, ctx: dict, weekly: pd.DataFrame) -> list[go.Figure]:
    """The chart that shows a rule check's evidence best."""
    picks = {p["name"]: p for p in ctx["picks"]}
    if f.id == "category_overload":
        return [category_chart(ctx)]
    if f.id in ("empty_phase", "plan_size"):
        return [phase_count_chart(ctx)]
    if f.id == "phase_mismatch" and f.products:
        p = picks.get(f.products[0], {})
        fig = phase_history_chart(weekly, f.products[0], p.get("phase"), p.get("recommended_phase"))
        return [fig] if fig else []
    if f.id in ("weak_data", "downgrade"):
        fig = range_chart(product_table(ctx, f.products))
        return [fig] if fig else []
    if f.id == "no_anchor":
        fig = price_chart(ctx, "Black Friday / Cyber Monday", ANCHOR_PRICE, above=True)
        return [fig] if fig else []
    if f.id == "no_stuffer":
        fig = price_chart(ctx, "Mid-Dec", STUFFER_PRICE, above=False)
        return [fig] if fig else []
    return []


def issue_evidence(products: list[str], linked: list[Finding], ctx: dict, weekly: pd.DataFrame):
    """(product table, charts) for one issue. Charts are de-duplicated by kind."""
    names = list(products)
    for f in linked:
        names += f.products
    charts, kinds = [], set()
    for f in linked:
        kind = f.id if f.id in ("phase_mismatch",) else f.id.split("_")[0]
        key = (kind, tuple(f.products) if f.id == "phase_mismatch" else ())
        if key in kinds:
            continue
        kinds.add(key)
        charts += finding_charts(f, ctx, weekly)
    if not linked:  # Gemini's own observation: show the rate ranges of what it names
        fig = range_chart(product_table(ctx, names))
        if fig:
            charts.append(fig)
    return product_table(ctx, names), charts[:3]


def action_evidence(action, ctx: dict, weekly: pd.DataFrame):
    """(table, chart or None, one-line summary) comparing before and after."""
    if action.type == "swap":
        table = product_table(ctx, [action.product, action.add])
        if not table.empty:
            table.insert(0, "Role", ["Out" if n == action.product else "In" for n in table["Product"]])
        return table, range_chart(table), "Compare the pick going out with the candidate coming in."
    if action.type == "move_phase":
        p = next((x for x in ctx["picks"] if x["name"] == action.product), {})
        h = phase_history(weekly, action.product)
        fig = phase_history_chart(weekly, action.product, p.get("phase"), action.phase)
        summary = ""
        if not h.empty:
            cur = h.loc[h["phase"] == p.get("phase"), "purchases_per_week"]
            new = h.loc[h["phase"] == action.phase, "purchases_per_week"]
            if len(cur) and len(new):
                summary = (f"Last season: {cur.iloc[0]:g} purchases/week in {p.get('phase')} "
                           f"vs {new.iloc[0]:g} in {action.phase}.")
        return product_table(ctx, [action.product]), fig, summary
    return product_table(ctx, [action.product]), None, "The pick that would be removed."


FIELD_NAMES = {
    "product": "Product", "plan_status": "Plan status", "phase": "Phase", "best_phase": "Best phase",
    "slot": "Slot", "label": "Label", "category": "Category", "views": "Views", "purchases": "Purchases",
    "view_to_buy_pct": "View → buy %", "price": "Price $", "weak_data": "Weak data", "week": "Week",
    "picks": "Number of picks",
}


def chart_data(chart, ctx: dict, weekly: pd.DataFrame) -> pd.DataFrame:
    """The rows behind a Gemini-designed chart, straight from the context and weekly data."""
    picks = {p["name"]: p for p in ctx["picks"]}
    pool = {p["name"]: p for p in ctx["swap_pool"]}
    if chart.products:
        names = list(dict.fromkeys(chart.products))
    else:
        names = list(picks) + (list(pool) if chart.include_candidates else [])
    if chart.data == "weekly":
        if weekly is None or weekly.empty:
            return pd.DataFrame()
        names = names[:6]
        w = weekly[weekly["item_name"].isin(names)]
        return pd.DataFrame({"product": w["item_name"], "week": pd.to_datetime(w["week_start"]),
                             "phase": w["phase"], "views": w["sessions_viewed"],
                             "purchases": w["sessions_purchased"]}).sort_values("week")
    rows = []
    for name in names:
        p = picks.get(name) or pool.get(name)
        if p is None:
            continue
        rows.append({
            "product": name, "plan_status": "In plan" if name in picks else "Candidate",
            "phase": p.get("phase") or "Not scheduled", "best_phase": p.get("recommended_phase") or "—",
            "slot": p.get("slot") or "—", "label": p.get("label") or "—", "category": p.get("category"),
            "views": p.get("views"), "purchases": p.get("purchases"),
            "view_to_buy_pct": p.get("view_to_buy_pct"), "price": p.get("price"),
            "weak_data": "Weak data" if p.get("weak_data") else "OK",
            "picks": 1, "_lo": p.get("ci_low_pct"), "_hi": p.get("ci_high_pct"),
        })
    return pd.DataFrame(rows)


def chart_for(chart, ctx: dict, weekly: pd.DataFrame) -> go.Figure | None:
    """Build the chart Gemini designed (an ai_review.Chart). Every value comes from chart_data."""
    import plotly.express as px

    df = chart_data(chart, ctx, weekly)
    needed = [f for f in (chart.x, chart.y, chart.color, chart.size) if f]
    if df.empty or any(f not in df.columns for f in needed):
        return None
    df = df.dropna(subset=[chart.x, chart.y])
    if df.empty:
        return None
    labels = {k: v for k, v in FIELD_NAMES.items() if k in df.columns}
    kwargs = {"x": chart.x, "y": chart.y, "color": chart.color, "labels": labels,
              "hover_data": [c for c in ("product", "phase", "view_to_buy_pct", "price") if c in df.columns]}
    if chart.show_range and "_lo" in df.columns and "view_to_buy_pct" in (chart.x, chart.y):
        df = df.assign(_plus=df["_hi"] - df["view_to_buy_pct"], _minus=df["view_to_buy_pct"] - df["_lo"])
        axis = "y" if chart.y == "view_to_buy_pct" else "x"
        kwargs[f"error_{axis}"], kwargs[f"error_{axis}_minus"] = "_plus", "_minus"
    if chart.mark == "bar":
        fig = px.bar(df, **kwargs)
        # Print each bar's value so the gap to a limit reads without hovering.
        value = chart.x if chart.x in NUMERIC_AXES else chart.y
        fmt = {"price": "$%{V:,.2f}", "view_to_buy_pct": "%{V}%"}.get(value, "%{V:,}")
        fig.update_traces(texttemplate=fmt.replace("V", "x" if value == chart.x else "y"),
                          textposition="outside", cliponaxis=False)
    elif chart.mark == "line":
        fig = px.line(df, markers=True, **{k: v for k, v in kwargs.items() if not k.startswith("error")})
    else:
        fig = px.scatter(df, size=chart.size, **kwargs)
        fig.update_traces(marker={"sizemin": 6} if chart.size else {"size": 11})
    if chart.reference_line is not None:
        money = "price" in (chart.x, chart.y)
        value = f"${chart.reference_line:g}" if money else f"{chart.reference_line:g}"
        label = f"{chart.line_label}: {value}" if chart.line_label else value
        if chart.y in NUMERIC_AXES:
            fig.add_hline(y=chart.reference_line, line_dash="dash", line_color=WARN,
                          annotation_text=label, annotation_position="top left")
            fig.update_yaxes(range=[0, max(float(df[chart.y].max()), chart.reference_line) * 1.2])
        else:
            fig.add_vline(x=chart.reference_line, line_dash="dash", line_color=WARN,
                          annotation_text=label, annotation_position="top left")
            fig.update_xaxes(range=[0, max(float(df[chart.x].max()), chart.reference_line) * 1.2])
    categorical_y = chart.y not in NUMERIC_AXES
    height = max(230, 36 * df[chart.y].nunique() + 90) if categorical_y else 280
    fig = _layout(fig, chart.title or f"{FIELD_NAMES[chart.y]} by {FIELD_NAMES[chart.x]}", height=height)
    fig.update_layout(showlegend=chart.color is not None,
                      legend={"orientation": "h", "yanchor": "top", "y": -0.25, "x": 0})
    if chart.color is not None:
        fig.update_layout(height=fig.layout.height + 40, margin={"b": 50})
    return fig


NUMERIC_AXES = {"views", "purchases", "view_to_buy_pct", "price", "week", "picks"}

"""
ai_panel.py — the "Plan review" section of the Shortlist Builder.

Kept out of the page code so the UI stays a thin layer: the page passes in the
dataframes it already loads, and this module calls ai_context / ai_rules /
ai_review / ai_evidence. Works with no API key (rule checks only).

Every block is labelled with where it comes from, so a reader can tell the AI's
words from the data:
  🤖 Gemini     text written by the model (already checked by ai_review.verify)
  📏 Rule check  a deterministic check in ai_rules.py
  📊 Data        tables and charts computed straight from the data (ai_evidence.py)
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import streamlit as st

import ui
from ai_context import PHASES, build_context
from ai_evidence import (
    FIELD_NAMES,
    action_evidence,
    chart_for,
    cite_numbers,
    issue_evidence,
    number_sources,
)
from ai_review import (
    DEFAULT_MODEL,
    Action,
    Issue,
    ReviewResult,
    apply_action,
    finding_refs,
    review_plan,
)
from ai_rules import Finding, run_rules

SEVERITY_STYLE = {
    "high": ("🔴", "High"),
    "medium": ("🟠", "Medium"),
    "low": ("🟡", "Low"),
}
ACTION_VERB = {"swap": "Swap", "move_phase": "Move", "remove": "Remove"}

GEMINI = ":violet-badge[🤖 Written by Gemini]"
RULE = ":blue-badge[📏 Rule check]"
DATA = ":green-badge[📊 From the data, no AI]"
OWN = ":orange-badge[💡 Gemini's own observation, not from a rule check]"
CHOSEN = ":violet-badge[🤖 Chart designed by Gemini] :green-badge[📊 every value drawn from the data]"

TABLE_CONFIG = {
    "View → buy %": st.column_config.NumberColumn(format="%.2f%%"),
    "Price $": st.column_config.NumberColumn(format="$%.2f"),
    "Views": st.column_config.NumberColumn(format="%d"),
    "Purchases": st.column_config.NumberColumn(format="%d"),
}


def _md(text: str) -> str:
    """Escape $ so Streamlit markdown doesn't treat prices as a math formula."""
    return text.replace("$", "\\$")


def _secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:  # no secrets.toml at all
        return default


def _plan_hash(ctx: dict, model: str, planted: bool) -> str:
    raw = json.dumps(ctx, sort_keys=True, ensure_ascii=False) + model + str(planted)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Evidence blocks (data only)
# ---------------------------------------------------------------------------


def _evidence(table: pd.DataFrame, charts: list, key: str, note: str = "") -> None:
    st.markdown(DATA)
    if note:
        st.caption(note)
    if not table.empty:
        st.dataframe(table, hide_index=True, width="stretch", column_config=TABLE_CONFIG)
    for i, fig in enumerate(charts):
        ui.plot(fig, key=f"{key}_chart_{i}")
    if table.empty and not charts:
        st.caption("This point is about the plan as a whole; see the tiles at the top of the page.")


def _citations(text: str, sources, names: set[str], linked: list[Finding] | None = None) -> None:
    cites = cite_numbers(text, sources, names, {f.title for f in linked or []})
    if not cites:
        return
    lines = []
    for c in cites:
        where = "  or  ".join(c["sources"][:2]) if c["sources"] else "no source found"
        # Escape $ so Streamlit doesn't read "$50 ... $20" as a math formula.
        lines.append(f"- `{c['number']}` ← {_md(where)}")
    with st.container(border=False):
        st.caption("**Where the numbers come from**")
        st.caption("\n".join(lines))


def _chosen_chart(issue: Issue, ctx: dict, weekly: pd.DataFrame, key: str) -> None:
    """The chart Gemini designed for this issue, filled by the app from the data."""
    c = issue.chart
    fig = chart_for(c, ctx, weekly) if c else None
    if fig is None:
        return
    st.markdown(CHOSEN)
    if c.why:
        st.markdown(f"**Why this chart:** {_md(c.why)}")
    ui.plot(fig, key=key)
    if c.look_for:
        st.markdown(f"👀 **What to look for:** {_md(c.look_for)}")
    parts = [f"**{c.mark}**", f"x = {FIELD_NAMES[c.x]}", f"y = {FIELD_NAMES[c.y]}"]
    if c.color:
        parts.append(f"colour = {FIELD_NAMES[c.color]}")
    if c.size:
        parts.append(f"size = {FIELD_NAMES[c.size]}")
    if c.show_range:
        parts.append("with 95% range")
    if c.reference_line is not None:
        parts.append(f"line at {c.reference_line:g}")
    shown = ", ".join(c.products) if c.products else (
        "all picks and candidates" if c.include_candidates else "all picks")
    st.caption(_md("Gemini's design: " + " · ".join(parts) + f" · {c.data} data · showing {shown}"))


def _linked_rules(issue: Issue, refs: dict[str, Finding]) -> list[Finding]:
    return [refs[r] for r in issue.based_on if r in refs]


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def _issue_card(issue: Issue, i: int, result: ReviewResult, refs, ctx, weekly, sources, names, key):
    icon, label = SEVERITY_STYLE.get(issue.severity, ("⚪", issue.severity))
    linked = _linked_rules(issue, refs)
    with st.container(border=True):
        if result.source == "gemini":
            st.markdown(f"{icon} **Point {i + 1}: {_md(issue.title)}** &nbsp; {GEMINI}")
            st.markdown(_md(issue.explanation))
            _citations(issue.explanation, sources, names, linked)
            if linked:
                st.markdown("**Based on:** " + " ".join(f"{RULE} {f.title}" for f in linked))
            else:
                st.markdown(OWN)
            _chosen_chart(issue, ctx, weekly, f"{key}_issue_{i}_chosen")
        else:
            st.markdown(f"{icon} **{issue.title}** &nbsp; {RULE}")
            st.markdown(_md(issue.explanation))
        st.caption(f"{label} priority")
        # Open the first card's evidence only when Gemini didn't draw its own chart above.
        with st.expander("📊 Evidence: the data behind this", expanded=(i == 0 and issue.chart is None)):
            table, charts = issue_evidence(issue.products, linked, ctx, weekly)
            _evidence(table, charts, f"{key}_issue_{i}")


def _action_card(action: Action, i: int, result: ReviewResult, ctx, weekly, sources, names, key, summary):
    with st.container(border=True):
        c1, c2 = st.columns([5, 1])
        badge = GEMINI if result.source == "gemini" else RULE
        c1.markdown(f"{_action_text(action)} &nbsp; {badge}")
        c1.markdown(_md(action.reason))
        if result.source == "gemini":
            with c1:
                _citations(action.reason, sources, names)
        if c2.button("Apply", key=f"ai_apply_{key}_{i}", type="primary"):
            summary_rows = {r["item_name"]: r for r in summary.to_dict("records")}
            new, clear = apply_action(st.session_state.shortlist, action, summary_rows)
            st.session_state.shortlist = new
            for k in clear:
                st.session_state.pop(k, None)
            # The Builder's table keeps its own edit state; start it fresh.
            st.session_state["plan_editor_v"] = st.session_state.get("plan_editor_v", 0) + 1
            st.session_state["ai_applied_msg"] = (
                f"Applied: {ACTION_VERB[action.type]} {action.product}. Review again to check the new plan."
            )
            st.rerun()
        with st.expander("📊 Before / after"):
            table, fig, note = action_evidence(action, ctx, weekly)
            _evidence(table, [fig] if fig else [], f"{key}_action_{i}", note)


def _action_text(a: Action) -> str:
    if a.type == "swap":
        where = ", ".join(x for x in [a.phase, a.slot] if x)
        return f"**Swap** {a.product} → **{a.add}**" + (f" ({where})" if where else "")
    if a.type == "move_phase":
        return f"**Move** {a.product} → **{a.phase}**"
    return f"**Remove** {a.product}"


def _rule_list(findings: list[Finding], ctx: dict, weekly: pd.DataFrame, key: str,
               featured: dict[str, int] | None = None) -> None:
    """The automatic checks as a quiet list (one line each; open a line for its data).
    After a Gemini review, each line says which of Gemini's points used it."""
    for ref, f in finding_refs(findings).items():
        icon, label = SEVERITY_STYLE.get(f.severity, ("⚪", f.severity))
        tag = ""
        if featured is not None:
            tag = f"  ·  used in Gemini's point {featured[ref]}" if ref in featured else "  ·  not featured by Gemini"
        with st.expander(f"{icon} {_md(f.title)}{tag}"):
            st.markdown(f"{RULE} &nbsp; {_md(f.message)}")
            st.caption(f"{label} priority · check `{f.id}` · numbers come straight from the data")
            table, charts = issue_evidence([], [f], ctx, weekly)
            _evidence(table, charts, f"{key}_{ref}")


def _what_gemini_did(result: ReviewResult, findings: list[Finding]) -> None:
    """One row of chips saying what the AI added on top of the automatic checks."""
    review, log = result.review, result.log or []
    used = {r for i in review.issues for r in i.based_on}
    own = sum(1 for i in review.issues if not i.based_on)
    charts = sum(1 for i in review.issues if i.chart)
    numbers = [x for x in log if x["item"].startswith(("issue", "action", "chart", "headline"))]
    kept = sum(1 for x in numbers if x["kept"])
    chips = [
        f":blue-badge[📏 read {len(findings)} automatic check{'s' if len(findings) != 1 else ''}]",
        (f":violet-badge[🔢 ranked them into {len(review.issues)} point{'s' if len(review.issues) != 1 else ''}"
         f" (used {len(used)} of {len(findings)})]"),
    ]
    if own:
        chips.append(f":orange-badge[💡 added {own} observation{'s' if own != 1 else ''} of its own]")
    if charts:
        chips.append(f":violet-badge[📈 designed {charts} chart{'s' if charts != 1 else ''}]")
    if review.actions:
        chips.append(f":violet-badge[🛠 proposed {len(review.actions)} fix{'es' if len(review.actions) != 1 else ''}]")
    removed = len(numbers) - kept
    chips.append(f":green-badge[✓ checked against the data: {kept} kept"
                 + (f", {removed} removed]" if removed else "]"))
    st.markdown("**What Gemini added:** " + " ".join(chips))


def _render_ai(result: ReviewResult, key: str, ctx: dict, findings: list[Finding],
               weekly: pd.DataFrame, summary: pd.DataFrame) -> None:
    """Gemini's second opinion: one labelled zone, then the checks it started from."""
    review = result.review
    log = result.log or []
    refs = finding_refs(findings)
    sources = number_sources(ctx, findings)
    names = {p["name"] for p in ctx["picks"] + ctx["swap_pool"]} | set(PHASES) | set(summary["item_name"])

    with st.container(border=True):
        st.markdown(f"{GEMINI} &nbsp; **Gemini's second opinion**")
        st.markdown(f"#### {_md(review.headline)}")
        _what_gemini_did(result, findings)

    for i, issue in enumerate(review.issues):
        _issue_card(issue, i, result, refs, ctx, weekly, sources, names, key)

    if review.actions:
        st.markdown(f"**Suggested fixes** &nbsp; {GEMINI} &nbsp; nothing changes until you click Apply")
        for i, action in enumerate(review.actions):
            _action_card(action, i, result, ctx, weekly, sources, names, key, summary)

    if log:
        dropped = [x for x in log if not x["kept"]]
        title = (f"✓ Verification log: {len(dropped)} removed before you saw it" if dropped
                 else "✓ Verification log: nothing needed removing")
        with st.expander(title, expanded=bool(dropped) and result.planted):
            for entry in log:
                mark = "✅ kept" if entry["kept"] else "❌ removed"
                st.markdown(f"{mark} · {_md(entry['item'])}  \n<small>{_md(entry['reason'])}</small>",
                            unsafe_allow_html=True)

    featured = {}
    for n, issue in enumerate(review.issues, 1):
        for r in issue.based_on:
            featured.setdefault(r, n)
    with st.expander(f"📏 The {len(findings)} automatic checks Gemini started from (no AI)"):
        _rule_list(findings, ctx, weekly, f"{key}_start", featured)


def _render_rules_only(result: ReviewResult, key: str, ctx: dict, findings: list[Finding],
                       weekly: pd.DataFrame, summary: pd.DataFrame) -> None:
    """No API key or the call failed: the automatic checks, with their rule-based fixes."""
    reason = f" ({result.error})" if result.error else ""
    st.info(f"Gemini isn't available{reason}, so this shows the automatic checks only.")
    _rule_list(findings, ctx, weekly, f"{key}_rules")
    if result.review.actions:
        sources = number_sources(ctx, findings)
        names = {p["name"] for p in ctx["picks"] + ctx["swap_pool"]} | set(PHASES)
        st.markdown(f"**Suggested fixes** &nbsp; {RULE}")
        for i, action in enumerate(result.review.actions):
            _action_card(action, i, result, ctx, weekly, sources, names, key, summary)


def brief_notes() -> list[str] | None:
    """The current plan's review as short lines for the PDF brief, or None if not reviewed.

    Only text that passed ai_review.verify is in the result, so nothing unchecked reaches
    the brief. Plain text: the PDF builder escapes it."""
    result: ReviewResult | None = st.session_state.get("ai_review_current")
    if result is None:
        return None
    review = result.review
    lines = [review.headline] if review.headline else []
    lines += [f"{i.title}: {i.explanation}" for i in review.issues[:3]]
    lines += [f"Suggested: {_action_text(a).replace('**', '')}. {a.reason}" for a in review.actions[:2]]
    return lines or None


def render_plan_review(
    shortlist: dict[str, dict],
    summary: pd.DataFrame,
    weekly: pd.DataFrame,
    pairs: pd.DataFrame,
    rescue: pd.DataFrame,
    prices: pd.DataFrame,
) -> None:
    st.markdown("### 🤖 Second opinion before you export")
    st.caption(
        "The AI never picks products: you do. Automatic checks (exact rules, no AI) look at your "
        "plan all the time. Gemini is the optional second step: it ranks what the checks found, adds "
        "what they miss, draws a chart for each point and proposes fixes. Nothing changes until you "
        "click Apply, every number it writes is checked against the data, and its notes go into "
        "the PDF brief."
    )

    if msg := st.session_state.pop("ai_applied_msg", None):
        st.success(msg)

    ctx = build_context(shortlist, summary, weekly, pairs, rescue, prices)
    findings = run_rules(ctx)

    api_key = _secret("GEMINI_API_KEY")
    model = _secret("GEMINI_MODEL", DEFAULT_MODEL)
    vertexai = bool(_secret("GEMINI_VERTEXAI", True))

    demo = st.query_params.get("demo") == "1"
    plant = demo and st.toggle("Demo: plant a wrong number in the AI's answer", key="ai_plant")

    key = _plan_hash(ctx, model, plant)
    cache: dict = st.session_state.setdefault("ai_review_cache", {})

    # The button sits below the checks, so read its click first and fetch before drawing.
    if st.session_state.get("ai_review_button") and key not in cache:
        with st.spinner("Gemini is reviewing your plan…"):
            cache[key] = review_plan(
                ctx, findings, api_key=api_key, model=model, vertexai=vertexai,
                catalog_names=set(summary["item_name"]), plant_mistake=plant,
            )

    # The export reads this, so the brief only carries a review of the plan as it is now.
    st.session_state["ai_review_current"] = cache.get(key)

    if key in cache:
        result = cache[key]
        if result.source == "gemini":
            _render_ai(result, key, ctx, findings, weekly, summary)
        else:
            _render_rules_only(result, key, ctx, findings, weekly, summary)
    else:
        if findings:
            st.markdown(f"#### {RULE} &nbsp; Automatic checks found {len(findings)} thing"
                        f"{'s' if len(findings) != 1 else ''} to look at")
            st.caption("Exact rules in code, always on, no AI. Open a line to see its data.")
            _rule_list(findings, ctx, weekly, f"rule_{key}")
        else:
            st.success("Automatic checks found no problems: the plan is balanced and every pick "
                       "has evidence behind it. Gemini can still look for anything they miss.")
        with st.container(border=True):
            st.markdown(
                f"{GEMINI} &nbsp; **Ask Gemini for a second opinion.** It will rank these checks, add "
                "anything they miss, draw a chart for each point and suggest fixes you can apply in "
                "one click. Every number it writes is checked first."
            )
            st.button(
                "🤖 Review my plan" if api_key else "🤖 Review my plan (no API key set: checks only)",
                type="primary",
                key="ai_review_button",
            )

    with st.expander("What the reviewer saw (facts passed to the AI)"):
        st.caption(
            "This is the complete set of facts the AI may use. Any number it writes must "
            "match one of these, or it is removed before you see it."
        )
        st.code(json.dumps(ctx, indent=2, ensure_ascii=False), language="json")

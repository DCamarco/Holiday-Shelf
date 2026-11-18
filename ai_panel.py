"""
ai_panel.py — the "Plan review" section of the Shortlist Builder.

Kept out of the page code so the UI stays a thin layer: the page passes in the
dataframes it already loads, and this module calls ai_context / ai_rules /
ai_review. Works with no API key (rule checks only).
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd
import streamlit as st

from ai_context import build_context
from ai_review import DEFAULT_MODEL, Action, ReviewResult, apply_action, review_plan
from ai_rules import Finding, run_rules

SEVERITY_STYLE = {
    "high": ("🔴", "High"),
    "medium": ("🟠", "Medium"),
    "low": ("🟡", "Low"),
}
ACTION_VERB = {"swap": "Swap", "move_phase": "Move", "remove": "Remove"}


def _secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:  # no secrets.toml at all
        return default


def _plan_hash(ctx: dict, model: str, planted: bool) -> str:
    raw = json.dumps(ctx, sort_keys=True, ensure_ascii=False) + model + str(planted)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _finding_card(f: Finding) -> None:
    icon, label = SEVERITY_STYLE.get(f.severity, ("⚪", f.severity))
    with st.container(border=True):
        st.markdown(f"{icon} **{f.title}**  \n{f.message}")
        st.caption(f"{label} priority · rule check `{f.id}` · numbers come straight from the data")


def _action_text(a: Action) -> str:
    if a.type == "swap":
        where = ", ".join(x for x in [a.phase, a.slot] if x)
        return f"**Swap** {a.product} → **{a.add}**" + (f" ({where})" if where else "")
    if a.type == "move_phase":
        return f"**Move** {a.product} → **{a.phase}**"
    return f"**Remove** {a.product}"


def _render_result(result: ReviewResult, key: str, summary: pd.DataFrame) -> None:
    review = result.review
    if result.source == "gemini":
        st.markdown(f"#### {review.headline}")
        st.caption("✓ Written by Gemini, then checked: every product name and number below matches the data.")
    else:
        st.markdown(f"#### {review.headline}")
        reason = f" ({result.error})" if result.error else ""
        st.caption(f"Showing rule checks only{reason}.")

    for issue in review.issues:
        icon, label = SEVERITY_STYLE.get(issue.severity, ("⚪", issue.severity))
        with st.container(border=True):
            st.markdown(f"{icon} **{issue.title}**  \n{issue.explanation}")
            badge = "✓ numbers verified" if result.source == "gemini" else "rule check"
            st.caption(f"{label} priority · {badge}")

    if review.actions:
        st.markdown("**Suggested fixes**")
        summary_rows = {r["item_name"]: r for r in summary.to_dict("records")}
        for i, action in enumerate(review.actions):
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                c1.markdown(f"{_action_text(action)}  \n{action.reason}")
                if c2.button("Apply", key=f"ai_apply_{key}_{i}"):
                    new, clear = apply_action(st.session_state.shortlist, action, summary_rows)
                    st.session_state.shortlist = new
                    for k in clear:
                        st.session_state.pop(k, None)
                    st.session_state["ai_applied_msg"] = (
                        f"Applied: {ACTION_VERB[action.type]} {action.product}. Review again to check the new plan."
                    )
                    st.rerun()

    if result.log:
        dropped = [x for x in result.log if not x["kept"]]
        title = f"Verification log ({len(dropped)} removed)" if dropped else "Verification log (nothing removed)"
        with st.expander(title, expanded=bool(dropped) and result.planted):
            for entry in result.log:
                mark = "✅ kept" if entry["kept"] else "❌ removed"
                st.markdown(f"{mark} · {entry['item']}  \n<small>{entry['reason']}</small>",
                            unsafe_allow_html=True)


def render_plan_review(
    shortlist: dict[str, dict],
    summary: pd.DataFrame,
    weekly: pd.DataFrame,
    pairs: pd.DataFrame,
    rescue: pd.DataFrame,
    prices: pd.DataFrame,
) -> None:
    st.markdown("### 🤖 Plan review")
    st.caption(
        "Checks your plan against the store's data: category balance, empty holiday "
        "phases, Season Playbook timing, weak evidence, downgrades, price anchors and "
        "bundle support. The AI review ranks these, explains them, and suggests fixes "
        "you can apply in one click."
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

    clicked = st.button(
        "🤖 Review my plan" if api_key else "🤖 Review my plan (rule checks; no API key set)",
        type="primary",
        key="ai_review_button",
    )
    if clicked and key not in cache:
        with st.spinner("Reviewing your plan…"):
            cache[key] = review_plan(
                ctx, findings, api_key=api_key, model=model, vertexai=vertexai,
                catalog_names=set(summary["item_name"]), plant_mistake=plant,
            )

    if key in cache:
        _render_result(cache[key], key, summary)
    elif not findings:
        st.success("No problems found. The plan is balanced and every pick has evidence behind it.")
    else:
        counts = pd.Series([f.severity for f in findings]).value_counts()
        bits = [f"{counts[s]} {SEVERITY_STYLE[s][1].lower()}" for s in ("high", "medium", "low") if s in counts]
        st.markdown(f"**{len(findings)} things to look at** ({', '.join(bits)} priority)")
        for f in findings:
            _finding_card(f)

    with st.expander("What the reviewer saw (facts passed to the AI)"):
        st.caption(
            "This is the complete set of facts the AI may use. Any number it writes must "
            "match one of these, or it is removed before you see it."
        )
        st.code(json.dumps(ctx, indent=2, ensure_ascii=False), language="json")

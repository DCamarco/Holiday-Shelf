"""
ai_context.py — the facts the AI Shortlist Reviewer is allowed to see.

Pure pandas, no Streamlit and no AI. `build_context()` turns the merchandiser's
shortlist plus the app's data tables into one JSON-friendly dict. The rule
checks (ai_rules.py), the Gemini prompt (ai_review.py) and the number verifier
all read this same dict, so every number is rounded exactly once, here.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

PHASES = [
    "Early Nov",
    "Black Friday / Cyber Monday",
    "Mid-Dec",
    "Post-Christmas",
]
SLOTS = ["Homepage", "Category page", "Promo banner", "Cart add-on"]

# Same price bands as the Shortlist Builder's price mix.
PRICE_BANDS = [
    (0, 10, "Under $10"),
    (10, 25, "$10–$24.99"),
    (25, 50, "$25–$49.99"),
    (50, math.inf, "$50+"),
]

# Season Playbook rule: a phase needs this many views before it can be recommended.
MIN_PHASE_VIEWS = 100
# A pick is "weak data" if its 95% range is wider than the rate itself.
MAX_RELATIVE_CI_WIDTH = 1.0
SWAP_POOL_SIZE = 20

_CATEGORY_GROUPS = {
    "Apparel": "Apparel",
    "Men's / Unisex": "Apparel",
    "Men's T-Shirts": "Apparel",
    "Women's": "Apparel",
    "Kids": "Apparel",
    "Drinkware": "Drinkware",
    "Mugs & Tumblers": "Drinkware",
    "Water Bottles": "Drinkware",
    "Bags": "Bags",
    "Backpacks": "Bags",
    "Stationery": "Stationery",
    "Notebooks": "Stationery",
    "Small Goods": "Small Goods",
    "Accessories": "Small Goods",
    "Uncategorized": "Uncategorized",
    "Uncategorized Items": "Uncategorized",
    "(not set)": "Uncategorized",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def category_group(raw: Any) -> str:
    """Collapse GA4's messy category paths into one merchandising group.

    "Home/Apparel/Men's / Unisex/" and "Apparel" both become "Apparel";
    "Lifestyle/Drinkware/" and "Mugs & Tumblers/" both become "Drinkware".
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return "Uncategorized"
    parts = [p.strip() for p in str(raw).strip("/").split("/") if p.strip()]
    if parts and parts[0] == "Home":
        parts = parts[1:]
    if not parts:
        return "Uncategorized"
    first = parts[0]
    if first == "Lifestyle" and len(parts) > 1:
        first = parts[1]
    if first == "Apparel" or first in _CATEGORY_GROUPS:
        return _CATEGORY_GROUPS.get(first, first)
    return first


def price_band(price: float | None) -> str:
    if price is None or (isinstance(price, float) and math.isnan(price)):
        return "Unknown"
    for low, high, label in PRICE_BANDS:
        if low <= price < high:
            return label
    return "Unknown"


def _num(value: Any) -> float | None:
    """Float or None (never NaN), so the context stays JSON-clean."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _pct(value: Any, digits: int = 2) -> float | None:
    """A 0–1 rate as a rounded percentage (0.01309 -> 1.31)."""
    f = _num(value)
    return None if f is None else round(f * 100, digits)


def _int(value: Any) -> int | None:
    f = _num(value)
    return None if f is None else int(round(f))


def _money(value: Any) -> float | None:
    f = _num(value)
    return None if f is None else round(f, 2)


def _clean_name(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return text or None


# ---------------------------------------------------------------------------
# Lookups built from the data tables
# ---------------------------------------------------------------------------


def recommended_phases(weekly: pd.DataFrame) -> dict[str, str]:
    """Each product's best phase, using the same rule as the Season Playbook.

    A phase qualifies with at least 100 views and purchases <= views. The best
    phase has the most purchase sessions per calendar week (revenue per week
    breaks ties). Products with no qualifying phase are left out.
    """
    if weekly is None or weekly.empty:
        return {}
    phase_weeks = weekly.groupby("phase")["week_start"].nunique()
    per = weekly.groupby(["item_name", "phase"], as_index=False).agg(
        views=("sessions_viewed", "sum"),
        purchases=("sessions_purchased", "sum"),
        revenue=("revenue", "sum"),
    )
    per["weeks"] = per["phase"].map(phase_weeks)
    per["ppw"] = per["purchases"] / per["weeks"]
    per["rpw"] = per["revenue"] / per["weeks"]
    ok = per[(per["views"] >= MIN_PHASE_VIEWS) & (per["purchases"] <= per["views"])]
    best = ok.sort_values(["ppw", "rpw"], ascending=False).drop_duplicates("item_name")
    return dict(zip(best["item_name"], best["phase"].astype(str)))


def _best_addons(pairs: pd.DataFrame) -> dict[str, dict]:
    """For each anchor, the add-on bought with it most often."""
    if pairs is None or pairs.empty:
        return {}
    top = pairs.sort_values(["orders_together", "lift"], ascending=False).drop_duplicates("anchor")
    return {
        r.anchor: {
            "addon": r.addon,
            "orders_together": _int(r.orders_together),
            "attach_rate_pct": _pct(r.addon_attach_rate, 1),
        }
        for r in top.itertuples()
    }


def pair_orders(pairs: pd.DataFrame, a: str, b: str) -> int:
    """Orders containing both products (either direction), 0 if never seen."""
    if pairs is None or pairs.empty or not a or not b:
        return 0
    hit = pairs[
        ((pairs["anchor"] == a) & (pairs["addon"] == b))
        | ((pairs["anchor"] == b) & (pairs["addon"] == a))
    ]
    return int(hit["orders_together"].max()) if not hit.empty else 0


# ---------------------------------------------------------------------------
# Per-product facts
# ---------------------------------------------------------------------------


def _product_facts(
    name: str,
    summary_row: dict | None,
    price: float | None,
    rec_phase: dict[str, str],
    addons: dict[str, dict],
    rescue_row: dict | None,
) -> dict:
    s = summary_row or {}
    rate = _num(s.get("view_to_buy_rate"))
    lo = _num(s.get("view_to_buy_ci_low"))
    hi = _num(s.get("view_to_buy_ci_high"))
    rel_width = None
    if rate and lo is not None and hi is not None and rate > 0:
        rel_width = (hi - lo) / rate

    label = s.get("label") if summary_row else None
    weak_reasons = []
    if summary_row is None:
        weak_reasons.append("no view data for this product")
    else:
        if label == "Not Enough Data":
            weak_reasons.append("labelled Not Enough Data")
        if bool(s.get("views_likely_insufficient")):
            weak_reasons.append("too few views")
        if bool(s.get("purchases_unmatched")):
            weak_reasons.append("purchases could not be matched to views")
        if lo is None:
            weak_reasons.append("no confidence range")
        elif rel_width is not None and rel_width > MAX_RELATIVE_CI_WIDTH:
            weak_reasons.append("confidence range is wider than the rate itself")

    facts = {
        "name": name,
        "category": category_group(s.get("item_category")),
        "price": _money(price),
        "price_band": price_band(_num(price)),
        "views": _int(s.get("sessions_viewed")),
        "purchases": _int(s.get("sessions_purchased")),
        "revenue": _int(s.get("revenue")),
        "view_to_buy_pct": _pct(rate),
        "ci_low_pct": _pct(lo),
        "ci_high_pct": _pct(hi),
        "label": label,
        "weak_data": bool(weak_reasons),
        "weak_reasons": weak_reasons,
        "recommended_phase": rec_phase.get(name),
        "best_addon": addons.get(name),
        "cart_abandon_pct": None,
    }
    if rescue_row is not None:
        ctb = _num(rescue_row.get("cart_to_buy_rate"))
        facts["cart_abandon_pct"] = None if ctb is None else round((1 - ctb) * 100, 1)
    return facts


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_context(
    shortlist: dict[str, dict],
    summary: pd.DataFrame,
    weekly: pd.DataFrame | None = None,
    pairs: pd.DataFrame | None = None,
    rescue: pd.DataFrame | None = None,
    prices: pd.DataFrame | None = None,
    tags: pd.DataFrame | None = None,
) -> dict:
    """Everything the reviewer may know about the current plan.

    shortlist: st.session_state.shortlist (key -> row dict). Reads item_name,
               holiday_phase, placement_slot / slot, replacement_product,
               paired_with.
    prices:    item_name + typical_price (load_product_prices() in app.py).
    tags:      optional AI product tags (item_name + tag columns), step 4.
    """
    summary_by_name = summary.set_index("item_name").to_dict("index") if summary is not None else {}
    price_by_name: dict[str, float] = {}
    if prices is not None and not prices.empty:
        price_by_name = dict(zip(prices["item_name"], prices["typical_price"]))
    rescue_by_name = (
        rescue.set_index("item_name").to_dict("index") if rescue is not None and not rescue.empty else {}
    )
    tags_by_name = tags.set_index("item_name").to_dict("index") if tags is not None and not tags.empty else {}
    rec_phase = recommended_phases(weekly)
    addons = _best_addons(pairs)

    def facts_for(name: str) -> dict:
        row = summary_by_name.get(name)
        price = price_by_name.get(name)
        if price is None and name in rescue_by_name:
            price = rescue_by_name[name].get("typical_price")
        f = _product_facts(name, row, price, rec_phase, addons, rescue_by_name.get(name))
        if name in tags_by_name:
            f["tags"] = {k: v for k, v in tags_by_name[name].items() if _clean_name(v) is not None}
        return f

    # ---- picks ----
    picks = []
    for key, row in shortlist.items():
        name = _clean_name(row.get("item_name")) or key
        f = facts_for(name)
        slot = row.get("placement_slot")
        if slot not in SLOTS:
            slot = "Cart add-on" if str(row.get("slot", "")).lower() == "cart add-on" else slot
        replaces = _clean_name(row.get("replacement_product"))
        paired_with = _clean_name(row.get("paired_with"))
        f.update(
            {
                "key": key,
                "phase": row.get("holiday_phase") if row.get("holiday_phase") in PHASES else None,
                "slot": slot,
                "replaces": replaces,
                "replaces_ci_low_pct": (
                    _pct(summary_by_name[replaces].get("view_to_buy_ci_low"))
                    if replaces in summary_by_name
                    else None
                ),
                "paired_with": paired_with,
                "pair_orders": pair_orders(pairs, name, paired_with) if paired_with else None,
            }
        )
        picks.append(f)

    # ---- for cart add-ons: the pick it was bought with most often ----
    for f in picks:
        if f["slot"] != "Cart add-on":
            continue
        best_name, best_orders = None, 0
        for other in picks:
            if other["name"] == f["name"]:
                continue
            together = pair_orders(pairs, f["name"], other["name"])
            if together > best_orders:
                best_name, best_orders = other["name"], together
        f["plan_pair_with"] = best_name
        f["plan_pair_orders"] = best_orders

    # ---- plan-level mix ----
    n = len(picks)

    def mix(field: str) -> list[dict]:
        counts = pd.Series([p[field] or "Unknown" for p in picks]).value_counts()
        return [
            {"name": k, "count": int(v), "share_pct": round(v / n * 100) if n else 0}
            for k, v in counts.items()
        ]

    phase_counts = {ph: sum(1 for p in picks if p["phase"] == ph) for ph in PHASES}
    plan = {
        "count": n,
        "target_min": 10,
        "target_max": 15,
        "category_mix": mix("category") if n else [],
        "price_mix": mix("price_band") if n else [],
        "phase_counts": phase_counts,
        "empty_phases": [ph for ph, c in phase_counts.items() if c == 0],
        "weak_data_count": sum(1 for p in picks if p["weak_data"]),
    }

    # ---- swap pool: strongest products not already in the plan ----
    chosen = {p["name"] for p in picks} | {p["replaces"] for p in picks if p["replaces"]}
    pool_df = summary[
        ~summary["item_name"].isin(chosen)
        & summary["label"].isin(["Star", "Hidden Gem"])
        & ~summary["views_likely_insufficient"].fillna(True).astype(bool)
        & ~summary["purchases_unmatched"].fillna(True).astype(bool)
    ].sort_values("view_to_buy_ci_low", ascending=False)
    swap_pool = []
    for name in pool_df["item_name"]:
        f = facts_for(name)
        if f["weak_data"]:
            continue
        swap_pool.append(f)
        if len(swap_pool) >= SWAP_POOL_SIZE:
            break

    return {
        "phases": PHASES,
        "slots": SLOTS,
        "plan": plan,
        "picks": picks,
        "swap_pool": swap_pool,
        "notes": [
            "Rates are view-to-purchase sessions from Nov 2020–Jan 2021 (GA4 sample).",
            "ci_low_pct / ci_high_pct are the 95% Wilson range for that rate.",
            "Bundle and add-on numbers are co-purchase associations, not causes.",
        ],
    }

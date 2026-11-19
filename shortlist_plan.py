"""
shortlist_plan.py — the logic behind the Shortlist Builder's plan board, table and
bulk actions.

Everything here is a plain function on the shortlist dict
(``st.session_state.shortlist``: key -> row dict) so it can be tested without
Streamlit. The page in views/shortlist_builder.py only draws widgets and calls
these functions.

Row fields written here (other pages and the AI reviewer read them, so keep the
names): ``holiday_phase``, ``placement_slot``, ``slot``, ``replacement_product``.
"""

from __future__ import annotations

import copy
import html
import math

import pandas as pd

from ai_context import PHASES, SLOTS, category_group

DEFAULT_PHASE = "Black Friday / Cyber Monday"
NO_REPLACEMENT = "No replacement"
WEAK_LABELS = ["Window-Shopper", "Low Priority"]  # products a pick may replace
FILL_LABELS = ["Star", "Hidden Gem"]  # used by Fill / Quick start, in this order

PHASE_ALIASES = {"Black Friday": "Black Friday / Cyber Monday", "Mid-December": "Mid-Dec"}
SLOT_ALIASES = {
    "homepage": "Homepage",
    "category page": "Category page",
    "banner": "Promo banner",
    "promo banner": "Promo banner",
    "cart add-on": "Cart add-on",
}
SLOT_ICONS = {"Homepage": "🏠", "Category page": "🗂️", "Promo banner": "📣", "Cart add-on": "🛒"}


# ---------------------------------------------------------------------------
# Row clean-up
# ---------------------------------------------------------------------------


def _clean(value):
    """None for NaN/empty so pandas missing values don't leak into the plan."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def normalize_row(row: dict, recommended: dict[str, str] | None = None) -> dict:
    """Give a row a valid phase and slot, keeping anything the user already chose.

    New rows start in their Season Playbook phase when there is one, otherwise
    Black Friday / Cyber Monday (the page's original default).
    """
    row = dict(row)
    phase = PHASE_ALIASES.get(row.get("holiday_phase"), row.get("holiday_phase"))
    if phase not in PHASES:
        phase = (recommended or {}).get(row.get("item_name"), DEFAULT_PHASE)
    row["holiday_phase"] = phase

    slot = row.get("placement_slot")
    if slot not in SLOTS:
        slot = SLOT_ALIASES.get(str(row.get("slot") or "").strip().lower(), "Homepage")
    row["placement_slot"] = slot
    row["slot"] = slot
    # A pick from the Opportunity Finder arrives with the weaker product it should
    # replace ("replaces"); use it until the user picks something else (even "none").
    if "replacement_product" not in row and _clean(row.get("replaces")):
        row["replacement_product"] = row["replaces"]
    if slot == "Cart add-on":
        row["replacement_product"] = None
    return row


def normalize_shortlist(shortlist: dict, recommended: dict[str, str] | None = None) -> dict:
    return {k: normalize_row(r, recommended) for k, r in shortlist.items()}


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------


def weak_data_mask(df: pd.DataFrame) -> pd.Series:
    """Same rule as the page's 'Picks with weak data' count: flagged by the
    pipeline, missing views or 95% range, or labelled Not Enough Data."""
    weak = pd.Series(False, index=df.index)
    for flag in ["views_likely_insufficient", "purchases_unmatched"]:
        weak |= df[flag].fillna(True).astype(bool) if flag in df.columns else True
    for metric in ["sessions_viewed", "view_to_buy_ci_low"]:
        weak |= pd.to_numeric(df[metric], errors="coerce").isna() if metric in df.columns else True
    if "label" in df.columns:
        weak |= df["label"].eq("Not Enough Data").fillna(False)
    return weak


def replacement_candidates(summary: pd.DataFrame, category, name: str) -> list[str]:
    """Weaker products in the same category, weakest conversion first."""
    c = summary[
        (summary["item_category"] == category)
        & summary["label"].isin(WEAK_LABELS)
        & (summary["item_name"] != name)
    ].sort_values("view_to_buy_rate", ascending=True, na_position="last")
    return c["item_name"].dropna().tolist()


def replacement_options(shortlist: dict, summary: pd.DataFrame) -> list[str]:
    """Every replacement any pick could use. A table dropdown has one option list
    for all rows, so the page checks the category per row (see bad_replacements)."""
    names: list[str] = []
    for row in shortlist.values():
        names += replacement_candidates(summary, row.get("item_category"), row.get("item_name"))
        for extra in (row.get("replacement_product"), row.get("replaces")):
            if _clean(extra):
                names.append(extra)
    return [NO_REPLACEMENT] + sorted(set(names))


# ---------------------------------------------------------------------------
# The editable plan table
# ---------------------------------------------------------------------------

# Editable columns (Phase, Slot, Replaces) come right after the product so they
# are on screen without scrolling; the evidence columns follow.
TABLE_COLUMNS = [
    "key", "Select", "Product", "Phase", "Slot", "Replaces", "Playbook phase",
    "Label", "Conversion", "Weak data", "Price", "Category", "Test visits/day",
]


def plan_table(
    shortlist: dict,
    summary: pd.DataFrame,
    prices: pd.DataFrame,
    recommended: dict[str, str],
    visits_per_day,
) -> pd.DataFrame:
    """One row per pick, in the order the table shows. ``visits_per_day`` maps a
    conversion rate to daily test traffic per variant (or None)."""
    rows = []
    price_map = dict(zip(prices["item_name"], prices["typical_price"])) if prices is not None else {}
    summary_by_name = summary.set_index("item_name") if summary is not None else None
    for key, r in shortlist.items():
        name = r.get("item_name", key)
        # Cart add-ons are added from the Bundles page without summary columns.
        facts = dict(r)
        if summary_by_name is not None and name in summary_by_name.index and "label" not in r:
            facts.update(summary_by_name.loc[name].to_dict())
        rate = pd.to_numeric(pd.Series([facts.get("view_to_buy_rate")]), errors="coerce").iloc[0]
        rows.append({
            "key": key,
            "Select": False,
            "Product": name,
            "Label": _clean(facts.get("label")) or "—",
            "Category": category_group(facts.get("item_category")),
            "Price": _clean(price_map.get(name)),
            "Conversion": None if pd.isna(rate) else float(rate),
            "Playbook phase": recommended.get(name, "—"),
            "Phase": r.get("holiday_phase"),
            "Slot": r.get("placement_slot"),
            "Replaces": (
                "— (add-on)" if r.get("placement_slot") == "Cart add-on"
                else _clean(r.get("replacement_product")) or NO_REPLACEMENT
            ),
            "Test visits/day": visits_per_day(None if pd.isna(rate) else float(rate)),
            "_facts": facts,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=TABLE_COLUMNS)
    df["Weak data"] = weak_data_mask(pd.DataFrame(list(df.pop("_facts")), index=df.index))
    return df[TABLE_COLUMNS]


def apply_table_edits(shortlist: dict, edited: pd.DataFrame) -> tuple[dict, bool]:
    """Write Phase / Slot / Replaces from the edited table back into the shortlist.
    Returns (new shortlist, whether anything changed). The input is not modified."""
    new = copy.deepcopy(shortlist)
    changed = False
    for rec in edited.to_dict("records"):
        row = new.get(rec["key"])
        if row is None:
            continue
        phase = rec.get("Phase") if rec.get("Phase") in PHASES else row["holiday_phase"]
        slot = rec.get("Slot") if rec.get("Slot") in SLOTS else row["placement_slot"]
        repl = rec.get("Replaces")
        repl = None if slot == "Cart add-on" or repl in (None, NO_REPLACEMENT, "— (add-on)") else repl
        before = (row.get("holiday_phase"), row.get("placement_slot"), _clean(row.get("replacement_product")))
        if before != (phase, slot, repl):
            changed = True
        row.update(holiday_phase=phase, placement_slot=slot, slot=slot, replacement_product=repl)
    return new, changed


def bad_replacements(shortlist: dict, summary: pd.DataFrame) -> list[tuple[str, str]]:
    """(pick, replacement) pairs where the replacement isn't a weaker product in
    the pick's own category."""
    out = []
    for r in shortlist.values():
        repl = _clean(r.get("replacement_product"))
        ok = replacement_candidates(summary, r.get("item_category"), r.get("item_name"))
        # The Opportunity Finder's own suggestion (``replaces``) is always fine.
        if repl and repl not in ok and repl != _clean(r.get("replaces")):
            out.append((r.get("item_name"), repl))
    return out


# ---------------------------------------------------------------------------
# Bulk actions (all return a new shortlist)
# ---------------------------------------------------------------------------


def set_for(shortlist: dict, keys, phase: str | None = None, slot: str | None = None) -> dict:
    new = copy.deepcopy(shortlist)
    for k in keys:
        if k not in new:
            continue
        if phase in PHASES:
            new[k]["holiday_phase"] = phase
        if slot in SLOTS:
            new[k]["placement_slot"] = slot
            new[k]["slot"] = slot
            if slot == "Cart add-on":
                new[k]["replacement_product"] = None
    return new


def remove_keys(shortlist: dict, keys) -> dict:
    drop = set(keys)
    return {k: copy.deepcopy(v) for k, v in shortlist.items() if k not in drop}


def use_playbook_phases(shortlist: dict, recommended: dict[str, str]) -> tuple[dict, int]:
    """Move every pick to its Season Playbook phase. Returns (new, how many moved)."""
    new = copy.deepcopy(shortlist)
    moved = 0
    for row in new.values():
        best = recommended.get(row.get("item_name"))
        if best in PHASES and best != row.get("holiday_phase"):
            row["holiday_phase"] = best
            moved += 1
    return new, moved


def fill_empty_phases(
    shortlist: dict,
    summary: pd.DataFrame,
    recommended: dict[str, str],
    per_phase: int = 1,
    min_total: int = 0,
) -> tuple[dict, list[str]]:
    """Add the strongest products whose Playbook phase is currently empty, then (if
    min_total is set) keep adding to the thinnest phase until the plan has min_total picks.

    Stars first, then Hidden Gems when a phase runs out of Stars (Early Nov and
    Post-Christmas have few). "Strongest" = highest lower end of the 95% range,
    so a product with little data can't win on a lucky rate. Weak-data products
    are skipped. Returns (new shortlist, names added).
    """
    new = copy.deepcopy(shortlist)
    used = {r.get("item_name") for r in new.values()}
    filled = {r.get("holiday_phase") for r in new.values()}
    pool = summary[summary["label"].isin(FILL_LABELS) & ~weak_data_mask(summary)].copy()
    pool["best_phase"] = pool["item_name"].map(recommended)
    pool["_rank"] = pool["label"].map({lab: i for i, lab in enumerate(FILL_LABELS)})
    pool = pool.sort_values(["_rank", "view_to_buy_ci_low"], ascending=[True, False]).drop(columns="_rank")
    added: list[str] = []
    for phase in PHASES:
        if phase in filled:
            continue
        picks = pool[(pool["best_phase"] == phase) & ~pool["item_name"].isin(used)].head(per_phase)
        for i, rec in enumerate(picks.to_dict("records")):
            # Strongest pick of the phase gets the homepage; the rest go to category pages.
            slot = "Homepage" if i == 0 else "Category page"
            row = {k: _clean(v) for k, v in rec.items() if k != "best_phase"}
            row.update(holiday_phase=phase, placement_slot=slot, slot=slot,
                       replacement_product=None)
            new[rec["item_name"]] = row
            used.add(rec["item_name"])
            added.append(rec["item_name"])

    # Top up to min_total: one pick at a time, into the phase with the fewest picks
    # that still has an unused candidate whose Playbook phase it is.
    counts = {p: 0 for p in PHASES}
    for r in new.values():
        if r.get("holiday_phase") in counts:
            counts[r["holiday_phase"]] += 1
    while len(new) < min_total:
        rest = pool[~pool["item_name"].isin(used)]
        choice = None
        for phase in sorted(PHASES, key=lambda p: counts[p]):  # stable: ties keep season order
            cand = rest[rest["best_phase"] == phase]
            if not cand.empty:
                choice = (phase, cand.iloc[0].to_dict())
                break
        if choice is None:
            break
        phase, rec = choice
        slot = "Category page" if counts[phase] else "Homepage"
        row = {k: _clean(v) for k, v in rec.items() if k != "best_phase"}
        row.update(holiday_phase=phase, placement_slot=slot, slot=slot, replacement_product=None)
        new[rec["item_name"]] = row
        used.add(rec["item_name"])
        added.append(rec["item_name"])
        counts[phase] += 1
    return new, added


# ---------------------------------------------------------------------------
# Plan stats and the phase board
# ---------------------------------------------------------------------------


def plan_stats(shortlist: dict, table: pd.DataFrame) -> dict:
    n = len(shortlist)
    phases = [r.get("holiday_phase") for r in shortlist.values()]
    cats = table["Category"].value_counts() if n else pd.Series(dtype=int)
    return {
        "count": n,
        "phases_covered": len({p for p in phases if p in PHASES}),
        "top_category": cats.index[0] if n else None,
        "top_category_share": round(100 * cats.iloc[0] / n) if n else 0,
        "weak": int(table["Weak data"].sum()) if n else 0,
        "off_playbook": int(
            ((table["Playbook phase"] != "—") & (table["Playbook phase"] != table["Phase"])).sum()
        ) if n else 0,
    }


def board_html(table: pd.DataFrame, label_colors: dict[str, str]) -> str:
    """Four phase columns; each pick is a chip showing its slot and label colour."""
    cols = []
    for phase in PHASES:
        sub = table[table["Phase"] == phase]
        chips = []
        for slot in SLOTS:
            for r in sub[sub["Slot"] == slot].to_dict("records"):
                color = label_colors.get(r["Label"], "#94A3B8")
                warn = " ⚠️" if r["Weak data"] else ""
                best = r["Playbook phase"]
                tip = html.escape(f"{r['Product']} · {r['Label']} · {slot}"
                                  + (f" · Playbook: {best}" if best != "—" else ""))
                chips.append(
                    f'<div class="pb-chip" title="{tip}" style="border-left-color:{color}">'
                    f'<span class="pb-slot">{SLOT_ICONS[slot]}</span>'
                    f'<span class="pb-name">{html.escape(r["Product"])}{warn}</span></div>'
                )
        body = "".join(chips) or '<div class="pb-empty">Nothing planned</div>'
        n = len(sub)
        cols.append(
            f'<div class="pb-col{" pb-col-empty" if not n else ""}">'
            f'<div class="pb-head"><div class="pb-phase">{html.escape(phase)}</div>'
            f'<div class="pb-count">{n}</div></div>{body}</div>'
        )
    legend = " ".join(f"{SLOT_ICONS[s]} {s}" for s in SLOTS)
    return f"""
<style>
.pb-board {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
@media (max-width: 900px) {{ .pb-board {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
.pb-col {{ background:var(--hs-card,#fff); border:1px solid var(--hs-border,#E4E7EC); border-radius:16px;
          padding:12px; min-height:150px; box-shadow:var(--hs-shadow,none); }}
.pb-col-empty {{ border-style:dashed; box-shadow:none; }}
.pb-head {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px; }}
.pb-phase {{ font-weight:800; font-size:.95rem; color:var(--hs-text,#1B2133); }}
.pb-count {{ background:var(--hs-soft,#EEF0FF); color:var(--hs-primary,#4F46E5); font-weight:800;
            border-radius:999px; min-width:28px; text-align:center; padding:2px 8px; font-size:.85rem; }}
.pb-chip {{ display:flex; gap:6px; align-items:center; border:1px solid var(--hs-border,#E4E7EC);
           border-left:4px solid; border-radius:10px; padding:5px 8px; margin-bottom:6px;
           font-size:.82rem; color:var(--hs-text,#1B2133); background:var(--hs-bg,transparent); }}
.pb-name {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.pb-empty {{ color:var(--hs-muted,#667085); font-size:.85rem; padding:18px 4px; text-align:center; }}
.pb-legend {{ color:var(--hs-muted,#667085); font-size:.78rem; margin-top:8px; }}
</style>
<div class="pb-board">{"".join(cols)}</div>
<div class="pb-legend">{legend} · left edge colour = label · ⚠️ weak data</div>
"""

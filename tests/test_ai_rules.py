"""Tests for ai_context.py and ai_rules.py. No network, no API key."""

import json
import unittest

import pandas as pd

from ai_context import build_context, category_group, recommended_phases
from ai_rules import run_rules

PHASES = ["Early Nov", "Black Friday / Cyber Monday", "Mid-Dec", "Post-Christmas"]


def summary_row(name, category, views=1000, purchases=50, label="Star", **extra):
    rate = purchases / views
    row = {
        "item_name": name,
        "item_category": category,
        "sessions_viewed": views,
        "sessions_purchased": purchases,
        "revenue": purchases * 20,
        "view_to_buy_rate": rate,
        "view_to_buy_ci_low": rate * 0.8,
        "view_to_buy_ci_high": rate * 1.2,
        "views_likely_insufficient": False,
        "purchases_unmatched": False,
        "label": label,
    }
    row.update(extra)
    return row


def make_summary():
    rows = [summary_row(f"Mug {i}", "Lifestyle/Drinkware/") for i in range(4)]
    rows += [summary_row(f"Tee {i}", "Home/Apparel/Men's / Unisex/") for i in range(4)]
    rows += [summary_row(f"Pen {i}", "Home/Stationery/Writing/") for i in range(4)]
    rows += [summary_row(f"Bag {i}", "Lifestyle/Bags/") for i in range(4)]
    rows.append(summary_row("Thin Sticker", "Home/Stationery/Stickers/", views=40, purchases=2,
                            label="Not Enough Data"))
    rows.append(summary_row("Weak Old Hat", "Home/Apparel/Hats/", views=2000, purchases=10,
                            label="Low Priority"))
    rows.append(summary_row("Strong Old Hat", "Home/Apparel/Hats/", views=1000, purchases=300,
                            label="Window-Shopper"))
    rows.append(summary_row("Pool Star", "Lifestyle/Small Goods/", views=1000, purchases=200))
    return pd.DataFrame(rows)


def make_prices(summary):
    prices = {name: 15.0 for name in summary["item_name"]}
    prices.update({"Tee 0": 55.0, "Pen 0": 3.0})
    return pd.DataFrame({"item_name": list(prices), "typical_price": list(prices.values())})


def make_weekly():
    # "Mug 0" sells best in Mid-Dec; every other row is too small to qualify.
    rows = []
    for phase, weeks, purchases in [("Black Friday / Cyber Monday", ["2020-11-23"], 2),
                                    ("Mid-Dec", ["2020-12-07", "2020-12-14"], 40)]:
        for week in weeks:
            rows.append({"item_name": "Mug 0", "week_start": week, "phase": phase,
                         "sessions_viewed": 300, "sessions_purchased": purchases, "revenue": purchases * 10})
    rows.append({"item_name": "Tee 1", "week_start": "2020-11-02", "phase": "Early Nov",
                 "sessions_viewed": 5, "sessions_purchased": 1, "revenue": 10})
    return pd.DataFrame(rows)


def make_pairs():
    return pd.DataFrame([
        {"anchor": "Pen 1", "addon": "Pen 0", "orders_together": 12, "lift": 5.0, "addon_attach_rate": 0.3},
        {"anchor": "Bag 0", "addon": "Mug 1", "orders_together": 1, "lift": 2.0, "addon_attach_rate": 0.1},
    ])


def pick(name, phase, slot="Homepage", **extra):
    row = {"item_name": name, "holiday_phase": phase, "placement_slot": slot}
    row.update(extra)
    return row


def clean_plan():
    """12 picks, every phase covered, mixed categories, no rule should fire."""
    plan = [
        pick("Mug 1", "Early Nov"), pick("Tee 0", "Black Friday / Cyber Monday"),
        pick("Pen 0", "Mid-Dec"), pick("Bag 0", "Post-Christmas"),
        pick("Mug 2", "Early Nov"), pick("Tee 1", "Black Friday / Cyber Monday"),
        pick("Pen 1", "Mid-Dec"), pick("Bag 1", "Post-Christmas"),
        pick("Mug 3", "Early Nov"), pick("Tee 2", "Black Friday / Cyber Monday"),
        pick("Pen 2", "Mid-Dec"), pick("Bag 2", "Post-Christmas"),
    ]
    return {p["item_name"]: p for p in plan}


class AIRulesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.summary = make_summary()
        cls.prices = make_prices(cls.summary)
        cls.weekly = make_weekly()
        cls.pairs = make_pairs()

    def ctx(self, shortlist):
        return build_context(shortlist, self.summary, self.weekly, self.pairs,
                             rescue=None, prices=self.prices)

    def ids(self, shortlist):
        return [f.id for f in run_rules(self.ctx(shortlist))]

    # ---- context ----

    def test_category_group_merges_messy_paths(self):
        self.assertEqual(category_group("Home/Apparel/Men's / Unisex/"), "Apparel")
        self.assertEqual(category_group("Apparel"), "Apparel")
        self.assertEqual(category_group("Lifestyle/Drinkware/"), "Drinkware")
        self.assertEqual(category_group("Mugs & Tumblers/"), "Drinkware")
        self.assertEqual(category_group(None), "Uncategorized")

    def test_recommended_phase_matches_playbook_rule(self):
        rec = recommended_phases(self.weekly)
        self.assertEqual(rec["Mug 0"], "Mid-Dec")
        self.assertNotIn("Tee 1", rec)  # under 100 views: no recommendation

    def test_context_is_json_serialisable_and_excludes_picks_from_pool(self):
        ctx = self.ctx(clean_plan())
        json.dumps(ctx)  # no NaN, no callables
        pool = {p["name"] for p in ctx["swap_pool"]}
        self.assertFalse(pool & set(clean_plan()))
        self.assertIn("Pool Star", pool)
        self.assertNotIn("Thin Sticker", pool)

    def test_empty_shortlist_has_no_findings(self):
        self.assertEqual(run_rules(self.ctx({})), [])

    # ---- each rule stays silent on a clean plan ----

    def test_clean_plan_has_no_findings(self):
        self.assertEqual(self.ids(clean_plan()), [])

    # ---- each rule fires on a plan built to break it ----

    def test_plan_size(self):
        plan = dict(list(clean_plan().items())[:8])
        self.assertIn("plan_size", self.ids(plan))

    def test_category_overload(self):
        plan = clean_plan()
        plan["Mug 0"] = pick("Mug 0", "Mid-Dec")
        for name in ["Pen 1", "Pen 2", "Bag 1", "Bag 2"]:
            plan.pop(name)
        findings = run_rules(self.ctx(plan))  # 4 of 9 picks are Drinkware = 44%
        overload = [f for f in findings if f.id == "category_overload"]
        self.assertEqual(len(overload), 1)
        self.assertEqual(overload[0].numbers["share_pct"], 44)
        self.assertEqual(findings[0].severity, "high")

    def test_empty_phase(self):
        plan = {k: {**v, "holiday_phase": "Early Nov" if v["holiday_phase"] == "Post-Christmas"
                    else v["holiday_phase"]} for k, v in clean_plan().items()}
        findings = [f for f in run_rules(self.ctx(plan)) if f.id == "empty_phase"]
        self.assertEqual([f.numbers["phases"] for f in findings], [["Post-Christmas"]])

    def test_phase_mismatch(self):
        plan = clean_plan()
        plan["Mug 0"] = pick("Mug 0", "Black Friday / Cyber Monday")
        plan.pop("Mug 3")
        found = [f for f in run_rules(self.ctx(plan)) if f.id == "phase_mismatch"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].numbers["recommended"], "Mid-Dec")

    def test_weak_data(self):
        plan = clean_plan()
        plan.pop("Pen 2")
        plan["Thin Sticker"] = pick("Thin Sticker", "Mid-Dec")
        self.assertIn("weak_data", self.ids(plan))

    def test_downgrade(self):
        plan = clean_plan()
        plan["Tee 2"]["replacement_product"] = "Strong Old Hat"
        found = [f for f in run_rules(self.ctx(plan)) if f.id == "downgrade"]
        self.assertEqual(found[0].products, ["Tee 2", "Strong Old Hat"])
        # Replacing a weaker product is fine.
        plan["Tee 2"]["replacement_product"] = "Weak Old Hat"
        self.assertNotIn("downgrade", self.ids(plan))

    def test_no_black_friday_anchor(self):
        plan = clean_plan()
        plan["Tee 0"]["holiday_phase"] = "Early Nov"
        self.assertIn("no_anchor", self.ids(plan))

    def test_no_mid_dec_stocking_stuffer(self):
        prices = self.prices.copy()
        prices.loc[prices["item_name"] != "Tee 0", "typical_price"] = 25.0
        ctx = build_context(clean_plan(), self.summary, self.weekly, self.pairs, prices=prices)
        self.assertIn("no_stuffer", [f.id for f in run_rules(ctx)])

    def test_addon_without_evidence(self):
        plan = clean_plan()
        plan["Mug 1"]["placement_slot"] = "Cart add-on"  # only 1 order with Bag 0
        self.assertIn("addon_no_evidence", self.ids(plan))

    def test_addon_with_evidence_passes(self):
        plan = clean_plan()
        plan["Pen 0"]["placement_slot"] = "Cart add-on"  # 12 orders with Pen 1
        self.assertNotIn("addon_no_evidence", self.ids(plan))

    def test_bundle_page_addon_uses_paired_with(self):
        plan = clean_plan()
        plan["Pen 0 (add-on)"] = {"item_name": "Pen 0", "slot": "cart add-on",
                                  "paired_with": "Pen 1", "holiday_phase": "Mid-Dec"}
        plan.pop("Pen 0")
        ctx = self.ctx(plan)
        addon = next(p for p in ctx["picks"] if p["key"] == "Pen 0 (add-on)")
        self.assertEqual(addon["slot"], "Cart add-on")
        self.assertEqual(addon["pair_orders"], 12)
        self.assertNotIn("addon_no_evidence", [f.id for f in run_rules(ctx)])


if __name__ == "__main__":
    unittest.main()

"""Tests for shortlist_plan.py: the Builder's table edits, bulk actions and stats.
Plain functions on the shortlist dict, so no Streamlit app is needed."""

import unittest

import pandas as pd

from shortlist_plan import (
    NO_REPLACEMENT,
    apply_table_edits,
    bad_replacements,
    board_html,
    fill_empty_phases,
    normalize_row,
    normalize_shortlist,
    plan_stats,
    plan_table,
    remove_keys,
    replacement_options,
    set_for,
    use_playbook_phases,
)

CAT = "Home/Apparel/Men's / Unisex/"
MUGS = "Mugs & Tumblers/"


def product(name, label="Star", cat=CAT, rate=0.05, low=0.04, views=2000, weak=False):
    return {
        "item_name": name, "item_category": cat, "label": label,
        "sessions_viewed": views, "sessions_purchased": int(views * rate),
        "view_to_buy_rate": rate, "view_to_buy_ci_low": low, "view_to_buy_ci_high": rate + 0.01,
        "views_likely_insufficient": weak, "purchases_unmatched": False, "revenue": 1000.0,
    }


SUMMARY = pd.DataFrame([
    product("Hoodie"),
    product("Tee", rate=0.04, low=0.035),
    product("Mug", cat=MUGS),
    product("Star Early", low=0.06),
    product("Star Early 2", low=0.05),
    product("Star Post", low=0.07),
    product("Weak Star", low=0.09, weak=True),
    product("Gem Early", label="Hidden Gem", low=0.08, views=300),
    product("Slow Shirt", label="Window-Shopper", rate=0.005, low=0.003),
    product("Slower Shirt", label="Low Priority", rate=0.002, low=0.001),
    product("Slow Mug", label="Window-Shopper", cat=MUGS, rate=0.004, low=0.002),
])
PRICES = pd.DataFrame({"item_name": ["Hoodie", "Tee"], "typical_price": [55.0, 18.0]})
RECOMMENDED = {
    "Hoodie": "Mid-Dec", "Tee": "Black Friday / Cyber Monday", "Mug": "Mid-Dec",
    "Star Early": "Early Nov", "Star Early 2": "Early Nov", "Star Post": "Post-Christmas",
    "Weak Star": "Post-Christmas", "Gem Early": "Early Nov",
}


def row(name, **extra):
    r = SUMMARY.set_index("item_name").loc[name].to_dict()
    r["item_name"] = name
    r.update(extra)
    return r


def plan():
    return normalize_shortlist({
        "Hoodie": row("Hoodie", holiday_phase="Black Friday / Cyber Monday", placement_slot="Homepage"),
        "Tee": row("Tee"),
        "Mug": row("Mug", holiday_phase="Mid-Dec", placement_slot="Promo banner"),
    }, RECOMMENDED)


def table(shortlist):
    return plan_table(shortlist, SUMMARY, PRICES, RECOMMENDED, lambda rate: None if rate is None else 100)


class NormalizeTest(unittest.TestCase):

    def test_new_pick_starts_in_playbook_phase(self):
        self.assertEqual(normalize_row(row("Hoodie"), RECOMMENDED)["holiday_phase"], "Mid-Dec")

    def test_unknown_pick_defaults_to_black_friday(self):
        self.assertEqual(normalize_row({"item_name": "X"}, RECOMMENDED)["holiday_phase"],
                         "Black Friday / Cyber Monday")

    def test_existing_choice_and_aliases_are_kept(self):
        r = normalize_row({"item_name": "Hoodie", "holiday_phase": "Mid-December", "slot": "banner"},
                          RECOMMENDED)
        self.assertEqual((r["holiday_phase"], r["placement_slot"]), ("Mid-Dec", "Promo banner"))

    def test_opportunity_finder_swap_carries_into_the_plan(self):
        r = normalize_row({"item_name": "Gem Early", "replaces": "Slow Shirt"}, RECOMMENDED)
        self.assertEqual(r["replacement_product"], "Slow Shirt")
        kept = normalize_row({"item_name": "Gem Early", "replaces": "Slow Shirt",
                              "replacement_product": None}, RECOMMENDED)
        self.assertIsNone(kept["replacement_product"])  # the user chose "No replacement"

    def test_bundle_addon_slot(self):
        r = normalize_row({"item_name": "Mug", "slot": "cart add-on", "replacement_product": "x"})
        self.assertEqual(r["placement_slot"], "Cart add-on")
        self.assertIsNone(r["replacement_product"])


class TableTest(unittest.TestCase):

    def test_one_row_per_pick_with_evidence(self):
        t = table(plan())
        self.assertEqual(t["Product"].tolist(), ["Hoodie", "Tee", "Mug"])
        hoodie = t.iloc[0]
        self.assertEqual(hoodie["Price"], 55.0)
        self.assertEqual(hoodie["Playbook phase"], "Mid-Dec")
        self.assertEqual(hoodie["Replaces"], NO_REPLACEMENT)
        self.assertEqual(hoodie["Test visits/day"], 100)
        self.assertFalse(hoodie["Weak data"])

    def test_edits_are_written_back(self):
        sl = plan()
        t = table(sl)
        t.loc[0, ["Phase", "Slot", "Replaces"]] = ["Early Nov", "Category page", "Slow Shirt"]
        new, changed = apply_table_edits(sl, t)
        self.assertTrue(changed)
        self.assertEqual(new["Hoodie"]["holiday_phase"], "Early Nov")
        self.assertEqual(new["Hoodie"]["slot"], "Category page")
        self.assertEqual(new["Hoodie"]["replacement_product"], "Slow Shirt")
        self.assertEqual(sl["Hoodie"]["holiday_phase"], "Black Friday / Cyber Monday")  # input untouched

    def test_unchanged_table_is_not_a_change(self):
        sl = plan()
        _, changed = apply_table_edits(sl, table(sl))
        self.assertFalse(changed)

    def test_replacement_options_and_category_check(self):
        sl = plan()
        opts = replacement_options(sl, SUMMARY)
        self.assertEqual(opts[0], NO_REPLACEMENT)
        self.assertIn("Slow Mug", opts)
        sl["Hoodie"]["replacement_product"] = "Slow Mug"  # wrong category
        self.assertEqual(bad_replacements(sl, SUMMARY), [("Hoodie", "Slow Mug")])


class BulkTest(unittest.TestCase):

    def test_set_for_selected(self):
        new = set_for(plan(), ["Hoodie", "Tee"], phase="Post-Christmas", slot="Cart add-on")
        self.assertEqual(new["Tee"]["holiday_phase"], "Post-Christmas")
        self.assertIsNone(new["Hoodie"]["replacement_product"])
        self.assertEqual(new["Mug"]["holiday_phase"], "Mid-Dec")

    def test_remove(self):
        self.assertEqual(list(remove_keys(plan(), ["Tee"])), ["Hoodie", "Mug"])

    def test_use_playbook(self):
        new, moved = use_playbook_phases(plan(), RECOMMENDED)
        self.assertEqual(moved, 1)  # only Hoodie was off
        self.assertEqual(new["Hoodie"]["holiday_phase"], "Mid-Dec")

    def test_fill_empty_phases_adds_strongest_unused_stars(self):
        new, added = fill_empty_phases(plan(), SUMMARY, RECOMMENDED, per_phase=1)
        self.assertEqual(added, ["Star Early", "Star Post"])  # Weak Star skipped
        self.assertEqual(new["Star Post"]["holiday_phase"], "Post-Christmas")
        self.assertEqual(len(new), 5)

    def test_starter_plan_from_empty(self):
        new, added = fill_empty_phases({}, SUMMARY, RECOMMENDED, per_phase=2)
        self.assertEqual(set(added), {"Star Early", "Star Early 2", "Star Post", "Hoodie", "Mug", "Tee"})
        self.assertEqual(new["Star Early"]["placement_slot"], "Homepage")  # strongest of its phase
        self.assertEqual(new["Star Early 2"]["placement_slot"], "Category page")


    def test_fill_tops_up_to_min_total_in_thinnest_phase(self):
        new, added = fill_empty_phases(plan(), SUMMARY, RECOMMENDED, per_phase=1, min_total=7)
        self.assertEqual(added, ["Star Early", "Star Post", "Star Early 2", "Gem Early"])
        self.assertEqual(len(new), 7)
        self.assertEqual(new["Star Early 2"]["placement_slot"], "Category page")  # phase already had a pick

    def test_fill_stops_when_candidates_run_out(self):
        new, _ = fill_empty_phases(plan(), SUMMARY, RECOMMENDED, per_phase=1, min_total=50)
        self.assertEqual(len(new), 7)  # Weak Star and the slow sellers are never added

    def test_hidden_gems_fill_in_after_stars(self):
        _, added = fill_empty_phases({}, SUMMARY, RECOMMENDED, per_phase=3)
        early = [n for n in added if RECOMMENDED[n] == "Early Nov"]
        self.assertEqual(early, ["Star Early", "Star Early 2", "Gem Early"])  # Stars first


class StatsTest(unittest.TestCase):

    def test_stats_and_board(self):
        sl = plan()
        t = table(sl)
        s = plan_stats(sl, t)
        self.assertEqual((s["count"], s["phases_covered"], s["off_playbook"]), (3, 2, 1))
        self.assertEqual((s["top_category"], s["top_category_share"]), ("Apparel", 67))
        board = board_html(t, {"Star": "#10B981"})
        self.assertEqual(board.count("Nothing planned"), 2)
        self.assertIn("Hoodie", board)


if __name__ == "__main__":
    unittest.main()

"""Tests for ai_review.py: verification, fallback, planted mistakes, Apply.
A fake Gemini call returns canned answers, so no network or key is needed."""

import unittest

from ai_context import build_context
from ai_review import Action, Issue, Review, apply_action, review_plan, verify
from ai_rules import run_rules
from tests.test_ai_rules import clean_plan, make_pairs, make_prices, make_summary, make_weekly, pick


class AIReviewTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.summary = make_summary()
        cls.catalog = set(cls.summary["item_name"])
        plan = clean_plan()
        plan["Mug 0"] = pick("Mug 0", "Black Friday / Cyber Monday")  # Playbook says Mid-Dec
        plan.pop("Mug 3")
        cls.plan = plan
        cls.ctx = build_context(plan, cls.summary, make_weekly(), make_pairs(),
                                prices=make_prices(cls.summary))
        cls.findings = run_rules(cls.ctx)
        cls.mug0 = next(p for p in cls.ctx["picks"] if p["name"] == "Mug 0")

    def good_review(self):
        rate = self.mug0["view_to_buy_pct"]
        return Review(
            headline="Mug 0 is scheduled in the wrong week.",
            issues=[Issue(severity="medium", title="Mug 0 timing",
                          explanation=f"Mug 0 converts at {rate}% of views. It sold best per week in Mid-Dec.",
                          products=["Mug 0"])],
            actions=[Action(type="move_phase", product="Mug 0", phase="Mid-Dec",
                            reason="The Season Playbook favours Mid-Dec."),
                     Action(type="swap", product="Bag 2", add="Pool Star", reason="Pool Star has stronger evidence.")],
        )

    def fake(self, review):
        return lambda client, model, ctx, findings: review

    # ---- verify ----

    def test_clean_answer_passes_untouched(self):
        clean, log = verify(self.good_review(), self.ctx, self.findings, self.catalog)
        self.assertEqual(clean, self.good_review())
        self.assertTrue(all(e["kept"] for e in log))

    def test_wrong_number_is_removed(self):
        r = self.good_review()
        r.issues[0].explanation = "Mug 0 converts at 61.37% of views. It sold best per week in Mid-Dec."
        clean, log = verify(r, self.ctx, self.findings, self.catalog)
        self.assertNotIn("61.37", clean.issues[0].explanation)
        self.assertIn("Mid-Dec", clean.issues[0].explanation)
        self.assertTrue(any("61.37" in e["reason"] for e in log if not e["kept"]))

    def test_unknown_product_is_removed(self):
        r = self.good_review()
        r.issues.append(Issue(severity="high", title="Add a robot", explanation="Try it.",
                              products=["Google Robot Dog"]))
        clean, _ = verify(r, self.ctx, self.findings, self.catalog)
        self.assertEqual(len(clean.issues), 1)

    def test_catalog_product_outside_plan_and_pool_is_removed(self):
        r = self.good_review()
        r.issues[0].explanation = "Consider Thin Sticker instead."
        clean, _ = verify(r, self.ctx, self.findings, self.catalog)
        self.assertEqual(clean.issues, [])

    def test_causal_claim_is_removed(self):
        r = self.good_review()
        r.issues[0].explanation = "Moving it will increase sales. It sold best per week in Mid-Dec."
        clean, log = verify(r, self.ctx, self.findings, self.catalog)
        self.assertEqual(clean.issues[0].explanation, "It sold best per week in Mid-Dec.")

    def test_swap_must_add_from_pool(self):
        r = self.good_review()
        r.actions[1].add = "Thin Sticker"
        clean, _ = verify(r, self.ctx, self.findings, self.catalog)
        self.assertEqual([a.type for a in clean.actions], ["move_phase"])

    def test_small_counts_and_rule_numbers_are_allowed(self):
        r = self.good_review()
        r.issues[0].explanation = "3 picks share a theme; the brief asks for 10–15 products."
        clean, _ = verify(r, self.ctx, self.findings, self.catalog)
        self.assertEqual(clean.issues[0].explanation, r.issues[0].explanation)

    # ---- review_plan ----

    def test_no_key_falls_back_to_rules(self):
        result = review_plan(self.ctx, self.findings, api_key=None)
        self.assertEqual(result.source, "rules")
        self.assertTrue(result.review.issues)
        self.assertEqual(result.review.actions[0].type, "move_phase")  # from phase_mismatch

    def test_api_error_falls_back_to_rules(self):
        def boom(*_):
            raise RuntimeError("quota exceeded")
        result = review_plan(self.ctx, self.findings, client=object(), call=boom)
        self.assertEqual(result.source, "rules")
        self.assertIn("quota", result.error)

    def test_gemini_answer_is_used_when_verified(self):
        result = review_plan(self.ctx, self.findings, client=object(),
                             call=self.fake(self.good_review()), catalog_names=self.catalog)
        self.assertEqual(result.source, "gemini")
        self.assertEqual(len(result.review.actions), 2)

    def test_planted_mistake_is_caught(self):
        result = review_plan(self.ctx, self.findings, client=object(), call=self.fake(self.good_review()),
                             catalog_names=self.catalog, plant_mistake=True)
        self.assertTrue(result.planted)
        self.assertTrue(any(not e["kept"] and "not in the data" in e["reason"] for e in result.log))
        self.assertNotIn(str(self.mug0["view_to_buy_pct"] * 3 + 7.3)[:4],
                         result.review.issues[0].explanation)

    def test_everything_dropped_falls_back_to_rules(self):
        bad = Review(headline="x", issues=[Issue(severity="high", title="t", explanation="Sales will sell out.",
                                                 products=["Mug 0"])], actions=[])
        result = review_plan(self.ctx, self.findings, client=object(), call=self.fake(bad))
        self.assertEqual(result.source, "rules")

    # ---- apply_action ----

    def summary_rows(self):
        return {r["item_name"]: r for r in self.summary.to_dict("records")}

    def test_apply_move_phase(self):
        new, clear = apply_action(self.plan, Action(type="move_phase", product="Mug 0", phase="Mid-Dec",
                                                    reason="r"), self.summary_rows())
        self.assertEqual(new["Mug 0"]["holiday_phase"], "Mid-Dec")
        self.assertIn("phase_Mug 0", clear)
        self.assertEqual(self.plan["Mug 0"]["holiday_phase"], "Black Friday / Cyber Monday")  # input untouched

    def test_apply_swap_keeps_phase_and_slot(self):
        new, _ = apply_action(self.plan, Action(type="swap", product="Bag 2", add="Pool Star", reason="r"),
                              self.summary_rows())
        self.assertNotIn("Bag 2", new)
        self.assertEqual(new["Pool Star"]["holiday_phase"], "Post-Christmas")
        self.assertEqual(new["Pool Star"]["placement_slot"], "Homepage")
        self.assertEqual(new["Pool Star"]["label"], "Star")
        self.assertEqual(len(new), len(self.plan))

    def test_apply_remove(self):
        new, _ = apply_action(self.plan, Action(type="remove", product="Bag 2", reason="r"), self.summary_rows())
        self.assertEqual(len(new), len(self.plan) - 1)


if __name__ == "__main__":
    unittest.main()

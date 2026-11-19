"""Tests for ai_evidence.py and the issue -> rule-check links (no network)."""

import unittest

from ai_context import build_context
from ai_evidence import (
    action_evidence,
    chart_for,
    cite_numbers,
    issue_evidence,
    number_sources,
    phase_history,
)
from ai_review import (
    Action,
    Chart,
    Issue,
    Review,
    finding_refs,
    review_plan,
    rules_review,
    verify,
)
from ai_rules import run_rules
from tests.test_ai_rules import (
    clean_plan,
    make_pairs,
    make_prices,
    make_summary,
    make_weekly,
    pick,
)


class EvidenceTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.summary = make_summary()
        cls.weekly = make_weekly()
        plan = clean_plan()
        plan["Mug 0"] = pick("Mug 0", "Black Friday / Cyber Monday")  # Playbook says Mid-Dec
        cls.ctx = build_context(plan, cls.summary, cls.weekly, make_pairs(), prices=make_prices(cls.summary))
        cls.findings = run_rules(cls.ctx)
        cls.refs = finding_refs(cls.findings)
        cls.mug0 = next(p for p in cls.ctx["picks"] if p["name"] == "Mug 0")

    def mismatch_ref(self):
        return next(r for r, f in self.refs.items() if f.id == "phase_mismatch")

    def test_numbers_are_traced_to_their_source(self):
        text = f"Mug 0 converts at {self.mug0['view_to_buy_pct']}% of views; 3 picks share a theme."
        cites = cite_numbers(text, number_sources(self.ctx, self.findings), {"Mug 0"})
        rate = cites[0]
        self.assertIn("Mug 0 · view-to-buy %", rate["sources"])
        self.assertEqual(cites[1]["number"], "3")
        self.assertTrue(cites[1]["sources"])  # a count or a matching value, never empty

    def test_dollar_amounts_only_cite_prices(self):
        n = self.ctx["plan"]["count"]
        cites = cite_numbers(f"Every pick costs under ${n}.", number_sources(self.ctx, self.findings), set())
        self.assertTrue(all("price" in s.lower() or "$" in s for s in cites[0]["sources"]), cites)

    def test_counts_cite_the_linked_rule_not_a_coincidence(self):
        plan_size = next((f for f in self.findings if f.id == "plan_size"), None)
        n = self.ctx["plan"]["count"]
        text = f"The plan has {n} products; the brief asks for 10-15. Add 1 more."
        cites = cite_numbers(text, number_sources(self.ctx, self.findings), set(),
                             {plan_size.title} if plan_size else set())
        by_num = {c["number"]: c["sources"] for c in cites}
        self.assertTrue(by_num[str(n)][0].startswith(("Plan ·", "Rule check")))
        self.assertTrue(by_num["10"][0].startswith(("Plan ·", "Rule check")))
        self.assertEqual(by_num["1"], ["a count (small whole numbers are allowed)"])

    def test_issue_links_survive_verification_and_bad_refs_are_logged(self):
        r = Review(headline="h", actions=[], issues=[Issue(
            severity="medium", title="Mug 0 timing", explanation="It sold best per week in Mid-Dec.",
            products=["Mug 0"], based_on=[self.mismatch_ref(), "F99"])])
        clean, log = verify(r, self.ctx, self.findings, set(self.summary["item_name"]))
        self.assertEqual(clean.issues[0].based_on, [self.mismatch_ref()])
        self.assertTrue(any("F99" in e["item"] and not e["kept"] for e in log))

    def test_rule_fallback_links_every_issue(self):
        review = rules_review(self.ctx, self.findings)
        self.assertEqual([i.based_on for i in review.issues], [[r] for r in self.refs])
        self.assertEqual(review_plan(self.ctx, self.findings).source, "rules")

    def test_phase_mismatch_evidence_has_table_and_history_chart(self):
        f = self.refs[self.mismatch_ref()]
        table, charts = issue_evidence([], [f], self.ctx, self.weekly)
        self.assertEqual(table["Product"].tolist(), ["Mug 0"])
        self.assertEqual(table.iloc[0]["Best phase (Playbook)"], "Mid-Dec")
        self.assertEqual(len(charts), 1)

    def test_phase_history_matches_playbook_rule(self):
        h = phase_history(self.weekly, "Mug 0").set_index("phase")
        self.assertEqual(h["purchases_per_week"].idxmax(), "Mid-Dec")

    def test_own_observation_shows_rate_ranges(self):
        table, charts = issue_evidence(["Mug 0", "Bag 2"], [], self.ctx, self.weekly)
        self.assertEqual(len(table), 2)
        self.assertEqual(len(charts), 1)

    def test_swap_before_after(self):
        a = Action(type="swap", product="Mug 0", add=self.ctx["swap_pool"][0]["name"], reason="r")
        table, fig, _ = action_evidence(a, self.ctx, self.weekly)
        self.assertEqual(table["Role"].tolist(), ["Out", "In"])
        self.assertIsNotNone(fig)

    def test_move_before_after_summary(self):
        a = Action(type="move_phase", product="Mug 0", phase="Mid-Dec", reason="r")
        _, fig, note = action_evidence(a, self.ctx, self.weekly)
        self.assertIn("purchases/week in Black Friday / Cyber Monday", note)
        self.assertIsNotNone(fig)



class ChartPickTest(unittest.TestCase):
    """Gemini picks a chart from the menu; the app draws it and checks the pick."""

    setUpClass = classmethod(EvidenceTest.setUpClass.__func__)

    def review_with(self, chart):
        issue = Issue(severity="medium", title="Mug 0 timing", explanation="Mug 0 sells best later.",
                      products=["Mug 0"], chart=chart)
        clean, log = verify(Review(headline="h", issues=[issue], actions=[]), self.ctx, self.findings)
        return clean.issues[0].chart, log

    def test_valid_design_is_kept_and_drawn_from_the_data(self):
        chart, log = self.review_with(Chart(
            why="w", data="products", mark="point", x="view_to_buy_pct", y="product", color="plan_status",
            include_candidates=True, show_range=True, title="Picks vs candidates",
            look_for="Look at the dots on the left."))
        self.assertIsNotNone(chart)
        fig = chart_for(chart, self.ctx, self.weekly)
        plotted = {v for tr in fig.data for v in tr.y}
        expected = {p["name"] for p in self.ctx["picks"] + self.ctx["swap_pool"]
                    if p.get("view_to_buy_pct") is not None}
        self.assertEqual(plotted, expected)  # every point is a real product row
        self.assertTrue(any(x["kept"] and x["item"].startswith("chart") for x in log))

    def test_invented_product_drops_the_chart(self):
        chart, log = self.review_with(Chart(why="w", data="products", mark="bar", x="product", y="views",
                                            products=["Mug 0", "Made-up Mug"], title="t", look_for="x"))
        self.assertIsNone(chart)
        self.assertTrue(any(not x["kept"] and "Made-up Mug" in x["reason"] for x in log))

    def test_field_must_exist_in_the_chosen_data(self):
        chart, log = self.review_with(Chart(why="w", data="weekly", mark="line", x="week", y="price", title="t",
                                            look_for="x"))
        self.assertIsNone(chart)
        self.assertTrue(any("price" in x["reason"] for x in log if not x["kept"]))

    def test_bar_values_and_named_limit_line_are_shown(self):
        chart = Chart(why="w", data="products", mark="bar", x="product", y="price", reference_line=50,
                      line_label="anchor-gift minimum", title="t", look_for="x")
        fig = chart_for(chart, self.ctx, self.weekly)
        self.assertIn("$", fig.data[0].texttemplate)
        self.assertIn("anchor-gift minimum: $50", fig.layout.annotations[0].text)

    def test_reference_line_must_be_a_real_number(self):
        ok, _ = self.review_with(Chart(why="w", data="products", mark="bar", x="product", y="price",
                                       reference_line=50, title="t", look_for="x"))
        bad, _ = self.review_with(Chart(why="w", data="products", mark="bar", x="product", y="price",
                                        reference_line=77.7, title="t", look_for="x"))
        self.assertIsNotNone(ok)
        self.assertIsNone(bad)

    def test_wrong_number_in_caption_is_removed_but_chart_kept(self):
        chart, log = self.review_with(Chart(why="w", data="products", mark="bar", x="category", y="picks",
                                            title="Picks by category", look_for="Mugs are 97.3% of the plan."))
        self.assertEqual(chart.look_for, "")
        self.assertIsNotNone(chart_for(chart, self.ctx, self.weekly))
        self.assertTrue(any(not x["kept"] and "97.3" in x["item"] for x in log))

    def test_weekly_line(self):
        chart = Chart(why="w", data="weekly", mark="line", x="week", y="purchases", color="product",
                      products=["Mug 0"], title="t", look_for="")
        self.assertIsNotNone(chart_for(chart, self.ctx, self.weekly))

if __name__ == "__main__":
    unittest.main()

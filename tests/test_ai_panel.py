"""The second-opinion section renders inside the real app (no API key needed),
and its notes fit on the one-page PDF brief."""

import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
MUGS = ["Google PNW Campus Mug", "Google Austin Campus Mug", "Google Seattle Campus Mug",
        "Google Chicago Campus Mug", "Google LA Campus Mug"]


class PlanReviewPanelTest(unittest.TestCase):

    def run_builder(self, shortlist):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        app.session_state["shortlist"] = shortlist
        app.sidebar.radio[0].set_value("Shortlist Builder").run()
        self.assertFalse(app.exception, [str(e.message) for e in app.exception])
        return app

    def test_mug_heavy_plan_shows_overload_card(self):
        summary = pd.read_csv(ROOT / "data" / "product_summary.csv")
        shortlist = {
            name: {**summary[summary["item_name"] == name].iloc[0].to_dict(),
                   "holiday_phase": "Black Friday / Cyber Monday"}
            for name in MUGS
        }
        app = self.run_builder(shortlist)
        text = " ".join(str(m.value) for m in app.markdown)
        self.assertIn("Second opinion before you export", text)
        rows = " ".join(e.label for e in app.expander)  # the checks list is one row per check
        self.assertIn("Too much Campus Collection", rows)
        self.assertIn("Ask Gemini for a second opinion", text)
        self.assertIn("Post-Christmas", text)


class BriefNotesTest(unittest.TestCase):
    """The AI notes are an optional extra on the brief: it must still be one page."""

    def test_fifteen_products_with_notes_stay_on_one_page(self):
        import re

        from test_part_a_pdf import TestPDFExport, load_pdf_builder

        build = load_pdf_builder()
        shortlist, cats, prices = TestPDFExport.make_data(None, 15)
        notes = ["Black Friday has no gift over $50 & <one> phase is empty."] + [
            f"Issue {i}: a two-sentence explanation of the problem. It cites 12.5% and $18." for i in range(5)
        ]
        pdf = build(shortlist, cats, prices, 0, review_notes=notes)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf)), 1)


if __name__ == "__main__":
    unittest.main()

"""The Plan review section renders inside the real app (no API key needed)."""

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
        self.assertIn("Plan review", text)
        self.assertIn("Too much Campus Collection", text)
        self.assertIn("Post-Christmas", text)


if __name__ == "__main__":
    unittest.main()

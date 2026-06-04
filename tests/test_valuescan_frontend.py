from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ValuescanFrontendTest(unittest.TestCase):
    def test_dashboard_declares_valuescan_research_feature_table(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="vs-feature-rows"', html)
        self.assertIn("Research Features", html)

    def test_valuescan_js_fetches_and_renders_research_features(self):
        js = (ROOT / "serve" / "static" / "js" / "valuescan.js").read_text(encoding="utf-8")

        self.assertIn("/valuescan/ai/features", js)
        self.assertIn("renderValuescanFeatures", js)
        self.assertIn("vs-feature-rows", js)


if __name__ == "__main__":
    unittest.main()

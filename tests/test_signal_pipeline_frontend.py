from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SignalPipelineFrontendTest(unittest.TestCase):
    def test_dashboard_declares_signal_pipeline_module_and_script(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-module="pipeline"', html)
        self.assertIn('id="module-pipeline"', html)
        self.assertIn('id="pipeline-summary-cards"', html)
        self.assertIn('id="pipeline-backtest-summary-cards"', html)
        self.assertIn('id="pipeline-backtest-trade-rows"', html)
        self.assertIn('id="pipeline-backtest-attribution-rows"', html)
        self.assertIn('id="pipeline-equity-feed"', html)
        self.assertIn('id="pipeline-comparison-summary-cards"', html)
        self.assertIn('id="pipeline-comparison-rows"', html)
        self.assertIn('js/pipeline.js', html)

    def test_router_initializes_pipeline_module(self):
        js = (ROOT / "serve" / "static" / "js" / "main.js").read_text(encoding="utf-8")

        self.assertIn("if (name === 'pipeline') initPipeline();", js)

    def test_pipeline_js_calls_pipeline_preview_api(self):
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("/signals/pipeline-preview", js)
        self.assertIn("/signals/event-backtest-preview", js)
        self.assertIn("/signals/migration-comparison-preview", js)
        self.assertIn("renderPipelineSignals", js)
        self.assertIn("renderPipelineRisk", js)
        self.assertIn("renderPipelineOrders", js)
        self.assertIn("renderPipelineBacktest", js)
        self.assertIn("renderPipelineAttribution", js)
        self.assertIn("renderPipelineComparison", js)

    def test_pipeline_orders_render_normalized_plan_prices(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("<th>Entry</th>", html)
        self.assertIn("<th>Stop</th>", html)
        self.assertIn("<th>Target</th>", html)
        self.assertIn("order.entry_price", js)
        self.assertIn("order.stop_price", js)
        self.assertIn("order.target_price", js)


if __name__ == "__main__":
    unittest.main()

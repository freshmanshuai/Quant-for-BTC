import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class PineGoldenCliTest(unittest.TestCase):
    def test_signal_module_parity_cli_writes_example_artifacts(self):
        from quant_platform.delivery import compare_pine_golden_vector_files
        from pine.signal_module_parity import main

        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["--output-dir", tmp])

            expected_path = Path(tmp) / "expected_vectors.json"
            observed_path = Path(tmp) / "observed_template.csv"
            pine_path = Path(tmp) / "signal_module_parity.pine"

            self.assertEqual(exit_code, 0)
            self.assertIn("PINE_PARITY_EXAMPLE_WRITTEN", output.getvalue())
            self.assertTrue(pine_path.exists())
            self.assertTrue(expected_path.exists())
            self.assertTrue(observed_path.exists())
            self.assertEqual(compare_pine_golden_vector_files(expected_path, observed_path, tolerance=0.01), [])

    def test_signal_module_parity_cli_compares_observed_export(self):
        from pine.signal_module_parity import main

        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main([
                    "--output-dir",
                    tmp,
                    "--observed",
                    str(Path(tmp) / "observed_template.csv"),
                    "--tolerance",
                    "0.01",
                ])

        self.assertEqual(exit_code, 0)
        self.assertIn("PINE_GOLDEN_VECTOR_MATCHES", output.getvalue())

    def test_signal_module_parity_cli_accepts_signal_module_config(self):
        from pine.signal_module_parity import main

        signal_config = {
            "default_module_set": "pine_subset",
            "module_sets": [
                {
                    "name": "pine_subset",
                    "modules": [
                        {
                            "type": "breakout",
                            "params": {
                                "module": "configured_breakout",
                                "lookback": 3,
                                "allow_short": False,
                            },
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            config_path = Path(tmp) / "research_signal_modules.json"
            config_path.write_text(json.dumps(signal_config), encoding="utf-8")

            with redirect_stdout(output):
                exit_code = main([
                    "--output-dir",
                    tmp,
                    "--config",
                    str(config_path),
                    "--timeframe",
                    "1D",
                ])

            pine_source = (Path(tmp) / "signal_module_parity.pine").read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("// configured_breakout", pine_source)
        self.assertIn('configured_breakout_close = request.security(syminfo.tickerid, "1D", close)', pine_source)
        self.assertNotIn("// pullback", pine_source)

    def test_compare_cli_returns_zero_when_observations_match(self):
        from pine.compare_golden_vectors import main

        with tempfile.TemporaryDirectory() as tmp:
            expected_path, observed_path = self._write_vector_files(tmp, score="82.0")
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main([
                    "--expected",
                    str(expected_path),
                    "--observed",
                    str(observed_path),
                    "--tolerance",
                    "0.01",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip(), "PINE_GOLDEN_VECTOR_MATCHES")

    def test_compare_cli_accepts_utf8_bom_files_from_powershell_exports(self):
        from pine.compare_golden_vectors import main

        with tempfile.TemporaryDirectory() as tmp:
            expected_path, observed_path = self._write_vector_files(tmp, score="82.0")
            expected_path.write_bytes(("\ufeff" + expected_path.read_text(encoding="utf-8")).encode("utf-8"))
            observed_path.write_bytes(("\ufeff" + observed_path.read_text(encoding="utf-8")).encode("utf-8"))
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main([
                    "--expected",
                    str(expected_path),
                    "--observed",
                    str(observed_path),
                    "--tolerance",
                    "0.01",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip(), "PINE_GOLDEN_VECTOR_MATCHES")

    def test_compare_cli_returns_one_and_prints_issues_when_observations_differ(self):
        from pine.compare_golden_vectors import main

        with tempfile.TemporaryDirectory() as tmp:
            expected_path, observed_path = self._write_vector_files(tmp, score="81.0")
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main([
                    "--expected",
                    str(expected_path),
                    "--observed",
                    str(observed_path),
                    "--tolerance",
                    "0.01",
                ])

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "BTC/USDT|tactical|breakout|long 2026-06-03T08:00:00Z: "
            "score expected=82.0 actual=81.0",
            output.getvalue(),
        )

    def _write_vector_files(self, tmp: str, *, score: str) -> tuple[Path, Path]:
        expected_path = Path(tmp) / "expected.json"
        observed_path = Path(tmp) / "observed.csv"
        expected_path.write_text(
            json.dumps([
                {
                    "signal_key": "BTC/USDT|tactical|breakout|long",
                    "bar_time": "2026-06-03T08:00:00Z",
                    "entry_price": 100.0,
                    "stop_price": 95.0,
                    "target_price": 120.0,
                    "score": 82.0,
                }
            ]),
            encoding="utf-8",
        )
        observed_path.write_text(
            "\n".join([
                "signal_key,bar_time,entry_price,stop_price,target_price,score",
                f"BTC/USDT|tactical|breakout|long,2026-06-03T08:00:00Z,100.0,95.0,120.0,{score}",
            ]),
            encoding="utf-8",
        )
        return expected_path, observed_path


if __name__ == "__main__":
    unittest.main()

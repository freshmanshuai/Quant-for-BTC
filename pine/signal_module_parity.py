"""Generate and optionally compare signal-module Pine parity artifacts."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from quant_platform.delivery import compare_pine_golden_vector_files
from quant_platform.pine import write_signal_module_pine_parity_example


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate direct-compute signal-module Pine parity artifacts and optionally compare observations."
    )
    parser.add_argument(
        "--output-dir",
        default="pine/examples",
        help="Directory for generated Pine script, expected vectors, and observed template.",
    )
    parser.add_argument(
        "--observed",
        help="Optional TradingView/Pine observed CSV or JSON export to compare after regenerating expected vectors.",
    )
    parser.add_argument(
        "--config",
        help="Optional research signal-module JSON config to generate Pine from.",
    )
    parser.add_argument(
        "--module-set",
        help="Optional module set name inside --config. Defaults to the config default_module_set.",
    )
    parser.add_argument(
        "--timeframe",
        default="",
        help="Optional timeframe injected into configured modules that omit timeframe.",
    )
    parser.add_argument("--tolerance", type=float, default=0.01, help="Numeric comparison tolerance.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    artifacts = write_signal_module_pine_parity_example(
        args.output_dir,
        config_path=args.config,
        module_set=args.module_set,
        timeframe=args.timeframe,
    )
    print("PINE_PARITY_EXAMPLE_WRITTEN")
    for name in ("pine_script", "expected_vectors", "observed_template"):
        print(f"{name}={artifacts[name]}")

    observed_path = args.observed
    if not observed_path:
        return 0

    issues = compare_pine_golden_vector_files(
        artifacts["expected_vectors"],
        observed_path,
        tolerance=args.tolerance,
    )
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print("PINE_GOLDEN_VECTOR_MATCHES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

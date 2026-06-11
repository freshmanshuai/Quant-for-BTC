"""Compare Python Pine golden vectors with exported Pine observations."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from quant_platform.delivery import compare_pine_golden_vector_files


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare expected Python Pine golden vectors with Pine/TradingView observations."
    )
    parser.add_argument("--expected", required=True, help="Path to expected golden-vector JSON.")
    parser.add_argument("--observed", required=True, help="Path to observed Pine CSV or JSON export.")
    parser.add_argument("--tolerance", type=float, default=1e-9, help="Numeric comparison tolerance.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    issues = compare_pine_golden_vector_files(
        args.expected,
        args.observed,
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

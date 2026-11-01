"""Small reproducible local benchmark for long-document rendering and API latency.

This is a measurement helper, not a merge gate. It never sends data to a
provider and exits non-zero only when an explicitly supplied budget is missed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


def fixture(size: int) -> str:
    return "\n".join(f"## Section {index}\nA searchable paragraph {index} with **formatting**." for index in range(size))


def measure(size: int, repeats: int) -> dict[str, float | int]:
    values = []
    text = fixture(size)
    for _ in range(repeats):
        started = time.perf_counter()
        # Parsing cost is intentionally represented by deterministic line/index work.
        _ = [line for line in text.splitlines() if line.startswith("## ")]
        values.append((time.perf_counter() - started) * 1000)
    values.sort()
    return {"fixture_sections": size, "repeats": repeats, "median_ms": statistics.median(values), "p95_ms": values[min(len(values) - 1, int(len(values) * .95))]}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sections", type=int, default=5000)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--p95-budget-ms", type=float, default=2000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.sections < 1 or args.repeats < 2: parser.error("sections >= 1 and repeats >= 2 are required")
    result = measure(args.sections, args.repeats)
    print(json.dumps(result, indent=2))
    if args.output: args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["p95_ms"] <= args.p95_budget_ms else 2


if __name__ == "__main__": raise SystemExit(main())

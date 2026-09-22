"""Print a markdown table from bench/*/summary.json:  uv run python scripts/results.py"""

import json
import sys
from pathlib import Path


def main():
    rows = []
    for summary in sorted(Path(sys.argv[1] if len(sys.argv) > 1 else "bench/final").glob("*/summary.json")):
        s = json.loads(summary.read_text())
        rows.append(s | {"folder": summary.parent.name})
    print("| task | policy | runs verified | median time | requests | stale | actions | model ms | input tokens | cost/run |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for s in sorted(rows, key=lambda r: (r["task"], r["folder"])):
        ms = f"{s['median_ms_verified'] / 1000:.2f} s" if s["median_ms_verified"] else "not verified"
        cost = f"${s['median_cost_usd']:.4f}" if s["median_cost_usd"] else ""
        fmt = lambda v: "" if v is None else (str(int(v)) if float(v).is_integer() else str(v))  # noqa: E731
        print(
            f"| {s['task']} | {s['policy']} ({s['folder']}) | {s['verified']}/{s['runs']} | {ms} | {fmt(s['median_requests'])} | "
            f"{fmt(s['median_stale'])} | {fmt(s['median_actions'])} | {fmt(s['median_model_ms'])} | "
            f"{fmt(s['median_input_tokens'])} | {cost} |"
        )


if __name__ == "__main__":
    main()

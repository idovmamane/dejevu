"""Repeat a reference task and write comparable numbers: python -m jevless.measure --task flights --runs 3 --out bench/flights"""

import argparse
import hashlib
import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from .agent import Agent
from .config import PRESETS, make_policy
from .tasks import TASKS


def source_hashes():
    root = Path(__file__).parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in sorted(root.iterdir()) if p.suffix in {".py", ".js"}}


def one_run(task, policy, *, headless=True, cdp_url=None, max_actions=40):
    started = time.perf_counter()
    agent = Agent(
        task.url,
        task.goal,
        policy=policy,
        headless=headless,
        cdp_url=cdp_url,
        max_actions=max_actions,
        clock_from=task.clock_from,
    )
    error = None
    try:
        for state in agent.run():
            last = state["history"][-1] if state["history"] else {}
            print(
                f"    {state['elapsed_ms']:>6} ms  {state['status']:<8} {last.get('op', ''):<12} "
                f"{str(last.get('label', ''))[:50]}",
                flush=True,
            )
    except Exception as e:  # keep the evidence of a failed run
        error = f"{type(e).__name__}: {e}"
    result = agent.snapshot()
    result["error"] = error
    # Verification looks at a NEW observation, outside the clock, never at the model's DONE claim.
    try:
        final = agent.tab.observe()
        result["verification"] = task.verify(final)
        result["final_url"] = final["url"]
    except Exception as e:
        result["verification"] = {"passed": False, "checks": {"observe": str(e)}}
    result["wall_ms"] = round((time.perf_counter() - started) * 1000)
    result["setup_ms"] = agent.setup_ms
    result["browser"] = agent.chrome.version
    agent.close()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=sorted(TASKS), required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--preset", choices=sorted(PRESETS))
    parser.add_argument("--model")
    parser.add_argument("--provider")
    parser.add_argument("--reasoning", choices=["off", "low", "medium"], help="reasoning setting for models that need one")
    parser.add_argument("--logprobs", action="store_true")
    parser.add_argument("--backend", choices=["llm", "typesafe"])
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--cdp-url")
    parser.add_argument("--out", required=True, help="folder for per-run JSON and the summary")
    args = parser.parse_args(argv)
    task = TASKS[args.task]
    policy = make_policy(
        backend=args.backend,
        preset=args.preset,
        model=args.model,
        provider=args.provider,
        logprobs=True if args.logprobs else None,
        reasoning=args.reasoning,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for i in range(args.runs):
        print(f"run {i + 1}/{args.runs} · {task.name} · {policy.name}", flush=True)
        r = one_run(task, policy, headless=not args.headed, cdp_url=args.cdp_url)
        runs.append(r)
        (out / f"run-{i + 1}.json").write_text(json.dumps(r, indent=2, default=str))
        t = r["totals"]
        print(
            f"  → {r['status']} verified={r['verification']['passed']} {r['elapsed_ms']} ms · {t['requests']} requests "
            f"({t['stale']} stale) · {t['actions']} actions · model {t['model_ms']} ms · {t['input_tokens']} tokens"
            + (f" · ${t['cost_usd']:.5f}" if t["cost_usd"] is not None else "")
            + (f" · ERROR {r['error']}" if r["error"] else ""),
            flush=True,
        )
    passed = [r for r in runs if r["verification"]["passed"]]

    def med(key, rows):
        values = [row[key] for row in rows]
        return round(statistics.median(values), 1) if values else None

    def med_total(key, rows):
        values = [row["totals"][key] for row in rows if row["totals"].get(key) is not None]
        return round(statistics.median(values), 5) if values else None

    summary = {
        "task": task.name,
        "goal": task.goal,
        "policy": policy.name,
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "browser": runs[0]["browser"] if runs else None,
        "runs": len(runs),
        "verified": len(passed),
        "median_ms_verified": med("elapsed_ms", passed),
        "median_ms_all": med("elapsed_ms", runs),
        "median_requests": med_total("requests", passed),
        "median_stale": med_total("stale", passed),
        "median_actions": med_total("actions", passed),
        "median_model_ms": med_total("model_ms", passed),
        "median_model_latency_ms": med_total("model_median_ms", passed),
        "median_input_tokens": med_total("input_tokens", passed),
        "median_cost_usd": med_total("cost_usd", passed),
        "median_cdp_calls": med_total("cdp_calls", passed),
        "per_run": [
            {
                "elapsed_ms": r["elapsed_ms"],
                "status": r["status"],
                "verified": r["verification"]["passed"],
                **r["totals"],
            }
            for r in runs
        ],
        "source": source_hashes(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("per_run", "source", "goal")}, indent=2))


if __name__ == "__main__":
    main()

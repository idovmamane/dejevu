"""dejevu --url URL --goal '...'   |   dejevu --task flights"""

import argparse
import json
import sys
import time
from pathlib import Path

from .agent import Agent
from .config import PRESETS, make_policy
from .tasks import TASKS


def build_parser():
    parser = argparse.ArgumentParser(
        prog="dejevu", description="One glance, one action: a browser agent on any OpenAI-compatible model."
    )
    parser.add_argument("--task", choices=sorted(TASKS), help="a reference task with an independent outcome check")
    parser.add_argument("--url")
    parser.add_argument("--goal", action="append", help="repeat for an ordered list of goals")
    parser.add_argument("--preset", choices=sorted(PRESETS))
    parser.add_argument("--model", help="any model id on the endpoint (overrides the preset)")
    parser.add_argument("--provider", help="OpenRouter provider to pin ('' to unpin)")
    parser.add_argument("--reasoning", choices=["off", "low", "medium"], help="reasoning setting for models that need one")
    parser.add_argument("--logprobs", action="store_true", help="ask for token logprobs to report target probabilities")
    parser.add_argument("--backend", choices=["llm", "typesafe"])
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--cdp-url", help="attach to a running Chrome (e.g. http://127.0.0.1:9222) instead of launching one")
    parser.add_argument("--record", metavar="DIR", help="save a screenshot per step and the trace")
    parser.add_argument("--json", metavar="PATH", help="write the full run (trace, decisions, verification) as JSON")
    parser.add_argument("--max-actions", type=int, default=40)
    parser.add_argument("--keep-open", action="store_true", help="leave the browser open after the run")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.task:
        task = TASKS[args.task]
        url, goal, verify, clock_from = task.url, task.goal, task.verify, task.clock_from
    elif args.url and args.goal:
        url, goal, verify, clock_from = args.url, "\n".join(args.goal), None, None
    else:
        sys.exit("Give --task NAME, or --url URL with --goal '...'")
    policy = make_policy(
        backend=args.backend,
        preset=args.preset,
        model=args.model,
        provider=args.provider,
        logprobs=True if args.logprobs else None,
        reasoning=args.reasoning,
    )
    print(f"dejevu · {policy.name} · {url}", flush=True)
    started = time.perf_counter()
    agent = Agent(
        url,
        goal,
        policy=policy,
        headless=not args.headed,
        cdp_url=args.cdp_url,
        record_dir=args.record,
        max_actions=args.max_actions,
        clock_from=clock_from,
    )
    print(
        f"  browser ready in {agent.setup_ms} ms · {len(agent.page['actions'])} elements on {agent.page['url'][:80]}",
        flush=True,
    )
    result = None
    try:
        for state in agent.run():
            decision = state["decisions"][-1] if state["decisions"] else {}
            last = state["history"][-1] if state["history"] else {}
            what = decision.get("op", "")
            if decision.get("target") is not None:
                what += f" [{decision['target']}]"
            if decision.get("text") is not None:
                what += f' "{decision["text"][:40]}"'
            if decision.get("key"):
                what += f" {decision['key']}"
            note = decision.get("outcome") or ""
            if note == "executed" and last.get("op") == decision.get("op"):
                note = f"{last['label'][:50]!r}" + (" → changed" if last.get("page_changed") else " → no change")
            print(
                f"  {state['elapsed_ms']:>6} ms  {what:<34} model {decision.get('latency_ms', 0):>4} ms  {note}",
                flush=True,
            )
        result = agent.snapshot()
        result["verification"] = verify(agent.page) if verify else None
        result["setup_ms"] = agent.setup_ms
        result["wall_ms"] = round((time.perf_counter() - started) * 1000)
        result["final_page"] = {k: agent.page[k] for k in ("url", "title", "text", "actions")}
    finally:
        if result is None:
            result = {**agent.snapshot(), "error": "interrupted"}
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(result, indent=2, default=str))
        if args.record:
            (Path(args.record) / "trace.json").write_text(json.dumps(result, indent=2, default=str))
        if not args.keep_open:
            agent.close()
    t = result["totals"]
    print(
        f"\n{result['status'].upper()} ({result['reason']}) in {result['elapsed_ms']} ms timed, "
        f"{result.get('wall_ms')} ms wall incl. {agent.setup_ms} ms setup"
    )
    print(
        f"  {t['requests']} model requests ({t['stale']} stale, {t['invalid']} invalid) · "
        f"{t['actions']} actions ({t['waits']} waits) · "
        f"model {t['model_ms']} ms total, median {t['model_median_ms']} ms · "
        f"{t['input_tokens']} in / {t['output_tokens']} out tokens"
        + (f" · ${t['cost_usd']:.5f}" if t["cost_usd"] is not None else "")
        + f" · {t['cdp_calls']} CDP calls"
    )
    if result.get("verification") is not None:
        v = result["verification"]
        print(f"  verified: {v['passed']} {json.dumps(v['checks'])}")
        if not v["passed"]:
            sys.exit(1)
    if result["status"] != "done":
        sys.exit(1)


if __name__ == "__main__":
    main()

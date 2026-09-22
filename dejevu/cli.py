"""dejevu --task flights   |   dejevu --url URL --goal '...'   |   dejevu --doctor"""

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .agent import Agent
from .cdp import CDPError, Chrome, find_chrome
from .config import PRESETS, PolicyConfigError, api_key, load_env, make_policy
from .state import validate
from .tasks import TASKS
from .types import PolicyError

EXAMPLES = """examples:
  dejevu --doctor                                  check Chrome, the API key and the model in ten seconds
  dejevu --task wikipedia                          a two second run with a verified result
  dejevu --task flights --record artifacts/flights the Google Flights benchmark, with a screencast
  dejevu --url https://example.com --goal "Open the pricing page"
  dejevu --preset balanced --task flights          another model route

presets: """ + ", ".join(f"{name} ({p['model']})" for name, p in PRESETS.items())


def build_parser():
    parser = argparse.ArgumentParser(
        prog="dejevu",
        description="Browser agents that run on instinct. One look at the page, one call to any model, one action.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--task", choices=sorted(TASKS), help="a reference task with an independent outcome check")
    parser.add_argument("--url", help="start page for your own goal")
    parser.add_argument("--goal", action="append", help="what to achieve, repeat for an ordered list")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="model route (default: fast)")
    parser.add_argument("--model", help="any model id on the endpoint, overrides the preset")
    parser.add_argument("--provider", help="OpenRouter provider to pin, '' to unpin")
    parser.add_argument("--reasoning", choices=["off", "low", "medium"], help="for models that need a reasoning setting")
    parser.add_argument("--logprobs", action="store_true", help="ask for token logprobs to report target probabilities")
    parser.add_argument(
        "--backend", choices=["llm", "typesafe"], help="typesafe uses Jev as the chooser (needs TYPESAFE_API_KEY)"
    )
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--cdp-url", help="attach to a running Chrome, e.g. http://127.0.0.1:9222, instead of launching one")
    parser.add_argument("--record", metavar="DIR", help="save a screencast, screenshots per step and trace.json")
    parser.add_argument("--json", metavar="PATH", help="write the full run (trace, decisions, verification) as JSON")
    parser.add_argument("--max-actions", type=int, default=40)
    parser.add_argument("--keep-open", action="store_true", help="leave the browser open after the run")
    parser.add_argument("--doctor", action="store_true", help="check Chrome, the API key and one model call, then exit")
    parser.add_argument("--version", action="version", version=f"dejevu {__version__}")
    return parser


def doctor(args):
    """Three checks a new user needs before anything else: Chrome launches, a key exists, the model answers."""
    load_env()
    problems = 0

    def line(ok, label, detail):
        print(f"  {'ok  ' if ok else 'FAIL'}  {label:<8} {detail}", flush=True)

    try:
        path = find_chrome()
        chrome = Chrome(headless=True)
        line(True, "chrome", f"{chrome.version} at {path}")
        chrome.close()
    except Exception as e:  # any failure here is a setup problem, so show it whole
        problems += 1
        line(False, "chrome", f"{e}. Install Google Chrome or set DEJEVU_CHROME=/path/to/chrome")
    key = api_key()
    if key:
        line(True, "api key", "found")
    else:
        problems += 1
        line(False, "api key", "not found. Put OPENROUTER_API_KEY=... in a .env file (see .env.example)")
    if key:
        try:
            policy = make_policy(
                backend=args.backend, preset=args.preset, model=args.model, provider=args.provider, reasoning=args.reasoning
            )
            page = {
                "url": "about:blank",
                "title": "Doctor",
                "text": "Welcome. Press Continue to go on.",
                "w": 1120,
                "h": 780,
                "scroll": {"y": 0, "height": 780},
                "omitted": 0,
                "actions": [{"id": 1, "node": 1, "role": "button", "label": "Continue", "value": "", "kind": "click"}],
                "fingerprint": "doctor",
            }
            started = time.perf_counter()
            decision = policy.decide("Click the Continue button.", page, [])
            validate(decision, page)
            cost = f", ${decision.cost:.5f}" if decision.cost else ""
            line(True, "model", f"{policy.name} answered in {round((time.perf_counter() - started) * 1000)} ms{cost}")
        except (PolicyError, PolicyConfigError) as e:
            problems += 1
            line(False, "model", str(e))
    print("\nall good. Try: dejevu --task wikipedia" if not problems else f"\n{problems} problem(s) marked FAIL above")
    return 0 if not problems else 2


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.doctor:
        sys.exit(doctor(args))
    if args.task:
        task = TASKS[args.task]
        url, goal, verify, clock_from = task.url, task.goal, task.verify, task.clock_from
    elif args.url and args.goal:
        url, goal, verify, clock_from = args.url, "\n".join(args.goal), None, None
    else:
        parser.print_help()
        sys.exit("\ndejevu: give --task NAME, or --url URL with --goal '...'")
    try:
        policy = make_policy(
            backend=args.backend,
            preset=args.preset,
            model=args.model,
            provider=args.provider,
            logprobs=True if args.logprobs else None,
            reasoning=args.reasoning,
        )
    except PolicyConfigError as e:
        sys.exit(f"dejevu: {e}\n  hint: copy .env.example to .env, fill it in, then run: dejevu --doctor")
    print(f"dejevu · {policy.name} · {url}", flush=True)
    started = time.perf_counter()
    try:
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
    except (FileNotFoundError, CDPError) as e:
        sys.exit(
            f"dejevu: could not start the browser: {e}\n"
            "  hint: install Google Chrome or set DEJEVU_CHROME=/path/to/chrome, then run: dejevu --doctor"
        )
    print(
        f"  browser ready in {agent.setup_ms} ms · {len(agent.page['actions'])} elements on {agent.page['url'][:80]}", flush=True
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
            print(f"  {state['elapsed_ms']:>6} ms  {what:<34} model {decision.get('latency_ms', 0):>4} ms  {note}", flush=True)
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
    cost = f" · ${t['cost_usd']:.5f}" if t["cost_usd"] is not None else ""
    print(
        f"  {t['requests']} model requests ({t['stale']} stale, {t['invalid']} invalid) · "
        f"{t['actions']} actions ({t['waits']} waits) · "
        f"model {t['model_ms']} ms total, median {t['model_median_ms']} ms · "
        f"{t['input_tokens']} in / {t['output_tokens']} out tokens{cost} · {t['cdp_calls']} CDP calls"
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

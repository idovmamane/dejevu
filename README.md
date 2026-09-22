# dejevu

[![ci](https://github.com/idovmamane/dejevu/actions/workflows/ci.yml/badge.svg)](https://github.com/idovmamane/dejevu/actions/workflows/ci.yml) [![python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml) [![license MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Jev? Déjà vu.** Browser agents that run on instinct, no Jev needed. One look at the page. One call to any open model. One action.

Jev is the model everyone is talking about: TypeSafe's System One model that answers with a choice instead of text, in about 200 ms. browser-use built [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) on it and booked a Google Flights search in 7.1 seconds. dejevu does the same search in 5.6 seconds with a plain open model, 10 model calls instead of 17, and 5.6x fewer tokens. No special decision API. No second model for typing. No browser daemon. One API key.

![Google Flights, Zurich to London, one way, searched and verified in 6.07 s at 1x speed](docs/flights.gif)

Zurich to London on Google Flights, real time, 6.07 s from the first decision to verified results. Model: llama-3.3-70b on Groq.

![Wikipedia, open the Godel incompleteness theorems article in 1.5 s](docs/wikipedia.gif)

Wikipedia, from the main page to the exact article in 1.5 s. Two model calls. One typed action with Enter.

## Try it in 60 seconds

```bash
git clone https://github.com/idovmamane/dejevu.git && cd dejevu
uv sync
cp .env.example .env         # put your OPENROUTER_API_KEY in it
uv run dejevu --doctor       # checks Chrome, the key and one model call
uv run dejevu --task wikipedia
```

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), Google Chrome, and one API key. OpenRouter is the default, any OpenAI compatible endpoint works. The Wikipedia run takes about two seconds and costs a quarter of a cent.

## Jev versus dejevu on the same task

Google Flights: find one way flights from Zurich to London on a given Sunday, one adult, economy, stop when results are visible. Every run is checked by code on the final page, never by the model saying it is done. Median of the verified runs.

| Agent and model | Verified | Time | Model calls | Actions | Input tokens | Cost per run |
|---|---|---|---|---|---|---|
| **jev-ultrafast, Jev 1.13 + Mercury 2.5** (published) | 3 of 3 | 7.09 s | 17 | 13 | 84,650 | about $0.0036 at list price |
| **dejevu, llama-3.3-70b on Groq** | 3 of 3 | **5.63 s** | **10** | 9 | **15,071** | $0.0092 |
| dejevu, gpt-oss-120b on Cerebras | 1 of 2 | 7.92 s | 12 | 9 | 20,506 | $0.0083 |
| dejevu, gpt-oss-20b on Groq | 1 of 1 | 11.5 s | 14 | 12 | 23,189 | $0.0020 |
| dejevu, gemini-2.5-flash | 0 of 2 | stops too early | | | | $0.0046 |
| dejevu, gemini-2.5-flash-lite | 0 of 1 | stops too early | | | | $0.0016 |
| dejevu, qwen3-next-80b | 0 of 1 | stops too early | | | | $0.0024 |
| dejevu, deepseek-v3.1 | 0 of 2 | too slow, 3 s per call | | | | $0.0047 |
| dejevu, gpt-4.1-nano | 0 of 1 | loops | | | | $0.0009 |

Wikipedia: from the main page, find and open the article about Godel's incompleteness theorems. The check is the exact article URL.

| Agent and model | Verified | Time | Model calls | Actions | Input tokens | Cost per run |
|---|---|---|---|---|---|---|
| **jev-ultrafast, Jev 1.13** (published) | | 2.80 s | | | | |
| **dejevu, llama-3.3-70b on Groq** | 3 of 3 | **1.31 s** | 2 | 1 | 4,033 | $0.0024 |
| dejevu, gpt-oss-120b on Cerebras | 2 of 2 | 1.30 s | 2 | 1 | 4,084 | $0.0015 |
| dejevu, gemini-2.5-flash | 2 of 2 | 1.48 s | 2 | 1 | 4,212 | $0.0014 |
| dejevu, gemini-2.5-flash-lite | 2 of 2 | 1.63 s | 2 | 1 | 4,212 | $0.0004 |
| dejevu, gpt-oss-20b on Groq | 2 of 2 | 1.72 s | 2 | 1 | 4,102 | $0.0003 |
| dejevu, qwen3-next-80b | 2 of 2 | 2.69 s | 2 | 1 | 4,118 | $0.0007 |
| dejevu, deepseek-v3.1 | 2 of 2 | 3.83 s | 2 | 1 | 3,999 | $0.0006 |
| dejevu, gpt-4.1-nano | 0 of 2 | loops | | | | $0.0003 |

What this says:

- The harness is model agnostic. Seven of eight models finish the Wikipedia task in one typed action.
- The nine step Flights form separates models. Llama 3.3 70b on Groq is the one that passes every time. gpt-oss-120b passes some of the time. Smaller and cheaper models tend to declare victory inside the calendar.
- Jev is still the cheapest per token by far. dejevu sends 5.6x fewer tokens, but the fast open model routes cost 8x to 14x more per token, so the Flights run costs about 2.5x more than Jev at list price. On a self hosted or cheaper endpoint the token saving is the cost saving.
- Zero wasted calls. jev-ultrafast throws away 4 to 6 of its 17 calls per run because the page changed under them. dejevu waits for the page to settle before it asks.

Measured 2026-09-22 on a MacBook Pro M3 Pro, headless Chrome 153, models through OpenRouter. jev-ultrafast numbers are its own published measurements on its author's machine and Chrome profile. Their task date, September 20 2026, has passed, so this repo searches Sunday October 18 2026 with the same wording and the same checks. A fresh profile also meets Google's consent page first. The agent dismisses it by itself and the clock starts on the Flights page, the same boundary jev-ultrafast uses. Raw traces for every run are in `bench/final`.

## How it is faster

- **One request per page state, everything in it.** The model returns `{"op", "target", "text", "option", "key"}` as one JSON object. No speculative per operation heads. No separate text model.
- **Settle detection instead of fixed waits.** After every action the loop waits for the DOM to go quiet and for the requests the action started to finish, with a cap per action type. Typed text gets a longer window because suggestions arrive late. A closing modal dialog counts as not settled until its transition ends.
- **A lean page view.** One numbered line per interactive element, visible text only. On the same Wikipedia page the request is 5.6k characters where jev-ultrafast sends 13.5k.
- **Just off screen elements are listed** as "below the fold" and scrolled into view when chosen. A control under the fold costs no separate scroll decision.
- **Compound TYPE plus Enter** accepts an unambiguous top suggestion or submits a search box in one step.
- **Rejected answers are explained back** to the model in the next request, so a bad answer costs one retry, not a dead run. Clear intent is honoured: SELECT on a suggestion clicks it, CLICK with text on a field types it, an operation written as the JSON key is read.

## How it stays safe

- The model never emits selectors, coordinates or code. It names an element number. The page resolves the real DOM node, rechecks visibility, enabled state and geometry, and hit tests for overlays right before input.
- Every decision carries a guard: the element's identity, role, name, state and the text of its nearest small block must be unchanged, or the decision is dropped and the page is observed again.
- DONE is only accepted on a settled page. Browser mutations are never retried. Execution is logged before the next observation.
- Password, file and hidden inputs are never listed. The browser is a throwaway profile unless you attach your own.

## Coverage jev-ultrafast lists as out of scope

Open shadow roots and same origin frames are traversed. Their controls are listed, clicked and filled with correct frame offsets. `scripts/check_browser.py` proves it on a local page with no model calls.

## All the ways to run it

```bash
uv run dejevu --task flights --record artifacts/flights          # the benchmark, with a screencast
uv run dejevu --url https://example.com --goal "Open the pricing page"
uv run dejevu --preset balanced --task flights                    # another model route
uv run dejevu --model vendor/model --provider Provider --task wikipedia
uv run dejevu --help                                              # every option, with examples
```

`--preset fast|balanced|gemini|cheap` picks a route, `--model` and `--provider` override it, `--headed` shows the window, `--cdp-url http://127.0.0.1:9222` attaches to a Chrome you started with `--remote-debugging-port=9222` so it uses your logins. `--record DIR` saves a screencast and a trace, and `scripts/render_gif.py DIR out.gif` renders it at 1x with the elapsed time overlay. `--json out.json` writes the full trace and verification.

Measure your own model:

```bash
uv run python -m dejevu.measure --task flights --model your/model --provider YourProvider --runs 3 --out bench/final/flights-yours
uv run python scripts/results.py
```

## Use it as a library

```python
from dejevu import Agent

with Agent(
    "https://en.wikipedia.org/wiki/Main_Page",
    "Find and open the Wikipedia article about Godel's incompleteness theorems.",
) as agent:
    for state in agent.run():
        print(state["elapsed_ms"], state["status"])
    print(agent.page["url"])
```

`Agent` owns the browser. `Loop` drives any tab like object with any policy and is what the offline tests exercise. `TypeSafePolicy` reproduces the Jev arrangement, one operation head plus per operation target heads plus a text helper, so a head to head on one machine is one flag away: `--backend typesafe` with `TYPESAFE_API_KEY`. It is untested here because no TypeSafe key was available. If you have one, run it and open a PR with the numbers.

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest                              # 45 offline contract tests, no browser, no paid calls
uv run python scripts/check_browser.py     # 18 real browser checks, no model calls
node --check dejevu/snapshot.js
```

## Layout

| File | Job |
|---|---|
| `dejevu/agent.py` | the loop: observe, decide, validate, guard, act, settle, plus budgets, loop breakers and the trace |
| `dejevu/snapshot.js` | one in page read: elements across shadow roots and frames, visible text, guards, hit testing |
| `dejevu/browser.py` | one tab over CDP: settle, observe, freshness, execution, screencast |
| `dejevu/cdp.py` | launch or attach to Chrome, one websocket, events |
| `dejevu/state.py` | the page view the model sees and validation of its answer against what was observed |
| `dejevu/policy.py` | `LLMPolicy` for any chat endpoint and `TypeSafePolicy` for Jev |
| `dejevu/tasks.py` | reference tasks with independent checks |
| `dejevu/measure.py` | repeated runs written as comparable JSON |

## Contribute

The repo is small on purpose, about two thousand lines, and every claim in it has a trace behind it. The most useful things you can add:

- **A model row.** Measure a model we have not tried and send the numbers with the `bench/final` folder. A model that fails is a result too.
- **A Jev head to head.** If you have a TypeSafe key, `--backend typesafe` runs the Jev arrangement on the same machine as the open model. We have not been able to run it ourselves.
- **A new task** with an independent check, on a site that is not Google or Wikipedia.
- **A page where the reader misses a control.** Closed shadow roots, cross origin frames and canvas are known gaps.

[CONTRIBUTING.md](CONTRIBUTING.md) has the commands. Issues have templates for bugs, model results and task proposals. Discussions are open for everything else.

## Questions people ask

**Is it cheaper than Jev?** Per token, no. Jev bills $0.042 per million input tokens and the fast open model routes cost 8x to 14x more. dejevu sends 5.6x fewer tokens, so a Flights run costs about 2.5x Jev at list price. On a self hosted or cheaper endpoint the token saving is the cost saving.

**Why does my model fail the Flights task?** The nine step form separates models. The common failure is declaring DONE inside the calendar. Try `--preset fast`, then `--record` to watch what it did, then send the result.

**Can it use my logged in Chrome?** Yes. Start Chrome with `--remote-debugging-port=9222` and pass `--cdp-url http://127.0.0.1:9222`. Then the agent acts with your sessions, so only give it goals you trust.

**Why is there a consent page in the traces?** A fresh headless profile meets Google's consent page first. The agent dismisses it by itself and the clock starts on the Flights page.

**Does it work on Linux or Windows?** Linux yes, CI runs the browser checks on Ubuntu. Windows should work with Chrome installed, but it is not tested yet. A report either way is welcome.

## Limits

The DOM reader covers common HTML and ARIA controls, not the full accessible name algorithm. Closed shadow roots, cross origin frames, canvas, uploads and new tabs are not handled. Guards accept unrelated changes elsewhere on the page by design. A valid action can still be the wrong action, and the model decides: llama-3.3-70b types dates into date fields and gets away with it, smaller models stop early. Two websites and a local fixture do not establish general reliability. Three runs per cell is evidence of a difference, not a benchmark.

MIT license.

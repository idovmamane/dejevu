# dejevu

[![ci](https://github.com/idovmamane/dejevu/actions/workflows/ci.yml/badge.svg)](https://github.com/idovmamane/dejevu/actions/workflows/ci.yml) [![python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml) [![license MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Jev? Déjà vu.** Browser agents that run on instinct, no Jev needed. One look at the page. One call to any open model. One action.

Jev is TypeSafe's System One model: it answers with a choice instead of text, in about 200 ms. Browser Use built [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) on it and booked a Google Flights search in 7.1 s. dejevu does the same search in 5.6 s with plain llama-3.3-70b, 10 model calls instead of 17, 5.6x fewer tokens. No decision API, no second model for typing, no browser daemon, one API key.

![Google Flights, Zurich to London, one way, verified in 6.07 s at 1x speed](docs/flights.gif)

Google Flights, real time, 6.07 s from the first decision to verified results, llama-3.3-70b on Groq.

![Wikipedia, open the Godel incompleteness theorems article in 1.5 s](docs/wikipedia.gif)

Wikipedia, main page to the exact article in 1.5 s, two model calls, one typed action.

Side by side with the jev-ultrafast demo, clocks aligned, real speed: [docs/race.mp4](docs/race.mp4). Their half is `docs/demo.mp4` from [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast), copyright Browser Use, MIT license, cropped with a counter overlay and otherwise unmodified.

## Try it in 60 seconds

```bash
git clone https://github.com/idovmamane/dejevu.git && cd dejevu
uv sync
cp .env.example .env         # put your OPENROUTER_API_KEY in it
uv run dejevu --doctor       # checks Chrome, the key and one model call
uv run dejevu --task wikipedia
```

Needs Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), Google Chrome and one API key. OpenRouter is the default, any OpenAI compatible endpoint works. The Wikipedia run takes about two seconds and costs a quarter of a cent.

## Jev versus dejevu on the same task

Google Flights: one way flights from Zurich to London on a given Sunday, one adult, economy, stop when results are visible. Every run is checked by code on the final page, never by the model saying it is done. Median of the verified runs.

| Agent and model | Verified | Time | Model calls | Actions | Input tokens | Cost per run |
|---|---|---|---|---|---|---|
| **jev-ultrafast, Jev 1.13 + Mercury 2.5** (published) | 3 of 3 | 7.09 s | 17 | 13 | 84,650 | about $0.0036 at list price |
| **dejevu, llama-3.3-70b on Groq** | 3 of 3 | **5.63 s** | **10** | 9 | **15,071** | $0.0092 |
| dejevu, gpt-oss-120b on Cerebras | 1 of 2 | 7.92 s | 12 | 9 | 20,506 | $0.0083 |
| dejevu, llama-3.3-70b on DeepInfra | 2 of 2 | 37.5 s | 12 | 10 | 18,490 | **$0.0020** |
| dejevu, gpt-oss-20b on Groq | 1 of 4 | 11.5 s | 14 | 12 | 23,189 | $0.0020 |
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

Hold out tasks, added after the harness was tuned and never used to adjust it. Three models, two runs each, all 18 verified. Median time.

| Task | llama-3.3-70b on Groq | gpt-oss-120b on Cerebras | gemini-2.5-flash |
|---|---|---|---|
| Selenium test form: text, textarea, native dropdown, checkbox, submit | 2.57 s, 6 calls | 3.37 s, 6 calls | 4.57 s, 6 calls |
| Python docs: find and open the asyncio.gather page | 2.11 s, 3 calls | 3.64 s, 4 calls | 2.49 s, 3 calls |
| Wikipedia: the article about the inventor of the World Wide Web | 1.33 s, 2 calls | 1.27 s, 2 calls | 4.23 s, 4 calls |

What this says:

- **The harness is model agnostic.** Seven of eight models finish Wikipedia in one typed action, three models pass all hold out tasks. The nine step Flights form is what separates models: llama-3.3-70b on Groq passes every time, gpt-oss-120b some of the time, smaller models declare victory inside the calendar.
- **Jev is cheaper per token, dejevu sends fewer tokens.** Groq, the fastest route, charges $0.59 per million, so a Flights run costs about 2.5x Jev at list price. Break even is a provider at $0.24 per million. The same model on DeepInfra passed 2 of 2 at $0.0020 per run, cheaper than Jev, but took 37 s. Speed and price are a provider choice, the token count is the design.
- **Zero wasted calls.** jev-ultrafast discards 4 to 6 of its 17 calls per run because the page changed under them. dejevu waits for the page to settle before it asks.

Measured 2026-09-22 on a MacBook Pro M3 Pro, headless Chrome 153, models through OpenRouter. jev-ultrafast's numbers are its own published measurements on its author's machine. Their task date, September 20 2026, has passed, so this repo searches Sunday October 18 2026 with the same wording and checks. A fresh profile meets Google's consent page first, the agent dismisses it and the clock starts on the Flights page, the same boundary jev-ultrafast uses. Traces for every run: `bench/final` and `bench/holdout`.

## How it is faster

- **One request per page state.** The model returns `{"op", "target", "text", "option", "key"}` as one JSON object. No per operation heads, no separate text model.
- **Settle detection instead of fixed waits.** After every action the loop waits for the DOM to go quiet and for the requests the action started to finish, capped per action type. A closing modal counts as not settled until its transition ends.
- **A lean page view.** One line per interactive element, visible text only. On the same Wikipedia page the request is 5.6k characters where jev-ultrafast sends 13.5k.
- **Off screen elements are listed** as "below the fold" and scrolled into view when chosen, so no separate scroll decision.
- **TYPE plus Enter** accepts an unambiguous top suggestion or submits a search box in one step.
- **Bad answers are explained back** to the model, so they cost one retry, not a dead run. Clear intent is honoured: SELECT on a suggestion clicks it, CLICK with text on a field types it.

## How it stays safe

- The model never emits selectors, coordinates or code. It names an element number, the page resolves the real node, rechecks visibility, state and geometry, and hit tests for overlays right before input.
- Every decision carries a guard: identity, role, name, state and nearby text must be unchanged, or the decision is dropped and the page is read again. DONE is only accepted on a settled page. Browser mutations are never retried.
- Password, file and hidden inputs are never listed. The browser is a throwaway profile unless you attach your own.
- Open shadow roots and same origin frames are traversed, which jev-ultrafast lists as out of scope. `scripts/check_browser.py` proves it on a local page with no model calls.

## More ways to run it

```bash
uv run dejevu --task flights --record artifacts/flights          # the benchmark, with a screencast
uv run dejevu --url https://example.com --goal "Open the pricing page"
uv run dejevu --model vendor/model --provider Provider --task wikipedia
uv run dejevu --cdp-url http://127.0.0.1:9222 --task wikipedia   # your own Chrome, started with --remote-debugging-port=9222
uv run python -m dejevu.measure --task flights --runs 3 --out bench/final/flights-yours
uv run dejevu --help
```

As a library:

```python
from dejevu import Agent

with Agent(
    "https://en.wikipedia.org/wiki/Main_Page", "Find and open the article about Godel's incompleteness theorems."
) as agent:
    for state in agent.run():
        print(state["elapsed_ms"], state["status"])
    print(agent.page["url"])
```

`--backend typesafe` with `TYPESAFE_API_KEY` runs the Jev arrangement, one operation head plus target heads plus a text helper, so a head to head on one machine is one flag away. It is untested here, no TypeSafe key was available.

## Contribute

Every claim in this repo has a trace behind it. The most useful things to add, in order: a model row with its `bench/final` folder (a model that fails is a result too), a Jev head to head if you have a key, a new task with an independent check on a site that is not Google or Wikipedia, a page where the reader misses a control. [CONTRIBUTING.md](CONTRIBUTING.md) has the commands, issues have templates, discussions are open.

## Limits

The DOM reader covers common HTML and ARIA controls, not the full accessible name algorithm. Closed shadow roots, cross origin frames, canvas, uploads and new tabs are not handled. Guards accept unrelated changes elsewhere on the page by design. The harness was tuned while watching llama-3.3-70b on the two reference tasks, other models were measured, not tuned for. Linux is covered by CI, Windows is untested. A valid action can still be the wrong action, and two runs per cell is evidence of a difference, not a benchmark.

MIT license.

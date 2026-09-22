# Contributing to dejevu

Thanks for helping. The most useful contributions, in order:

1. **A model result.** Run a task on a model we have not measured and send the numbers with the trace.
2. **A Jev head to head.** If you have a TypeSafe key, run `--backend typesafe` on the same machine as `--preset fast` and send both.
3. **A new reference task** with an independent check, on a site that is not Google or Wikipedia.
4. **Site coverage**: a page where the element reader misses a control, with a minimal reproduction.
5. Bug reports with a trace.

## Set up

```bash
git clone https://github.com/idovmamane/dejevu.git
cd dejevu
uv sync
cp .env.example .env      # add OPENROUTER_API_KEY, or any OpenAI compatible endpoint
uv run dejevu --doctor    # Chrome, key and one model call
```

Needs Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), Google Chrome, and Node for the JavaScript syntax check.

## Before you open a pull request

```bash
uv run ruff check . && uv run ruff format .
uv run pytest                              # offline contract tests, no browser, no paid calls
uv run python scripts/check_browser.py     # real browser checks, no model calls
node --check dejevu/snapshot.js
```

All four run in CI. Tests must stay offline: no browser, no network, no paid API. Browser behaviour is checked by `scripts/check_browser.py` against a local page.

## Add a model result

```bash
uv run python -m dejevu.measure --task flights --model vendor/model --provider Provider --runs 3 --out bench/final/flights-yourslug
uv run python -m dejevu.measure --task wikipedia --model vendor/model --provider Provider --runs 2 --out bench/final/wikipedia-yourslug
uv run python scripts/results.py
```

Then add a row to the README tables with the median of the verified runs, and commit the `bench/final/*-yourslug` folder (the per run JSON is the evidence). Run measurements one at a time: two batches in parallel stall the first model call by 20 to 40 seconds and corrupt the timings. A model that fails a task is a result too. Say how it failed in the row (stops early, loops, too slow).

## Add a task

Add a `Task` to `dejevu/tasks.py`: a start URL, a goal in plain language, a `verify(page)` that reads the final page and returns `{"passed": bool, "checks": {...}}`, and optionally `clock_from(page)` to start the clock on the right page. The check must not trust the model's DONE. Add a test in `tests/test_contract.py` that feeds `verify` a good page and a broken one.

## Add a preset

Presets live in `dejevu/config.py`. A preset is a model id, an optional pinned provider, and any settings the model needs (reasoning off or low, a bigger `max_tokens` for models that reason). Measure it before proposing it as a default.

## What we will not merge

- Site specific rules or hardcoded field values in the policy or the prompt. The input is one goal in plain language.
- Anything that lets model output become a selector, a coordinate or executable code.
- Retries of browser mutations. A click that may or may not have happened is never retried by code.
- Timing claims without a `bench/final` folder behind them.

## Layout

| File | Job |
|---|---|
| `dejevu/agent.py` | the loop: observe, decide, validate, guard, act, settle, plus budgets, loop breakers and the trace |
| `dejevu/snapshot.js` | one in page read: elements across shadow roots and frames, visible text, guards, hit testing |
| `dejevu/browser.py` | one tab over CDP: settle, observe, freshness, execution, screencast |
| `dejevu/cdp.py` | launch or attach to Chrome, one websocket, events |
| `dejevu/state.py` | the page view the model sees and validation of its answer against what was observed |
| `dejevu/policy.py` | `LLMPolicy` for any chat endpoint and `TypeSafePolicy` for Jev |
| `dejevu/tasks.py` | reference and hold out tasks with independent checks |
| `dejevu/measure.py` | repeated runs written as comparable JSON |

## Style

Ruff at 130 columns, formatted with `ruff format`. Comments explain why, not what. Keep the loop small: page, elements, one decision, one action.

## Reporting a security problem

See [SECURITY.md](SECURITY.md).

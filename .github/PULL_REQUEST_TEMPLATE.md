## What this changes

## Why

## Checks

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run pytest` (offline, no paid calls)
- [ ] `uv run python scripts/check_browser.py`
- [ ] Timing or model claims come with a `bench/final` folder
- [ ] No site specific rules, no hardcoded field values, no retried browser mutations

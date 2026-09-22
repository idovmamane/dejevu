"""Environment and presets. One key is enough; everything else has a default."""

import os
from pathlib import Path

from .policy import LLMPolicy, TypeSafePolicy

PRESETS = {
    # Medians on a real 1.7k-token step prompt, 3 runs each, 2026-09-22 (artifacts/route-probe.json).
    # ~270 ms, $0.59/M input on Groq, no logprobs. The default: speed is what a per-step decision needs most.
    "fast": {"model": "meta-llama/llama-3.3-70b-instruct", "provider": "Groq", "logprobs": False},
    # ~320 ms, $0.35/M on Cerebras; reasoning must stay low and the budget large enough for it.
    "balanced": {
        "model": "openai/gpt-oss-120b",
        "provider": "Cerebras",
        "logprobs": False,
        "reasoning": "low",
        "max_tokens": 600,
    },
    # ~450 ms, $0.10/M, no logprobs.
    "gemini": {"model": "google/gemini-2.5-flash-lite", "provider": None, "logprobs": False, "reasoning": "off"},
    # 600-850 ms on the best gemma routes, $0.09/M, token logprobs give target probabilities for free.
    "cheap": {"model": "google/gemma-4-26b-a4b-it", "provider": "NextBit", "logprobs": True},
}
DEFAULT_PRESET = "fast"


def load_env():
    """Read .env from the working directory and its parents (first definition wins; the environment wins over files)."""
    seen = set()
    for base in [
        Path.cwd(),
        *Path.cwd().parents,
        Path(__file__).resolve().parents[1],
        Path(__file__).resolve().parents[2],
    ]:
        path = base / ".env"
        if path in seen or not path.exists():
            continue
        seen.add(path)
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_key():
    return os.environ.get("DEJEVU_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("okey")


def make_policy(*, backend=None, preset=None, model=None, provider=None, logprobs=None, reasoning=None, base_url=None, key=None):
    load_env()
    backend = backend or os.environ.get("DEJEVU_BACKEND", "llm")
    if backend == "typesafe":
        text = PRESETS[preset or os.environ.get("DEJEVU_PRESET", DEFAULT_PRESET)]
        typesafe_key = os.environ.get("TYPESAFE_API_KEY")
        if not typesafe_key:
            raise PolicyConfigError("TYPESAFE_API_KEY is required for the typesafe backend")
        return TypeSafePolicy(
            api_key=typesafe_key,
            model=os.environ.get("TYPESAFE_MODEL", "jev-latest"),
            text_model=model or os.environ.get("DEJEVU_TEXT_MODEL", text["model"]),
            text_api_key=key or api_key(),
            text_base_url=base_url or os.environ.get("DEJEVU_BASE_URL", "https://openrouter.ai/api/v1"),
        )
    chosen = dict(PRESETS[preset or os.environ.get("DEJEVU_PRESET", DEFAULT_PRESET)])
    if model or os.environ.get("DEJEVU_MODEL"):
        chosen = {
            "model": model or os.environ.get("DEJEVU_MODEL"),
            "provider": provider or os.environ.get("DEJEVU_PROVIDER"),
            "logprobs": False,
        }
    if provider is not None:
        chosen["provider"] = provider or None
    if logprobs is not None:
        chosen["logprobs"] = logprobs
    elif os.environ.get("DEJEVU_LOGPROBS"):
        chosen["logprobs"] = os.environ["DEJEVU_LOGPROBS"] not in ("0", "false", "no")
    if reasoning is not None:
        chosen["reasoning"] = reasoning
    key = key or api_key()
    if not key:
        raise PolicyConfigError("Set OPENROUTER_API_KEY (or DEJEVU_API_KEY for another OpenAI-compatible endpoint)")
    return LLMPolicy(
        model=chosen["model"],
        api_key=key,
        base_url=base_url or os.environ.get("DEJEVU_BASE_URL", "https://openrouter.ai/api/v1"),
        provider=chosen.get("provider"),
        logprobs=chosen.get("logprobs", False),
        reasoning=chosen.get("reasoning"),
        max_tokens=chosen.get("max_tokens", 600 if chosen.get("reasoning") in ("low", "medium") else 160),
    )


class PolicyConfigError(RuntimeError):
    pass

"""Policies turn an observation into one Decision.

LLMPolicy: any OpenAI-compatible chat endpoint, one request per step, the choice and the text in the same answer.
TypeSafePolicy: Jev's System One heads (the jev-ultrafast design) plus a text helper, for head-to-head comparison.
"""

import json
import math
import re
import time

import httpx

from .prompts import SYSTEM, TEXT_HELPER
from .state import available_ops, render
from .types import ALIASES, OPS, Decision, PolicyError


class AnswerError(PolicyError):
    """The answer could not be read. The loop treats it like any other unusable answer and asks again."""


RETRY_STATUS = {429, 500, 502, 503, 529}


def post_json(client, url, body):
    """A decision request has no side effect, so transport retries are safe. Nothing is executed on failure."""
    for attempt in range(3):
        try:
            response = client.post(url, json=body)
        except httpx.HTTPError as e:
            raise PolicyError(f"model connection failed ({type(e).__name__}); no action executed") from None
        if response.status_code in RETRY_STATUS and attempt < 2:
            time.sleep(0.3 * 2**attempt)
            continue
        if response.is_error:
            raise PolicyError(f"model provider returned HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        if isinstance(data, dict) and data.get("error") and not data.get("choices"):
            raise PolicyError(f"model provider error: {str(data['error'])[:200]}")
        return data
    raise PolicyError("model unavailable; no action executed")


def parse_answer(content):
    s = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content.strip())
    try:
        value = json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        if start < 0:
            raise AnswerError("answer is not a JSON object; no action executed") from None
        try:
            value, _ = json.JSONDecoder().raw_decode(s[start:])  # the first complete object; trailing chatter is ignored
        except json.JSONDecodeError:
            raise AnswerError("answer is not valid JSON; no action executed") from None
    if not isinstance(value, dict):
        raise AnswerError("answer is not a JSON object; no action executed")
    return value


def to_int(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, str):
        m = re.search(r"\d+", x)
        return int(m.group()) if m else None
    return None


def normalize(value):
    op = str(value.get("op") or value.get("operation") or value.get("action") or "").strip().upper()
    op = ALIASES.get(op.replace(" ", "_").replace("-", "_"), op.replace(" ", "_").replace("-", "_"))
    target = to_int(value.get("target", value.get("element", value.get("index"))))
    if not op:  # some models put the operation in the key: {"CLICK": 18}
        for key, item in value.items():
            candidate = key.strip().upper().replace(" ", "_").replace("-", "_")
            candidate = ALIASES.get(candidate, candidate)
            if candidate in OPS:
                op = candidate
                if target is None:
                    target = to_int(item)
                break
    text = value.get("text")
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        text = str(text)
    if not isinstance(text, str):
        text = None
    key = value.get("key")
    key = (
        {"enter": "Enter", "return": "Enter", "escape": "Escape", "esc": "Escape"}.get(str(key).strip().lower()) if key else None
    )
    return Decision(op=op, target=target, text=text, option=to_int(value.get("option")), key=key)


def target_probabilities(content, logprobs, target):
    """Alternatives the model weighed for the target number, read from the token logprobs of that position."""
    if target is None:
        return {}
    m = re.search(r'"target"\s*:\s*(\d+)', content)
    if not m:
        return {}
    start = m.start(1)
    position = 0
    for token in logprobs:
        piece = token.get("token") or ""
        end = position + len(piece)
        if position <= start < end:
            weights = {}
            for alt in token.get("top_logprobs") or []:
                s = (alt.get("token") or "").strip()
                if s.isdigit():
                    weights[int(s)] = weights.get(int(s), 0.0) + math.exp(alt["logprob"])
            total = sum(weights.values())
            return {k: round(v / total, 4) for k, v in sorted(weights.items(), key=lambda kv: -kv[1])} if total else {}
        position = end
    return {}


class LLMPolicy:
    def __init__(
        self,
        *,
        model,
        api_key,
        base_url="https://openrouter.ai/api/v1",
        provider=None,
        fallbacks=True,
        logprobs=False,
        reasoning=None,
        temperature=0.0,
        max_tokens=160,
        timeout=30.0,
        text_chars=4000,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.fallbacks = fallbacks
        self.logprobs = logprobs
        self.reasoning = reasoning
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.text_chars = text_chars
        self.openrouter = "openrouter.ai" in self.base_url
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "X-Title": "jevless"}
        self.client = httpx.Client(http2=True, timeout=httpx.Timeout(timeout, connect=10.0), headers=headers)

    @property
    def name(self):
        return self.model + (f"@{self.provider}" if self.provider else "")

    def body(self, goal, page, history, note=None):
        user = render(goal, page, history, text_chars=self.text_chars, note=note)
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self.openrouter:
            body["usage"] = {"include": True}
            if self.provider:
                body["provider"] = {"order": [self.provider], "allow_fallbacks": self.fallbacks}
        if self.reasoning == "off":
            body["reasoning"] = {"enabled": False}
        elif self.reasoning:
            body["reasoning"] = {"effort": self.reasoning}
        if self.logprobs:
            body.update(logprobs=True, top_logprobs=8)
        return body, user

    def decide(self, goal, page, history, note=None):
        body, user = self.body(goal, page, history, note)
        started = time.perf_counter()
        result = post_json(self.client, self.base_url + "/chat/completions", body)
        latency = round((time.perf_counter() - started) * 1000)
        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if not content.strip():
            hint = " (it spent the budget on reasoning; set reasoning off)" if message.get("reasoning") else ""
            raise AnswerError("model returned no answer" + hint)
        decision = normalize(parse_answer(content))
        usage = result.get("usage") or {}
        decision.latency_ms = latency
        decision.usage = usage
        decision.cost = usage.get("cost") if isinstance(usage.get("cost"), (int, float)) else None
        decision.model = result.get("model") or self.model
        decision.provider = result.get("provider")
        decision.raw = content
        decision.request_chars = len(user) + len(SYSTEM)
        tokens = (choice.get("logprobs") or {}).get("content")
        if tokens:
            decision.probabilities = target_probabilities(content, tokens, decision.target)
            decision.confidence = decision.probabilities.get(decision.target)
        return decision


class TypeSafePolicy:
    """The original arrangement: Jev picks an operation and a per-operation target in one System One request;
    an OpenAI-compatible text model writes the value when the operation is TYPE."""

    URL = "https://api.typesafe.ai/v1/systemone"
    OPERATIONS = {
        "CLICK": "Click an element, button, link, menu option, autocomplete suggestion, or calendar day.",
        "TYPE": "Enter or replace text in an editable field. A text model supplies the value from the goal.",
        "SELECT": "Choose an observed option in a native dropdown.",
        "PRESS_ENTER": "Press Enter to submit the focused field.",
        "PRESS_ESCAPE": "Press Escape to close a menu or dialog.",
        "SCROLL_DOWN": "Scroll down to reveal more of the page.",
        "SCROLL_UP": "Scroll up.",
        "WAIT": "Wait briefly because the page is visibly loading or a needed control has not appeared.",
        "DONE": "Every requirement of the goal is visibly satisfied.",
        "BLOCKED": "No supported operation can make progress.",
    }

    def __init__(
        self,
        *,
        api_key,
        model="jev-latest",
        text_model,
        text_api_key,
        text_base_url="https://openrouter.ai/api/v1",
        timeout=25.0,
    ):
        self.model = model
        self.text_model = text_model
        self.text_base_url = text_base_url.rstrip("/")
        self.client = httpx.Client(http2=True, timeout=timeout, headers={"Authorization": f"Bearer {api_key}"})
        self.text_client = httpx.Client(http2=True, timeout=timeout, headers={"Authorization": f"Bearer {text_api_key}"})

    @property
    def name(self):
        return f"{self.model}+{self.text_model}"

    def questions(self, goal, page):
        ops = available_ops(page)
        offered = []
        for op in ops:
            offered += ["PRESS_ENTER", "PRESS_ESCAPE"] if op == "PRESS" else [op]
        rules = SYSTEM.split("Rules:", 1)[1].strip()
        questions = {
            "operation": {
                "type": "choice",
                "criteria": {op: self.OPERATIONS[op] for op in offered},
                "instructions": {"goal": goal, "rules": rules},
            }
        }
        heads = {
            "CLICK": [a for a in page["actions"] if a["kind"] in ("click", "fill")],
            "TYPE": [a for a in page["actions"] if a["kind"] == "fill"],
        }
        for op, elements in heads.items():
            if op in ops and elements:
                questions[op.lower() + "_target"] = {
                    "type": "choice",
                    "criteria": {
                        str(a["id"]): {
                            "element": f"[{a['id']}] {a['role']} {a['label']}",
                            "current_value": a.get("value", ""),
                            **{k: a[k] for k in ("checked", "expanded", "selected") if k in a},
                        }
                        for a in elements
                    },
                    "instructions": {
                        "goal": goal,
                        "operation": op,
                        "rules": rules,
                        "note": "This question only picks a target for that operation; another question picks the operation.",
                    },
                }
        selects = [a for a in page["actions"] if a["kind"] == "select"]
        if "SELECT" in ops and selects:
            questions["select_target"] = {
                "type": "choice",
                "criteria": {
                    f"{a['id']}:{o['i']}": f"[{a['id']}] {a['label']} → {o['label']}" for a in selects for o in a["options"]
                },
                "instructions": {"goal": goal, "operation": "SELECT", "rules": rules},
            }
        return questions

    def decide(self, goal, page, history, note=None):
        questions = self.questions(goal, page)
        state = {
            "page": {"url": page["url"], "title": page["title"], "text": page["text"][:4000]},
            "elements": [
                {
                    k: a.get(k)
                    for k in ("id", "role", "label", "value", "editable", "checked", "expanded", "selected")
                    if a.get(k) is not None
                }
                for a in page["actions"]
            ],
            "recent_actions": [{k: h.get(k) for k in ("op", "label", "text", "page_changed")} for h in history[-10:]],
        }
        body = {"model": self.model, "state": state, "questions": questions}
        started = time.perf_counter()
        result = post_json(self.client, self.URL, body)
        latency = round((time.perf_counter() - started) * 1000)
        answers = result.get("answers") or {}
        op_answer = answers.get("operation") or {}
        op = op_answer.get("choice")
        if op not in questions["operation"]["criteria"]:
            raise PolicyError("TypeSafe returned an operation that was not offered; no action executed")
        decision = Decision(op=op, confidence=op_answer.get("confidence"))
        if op in ("PRESS_ENTER", "PRESS_ESCAPE"):
            decision.op, decision.key = "PRESS", op.split("_")[1].capitalize()
        elif op in ("CLICK", "TYPE", "SELECT"):
            head = answers.get(op.lower() + "_target") or {}
            chosen = head.get("choice")
            if chosen not in questions.get(op.lower() + "_target", {}).get("criteria", {}):
                raise PolicyError("TypeSafe target was not an offered element; no action executed")
            probabilities = head.get("probabilities") or {}
            if op == "SELECT":
                element, option = chosen.split(":")
                decision.target, decision.option = int(element), int(option)
            else:
                decision.target = int(chosen)
            decision.probabilities = {k: round(v, 4) for k, v in probabilities.items()}
            decision.confidence = head.get("confidence")
        usage = result.get("usage") or {}
        decision.usage, decision.model, decision.latency_ms = usage, result.get("model", self.model), latency
        if decision.op == "TYPE":
            element = next(a for a in page["actions"] if a["id"] == decision.target)
            decision.text, helper = self.field_text(goal, element, page, history)
            decision.latency_ms += helper["latency_ms"]
            decision.usage = {"jev": usage, "text": helper["usage"]}
        return decision

    def field_text(self, goal, element, page, history):
        context = {
            "goal": goal,
            "field": {k: element.get(k) for k in ("label", "role", "value")},
            "page": {"title": page["title"], "text": page["text"][:4000]},
            "recent_actions": [{k: h.get(k) for k in ("op", "label", "text")} for h in history[-6:]],
        }
        body = {
            "model": self.text_model,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": TEXT_HELPER}, {"role": "user", "content": json.dumps(context)}],
        }
        started = time.perf_counter()
        result = post_json(self.text_client, self.text_base_url + "/chat/completions", body)
        try:
            output = json.loads(result["choices"][0]["message"]["content"])
            value = output["text"]
            if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise PolicyError("text helper returned no valid field value; nothing typed") from None
        return value, {"latency_ms": round((time.perf_counter() - started) * 1000), "usage": result.get("usage", {})}

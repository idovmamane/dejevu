"""The loop: observe → decide → guard → act → settle. One request per observed state; nothing executes on a stale page."""

import base64
import json
import statistics
import time
from pathlib import Path

from .browser import StalePage, Tab
from .cdp import Chrome
from .policy import AnswerError
from .state import validate
from .types import PolicyError

FINISHED = {"done", "blocked", "error"}


class Loop:
    """Drives any tab-like object (observe / fresh / act) with any policy (decide). Testable offline."""

    def __init__(
        self,
        tab,
        policy,
        goal,
        *,
        max_actions=40,
        max_requests=80,
        screenshots=False,
        record_dir=None,
        clock_from=None,
        first_page=None,
    ):
        self.goal = goal.strip() if isinstance(goal, str) else "\n".join(goals for goals in goal).strip()
        if not self.goal:
            raise ValueError("Supply a goal")
        self.tab = tab
        self.policy = policy
        self.max_actions = max_actions
        self.max_requests = max_requests
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)
        # The clock starts at the first decision on a page this accepts (default: the first decision).
        self.clock_from = clock_from or (lambda page: True)
        self.history = []
        self.decisions = []
        self.status = "ready"
        self.reason = None
        self.started = None
        self.elapsed_ms = 0
        self.stale = 0
        self.invalid = 0
        self._invalid_streak = 0
        self.note = None  # why the previous answer was rejected, shown to the model once
        self._deferred = 0  # DONE/BLOCKED verdicts deferred while the page was still loading
        self._stale_streak = 0
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
        self.page = first_page if first_page is not None else tab.observe(screenshot=self.screenshots)
        self._record(0)
        self.started_wall = None
        if self.record_dir and hasattr(tab, "start_screencast"):
            tab.start_screencast()

    def _elapsed(self):
        return round((time.perf_counter() - self.started) * 1000) if self.started else 0

    def _stop(self, status, reason=None):
        self.status, self.reason = status, reason
        self.elapsed_ms = self._elapsed()
        if self.record_dir and getattr(self.tab, "frames", None) is not None:
            self.save_screencast()

    def save_screencast(self):
        """Write frames/NNNNNN.jpg plus frames.json (Chrome capture timestamps, clock start) for scripts/render_gif.py."""
        frames = self.tab.stop_screencast()
        folder = self.record_dir / "frames"
        folder.mkdir(parents=True, exist_ok=True)
        index = []
        for i, (stamp, data) in enumerate(frames):
            name = f"{i:06d}.jpg"
            (folder / name).write_bytes(base64.b64decode(data))
            index.append({"file": name, "timestamp": stamp})
        (self.record_dir / "frames.json").write_text(
            json.dumps(
                {
                    "frames": index,
                    "clock_started_at": self.started_wall,
                    "finished_at": time.time(),
                    "status": self.status,
                    "elapsed_ms": self.elapsed_ms,
                },
                indent=1,
            )
        )

    def _record(self, stamp):
        if self.record_dir and self.page.get("screenshot"):
            (self.record_dir / f"{stamp:06d}.jpg").write_bytes(base64.b64decode(self.page["screenshot"]))

    def _reobserve(self):
        self.page = self.tab.observe(screenshot=self.screenshots)
        self.elapsed_ms = self._elapsed()

    def step(self):
        if self.status in FINISHED:
            raise RuntimeError("This run has finished; start a new one")
        page = self.page
        if self.started is None and self.clock_from(page):
            self.started = time.perf_counter()
            self.started_wall = time.time()
        if len(self.decisions) >= self.max_requests:
            self._stop("blocked", f"reached the {self.max_requests}-request budget")
            return self.snapshot()
        try:
            decision = self.policy.decide(self.goal, page, self.history, note=self.note)
        except AnswerError as e:
            self.decisions.append(
                {
                    "op": "",
                    "valid": False,
                    "outcome": f"invalid: {e}",
                    "latency_ms": 0,
                    "usage": {},
                    "elapsed_ms": self._elapsed(),
                    "fingerprint": page["fingerprint"],
                }
            )
            self.note = f"your previous answer could not be read: {e}. Reply with one JSON object only."
            self.invalid += 1
            self._invalid_streak += 1
            if self._invalid_streak >= 3:
                self._stop("blocked", f"three unusable answers in a row; last: {e}")
            return self.snapshot()
        except PolicyError as e:
            self._stop("error", str(e))
            return self.snapshot()
        record = {
            **decision.as_dict(),
            "fingerprint": page["fingerprint"],
            "elapsed_ms": self._elapsed(),
            "valid": True,
            "outcome": None,
        }
        record["raw"] = (decision.raw or "")[:300]
        self.decisions.append(record)
        try:
            action = validate(decision, page)
        except PolicyError as e:
            record.update(valid=False, outcome=f"invalid: {e}")
            self.note = f"your previous answer {decision.raw[:160]} was rejected: {e}. Answer differently."
            self.invalid += 1
            self._invalid_streak += 1
            if self._invalid_streak >= 3:
                self._stop("blocked", f"three unusable answers in a row; last: {e}")
            return self.snapshot()
        self._invalid_streak = 0
        self.note = None
        if action is not None:
            self._deferred = 0
        if action is None:  # DONE or BLOCKED: only on a page that is still exactly what was judged
            since = getattr(self.tab, "acted_at", None)
            if self._deferred < 2 and getattr(self.tab, "pending", lambda since=None: 0)(since=since):
                self._deferred += 1
                # The page is still loading what the model is judging: let it finish, then ask again.
                record["outcome"] = "premature: requests in flight"
                self.stale += 1
                self.tab.settle("idle")
                self._reobserve()
                return self.snapshot()
            if not self.tab.fresh(page):
                record["outcome"] = "stale"
                self.stale += 1
                self._reobserve()
                return self.snapshot()
            record["outcome"] = "executed"
            self._stop("done" if decision.op == "DONE" else "blocked", "model's call")
            return self.snapshot()
        if len(self.history) >= self.max_actions:
            self._stop("blocked", f"reached the {self.max_actions}-action budget")
            return self.snapshot()
        try:
            self.tab.act(action, page, text=decision.text)
        except StalePage as e:
            record["outcome"] = f"stale: {e}"
            self.stale += 1
            self._stale_streak += 1
            if self._stale_streak >= 2:
                self.note = (
                    f"your previous answer {decision.raw[:120]} could not be executed: {e}. "
                    "Choose a different element or operation."
                )
            if self._stale_streak >= 8:
                self._stop("blocked", "the page kept changing under eight decisions in a row")
                return self.snapshot()
            self._reobserve()
            return self.snapshot()
        record["outcome"] = "executed"
        self._stale_streak = 0
        # Log the action before observing its result: a navigation during observation must not erase it.
        entry = {
            "step": len(self.history) + 1,
            "op": action["op"],
            "kind": action["kind"],
            "label": action["label"],
            "target": decision.target,
            "text": decision.text,
            "option": decision.option,
            "key": decision.key,
            "confidence": decision.confidence,
            "latency_ms": decision.latency_ms,
            "url": page["url"],
            "executed_ms": self._elapsed(),
            "page_changed": None,
            "elapsed_ms": None,
        }
        self.history.append(entry)
        self._reobserve()
        entry.update(
            page_changed=self.page["fingerprint"] != page["fingerprint"],
            url=self.page["url"],
            elapsed_ms=self.elapsed_ms,
        )
        self._record(self.elapsed_ms)
        signature = (entry["op"], entry["label"], entry["text"])
        if entry["kind"] != "wait" and sum(1 for h in self.history[-6:] if (h["op"], h["label"], h["text"]) == signature) >= 4:
            self._stop("blocked", f"looping: {entry['op']} {entry['label']!r} repeated four times in six actions")
        recent = self.history[-3:]
        if len(recent) == 3 and all(h["page_changed"] is False and h["kind"] != "wait" for h in recent):
            self._stop("blocked", "no visible progress in three actions")
        return self.snapshot()

    def run(self):
        while self.status not in FINISHED:
            yield self.step()

    def totals(self):
        latencies = [d["latency_ms"] for d in self.decisions]
        usage = [d.get("usage") or {} for d in self.decisions]
        costs = [d.get("cost") for d in self.decisions if isinstance(d.get("cost"), (int, float))]
        return {
            "requests": len(self.decisions),
            "actions": len(self.history),
            "waits": sum(1 for h in self.history if h["kind"] == "wait"),
            "stale": self.stale,
            "invalid": self.invalid,
            "model_ms": sum(latencies),
            "model_median_ms": round(statistics.median(latencies)) if latencies else 0,
            "input_tokens": sum(u.get("prompt_tokens") or 0 for u in usage),
            "output_tokens": sum(u.get("completion_tokens") or 0 for u in usage),
            "cost_usd": round(sum(costs), 6) if costs else None,
            "request_chars": sum(d.get("request_chars") or 0 for d in self.decisions),
            "cdp_calls": getattr(getattr(self.tab, "chrome", None), "calls", None),
        }

    def snapshot(self):
        return {
            "goal": self.goal,
            "policy": getattr(self.policy, "name", type(self.policy).__name__),
            "status": self.status,
            "reason": self.reason,
            "elapsed_ms": self.elapsed_ms if self.status in FINISHED else self._elapsed(),
            "url": self.page["url"],
            "title": self.page["title"],
            "elements": len(self.page["actions"]),
            "history": self.history,
            "decisions": self.decisions,
            "totals": self.totals(),
        }


class Agent(Loop):
    """A Loop that owns its browser: a private headless Chrome by default, or an existing one via cdp_url."""

    def __init__(self, url, goal, *, policy=None, headless=True, cdp_url=None, viewport=(1120, 780), **options):
        started = time.perf_counter()
        self.chrome = Chrome(headless=headless, cdp_url=cdp_url, window=viewport)
        try:
            tab = Tab(self.chrome, url, viewport)
            if policy is None:
                from .config import make_policy

                policy = make_policy()
            super().__init__(tab, policy, goal, **options)
        except Exception:
            self.chrome.close()
            raise
        self.setup_ms = round((time.perf_counter() - started) * 1000)

    def close(self):
        try:
            self.tab.close()
        except Exception:
            pass
        self.chrome.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

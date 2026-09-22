"""One tab over one CDP session: settle, observe, guard, act. Model output never reaches the page as code."""

import hashlib
import json
import sys
import time
from pathlib import Path

from .cdp import CDPError, Chrome, ContextDestroyed

SNAPSHOT = Path(__file__).with_name("snapshot.js").read_text()
MARKER = "(() => { const s = " + SNAPSHOT + "; return s ? s.marker : null; })()"
# Requests whose completion can change what the model sees. Images, fonts, media and sockets are not waited for.
IDLE_TYPES = {"Document", "XHR", "Fetch", "Script", "Preflight", "Other"}
SETTLE = {
    "quiet_ms": 60,  # no relevant DOM mutation for this long counts as settled
    "quiet_fill_ms": 120,  # typed text often triggers suggestions after a short delay
    "probe_ms": 150,  # one in-page wait at a time, so navigations are noticed quickly
    "cap_ms": {
        "idle": 3000,  # a DONE/BLOCKED verdict waits this long for in-flight requests to finish
        "initial": 1500,
        "navigate": 1500,
        "click": 300,
        "fill": 450,
        "select": 300,
        "press": 400,
        "scroll": 200,
        "wait": 250,
    },
    "network_ms": 1500,  # one extension while a page-changing request started by the action is still in flight
    "stale_request_s": 2.5,  # requests older than this (long polls, analytics) never block
}
QUIET = """(new Promise((resolve) => {{
  const quiet = {quiet}, cap = {cap};
  if (document.readyState === 'loading') {{ setTimeout(() => resolve(false), Math.min(cap, 40)); return; }}
  // While a modal dialog is on screen, a finite transition still running (the dialog closing) is not a settled page.
  // Ordinary menu animations are not waited for, and infinite ones (spinners, shimmers) never count.
  const modal = () => [...document.querySelectorAll('[aria-modal="true"],dialog[open]')]
    .some((d) => {{ const r = d.getBoundingClientRect(); return r.width > 0 && r.height > 0; }});
  const animating = () => modal() && document.getAnimations().some((a) => {{
    if (a.playState !== 'running') return false;
    const t = a.effect && a.effect.getTiming ? a.effect.getTiming() : null;
    return !t || (t.iterations !== Infinity && (t.duration === 'auto' || t.duration <= 2000));
  }});
  let timer = null, done = false;
  const finish = (ok) => {{ if (done) return; done = true; observer.disconnect(); resolve(ok); }};
  const settled = () => {{ if (animating()) {{ timer = setTimeout(settled, 40); return; }} finish(true); }};
  const observer = new MutationObserver(() => {{ clearTimeout(timer); timer = setTimeout(settled, quiet); }});
  observer.observe(document.documentElement, {{ subtree: true, childList: true, characterData: true, attributes: true,
    attributeFilter: ['value', 'aria-expanded', 'aria-selected', 'aria-checked', 'aria-hidden',
      'aria-busy', 'hidden', 'disabled', 'open', 'class'] }});
  timer = setTimeout(settled, quiet);
  setTimeout(() => finish(false), cap);
}}))"""


class StalePage(ValueError):
    """A decision no longer describes the page in front of us."""


def fingerprint(page):
    content = {"url": page["url"], "text": page["text"], "scroll": page["scroll"]}
    content["actions"] = [{k: v for k, v in a.items() if k != "rect"} for a in page["actions"]]
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


class Tab:
    def __init__(self, chrome: Chrome, url, viewport=(1120, 780)):
        self.chrome = chrome
        self.inflight = {}
        self.nav_epoch = 0
        self.dom_ready = True
        self.loaded = True
        self.after = "initial"
        self.acted_at = time.monotonic()
        self.frames = None  # [(chrome timestamp, jpeg base64)] while a screencast runs
        self.target = chrome.call("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = chrome.call("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        chrome.listeners[self.session] = self._event
        self.call("Page.enable")
        self.call("Network.enable")
        self.call(
            "Emulation.setDeviceMetricsOverride",
            width=viewport[0],
            height=viewport[1],
            deviceScaleFactor=1,
            mobile=False,
        )
        # Keep animation frames and menus running in an unfocused/background tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.navigate(url)

    def start_screencast(self, max_width=1120, max_height=780, quality=60):
        self.frames = []
        self.call(
            "Page.startScreencast", format="jpeg", quality=quality, maxWidth=max_width, maxHeight=max_height, everyNthFrame=1
        )

    def stop_screencast(self):
        frames, self.frames = self.frames, None
        try:
            self.call("Page.stopScreencast")
        except CDPError:
            pass
        return frames or []

    def _event(self, method, p):
        if method == "Page.screencastFrame":
            if self.frames is not None:
                self.frames.append((p.get("metadata", {}).get("timestamp"), p["data"]))
            try:
                self.call("Page.screencastFrameAck", sessionId=p["sessionId"])
            except CDPError:
                pass
            return
        if method == "Network.requestWillBeSent":
            if p.get("type") in IDLE_TYPES:
                self.inflight[p["requestId"]] = time.monotonic()
        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            self.inflight.pop(p["requestId"], None)
        elif method == "Page.frameNavigated" and not p.get("frame", {}).get("parentId"):
            self.nav_epoch += 1
            self.dom_ready = False
            self.loaded = False
            self.inflight.clear()
        elif method == "Page.domContentEventFired":
            self.dom_ready = True
        elif method == "Page.loadEventFired":
            self.loaded = True

    def pending(self, since=None):
        """Page-changing requests in flight, ignoring long-lived ones; with `since`, only those started after it."""
        now = time.monotonic()
        floor = since if since is not None else now - SETTLE["stale_request_s"]
        return sum(1 for t in self.inflight.values() if t >= floor and now - t < SETTLE["stale_request_s"])

    def call(self, method, **params):
        return self.chrome.call(method, session=self.session, **params)

    def evaluate(self, expression, *, await_promise=False, timeout=15.0):
        try:
            r = self.chrome.call(
                "Runtime.evaluate",
                session=self.session,
                timeout=timeout,
                expression=expression,
                returnByValue=True,
                awaitPromise=await_promise,
            )
        except CDPError as e:
            msg = str(e)
            if any(s in msg for s in ("context was destroyed", "Cannot find context", "navigated or closed", "Inspected target")):
                raise ContextDestroyed(msg) from None
            raise
        details = r.get("exceptionDetails")
        if details:
            text = details.get("text", "") + " " + json.dumps(details.get("exception", {}))[:300]
            if "context" in text.lower():
                raise ContextDestroyed(text)
            raise CDPError("page script failed: " + text)
        return r.get("result", {}).get("value")

    def navigate(self, url):
        self.dom_ready = False
        self.loaded = False
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while not self.loaded and time.monotonic() < deadline:
            self.chrome.pump(max_ms=50)
        self.after = "initial"

    def _await_navigation(self, cap=5.0):
        deadline = time.monotonic() + cap
        while not self.dom_ready and time.monotonic() < deadline:
            self.chrome.pump(max_ms=50)
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState") != "loading":
                    return
            except ContextDestroyed:
                pass
            time.sleep(0.02)

    def settle(self, kind="click"):
        """Return once relevant DOM mutations have stopped and no page-changing request is in flight, or at the cap."""
        quiet = SETTLE["quiet_fill_ms"] if kind == "fill" else SETTLE["quiet_ms"]
        cap = SETTLE["cap_ms"].get(kind, 300) / 1000
        t0 = time.monotonic()
        epoch = self.nav_epoch
        extended = False
        while True:
            remaining = cap - (time.monotonic() - t0)
            if remaining <= 0:
                # The action started a request that is still loading: wait for it once rather than ask about a half-loaded page.
                if not extended and self.pending(since=self.acted_at):
                    extended = True
                    cap = SETTLE["network_ms"] / 1000
                    t0 = time.monotonic()
                    continue
                return False
            probe = int(min(remaining, SETTLE["probe_ms"] / 1000) * 1000)
            try:
                quiet_now = self.evaluate(
                    QUIET.format(quiet=quiet, cap=max(probe, quiet + 5)), await_promise=True, timeout=probe / 1000 + 3
                )
            except (ContextDestroyed, CDPError):
                self._await_navigation()
                cap = SETTLE["cap_ms"]["navigate"] / 1000
                t0 = time.monotonic()
                epoch = self.nav_epoch
                continue
            self.chrome.pump()
            if self.nav_epoch != epoch:
                epoch = self.nav_epoch
                self._await_navigation()
                cap = SETTLE["cap_ms"]["navigate"] / 1000
                t0 = time.monotonic()
                continue
            if quiet_now and not self.pending():
                # A request fired by the action often starts a beat after the DOM goes quiet: give it 60 ms to show up.
                self.chrome.pump(max_ms=60)
                if not self.pending(since=self.acted_at):
                    return True

    def observe(self, screenshot=False):
        self.settle(self.after or "initial")
        self.after = None
        for _ in range(10):
            try:
                page = self.evaluate(SNAPSHOT, timeout=10)
            except (ContextDestroyed, CDPError):
                self._await_navigation()
                self.settle("navigate")
                continue
            if page is None:
                time.sleep(0.03)
                continue
            page["fingerprint"] = fingerprint(page)
            page["epoch"] = self.nav_epoch
            if screenshot:
                page["screenshot"] = self.screenshot()
            return page
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        try:
            if action is not None and action.get("node") is not None:
                node = action["node"]
                if type(node) is not int:
                    return False
                current = self.evaluate(
                    "(() => { const c = window.__dejevu; return c ? [c.pageKey(), c.guard(c.nodes.get(%d))] : null; })()" % node
                )
                return current == [page["page_key"], page["guards"].get(str(node))]
            return self.evaluate(MARKER) == page["marker"]
        except ContextDestroyed:
            return False

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision")
        kind = action["kind"]
        if kind == "wait":
            time.sleep(0.1)
        elif kind == "scroll":
            self.call(
                "Input.dispatchMouseEvent",
                type="mouseWheel",
                x=page["w"] // 2,
                y=int(page["h"] * 0.6),
                deltaX=0,
                deltaY=action["delta"],
            )
        elif kind == "press":
            self.press(action["key"])
        else:
            node = action["node"]
            if type(node) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node ids name observed elements; the page resolves them to current geometry and hit-tests occlusion.
            try:
                point = self.evaluate(
                    "window.__dejevu ? window.__dejevu.point(%d, %s, %s, %s) : null"
                    % (node, json.dumps(kind), json.dumps(action.get("value")), json.dumps(action.get("index")))
                )
            except ContextDestroyed:
                if kind == "select":
                    raise RuntimeError(
                        "Dropdown change interrupted; its change event may have fired. Inspect before retrying."
                    ) from None
                raise StalePage("Document changed during execution") from None
            if point is None:
                if kind == "select":
                    raise RuntimeError("Dropdown change was not confirmed; inspect before retrying.")
                raise StalePage("Target moved, hid or is covered")
            if kind != "select":
                x, y = point["x"], point["y"]
                self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
                self.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
                self.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
                if kind == "fill":
                    modifiers = 4 if sys.platform == "darwin" else 2
                    self.call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=modifiers,
                        commands=["selectAll"],
                    )
                    self.call("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=modifiers)
                    self.call("Input.insertText", text=text or "")
                    if action.get("key") == "Enter":
                        self.press("Enter")
        self.after = "press" if action.get("key") == "Enter" else kind
        self.acted_at = time.monotonic()

    def press(self, key):
        code, vk, text = {"Enter": ("Enter", 13, "\r"), "Escape": ("Escape", 27, None)}[key]
        down = dict(type="keyDown", key=key, code=code, windowsVirtualKeyCode=vk, nativeVirtualKeyCode=vk)
        if text:
            down.update(text=text, unmodifiedText=text)
        self.call("Input.dispatchKeyEvent", **down)
        self.call(
            "Input.dispatchKeyEvent",
            type="keyUp",
            key=key,
            code=code,
            windowsVirtualKeyCode=vk,
            nativeVirtualKeyCode=vk,
        )

    def screenshot(self):
        return self.call("Page.captureScreenshot", format="jpeg", quality=60)["data"]

    def close(self):
        if self.target:
            try:
                self.chrome.call("Target.closeTarget", targetId=self.target)
            except CDPError:
                pass
            self.chrome.listeners.pop(self.session, None)
            self.target = None

"""Minimal Chrome DevTools Protocol client: launch a private Chrome or attach to one, one socket, flat sessions."""

import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


class CDPError(RuntimeError):
    pass


class ContextDestroyed(CDPError):
    """An evaluation lost its execution context: the page navigated or the frame went away."""


CHROME_CANDIDATES = {
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ],
    "Linux": [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "microsoft-edge",
    ],
    "Windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
}


def find_chrome():
    explicit = os.environ.get("JEVLESS_CHROME") or os.environ.get("CHROME_PATH")
    if explicit:
        return explicit
    for candidate in CHROME_CANDIDATES.get(platform.system(), []):
        found = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if found:
            return found
    raise FileNotFoundError("No Chrome/Chromium found; set JEVLESS_CHROME=/path/to/chrome")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Chrome:
    """A Chrome we own (fresh temp profile, headless by default) or an existing one we attach to via JEVLESS_CDP_URL."""

    def __init__(self, *, headless=True, cdp_url=None, profile=None, window=(1120, 780), extra_args=()):
        self.proc = None
        self.profile_dir = None
        self._own_profile = False
        self.calls = 0
        self.listeners = {}  # sessionId -> callable(method, params)
        self.responses = {}  # replies that arrived while a nested call was waiting
        cdp_url = cdp_url or os.environ.get("JEVLESS_CDP_URL")
        if cdp_url:
            self.http = cdp_url.rstrip("/")
        else:
            port = free_port()
            self.profile_dir = Path(profile) if profile else Path(tempfile.mkdtemp(prefix="jevless-profile-"))
            self._own_profile = profile is None
            args = [
                find_chrome(),
                f"--remote-debugging-port={port}",
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disable-features=Translate,MediaRouter",
                "--lang=en-US",
                f"--window-size={window[0]},{window[1]}",
            ]
            if headless:
                args.append("--headless=new")
            args += list(extra_args) + ["about:blank"]
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.http = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 20
        while True:
            try:
                info = json.load(urllib.request.urlopen(self.http + "/json/version", timeout=1))
                break
            except Exception:
                if self.proc and self.proc.poll() is not None:
                    raise CDPError("Chrome exited during startup") from None
                if time.monotonic() > deadline:
                    raise CDPError(f"Chrome did not answer at {self.http}") from None
                time.sleep(0.05)
        self.version = info.get("Browser", "")
        self.ws = connect(info["webSocketDebuggerUrl"], max_size=None)
        self._n = 0

    def call(self, method, session=None, timeout=20.0, **params):
        self._n += 1
        self.calls += 1
        mid = self._n
        msg = {"id": mid, "method": method, "params": params}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))
        deadline = time.monotonic() + timeout
        while True:
            if mid in self.responses:
                m = self.responses.pop(mid)
                if "error" in m:
                    raise CDPError(f"{method}: {m['error'].get('message', m['error'])}")
                return m.get("result", {})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CDPError(f"{method}: no response within {timeout}s")
            try:
                m = json.loads(self.ws.recv(timeout=remaining))
            except TimeoutError:
                raise CDPError(f"{method}: no response within {timeout}s") from None
            if m.get("id") == mid:
                if "error" in m:
                    raise CDPError(f"{method}: {m['error'].get('message', m['error'])}")
                return m.get("result", {})
            if "id" in m:
                self.responses[m["id"]] = m
            elif "method" in m:
                self._dispatch(m)

    def pump(self, max_ms=0):
        """Deliver queued events. With max_ms > 0, keep listening that long."""
        deadline = time.monotonic() + max_ms / 1000
        while True:
            wait = max(0.0, deadline - time.monotonic()) if max_ms else 0
            try:
                m = json.loads(self.ws.recv(timeout=wait))
            except TimeoutError:
                return
            if "method" in m:
                self._dispatch(m)
            if max_ms and time.monotonic() >= deadline:
                return

    def _dispatch(self, m):
        fn = self.listeners.get(m.get("sessionId"))
        if fn:
            fn(m["method"], m.get("params", {}))

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._own_profile and self.profile_dir:
            shutil.rmtree(self.profile_dir, ignore_errors=True)

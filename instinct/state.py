"""What the model sees (one compact page view) and what it may answer (validated against the observed action space)."""

import re

from .types import KEYS, PolicyError

KIND_OF = {
    "CLICK": "click",
    "TYPE": "fill",
    "SELECT": "select",
    "PRESS": "press",
    "SCROLL_DOWN": "scroll",
    "SCROLL_UP": "scroll",
    "WAIT": "wait",
}


def clip(value, n):
    s = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def available_ops(page):
    ops = ["CLICK"] if page["actions"] else []
    if any(a["kind"] == "fill" for a in page["actions"]):
        ops.append("TYPE")
    if any(a["kind"] == "select" for a in page["actions"]):
        ops.append("SELECT")
    ops.append("PRESS")
    scroll = page["scroll"]
    if scroll["y"] + page["h"] < scroll["height"] - 2:
        ops.append("SCROLL_DOWN")
    if scroll["y"] > 0:
        ops.append("SCROLL_UP")
    return ops + ["WAIT", "DONE", "BLOCKED"]


def element_line(a):
    parts = [f'[{a["id"]}] {a["role"]} "{clip(a["label"], 90)}"']
    if a["kind"] == "select":
        parts.append(f'= "{clip(a.get("value"), 60)}"')
        parts.append("options: " + " ".join(f'{o["i"]}:"{clip(o["label"], 40)}"' for o in a.get("options", [])[:40]))
    elif a.get("editable"):
        parts.append(f'= "{clip(a.get("value"), 60)}" (editable)')
    elif a.get("value"):
        parts.append(f'= "{clip(a["value"], 60)}"')
    if a.get("offscreen"):
        parts.append("(below the fold)" if a["offscreen"] == "below" else "(above, scrolled past)")
    for flag in ("checked", "expanded", "selected", "pressed"):
        if flag in a:
            parts.append(f"[{flag}]" if a[flag] else f"[not {flag}]")
    return " ".join(parts)


def history_line(h):
    line = f"{h['step']}. {h['op']}"
    if h.get("kind") in ("click", "fill", "select"):
        line += f" [{clip(h.get('label'), 60)}]"
    if h.get("text") is not None:
        line += f' text="{clip(h["text"], 40)}"'
    if h.get("option") is not None:
        line += f" option {h['option']}"
    if h.get("key"):
        line += f" {h['key']}"
    if h.get("page_changed") is True:
        line += " → page changed"
    elif h.get("page_changed") is False:
        line += " → no visible change"
    return line


def render(goal, page, history, *, text_chars=4000, history_n=8, note=None):
    scroll = page["scroll"]
    below = max(0, scroll["height"] - scroll["y"] - page["h"])
    lines = [f"GOAL: {goal}", "", f"PAGE: {clip(page['title'], 120)}", f"URL: {clip(page['url'], 200)}"]
    if scroll["y"] > 0 or below > 0:
        lines.append(f"SCROLL: {scroll['y']}px down, {below}px more below")
    count = len(page["actions"])
    more = f", {page['omitted']} more not listed" if page.get("omitted") else ""
    lines += ["", f"ELEMENTS ({count} visible{more}):"]
    lines += [element_line(a) for a in page["actions"]] or ["(none)"]
    text = page["text"][:text_chars]
    lines += ["", "VISIBLE TEXT:", text if text.strip() else "(none)"]
    if history:
        recent = history[-history_n:]
        lines += ["", f"YOUR LAST {len(recent)} ACTIONS:"] + [history_line(h) for h in recent]
    if note:
        lines += ["", f"NOTE: {note}"]
    lines += ["", "AVAILABLE OPERATIONS: " + ", ".join(available_ops(page)), "Answer with one JSON object."]
    return "\n".join(lines)


def validate(decision, page):
    """Turn a decision into an executable action, or raise PolicyError. DONE/BLOCKED return None."""
    ops = available_ops(page)
    op = decision.op
    element = next((a for a in page["actions"] if a["id"] == decision.target), None)
    if not op:  # the answer named a target, maybe text, but no operation: take the obvious reading
        if element is not None and element["kind"] == "fill" and decision.text is not None:
            op = "TYPE"
        elif element is not None:
            op = "CLICK"
        elif decision.key in KEYS:
            op = "PRESS"
    # Models read comboboxes as dropdowns: "SELECT [field] option N" means click suggestion N (or the field itself).
    # And a native dropdown asked for with CLICK plus an option number is a SELECT.
    if op == "SELECT" and element is not None and element["kind"] != "select":
        suggestion = next((a for a in page["actions"] if a["id"] == decision.option and a["kind"] == "click"), None)
        if suggestion is None and element["kind"] == "click":
            suggestion = element
        if suggestion is None:
            raise PolicyError(f"element [{element['id']}] is not a dropdown; CLICK the suggestion you want")
        op, element = "CLICK", suggestion
    elif op == "CLICK" and element is not None and element["kind"] == "select" and decision.option is not None:
        op = "SELECT"
    # CLICK with a text value on an editable field means TYPE; TYPE without text on a clickable element means CLICK.
    if op == "CLICK" and element is not None and element["kind"] == "fill" and decision.text:
        op = "TYPE"
    elif op == "TYPE" and element is not None and element["kind"] == "click" and decision.text is None:
        op = "CLICK"
    if op not in ops:
        raise PolicyError(f"operation {op!r} is not available here; offered: {', '.join(ops)}")
    if op in ("DONE", "BLOCKED"):
        return None
    action = {"kind": KIND_OF[op], "op": op, "node": None, "id": None, "label": op}
    if op in ("CLICK", "TYPE", "SELECT"):
        if element is None:
            raise PolicyError(f"target {decision.target!r} is not an offered element number")
        if op == "TYPE" and element["kind"] != "fill":
            raise PolicyError(f"element [{element['id']}] is not editable")
        if op == "TYPE" and decision.text is None:
            raise PolicyError("TYPE needs a text value")
        if op == "TYPE" and len(decision.text) > 2000:
            raise PolicyError("text is too long")
        if op == "CLICK" and element["kind"] == "select":
            raise PolicyError(f"element [{element['id']}] is a dropdown; use SELECT with an option number")
        if op == "SELECT":
            if element["kind"] != "select":
                raise PolicyError(f"element [{element['id']}] is not a dropdown")
            option = next((o for o in element.get("options", []) if o["i"] == decision.option), None)
            if option is None:
                raise PolicyError(f"option {decision.option!r} is not offered for element [{element['id']}]")
            action.update(value=option["value"], index=option["i"], option_label=option["label"])
        action.update(node=element["node"], id=element["id"], label=element["label"])
        if op == "TYPE" and decision.key == "Enter":
            action.update(key="Enter", label=element["label"] + " + Enter")
    elif op == "PRESS":
        if decision.key not in KEYS:
            raise PolicyError(f"PRESS needs key in {KEYS}")
        action.update(key=decision.key, label=f"key {decision.key}")
    elif op in ("SCROLL_DOWN", "SCROLL_UP"):
        step = int(page["h"] * 0.7)
        action.update(delta=step if op == "SCROLL_DOWN" else -step, label=op.replace("_", " ").lower())
    else:
        action.update(label="wait")
    return action

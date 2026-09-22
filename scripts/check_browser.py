"""Local browser checks: guards, occlusion, shadow DOM, same-origin frames, autocomplete settle, navigation. No model calls."""

import time
from urllib.parse import quote

from instinct.browser import StalePage, Tab
from instinct.cdp import Chrome

HTML = """<!doctype html><title>Guard checks</title>
<style>body{margin:30px;font:16px sans-serif}button{width:180px;height:50px}#outside{position:absolute;top:3000px}</style>
<p id="context">Cart total: $10</p>
<button id="target" onclick="window.clicks=(window.clicks||0)+1">Continue</button>
<label>City<input id="field" value="Zurich"></label>
<label><input id="toggle" type="checkbox">Refundable</label>
<select aria-label="Category"><option>All</option><option>Design</option><option disabled>Unavailable</option></select>
<input id="secret" type="password" value="never expose this">
<button id="off" disabled>Disabled</button>
<div id="host"></div>
<iframe id="frame" style="width:400px;height:120px"
  srcdoc="<label>Card number<input id='card'></label><button id='pay' onclick='window.paid=1'>Pay now</button>"></iframe>
<label>Search <input id="query" role="combobox" aria-controls="suggestions"></label>
<div role="listbox" id="suggestions"></div>
<p id="outside">Unrelated offscreen text</p>
<script>
  const root = document.getElementById('host').attachShadow({mode: 'open'});
  root.innerHTML = '<button id="shadowed" onclick="window.shadowClicks=(window.shadowClicks||0)+1">Shadow button</button>';
  document.getElementById('query').addEventListener('input', () => setTimeout(() => {
    document.getElementById('suggestions').innerHTML = '<div role="option">Generated suggestion</div>';
  }, 90));
</script>"""


def find(page, label):
    return next(a for a in page["actions"] if a["label"] == label)


def main():
    chrome = Chrome(headless=True)
    passed = []
    try:
        tab = Tab(chrome, "data:text/html," + quote(HTML))
        page = tab.observe()
        labels = [a["label"] for a in page["actions"]]
        assert "Shadow button" in labels, labels
        assert "Card number" in labels and "Pay now" in labels, labels
        assert not any(a.get("value") == "never expose this" for a in page["actions"])
        assert "Disabled" not in labels
        passed.append("snapshot lists shadow DOM and same-origin frame controls, hides password and disabled ones")

        select = find(page, "Category")
        assert select["kind"] == "select" and [o["label"] for o in select["options"]] == ["All", "Design"]
        assert find(page, "Refundable")["kind"] == "click" and find(page, "City")["kind"] == "fill"
        passed.append("native controls expose only supported operations and enabled options")

        continue_button = find(page, "Continue")
        tab.evaluate("document.querySelector('#target').style.transform='translateX(200px)'")
        assert tab.fresh(page, continue_button), "movement should use fresh geometry, not another model call"
        tab.act(continue_button, page)
        assert tab.evaluate("window.clicks") == 1
        passed.append("moving target clicked at its current location")

        page = tab.observe()
        tab.evaluate("document.querySelector('#outside').textContent='Updated outside the viewport'")
        assert tab.fresh(page, find(page, "Continue"))
        passed.append("unrelated offscreen text does not invalidate a click")

        for label, expression in {
            "visible context": "document.querySelector('#context').textContent='Cart total: $100'",
            "accessible label": "document.querySelector('#target').setAttribute('aria-label','Delete account')",
            "field value": "document.querySelector('#field').value='London'",
            "checkbox state": "document.querySelector('#toggle').checked=true",
            "disabled target": "document.querySelector('#target').disabled=true",
            "hidden target": "document.querySelector('#target').style.display='none'",
            "replaced node": "document.querySelector('#target').outerHTML=document.querySelector('#target').outerHTML",
        }.items():
            tab.evaluate(
                "(() => { const t=document.querySelector('#target'); t.style.display='block'; t.disabled=false; "
                "t.removeAttribute('aria-label'); document.querySelector('#field').value='Zurich'; "
                "document.querySelector('#toggle').checked=false; })()"
            )
            page = tab.observe()
            action = find(page, "Continue")
            tab.evaluate(expression)
            assert not tab.fresh(page, action), label
            passed.append(f"{label} invalidates the decision")

        tab.evaluate(
            "(() => { const t=document.querySelector('#target'); t.style.display='block'; t.disabled=false; "
            "t.removeAttribute('aria-label'); })()"
        )
        page = tab.observe()
        action = find(page, "Continue")
        tab.evaluate(
            "(() => { const c=document.createElement('div'); "
            "c.style.cssText='position:fixed;inset:0;z-index:9999;background:white'; document.body.append(c); })()"
        )
        assert tab.fresh(page, action), "a textless overlay is not a semantic change"
        try:
            tab.act(action, page)
        except StalePage:
            pass
        else:
            raise AssertionError("covered target was clicked")
        assert tab.evaluate("window.clicks") == 1
        tab.evaluate("document.body.lastElementChild.remove()")
        passed.append("overlay blocks the click before any input")

        page = tab.observe()
        tab.act(find(page, "Shadow button"), page)
        assert tab.evaluate("window.shadowClicks") == 1
        passed.append("shadow DOM button clicked through the host")

        page = tab.observe()
        tab.act(find(page, "Card number"), page, text="4242")
        assert tab.evaluate("document.querySelector('#frame').contentDocument.querySelector('#card').value") == "4242"
        page = tab.observe()
        tab.act(find(page, "Pay now"), page)
        assert tab.evaluate("document.querySelector('#frame').contentWindow.paid") == 1
        passed.append("same-origin frame field filled and button clicked with frame offsets")

        page = tab.observe()
        select = find(page, "Category")
        tab.act({"kind": "select", "node": select["node"], "value": "Design", "index": 2}, page)
        assert tab.evaluate("document.querySelector('select').value") == "Design"
        passed.append("native dropdown set to an observed option")

        page = tab.observe()
        started = time.perf_counter()
        tab.act(find(page, "Search"), page, text="Generated")
        page = tab.observe()
        waited = round((time.perf_counter() - started) * 1000)
        assert tab.evaluate("document.querySelector('#query').value") == "Generated"
        assert any(a["role"] == "option" for a in page["actions"]), "suggestion should be visible after settle"
        assert waited < 450, waited
        passed.append(f"typing waits for the asynchronous suggestion ({waited} ms), not a fixed delay")

        tab.act(find(page, "City"), page, text="Geneva")
        assert tab.evaluate("document.querySelector('#field').value") == "Geneva"
        passed.append("typing replaces existing field contents")

        page = tab.observe()
        field = find(page, "City")
        tab.call("Page.navigate", url="about:blank")
        time.sleep(0.2)
        assert not tab.fresh(page, field)
        passed.append("navigation invalidates the old document")
        tab.close()
    finally:
        chrome.close()
    print("\n".join(passed))
    print(f"PASS: {len(passed)} browser checks; no model calls")


if __name__ == "__main__":
    main()

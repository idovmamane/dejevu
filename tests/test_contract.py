"""Offline contracts: encoding, validation, stale handling, budgets, probability parsing. No browser, no paid APIs."""

import json
from unittest.mock import Mock

import pytest

from dejevu.agent import Loop
from dejevu.browser import StalePage, fingerprint
from dejevu.policy import LLMPolicy, normalize, parse_answer, target_probabilities
from dejevu.state import available_ops, render, validate
from dejevu.tasks import FLIGHT_DATE, verify_flights
from dejevu.types import Decision, PolicyError


def page(**overrides):
    p = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search the catalogue",
        "w": 1120,
        "h": 780,
        "scroll": {"y": 0, "height": 2000},
        "omitted": 0,
        "actions": [
            {
                "id": 1,
                "node": 10,
                "role": "searchbox",
                "label": "Search",
                "value": "",
                "kind": "fill",
                "editable": True,
            },
            {"id": 2, "node": 20, "role": "button", "label": "Go", "value": "", "kind": "click"},
            {
                "id": 3,
                "node": 30,
                "role": "checkbox",
                "label": "Free cancellation",
                "value": "",
                "kind": "click",
                "checked": True,
            },
            {
                "id": 4,
                "node": 40,
                "role": "select",
                "label": "Category",
                "value": "All",
                "kind": "select",
                "options": [
                    {"i": 1, "label": "All", "value": "all", "selected": True},
                    {"i": 2, "label": "Design", "value": "design", "selected": False},
                ],
            },
        ],
        "marker": ["m"],
        "page_key": ["k"],
        "guards": {"10": ["g10"], "20": ["g20"], "30": ["g30"], "40": ["g40"]},
    }
    p.update(overrides)
    p["fingerprint"] = fingerprint(p)
    return p


def test_render_is_compact_and_lists_every_element_once():
    view = render("Find a book", page(), [])
    assert '[1] searchbox "Search" = "" (editable)' in view
    assert '[3] checkbox "Free cancellation" [checked]' in view
    assert '[4] select "Category" = "All" options: 1:"All" 2:"Design"' in view
    assert "AVAILABLE OPERATIONS: CLICK, TYPE, SELECT, PRESS, SCROLL_DOWN, WAIT, DONE, BLOCKED" in view
    assert len(view) < 1200


def test_available_ops_follow_the_page():
    p = page(
        scroll={"y": 100, "height": 500},
        actions=[{"id": 1, "node": 1, "role": "button", "label": "Go", "kind": "click"}],
    )
    assert available_ops(p) == ["CLICK", "PRESS", "SCROLL_UP", "WAIT", "DONE", "BLOCKED"]


@pytest.mark.parametrize(
    "decision, message",
    [
        (Decision(op="CLICK", target=99), "not an offered element"),
        (Decision(op="TYPE", target=2, text="x"), "not editable"),
        (Decision(op="TYPE", target=1), "needs a text value"),
        (Decision(op="CLICK", target=4), "use SELECT"),
        (Decision(op="SELECT", target=4, option=7), "not offered"),
        (Decision(op="SELECT", target=1, option=99), "CLICK the suggestion"),
        (Decision(op="PRESS", key="F5"), "PRESS needs key"),
        (Decision(op="SCROLL_UP"), "not available"),
        (Decision(op="JUMP"), "not available"),
    ],
)
def test_invalid_decisions_are_rejected_before_execution(decision, message):
    with pytest.raises(PolicyError, match=message):
        validate(decision, page())


def test_valid_decisions_resolve_to_observed_nodes():
    assert validate(Decision(op="CLICK", target=2), page())["node"] == 20
    fill = validate(Decision(op="TYPE", target=1, text="Zurich"), page())
    assert (fill["kind"], fill["node"]) == ("fill", 10)
    select = validate(Decision(op="SELECT", target=4, option=2), page())
    assert (select["value"], select["index"]) == ("design", 2)
    assert validate(Decision(op="DONE"), page()) is None
    assert validate(Decision(op="SCROLL_DOWN"), page())["delta"] > 0


@pytest.mark.parametrize(
    "content, expected",
    [
        ('{"op": "CLICK", "target": 2}', ("CLICK", 2, None)),
        ('```json\n{"operation": "type_text", "target": "1", "text": "Zurich"}\n```', ("TYPE", 1, "Zurich")),
        ('Sure: {"op":"press","key":"enter"}', ("PRESS", None, None)),
        ('{"op": "select option", "target": 4, "option": 2.0}', ("SELECT", 4, None)),
    ],
)
def test_answers_are_parsed_and_normalized(content, expected):
    d = normalize(parse_answer(content))
    assert (d.op, d.target, d.text) == expected


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"op": "CLICK"} {"op": "DONE"}', ""])
def test_unparseable_answers_execute_nothing(content):
    if content.startswith('{"op": "CLICK"}'):
        assert normalize(parse_answer(content)).op == "CLICK"  # first object wins; validation still applies
        return
    with pytest.raises(PolicyError):
        parse_answer(content)


def test_target_probabilities_come_from_the_target_token():
    content = '{"op": "CLICK", "target": 12, "text": null}'
    tokens = [{"token": t, "logprob": -0.1, "top_logprobs": []} for t in ['{"', "op", '": "', "CLICK", '", "', "target", '": ']]
    tokens.append(
        {
            "token": "12",
            "logprob": -0.2,
            "top_logprobs": [
                {"token": "12", "logprob": -0.2},
                {"token": "7", "logprob": -1.8},
                {"token": '"', "logprob": -9},
            ],
        }
    )
    tokens.append({"token": ', "text": null}', "logprob": -0.1, "top_logprobs": []})
    probabilities = target_probabilities(content, tokens, 12)
    assert list(probabilities) == [12, 7]
    assert abs(sum(probabilities.values()) - 1) < 0.01
    assert target_probabilities(content, tokens, None) == {}


def test_llm_policy_sends_one_request_and_reads_choice_and_text_together(monkeypatch):
    calls = []

    def fake_post(client, url, body):
        calls.append((url, body))
        return {
            "model": "test",
            "provider": "P",
            "choices": [{"message": {"content": '{"op":"TYPE","target":1,"text":"Zurich"}'}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 12, "cost": 0.0001},
        }

    monkeypatch.setattr("dejevu.policy.post_json", fake_post)
    policy = LLMPolicy(model="m", api_key="k", provider="P", logprobs=True)
    d = policy.decide("Find flights from Zurich", page(), [])
    assert len(calls) == 1
    body = calls[0][1]
    assert body["response_format"] == {"type": "json_object"} and body["logprobs"] is True
    assert body["provider"] == {"order": ["P"], "allow_fallbacks": True}
    assert (d.op, d.target, d.text, d.cost, d.provider) == ("TYPE", 1, "Zurich", 0.0001, "P")


def test_empty_answer_is_a_policy_error(monkeypatch):
    monkeypatch.setattr("dejevu.policy.post_json", lambda *_: {"choices": [{"message": {"content": "", "reasoning": "hmm"}}]})
    with pytest.raises(PolicyError, match="reasoning"):
        LLMPolicy(model="m", api_key="k").decide("goal", page(), [])


class FakeTab:
    def __init__(self, pages, fresh=True):
        self.pages = list(pages)
        self.fresh_value = fresh
        self.acted = []
        self.chrome = Mock(calls=0)

    def observe(self, screenshot=False):
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]

    def fresh(self, page, action=None):
        return self.fresh_value

    def act(self, action, page, text=None):
        if not self.fresh_value:
            raise StalePage("changed")
        self.acted.append((action["kind"], action.get("node"), text))


class FakePolicy:
    name = "fake"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0
        self.notes = []

    def decide(self, goal, page, history, note=None):
        self.calls += 1
        self.notes.append(note)
        return self.answers.pop(0)


def test_stale_decision_is_consumed_and_never_executed():
    tab = FakeTab([page()], fresh=False)
    loop = Loop(tab, FakePolicy([Decision(op="CLICK", target=2), Decision(op="DONE")]), "goal")
    loop.step()
    assert tab.acted == [] and loop.stale == 1 and loop.decisions[0]["outcome"].startswith("stale")
    tab.fresh_value = True
    loop.step()
    assert loop.status == "done"


def test_action_is_logged_before_the_next_observation_and_marks_page_change():
    changed = page(text="Results for Zurich")
    tab = FakeTab([page(), changed])
    loop = Loop(tab, FakePolicy([Decision(op="TYPE", target=1, text="Zurich"), Decision(op="DONE")]), "goal")
    loop.step()
    assert tab.acted == [("fill", 10, "Zurich")]
    assert loop.history[0]["page_changed"] is True and loop.history[0]["text"] == "Zurich"


def test_three_unusable_answers_stop_the_run_without_executing():
    tab = FakeTab([page()])
    loop = Loop(tab, FakePolicy([Decision(op="CLICK", target=99)] * 3), "goal")
    for _ in range(3):
        loop.step()
    assert loop.status == "blocked" and "unusable" in loop.reason and tab.acted == [] and loop.invalid == 3


def test_no_visible_progress_in_three_actions_stops():
    tab = FakeTab([page()])
    loop = Loop(tab, FakePolicy([Decision(op="CLICK", target=2)] * 3), "goal")
    for _ in range(3):
        loop.step()
    assert loop.status == "blocked" and "no visible progress" in loop.reason


def test_waits_do_not_count_as_no_progress():
    tab = FakeTab([page()])
    loop = Loop(tab, FakePolicy([Decision(op="WAIT")] * 4 + [Decision(op="DONE")]), "goal")
    for _ in range(4):
        loop.step()
    assert loop.status == "ready" and len(loop.history) == 4


def test_clock_starts_on_the_accepted_page_only():
    consent = page(url="https://consent.example/")
    tab = FakeTab([consent, page()])
    loop = Loop(
        tab,
        FakePolicy([Decision(op="CLICK", target=2), Decision(op="DONE")]),
        "goal",
        clock_from=lambda p: p["url"].startswith("https://example.test"),
    )
    loop.step()
    assert loop.started is None and loop.history[0]["elapsed_ms"] == 0
    loop.step()
    assert loop.started is not None and loop.status == "done"


def test_fingerprint_ignores_geometry_and_screenshots():
    a = page()
    b = page()
    b["actions"][0]["rect"] = {"x": 1, "y": 2, "w": 3, "h": 4}
    b["screenshot"] = "zzz"
    assert fingerprint(a) == fingerprint(b)
    c = page(text="different")
    assert fingerprint(a) != fingerprint(c)


@pytest.mark.parametrize("broken", ["Departure", "Where from?", "Where to?", "year"])
def test_flight_verification_rejects_a_wrong_trip(broken):
    good = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": f"Track prices from Zürich to London departing {FLIGHT_DATE.isoformat()}",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", "London"),
                ("Departure", f"{FLIGHT_DATE:%a, %b} {FLIGHT_DATE.day}"),
                (f"Nonstop flight on {FLIGHT_DATE:%A, %B} {FLIGHT_DATE.day}. Select flight", ""),
            ]
        ],
    }
    assert verify_flights(good)["passed"]
    bad = json.loads(json.dumps(good))
    if broken == "year":
        bad["text"] = bad["text"].replace(str(FLIGHT_DATE.year), str(FLIGHT_DATE.year + 1))
    else:
        next(a for a in bad["actions"] if a["label"] == broken)["value"] = "wrong"
    assert not verify_flights(bad)["passed"]


def test_select_on_a_combobox_suggestion_becomes_a_click():
    p = page()
    p["actions"].append({"id": 5, "node": 50, "role": "option", "label": "London, United Kingdom", "kind": "click"})
    p["fingerprint"] = fingerprint(p)
    action = validate(Decision(op="SELECT", target=1, option=5), p)
    assert (action["kind"], action["node"], action["label"]) == ("click", 50, "London, United Kingdom")
    assert validate(Decision(op="SELECT", target=5), p)["node"] == 50
    assert validate(Decision(op="CLICK", target=4, option=2), p)["kind"] == "select"


def test_rejected_answer_is_explained_to_the_model_once():
    tab = FakeTab([page()])
    policy = FakePolicy(
        [
            Decision(op="CLICK", target=99, raw='{"op":"CLICK","target":99}'),
            Decision(op="CLICK", target=2),
            Decision(op="DONE"),
        ]
    )
    loop = Loop(tab, policy, "goal")
    for _ in range(3):
        loop.step()
    assert policy.notes[0] is None
    assert "target 99" in policy.notes[1] and "rejected" in policy.notes[1]
    assert policy.notes[2] is None and loop.status == "done"
    assert "NOTE: " + policy.notes[1] in render("goal", page(), [], note=policy.notes[1])


def test_repeating_the_same_action_stops_the_run():
    tab = FakeTab([page(), page(text="a"), page(text="b"), page(text="c"), page(text="d"), page(text="e"), page(text="f")])
    loop = Loop(tab, FakePolicy([Decision(op="CLICK", target=2)] * 6), "goal")
    while loop.status == "ready":
        loop.step()
    assert loop.status == "blocked" and "looping" in loop.reason and len(loop.history) == 4


def test_done_is_not_accepted_while_the_page_is_still_loading():
    tab = FakeTab([page()])
    tab.pending = lambda since=None: 1
    tab.settle = lambda kind: None
    loop = Loop(tab, FakePolicy([Decision(op="DONE"), Decision(op="DONE")]), "goal")
    loop.step()
    assert loop.status == "ready" and loop.decisions[0]["outcome"].startswith("premature")
    tab.pending = lambda since=None: 0
    loop.step()
    assert loop.status == "done"


def test_select_on_a_combobox_works_even_without_native_dropdowns():
    p = page()
    p["actions"] = [a for a in p["actions"] if a["kind"] != "select"]
    p["actions"].append({"id": 5, "node": 50, "role": "option", "label": "London, United Kingdom", "kind": "click"})
    p["fingerprint"] = fingerprint(p)
    assert "SELECT" not in available_ops(p)
    assert validate(Decision(op="SELECT", target=1, option=5), p)["node"] == 50
    assert validate(Decision(op="SELECT", target=2), p)["node"] == 20


def test_click_with_text_on_an_editable_field_types_and_type_without_text_clicks():
    typed = validate(Decision(op="CLICK", target=1, text="Zurich", key="Enter"), page())
    assert (typed["kind"], typed["node"], typed.get("key")) == ("fill", 10, "Enter")
    assert validate(Decision(op="TYPE", target=2), page())["kind"] == "click"


def test_missing_operation_is_inferred_from_target_and_text():
    assert validate(Decision(op="", target=1, text="Zurich"), page())["kind"] == "fill"
    assert validate(Decision(op="", target=2), page())["kind"] == "click"
    assert validate(Decision(op="", key="Escape"), page())["kind"] == "press"
    with pytest.raises(PolicyError):
        validate(Decision(op=""), page())


def test_a_verdict_is_deferred_at_most_twice_while_requests_keep_coming():
    tab = FakeTab([page()])
    tab.pending = lambda since=None: 1
    tab.settle = lambda kind: None
    loop = Loop(tab, FakePolicy([Decision(op="DONE")] * 4), "goal")
    for _ in range(3):
        loop.step()
    assert loop.status == "done" and loop.stale == 2


def test_operation_given_as_the_json_key_is_understood():
    d = normalize(parse_answer('{"CLICK": 18}'))
    assert (d.op, d.target) == ("CLICK", 18)
    d = normalize(parse_answer('{"TYPE": "TYPE", "target": 16, "text": "London", "key": "Enter"}'))
    assert (d.op, d.target, d.text, d.key) == ("TYPE", 16, "London", "Enter")


def test_unreadable_answer_is_retried_with_feedback_not_fatal():
    class Flaky:
        name = "flaky"

        def __init__(self):
            self.notes = []

        def decide(self, goal, page, history, note=None):
            self.notes.append(note)
            if len(self.notes) == 1:
                from dejevu.policy import AnswerError

                raise AnswerError("answer is not valid JSON; no action executed")
            return Decision(op="DONE")

    tab = FakeTab([page()])
    flaky = Flaky()
    loop = Loop(tab, flaky, "goal")
    loop.step()
    assert loop.status == "ready" and loop.invalid == 1
    loop.step()
    assert loop.status == "done" and "could not be read" in flaky.notes[1]


def test_repeated_stale_decisions_get_feedback_and_a_stop():
    tab = FakeTab([page()], fresh=False)
    policy = FakePolicy([Decision(op="CLICK", target=2, raw="x")] * 9)
    loop = Loop(tab, policy, "goal")
    while loop.status == "ready":
        loop.step()
    assert loop.status == "blocked" and "kept changing" in loop.reason
    assert policy.notes[0] is None and policy.notes[2] and "could not be executed" in policy.notes[2]


def test_cli_without_a_key_exits_with_a_hint(monkeypatch):
    from dejevu import cli

    monkeypatch.setattr("dejevu.config.load_env", lambda: None)
    for name in ("OPENROUTER_API_KEY", "DEJEVU_API_KEY", "okey"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as stop:
        cli.main(["--task", "wikipedia"])
    assert "doctor" in str(stop.value) and "OPENROUTER_API_KEY" in str(stop.value)


def test_cli_without_arguments_shows_help_and_exits(capsys):
    from dejevu import cli

    with pytest.raises(SystemExit):
        cli.main([])
    assert "examples:" in capsys.readouterr().out


def test_holdout_checks_are_strict():
    from dejevu.tasks import verify_pydocs, verify_webform, verify_www

    good = "https://www.selenium.dev/selenium/web/submitted-form.html?my-text=dejevu&my-password=&my-textarea=hello+from+dejevu&my-select=2&my-check=on&my-check=on&my-radio=on"
    assert verify_webform({"url": good})["passed"]
    assert not verify_webform({"url": good.replace("my-select=2", "my-select=3")})["passed"]
    assert not verify_webform({"url": good.replace("&my-check=on&my-check=on", "&my-check=on")})["passed"]
    assert verify_pydocs({"url": "https://docs.python.org/3/library/asyncio-task.html#asyncio.gather"})["passed"]
    assert not verify_pydocs({"url": "https://docs.python.org/3/search.html?q=asyncio.gather"})["passed"]
    assert verify_www({"url": "https://en.wikipedia.org/wiki/Tim_Berners-Lee#Early_life"})["passed"]
    assert not verify_www({"url": "https://en.wikipedia.org/wiki/World_Wide_Web"})["passed"]

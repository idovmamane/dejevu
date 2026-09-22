"""Reference tasks with independent outcome checks. A DONE answer is a claim; verify() is the evidence."""

import base64
import datetime as dt
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qs, urlparse

# jev-ultrafast searched Sunday 2026-09-20; that date has passed, so the same task uses a Sunday four weeks out.
FLIGHT_DATE = dt.date(2026, 10, 18)


@dataclass
class Task:
    name: str
    url: str
    goal: str
    verify: Callable[[dict], dict]
    # Timing starts at the first decision on a page accepted here, mirroring jev-ultrafast's "after initial observation".
    clock_from: Callable[[dict], bool] = lambda page: True


def verify_flights(page):
    parsed = urlparse(page["url"])
    encoded = parse_qs(parsed.query).get("tfs", [""])[0]
    try:
        date_in_url = FLIGHT_DATE.isoformat().encode() in base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except ValueError:
        date_in_url = False
    values = {a["label"].strip(): a.get("value") for a in page["actions"]}
    # Result rows carry the itinerary in their accessible name ("... Leaves Zurich Airport at 8:55 PM on Sunday, October 18 ...").
    flights = [
        a["label"]
        for a in page["actions"]
        if "Select flight" in a["label"] or (a["label"].startswith("From ") and "Leaves" in a["label"])
    ]
    checks = {
        "search_page": parsed.hostname == "www.google.com" and parsed.path == "/travel/flights/search",
        "one_way": values.get("Change ticket type. One way") == "One way",
        "origin": values.get("Where from?") == "Zürich",
        "destination": values.get("Where to?") == "London",
        "date": values.get("Departure") == f"{FLIGHT_DATE:%a, %b} {FLIGHT_DATE.day}",
        "year": date_in_url or f"departing {FLIGHT_DATE.isoformat()}" in page["text"],
        "results": bool(flights) and all(f"{FLIGHT_DATE:%A, %B} {FLIGHT_DATE.day}" in f for f in flights),
    }
    return {"passed": all(checks.values()), "checks": checks, "visible_flights": flights[:5]}


def verify_wikipedia(page):
    ok = page["url"].split("#")[0] == "https://en.wikipedia.org/wiki/G%C3%B6del%27s_incompleteness_theorems"
    return {"passed": ok, "checks": {"article_url": ok}, "url": page["url"]}


TASKS = {
    "flights": Task(
        name="flights",
        url="https://www.google.com/travel/flights?hl=en",
        goal=(
            f"Find one-way flights from Zurich to London on {FLIGHT_DATE:%B} {FLIGHT_DATE.day}, {FLIGHT_DATE.year}, "
            "for one adult in economy. "
            "Stop when matching flight options are visible. Do not select or book a flight."
        ),
        verify=verify_flights,
        clock_from=lambda page: page["url"].startswith("https://www.google.com/travel/flights"),
    ),
    "wikipedia": Task(
        name="wikipedia",
        url="https://en.wikipedia.org/wiki/Main_Page",
        goal="Find and open the Wikipedia article about Gödel's incompleteness theorems.",
        verify=verify_wikipedia,
    ),
}

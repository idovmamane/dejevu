"""Live Google Flights search with an independent result check. Same goal as jev-ultrafast; never books anything.

uv run python examples/flights.py [--headed] [--json artifacts/flights.json]
"""

import sys

from jevless.cli import main

if __name__ == "__main__":
    main(["--task", "flights", *sys.argv[1:]])

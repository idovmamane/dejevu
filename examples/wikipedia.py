"""Open the Gödel's incompleteness theorems article from the Wikipedia main page; the check is the exact article URL.

uv run python examples/wikipedia.py [--headed] [--json artifacts/wikipedia.json]
"""

import sys

from jevless.cli import main

if __name__ == "__main__":
    main(["--task", "wikipedia", *sys.argv[1:]])

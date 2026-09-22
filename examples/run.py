"""Any page, any goal:  uv run python examples/run.py --url https://example.com --goal 'Open the pricing page'"""

import sys

from dejevu.cli import main

if __name__ == "__main__":
    main(sys.argv[1:])

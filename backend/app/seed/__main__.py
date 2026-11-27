"""Allow running `python -m app.seed` inside the API container."""

import sys

from app.seed.runner import main

if __name__ == "__main__":
    sys.exit(main())

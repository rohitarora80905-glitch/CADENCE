"""Allows `python -m cadence song.cad`."""
import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())

"""Permite `python -m sibila ...` (trampa: sin este archivo, exit 1)."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

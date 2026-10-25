"""Launches Cicero, so ``python main.py`` (and the IDE run button) keeps working.

The application itself lives in the ``cicero`` package; see README.md.
"""

from cicero.app import main

if __name__ == "__main__":
    raise SystemExit(main())

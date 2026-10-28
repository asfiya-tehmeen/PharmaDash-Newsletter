"""PharmaDash: editorial-research agent for the PharmaDash newsletter."""

__version__ = "0.1.0"

import sys

# Windows consoles default to a legacy encoding that crashes on characters like non-breaking spaces.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

"""Compatibility shim — module renamed to gemini_synthesis.py.

All imports should use analysis.gemini_synthesis going forward.
This file is kept only so any stale import doesn't break the server.
"""

from analysis.gemini_synthesis import (  # noqa: F401
    get_user_config,
    synthesise_recommendation,
    synthesise_all,
    format_morning_briefing,
)

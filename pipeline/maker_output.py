"""Maker output contract helpers.

The v3 Maker output keeps user-facing text in ``answer`` and exposes one
machine-readable safety field at top level: ``urgency``.
"""

from __future__ import annotations

from typing import Any, Iterable


URGENCY_VALUES = frozenset(
    {
        "emergency",
        "urgent",
        "routine",
        "self_care",
        "education_only",
        "uncertain",
    }
)

URGENT_URGENCIES = frozenset({"emergency", "urgent"})


def normalize_urgency(value: Any) -> str:
    """Return a valid urgency label, falling back to ``uncertain``."""

    text = str(value or "").strip().lower()
    return text if text in URGENCY_VALUES else "uncertain"

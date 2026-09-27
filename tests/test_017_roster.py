"""017 eval-set roster freeze (task 017 §三): the real-board annotation sets
under ``reviewsets/`` (top level, non-injected) and their ``split_default``
are frozen here. Adding a board, removing one, or flipping a split means
editing this table **in the same commit** as the annotation change — the
deliberate review moment the split discipline exists to force. Injected
boards are governed separately by ``tests/test_injected_variants.py``
(``FROZEN_DEV`` / ``FROZEN_HOLDOUT`` there).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REVIEWSETS = REPO / "reviewsets"

# annotation file name -> frozen split_default (frozen 2026-09-27, task 017)
FROZEN_ROSTER: dict[str, str] = {
    "ch340g_golden.json": "dev",
    "ProPrj_毕设FOC驱动板_2026-09-17.json": "holdout",
}


def test_no_unrostered_annotation_sets() -> None:
    """Every top-level annotation set on disk is rostered with its frozen
    split — a new board or a flipped split goes red here."""
    on_disk = sorted(p.name for p in REVIEWSETS.glob("*.json"))
    unrostered = [name for name in on_disk if name not in FROZEN_ROSTER]
    assert not unrostered, f"annotation set(s) not in FROZEN_ROSTER: {unrostered}"
    for name in on_disk:
        data = json.loads((REVIEWSETS / name).read_text(encoding="utf-8"))
        actual = data.get("split_default")
        assert actual == FROZEN_ROSTER[name], (
            f"{name}: split_default {actual!r} != frozen {FROZEN_ROSTER[name]!r}"
        )


def test_roster_entries_exist() -> None:
    """A rostered set that disappears or gets renamed goes red — the roster
    cannot silently shrink either."""
    missing = [name for name in FROZEN_ROSTER if not (REVIEWSETS / name).exists()]
    assert not missing, f"rostered annotation set(s) missing from disk: {missing}"

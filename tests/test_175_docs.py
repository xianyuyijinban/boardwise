"""175 item 4: `docs/draw.md` says what the compiler does about labels.

**The drift.** The document's "Where a placed label is allowed to land" section
said 「Every label that *is* placed goes through `layout.clear_label_point`」 —
true of **signal names** and, until 173/A, false of power/ground flags, which were
pinned to the router's own candidate without the search ever looking at them. That
half-sentence is the same fact 163a/E3 caught on the golden page (the `+5V` flag's
anchor on another net's wire, `LABEL_ON_FOREIGN_WIRE`), and 173/A fixed the code:
rails go through the same search, with `margin=0.0` — they may not land on a
foreign wire, a body or another name, and they are never dropped for a preference.

The scan for other stale one-sided claims came up empty: the violation-code table
already carries 163a's codes (`LABEL_ON_FOREIGN_WIRE`, `WIRE_OVERLAP`,
`PINS_UNPLACED`), and 074's 「普通信号布线穿越不硬化」 note is still true — 175/B-1
put a **price** on an ordinary crossing and did not harden it.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DRAW_DOC = (ROOT / "docs" / "draw.md").read_text(encoding="utf-8")


def _section(title: str, next_title: str) -> str:
    start = DRAW_DOC.index(title)
    end = DRAW_DOC.index(next_title, start)
    return DRAW_DOC[start:end]


def test_the_label_section_says_flags_go_through_the_same_search():
    section = _section("### Where a placed label is allowed to land", "## Two design sources")
    assert "clear_label_point" in section
    assert "Power/ground flags go through the same search" in section
    assert "`route.attach`" in section, (
        "the old behaviour is named, so the sentence is a history and not a claim "
        "about the current code"
    )
    assert "margin=0.0" in section and "LABEL_ON_FOREIGN_WIRE" in section


def test_the_label_section_no_longer_reads_as_if_names_were_all_that_is_placed():
    """The one-sided reading is gone: the flags half is stated where it was missing."""
    section = _section("### Where a placed label is allowed to land", "## Two design sources")
    assert "used to be true of signal names only" in section


def test_the_violation_table_carries_the_163a_codes():
    """173's leftover ④'s other half was already done; pinned so it stays."""
    table = _section("| Code | Meaning |", "`LABEL_ON_FOREIGN_WIRE` has **two paths")
    for code in ("LABEL_ON_FOREIGN_WIRE", "WIRE_OVERLAP", "PINS_UNPLACED"):
        assert code in table


def test_the_ordinary_wiring_crossing_is_still_a_price_and_not_a_wall():
    """175/B-1 must not be read out of this document as a hardening.

    074 hardens a **flag's lead**; 175 raised the *price* of an ordinary crossing
    in the search and in the one-bend shortcut. The doc's 074 note says the
    hardening covers leads only, and that is still exactly true.
    """
    assert "**普通信号布线穿越不硬化**" in DRAW_DOC
    assert "crossings 仍是软指标" in DRAW_DOC
    assert "175/B-1" in DRAW_DOC, "the crossing price is documented where 074 is"

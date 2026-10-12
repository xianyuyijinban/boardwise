"""Task 171 B: ``EARTH`` joins the core ground vocabulary.

``core.model.GROUND_NET_PREFIXES`` carried ``GND`` / ``AGND`` / ``DGND`` / ``PGND``
/ ``EGND`` / ``SGND`` / ``VSS`` and **not** ``EARTH``, so ``is_ground_net("EARTH")``
— 「the one place this repo calls a name ground」 (143d) — answered *no* for the most
common English spelling of a board's ground. 164a's D2 found the hole from one side
and worked around it: ``rules/pcb/focground.GROUND_DOMAIN_POWER_PREFIXES`` names
``EARTH`` as a power-domain word, so ``split_ground_domains`` sieves with a **union**
(``domain_of`` ∨ ``is_ground_net``) to stop a bare ``EARTH`` net vanishing from every
domain in silence.

This batch closes it in the vocabulary instead, which is where the ruling language
belongs: a word that means ground is a fact about net names, not about one rule's
domain table. ``focground``'s union sieve stays (it is now redundant for ``EARTH``
and still carries ``P_GND`` / ``POWER_GND``, which core does not claim) — one place
per question, with the second one no longer load-bearing.

**The prefix convention's cost, measured and pinned rather than hidden.** A member of
``GROUND_NET_PREFIXES`` is matched with ``startswith``, so ``EARTHING`` / ``EARTHED``
are ground-class too. That is the convention this vocabulary has always used —
``tests/test_145a_walls.py`` pins ``is_ground_net("GNDX_RAIL") is True`` for the same
reason — and the alternative (a third, exact-name list) would be a second vocabulary
to keep in step with the first.

**Pinned flips (old → new + reason).** 164a's fixture for D2 asserted ``EARTH`` was
ground-class to ``domain_of`` but **not** to ``is_ground_net``; that half of the
statement is what this batch makes false, and ``tests/test_164a_foc_view_truth.py``'s
assertions (``split.power == ("EARTH",)``, ``unclassified == ()``) hold either way —
only its prose describes the old world. ``tests/test_145a_walls.py``'s
``set(GROUND_NET_SUFFIX_WORDS) == {…}`` is the one pin whose *value* moves, because
the suffix vocabulary is the prefix vocabulary (145a's own 「the suffix words are the
ground words, not a second list that can drift」).
"""

from __future__ import annotations

import pytest

from boardwise.core.blocks import net_class_of
from boardwise.core.changeplan import (
    DRAW_FLAG_GROUND,
    ChangePlanError,
    _draw_flags_from,
)
from boardwise.core.geometry import BoardGeometry, NetGeometry
from boardwise.core.model import GROUND_NET_SUFFIX_WORDS, is_ground_net
from boardwise.core.symbolprofile import SymbolProfile, flag_glyph_kind
from boardwise.engines.drawapply import DrawPlanError, flag_kind
from boardwise.rules.pcb.focground import domain_of, split_ground_domains


def test_earth_is_a_ground_name():
    """The bare spelling 164a's D2 had to work around, and its compound forms."""
    for name in ("EARTH", "earth", "Earth", "EARTH_PGND", "SEC_EARTH",
                 "sec_earth", "CHASSIS_EARTH"):
        assert is_ground_net(name), name


def test_the_prefix_convention_puts_earth_derivatives_on_ground_too():
    """``startswith``, so ``EARTHING`` is ground-class — the convention's own cost.

    The same over-reach the GND family has always had (``GNDX_RAIL`` is ground by
    prefix, pinned in 145a). Stated here so it is a measured property of the
    vocabulary rather than a surprise: the alternative is a second, exact-name list
    beside this one, which is the drift 145a removed.
    """
    for name in ("EARTHING", "EARTHED", "EARTHX"):
        assert is_ground_net(name), name


def test_the_other_negatives_are_unchanged():
    """Adding a word must not turn anything that was not ground into ground."""
    for name in ("VM", "+24V", "VCC", "VEE", "VEE-5V", "-5V", "3V3", "RX",
                 "SEC_12V", "HVDC", "SEC_SW", "SECGND", "", None):
        assert not is_ground_net(name), name


def test_the_suffix_vocabulary_is_the_prefix_vocabulary_and_now_carries_earth():
    """145a's 「the suffix words are the ground words, not a second list」, now with EARTH.

    This is the pin whose **value** moves: ``GROUND_NET_SUFFIX_WORDS`` is the prefix
    tuple by construction (``= GROUND_NET_PREFIXES``), and ``tests/test_145a_walls.py``
    pinned the seven-word set. A ground word at the end of a name is the same
    statement as one at the front, so ``SEC_EARTH`` is ground-class from this batch.
    """
    assert "EARTH" in GROUND_NET_SUFFIX_WORDS
    assert is_ground_net("SEC_EARTH")


# ---------------------------------------------------------------------------
# the consumers, one witness each: what the flip actually changes
# ---------------------------------------------------------------------------


def test_a_flag_on_an_earth_net_is_a_ground_flag():
    """``engines.drawapply.flag_kind`` — the 143d cross-check's own reading.

    Before: ``flag_kind('EARTH')`` answered ``''`` (the host's rail vocabulary did
    not know the name) and ``flag_kind('EARTH', 'PWR-GND')`` **raised** — 143d's
    "a ground symbol on a name that is not a ground name" refusal, i.e. the ground
    glyph 岳's own pages draw on an earthing net was the disagreement. Now the name
    says ground on its own and both questions agree.
    """
    assert flag_kind("EARTH") == DRAW_FLAG_GROUND
    assert flag_kind("EARTH", "PWR-GND") == DRAW_FLAG_GROUND
    # A supply rail's flag is untouched by the vocabulary growing.
    assert flag_kind("+24V") == "Power"
    with pytest.raises(DrawPlanError):
        flag_kind("+24V", "PWR-GND")  # the disagreement is still caught


def test_a_plan_may_hang_a_ground_flag_on_an_earth_net():
    """``core.changeplan``'s flag validation — the plan half of the same statement.

    The gate is ``(kind == DRAW_FLAG_GROUND) != is_ground_net(net)``: a plan that
    placed a ``Ground`` flag on ``EARTH`` used to be refused as a net/kind
    contradiction (029-d's reasoning, applied to a name the vocabulary had not
    learned). It validates now.
    """
    flags = _draw_flags_from(
        [{"net": "EARTH", "kind": DRAW_FLAG_GROUND, "x": 100, "y": 100}], []
    )
    assert [flag.net for flag in flags] == ["EARTH"]
    with pytest.raises(ChangePlanError):
        # the contradiction the gate exists for is unchanged:
        _draw_flags_from(
            [{"net": "+24V", "kind": DRAW_FLAG_GROUND, "x": 100, "y": 100}], []
        )


def test_the_net_class_and_the_flag_glyph_family_follow_the_vocabulary():
    """``core.blocks.net_class_of`` and ``core.symbolprofile.flag_glyph_kind``.

    Both read the name through the shared predicate (「one place this repo calls a
    name ground」): an ``EARTH`` net is a ``gnd`` interface net, and a flag library
    entry titled ``Ground-EARTH`` is the ground glyph family (060's two families
    hang their glyph on opposite sides, so the family is what decides rotation and
    box — this one used to be read as a *rail* and drawn upside down).
    """
    assert net_class_of("EARTH", {}) == "gnd"
    assert net_class_of("EARTH", {"EARTH": "Power"}) == "gnd", "the name wins"
    assert flag_glyph_kind(SymbolProfile(symbol_ref="Ground-EARTH")) == "gnd"
    assert flag_glyph_kind(SymbolProfile(symbol_ref="Power-VCC")) == "rail"


def test_the_geometry_net_predicate_reads_it_too():
    """``core.geometry.NetGeometry.is_ground`` — the geometry side of one predicate."""
    assert NetGeometry(name="EARTH").is_ground
    assert not NetGeometry(name="+24V").is_ground


def test_focgrounds_union_sieve_still_answers_the_same_way():
    """164a's D2 rows do not move: ``EARTH`` was already a power-domain net there.

    ``domain_of`` names ``EARTH`` in its own power list, and the sieve was already a
    union, so the split is what it was — the difference is only *which* vocabulary
    is doing the work. Pinned so the redundancy is a measured fact rather than an
    assumption.
    """
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        nets={name: NetGeometry(name=name) for name in ("EARTH", "GND", "PGND")},
    )
    split = split_ground_domains(board)
    assert split.power == ("EARTH", "PGND")
    assert split.logic == ("GND",)
    assert split.unclassified == ()
    assert domain_of("EARTH") == "power"


def test_a_suffix_earth_name_now_lands_in_unclassified_instead_of_vanishing():
    """The vocabulary flip's one visible change in focground's rows.

    ``SEC_EARTH`` is ground-class by the suffix rule now (145a's vocabulary, one word
    wider), and ``domain_of`` is a **prefix** table, so it lands in
    ``unclassified`` —「the drawing spells its ground something this word list does
    not carry」 (UNKNOWN, not 「logic」), which is the D2 direction: a name the drawing
    stated is disclosed rather than dropped. Before this batch the sieve would not
    have let the name through at all, so it appeared in no domain and no evidence
    line.
    """
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        nets={name: NetGeometry(name=name) for name in ("SEC_EARTH", "GND")},
    )
    split = split_ground_domains(board)
    assert split.unclassified == ("SEC_EARTH",)
    assert split.logic == ("GND",) and split.power == ()

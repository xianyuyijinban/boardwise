"""Issue #86: an old-library instance's blank ``Value`` is recovered from its identity.

An old-library instance carries ``partId="1"``, an **empty** ``Value`` and a
perfectly good MPN. The decoupling pool read only the field, so a real 100 nF
capacitor entered the pool with no readable capacitance: it was counted in
neither pool — not bulk, not high-frequency — and on 实板 A the measured
consequence was `pcb-decap-distance` reporting the nearest *readable* capacitor
**1146 mil** away while the true one sat **21 mil** from the IC (MPN
``CC0603KRX7R9BB104``, LCSC ``C14663``).

The fix has three parts, each pinned here:

* **the pool recovers** (:func:`~boardwise.rules.decap.recovered_capacitance`) —
  the shelf entry the part's MPN / C-number resolves to, else the EIA value code
  inside the MPN, in that order;
* **the candidate discloses** — :class:`~boardwise.rules.decap.CapCandidate`
  gained ``value_source`` (``schematic`` / ``shelf`` / ``mpn`` / ``""``), whose
  invariant is *``value`` parses as a capacitance exactly when ``value_source``
  is one of the three routes*;
* **the readers accept it and say so** — ``capacitor_role``
  (:mod:`boardwise.rules.pcb.distance`) and ``regulator_role`` /
  ``_pool_reason`` (:mod:`boardwise.rules.pcb.regulator`) read the drawing's own
  field **first**, and only when that yields nothing do they take the recovered
  value, with the reason naming the route. A row that presented a recovered
  number as a declared one would be the kind of lie 164b exists to prevent.

The MPN's own traps are not re-solved here: the decode goes through
:func:`boardwise.core.values.mpn_value_code` (which refuses the notations that
are not EIA codes, so a capacitance ``472M`` is 4.7 nF and never 472 MΩ) and
:func:`boardwise.core.values.decode_eia_3digit`, which is the pair
:func:`boardwise.rules.decap.candidate_farads` already used.

The end-to-end consequence on a real fixture — 毕设FOC PCB1's ``C30``, whose
``Value`` is empty and whose MPN is ``CC0805KRX7R9BB104`` — is pinned where the
board is: ``tests/test_126b_pcb_distance_rules.py`` and
``tests/test_127b_blind_review_fixes.py``, both of whose decap assertions moved
when this landed. This file is the unit-level half.
"""

from __future__ import annotations

import pytest

from boardwise.core.model import Component, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.core.values import parse_capacitance_farads
from boardwise.rules.decap import (
    VALUE_SOURCE_MPN,
    VALUE_SOURCE_SCHEMATIC,
    VALUE_SOURCE_SHELF,
    CapCandidate,
    cap_candidates_on,
    recovered_capacitance,
    recovered_farads,
    value_source_label,
)
from boardwise.rules.pcb.distance import (
    CAP_ROLE_BULK,
    CAP_ROLE_HF,
    CAP_ROLE_UNKNOWN,
    capacitor_role,
)
from boardwise.rules.pcb.regulator import (
    POOL_HF,
    POOL_STORAGE,
    _pool_reason,
    regulator_role,
)

#: 实板 A's own part (anonymised board, the issue's witness): 0603 X7R 100 nF,
#: whose MPN states ``104`` and whose shelf entry is ``cap.100n_0603.c14663``.
LEGACY_MPN = "CC0603KRX7R9BB104"
LEGACY_LCSC = "C14663"
LEGACY_NEARBY_MPN = "CC0805KRX7R9BB104"  # the same code in 0805 (毕设FOC's C30)

#: The synthetic helpers are 131b's: a ``Component`` with value/MPN/LCSC/pins
#: and a ``DesignModel`` whose net index is built from those pins.
from test_131b_regulator_cap_distance import _comp, _model  # noqa: E402


def _legacy(designator: str = "C21", **kwargs) -> object:
    """One old-library instance: **no** ``Value``, a good MPN and C-number.

    Pins 1/2 bridge ``VCC`` to ``GND`` — the shape
    :func:`~boardwise.rules.decap.cap_candidates_on` requires (a capacitor whose
    two terminals sit on one net bridges nothing and is not a candidate).
    """
    return _comp(
        designator,
        value="",
        mpn=kwargs.pop("mpn", LEGACY_MPN),
        lcsc=kwargs.pop("lcsc", LEGACY_LCSC),
        pins=[Pin("1", "1", "VCC"), Pin("2", "2", "GND")],
        **kwargs,
    )


def _shelf(value: str = "0.1uF", **kwargs) -> PartLibrary:
    """A real shelf holding exactly this part, with ``value``.

    ``0.1uF`` rather than the MPN's own ``100nF`` on purpose: the two spell the
    same capacitance, so the *text* is the evidence of **which route answered**
    — a shelf that agreed in wording with the decode could not show that the
    shelf is asked first.
    """
    return PartLibrary(
        parts=[
            PartEntry(
                key="test.legacy.c21",
                value=value,
                mpn=kwargs.pop("mpn", LEGACY_MPN),
                lcsc=kwargs.pop("lcsc", LEGACY_LCSC),
                category="capacitor",
                **kwargs,
            )
        ]
    )


# ---------------------------------------------------------------------------
# the recovery itself
# ---------------------------------------------------------------------------


def test_the_mpn_supplies_the_value_when_the_field_is_blank():
    """Route 2, on the issue's own MPN: ``…BB104`` states the EIA code ``104``.

    ``decode_eia_3digit("104", 1e-12)`` is ``10 x 10^4`` picofarads = **100 nF**,
    and the text that comes back is the trade's spelling of it rather than the
    float (``1.0000000000000001e-07``) — a recovered value a second reader could
    not read again would be a claim with a hole in it.
    """
    text, source = recovered_capacitance("C21", LEGACY_MPN, LEGACY_LCSC, None)
    assert (text, source) == ("100nF", VALUE_SOURCE_MPN)
    assert parse_capacitance_farads(text) == pytest.approx(1e-7)


def test_the_shelf_is_asked_before_the_mpn_is_decoded():
    """Route 1 wins: the curated value, verbatim, even where the two differ.

    The shelf here states ``0.1uF`` for a part whose MPN decodes to ``100nF`` —
    the same capacitance, two spellings — so the text says which route answered.
    """
    text, source = recovered_capacitance(
        "C21", LEGACY_MPN, LEGACY_LCSC, _shelf("0.1uF")
    )
    assert (text, source) == ("0.1uF", VALUE_SOURCE_SHELF)
    # ... and with no shelf in hand the MPN answers instead, from the same part.
    assert recovered_capacitance("C21", LEGACY_MPN, LEGACY_LCSC, None)[1] == (
        VALUE_SOURCE_MPN
    )


def test_a_shelf_value_that_is_not_a_capacitance_supplies_nothing():
    """The shelf is only trusted for a value that reads as a capacitance.

    A part whose MPN resolves to a shelf entry stating ``10kΩ`` (the identity is
    exact, the *field* is not a capacitance) leaves the MPN route to answer:
    what this function recovers is a capacitance or nothing, never 「whatever the
    entry's value field says」.
    """
    text, source = recovered_capacitance(
        "C21", LEGACY_MPN, LEGACY_LCSC, _shelf("10kΩ")
    )
    assert (text, source) == ("100nF", VALUE_SOURCE_MPN)


def test_the_eia_code_is_read_and_the_trades_other_notations_are_not():
    """``472M`` is 4.7 nF, not 472 MΩ — the trap the issue names.

    ``MPN 472M``'s ``472`` is an EIA capacitance code (``47 x 10^2`` pF), and the
    reading is **not** written here: it is
    :func:`boardwise.core.values.mpn_value_code`'s, which already refuses the
    mid-letter / R-field notations (``472M``'s sibling ``FRL1210FR400TS`` is 400
    mΩ, and reading ``330uF``'s digits as an EIA code is what once produced 33 pF
    for a 330 µF part). This pins the recovery to that existing reader rather
    than to a second decoder.
    """
    assert recovered_capacitance("C1", "472M", "", None) == ("4.7nF", VALUE_SOURCE_MPN)
    assert recovered_capacitance("C1", "SPZ1HM100E07O00RAXXX", "", None) == ("", "")


def test_an_mpn_that_does_not_look_like_a_capacitor_decodes_to_nothing():
    """The ``CH340G`` trap, at this entry point too.

    ``candidate_farads`` refuses to read an MPN's digits as a value code unless
    the part already looks like a capacitor, because ``CH340G`` decodes to
    "34 pF". The recovery applies the same guard, so a designator that is not a
    capacitor's and a footprint that is not a chip size are both refused here —
    this function is a *recovery*, not a second opinion about what a part is.
    """
    assert recovered_capacitance("U1", "CH340G", "", None) == ("", "")
    assert recovered_capacitance("U1", "RT9013-33GB", "", None) == ("", "")
    # The designator is what the conjunction turns on: a C-prefixed part with a
    # decodable MPN *is* a capacitor by the shared predicate (route 3 of
    # `looks_like_capacitor`), so the same MPN reads there — 34 pF, the number
    # `candidate_farads`' own docstring names as the reason the guard exists.
    # The guard narrows *who* may be decoded; it does not second-guess the
    # predicate about a part the board drew as a capacitor.
    assert recovered_capacitance("C1", "CH340G", "", None) == (
        "34pF", VALUE_SOURCE_MPN,
    )


def test_nothing_recoverable_is_an_empty_answer_not_a_guess():
    """No MPN, no C-number, no shelf: ``("", "")`` — never a default value.

    The shelf can only be reached through an identity key, so a part with neither
    MPN nor C-number finds nothing there either; and the last line is the
    converse, the same part **with** a C-number, which does find it.
    """
    assert recovered_capacitance("C21", "", "", None) == ("", "")
    assert recovered_capacitance("C21", "", "", _shelf()) == ("", "")
    assert recovered_capacitance("C21", "", LEGACY_LCSC, _shelf()) == (
        "0.1uF", VALUE_SOURCE_SHELF,
    )


def test_every_route_has_a_phrase_that_cannot_be_mistaken_for_a_declaration():
    """The disclosure vocabulary, including the case nobody has heard of."""
    assert "shelf" in value_source_label(VALUE_SOURCE_SHELF)
    assert "EIA" in value_source_label(VALUE_SOURCE_MPN)
    assert "schematic" in value_source_label(VALUE_SOURCE_SCHEMATIC)
    unknown = value_source_label("some-future-route")
    assert "recovery" in unknown, (
        "an unrecorded source must still read as a recovery, never as a "
        "declaration: that is the one confusion this phrase may not permit"
    )


# ---------------------------------------------------------------------------
# the pool
# ---------------------------------------------------------------------------


def test_the_pool_recovers_the_value_and_discloses_the_route():
    """``cap_candidates_on``'s own output for the legacy instance.

    The pair ``(100nF, mpn)`` is the whole issue in one assertion: the part is in
    the pool, its capacitance is readable, and the candidate says the number was
    **not** read off the schematic.
    """
    model = _model([_legacy()])
    pool = cap_candidates_on(model, "VCC")
    assert [c.designator for c in pool] == ["C21"]
    assert pool[0].value == "100nF"
    assert pool[0].value_source == VALUE_SOURCE_MPN
    assert pool[0].grounded is True


def test_the_pool_prefers_the_shelf_and_still_names_the_route():
    """With a shelf in hand the candidate carries the shelf's own text."""
    model = _model([_legacy()])
    pool = cap_candidates_on(model, "VCC", _shelf("0.1uF"))
    assert (pool[0].value, pool[0].value_source) == ("0.1uF", VALUE_SOURCE_SHELF)


def test_a_declared_value_is_still_tagged_as_the_schematic_s_own():
    """The normal case keeps its meaning, and is not confused with a recovery."""
    model = _model([
        _comp(
            "C21",
            value="2.2uF",
            mpn=LEGACY_MPN,
            lcsc=LEGACY_LCSC,
            pins=[Pin("1", "1", "VCC"), Pin("2", "2", "GND")],
        )
    ])
    pool = cap_candidates_on(model, "VCC")
    assert (pool[0].value, pool[0].value_source) == ("2.2uF", VALUE_SOURCE_SCHEMATIC)


def test_a_non_blank_field_that_is_not_a_capacitance_is_left_alone():
    """``DNP`` is the drawing speaking, and is not overridden by an MPN.

    The recovery runs **only on a blank field**: a schematic that wrote something
    — even something that is not a capacitance — is still the evidence about what
    this part is meant to be, so the candidate carries the literal text and no
    source. 「Unreadable」 is then the honest answer, which is the state
    ``decide_required_cap`` and ``capacitor_role`` each already report.
    """
    model = _model([
        _comp(
            "C21",
            value="DNP",
            mpn=LEGACY_MPN,
            lcsc=LEGACY_LCSC,
            pins=[Pin("1", "1", "VCC"), Pin("2", "2", "GND")],
        )
    ])
    pool = cap_candidates_on(model, "VCC")
    assert (pool[0].value, pool[0].value_source) == ("DNP", "")
    assert recovered_farads(pool[0]) is None


def test_the_value_source_invariant_holds_across_the_four_routes():
    """``value`` parses exactly when ``value_source`` names a route.

    The invariant the field's own docstring states, checked over the four shapes
    a candidate can take — because it is what lets a consumer read 「``""``」 as
    「this is not a number」 instead of asking a second question.
    """
    model = _model([
        _legacy("C21"),
        _comp(
            "C22",
            value="2.2uF",
            pins=[Pin("1", "1", "VCC"), Pin("2", "2", "GND")],
        ),
        _comp(
            "C23",
            value="DNP",
            mpn=LEGACY_MPN,
            pins=[Pin("1", "1", "VCC"), Pin("2", "2", "GND")],
        ),
        # A C-prefixed part with nothing to say for itself: no value, no MPN,
        # no C-number. It is the pool's weakest accepted shape — a chip-size
        # footprint is the whole of its evidence (`looks_like_capacitor`'s route
        # 3) — and it is here as the 「nothing recovered」 row of the table.
        Component(
            uid="u-C24",
            designator="C24",
            footprint="C0603",
            pins=[Pin("1", "1", "VCC"), Pin("2", "2", "GND")],
        ),
    ])
    pool = {c.designator: c for c in cap_candidates_on(model, "VCC")}
    assert set(pool) == {"C21", "C22", "C23", "C24"}, (
        "all four are in the pool — including the one nothing could be "
        "recovered for, which is the point: the recovery adds a value, it never "
        "adds or removes a candidate"
    )
    for candidate in pool.values():
        readable = parse_capacitance_farads(candidate.value) is not None
        named = candidate.value_source in (
            VALUE_SOURCE_SCHEMATIC, VALUE_SOURCE_SHELF, VALUE_SOURCE_MPN,
        )
        assert readable == named, (candidate.designator, candidate.value,
                                   candidate.value_source)
    assert pool["C24"].value_source == "", "nothing readable, nothing claimed"


def test_recovered_farads_answers_only_for_a_recovered_value():
    """The shared reading, and its narrowness.

    ``None`` for a candidate whose value is the schematic's own (whoever owns
    that question reads it at their own gate) and for one that was never
    recovered; the capacitance for a recovered one. A duck-typed object with no
    ``value_source`` at all — 131b's own candidates are built that way — answers
    ``None`` rather than raising.
    """
    legacy = _model([_legacy()])
    candidate = cap_candidates_on(legacy, "VCC")[0]
    assert recovered_farads(candidate) == pytest.approx(1e-7)
    assert recovered_farads(CapCandidate(designator="C1", value="100nF")) is None
    assert recovered_farads(
        CapCandidate(
            designator="C1", value="100nF", value_source=VALUE_SOURCE_SCHEMATIC
        )
    ) is None
    assert recovered_farads(type("Bare", (), {"designator": "C1"})()) is None


# ---------------------------------------------------------------------------
# the readers — where the issue was actually measured
# ---------------------------------------------------------------------------


def _legacy_pair(designator: str = "C21") -> tuple:
    """``(model, candidate)`` for the legacy instance, as the rules receive it."""
    model = _model([_legacy(designator)])
    return model, cap_candidates_on(model, "VCC")[0]


def test_the_decap_role_reads_the_recovered_value_and_names_where_it_came_from():
    """The symptom: 分档 used to file this part in neither pool.

    100 nF is <= the 1 µF high-frequency ceiling, so the part is an HF
    candidate — and the reason says 「recovered」 and names the route, so the row
    can never be read as 「the schematic declared 100nF」.
    """
    model, candidate = _legacy_pair()
    role = capacitor_role(candidate, model)
    assert role.role == CAP_ROLE_HF
    assert role.farads == pytest.approx(1e-7)
    assert "recovered '100nF'" in role.reason
    assert "EIA value code inside its MPN" in role.reason
    assert "not from the schematic" in role.reason
    assert "declared" not in role.reason


def test_the_decap_role_is_unknown_without_the_recovery():
    """The reading depends on the pool's recovery, not on a second look.

    The same board model and the same component, but a candidate that carries no
    recovery (`CapCandidate` built by hand, as apply's live-page probe does):
    the role is UNKNOWN and says so. This is the pre-#86 answer on 实板 A, and it
    is what made the nearest *readable* capacitor 1146 mil away the row.
    """
    model, candidate = _legacy_pair()
    bare = CapCandidate(designator=candidate.designator, mpn=LEGACY_MPN)
    role = capacitor_role(bare, model)
    assert role.role == CAP_ROLE_UNKNOWN
    assert role.farads is None
    assert "no readable capacitance" in role.reason


def test_the_schematic_still_wins_over_a_recovered_value():
    """164b's order is untouched: the drawing's own field decides when it can.

    A component the drawing declares ``22uF`` with a candidate whose recovery
    says ``100nF`` is **bulk** on the declared value, and the reason quotes the
    declaration — the recovery is a fallback, not a second opinion.
    """
    model = _model([
        _comp(
            "C21",
            value="22uF",
            mpn=LEGACY_MPN,
            pins=[Pin("1", "1", "VCC"), Pin("2", "2", "GND")],
        )
    ])
    candidate = CapCandidate(
        designator="C21", value="100nF", value_source=VALUE_SOURCE_MPN
    )
    role = capacitor_role(candidate, model)
    assert role.role == CAP_ROLE_BULK
    assert "declared '22uF'" in role.reason
    assert "recovered" not in role.reason


def test_the_regulator_pool_reads_it_too_and_the_evidence_says_so():
    """The sibling reader, which had the same blind spot on the same part.

    ``pcb-regulator-cap-distance`` splits a rail's capacitors into HF and
    storage through :func:`regulator_role`; a legacy instance with a blank
    ``Value`` used to be in neither pool there as well (``""``). It now reads
    the recovered value, and the row's own evidence sentence carries the
    recovery instead of presenting it as a declaration.
    """
    model, candidate = _legacy_pair()
    assert regulator_role(candidate, model) == POOL_HF
    reason = _pool_reason(candidate, model)
    assert "recovered '100nF'" in reason
    assert "EIA value code inside its MPN" in reason
    # The storage side of the same reader, for the boundary the pool uses.
    big = CapCandidate(
        designator="C21", value="22uF", value_source=VALUE_SOURCE_MPN
    )
    blank = _model([_legacy("C21")])
    assert regulator_role(big, blank) == POOL_STORAGE
    assert "recovered '22uF'" in _pool_reason(big, blank)
    # ... and with no recovery at all the reader keeps its old answer.
    assert regulator_role(
        CapCandidate(designator="C21", mpn=LEGACY_MPN), blank
    ) == ""


def test_the_measured_fixture_part_is_the_issue_s_witness():
    """``CC0805KRX7R9BB104`` — the MPN of 毕设FOC PCB1's ``C30`` — decodes.

    The board-level consequence is pinned where the board is
    (``tests/test_126b_pcb_distance_rules.py``); this is the reason it moved,
    stated in the one place a reader of this file will look for it: ``C30`` has
    no ``Value`` on that fixture, its MPN's ``104`` is 100 nF, and the shelf
    entry for the same code (``cap.100n_0603.c14663``) agrees.
    """
    assert recovered_capacitance("C30", LEGACY_NEARBY_MPN, "C49678", None) == (
        "100nF", VALUE_SOURCE_MPN,
    )

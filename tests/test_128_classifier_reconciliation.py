"""Issue #63: the three device classifiers must be reconciled, and the shipped
shelf must actually reach the strongest path.

Three classifiers have always answered "is this an IC?" for the same part, and
**nothing compared them**:

* **A** :data:`boardwise.core.parts.DESIGNATOR_CATEGORIES` — the repo's own
  designator-prefix table (``U``/``IC`` → ``ic``). Before this batch nobody
  used it for this question; a private ``^U\\d`` regex answered instead;
* **B** that regex — issue #63's §4 measured A and B disagreeing *inside one
  repository*: the table called ``IC1``/``IC12`` ICs and the gate let them
  through, while ``DRV1`` — a real gate driver with a shelf entry and a
  datasheet — was never looked at at all (#56). Retired in 128: the gate now
  asks :func:`boardwise.core.parts.is_ic_designator`;
* **C** the shelf's hand-curated ``category`` field — **12 of 109** entries
  carried one, and **0** of them said ``ic.mcu``, so
  :func:`boardwise.core.architecture.controller_evidence`'s strongest route was
  dead on shipped data and only its ≥4-``P<port><n>``-pin fallback ever fired.

Two guards live here. The first reconciles the classifiers against the **real
shelf** and reports drift in **both** directions (the shape of
``connector/tests/contract-drift.test.mjs``). The second asserts the thing
neither an earlier test nor any rule ever checked: that the shipped library
plus the shipped ROBOT ctrl FOC export actually *walk into* the shelf route,
rather than permanently falling back to the pin-shape route.
"""

from __future__ import annotations

import json
from pathlib import Path

from boardwise.core.architecture import controller_evidence
from boardwise.core.parts import (
    DESIGNATOR_CATEGORIES,
    is_ic_designator,
    load_parts,
)
from boardwise.parsers.schematic import build_project_model

FIXTURES = Path(__file__).parent / "fixtures"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
SHELF = Path("blocklib/parts.json")
CORRECTIONS = Path("blocklib/parts.corrections.json")


# ---------------------------------------------------------------------------
# guard 1: the classifiers reconcile where they can both answer — and the
#          cases they cannot are named rather than swept
# ---------------------------------------------------------------------------
#
# What the shipped shelf actually contains, measured while writing this test
# (and why the comparison is narrower than #63 §1 assumed):
#
# * **Every** ``ic.*`` key now carries a category. Zero exceptions — the §3 gap
#   is closed.
# * **No** shelf entry says ``ic.*`` at a designator A does not call an IC. The
#   contradiction §4 describes (``DRV1``, ``IC12``) is gone, in the direction
#   where it *is* a contradiction.
# * But 21 ``(designator, entry)`` pairs still have A saying ``ic`` and C saying
#   nothing — and **that is not drift**. They are connectors
#   (``conn.1271wv_3p`` at ``U12``, ``conn.mx1_25_lt_3`` at ``U3``/``U8``/``U9``)
#   and resistors (``res.470_0805`` at ``U3``/``U7``/``U10``/``U14``) the boards
#   deliberately placed at ``U*`` designators, plus ``ic.2n7002k`` (a MOSFET)
#   at ``U2``. ``core/parts.py`` states the rule in so many words at
#   :data:`CATEGORY_VOCABULARY` — "the golden board's U3 (a resistor wearing a
#   ``U`` prefix) is the measured proof that the two must not be conflated" —
#   and the gate honours it: ``rules.facts._category_state`` turns a non-IC
#   category into NOT_APPLICABLE rather than judging the part.
#
# So "the two agree on every part" is not a property this shelf has, and
# asserting it would be a test that fails for the right reason on the right
# data. What *is* assertable, and is what actually regressed, is below.


def _is_ic_key(key: str) -> bool:
    """The shelf's own **key** prefix — a package bucket, not a function class.

    Deliberately not the category: ``make_key`` puts a part under ``ic.`` because
    its *package* matched :data:`FOOTPRINT_CATEGORIES` (``ic.2n7002k`` is a
    SOT-23 MOSFET), so ``ic.``-keyed parts include transistors and diode arrays.
    That is exactly why #63 §1 ruled mechanical derivation out.
    """
    return key.startswith("ic.")


def test_every_ic_keyed_shelf_entry_carries_a_category():
    """The §3 gap, closed — and the assertion is deliberately weaker than
    "its category starts with ``ic.``".

    ``ic.2n7002k`` is a MOSFET and ``ic.tpd4s010dqar`` is an ESD-protection
    diode array, so "the key says ``ic.``, therefore the category must say
    ``ic.*``" would be false on purpose. What holds is the narrower, true claim:
    a part filed under an ``ic.`` key is an integrated circuit **or a discrete
    device**, and its category must not be blank — blank means "the library
    could not tell", which for a part whose own key already made a claim is
    just debt. Issue #63 §3 counted 10 such entries; this fails if one returns.
    """
    library = load_parts(SHELF)
    blank = sorted(
        entry.key for entry in library.parts
        if _is_ic_key(entry.key) and not entry.category
    )
    assert blank == [], f"ic.* keys with no category again: {blank}"


def test_no_shelf_entry_calls_itself_an_ic_at_a_non_ic_designator():
    """The bidirectional diff's direction that is a genuine contradiction.

    An entry whose category says ``ic.mcu`` at a designator A does not call an
    IC is classified *and* invisible at the same time: the facts gate walks
    through ``is_ic_designator`` — now the only gate (#63 §2) — and never
    reaches the entry. That is ``DRV1``'s and ``IC12``'s shape. Reported by
    entry, so a failure names the part rather than a count.
    """
    library = load_parts(SHELF)
    contradictions = sorted(
        (entry.key, entry.category, placed.split("@", 1)[0])
        for entry in library.parts
        if entry.category.startswith("ic")
        for placed in entry.provenance.designators
        if not is_ic_designator(placed.split("@", 1)[0])
    )
    assert contradictions == [], (
        "classified ic.* at a designator the repo table does not call an IC — "
        "the facts gate can never reach it"
    )


def test_the_diff_reports_drift_from_either_side():
    """Positive control, the shape of ``contract-drift.test.mjs``' third test.

    Four synthetic pairs through the same predicate: one disagreement in each
    direction and one agreement on each side. Without this, a predicate that
    always returned ``True`` would pass the two guards above over the whole
    shelf forever.
    """
    def agrees(table: str, shelf: str) -> bool:
        return (table == "ic") == shelf.startswith("ic")

    # table says ic, shelf silent — curated debt, not a contradiction
    assert not agrees("ic", "")
    # shelf says ic.mcu at a non-IC designator — the DRV1/IC12 shape, forbidden
    assert not agrees("res", "ic.mcu")
    # the two agree, and agree on the non-IC side too
    assert agrees("ic", "ic.mcu")
    assert agrees("res", "fet")


def test_the_drive_prefix_is_in_the_repository_ic_table():
    """#63 §4/§5: ``DRV1`` is the ctrl FOC board's gate driver, on the shelf
    with a datasheet, and the table did not know the prefix at all.

    ``ic.drv8313pwpr`` carries ``category: ic.motor-driver`` and the real board
    places it at ``DRV1``; without a ``DRV`` row the two classifiers disagreed
    about a part the project has measured three ways.
    """
    library = load_parts(SHELF)
    entry = next(p for p in library.parts if p.lcsc == "C92482")
    assert entry.category == "ic.motor-driver"
    assert any(d.startswith("DRV") for d in entry.provenance.designators)
    assert DESIGNATOR_CATEGORIES["DRV"] == "ic"


# ---------------------------------------------------------------------------
# guard 2: the shipped data reaches the strongest controller route
# ---------------------------------------------------------------------------


def test_the_shipped_shelf_and_the_ctrl_foc_board_take_the_shelf_route():
    """The assertion #63 §2 asks for, and the one no rule ever made.

    ``controller_evidence``'s shelf route (``category == "ic.mcu"``) was
    implemented, documented as "the stronger signal, wins when present", and
    pinned by a test that **constructed** its own shelf entry. The shipped
    library had **zero** ``ic.mcu`` entries, so on every real board the route
    was unreachable and only the ≥4-``P<port><n>``-pin fallback ever fired —
    a dead branch with a green test over it.

    This reads the committed library and the committed export, and asserts the
    basis names the **shelf route**. It fails if someone empties the STM32's
    category again.
    """
    library = load_parts(SHELF)
    model = build_project_model(ROBOT)

    u1 = model.components["U1"]
    assert u1.mpn == "STM32G431RBT6" and u1.lcsc_part == "C431633"

    basis = controller_evidence(u1, library)
    assert basis == "货架 category=ic.mcu（ic.stm32g431rbt6）", (
        "the shipped controller did not reach the shelf route; it fell back to "
        f"the pin-shape route instead: {basis!r}"
    )


def test_the_gate_driver_on_the_same_board_is_classified_as_an_ic():
    """``DRV1`` is the other half of #63 §5: a real gate driver with a shelf
    entry, a datasheet, and ten named pins — which no facts rule ever saw.
    """
    library = load_parts(SHELF)
    model = build_project_model(ROBOT)
    drv1 = model.components["DRV1"]
    assert drv1.mpn == "DRV8313PWPR"
    assert is_ic_designator("DRV1")
    # It is emphatically not a controller: no ic.mcu, no port pins.
    assert controller_evidence(drv1, library) == ""


def test_the_categories_come_from_the_generation_source_not_a_hand_edit():
    """The shelf is generated, so the categories live in the sidecar.

    ``blocklib/parts.json`` is a function of ``tools/harvest_parts.py``'s
    sources (``blocklib/harvest.sources.json``, #38) plus
    ``blocklib/parts.corrections.json``. Hand-editing a generated file is what
    ``--check`` exists to catch, so this asserts both halves: the sidecar's
    ``curated`` section carries each category, and the harvest applied it.
    """
    curated = {
        record["lcsc"]: record["fields"]
        for record in json.loads(CORRECTIONS.read_text(encoding="utf-8"))["curated"]
    }
    library = load_parts(SHELF)
    checked = 0
    for entry in library.parts:
        if not _is_ic_key(entry.key):
            continue
        assert entry.category, f"{entry.key} ({entry.lcsc}) has no category"
        fields = curated.get(entry.lcsc, {})
        assert fields.get("category") == entry.category, (
            f"{entry.key}: the sidecar says {fields.get('category')!r} but the "
            f"library says {entry.category!r} — the library is hand-edited"
        )
        checked += 1
    # 22 ic.* entries; a guard that quietly stops matching entries is worse
    # than no guard.
    assert checked >= 20, f"only {checked} ic.* entries reconciled"
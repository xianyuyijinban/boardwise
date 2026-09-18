"""Tests for the 006b revision-4 placement verifier (``core.verify``).

The verifier is what stands between the replay and a *confidently* broken
page. Round 4's 51 differences came from replayed endpoints missing pin tips
on a part whose library had been redrawn; the verifier must catch exactly
that, and must not manufacture a mapping it cannot justify.

The fixtures are the real pair: the golden ``.epro2`` and the golden page's
own editor netlist, which agree pin for pin. The drifted case is built from
that pair by renumbering USB1 the way the measured library did.
"""

from __future__ import annotations

import copy

import pytest

from boardwise.core.candidate import candidate_from_netlist
from boardwise.core.model import Component, DesignModel, Pin
from boardwise.core.verify import (
    MATCH_DRIFTED,
    MATCH_EXACT,
    MATCH_UNMAPPABLE,
    build_pin_map,
    verify_placements,
)
from boardwise.parsers.schematic import build_schematic_model

GOLDEN = "tests/fixtures/ch340_golden.epro2"
EDITOR_NETLIST = "tests/fixtures/ch340_p1_editor_netlist.json"

#: The Type-C pad numbering the measured library moved USB1 to (round 4, §E).
USB1_PAD_NUMBERS = [
    "A1B12", "B1A12", "A4B9", "B4A9", "A5", "B5", "A6",
    "B6", "A7", "B7", "A2", "B2", "A3", "B3",
]


@pytest.fixture(scope="module")
def golden() -> DesignModel:
    return build_schematic_model(GOLDEN)


@pytest.fixture(scope="module")
def placed(golden) -> DesignModel:
    import pathlib

    text = pathlib.Path(EDITOR_NETLIST).read_text(encoding="utf-8")
    return candidate_from_netlist(text, "EasyEDA")


def _drift(pins: list[Pin], numbers: list[str]) -> Component:
    """The same pins, renumbered — names and nets untouched."""
    out = Component(uid="usb", designator="USB1")
    for old, new in zip(pins, numbers):
        out.pins.append(Pin(number=new, name=old.name, net=old.net))
    return out


# --- the identity baseline -------------------------------------------------


def test_every_golden_part_matches_its_own_netlist(golden, placed):
    """The instrument is calibrated: golden vs its own export, all exact."""
    report = verify_placements(golden, placed)
    assert report.ok
    assert not report.unmappable
    assert not report.drifted
    assert not any(report.orphan_pins.values())
    assert len(report.checks) == len(golden.components)


def test_exact_match_is_by_number(golden, placed):
    pin_map = build_pin_map(
        "U1", golden.components["U1"], placed.components["U1"]
    )
    assert pin_map.kind == MATCH_EXACT
    assert pin_map.ok
    # Identity: a number maps to itself when nothing drifted.
    assert pin_map.remap("1") == "1"


# --- the drift case the verifier exists for --------------------------------


def test_renumbered_part_maps_by_name(golden, placed):
    """USB1's library renumbered 1..14 to pad names; names must carry it."""
    drifted = _drift(placed.components["USB1"].pins, USB1_PAD_NUMBERS)
    pin_map = build_pin_map("USB1", golden.components["USB1"], drifted)

    assert pin_map.kind == MATCH_DRIFTED
    assert pin_map.ok
    assert len(pin_map.pairs) == 14
    # Pin 1 is GND on both sides: the mapping must respect the signal, not
    # the position in the list.
    golden_1 = next(p for p in golden.components["USB1"].pins if p.number == "1")
    placed_target = next(
        p for p in drifted.pins if p.number == pin_map.remap("1")
    )
    assert placed_target.name == golden_1.name


def test_drift_reports_but_does_not_block(golden, placed):
    """A drift is information for the report — the endpoints get remapped."""
    board = copy.deepcopy(placed)
    board.components["USB1"] = _drift(
        placed.components["USB1"].pins, USB1_PAD_NUMBERS
    )
    report = verify_placements(golden, board)

    assert report.ok, "a name-mappable drift must not block the draw"
    assert [c.designator for c in report.drifted] == ["USB1"]
    assert "drifted" in report.drifted[0].detail
    assert not report.orphan_pins


# --- the refusal cases -----------------------------------------------------


def test_absent_part_is_unmappable(golden):
    pin_map = build_pin_map("R24", golden.components["R24"], None)
    assert pin_map.kind == MATCH_UNMAPPABLE
    assert not pin_map.ok
    assert "not present" in pin_map.detail


def test_wrong_part_is_unmappable_and_blocks(golden, placed):
    """A part with neither the golden's numbers nor its names is a refusal."""
    board = copy.deepcopy(placed)
    # R24's golden pins are "1"/"2"; this stands in a different device whose
    # pins are neither the same numbers nor recognisable names.
    board.components["R24"] = Component(
        uid="x", designator="R24",
        pins=[Pin(number=n, name=nm, net=None)
              for n, nm in (("A", "ANODE"), ("K", "CATHODE"))],
    )
    report = verify_placements(golden, board)
    assert not report.ok
    assert "R24" in [c.designator for c in report.unmappable]
    assert "R24" in report.blocks()
    assert report.unmappable[0].pin_map.detail.startswith("no pin mapping")


def test_extra_pad_is_reported_as_orphan(golden, placed):
    """An extra pin the golden does not know about must surface, not vanish."""
    board = copy.deepcopy(placed)
    comp = board.components["R24"] = copy.deepcopy(placed.components["R24"])
    comp.pins.append(Pin(number="99", name="EXTRA", net=None))
    report = verify_placements(golden, board)
    assert report.orphan_pins.get("R24") == ["99"]
    assert not report.ok
    assert "extra pins on: R24" in report.blocks()


def test_unnamed_pins_cannot_use_the_name_fallback(golden, placed):
    """With no names on either side there is nothing to map by — refuse."""
    golden_comp = Component(
        uid="g", designator="U9",
        pins=[Pin(number=n, name="", net=None) for n in ("1", "2")],
    )
    placed_comp = Component(
        uid="p", designator="U9",
        pins=[Pin(number=n, name="", net=None) for n in ("X", "Y")],
    )
    pin_map = build_pin_map("U9", golden_comp, placed_comp)
    assert pin_map.kind == MATCH_UNMAPPABLE
    assert not pin_map.ok


# --- the map is usable by the replay ---------------------------------------


def test_the_machines_own_usb1_matches_hybrid(golden):
    """The real thing: the library renamed 12 pins to pad names, kept 13/14.

    Captured from the editor on 2026-09-14 (`ch340_drawn_page_netlist.json`,
    the page `boardwise draw` actually placed). It is the case that defeated
    both pure strategies: goldens `1..12` became ``A1B12``/``B4A9``/``B5``…
    (so "all by number" fails), while ``13``/``14`` kept their numbers and the
    differential pairs only changed *case* (``DN2`` -> ``Dn2``) and ``SHELL``
    became ``EH`` (so "all by name" fails too). The matcher has to take the
    surviving numbers by number and the rest by name.
    """
    import pathlib

    text = pathlib.Path("tests/fixtures/ch340_drawn_page_netlist.json").read_text(
        encoding="utf-8"
    )
    drawn = candidate_from_netlist(text, "EasyEDA")
    pin_map = build_pin_map(
        "USB1", golden.components["USB1"], drawn.components["USB1"]
    )

    assert pin_map.kind == MATCH_DRIFTED
    assert pin_map.ok
    assert len(pin_map.pairs) == 14
    # 13/14 survived the redraw, so they are matched by number.
    assert pin_map.remap("13") == "13"
    # DN2 -> Dn2: the same signal, a different capitalisation.
    assert pin_map.remap("5") == "B7"
    # GND (pin 1) lands on a GND pad, not merely on *some* pad.
    placed_by_number = {p.number: p.name for p in drawn.components["USB1"].pins}
    assert placed_by_number[pin_map.remap("1")].upper() == "GND"

    report = verify_placements(golden, drawn)
    assert report.ok
    assert [c.designator for c in report.drifted] == ["USB1"]
    assert not report.unmappable


def test_remap_is_identity_when_exact_and_counterpart_when_drifted(golden, placed):
    exact = build_pin_map("U1", golden.components["U1"], placed.components["U1"])
    assert exact.remap("7") == "7"

    drifted = build_pin_map(
        "USB1",
        golden.components["USB1"],
        _drift(placed.components["USB1"].pins, USB1_PAD_NUMBERS),
    )
    assert drifted.remap("1") != "1"
    assert drifted.remap("1") in USB1_PAD_NUMBERS

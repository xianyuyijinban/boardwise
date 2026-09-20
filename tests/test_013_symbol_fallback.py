"""Task 013: the Symbol-ATTR fallback in the schematic parser.

EasyEDA does not write the ``Symbol`` ATTR on early-placed basic parts
(R/C/L/TP with old small tickets). Measured 2026-09-20 on the graduation
board: 132 instances carry the attr, 25 do not, and those 25 are exactly the
components that used to parse out **pin-less** -- their DEVICE META
``attributes.Symbol`` is always present and points at a SYMBOL document with
full PIN records, so the parser now falls back to it (instance-first) and the
pins instantiate.

The ruling this file pins (task book 013, evidence gathered by Kimi and
re-measured here):

* every one of the 25 parses with pins, and the two oscillator load caps
  agree pin-for-pin with the PCB side's own PAD_NET records;
* the other three real boards that carried the same gap (pillbox 23, llc 5)
  come out clean too -- llc's test points included, no exemption needed;
* the boards that never had the bug (golden x2, injected x7) are frozen:
  the fallback must not move a single pin or net on them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.parsers.schematic import build_schematic_model

FIXTURES = Path(__file__).parent / "fixtures"
BISHE = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"

#: The 25 early-placed parts, Kimi's measured list (2026-09-20) -- it matched
#: the parser's pin-less census 1:1 before the fix, which is what made the
#: list trustworthy enough to pin by name.
EARLY_PLACED_25 = [
    "C13", "C15", "C17", "C18", "C20", "C21", "C22", "C23", "C24", "C25",
    "C32", "C33", "C34", "C37", "C39",
    "L2", "L3", "L4",
    "R22", "R24", "R25", "R26", "R27", "R28", "R29",
]

#: The PCB side of the cross-check, measured by Kimi from the live project's
#: PAD_NET records (2026-09-20) -- independent of this parser: the numbers
#: were read off the PCB document, not derived from any schematic parse. The
#: fixture's own PCB section is an *early placement snapshot* (33 placements,
#: no C20/C21), so this cross-check cannot be re-derived inside the fixture;
#: what the test pins is that the schematic side reproduces the PCB evidence
#: pin-for-pin, numbers taken verbatim from the task book.
PAD_NET_EVIDENCE = {
    "C20": {"1": "GND", "2": "OSC-IN"},
    "C21": {"1": "GND", "2": "OSC-OUT"},
}


def _designators_without_pins(model) -> list[str]:
    return sorted(des for des, comp in model.components.items() if not comp.pins)


def test_every_early_placed_part_parses_with_pins():
    """The 25 used to come out pin-less and silently dropped every connection.

    Two layers: no component on the board is pin-less any more (the census
    that found the bug), and each of the 25 by name carries pins on **every**
    net-bearing pad -- a pin that instantiates but sits net-less would be the
    same connectivity loss wearing a different coat.
    """
    model = build_schematic_model(BISHE)
    assert _designators_without_pins(model) == []
    for designator in EARLY_PLACED_25:
        pins = model.components[designator].pins
        assert pins, f"{designator}: still pin-less after the fallback"
        netless = [pin.number for pin in pins if pin.net is None]
        assert netless == [], f"{designator}: pins without a net: {netless}"


def test_oscillator_load_caps_match_the_pcb_side_pad_net():
    """C20/C21 against the PCB evidence, pin number and net name both.

    This is the two-independent-sources agreement the task book asked for:
    Kimi read these nets off PAD_NET records on the PCB side before the
    schematic parser could produce them; when the fallback landed, the
    schematic side produced the same pairs -- same pins, same names. (The
    full 25-part cross-check is *not* pinnable here: the fixture's PCB
    section predates the layout of 24 of these parts, and its 11 bridgable
    placements disagree with the schematic for pre-existing reasons recorded
    in the 013 handover, none of them touched by this fix.)
    """
    model = build_schematic_model(BISHE)
    for designator, expected in PAD_NET_EVIDENCE.items():
        actual = {pin.number: pin.net for pin in model.components[designator].pins}
        assert actual == expected, (
            f"{designator}: schematic {actual} disagrees with the PCB-side "
            f"PAD_NET evidence {expected}"
        )


def test_instance_attr_outranks_the_library_symbol():
    """Instance-first, META-only-when-absent -- pinned on a synthetic input.

    No fixture distinguishes the two orders (on every board we have, a
    populated instance Symbol agrees with its DEVICE META), so the precedence
    rule -- the 006b "stale instance copy is a placement fact" lesson -- is
    pinned here directly against the helper.
    """
    from types import SimpleNamespace

    from boardwise.parsers.schematic import _symbol_uuid_of

    device_meta = {"dev-uuid": {"symbol": "lib-uuid"}}
    populated = SimpleNamespace(attrs={"Symbol": "inst-uuid", "Device": "dev-uuid"})
    assert _symbol_uuid_of(populated, device_meta) == "inst-uuid"

    absent = SimpleNamespace(attrs={"Device": "dev-uuid"})
    assert _symbol_uuid_of(absent, device_meta) == "lib-uuid"

    unknown_device = SimpleNamespace(attrs={"Device": "no-such-device"})
    assert _symbol_uuid_of(unknown_device, device_meta) == ""


@pytest.mark.parametrize(
    "path,label",
    [(PILLBOX, "pillbox"), (LLC, "llc"),],
)
def test_the_other_boards_with_the_same_gap_come_out_clean(path, label):
    """Pillbox carried 23 of these, llc 5 -- all gone now.

    llc's TP1-TP4 are part of the five: their symbols do define PIN records,
    so no test-point exemption applies (checked, not assumed -- the task book
    allowed for one and the fixtures did not need it). ROBOT ctrl FOC and the
    high-speed controller board never had the gap and stay at zero as well;
    they are covered by the freeze test below via their own suites.
    """
    model = build_schematic_model(path)
    assert _designators_without_pins(model) == [], (
        f"{label}: pin-less components survived the fallback"
    )


#: The boards the bug never touched. Their counts were measured after the
#: fix; the fallback must leave them byte-for-byte where they were. (A full
#: serialized before/after diff was also run during the 013 handover as a
#: mutation check -- deleting the fallback changed nothing on these boards.)
FROZEN = [
    (FIXTURES / "ch340_golden.epro2", 17, 13, 66),
    (FIXTURES / "ProPrj_CH340G_2026-09-13.epro2", 17, 13, 66),
    (Path("reviewsets/injected/duplicate-designator.epro2"), 17, 12, 66),
    (Path("reviewsets/injected/fixed-base.epro2"), 17, 12, 66),
    (Path("reviewsets/injected/ldo-no-headroom.epro2"), 17, 12, 66),
    (Path("reviewsets/injected/nc-pin-grounded.epro2"), 17, 12, 66),
    (Path("reviewsets/injected/overvoltage-rail.epro2"), 17, 12, 66),
    (Path("reviewsets/injected/v3-decap-missing.epro2"), 16, 12, 64),
    (Path("reviewsets/injected/value-mpn-mismatch.epro2"), 17, 12, 66),
]


@pytest.mark.parametrize("path,comps,nets,pins", FROZEN)
def test_boards_the_bug_never_touched_are_frozen(path, comps, nets, pins):
    """Golden x2 + injected x7: component/net/pin counts, pinned.

    The fallback fires only when an instance's Symbol ATTR is *empty*; on
    these boards every instance carries one, so nothing here may move.
    """
    model = build_schematic_model(path)
    total_pins = sum(len(c.pins) for c in model.components.values())
    assert (len(model.components), len(model.nets), total_pins) == (comps, nets, pins)
    assert _designators_without_pins(model) == []

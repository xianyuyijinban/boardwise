"""520B2: the rail seat ladder widened over the net's own pads, and its ceiling.

520B's diagnosis (`evidence/520b/flag-seat.md`) measured the flyback page dying at
`SEC_12V`'s flag: the rail's own symbol was allowed **one** pad — the pin it
supplies, `D3.1` — and that pad has 11.5 units of clearance up (the diode's own
body) and a text row down, so `_rail_flag_room_failure` refused the page while
four other pads of the same net stood clear. Two things changed, and this file
pins both:

* :func:`boardwise.engines.drawcompiler._flag_seat_pins` — a rail walks the same
  ladder a ground already walked (the supplying pin first, then that net's
  remaining pads, **nearest first**), and
  :func:`boardwise.engines.drawcompiler._seat_wire_flags` — a rail takes **one**
  seat off that ladder, however many of its pads could hold one;
* :data:`boardwise.engines.drawcompiler.FLAG_LEAD_LIMIT` — the ladder has a
  ceiling now. It had none: 520B's Q5 measured a legal, 120-unit-long lead being
  preferred over a 30-unit one, and judged it "readable but pointed at the wrong
  place".

Fixtures are hand-written here and in the sibling test modules; nothing in this
file reads a spec file, talks to a bridge, or writes to disk.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from boardwise.engines import drawcompiler as dc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import test_053b_drawcompiler as b053  # noqa: E402
import test_201a_flags as t201a  # noqa: E402


# ------------------------------------------------------------------ the ladder


def _ctx(chain: tuple[str, ...]):
    """A context whose `slots` names the chain parts, and nothing else.

    `_flag_seat_pins` asks exactly two questions of it — "is this part the
    core's?" (`ctx.slots[...].kind`) and, for a ground, "where is the inlet?"
    (`ctx.presentation.side_for`) — so a stub with those two answers is the whole
    of what the ladder reads.
    """
    return types.SimpleNamespace(
        slots={
            part: types.SimpleNamespace(
                kind="chain" if part in chain else "branch"
            )
            for part in ("U1", "C1", "C2", "C3")
        },
        presentation=types.SimpleNamespace(side_for=lambda role: "left"),
    )


def _expression(net, style, points):
    return dc._Expression(
        net=net, style=style,
        points=tuple((member, (float(x), float(y))) for member, x, y in points),
        reason="the ladder test states its own pads",
    )


def test_a_rail_ladder_reaches_every_pad_of_its_own_net_nearest_first():
    """520B2: the supplying pin first, then the net's pads by distance from it.

    The pads here are `U1.8` (the chain part's, so the pin the rail supplies) and
    three pads at 25, 35 and 90 units from it — the shape the flyback page has,
    where `D3.1` supplies `SEC_12V` and `R7.1`, `C13.1`, `R9.1` and `C11.1` are
    the pads the symbol could have stood on instead.
    """
    expression = _expression("VCC", "wire", [
        ("C1.1", -25.0, 0.0),
        ("C2.1", 35.0, 0.0),
        ("C3.1", -90.0, 0.0),
        ("U1.8", 0.0, 0.0),
    ])
    ladder = dc._flag_seat_pins(_ctx(("U1",)), expression, "power")
    assert [member for member, _point in ladder] == [
        "U1.8", "C1.1", "C2.1", "C3.1",
    ], (
        "a rail's ladder is the pin it supplies and then the net's pads, nearest "
        f"first — 520B measured `SEC_12V` stuck on its one supplying pad: {ladder}"
    )


def test_a_rail_with_no_chain_part_still_walks_its_pads():
    """A net nothing supplies is the same ladder, from its first pad by id.

    That head is `_power_flag_pin`'s own second half; 520B2 keeps it as the head
    of the ladder rather than as the whole of it.
    """
    expression = _expression("VCC", "wire", [
        ("C1.1", 0.0, 0.0),
        ("C2.1", 100.0, 0.0),
        ("C3.1", 10.0, 0.0),
    ])
    ladder = dc._flag_seat_pins(_ctx(()), expression, "power")
    assert [member for member, _point in ladder] == ["C1.1", "C3.1", "C2.1"], (
        f"the head is the first pad by id and the rest follow it outwards: {ladder}"
    )


def test_a_ground_ladder_comes_out_of_the_far_end_first_as_before():
    """088b's reading still heads a ground's ladder — this file adds nothing.

    The far end (背向入口那端) is `_gnd_outlet_pin`'s answer; the rest follow in
    member-id order, which is what 201A and 515A hole 6 already pinned.
    """
    ctx = _ctx(())
    members = ("C1.2", "C2.2", "U1.4", "U1.11")
    points = [
        (member, float(index * 10), 0.0) for index, member in enumerate(members)
    ]
    expression = _expression("GND", "flag", points)
    ladder = dc._flag_seat_pins(ctx, expression, "gnd")
    far = dc._gnd_outlet_pin(ctx, expression)
    assert far is not None, "premise: this ground has a far end at all"
    assert [member for member, _point in ladder] == [far[0]] + [
        member for member in members if member != far[0]
    ], f"the ground ladder moved: {ladder}"


# ------------------------------------------------------------- one seat a rail


def test_a_rail_takes_one_seat_however_many_of_its_pads_are_free(monkeypatch):
    """520B2: the widened ladder must not seat the same rail three times.

    `_seat_wire_flags` reserves the lane the flag will be drawn on, and the box
    it returns is an obstacle for every wire — so a rail that took a seat at
    every pad the ladder can reach walls off three corridors for a symbol that
    stands on one. Measured on the flyback page with the guard taken out: `HVDC`
    took 3 seats and the pass returned 6 wall boxes instead of 4 (the drawn
    symbols stayed one per net, which is why this rule's subject is the
    *reservation* and not the symbol).
    """
    seen: dict[str, int] = {}
    original = dc._seat_wire_flags

    def counting_seat_wire_flags(ctx, placed, expressions, net_order, router,
                                 solids, bodies, tips, taken):
        walls = original(ctx, placed, expressions, net_order, router, solids,
                         bodies, tips, taken)
        counts: dict[str, int] = {}
        for net_id, _member in router.flag_seats:
            counts[net_id] = counts.get(net_id, 0) + 1
        if counts:
            seen.clear()
            seen.update(counts)
        return walls

    monkeypatch.setattr(dc, "_seat_wire_flags", counting_seat_wire_flags)
    circuit, presentation, library = _multi_pad_rail_page()
    dc.compile(circuit, presentation, library, dc.CompileBudget())
    assert seen, "premise: the reservation pass has to take some seat at all"
    assert max(seen.values()) == 1, (
        "a rail carries one symbol, so it may take one seat: "
        f"{seen} — the first pad of its ladder that fits is the answer and the "
        "rest of that net's candidates are passed over"
    )


def _multi_pad_rail_page():
    """`U1` (the core, so the rail's supplying part) + two capacitors on `VCC`.

    Hand-written, like its neighbours in `test_201a_flags`; the library carries a
    `PWR-VCC` glyph so the net really wants one symbol.
    """
    library = t201a.book()
    library["PWR-VCC"] = b053.flag("PWR-VCC")
    circuit = b053.circuit(
        [
            b053.part("U1", "OPAMP-2GND-EP", "OPA2GND"),
            b053.part("C1", "C0402", "100n"),
            b053.part("C2", "C0402", "10u"),
        ],
        [
            b053.net("VCC", "power", ["U1.8", "C1.1", "C2.1"]),
            b053.net("GND", "gnd", ["U1.4", "U1.11", "C1.2", "C2.2"]),
            b053.net("INP", "signal", ["U1.3"]),
            b053.net("INN", "signal", ["U1.2"]),
            b053.net("OUT", "signal", ["U1.1"]),
        ],
    )
    presentation = b053.presentation(
        "ic-periphery",
        modules=[{"id": "amp", "parts": ["U1", "C1", "C2"], "role": "amp",
                  "core": "U1"}],
        portRoles={"INP": "input", "OUT": "output"},
    )
    return circuit, presentation, library


# ------------------------------------------------------------- the lead ceiling


def _router():
    return dc.lattice_router(
        grid=5.0, residue=(0.0, 0.0), boxes=(), bounds=(0.0, 0.0, 800.0, 800.0),
    )


def test_a_lead_that_only_fits_past_the_ceiling_is_refused_not_drawn():
    """520B2: no rung may reach past :data:`FLAG_LEAD_LIMIT`.

    The `fits` predicate here is the page at its worst: the only room left is 100
    units out. Without a ceiling the ladder's last reach (`4 * FLAG_LEAD`) answers
    that with a lead 120 units long — 520B's Q5 measured exactly that shape being
    preferred over a 30-unit one and judged it "readable but pointed at the wrong
    place". A pad that crowded gets the loud refusal, not a long run.
    """
    pin = (200.0, 200.0)
    anchor, lead, _hang = dc._flag_anchor(
        _router(), pin, (1.0, 0.0), set(),
        fits=lambda here, _hang: here[0] >= pin[0] + 100.0,
    )
    assert lead is None, (
        f"a lead {lead} was drawn past the {dc.FLAG_LEAD_LIMIT:g}-unit ceiling — "
        "069 sec.3's ceiling is where a pin's reach stops being a stub"
    )
    assert anchor == pin


def test_the_ceiling_still_offers_the_rung_it_was_derived_from():
    """The ceiling is not a tightening of 069's own band: 60 stays a rung.

    `SIBLING_LEAD` is 069 sec.1's middle (its band is 40-60) and 069 sec.3's
    ceiling is 60, which is this constant's value — so the ladder must still
    answer a pad whose only free room is 60 units out.
    """
    pin = (200.0, 200.0)
    anchor, lead, _hang = dc._flag_anchor(
        _router(), pin, (1.0, 0.0), set(),
        fits=lambda here, _hang: abs(here[0] - pin[0]) >= 59.0,
    )
    assert lead is not None, "the 60 rung is inside 069's own band and must stay"
    assert abs(lead[1][0] - pin[0]) == dc.FLAG_LEAD_LIMIT, (
        f"the rung inside the ceiling is {dc.FLAG_LEAD_LIMIT:g}: {lead}"
    )


def test_the_ceiling_is_069s_own_number():
    """The value, stated once: `2 * FLAG_LEAD` — 069 sec.3's 60.

    Written as arithmetic rather than as a bare literal so it cannot drift away
    from the constant it was read off.
    """
    assert dc.FLAG_LEAD_LIMIT == pytest.approx(2.0 * dc.FLAG_LEAD)
    assert dc.FLAG_LEAD_LIMIT == pytest.approx(60.0)
    assert dc.FLAG_LEAD <= dc.SIBLING_LEAD <= dc.FLAG_LEAD_LIMIT

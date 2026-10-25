"""530B: every part stands beside the pin it serves — the pin-based island layout.

The batch's contract is ``evidence/523/DESIGN.md`` §1 (the anchor, the service
tree, the position, the row of centres), §2 (decoupling parts) and §3 (rows), and
it replaces `layout_island`'s hub-and-ring — 「不是摆一个环让它看起来很紧凑，
根本不是给人类看的东西」 (岳 2026-10-20, `docs/schematic-style-spec.md`) — with
`place_service_tree`.  This file measures each clause of it:

**A. the anchor** — a 3-pin-or-more part chosen on the island's own **signal**
nets, with the degree rule as the documented fallback (§1.1);

**B. 贴引脚** — a served part sits at ``tip(served pin) + d * lead``, its own pin
turned back at the pin it serves, and no two pins are ever butted (S-04, S-13);

**C. 去耦** — a two-pin part across a rail and a ground stands beside the **rail's**
pin (S-05), ≤ 30 by tip-to-tip measurement, and a rail nobody decouples is
accounted rather than refused (§2.2-§2.3);

**D. 成排** — same library symbol, same father, same served-pin direction word:
one row, at a pitch derived from the parts' own spans and the designators' own
widths (§3).  `value` is deliberately **not** in that key, and the fixture proves
it by putting three different values on one row.

**E. the real document** — the three acceptance readings the batch states
(two-pin part to the pin it serves: median ≤ 25; decoupling part ≤ 30; rotated
text 0), and the single-island path's own byte-for-byte invariance.

The S-06 fixtures are synthetic on purpose: the design measured that the flyback
island page cannot test 「≥3 等距成排」 at all — its only same-row pair is
`R4`/`R5` (`DESIGN` §3.1), and a test that passed there would be a test that
measured nothing.
"""

from __future__ import annotations

import itertools
import json
import statistics
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

PROV = "verified_recipe"


# ------------------------------------------------------------- the real flyback



def _overlaps(first, second) -> bool:
    return (
        first[0] < second[2] and second[0] < first[2]
        and first[1] < second[3] and second[1] < first[3]
    )


def _library(stem: str) -> dict[str, SymbolProfile]:
    """The library sidecar through the real reader — `SymbolProfile.from_dict`."""
    payload = json.loads(
        (SPECS / f"{stem}.library.json").read_text(encoding="utf-8")
    )
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        profile = SymbolProfile.from_dict(entry)
        book[profile.symbol_ref] = profile
    return book


def _flyback() -> tuple[CircuitSpec, PresentationSpec, dict[str, SymbolProfile]]:
    return (
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
        _library("flyback_uc3845"),
    )


def _flyback_page() -> il.PackedPage:
    circuit, presentation, book = _flyback()
    return il.island_page(circuit, presentation, book)


def _tips(block: il.IslandBlock, circuit: CircuitSpec, book) -> dict[str, tuple[float, float]]:
    """Every pin of a block, where its part's origin and rotation put it."""
    poses = {
        part.part_id: il.SymbolPose(rotation=part.rotation, mirror=part.mirror)
        for part in block.parts
    }
    origins = {part.part_id: (part.x, part.y) for part in block.parts}
    out: dict[str, tuple[float, float]] = {}
    for part in block.parts:
        profile = book[circuit.part(part.part_id).symbol_ref]
        for pin in profile.pins:
            out[f"{part.part_id}.{pin.number}"] = il._posed_point(  # noqa: SLF001
                pin.tip, poses[part.part_id], origins[part.part_id],
            )
    return out


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _blocks() -> dict[str, il.IslandBlock]:
    circuit, presentation, book = _flyback()
    return {
        block.island_id: block
        for block in il.island_blocks(circuit, presentation, book)
    }


# ------------------------------------------------------------- the synthetic kit


def _ic(ref: str, pins: int) -> SymbolProfile:
    """A small IC: ``pins`` pins down its **left** side, a body and nothing else."""
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-30.0, -40.0, 30.0, 40.0),
        pins=[
            SymbolPin(
                number=str(index + 1), tip=(-50.0, 30.0 - 10.0 * index),
                name=f"P{index + 1}", direction="left", length=10.0,
            )
            for index in range(pins)
        ],
    )


def _passive(ref: str = "R0402", length: float | None = 10.0) -> SymbolProfile:
    """Two pins on the vertical axis, tips 50 out — a resistor's own geometry.

    Since 531 it also declares its **text rows** (`reference` at ``(-10, +5)``,
    `value` at ``(-10, -15)`` — the real `R0603` profile's own measured pair). That
    is what a library has to have for the islands' text to be measurable at all: the
    host prints a placed part's designator and value itself, so a profile with no
    anchors is a profile whose rows nobody can say the position of.
    """
    from boardwise.core.symbolprofile import SymbolText

    return SymbolProfile(
        symbol_ref=ref, title="Passive", body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up",
                      length=length),
            SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down",
                      length=length),
        ],
        texts=[SymbolText("reference", -10.0, 5.0), SymbolText("value", -10.0, -15.0)],
    )


def _flag(ref: str, ground: bool) -> SymbolProfile:
    """A flag profile: a glyph box, **no pins** — how the compiler spots a flag."""
    body = (-10.5, 0.0, 10.5, 19.5) if ground else (-5.5, 0.0, 5.5, 10.5)
    return SymbolProfile(symbol_ref=ref, title=ref, body=body, pins=[])


def _part(part_id: str, symbol: str, value: str = "") -> dict:
    return {"id": part_id, "symbolRef": symbol, "value": value, "provenance": PROV}


def _net(net_id: str, cls: str, members: list[str]) -> dict:
    return {
        "id": net_id, "class": cls, "members": list(members), "provenance": PROV,
    }


def _island(
    parts: list[dict],
    nets: list[dict],
    book: dict[str, SymbolProfile],
    *,
    holding: list[str] | None = None,
    roles: bool = False,
) -> tuple[CircuitSpec, il.IslandBlock]:
    """One declared island holding every part given, laid out by the real placer."""
    circuit = CircuitSpec.from_dict({"parts": parts, "nets": nets})
    names = holding or [part["id"] for part in parts]
    presentation = PresentationSpec.from_dict({
        "grammarRef": "flyback",
        "modules": [{"id": "main", "parts": names, "role": "tube"}],
        "islands": [
            {"id": "a", "role": "primary" if roles else "", "parts": names},
        ],
    })
    for subgraph in il.island_subgraphs(circuit, presentation):
        return circuit, il.layout_island(circuit, subgraph, book)
    raise AssertionError("the fixture declared no island")


def _base_book(**extra: SymbolProfile) -> dict[str, SymbolProfile]:
    book: dict[str, SymbolProfile] = {
        "IC6": _ic("IC6", 6), "IC3": _ic("IC3", 3), "R0402": _passive(),
        "PWR-GND": _flag("PWR-GND", ground=True),
        "PWR-VBUS": _flag("PWR-VBUS", ground=False),
        "PWR-RAIL": _flag("PWR-RAIL", ground=False),
    }
    book.update(extra)
    return book


def _service_fixture(
    nets: list[dict] | None = None, *, value: str = "1k"
) -> tuple[CircuitSpec, il.IslandBlock, dict[str, SymbolProfile]]:
    """`U1` (6 pins) with `R1` on its first pin — the smallest 贴引脚 picture."""
    book = _base_book()
    parts = [_part("U1", "IC6", "MCU"), _part("R1", "R0402", value)]
    circuit, block = _island(
        parts,
        nets if nets is not None else [_net("SIG", "signal", ["U1.1", "R1.1"])],
        book,
        holding=[part["id"] for part in parts],
    )
    return circuit, block, book


# ----------------------------------------------------------------------- A: 锚


def test_the_anchor_is_the_islands_ic_not_the_busiest_two_pin_part():
    """`DESIGN` §1.1's first key: the island's own **signal** nets decide the centre.

    `U1` and `U2` are both 3-pin, and `subgraph.anchor()` — which counts *every*
    net — picks `U2` (two nets against `U1`'s one).  `anchor_of` must pick `U1`,
    because `U1`'s single net is a **signal** and `U2`'s two are a rail and a
    ground.  If this goes red, the anchor has fallen back to "the busiest part",
    which is the rule a rail-heavy two-pin part would win.
    """
    from boardwise.core.presentationspec import PresentationSpec as PS

    book = _base_book()
    circuit = CircuitSpec.from_dict({
        "parts": [
            _part("U1", "IC3", "MCU"), _part("U2", "IC3", "LDO"),
            _part("C1", "R0402", "100n"),
        ],
        "nets": [
            _net("S_A", "signal", ["U1.1"]),
            _net("P_B", "power", ["U2.1", "C1.1"]),
            _net("G_B", "gnd", ["U2.2", "C1.2"]),
        ],
    })
    presentation = PS.from_dict({
        "grammarRef": "flyback",
        "modules": [{"id": "main", "parts": ["U1", "U2", "C1"], "role": "tube"}],
        "islands": [{"id": "a", "role": "", "parts": ["U1", "U2", "C1"]}],
    })
    subgraph = il.island_subgraphs(circuit, presentation)[0]
    facts = il._facts(subgraph, circuit, book)  # noqa: SLF001
    assert subgraph.degree("U2") == 2 and subgraph.degree("U1") == 1, (
        "the fixture must have the busier part differing from the signal-busier "
        f"one; got {[(p, subgraph.degree(p)) for p in subgraph.parts]}"
    )
    assert subgraph.anchor() == "U2", "the old rule must pick the busier part"
    assert il.anchor_of(facts, subgraph) == "U1", (
        "the anchor is the island's signal-busiest 3-pin part; a rail and a ground "
        "are buses that pass through, not what the island is about"
    )


def test_an_island_with_no_three_pin_part_gets_the_documented_fallback():
    """No 3-pin part anywhere: `IslandSubgraph.anchor()` decides, ties to the spec.

    The fallback is written down rather than reached by accident (§1.1), and it is
    the degree rule with the spec's own order breaking a tie — so declaring the
    same three parts in another order moves the centre, which is exactly what
    「ties go to the subgraph's own order」 means.
    """
    book = _base_book()
    for order, expected in ((["R1", "R2", "R3"], "R1"), (["R3", "R1", "R2"], "R3")):
        parts = [_part(name, "R0402", "1k") for name in order]
        circuit, block = _island(
            parts,
            [_net("N1", "signal", ["R1.1", "R2.1", "R3.1"])],
            book, holding=order,
        )
        assert block.anchor == expected, (
            f"declared {order}: the fallback anchor is {block.anchor}, expected "
            f"{expected} — every part has one net, so the spec's own order decides"
        )
    for block in _blocks().values():
        if block.island_id != "secondary":
            continue
        assert block.anchor == "D3", (
            "the flyback's `secondary` is `D3` + two capacitors, all two-pin, so it "
            f"is the fallback's own case: anchor {block.anchor}"
        )


def test_the_anchor_sits_at_the_local_origin_and_no_part_escapes_its_island():
    """S-03's 「主 IC 不跑出岛」, read on the block's own frame.

    The anchor holds `(0, 0)` — it is the frame's pole — every part the island
    declares is placed, and no part sits further from the pole than the island's
    own reach (`IslandBlock.ring_radius`, which 530B redefined as exactly that
    distance plus one channel and no longer as a ring's radius).
    """
    circuit, block, book = _service_fixture()
    origins = {part.part_id: (part.x, part.y) for part in block.parts}
    assert origins[block.anchor] == (0.0, 0.0), (
        f"the anchor {block.anchor} is at {origins[block.anchor]}, not the local origin"
    )
    assert set(origins) == {"U1", "R1"}, "the island dropped or invented a part"
    box = block.bbox()
    assert box[2] > box[0] and box[3] > box[1], "the island drew nothing at all"
    for part in block.parts:
        reach = max(
            abs(part.x - origins[block.anchor][0]),
            abs(part.y - origins[block.anchor][1]),
        )
        assert reach <= block.ring_radius + 1e-6, (
            f"{part.part_id} sits {reach:g} from the anchor, past the island's own "
            f"reach {block.ring_radius:g}"
        )


# ------------------------------------------------------------------ B: 贴引脚


def test_a_two_pin_part_lands_beside_the_pin_it_serves():
    """S-04: the served part's own pin tip stands within a pin gap of the served pin.

    `DESIGN` §9.1 #4's own assertion, on a fixture whose geometry is small enough to
    read: `R1`'s `1` is the pin it serves, so ``|tip(R1.1) - tip(U1.1)|`` is the
    number, and it may not exceed ``pin_gap + grid``.
    """
    circuit, block, book = _service_fixture()
    tips = _tips(block, circuit, book)
    gap = _distance(tips["R1.1"], tips["U1.1"])
    budget = il.IslandBudget()
    assert gap <= budget.pin_gap + budget.grid, (
        f"R1's serving pin stands {gap:.2f} from U1.1 (budget "
        f"{budget.pin_gap} + {budget.grid}) — the part is not beside the pin it serves"
    )
    assert gap > 0.0, "two pin tips coincide: that is the butt S-13 forbids"


def test_the_served_part_moves_when_its_service_pin_turns():
    """S-04/§1.4: which side a part stands on is the **served pin's** to say.

    The same two parts and the same net, with the served pin declared on the IC's
    right instead of its left: the part must move to the other side of the IC.  If
    it does not, the placement is not reading the pin and 530B has not happened.
    """
    book = _base_book(
        IC3R=SymbolProfile(
            symbol_ref="IC3R", title="IC3R", body=(-30.0, -40.0, 30.0, 40.0),
            pins=[
                SymbolPin(number="1", tip=(50.0, 0.0), name="P1", direction="right",
                          length=10.0),
                SymbolPin(number="2", tip=(-50.0, 0.0), name="P2", direction="left",
                          length=10.0),
                SymbolPin(number="3", tip=(0.0, -50.0), name="P3", direction="down",
                          length=10.0),
            ],
        ),
    )
    sides = {}
    for symbol in ("IC3", "IC3R"):
        parts = [_part("U1", symbol, "MCU"), _part("R1", "R0402", "1k")]
        _circuit, block = _island(
            parts, [_net("SIG", "signal", ["U1.1", "R1.1"])], book,
            holding=["U1", "R1"],
        )
        origin = {part.part_id: (part.x, part.y) for part in block.parts}["R1"]
        sides[symbol] = origin[0]
    assert sides["IC3"] < 0.0 and sides["IC3R"] > 0.0, (
        f"the served part did not follow its pin across the IC: {sides} — a left pin "
        "and a right pin must put the part on opposite sides"
    )


def test_the_serving_pin_faces_back_at_the_anchor_pin():
    """§1.4: the two pins are coaxial, which is what makes the link a straight stub.

    ``dot(_pin_outward(P.service), -d) ≈ 1``: the served part's own pin points back
    at the pin it serves.  When this holds the route between them has nowhere to
    bend, and S-09's 「66% 导线是一根直 stub」 is a property of the placement rather
    than of the router.
    """
    circuit, block, book = _service_fixture()
    poses = {
        part.part_id: il.SymbolPose(rotation=part.rotation, mirror=part.mirror)
        for part in block.parts
    }
    served = book["IC6"]
    d = il._pin_outward(served, "1", poses["U1"])  # noqa: SLF001
    back = il._pin_outward(book["R0402"], "1", poses["R1"])  # noqa: SLF001
    dot = back[0] * -d[0] + back[1] * -d[1]
    assert dot == pytest.approx(1.0, abs=1e-9), (
        f"R1's serving pin points {back}, and the pin it serves points {d}: the two "
        "are not coaxial, so the link cannot be a straight stub"
    )
    # And the drawn link really is one straight run, not a bend nobody asked for.
    link = [segment for segment in block.segments if segment.net == "SIG"]
    assert len(link) == 1 and len(link[0].points) == 2, (
        "the link between the served pin and the pin it serves is "
        f"{[segment.points for segment in link]} — §1.4's promise is one straight stub"
    )


def test_two_pins_never_butt_together():
    """S-13: the generator does not lay two pins tip to tip, and the stub is real.

    Two readings, because either alone can pass on the wrong drawing: the two tips
    are at least one lattice step apart, and the run between them has positive
    length (a zero-length segment is the butt S-13 forbids, and `_tidy` refuses it
    — so a butt here would also mean the link had vanished).
    """
    book = _base_book()
    parts = [_part("U1", "IC6", "MCU"), _part("R1", "R0402", "1k")]
    circuit, block = _island(
        parts, [_net("SIG", "signal", ["U1.1", "R1.1"])], book, holding=["U1", "R1"],
    )
    tips = _tips(block, circuit, book)
    budget = il.IslandBudget()
    gap = _distance(tips["R1.1"], tips["U1.1"])
    assert gap >= budget.grid - 1e-9, (
        f"the two pinned tips are {gap:.2f} apart, under one {budget.grid:g} step — "
        "that is the generator butting two pins, which S-13 forbids"
    )
    length = il._length([  # noqa: SLF001
        point for segment in block.segments if segment.net == "SIG"
        for point in segment.points
    ])
    assert length > 0.0, "the link between the two pins has no length at all"


# -------------------------------------------------------------------- C: 去耦


def test_a_power_gnd_two_pin_part_lands_within_thirty_of_the_supply_pin():
    """S-05 on the real document, plus the reading it was measured with.

    The flyback's two decoupling parts are `C11` and `C13` (`SEC_12V`/`SEC_GND`),
    and §2.2's number is the **tip-to-tip** one — S-05 does not say which reading it
    means, so the note the block writes says which, and this test checks the note
    against the geometry rather than trusting it.

    **532 re-pinned both numbers, and the trade is bigger and named.** The first
    decap is **35.0** (it was 20.0) and the second **58.94** (it was 38.33). The
    cause is S-21's category rule (岳 2026-10-21): the 220uF's value row is 52 units
    wide, hangs past its own pin's tip, and **may no longer be hidden** — so the
    placement has to move the part until the row is clear of the corridor the pin's
    own wiring uses, which is what `place_service_tree`'s lead-clearance rule
    (`held_lead`) does, and what pushes the pair apart on a row whose pitch is now
    sized by where each part's drawing actually reaches. The page keeps the gate
    (ok=True) and prints **every** value; S-05 is broken by 5 units for the first
    decap and 28.9 for the second, both larger than 531's 8.3, and both are the
    price of the same sentence. The arithmetic is in
    `islandlayout.DECAP_ROW_CAP`'s comment, the tests that pin it, and
    `evidence/532/report.md`; the ruling is 岳's.
    """
    circuit, presentation, book = _flyback()
    blocks = {
        block.island_id: block
        for block in il.island_blocks(circuit, presentation, book)
    }
    secondary = blocks["secondary"]
    notes = [note for note in secondary.notes if note.startswith("decap ")]
    assert len(notes) == 2, f"the secondary island owes two decap readings; got {notes}"
    tips = _tips(secondary, circuit, book)
    ceiling = {"C11": 35.0, "C13": 58.95}
    for part_id, rail_pin, supply_pin in (
        ("C11", "C11.1", "D3.1"), ("C13", "C13.1", "D3.1"),
    ):
        gap = _distance(tips[rail_pin], tips[supply_pin])
        assert gap <= ceiling[part_id], (
            f"{part_id}'s {rail_pin} stands {gap:.2f} from {supply_pin} — over the "
            "ceiling this test states for it (532's measured trade, pinned below: "
            "S-21 will not hide the 220uF's value row, so the placement has to make "
            "the room and S-05 is what pays for it)"
        )
        assert _distance(tips["C11.1"], tips["D3.1"]) == pytest.approx(
            35.0, abs=0.01,
        ), "532 re-pinned the first decap's reading too — it is the trade now"
        assert _distance(tips["C13.1"], tips["D3.1"]) == pytest.approx(
            58.9406, abs=0.01,
        ), "...and the second one's is the trade this test re-pinned"
        named = [note for note in notes if note.startswith(f"decap {part_id}:")]
        assert named, f"{part_id} is a decoupling part with no reading written down"
        assert f"{gap:g}" in named[0], (
            f"the note says {named[0]!r} and the geometry says {gap:g} — a reading "
            "that does not match the drawing is worse than no reading"
        )


def test_a_rail_with_no_decoupling_element_is_reported_and_not_refused():
    """§2.3: 「IC 每条电源网至少 1 只」 is an account, not a gate.

    The fixture's `U1` is supplied by `VBUS` and nothing decouples it.  The placer
    must **say so** — `decap-missing`, naming the rail — and must still draw the
    island: whether the board should have that capacitor is the review line's
    question, and a placer that refused would be asking the drawing to answer for a
    part that is not there.
    """
    book = _base_book()
    parts = [_part("U1", "IC6", "MCU"), _part("R1", "R0402", "1k")]
    circuit, block = _island(
        parts,
        [
            _net("VBUS", "power", ["U1.1", "R1.1"]),
            _net("OUT", "signal", ["R1.2"]),
        ],
        book, holding=["U1", "R1"],
    )
    missing = [note for note in block.notes if note.startswith("decap-missing")]
    assert missing, (
        f"VBUS supplies U1 and nothing decouples it; the block's notes say "
        f"{block.notes} — §2.3 asks for a named account"
    )
    assert "VBUS" in missing[0], f"the account does not name the rail: {missing[0]}"
    assert {part.part_id for part in block.parts} == {"U1", "R1"}, (
        "the island was refused or changed by a soft account"
    )


def test_a_power_gnd_part_whose_rail_has_no_ic_supplier_still_lands():
    """§2.3's other half: the supplier is a two-pin rectifier, not an IC's pin.

    The flyback's `secondary` island is exactly this shape — `SEC_12V` is supplied
    by `D3`, a rectifier, and the anchor there is a two-pin part.  The decoupling
    parts must still stand beside the rail's pin, and no account may be owed for a
    rail that **is** decoupled just because the supplier is not an IC.
    """
    circuit, presentation, book = _flyback()
    blocks = {
        block.island_id: block
        for block in il.island_blocks(circuit, presentation, book)
    }
    secondary = blocks["secondary"]
    assert len(book["DIO-SMA-SS310"].pins) == 2, "the fixture's supplier must be two-pin"
    assert not [
        note for note in secondary.notes if note.startswith("decap-missing")
    ], f"SEC_12V has two decoupling parts, so no account is owed: {secondary.notes}"
    origins = {part.part_id: (part.x, part.y) for part in secondary.parts}
    assert set(origins) == {"D3", "C11", "C13"}


# -------------------------------------------------------------------- D: 成排


def _row_fixture(count: int, value: str) -> tuple[CircuitSpec, il.IslandBlock, dict]:
    """``count`` identical two-pin parts on **one** pin of one IC (`DESIGN` §3.1)."""
    book = _base_book()
    parts = [_part("U1", "IC6", "MCU")]
    members = ["U1.1"]
    for index in range(count):
        name = f"R{index + 1}"
        parts.append(_part(name, "R0402", value))
        members.append(f"{name}.1")
    circuit, block = _island(
        parts, [_net("SIG", "signal", members)], book,
        holding=[part["id"] for part in parts],
    )
    return circuit, block, book


def test_two_identical_parts_on_one_side_share_a_row():
    """S-06's two-part case: same symbol, same father, same side ⇒ collinear.

    `DESIGN` §3.2: two of a row need 「共线对齐」 and no invented pitch — so the
    assertion is that the two origins differ along **one** axis, and that the axis
    is the row's own (perpendicular to the pin they both serve).
    """
    circuit, block, book = _row_fixture(2, "1k")
    origins = {part.part_id: (part.x, part.y) for part in block.parts}
    (x1, y1), (x2, y2) = origins["R1"], origins["R2"]
    assert abs(x1 - x2) < 1e-9 or abs(y1 - y2) < 1e-9, (
        f"R1 {origins['R1']} and R2 {origins['R2']} share no axis — two parts of one "
        "row must be collinear with it"
    )
    poses = {
        part.part_id: il.SymbolPose(rotation=part.rotation, mirror=part.mirror)
        for part in block.parts
    }
    d = il._pin_outward(book["IC6"], "1", poses["U1"])  # noqa: SLF001
    row_axis = (-d[1], d[0])
    along = abs((x2 - x1) * d[0] + (y2 - y1) * d[1])
    across = abs((x2 - x1) * row_axis[0] + (y2 - y1) * row_axis[1])
    assert across > 0.0 and along <= 1e-6, (
        f"the two parts differ by {along:g} along the served pin's axis and "
        f"{across:g} across it — a row's two members are laid **along the row**, "
        "not strung out behind the pin they serve"
    )


def test_a_run_of_three_is_evenly_spaced_with_the_declared_pitch():
    """S-06's ≥3 case, and the pitch is `DESIGN` §3.2's formula, not a magic number.

    Three identical parts, three different designators, one row: the spacing
    between neighbours is computed in this test from the profile's own box and
    `render_width`, and the drawing must agree with it.  This is the case the real
    flyback cannot test at all (its only same-row pair is `R4`/`R5`), which is why
    the fixture is synthetic.
    """
    from boardwise.core.textmetrics import render_width, symbol_rows

    circuit, block, book = _row_fixture(3, "1k")
    origins = {part.part_id: (part.x, part.y) for part in block.parts}
    poses = {
        part.part_id: il.SymbolPose(rotation=part.rotation, mirror=part.mirror)
        for part in block.parts
    }
    budget = il.IslandBudget()
    d = il._pin_outward(book["IC6"], "1", poses["U1"])  # noqa: SLF001
    row_axis = (-d[1], d[0])
    spans, names, reaches = {}, {}, {}
    for part in block.parts:
        if part.part_id == "U1":
            continue
        box = il._part_box(book["R0402"], poses[part.part_id], (0.0, 0.0))  # noqa: SLF001
        spans[part.part_id] = max(
            abs(box[2] - box[0]) * abs(row_axis[0])
            + abs(box[3] - box[1]) * abs(row_axis[1]), 0.0,
        )
        names[part.part_id] = render_width(part.part_id)
        # 532: the pitch is made of where the part's own drawing is, not only of
        # how wide it is — the same two extents `place_service_tree` measures.
        corners = [
            (box[0], box[1]), (box[0], box[3]), (box[2], box[1]), (box[2], box[3]),
        ]
        corners.extend(
            corner
            for _kind, _text, row in symbol_rows(
                book["R0402"], (0.0, 0.0), reference=part.part_id,
                value=circuit.part(part.part_id).value, pose=poses[part.part_id],
            )
            for corner in (
                (row[0], row[1]), (row[0], row[3]),
                (row[2], row[1]), (row[2], row[3]),
            )
        )
        along = [row_axis[0] * corner[0] + row_axis[1] * corner[1] for corner in corners]
        reaches[part.part_id] = (max(0.0, -min(along)), max(0.0, max(along)))
    key = ("R0402", "U1", "left")
    extents = il.row_group_extents(
        {key: ["R1", "R2", "R3"]}, spans=spans, names=names, values={},
        reaches=reaches,
    )
    pitch = il.pack_rows(
        {key: ["R1", "R2", "R3"]}, spans=spans, names=names, reaches=reaches,
        budget=budget,
    )[key]
    # 534 R1: the pitch reads the geometry — the body span and where the row sits
    # (`draw_span`, 532) — and no longer the strings; the string's own width is a
    # *pair* rent, charged next door by `row_text_rent`.
    assert pitch == pytest.approx(
        il._snap_up(  # noqa: SLF001
            max(
                max(spans.values()),
                max(left + right for left, right in reaches.values()),
            ),
            budget.grid,
        ) + budget.row_gap, abs=1e-9
    ), "the fixture's own arithmetic drifted from §3.2's formula"
    assert il.row_pair_pitch(extents, key, key, budget=budget) == pytest.approx(
        pitch, abs=1e-9,
    ), "one group beside itself must cost the same as its own pitch"
    measured = []
    for first, second in (("R1", "R2"), ("R2", "R3")):
        delta = (origins[second][0] - origins[first][0],
                 origins[second][1] - origins[first][1])
        measured.append(delta[0] * row_axis[0] + delta[1] * row_axis[1])
    assert measured[0] == pytest.approx(measured[1], abs=1e-9), (
        f"a run of three is not evenly spaced: steps {measured}"
    )
    assert measured[0] == pytest.approx(pitch, abs=1e-9), (
        f"the row's step is {measured[0]:g}; §3.2's pitch for this row is {pitch:g}"
    )


def test_a_rows_pitch_is_geometry_and_its_values_pay_rent_beside_it():
    """534 R1, on the fixture 531 wrote for the opposite answer.

    531 answered S-21 by growing the row pitch to fit the value string. What that
    cost was measured on the real board in `evidence/534/quality/REPORT.md` §3: a
    9-unit-wide resistor carrying 「1k 1% 0805」 asked for a 41.7+ pitch, the
    island paid it in width, and the usb_c island came out 420x154 at 12.6% fill.
    The string is not what a row **is**. This test owns the split — `row_pitch`
    reads the parts' geometry (`body_span`, `draw_span`), `row_text_rent` states
    what a text row wider than its column asks of the row **next to it**, and
    `row_pair_pitch` takes the larger of the two, so a neighbour that really does
    print beside it still gets the room.

    S-21's own promise stays where it can be checked as a fact about the page:
    every value is printed or hidden with a reason, and no two printed value rows
    overlap — that assertion is unchanged from 531 and is what makes a narrower
    pitch legal rather than merely cheap.
    """
    from boardwise.core.textmetrics import render_width

    long_value = "4.7k 1% 0603 TCR100"
    circuit, block, book = _row_fixture(3, long_value)
    names = {f"R{index + 1}" for index in range(3)}
    printed = [text for text in block.texts if text.kind == "value"]
    reasons = [note for note in block.notes if "is not drawn" in note]
    dropped = {
        part_id for part_id in names if any(part_id in note for note in reasons)
    }
    assert {text.part_id for text in printed} | dropped == names, (
        "every value of the row is accounted for — printed or hidden with a reason: "
        f"printed {[text.part_id for text in printed]}, dropped {sorted(dropped)}"
    )
    assert all("is not drawn — " in note for note in reasons), reasons
    for first, second in itertools.combinations(
        sorted(printed, key=lambda text: text.bbox[0]), 2,
    ):
        assert not _overlaps(first.bbox, second.bbox), (
            f"{first.part_id}'s value row {first.bbox} and {second.part_id}'s "
            f"{second.bbox} intersect — a pitch that does not fit the row it prints "
            f"({render_width(long_value):.0f} units) is what this test is for"
        )

    # -- the 534 R1 contract, stated as a fact about the functions --------------
    budget = il.IslandBudget()
    group = ("R0402", "U1", "up")
    spans = {name: 20.0 for name in names}
    pitch = il.pack_rows(
        {group: ["R1", "R2", "R3"]},
        spans=spans,
        names={name: render_width(name) for name in names},
        values={name: render_width(long_value) for name in names},
        budget=budget,
    )[group]
    assert pitch == pytest.approx(
        il._snap_up(20.0, budget.grid) + budget.row_gap, abs=1e-9,  # noqa: SLF001
    ), (
        f"the row pitch {pitch:g} is not `snap_up(body span) + row_gap` — a value "
        f"string {render_width(long_value):.0f} wide reached the pitch again"
    )
    rent = il.row_text_rent(
        name_w=max(render_width(name) for name in names),
        value_w=render_width(long_value),
        budget=budget,
    )
    assert rent == pytest.approx(
        il._snap_up(render_width(long_value), budget.grid) + budget.row_gap,  # noqa: SLF001
        abs=1e-9,
    ), "the rent is what the widest printed string asks for, snapped like a pitch"
    assert rent > pitch, (
        "the rent has to be the bigger number here, or this fixture cannot tell the "
        f"two apart (pitch {pitch:g}, rent {rent:g})"
    )

    # -- and the pair step is the larger of the two ----------------------------
    extents = il.row_group_extents(
        {group: ["R1", "R2", "R3"]},
        spans=spans,
        names={name: render_width(name) for name in names},
        values={name: render_width(long_value) for name in names},
        reaches={name: (0.0, 0.0) for name in names},
    )
    two_rows = il.row_pair_pitch(extents, group, group, budget=budget)
    assert two_rows == pytest.approx(max(pitch, rent), abs=1e-9), (
        f"two rows side by side cost {two_rows:g}; the contract is "
        f"max(geometry pitch {pitch:g}, text rent {rent:g})"
    )


# -------------------------------------------------------- E: the real document


def test_the_real_flyback_reads_the_three_acceptance_numbers():
    """The batch's own readings, on the real document, at plan level.

    * **S-04** — every two-pin part's distance to the nearest pin of another part
      on a net they share (the pin it serves, read off the drawing): the **median**
      is what S-04 states (the golden board measures 16.5) and the batch's
      acceptance is ≤ 25;
    * **S-05** — both decoupling parts ≤ 30 (see the dedicated test for the note);
    * **S-20** — no text on the page is rotated.
    """
    circuit, presentation, book = _flyback()
    page = _flyback_page()
    plan = page.plan()

    member_net = {
        member: net.id for net in circuit.nets for member in net.members
    }
    measured: list[float] = []
    for block in page.blocks:
        tips = _tips(block, circuit, book)
        for part in block.parts:
            profile = book[part.symbol_ref]
            if len(profile.pins) != 2:
                continue
            best = None
            for pin in profile.pins:
                here = f"{part.part_id}.{pin.number}"
                net_id = member_net.get(here)
                if net_id is None or here not in tips:
                    continue
                for other in circuit.net(net_id).members:
                    if other.partition(".")[0] == part.part_id or other not in tips:
                        continue
                    gap = _distance(tips[here], tips[other])
                    best = gap if best is None else min(best, gap)
            if best is not None:
                measured.append(best)
    assert len(measured) == 15, (
        f"the flyback has fifteen two-pin parts on the page; measured {len(measured)}"
    )
    median = statistics.median(measured)
    assert median <= 25.0, (
        f"the median two-pin part stands {median:.1f} from the pin it serves (S-04's "
        f"acceptance is ≤ 25; measured {sorted(measured)})"
    )
    assert min(measured) > 0.0, "two pins of the page coincide"

    rotated = [text for text in plan.texts if text.rotation] + [
        label for label in plan.labels if label.rotation
    ]
    assert not rotated, f"S-20: {len(rotated)} rotated text(s) on the page"


def test_a_spec_without_islands_is_untouched_by_this_batch():
    """The single-island path is byte-for-byte what it was (520m's own promise).

    `DESIGN` §8.1 gives the structural reason (the guard at `drawcompiler`'s step 5
    is what routes a document to the island path, and `pagecompiler._module_view`
    does not carry `islands`), and this is the measurement: the two documents in the
    repository that declare no islands compile to the same `geometry_sha256` they
    compiled to before 530B.  The constants are the ones `evidence/530m` and
    `evidence/530a` recorded.
    """
    expected = {
        ("ch340_serial", 0): "c05e80b90a0eadc3419277541a07a606b47c515e43dc54c4bddbaeb535278d29",
        ("power_entry_xt30", 0): "085866e4944328f6c8ab65898fee0a2c771993cdcc161069370dca9b8be954ca",
        ("power_entry_xt30", 1): "0a124aeaedf057b1d2f9566b8bcaf86b41ed388a63be4a65ed63717a3bbd5020",
        ("power_entry_xt30", 2): "76d4798a46e695f056f4c7eb074f556b7c3f60e5a2a94c03aded5fb14c01c6f7",
        ("power_entry_xt30", 3): "ead7bf3da4fe98f912bee134dbad7d586506d3c3ed687327f51ae4ef53583b2a",
    }
    seen: dict[tuple[str, int], str] = {}
    for stem in ("ch340_serial", "power_entry_xt30"):
        circuit = CircuitSpec.load(SPECS / f"{stem}.circuit.json")
        presentation = PresentationSpec.load(SPECS / f"{stem}.presentation.json")
        book = _library(stem)
        result = dc.compile(circuit, presentation, book)
        assert "boardwise-island-page" not in " ".join(result.notes), (
            f"{stem} declared no islands and must not reach the island path"
        )
        for index, candidate in enumerate(result.ranked):
            seen[(stem, index)] = candidate.plan.geometry_sha256()
    assert seen == expected, (
        "a document that declares no islands compiled differently after 530B — the "
        f"single-island path is supposed to be untouched; got {seen}"
    )

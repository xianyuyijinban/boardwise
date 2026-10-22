"""530A: the island path names a rail with a **flag**, and a one-pin net with a name.

The batch's contract is ``evidence/523/DESIGN.md`` §7.2 (S-16: 「地/电源一律旗标，
不拉母线」), §7.3 (a one-pin net is named and linted, not refused) and §14 (岳's
rulings of 2026-10-20: **一标多脚** — one flag may gather several nearby pins —
and 单脚网挂名 + lint).  It is implemented in `engines/islandlayout.py`, and this
file is where each clause of it is measured:

**1. The field is additive.**  `IslandBlock.power_symbols` defaults to ``[]`` and
`:attr:`IslandBlock.power_boxes` with it, so every construction point and every
reader that predates 530A behaves exactly as it did (the whole existing island
suite is the other half of that claim; this file measures the empty case and the
rigid-block arithmetic).

**2. A rail or ground is a flag, a signal is a label.**  On the real flyback
document (five islands) the ten `power`/`gnd` boundary names become ten flags with
the library's own `PWR-*` symbols, and no label carries a rail or ground name.

**3. One flag per net, not per pin.**  A rail with three pins in one island gets
**one** flag: the pins are already one blob (`_wire_net` drew them as a chain) and
the name is the blob's, which is 岳's own reading of S-16 — the golden board's
`GND` is 48 pins under 34 flags.

**4. A one-pin net is named, and the lint is on the artifact.**  `GATE`/`VFB_NF`
get a label at their own pin and an `island-single-name` note that reaches the
**page plan** (not only the block), so `required-pin-not-connected` is 0 rather
than 2.

**5. Nothing drifts from the compiler.**  The island's flag *ref* and flag
*rotation* are written in `islandlayout` (it may not import the compiler: the
dependency runs the other way), so this file pins both against
`drawcompiler._flag_ref` / `drawcompiler.flag_rotation` — the two copies may not
disagree about which symbol a net takes or which side a glyph hangs.

The synthetic fixture is hand-written (spec + library in the test, the way
`test_173_ground_isolation` writes its own) because the **rule** is what this file
judges, and the flyback is a document whose every number 530B is about to move.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile, flag_glyph_box
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

PROV = "verified_recipe"


# ------------------------------------------------------------- the flyback

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


def _flyback_blocks() -> list[il.IslandBlock]:
    circuit, presentation, book = _flyback()
    return il.island_blocks(circuit, presentation, book)


def test_the_library_carries_every_flag_the_flyback_page_needs():
    """The five `PWR-*` symbols the page asks for are all in the book.

    Checked before anything is drawn, because §7.2.2's downgrade ("no symbol, so a
    label and a note") is only honest if a symbol really is absent: the four nets
    this page flags are `HVDC`, `PGND`, `SEC_12V` and `SEC_GND`, and a book that
    carried them would make every "no symbol" note in this file a lie about the
    library.
    """
    book = _library("flyback_uc3845")
    for ref in ("PWR-GND", "PWR-PGND", "PWR-SEC_GND", "PWR-HVDC", "PWR-SEC_12V"):
        profile = book.get(ref)
        assert profile is not None, f"the book has no {ref}"
        assert not profile.pins, (
            f"{ref} must be a pin-less flag profile — a pin-less profile is how "
            "the compiler identifies a flag"
        )


def test_a_rail_or_ground_crossing_becomes_a_flag_and_a_signal_stays_a_label():
    """S-16 on the real document: ten boundary names become ten flags.

    ``primary`` 8 parts, ``secondary`` 3, ``feedback`` 4, ``bridge`` 2 and
    ``control`` 2 — the crossing nets of the class `power`/`gnd` are `HVDC`(×2),
    `PGND`(×3), `SEC_12V`(×2) and `SEC_GND`(×3), one per island that holds one, and
    each takes the library's own symbol for that net.
    """
    blocks = {block.island_id: block for block in _flyback_blocks()}
    flagged = {
        name: {symbol.net: symbol.symbol_ref for symbol in block.power_symbols}
        for name, block in blocks.items()
    }
    assert flagged == {
        "primary": {"HVDC": "PWR-HVDC", "PGND": "PWR-PGND"},
        "secondary": {"SEC_12V": "PWR-SEC_12V", "SEC_GND": "PWR-SEC_GND"},
        "feedback": {"SEC_12V": "PWR-SEC_12V", "SEC_GND": "PWR-SEC_GND"},
        "bridge": {
            "HVDC": "PWR-HVDC", "PGND": "PWR-PGND", "SEC_GND": "PWR-SEC_GND",
        },
        "control": {"PGND": "PWR-PGND"},
    }, flagged
    circuit, _presentation, _book = _flyback()
    cls = {net.id: net.cls for net in circuit.nets}
    for name, block in blocks.items():
        banned = [
            (label.net, label.text) for label in block.labels
            if cls.get(label.net) in ("power", "gnd")
        ]
        assert not banned, (
            f"island {name} still names {banned} with a label — S-16 says a rail or "
            "a ground is a flag and never a label"
        )


def test_the_flags_reach_the_page_plan_and_carry_their_symbol_hash():
    """The landing step reads `LayoutPlan.power_symbols`, so the page must fill it.

    `drawcompiler._try_island_variants` and `drawapply.module_plan` both consume
    `PackedPage.plan()`, and `readability` grades the flags from the same plan —
    so a block-level flag that stopped at the block would be drawn nowhere and
    measured by nobody.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    plan = page.plan()
    per_block = sum(len(block.power_symbols) for block in page.blocks)
    assert len(plan.power_symbols) == per_block == 10, (
        f"the page plan carries {len(plan.power_symbols)} flags of {per_block} the "
        "blocks hold"
    )
    for symbol in plan.power_symbols:
        profile = book[symbol.symbol_ref]
        assert symbol.symbol_hash == profile.geometry_hash(), (
            f"{symbol.symbol_ref} on {symbol.net} carries a stale symbol hash — "
            "drawapply refuses a flag whose hash disagrees with the library's"
        )
        assert symbol.net, "a flag with no net is a flag that names nothing"


def test_one_flag_gathers_every_pin_of_that_rail_in_the_island():
    """岳's 一标多脚: `PGND` has five members and the page hangs three flags.

    Read off the real circuit — `PGND` is `C10.2 C6.2 R10.2 R5.2 U5.3`, spread over
    the `control`, `primary` and `bridge` islands — so the assertion is the
    arithmetic the ruling asks for: **one flag per island that holds the net**, not
    one per pin (five pins, three flags) and not one for the whole page either.
    """
    circuit, _presentation, _book = _flyback()
    members = {net.id: list(net.members) for net in circuit.nets}
    assert len(members["PGND"]) == 5, members["PGND"]
    blocks = _flyback_blocks()
    flags = [
        (block.island_id, symbol.net)
        for block in blocks for symbol in block.power_symbols
        if symbol.net == "PGND"
    ]
    assert len(flags) == 3, (
        f"PGND hangs {flags} — one flag is owed per island that holds it, and five "
        "flags (one per pin) is the shape 岳 ruled against"
    )
    for island_id, _net in flags:
        block = [item for item in blocks if item.island_id == island_id][0]
        assert sum(1 for segment in block.segments if segment.net == "PGND") >= 1, (
            f"island {island_id} flags PGND but draws no conductor for it, so the "
            "pins it claims to gather are not gathered"
        )


# ------------------------------------------------------- the rigid-block half


def _fingerprint(block: il.IslandBlock) -> list[float]:
    """Every coordinate a block draws, flags included, in a fixed order.

    `test_520m_island_page._fingerprint` extended by 530A with the two lists a flag
    lives in (523 DESIGN §9.1 #31): the symbol's own anchor and rotation, and the
    box it reserves.  Without them a packer that recomputed or dropped a flag would
    still pass the rigidity test.
    """
    out: list[float] = []
    for part in sorted(block.parts, key=lambda item: item.part_id):
        out.extend([part.x, part.y, part.rotation, float(part.mirror)])
    for segment in block.segments:
        out.append(len(segment.points))
        for point in segment.points:
            out.extend(point)
    for label in block.labels:
        out.extend([label.x, label.y, *label.bbox])
    for symbol in block.power_symbols:
        out.extend([symbol.x, symbol.y, symbol.rotation])
    for box in block.power_boxes:
        out.extend(box)
    for text in block.texts:
        out.extend([*text.bbox])
    for junction in block.junctions:
        out.extend([junction.x, junction.y])
    return out


def test_the_packing_translates_the_flags_and_recomputes_nothing():
    """A flag is part of the rigid block: the packer moves it and never re-makes it.

    The same round trip `test_520m` makes for the parts and wires — move the block
    back by its own offset and compare fingerprints — with the flags in the
    fingerprint.  It also pins the invariant the flags exist for: a block's own
    `power_symbols` and the packed page's agree one for one.
    """
    circuit, presentation, book = _flyback()
    alone = {
        block.island_id: block
        for block in il.island_blocks(circuit, presentation, book)
    }
    page = il.island_page(circuit, presentation, book)
    assert sum(len(block.power_symbols) for block in page.blocks) == 10
    for block in page.blocks:
        dx, dy = page.offsets[block.island_id]
        back = block.translated(-dx, -dy)
        assert _fingerprint(back) == pytest.approx(
            _fingerprint(alone[block.island_id]), abs=1e-9
        ), (
            f"{block.island_id} changed inside the packing — a flag is part of the "
            "block and may only be translated"
        )


def test_the_flag_is_inside_the_blocks_own_box():
    """`bbox()` has to hold the flags, or the packer lays the next island on one.

    The glyph hangs off the end of a boundary stub, past everything else the block
    draws — which is exactly why 520m's `S-01` (nothing enters the title block) is
    decided from this box.  Two readings of "it is in the box", and the second is
    the one that can fail:

    * every stored `power_boxes` entry is inside `bbox()` — a regression guard for
      a future edit that drops the field from `bbox`'s own list;
    * the glyph **recomputed from the library** (`flag_glyph_box` at the symbol's
      own rotation and anchor) is inside `bbox()` too — that one ties the block's
      box to the library rather than to the list the block stored, so a
      `_flag_seat` that measured the wrong rotation would show up here.
    """
    book = _library("flyback_uc3845")
    for block in _flyback_blocks():
        box = block.bbox()
        assert block.power_boxes, f"island {block.island_id} has no flag at all"
        for index, glyph in enumerate(block.power_boxes):
            symbol = block.power_symbols[index]
            assert box[0] <= glyph[0] and glyph[2] <= box[2], (
                f"island {block.island_id}: flag {symbol.symbol_ref} on "
                f"{symbol.net} is outside its own block's box {box}"
            )
            assert box[1] <= glyph[1] and glyph[3] <= box[3], (
                f"island {block.island_id}: flag {symbol.symbol_ref} on "
                f"{symbol.net} is outside its own block's box {box}"
            )
            measured = flag_glyph_box(
                book[symbol.symbol_ref], rotation=symbol.rotation,
                anchor=(symbol.x, symbol.y),
            )
            assert measured is not None, (
                f"{symbol.symbol_ref} states no glyph box, so the drawing reserved "
                "room for a flag nobody can measure"
            )
            assert (
                box[0] <= measured[0] and measured[2] <= box[2]
                and box[1] <= measured[1] and measured[3] <= box[3]
            ), (
                f"island {block.island_id}: the glyph of {symbol.symbol_ref} on "
                f"{symbol.net}, measured off the library at rotation "
                f"{symbol.rotation}, is {measured} — outside the block's own box "
                f"{box}"
            )


def test_a_block_with_no_flags_is_what_it_always_was():
    """The field is additive: no flags means no trace of them anywhere.

    A block built by the module's own placer for an island that crosses nothing
    (the `bridge` island of a two-part circuit that shares no net) has an empty
    `power_symbols`/`power_boxes`, and `bbox`, `translated` and `plan` answer
    exactly what they answered before the field existed.
    """
    block = il.IslandBlock(island_id="solo", role="", anchor="U1")
    assert block.power_symbols == [] and block.power_boxes == []
    assert block.bbox() == (0.0, 0.0, 0.0, 0.0)
    moved = block.translated(10.0, -5.0)
    assert moved.power_symbols == [] and moved.power_boxes == []
    plan = block.plan()
    assert plan.power_symbols == []
    assert plan.notes[0] == il.ISLAND_LAYOUT_KIND


# --------------------------------------------------- agreement with the compiler


def test_the_islands_flag_rotation_is_the_compilers_flag_rotation():
    """`islandlayout._flag_rotation` and `drawcompiler.flag_rotation` agree, always.

    The island module may not import the compiler (`_try_island_variants` imports
    *it*, lazily, and 530A may not close that into a module-level cycle), so the
    rule is written twice.  This is what keeps the two copies honest: 069 sec.7's
    answer is 0 or 180 and nothing else, and the two functions must give the same
    one for all four compass points on both families.
    """
    from boardwise.core.symbolprofile import (
        FLAG_GLYPH_KIND_GND, FLAG_GLYPH_KIND_RAIL,
    )

    for kind in (FLAG_GLYPH_KIND_GND, FLAG_GLYPH_KIND_RAIL):
        for direction in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)):
            mine = il._flag_rotation(direction, kind)  # noqa: SLF001
            theirs = dc.flag_rotation(direction, kind)
            assert mine == theirs, (
                f"a {kind} flag hanging {direction}: the island module says "
                f"{mine}, the compiler says {theirs}"
            )
            assert mine in (0.0, 180.0), (
                f"069 sec.7: a flag stands upright — got {mine}"
            )


def _context(circuit: CircuitSpec, book: dict[str, SymbolProfile]) -> dc._Context:
    """A `_Context` carrying only what the flag chooser reads (test_173's own shape)."""
    return dc._Context(
        circuit=circuit,
        presentation=PresentationSpec.from_dict({"grammarRef": "flyback"}),
        binding=None,
        book=book,
        budget=dc.CompileBudget(),
        axis="x",
        progress=(1.0, 0.0),
        chain_net_rank={},
        slots={},
        chain=[],
        accepted={},
        body_dirs={},
    )


def test_the_islands_flag_chooser_is_the_compilers_flag_chooser():
    """The **ref** a net is looked up under is the same on both paths (173/C).

    Asked on the real flyback document, whose grounds fall in two domains
    (`PGND` → `power`, `SEC_GND` → its own name), which is the case 173/C's
    per-domain mapping exists for: the island module's answer and
    `drawcompiler._flag_ref`'s must be the same string for every rail and ground
    net the page carries.
    """
    circuit, _presentation, book = _flyback()
    ctx = _context(circuit, book)
    asked = [
        (net.id, net.cls) for net in circuit.nets if net.cls in ("power", "gnd")
    ]
    assert {net for net, _cls in asked} == {"HVDC", "PGND", "SEC_12V", "SEC_GND"}
    domains = frozenset(il._ground_domains(circuit))  # noqa: SLF001
    assert len(domains) > 1, (
        f"the fixture must have more than one ground domain or this proves "
        f"nothing about 173/C; got {domains}"
    )
    for net_id, cls in asked:
        mine = il._flag_ref(  # noqa: SLF001
            net_id, cls, book=book, budget=il.IslandBudget(),
            ground_domains=domains,
        )
        theirs = dc._flag_ref(ctx, net_id, cls)
        assert mine == theirs, (
            f"net {net_id!r} ({cls}): the island module looks it up as {mine!r}, the "
            f"compiler as {theirs!r} — one document may not name one net two ways"
        )


def test_the_ground_switch_is_the_budgets_own_statement():
    """`gnd_flag=""` means 「this drawing names no ground with a flag」 (178).

    Off means off, and the island path is no exception: the docstring's own words
    are 「the library cannot overrule a scenario's statement about itself」.  The
    rails still take their own `PWR-<net>`; the ground falls back to a label, and
    **silently** — an empty ref is a decision, not a missing library entry.
    """
    circuit, presentation, book = _flyback()
    block = {
        item.island_id: item
        for item in il.island_blocks(
            circuit, presentation, book,
            budget=il.IslandBudget(gnd_flag=""),
        )
    }["bridge"]
    flagged = {symbol.net for symbol in block.power_symbols}
    assert flagged == {"HVDC"}, flagged
    assert "SEC_GND" in {label.net for label in block.labels}
    silent = [note for note in block.notes if "PWR-SEC_GND" in note]
    assert not silent, (
        f"an empty gnd_flag is the budget's statement, not a missing symbol, so it "
        f"must not be reported as one: {silent}"
    )


# --------------------------------------------------------- the synthetic fixture


def _resistor(ref: str = "R0402") -> SymbolProfile:
    return SymbolProfile(
        symbol_ref=ref, title="Resistor", body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up"),
            SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down"),
        ],
    )


def _ic(ref: str, pins: int) -> SymbolProfile:
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-30.0, -40.0, 30.0, 40.0),
        pins=[
            SymbolPin(
                number=str(index + 1), tip=(-50.0, 0.0), name=f"P{index + 1}",
                direction="left",
            )
            for index in range(pins)
        ],
    )


def _flag(ref: str, ground: bool) -> SymbolProfile:
    """A flag profile: a glyph box, **no pins** — how the compiler spots a flag."""
    body = (-10.5, 0.0, 10.5, 19.5) if ground else (-5.5, 0.0, 5.5, 10.5)
    return SymbolProfile(symbol_ref=ref, title=ref, body=body, pins=[])


def _part(part_id: str, symbol: str, value: str = "") -> dict:
    return {"id": part_id, "symbolRef": symbol, "value": value, "provenance": PROV}


def _net(net_id: str, cls: str, members: list[str]) -> dict:
    return {
        "id": net_id, "class": cls, "members": list(members),
        "provenance": PROV,
    }


def _two_islands(
    nets: list[dict] | None = None,
) -> tuple[CircuitSpec, PresentationSpec, dict[str, SymbolProfile]]:
    """Two islands: `a` holds the rail's three pins, `b` one.

    Chosen so that every branch of the naming rule has a net to land on, and every
    number is small enough to check by eye:

    * ``VBUS`` (power) — `U1.1 R1.1 R2.1` in `a`, `D1.1` in `b`: crossing, three
      pins on one island (**一标多脚**), one flag;
    * ``PGND`` (gnd) — `R1.2 R2.2` in `a`, `D1.2` in `b`: crossing, and with
      ``SGND`` beside it the page has **two ground domains** (`PGND` is the power
      domain, `SGND` keys its own name), so each asks for its own symbol;
    * ``SGND`` (gnd) — `U1.3` in `a`, `R3.1` in `b`: crossing;
    * ``OUT`` (signal) — `U1.2` in `a`, `D1.3` in `b`: crossing, stays a label;
    * ``SPARE`` (signal) — `U1.4` only: **one pin and no second end anywhere**.

    ``R3.2`` is on no net at all (a transformer's NC pin is the same shape), which
    is deliberately *not* the same thing as `SPARE` and is why both are here.
    """
    circuit = CircuitSpec.from_dict({
        "parts": [
            _part("U1", "IC4", "MCU"), _part("R1", "R0402", "10k"),
            _part("R2", "R0402", "4.7k"), _part("D1", "IC3", "DIODE"),
            _part("R3", "R0402", "1k"),
        ],
        "nets": nets if nets is not None else [
            _net("VBUS", "power", ["U1.1", "R1.1", "R2.1", "D1.1"]),
            _net("PGND", "gnd", ["R1.2", "R2.2", "D1.2"]),
            _net("SGND", "gnd", ["U1.3", "R3.1"]),
            _net("OUT", "signal", ["U1.2", "D1.3"]),
            _net("SPARE", "signal", ["U1.4"]),
        ],
    })
    presentation = PresentationSpec.from_dict({
        "grammarRef": "flyback",
        "modules": [
            {"id": "main", "parts": ["U1", "R1", "R2", "D1", "R3"], "role": "tube"},
        ],
        "islands": [
            {"id": "a", "role": "primary", "parts": ["U1", "R1", "R2"]},
            {"id": "b", "role": "secondary", "parts": ["D1", "R3"]},
        ],
    })
    book = {
        "IC4": _ic("IC4", 4), "IC3": _ic("IC3", 3), "R0402": _resistor(),
        "PWR-VBUS": _flag("PWR-VBUS", ground=False),
        "PWR-PGND": _flag("PWR-PGND", ground=True),
        "PWR-SGND": _flag("PWR-SGND", ground=True),
        "PWR-GND": _flag("PWR-GND", ground=True),
    }
    return (circuit, presentation, book)


def _synthetic_blocks(
    budget: il.IslandBudget | None = None,
    nets: list[dict] | None = None,
) -> dict[str, il.IslandBlock]:
    circuit, presentation, book = _two_islands(nets)
    return {
        block.island_id: block
        for block in il.island_blocks(circuit, presentation, book, budget=budget)
    }


def _ends_at(segment, point: tuple[float, float]) -> bool:
    """Is ``point`` one of this segment's own vertices (to 1e-6)?"""
    return any(
        abs(x - point[0]) < 1e-6 and abs(y - point[1]) < 1e-6
        for x, y in segment.points
    )


def test_three_pins_of_one_rail_in_one_island_are_one_flag():
    """一标多脚, on a fixture small enough to count: three pins, one flag, one wire.

    The pins are one blob because :func:`_wire_net` chains them, and the name is
    the blob's — so `a` holds one chain that reaches all three pins of `VBUS` and
    exactly one flag at the end of it.
    """
    blocks = _synthetic_blocks()
    primary = blocks["a"]
    vbus_flags = [s for s in primary.power_symbols if s.net == "VBUS"]
    assert len(vbus_flags) == 1, (
        f"three pins of VBUS sit in island 'a' and it hangs {len(vbus_flags)} flags "
        "— 岳's ruling is one flag gathering the nearby pins of one blob"
    )
    assert vbus_flags[0].symbol_ref == "PWR-VBUS"
    runs = [segment for segment in primary.segments if segment.net == "VBUS"]
    assert len(runs) == 3, (
        f"three pins chain into two links and the flag has one lead, so VBUS owes "
        f"three conductors in island 'a'; got {len(runs)}"
    )
    anchor = (vbus_flags[0].x, vbus_flags[0].y)
    assert sum(1 for run in runs if _ends_at(run, anchor)) == 1, (
        "the flag's connection point is not the end of exactly one conductor of its "
        "own net — the editor would read the rail as unconnected"
    )


def test_a_multi_domain_page_gives_each_ground_its_own_flag():
    """173/C on the synthetic page: two ground domains, each named by itself.

    `PGND` is the power domain and `SGND` keys its own name, so the shared family
    symbol would say the two are one ground — the defect 173/C names.
    """
    blocks = _synthetic_blocks()
    primary = {s.net: s.symbol_ref for s in blocks["a"].power_symbols}
    assert primary == {
        "VBUS": "PWR-VBUS", "PGND": "PWR-PGND", "SGND": "PWR-SGND",
    }, primary
    # …and a one-domain page keeps the shared family symbol: with `SGND` dropped
    # from the circuit the page has nothing to isolate.
    one_ground = _synthetic_blocks(nets=[
        _net("VBUS", "power", ["U1.1", "R1.1", "R2.1", "D1.1"]),
        _net("PGND", "gnd", ["R1.2", "R2.2", "D1.2"]),
        _net("OUT", "signal", ["U1.2", "D1.3"]),
        _net("SPARE", "signal", ["U1.4"]),
    ])
    assert {s.net: s.symbol_ref for s in one_ground["a"].power_symbols}["PGND"] == (
        "PWR-GND"
    ), (
        "a page with one ground domain has nothing to isolate, so it keeps the "
        "family's shared symbol (173/C)"
    )


def test_a_signal_crossing_is_still_a_label_and_a_one_pin_net_is_named_with_a_lint():
    """The two halves of the naming rule that a flag must not swallow.

    * `OUT` crosses and is a signal: a label in each island, one name each, and
      **no** flag;
    * `SPARE` has one pin and no second end anywhere: named at that pin, with the
      `island-single-name` lint on the block — 岳's ruling, and the reason the pin
      no longer reads as an unconnected member.
    """
    blocks = _synthetic_blocks()
    primary, secondary = blocks["a"], blocks["b"]
    assert "OUT" in {label.net for label in primary.labels}
    assert "OUT" in {label.net for label in secondary.labels}
    assert "OUT" not in {symbol.net for symbol in primary.power_symbols}
    assert "SPARE" in {label.net for label in primary.labels}, (
        "a one-pin net is named at its own pin (岳 2026-10-20)"
    )
    lint = [note for note in primary.notes if "island-single-name" in note]
    assert len(lint) == 1 and "SPARE" in lint[0] and "U1.4" in lint[0], lint


def test_one_pin_net_is_a_property_of_the_net_not_of_the_island():
    """`IslandNet.single_pin` reads "one member in the **document**", not "here".

    The two are different questions and only one of them is 岳's: a crossing net
    with one pin in this island is `crossing` (named as a jump), while a net whose
    whole membership is one pin is `single_pin` (named and linted).  Asked on the
    fixture's own subgraphs so the distinction cannot be flattened by accident.
    """
    circuit, presentation, _book = _two_islands()
    subgraphs = {
        graph.island_id: graph
        for graph in il.island_subgraphs(circuit, presentation)
    }
    by_id = {
        (graph.island_id, net.net_id): net
        for graph in subgraphs.values() for net in graph.nets
    }
    assert by_id[("a", "SPARE")].single_pin
    assert ("b", "SPARE") not in by_id, (
        "SPARE is one pin of U1 and touches no part of island 'b'"
    )
    assert by_id[("b", "OUT")].crossing
    assert by_id[("b", "OUT")].single_pin is False, (
        "a crossing net with one pin here is named as a jump, not as a dangling net"
    )
    singles = {
        (net.net_id, str(net.pins[0]))
        for graph in subgraphs.values() for net in graph.single_pin_nets
    }
    assert singles == {("SPARE", "U1.4")}, singles


def test_a_library_without_the_flag_symbol_falls_back_and_says_so():
    """§7.2.2's downgrade, out loud: no `PWR-VBUS` in the book, so a label and a note.

    The alternative — drawing the flag anyway — is not something this host can do
    (143 F1: a flag net with no symbol is what the drawing has to say out loud),
    and the note must name the ref that was looked for, or the reader cannot tell
    "this library is short a symbol" from "this net was never a rail".
    """
    circuit, presentation, book = _two_islands()
    del book["PWR-VBUS"]
    block = {
        item.island_id: item
        for item in il.island_blocks(circuit, presentation, book)
    }["a"]
    assert "VBUS" not in {symbol.net for symbol in block.power_symbols}
    assert "VBUS" in {label.net for label in block.labels}, (
        "with no flag symbol the net must fall back to a label — never to nothing"
    )
    notes = [note for note in block.notes if "PWR-VBUS" in note]
    assert len(notes) == 1 and "label" in notes[0], (
        f"the downgrade must be recorded and must name the missing ref; got {notes}"
    )


def test_a_flag_is_never_a_label_for_the_same_net_in_one_island():
    """A net is named once, one way: S-14's 「箱数 = 名字数」 at island scale.

    A label and a flag for one net in one island would say the same thing twice —
    and `drawapply` would silently drop the label (`covered`), so the drawing on
    the canvas and the plan under it would disagree about how many names the net
    has.  Checked on both fixtures: the two sets are disjoint everywhere.
    """
    circuit, presentation, book = _flyback()
    blocks = il.island_blocks(circuit, presentation, book)
    synthetic = list(_synthetic_blocks().values())
    for block in [*blocks, *synthetic]:
        both = {label.net for label in block.labels} & {
            symbol.net for symbol in block.power_symbols
        }
        assert not both, f"island {block.island_id} names {both} twice"

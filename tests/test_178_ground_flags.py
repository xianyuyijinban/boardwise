"""178: the library carries a ground flag **per domain** — 173 sec.C.5's residual.

======================= what 173 left open =======================

173/C connected the mapping 「网的地域 → 旗标族」: on a page whose ``gnd`` nets
fall in more than one domain, `drawcompiler._flag_ref` asks for the flag named
after the net (``PWR-<net>``) instead of the family's one shared symbol — and it
falls back to the shared symbol when the book has no such entry. 173's own words
for the state it left behind: 「本仓所有库都只有**一个**地旗符号 `PWR-GND`…
映射虽然接通了，**今天所有页面上两域仍共用同一个字形**」. On the delivered
flyback page that is exactly what happens: `PGND` and `SEC_GND` are drawn with
one `PWR-GND`, so two isolated ground domains read as one net.

===================== what this batch adds ========================

岳's naming rule (2026-10-12): 基础域 **PGND / AGND / DGND**，特殊地 **xxx-GND**，
既有板子在用的名字（如 SEC_GND）不强行改名。 The flyback circuit's ground nets
are `PGND` (base domain) and `SEC_GND` (a special ground keeping its own name),
so the book gains exactly two ground flags: ``PWR-PGND`` and ``PWR-SEC_GND``.
The other two books need nothing: their circuits have **one** ground net each
(`GND`), one domain, and 173's gate keeps the shared family symbol there.

The flags are pin-less profiles — the connection point IS the origin, which is
how the compiler identifies a flag — and their glyph box is **inherited** from
``PWR-GND`` (the ground family's measured extent) rather than measured again:
nobody has placed a ``Ground-PGND`` through this repo, so a second measurement
would be a measurement of nothing. `tests/test_118_measured_profiles.py` holds
them to that inheritance byte-for-byte, and to the reading that *does* exist:
the host's own library carries a net-named member of the one ground family
(毕设 FOC P1's live geometry resolves `PGND` → `Ground-PGND`, `AGND` →
`Ground-AGND`, `GND` → `Ground-GND`).

========================= what is proven here =========================

1. the two profiles are in the book, are ground-family, and carry the family's
   measured box;
2. the single-domain books keep their one symbol and need no addition;
3. on the real landing page (``outputs/150/presentation_150_r5rot.json``) the
   two families now hang **two** flags, and the drawing does not move by a unit
   — the same page compiled with the two refs removed is byte-identical in
   geometry, so this is a naming change and not a layout change;
4. the apply stage still reads both as `Ground` flags (the host is handed
   kind + net, never the symbolRef), and refuses a ground flag on a rail name.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from boardwise.core.changeplan import DRAW_FLAG_GROUND
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import flag_glyph_kind
from boardwise.engines import drawapply, drawcompiler as dc

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
FLYBACK = SPECS / "flyback_uc3845.circuit.json"
FLYBACK_LIBRARY = SPECS / "flyback_uc3845.library.json"
#: the page 175/B-2 pins: the flyback landing page as delivered, both ground
#: families drawn with a flag (the shape 173 measured the defect on).
LANDING_PAGE = ROOT / "outputs" / "150" / "presentation_150_r5rot.json"
#: the host's own reading of a board drawn in the editor (毕设 FOC P1,
#: 2026-09-21) — where a ground flag's symbol name is the net's.
HOST_READING = ROOT / "outputs" / "013_p2_geometry_bisheP1.json"

#: 178's two additions: ``symbolRef -> the net it names``.
PER_DOMAIN_FLAGS: tuple[tuple[str, str], ...] = (
    ("PWR-PGND", "PGND"),
    ("PWR-SEC_GND", "SEC_GND"),
)

#: The two books whose circuits have a single ground net (``GND``).
SINGLE_DOMAIN_BOOKS = ("power_entry_xt30", "ch340_serial")


def _book(path: pathlib.Path):
    return drawapply.load_library(path)


def _compile(circuit, presentation, book):
    result = dc.compile(circuit, presentation, book, dc.CompileBudget())
    assert result.ok, [item.detail for item in result.failures]
    return result.candidates[0]


def _geometry(plan) -> dict:
    """Everything a reader sees, except which flag symbol names which net."""
    return {
        "parts": sorted(
            [part.part_id, part.symbol_ref, round(part.x, 4), round(part.y, 4),
             int(part.rotation), bool(part.mirror)]
            for part in plan.parts
        ),
        "wires": sorted(
            [segment.net, [list(point) for point in segment.points]]
            for segment in plan.segments
        ),
        "texts": sorted(
            [text.kind, text.text, text.part_id]
            + [round(value, 4) for value in text.bbox]
            for text in plan.texts
        ),
        "flags": sorted(
            [symbol.net, round(symbol.x, 4), round(symbol.y, 4),
             int(symbol.rotation)]
            for symbol in plan.power_symbols
        ),
    }


def _refs(plan) -> dict[str, str]:
    """``net -> symbol_ref`` (one entry per net; every flag counts separately)."""
    out: dict[str, str] = {}
    for symbol in plan.power_symbols:
        out.setdefault(symbol.net, symbol.symbol_ref)
    return out


# ------------------------------------------------------- 1 入库：按岳的规则


def test_the_book_carries_one_flag_per_ground_domain():
    """``PWR-PGND`` / ``PWR-SEC_GND``, ground family, the family's measured box.

    岳's rule gives the naming: the base ground domains are PGND/AGND/DGND, a
    special ground is ``xxx-GND`` — and the flyback circuit's two ``gnd`` nets
    are exactly those two spellings, so the flyback book is the one that needs
    the addition and it needs exactly these two entries. Nothing is renamed: an
    existing board's ``SEC_GND`` keeps the name it has.
    """
    book = _book(FLYBACK_LIBRARY)
    family_box = list(book["PWR-GND"].body)
    for ref, _net in PER_DOMAIN_FLAGS:
        assert ref in book, (
            f"{ref} is not in the flyback book, so 173's per-domain mapping falls "
            "back to the one family symbol and the two domains read as one"
        )
        profile = book[ref]
        assert not profile.pins, (
            f"{ref}: a flag is identified by having no pins — its origin IS the "
            "connection point"
        )
        assert flag_glyph_kind(profile) == "gnd", (
            f"{ref}: the family is read off the name; anything but 'gnd' hangs the "
            "glyph on the rail family's side"
        )
        assert list(profile.body) == family_box, (
            f"{ref}: body {profile.body} is not the ground family's measured box "
            f"{family_box} (inherited from PWR-GND; see the profile's own note)"
        )
    circuit = CircuitSpec.load(FLYBACK)
    ground_nets = {net.id for net in circuit.nets if net.cls == "gnd"}
    assert ground_nets == {net for _ref, net in PER_DOMAIN_FLAGS}, (
        f"the flyback circuit's grounds are {sorted(ground_nets)}; the book's "
        "per-domain flags have to be the nets this circuit actually spells"
    )


# -------------------------------------------- 2 单域网：不拆，也不需要拆


def test_a_single_domain_book_keeps_the_one_family_symbol():
    """`power_entry` / `ch340`: one ground net each, so nothing to isolate.

    173's gate is 「本页 gnd 网落在一个域就用家族共享符号」. Both books have a
    single ``gnd`` net (``GND``, the ``logic`` domain), so their pages keep
    ``PWR-GND`` and a per-domain entry would be a symbol nobody's page asks for
    — which is why this batch adds none. The compile-level half of this claim is
    173's own
    `test_173_ground_isolation.test_a_single_domain_page_keeps_the_family_symbol`.
    """
    for name in SINGLE_DOMAIN_BOOKS:
        circuit = CircuitSpec.load(SPECS / f"{name}.circuit.json")
        ground_nets = {net.id for net in circuit.nets if net.cls == "gnd"}
        assert ground_nets == {"GND"}, (
            f"{name}: this book's grounds are {sorted(ground_nets)}; the 'single "
            "domain, nothing to add' statement is about a circuit with one"
        )
        domains = {dc._ground_domain(net) for net in ground_nets}
        assert len(domains) == 1, (
            f"{name}: {sorted(domains)} — more than one domain means 173's "
            "mapping asks for a per-domain flag this batch did not add"
        )
        book = _book(SPECS / f"{name}.library.json")
        assert not any(ref in book for ref in dict(PER_DOMAIN_FLAGS)), (
            f"{name}: a per-domain ground flag appeared in a book whose circuit "
            "spells one ground — nobody's page would ask for it"
        )


# ------------------------------------- 3 多域落地页：两族各挂各旗，图不动


def test_each_family_hangs_its_own_flag_and_the_drawing_does_not_move():
    """The 150 landing page: **two** flags now, and not one unit of geometry.

    Both halves matter. Two flags is what 岳 asked for (「两族各挂各旗」), and the
    drawing standing still is what makes this a **naming** change: the profiles'
    box is the ground family's own, so the occupancy the compiler reserves, the
    rotation it picks and therefore every lead is what it was. The comparison is
    made inside the test — the same page compiled with the two refs taken out of
    the book — rather than against a recorded hash, so a future layout change
    moves both sides together and this test keeps measuring its own subject.
    """
    book = _book(FLYBACK_LIBRARY)
    circuit = CircuitSpec.load(FLYBACK)
    presentation = PresentationSpec.load(LANDING_PAGE)
    without = {
        ref: profile for ref, profile in book.items()
        if ref not in dict(PER_DOMAIN_FLAGS)
    }
    before = _compile(circuit, presentation, without)
    after = _compile(circuit, presentation, book)

    assert _refs(before) == {
        "PGND": "PWR-GND", "SEC_GND": "PWR-GND",
        "HVDC": "PWR-HVDC", "SEC_12V": "PWR-SEC_12V",
    }, "premise: without the two entries both families share one flag (173 C.5)"
    assert _refs(after) == {
        "PGND": "PWR-PGND", "SEC_GND": "PWR-SEC_GND",
        "HVDC": "PWR-HVDC", "SEC_12V": "PWR-SEC_12V",
    }, (
        "the two ground families have to ask for their own flags; the rails are "
        "untouched and stay on PWR-<net>"
    )
    counts: dict[str, int] = {}
    for symbol in after.power_symbols:
        counts[symbol.symbol_ref] = counts.get(symbol.symbol_ref, 0) + 1
    assert counts["PWR-PGND"] == 5 and counts["PWR-SEC_GND"] == 5, (
        f"every ground pin is named by its own family's flag (069 sec.1); the page "
        f"hangs {counts}"
    )
    assert set(counts) == {"PWR-PGND", "PWR-SEC_GND", "PWR-HVDC", "PWR-SEC_12V"}, (
        f"the page draws {sorted(counts)} — one shared ground symbol means two "
        "isolated domains still read as one"
    )
    assert _geometry(after) == _geometry(before), (
        "the library addition moved the drawing: the per-domain flags must carry "
        "the ground family's own box, or this is a layout change wearing a "
        "renaming's clothes"
    )


# ------------------------------------------- 4 apply 侧：仍是地旗，且只认名字


def test_the_apply_stage_reads_both_families_as_ground_flags():
    """`drawapply.flag_kind` is the gate between the plan and `sch.place_power`.

    The host is handed **kind + net** and resolves its own symbol
    (`cli.py`, `engines/draw.py`: the plan's ``symbolRef`` is recorded in the
    report, never sent), so the one thing that must keep working is that
    ``PWR-<ground name>`` reads as a ground flag. The rule is the name: the
    ``PWR-`` prefix plus `core.model.is_ground_net` on the token that follows —
    which is why ``PWR-PGND`` and ``PWR-SEC_GND`` need no case of their own.
    """
    assert drawapply.flag_kind("PGND", "PWR-PGND") == DRAW_FLAG_GROUND
    assert drawapply.flag_kind("SEC_GND", "PWR-SEC_GND") == DRAW_FLAG_GROUND
    assert drawapply.flag_kind("PGND") == DRAW_FLAG_GROUND
    with pytest.raises(drawapply.DrawPlanError):
        # 143d: a ground symbol on a rail name is a disagreement, not a choice —
        # the flag's kind is what the editor's netlist carries (029-d).
        drawapply.flag_kind("SEC_12V", "PWR-PGND")


# ------------------------------------------- 5 库之外：宿主按网名挂符号


def test_the_host_names_its_ground_symbol_after_the_net():
    """The host library carries a net-named member of the one ground family.

    Read off 毕设 FOC P1's live ``sch.geometry`` answer (2026-09-21) — a board
    drawn in the editor, so the symbols are the editor's own: net ``PGND`` carries
    ``Ground-PGND`` and net ``AGND`` carries ``Ground-AGND``, while ``GND``
    carries ``Ground-GND``. That is why a per-domain profile states the ground
    family's box and its own name: the family is one glyph family, the net is what
    picks the member. It does **not** settle which member the
    ``sch.place_power`` **API** picks for an arbitrary ground net — no probe in
    this tree ever placed a non-``GND`` ground flag through it — so this test
    claims the library's contents and nothing about the API's mapping.
    """
    payload = json.loads(HOST_READING.read_text(encoding="utf-8"))
    placed = set()
    for component in payload["components"]:
        state = component.get("state", component)
        if state.get("ComponentType") != "netflag":
            continue
        placed.add((
            str(state.get("Net") or ""),
            str((state.get("Component") or {}).get("name", "")),
        ))
    for net, symbol in (("PGND", "Ground-PGND"), ("AGND", "Ground-AGND"),
                        ("GND", "Ground-GND")):
        assert (net, symbol) in placed, (
            f"the host reading no longer shows net {net} carried by {symbol}; the "
            f"net-name convention the per-domain profiles rest on is {sorted(placed)}"
        )

"""530E: the mixed-island path — `draw islands propose` and `draw islands apply`.

The batch's contract is ``evidence/523/DESIGN.md`` §5 (the two-stage rule §5.2,
the clustering §5.3, the AI contract §5.4, the six gates §5.5, the four fallback
levels §5.6) and 岳's second ruling of 2026-10-20 — 「`islands[]` 声明优先；未声明的
部分自动聚类；自动聚类出的岛交给 AI 做语义判断」.  What each part of the file
measures:

**A. the probe** — §5.3.1's throwaway placement: one pass, one box per part, no
drawing, and the same boxes on every run (the determinism the whole proposal rests
on).

**B. the rule** — §5.3's four clauses taken apart.  Every one of the geometry-driven
cases is tested with the **boxes injected** rather than by building a board whose
probe happens to fall where the test wants: the rule is a function of the boxes and
the netlist, and a fixture that reached the same verdict through an accidental
geometry would be measuring the probe, not the rule.  The one clause that needs the
real probe (an anchor with nothing hanging on it) uses it.

**C. the proposal** — §5.4's work order: no coordinates, only facts, the nets and
their classes, who the neighbours are, the evidence, and `auto-<n>` assigned by
(anchor, smallest part) so two runs of the same input are the same bytes.

**D. the six gates** — §5.5, one test per gate, plus the four failure shapes the
gate that takes the whole document down (件守恒) is distinguished from.

**E. the fallback** — §5.6's four levels, including L3, which is not a fallback at
all: an island derived by clustering is **drawn**, and the page says so.

**F. nothing else moved** — the single-island and declared-island paths compile to
the same bytes they did before this batch (the island page's `geometry_sha256` is
pinned as a constant), which is the "compile is untouched" half of §5.2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.designintent import DesignIntent, IntentBlock, IntentRail
from boardwise.core.presentationspec import PresentationSpec, PresentationSpecError
from boardwise.core.symbolprofile import SymbolProfile, SymbolPin
from boardwise.engines import islandlayout as il
from boardwise.engines import islandproposal as ip

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

PROV = "verified_recipe"

#: The island page of the **shipped** flyback presentation (five declared islands),
#: as it stood before this batch.  Pinned because `draw compile` reads `islands[]`
#: and nothing else: a proposal command that changed the layout path would move
#: this number, and §5.2 promises it cannot.
#:
#: 532 re-pinned it (`a797e3af…` → `e165aede…`) and the reason is a layout change,
#: not a proposal one: the row pitch is now sized by where a part's own drawing
#: reaches, a part's lead has to clear that drawing from the pin it serves, and a
#: boundary stub whose outward end has no way out may try the other end of the
#: segment. All three are the same sentence — S-21 will not hide an R/C/L/IC
#: value, so the parts move — and none of them is this batch's proposal path,
#: whose two tests below still read exactly what they always did.
#: 201H re-pinned it (`e165aede…` → `565ab76d…`) and the mover is **one row**, not a
#: layout: the transformer's value row is hidden by S-21's first way out (it prints
#: through its own pin name/number rows, and both rows ride the same symbol), and a
#: text box is part of the picture the digest states. Parts, segments, junctions,
#: labels and power symbols are byte-identical (`evidence/201h/`), so §5.2's
#: promise — a proposal command cannot move the layout — is untouched.
#: 542 re-pinned it again (`565ab76d…` → `9bae9deb…`) and **this one is a layout
#: change, of exactly one island**: `FB_SENSE` no longer takes the channel inside
#: `U4`'s frame (S-10), so its long run moves from `y = 360` to `y = 370` in the
#: feedback island's own frame and the `SEC_GND` boundary stub — a name stub drawn
#: after the wiring — turns with its flag (`610,375` rot 180 → `610,315` rot 0).
#: The other four islands' parts, segments, junctions, labels, flags and texts are
#: unchanged, `page.bbox()`/`page.offsets` do not move, and §5.2's promise still
#: holds: the digest changed because a conductor moved in the *layout*, not because
#: anything a proposal command does could move it.
#: 542-C11 re-pinned it a third time (`9bae9deb…` → `bc5e1b1f…`), and this one is
#: the **text-clearance** rule, again as routing inside two islands and nothing
#: else: `secondary`'s `SEC_12V` link now bends at `x = 875` instead of
#: `872.4402373472949` (which *was* `C11`'s value row's right edge, i.e. zero
#: clearance), and `feedback`'s `FB_SENSE` long run moves from `y = 370` to
#: `y = 372` in the page's own frame (the host frame reads `540 → 542`; `U4`'s
#: reference row's bottom edge was the same zero), with `SEC_12V`'s junction
#: following it to `875, 95`. `C11`'s value is still printed (S-21; no text row is
#: hidden), all 37 printed rows keep >= 2 units from every conductor, and
#: `page.offsets`/`page.bbox()` do not move — §5.2's promise holds for the same
#: reason as the two re-pins above: a conductor moved in the layout, and no
#: proposal command can move one.
#: 542-B1 re-pinned it a fourth time (`bc5e1b1f…` → `bb1a6732…`), and the movers
#: are **four signal carriers and nothing else** — S-20's horizontal-word rule,
#: applied to the wire a label hangs on (the host rows a name along its wire's
#: longest straight run, so the carrier is the only lever): `LED_K` in `feedback`
#: and in `bridge` each take **one bend** (clear 30-unit vertical leg + 35-unit
#: horizontal leg, the horizontal being strictly the longer run), `LED_A` in
#: `feedback` and `VFB_NF` in `control` take a **straight horizontal** stub. The
#: electrical readings are unchanged — 22 names for 22 blobs, 44 source pin feet
#: still endpoints of their own net's runs, 37 printed rows all >= 2 units from
#: every conductor, no crossing, no diagonal — and the ten rail flags keep their
#: nets and rotations. `page.offsets`/`page.bbox()` **do** move this time (530G
#: pins them): `primary`'s offset is unchanged and the other four blocks are packed
#: elsewhere because two grew by the bend, so the digest's increment is four
#: carriers plus a rigid translation. §5.2's promise is untouched for the same
#: reason as every re-pin above: a batched layout decision moved the picture, and
#: no proposal command can move a carrier.
FLYBACK_ISLAND_PAGE_SHA256 = (
    "bb1a6732c2ada7dead56a54eae853d654327d0a1d5d1ce2d29526d5d27766c64"
)


# ------------------------------------------------------------- the synthetic kit


def _ic(ref: str, pins: int, *, side: str = "left") -> SymbolProfile:
    """A small IC: ``pins`` pins down one side, a body and nothing else."""
    sign = -1.0 if side == "left" else 1.0
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-30.0, -40.0, 30.0, 40.0),
        pins=[
            SymbolPin(
                number=str(index + 1), tip=(sign * 50.0, 30.0 - 10.0 * index),
                name=f"P{index + 1}",
                direction="left" if side == "left" else "right", length=10.0,
            )
            for index in range(pins)
        ],
    )


def _passive(ref: str = "R0402") -> SymbolProfile:
    """Two pins on the vertical axis, tips 50 out — a resistor's own geometry."""
    return SymbolProfile(
        symbol_ref=ref, title="Passive", body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up",
                      length=10.0),
            SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down",
                      length=10.0),
        ],
    )


def _book() -> dict[str, SymbolProfile]:
    return {
        "IC6": _ic("IC6", 6), "IC4": _ic("IC4", 4, side="right"),
        "R0402": _passive(),
    }


def _part(part_id: str, symbol: str, value: str = "") -> dict:
    return {"id": part_id, "symbolRef": symbol, "value": value, "provenance": PROV}


def _net(net_id: str, cls: str, members: list[str]) -> dict:
    return {"id": net_id, "class": cls, "members": list(members), "provenance": PROV}


def _circuit(parts: list[dict], nets: list[dict]) -> CircuitSpec:
    return CircuitSpec.from_dict({"parts": parts, "nets": nets})


def _payload(
    parts: list[str], islands: list[dict] | None = None, *, grammar: str = "flyback",
) -> dict:
    body: dict = {
        "grammarRef": grammar,
        "modules": [{"id": "main", "parts": list(parts), "role": "tube"}],
    }
    if islands is not None:
        body["islands"] = islands
    return body


def _flyback() -> tuple[CircuitSpec, dict, dict[str, SymbolProfile]]:
    """The real document: 19 parts, five declared islands (the shipped spec)."""
    book: dict[str, SymbolProfile] = {}
    for entry in json.loads(
        (SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8")
    )["profiles"]:
        profile = SymbolProfile.from_dict(entry)
        book[profile.symbol_ref] = profile
    payload = json.loads(
        (SPECS / "flyback_uc3845.presentation.json").read_text(encoding="utf-8")
    )
    return CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"), payload, book


def _inject(monkeypatch, table: dict[str, tuple[float, float, float, float]]):
    """Answer the probe with boxes the test chose (see the module docstring)."""

    def fake(circuit, parts, profiles, **kwargs):  # noqa: ANN001, ARG001
        return {part_id: table[part_id] for part_id in parts}

    monkeypatch.setattr(il, "probe_boxes", fake)


def _box(x0: float, y0: float, width: float, height: float):
    return (x0, y0, x0 + width, y0 + height)


# ------------------------------------------------------------------ A: the probe


def test_the_probe_lays_the_anchors_out_and_measures_every_part():
    """§5.3.1 step 1 and 4: one row of anchors, and a box per part, nothing else.

    The probe is the one place in this batch that computes geometry without
    drawing anything.  What it must do is measure every part it was given — a
    missing box is a part the clustering then has no distance for — and put the
    anchors (≥3 pins) on one row in the order §1.6 uses.
    """
    book = _book()
    circuit = _circuit(
        [_part("U2", "IC4"), _part("U1", "IC6"), _part("R1", "R0402")],
        [_net("SIG", "signal", ["U1.1", "R1.1"])],
    )
    boxes = il.probe_boxes(
        circuit, ["U2", "U1", "R1"], book,
        anchor_min_pins=ip.ANCHOR_MIN_PINS, orphan_gap=ip.ATTACH_MAX_GAP,
    )
    assert set(boxes) == {"U1", "U2", "R1"}
    assert boxes["U2"][2] < boxes["U1"][0] or boxes["U1"][2] < boxes["U2"][0], (
        "the two anchors must be laid out side by side, not on top of each other"
    )
    assert boxes["U1"][3] <= boxes["U2"][3] and boxes["U1"][1] >= boxes["U2"][1], (
        "the anchors share one row: same vertical band"
    )


def test_the_probe_never_puts_two_boxes_on_top_of_each_other():
    """§5.3.1's product is a **gap**; two boxes sharing space measure zero.

    This is the one thing the batch adds to §5.3.1 (it says nothing about a taken
    place): the probe walks a part along its own row until it is clear.  Measured
    on the real flyback's 19 parts, no two boxes intersect.
    """
    circuit, _payload_doc, book = _flyback()
    parts = [part.id for part in circuit.parts]
    boxes = il.probe_boxes(
        circuit, parts, book,
        anchor_min_pins=ip.ANCHOR_MIN_PINS, orphan_gap=ip.ATTACH_MAX_GAP,
    )
    hits = [
        (first, second)
        for index, first in enumerate(parts)
        for second in parts[index + 1:]
        if il._overlaps(boxes[first], boxes[second])  # noqa: SLF001
    ]
    assert hits == [], f"overlapping probe boxes: {hits}"


def test_the_probe_is_a_function_of_the_documents():
    """Same input, same boxes — the determinism the proposal file rests on."""
    circuit, _payload_doc, book = _flyback()
    parts = [part.id for part in circuit.parts]
    arguments = dict(anchor_min_pins=ip.ANCHOR_MIN_PINS, orphan_gap=ip.ATTACH_MAX_GAP)
    first = il.probe_boxes(circuit, parts, book, **arguments)
    second = il.probe_boxes(circuit, parts, book, **arguments)
    assert first == second


def test_box_gap_is_the_shortest_distance_between_the_two_boxes():
    """`box_gap` — the only measurement the clustering compares."""
    assert il.box_gap((0, 0, 10, 10), (30, 0, 40, 10)) == 20
    assert il.box_gap((0, 0, 10, 10), (10, 0, 20, 10)) == 0, "touching is zero"
    assert il.box_gap((0, 0, 10, 10), (13, 14, 20, 20)) == pytest.approx(5.0)


# ------------------------------------------------------------- B: the clustering


def _pair(
    monkeypatch,
    table: dict[str, tuple[float, float, float, float]],
    nets: list[dict],
    *,
    parts: list[str],
) -> tuple[list[ip.Cluster], list[str]]:
    """One cluster call over two anchors and one candidate part."""
    monkeypatch.setattr(il, "probe_boxes", None)
    _inject(monkeypatch, table)
    book = {**_book(), "IC3": _ic("IC3", 3)}
    circuit = _circuit(
        [
            _part("A1", "IC6"), _part("A2", "IC3"), _part("P1", "R0402"),
        ],
        nets,
    )
    payload = _payload(parts, islands=None)
    declared = ip.read_declared(payload)
    return ip.cluster_unplaced(circuit, declared, book)


def test_a_part_attaches_to_the_anchor_it_shares_a_net_with(monkeypatch):
    """§5.3 clause 1's first half: the nearest anchor **is** the one they share."""
    clusters, _ = _pair(
        monkeypatch,
        {"A1": _box(0, 0, 10, 10), "A2": _box(120, 0, 10, 10),
         "P1": _box(20, 0, 10, 10)},
        [_net("SIG", "signal", ["A1.1", "P1.1"])],
        parts=["A1", "A2", "P1"],
    )
    by_id = {cluster.island_id: cluster for cluster in clusters}
    assert len(clusters) == 2, "A1's cluster and A2's own cluster"
    assert by_id["auto-1"].parts == ("A1", "P1")
    assert by_id["auto-2"].parts == ("A2",)


def test_a_part_with_no_shared_net_still_attaches_inside_the_tight_gap(monkeypatch):
    """§5.3 clause 1's second half: `TIGHT_GAP` is the 「近到不必共网」 floor."""
    clusters, _ = _pair(
        monkeypatch,
        {"A1": _box(0, 0, 10, 10), "A2": _box(200, 0, 10, 10),
         "P1": _box(30, 0, 10, 10)},
        [],  # no nets at all: nothing is shared with anybody
        parts=["A1", "A2", "P1"],
    )
    assert [cluster.parts for cluster in clusters] == [("A1", "P1"), ("A2",)]


def test_a_part_in_the_transition_band_goes_to_the_anchor_it_shares_a_net_with(monkeypatch):
    """§5.3 clause 2 — the batch's own correction to 522's plain "nearest within 120".

    `P1` is 41 units from `A1` (over `TIGHT_GAP` 40) and shares no net with it,
    so clause 1 does **not** fire even though `A1` is well inside
    `ATTACH_MAX_GAP`; it shares `SIG` with `A2`, 140 units away, which is inside
    `ATTACH_MAX_GAP_NET` 200.  That is 522's own audit criterion (「与锚共一条信号
    网」) doing the deciding, and the whole reason the design added the clause:
    the probe measured "nearest anchor" at 76%, with every error in this band.
    """
    clusters, _ = _pair(
        monkeypatch,
        {"A1": _box(51, 0, 10, 10), "A2": _box(150, 0, 10, 10),
         "P1": _box(0, 0, 10, 10)},
        [_net("SIG", "signal", ["A2.1", "P1.1"])],
        parts=["A1", "A2", "P1"],
    )
    assert [cluster.parts for cluster in clusters] == [("A1",), ("A2", "P1")]


def test_a_part_beyond_every_anchor_becomes_an_island_of_its_own(monkeypatch):
    """§5.3's last clause: 「离所有锚 >120 自成岛」 — and no shared net to rescue it."""
    clusters, _ = _pair(
        monkeypatch,
        {"A1": _box(0, 0, 10, 10), "A2": _box(200, 0, 10, 10),
         "P1": _box(130, 0, 10, 10)},
        [],
        parts=["A1", "A2", "P1"],
    )
    assert [cluster.parts for cluster in clusters] == [("A1",), ("A2",), ("P1",)]
    assert clusters[2].anchor == "P1", (
        "a cluster with no anchor of its own falls back to its busiest part "
        "(DESIGN §1.1's third rule), and the fallback is what its id is keyed on"
    )


def test_a_shared_net_does_not_reach_past_the_net_limit(monkeypatch):
    """`ATTACH_MAX_GAP_NET` 200 is a limit, not a licence: 290 is still too far."""
    clusters, _ = _pair(
        monkeypatch,
        {"A1": _box(0, 0, 10, 10), "A2": _box(400, 0, 10, 10),
         "P1": _box(100, 0, 10, 10)},
        [_net("SIG", "signal", ["A2.1", "P1.1"])],
        parts=["A1", "A2", "P1"],
    )
    assert [cluster.parts for cluster in clusters] == [("A1",), ("A2",), ("P1",)]


def test_a_declared_island_is_never_re_clustered(monkeypatch):
    """声明优先: a part a declared island names is not this command's to move."""
    _inject(monkeypatch, {
        "A1": _box(0, 0, 10, 10), "T1": _box(100, 0, 10, 10),
        "P1": _box(300, 0, 10, 10),
    })
    book = {**_book(), "XFMR": _ic("XFMR", 4)}
    circuit = _circuit(
        [_part("T1", "XFMR"), _part("A1", "IC6"), _part("P1", "R0402")],
        [_net("SIG", "signal", ["T1.1", "P1.1"])],
    )
    declared = ip.read_declared(
        _payload(["T1", "A1", "P1"], islands=[{"id": "bridge", "parts": ["T1"]}])
    )
    clusters, unknown = ip.cluster_unplaced(circuit, declared, book)
    assert unknown == []
    assert all("T1" not in cluster.parts for cluster in clusters), (
        "a declared part must not appear in any cluster"
    )


def test_a_part_the_library_does_not_have_is_reported_not_placed():
    """R3: 找不到就报，不许自行解释。"""
    book = _book()
    circuit = _circuit([_part("U1", "IC6"), _part("R1", "R0402")], [])
    declared = ip.read_declared(_payload(["U1", "R1", "GHOST"]))
    clusters, unknown = ip.cluster_unplaced(circuit, declared, book)
    assert unknown == ["GHOST"]
    assert all("GHOST" not in cluster.parts for cluster in clusters)


def test_a_spec_that_declares_some_of_its_parts_is_read_but_not_by_the_spec_reader():
    """§5.1: the document this command exists for is one `parse_islands` refuses.

    Read leniently by `read_declared` (the proposal's business), and still refused
    by the layout layer's own reader — which is what keeps "declare half" out of
    the compiler.
    """
    payload = _payload(["U1", "R1", "R2"], islands=[{"id": "a", "parts": ["U1"]}])
    declared = ip.read_declared(payload)
    assert declared.parts == ("U1", "R1", "R2")
    assert declared.ids == ("a",)
    assert declared.complete is False
    with pytest.raises(PresentationSpecError):
        PresentationSpec.from_dict(payload)


def test_the_lenient_reader_still_refuses_what_the_document_decides_on_its_own():
    """Leniency is about **completeness** and nothing else (§5.1)."""
    for islands, why in (
        ([{"id": "a", "parts": ["U1"]}, {"id": "a", "parts": ["R1"]}], "duplicate id"),
        ([{"id": "a", "parts": ["U1"]}, {"id": "b", "parts": ["U1", "R1"]}],
         "a part in two islands"),
        ([{"id": "a", "parts": ["GHOST"]}], "a part the spec does not have"),
        ([{"id": "all", "parts": ["U1"]}], "the implicit island's id"),
        ([{"id": "a", "parts": []}], "an island with no parts"),
        ([{"id": "a", "parts": ["U1"], "role": "nonsense"}], "an unknown role"),
        ([{"id": "a", "parts": ["U1"], "colour": "red"}], "an unknown key"),
    ):
        with pytest.raises(ip.IslandsProposalError):
            ip.read_declared(_payload(["U1", "R1"], islands=islands))
        assert why  # the loop's own documentation


# ------------------------------------------------------------- C: the proposal


def _three_clusters(monkeypatch) -> tuple[CircuitSpec, dict, dict[str, SymbolProfile]]:
    """`U1` with two satellites, `U2` with one, and `X1` alone — the demo shape."""
    _inject(monkeypatch, {
        "U1": _box(0, 0, 10, 10), "R1": _box(20, 0, 10, 10),
        "C1": _box(20, 30, 10, 10), "U2": _box(300, 0, 10, 10),
        "R2": _box(320, 0, 10, 10), "X1": _box(600, 0, 10, 10),
    })
    book = {**_book(), "XFMR": _ic("XFMR", 4)}
    circuit = _circuit(
        [
            _part("T1", "XFMR", "EE25"), _part("U1", "IC6", "CTRL"),
            _part("R1", "R0402", "10k"), _part("C1", "R0402", "100n"),
            _part("U2", "IC4", "DRV"), _part("R2", "R0402", "4k7"),
            _part("X1", "R0402", "8MHz"),
        ],
        [
            _net("VIN", "power", ["U1.4", "T1.1"]),
            _net("SIG", "signal", ["U1.1", "R1.1"]),
            _net("VCC", "power", ["U1.2", "C1.1"]),
            _net("PGND", "gnd", ["U1.3", "C1.2", "R1.2"]),
            _net("SIG2", "signal", ["U2.1", "R2.1"]),
            _net("SGND", "gnd", ["U2.2", "R2.2"]),
            _net("OSC", "signal", ["X1.1"]),
        ],
    )
    payload = _payload(
        ["T1", "U1", "R1", "C1", "U2", "R2", "X1"],
        islands=[{"id": "bridge", "role": "bridge", "parts": ["T1"]}],
    )
    return circuit, payload, book


def test_the_proposal_is_the_same_bytes_on_every_run(monkeypatch):
    """§5.4's ids and the file itself: no hash, no clock, no dictionary walk."""
    circuit, payload, book = _three_clusters(monkeypatch)
    first = ip.build_proposal(circuit, payload, book)
    second = ip.build_proposal(circuit, payload, book)
    assert ip.render_proposal(first.document) == ip.render_proposal(second.document)
    assert first.document["clusters"] == second.document["clusters"]


def test_the_auto_ids_run_by_anchor_and_then_by_the_smallest_part(monkeypatch):
    """§5.4: ``auto-<n>`` is assigned by the clusters' own order, from 1."""
    circuit, payload, book = _three_clusters(monkeypatch)
    proposal = ip.build_proposal(circuit, payload, book)
    assert [cluster.island_id for cluster in proposal.clusters] == [
        "auto-1", "auto-2", "auto-3",
    ]
    assert [cluster.parts for cluster in proposal.clusters] == [
        ("C1", "R1", "U1"), ("R2", "U2"), ("X1",),
    ]


def test_a_work_order_carries_facts_and_no_coordinates(monkeypatch):
    """§5.4's transport rule: coordinates would invite a geometric answer."""
    circuit, payload, book = _three_clusters(monkeypatch)
    ticket = ip.build_proposal(circuit, payload, book).document["clusters"][0]
    assert set(ticket) == {
        "islandId", "parts", "localNets", "netClasses", "crossingNets",
        "neighbours", "evidence", "declaredBy",
    }
    assert ticket["declaredBy"] == "clustering"
    assert set(ticket["parts"][0]) == {"id", "symbolRef", "value", "pins"}
    rendered = json.dumps(ticket, ensure_ascii=False)
    assert not any(f'"{key}":' in rendered for key in ("x", "y", "origin", "rotation"))


def test_the_work_order_names_the_clusters_nets_classes_and_neighbours(monkeypatch):
    """The facts a judgement is allowed to cite (`netClasses`, `crossingNets`,
    `neighbours`) are the ones the model would otherwise have to guess."""
    circuit, payload, book = _three_clusters(monkeypatch)
    ticket = ip.build_proposal(circuit, payload, book).document["clusters"][0]
    assert ticket["localNets"] == ["SIG", "VCC", "PGND"], "in the netlist's order"
    assert ticket["netClasses"]["VCC"] == "power"
    assert ticket["netClasses"]["PGND"] == "gnd"
    assert ticket["crossingNets"] == ["VIN"]
    assert ticket["neighbours"] == [{"islandId": "bridge", "nets": ["VIN"]}]
    assert ticket["evidence"]["anchorCandidate"] == "U1"
    assert "U1" in ticket["evidence"]["why"]


def test_a_fully_declared_spec_proposes_nothing():
    """The real flyback declares all five islands: 声明优先 leaves nothing to ask."""
    circuit, payload, book = _flyback()
    proposal = ip.build_proposal(circuit, payload, book)
    assert proposal.empty
    assert proposal.document["clusters"] == []
    assert proposal.document["unresolved"] == []
    assert proposal.declared.complete
    assert len(proposal.document["declared"]) == 5


def test_the_proposal_names_the_parts_it_could_not_place(monkeypatch):
    circuit, payload, book = _three_clusters(monkeypatch)
    payload = json.loads(json.dumps(payload))
    payload["modules"][0]["parts"].append("GHOST")
    proposal = ip.build_proposal(circuit, payload, book)
    assert proposal.document["unresolved"] == ["GHOST"]
    assert any("GHOST" in note for note in proposal.document["notes"])


# ---------------------------------------------------------------- D: six gates


def _proposal_and_judge(monkeypatch, judgement):
    circuit, payload, book = _three_clusters(monkeypatch)
    proposal = ip.build_proposal(circuit, payload, book)
    result = ip.apply_judgement(proposal.document, proposal.declared, judgement)
    return proposal, result


def _accept(name: str = "控制", role: str = "control", *, reason: str = "U1 是锚"):
    return {"islandId": "auto-1", "verdict": "accept", "name": name, "role": role,
            "reason": reason}


def test_gate_one_states_an_id_the_proposal_printed(monkeypatch):
    """§5.5 闸 1: a judgement answers a work order, and there is no work order here."""
    _proposal, result = _proposal_and_judge(monkeypatch, [
        {"islandId": "auto-9", "verdict": "accept", "name": "x", "reason": "auto-9"},
    ])
    rejected = [row for row in result.report["entries"] if row.get("gate") == 1]
    assert len(rejected) == 1 and rejected[0]["fallback"] == "rejected"
    assert result.written, "闸 1 只拒这一条，其余照收"
    assert {island.id for island in result.islands} == {
        "bridge", "auto-1", "auto-2", "auto-3",
    }


def test_gate_one_refuses_a_work_order_answered_twice(monkeypatch):
    _proposal, result = _proposal_and_judge(monkeypatch, [
        _accept(), _accept(name="另一个"),
    ])
    rejected = [row for row in result.report["entries"] if row.get("gate") == 1]
    assert len(rejected) == 2
    assert all("appears 2 times" in row["why"] for row in rejected)


def test_gate_two_holds_the_verdict_vocabulary_and_the_keys_each_one_needs(monkeypatch):
    """§5.5 闸 2: accept→`name`, split→`split`, merge→`mergeWith`."""
    shapes = [
        {"islandId": "auto-1", "verdict": "maybe", "reason": "U1"},
        {"islandId": "auto-2", "verdict": "accept", "reason": "U2"},
        {"islandId": "auto-3", "verdict": "split", "reason": "X1"},
    ]
    _proposal, result = _proposal_and_judge(monkeypatch, shapes)
    gates = [row.get("gate") for row in result.report["entries"]]
    assert gates == [2, 2, 2]
    assert all(row["fallback"] == "L0" for row in result.report["entries"])
    assert result.written


def test_gate_three_is_the_only_one_that_refuses_the_whole_document(monkeypatch):
    """§5.5 闸 3 / §5.6 L2: 件守恒 — and nothing at all is written."""
    _proposal, result = _proposal_and_judge(monkeypatch, [
        {"islandId": "auto-1", "verdict": "split",
         "split": [["U1"], ["R1"], ["C1"], ["GHOST"]], "reason": "U1 分三处"},
    ])
    assert not result.written
    assert result.report["gate"] == ip.APPLY_GATE_CONSERVATION
    assert "GHOST" in result.report["why"]
    assert result.islands == _proposal.declared.islands, (
        "a refused judgement leaves the declared islands exactly as they were"
    )


def test_gate_three_also_catches_a_dropped_part(monkeypatch):
    _proposal, result = _proposal_and_judge(monkeypatch, [
        {"islandId": "auto-1", "verdict": "split",
         "split": [["U1"], ["R1"]], "reason": "U1 与 R1"},
    ])
    assert not result.written
    assert result.report["gate"] == ip.APPLY_GATE_CONSERVATION


def test_gate_four_holds_the_role_vocabulary_and_the_name_length(monkeypatch):
    """§5.5 闸 4: `ISLAND_ROLES` ∪ {""}, and a name that fits a report column."""
    _proposal, result = _proposal_and_judge(monkeypatch, [
        _accept(role="totally-a-lie"),
        {"islandId": "auto-2", "verdict": "accept", "name": "x" * 13,
         "reason": "U2"},
    ])
    gates = [row.get("gate") for row in result.report["entries"]]
    assert gates == [4, 4]
    assert result.written, "the clusters still land, as §5.6 L0 islands"


def test_gate_four_refuses_a_name_on_a_split(monkeypatch):
    _proposal, result = _proposal_and_judge(monkeypatch, [
        {"islandId": "auto-2", "verdict": "split", "name": "一个名字",
         "split": [["U2"], ["R2"]], "reason": "U2/R2"},
    ])
    assert [row.get("gate") for row in result.report["entries"]] == [4]


def test_gate_five_wants_a_reason_that_cites_the_work_order(monkeypatch):
    """§5.5 闸 5: 521's citation rule — a judgement may not say what the proposal did not."""
    _proposal, result = _proposal_and_judge(monkeypatch, [
        _accept(reason=""),
        {"islandId": "auto-2", "verdict": "accept", "name": "驱动",
         "reason": "我看这张图觉得挺好", "role": "primary"},
    ])
    gates = [row.get("gate") for row in result.report["entries"]]
    assert gates == [5, 5]
    assert "cites none of the names" in result.report["entries"][1]["why"]


def test_gate_five_accepts_a_reason_that_names_a_net(monkeypatch):
    _proposal, result = _proposal_and_judge(monkeypatch, [
        _accept(reason="VCC 与 PGND 都挂在 U1 上"),
    ])
    assert result.report["entries"][0]["gate"] is None
    written = {item["islandId"]: item for item in result.report["islands"]}
    assert written["auto-1"]["role"] == "control"


def test_gate_six_never_reaches_into_a_declared_island(monkeypatch):
    """§5.5 闸 6: a proposal may rearrange what it proposed, and no more."""
    _proposal, result = _proposal_and_judge(monkeypatch, [
        {"islandId": "auto-3", "verdict": "merge", "mergeWith": ["bridge"],
         "reason": "X1 与 T1 共 OSC"},
    ])
    assert [row.get("gate") for row in result.report["entries"]] == [6]
    assert result.written
    assert {island.id for island in result.islands} == {
        "bridge", "auto-1", "auto-2", "auto-3",
    }, "the refused merge falls back to the geometric cluster, it is not lost"


def test_the_accept_shape_writes_the_partition_and_the_role(monkeypatch):
    proposal, result = _proposal_and_judge(monkeypatch, [
        _accept(name="控制与偏置", role="control", reason="U1/R1/C1 共 PGND"),
        {"islandId": "auto-2", "verdict": "accept", "name": "栅驱动",
         "role": "primary", "reason": "U2/R2 共 SIG2"},
        {"islandId": "auto-3", "verdict": "accept", "name": "晶振", "role": "",
         "reason": "X1 只经 OSC 与 T1 相连"},
    ])
    islands = {island.id: island for island in result.islands}
    assert islands["auto-1"].role == "control"
    assert islands["auto-1"].parts == ["C1", "R1", "U1"]
    assert islands["auto-3"].role == ""
    assert islands["bridge"].parts == ["T1"]


def test_the_split_shape_writes_one_island_per_group(monkeypatch):
    """§5.4: the grain of a verdict is a whole cluster or a whole group of parts."""
    _proposal, result = _proposal_and_judge(monkeypatch, [
        {"islandId": "auto-1", "verdict": "split",
         "split": [["U1"], ["R1", "C1"]], "reason": "U1 是核心，R1/C1 是外围"},
    ])
    islands = {island.id: island.parts for island in result.islands}
    assert islands["auto-1-1"] == ["U1"]
    assert islands["auto-1-2"] == ["C1", "R1"]
    assert "auto-1" not in islands, "the cluster's own id is replaced by its groups"
    written = {item["islandId"]: item for item in result.report["islands"]}
    assert written["auto-1-1"]["fromCluster"] == "auto-1"
    assert written["auto-1-1"]["role"] == "", (
        "one role may not be claimed for several islands (§5.4)"
    )


def test_the_merge_shape_joins_two_clusters_into_one(monkeypatch):
    _proposal, result = _proposal_and_judge(monkeypatch, [
        _accept(name="控制", role="control", reason="U1 是锚"),
        {"islandId": "auto-3", "verdict": "merge", "mergeWith": ["auto-1"],
         "reason": "X1 只经 OSC 与 U1 相连，与 U1 同处一岛"},
    ])
    islands = {island.id: island.parts for island in result.islands}
    assert islands["auto-1"] == ["C1", "R1", "U1", "X1"]
    assert "auto-3" not in islands
    assert islands["auto-2"] == ["R2", "U2"]


def test_a_merge_cycle_falls_back_instead_of_being_followed(monkeypatch):
    _proposal, result = _proposal_and_judge(monkeypatch, [
        {"islandId": "auto-1", "verdict": "merge", "mergeWith": ["auto-2"],
         "reason": "U1 并进 U2"},
        {"islandId": "auto-2", "verdict": "merge", "mergeWith": ["auto-1"],
         "reason": "U2 并进 U1"},
    ])
    gates = [row.get("gate") for row in result.report["entries"]]
    assert gates[-2:] == [2, 2], (
        "both ends of the cycle are reported, after the two rows that resolved"
    )
    islands = {island.id: island.parts for island in result.islands}
    assert islands["auto-1"] == ["C1", "R1", "U1"] and islands["auto-2"] == ["R2", "U2"]


def test_a_judgement_is_only_ever_read_through_the_gates(monkeypatch):
    """§5.4's closed contract: an unknown key is not a second way to say something.

    The gates read the keys they know and ignore everything else — a judgement
    cannot smuggle a part in through a field nobody asked about, because the
    partition is conserved from the **proposal** (闸 3), never from the judgement.
    """
    _proposal, result = _proposal_and_judge(monkeypatch, [
        _accept(reason="U1 是锚") | {"extra": ["GHOST"]},
    ])
    assert result.written
    assert all("GHOST" not in island.parts for island in result.islands)


# --------------------------------------------------------------- E: the fallback


def test_level_zero_uses_the_geometric_cluster_exactly_as_it_was(monkeypatch):
    """§5.6 L0: 不并、不切，`role = ""`，`name = ""`."""
    proposal, result = _proposal_and_judge(monkeypatch, [])
    assert result.written
    assert [island.id for island in result.islands] == [
        "bridge", "auto-1", "auto-2", "auto-3",
    ]
    assert all(
        island.role == "" for island in result.islands if island.id != "bridge"
    )
    assert result.derived == ["auto-1", "auto-2", "auto-3"]


def test_level_one_falls_back_only_the_entry_that_failed(monkeypatch):
    """§5.6 L1: 局部失败不连坐."""
    _proposal, result = _proposal_and_judge(monkeypatch, [
        _accept(name="控制与偏置", role="control", reason="U1 是锚"),
        {"islandId": "auto-2", "verdict": "accept", "name": "栅驱动",
         "role": "not-a-role", "reason": "U2"},
        {"islandId": "auto-3", "verdict": "accept", "name": "晶振", "role": "",
         "reason": "X1 只经 OSC 与 T1 相连"},
    ])
    islands = {island.id: island for island in result.islands}
    assert islands["auto-1"].role == "control"
    assert islands["auto-3"].role == ""
    assert islands["auto-2"].role == "", "the failed entry is back to L0"
    assert [row.get("gate") for row in result.report["entries"]] == [None, 4, None]


def test_level_two_is_a_whole_document_refusal(monkeypatch):
    """§5.6 L2: gate 3 fails → the spec and the intent are untouched."""
    circuit, payload, book = _three_clusters(monkeypatch)
    proposal = ip.build_proposal(circuit, payload, book)
    document = json.loads(json.dumps(proposal.document))
    document["judgement"] = [{
        "islandId": "auto-1", "verdict": "split", "split": [["U1"], ["R1"]],
        "reason": "U1 与 R1",
    }]
    intent = DesignIntent(rails=[IntentRail(net="VIN", slots={"targetVoltage": "12V"},
                                            provenance="user_stated")])
    application = ip.apply_proposal(document, payload, intent=intent)
    assert not application.result.written
    assert application.spec is None
    assert application.payload is None
    assert application.intent is intent, "nothing to write, so nothing was made"


def test_level_two_leaves_the_presentation_document_alone_on_disk(monkeypatch):
    circuit, payload, book = _three_clusters(monkeypatch)
    proposal = ip.build_proposal(circuit, payload, book)
    document = json.loads(json.dumps(proposal.document))
    document["judgement"] = [{
        "islandId": "auto-1", "verdict": "accept", "name": "x",
        "reason": "GHOST nowhere",
    }]
    # A reason with no token falls back (L1), not the document (L2) — and the
    # difference is what this test pins: only 件守恒 takes everything with it.
    application = ip.apply_proposal(document, payload)
    assert application.result.written


def test_level_three_draws_the_page_and_says_where_the_partition_came_from():
    """§5.6 L3: an island derived by clustering is **legal** and the page says so."""
    book: dict[str, SymbolProfile] = {}
    for entry in json.loads(
        (SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8")
    )["profiles"]:
        profile = SymbolProfile.from_dict(entry)
        book[profile.symbol_ref] = profile
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    payload = json.loads(
        (SPECS / "flyback_uc3845.presentation.json").read_text(encoding="utf-8")
    )
    payload["islands"] = [
        {"id": "bridge", "role": "bridge", "parts": ["T1", "U5"]},
        {"id": "auto-1", "parts": ["Q1", "R5", "R4", "C6", "R3", "R15", "C5", "D1"]},
        {"id": "auto-2", "parts": ["D3", "C11", "C13"]},
        {"id": "auto-3", "parts": ["R7", "R8", "U4", "R9"]},
        {"id": "auto-4", "parts": ["R10", "C10"]},
    ]
    spec = PresentationSpec.from_dict(payload)
    page = il.island_page(circuit, spec, book)
    notes = page.plan().notes
    assert any("derived by clustering, unnamed (auto-1)" in note for note in notes)
    assert any(note.startswith("[auto-1]") for note in notes), (
        "the block's own note carries the same sentence"
    )
    blocks = {block.island_id: block for block in page.blocks}
    assert il.derived_cluster_note("auto-1") in blocks["auto-1"].notes
    assert il.derived_cluster_note("bridge") not in " ".join(blocks["bridge"].notes)


def test_the_compilers_own_evidence_carries_the_same_sentence():
    """L3 reaches `result.notes` and `LayoutEvidence.notes`, not only the block."""
    from boardwise.engines import drawcompiler as dc

    circuit, payload, book = _flyback()
    payload = json.loads(json.dumps(payload))
    payload["islands"][0]["id"] = "auto-9"
    spec = PresentationSpec.from_dict(payload)
    result = dc.compile(
        circuit, spec, book,
        budget=dc.CompileBudget(),
    )
    assert any("derived by clustering, unnamed (auto-9)" in note
               for note in result.notes)


# ------------------------------------------------------- F: nothing else moved


def test_the_declared_island_page_compiles_to_the_same_geometry_as_before():
    """§5.2's other half: `compile` runs neither half of this batch.

    The shipped flyback presentation (five declared islands) is laid out by the
    same code path it always was, and its page is pinned byte for byte — so a
    proposal command that leaked into the compiler would move this number.
    """
    circuit, payload, book = _flyback()
    page = il.island_page(circuit, PresentationSpec.from_dict(payload), book)
    assert page.plan().geometry_sha256() == FLYBACK_ISLAND_PAGE_SHA256


def test_a_spec_without_islands_has_every_part_to_propose():
    """A document that states no islands is a document where nothing is declared.

    It still compiles to exactly what it always did — `islands is None` is the
    implicit island, and the proposal path is a *separate command* that writes
    nothing until somebody runs it (§5.2).  What this pins is the reading: "no
    islands" is "all of it is unplaced", not "all of it is placed".
    """
    circuit, payload, book = _flyback()
    payload = json.loads(json.dumps(payload))
    payload.pop("islands")
    declared = ip.read_declared(payload)
    assert declared.islands == ()
    assert declared.complete is False
    assert len(declared.parts) == 19
    proposal = ip.build_proposal(circuit, payload, book)
    assert not proposal.empty
    covered = [part for cluster in proposal.clusters for part in cluster.parts]
    assert sorted(covered) == sorted(declared.parts)
    assert PresentationSpec.from_dict(payload).islands is None


def test_the_intent_the_judgement_lands_in_is_a_draft():
    """§5.4: `provenance = ai_asserted` — 模型的话不会被当成人的话."""
    circuit, payload, book = _flyback()
    partial = json.loads(json.dumps(payload))
    partial["islands"] = [{"id": "bridge", "role": "bridge", "parts": ["T1", "U5"]}]
    proposal = ip.build_proposal(circuit, partial, book)
    document = json.loads(json.dumps(proposal.document))
    document["judgement"] = [
        {"islandId": cluster.island_id, "verdict": "accept",
         "name": f"块{index}", "role": "", "reason": cluster.anchor}
        for index, cluster in enumerate(proposal.clusters, start=1)
    ]
    intent = DesignIntent(rails=[IntentRail(net="HVDC", slots={"targetVoltage": "48V"},
                                            provenance="user_stated")])
    assert intent.draft is False
    application = ip.apply_proposal(document, partial, intent=intent)
    assert application.result.written
    assert application.intent.draft is True
    assert all(
        block.provenance == "ai_asserted" for block in application.intent.blocks
    )
    assert {block.id for block in application.intent.blocks} == {
        cluster.island_id for cluster in proposal.clusters
    }
    assert application.intent.rails == intent.rails, "no other section is rewritten"


def test_the_written_spec_reads_back_through_its_own_schema(monkeypatch):
    """The last check on a write: the document's closed schema, not a second one."""
    circuit, payload, book = _three_clusters(monkeypatch)
    proposal = ip.build_proposal(circuit, payload, book)
    document = json.loads(json.dumps(proposal.document))
    document["judgement"] = [{
        "islandId": cluster.island_id, "verdict": "accept",
        "name": f"块{index}", "role": "", "reason": cluster.anchor,
    } for index, cluster in enumerate(proposal.clusters, start=1)]
    application = ip.apply_proposal(document, payload)
    written = PresentationSpec.from_dict(application.payload)
    assert written.islands is not None
    assert [island.id for island in written.islands] == ["bridge", "auto-1", "auto-2", "auto-3"]
    assert sorted(
        part for island in written.islands for part in island.parts
    ) == sorted(["T1", "U1", "R1", "C1", "U2", "R2", "X1"])


def test_an_existing_block_of_the_same_id_is_replaced_not_duplicated():
    circuit, payload, book = _flyback()
    payload = json.loads(json.dumps(payload))
    payload["islands"] = [{"id": "bridge", "role": "bridge", "parts": ["T1", "U5"]}]
    proposal = ip.build_proposal(circuit, payload, book)
    document = json.loads(json.dumps(proposal.document))
    first = proposal.clusters[0]
    document["judgement"] = [{
        "islandId": first.island_id, "verdict": "accept", "name": "旧的",
        "role": "", "reason": first.anchor,
    }]
    intent = DesignIntent(blocks=[IntentBlock(id=first.island_id, kind="旧的")])
    application = ip.apply_proposal(document, payload, intent=intent)
    blocks = [block for block in application.intent.blocks
              if block.id == first.island_id]
    assert len(blocks) == 1
    assert blocks[0].parts == list(first.parts)


# ------------------------------------------------------------- G: the commands


def _write(payload: dict, path: Path) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def test_the_two_commands_run_the_whole_chain(tmp_path, capsys):
    """`draw islands propose` → judgement → `draw islands apply` → `draw compile`.

    The document is the **real flyback** with only `bridge` declared, which is the
    mixed-island case 岳's ruling is about: one island a human stated, the rest
    proposed and judged.  The compile leg asserts the one thing that matters for
    this batch — the applied spec reaches the **island** path and the page carries
    the L3 sentence — not that the page passes the gate (530F is that batch).
    """
    payload = json.loads(
        (SPECS / "flyback_uc3845.presentation.json").read_text(encoding="utf-8")
    )
    payload["islands"] = [{"id": "bridge", "role": "bridge", "parts": ["T1", "U5"]}]
    partial = tmp_path / "flyback-partial.presentation.json"
    _write(payload, partial)
    proposal_path = tmp_path / "islands-proposal.json"
    applied = tmp_path / "applied.presentation.json"
    intent_path = tmp_path / "intent.json"
    DesignIntent(rails=[
        IntentRail(net="HVDC", slots={"targetVoltage": "48V"}, provenance="user_stated"),
    ]).dump(intent_path)

    assert cli.main([
        "draw", "islands", "propose",
        "--circuit", str(SPECS / "flyback_uc3845.circuit.json"),
        "--presentation", str(partial),
        "--profiles", str(SPECS / "flyback_uc3845.library.json"),
        "--intent", str(intent_path),
        "-o", str(proposal_path),
    ]) == 0
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["clusters"], capsys.readouterr().out

    # step ②: a human or an AI fills the judgement in.  One work order is left
    # unanswered on purpose, which is §5.6 L0's whole case.
    judged = proposal["clusters"][0]
    proposal["judgement"] = [{
        "islandId": judged["islandId"], "verdict": "accept", "name": "第一块",
        "role": "primary", "reason": judged["evidence"]["anchorCandidate"],
    }]
    _write(proposal, proposal_path)

    assert cli.main([
        "draw", "islands", "apply",
        "--proposal", str(proposal_path),
        "--presentation", str(partial),
        "--out-spec", str(applied),
        "--intent", str(intent_path),
        "--json", str(tmp_path / "apply.json"),
    ]) == 0
    written = PresentationSpec.load(applied)
    assert written.islands is not None
    assert written.islands[0].id == "bridge"
    assert written.islands[1].id == judged["islandId"]
    assert written.islands[1].role == "primary"
    assert sorted(
        part for island in written.islands for part in island.parts
    ) == sorted(payload["modules"][0]["parts"])
    assert json.loads((tmp_path / "intent.json").read_text(encoding="utf-8"))[
        "blocks"
    ], "the judgement landed in the intent's blocks[]"

    code = cli.main([
        "draw", "compile",
        "--circuit", str(SPECS / "flyback_uc3845.circuit.json"),
        "--presentation", str(applied),
        "--profiles", str(SPECS / "flyback_uc3845.library.json"),
        "--json", str(tmp_path / "compile.json"),
        "--out", str(tmp_path / "previews"),
    ])
    result = json.loads((tmp_path / "compile.json").read_text(encoding="utf-8"))
    printed = capsys.readouterr().out
    assert code in (0, 5)
    assert any("derived by clustering, unnamed" in note for note in result["notes"]), (
        "the island path ran and said where its partition came from"
    )
    assert "island" in printed or "derived by clustering" in printed


def test_apply_writes_nothing_when_a_judgement_breaks_part_conservation(tmp_path, capsys):
    payload = json.loads(
        (SPECS / "flyback_uc3845.presentation.json").read_text(encoding="utf-8")
    )
    payload["islands"] = [{"id": "bridge", "role": "bridge", "parts": ["T1", "U5"]}]
    partial = tmp_path / "partial.presentation.json"
    _write(payload, partial)
    proposal_path = tmp_path / "proposal.json"
    applied = tmp_path / "applied.presentation.json"
    assert cli.main([
        "draw", "islands", "propose",
        "--circuit", str(SPECS / "flyback_uc3845.circuit.json"),
        "--presentation", str(partial),
        "--profiles", str(SPECS / "flyback_uc3845.library.json"),
        "-o", str(proposal_path),
    ]) == 0
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    first = proposal["clusters"][0]
    proposal["judgement"] = [{
        "islandId": first["islandId"], "verdict": "split",
        "split": [["T1"]], "reason": first["evidence"]["anchorCandidate"],
    }]
    _write(proposal, proposal_path)
    code = cli.main([
        "draw", "islands", "apply",
        "--proposal", str(proposal_path),
        "--presentation", str(partial),
        "--out-spec", str(applied),
    ])
    printed = capsys.readouterr().err + capsys.readouterr().out
    assert code == 5
    assert not applied.exists(), "a refused judgement writes no document at all"
    assert "conserv" in printed or "gate 3" in printed


def test_propose_reports_a_presentation_it_cannot_read(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    code = cli.main([
        "draw", "islands", "propose",
        "--circuit", str(SPECS / "flyback_uc3845.circuit.json"),
        "--presentation", str(bad),
        "--profiles", str(SPECS / "flyback_uc3845.library.json"),
    ])
    assert code == 2
    assert "not JSON" in capsys.readouterr().err


def test_propose_refuses_a_presentation_whose_islands_contradict_themselves(tmp_path, capsys):
    payload = json.loads(
        (SPECS / "flyback_uc3845.presentation.json").read_text(encoding="utf-8")
    )
    payload["islands"][1]["parts"].append("T1")
    broken = tmp_path / "contradiction.presentation.json"
    _write(payload, broken)
    code = cli.main([
        "draw", "islands", "propose",
        "--circuit", str(SPECS / "flyback_uc3845.circuit.json"),
        "--presentation", str(broken),
        "--profiles", str(SPECS / "flyback_uc3845.library.json"),
        "-o", str(tmp_path / "p.json"),
    ])
    assert code == 2
    assert "exactly one block" in capsys.readouterr().err


def test_the_help_of_both_commands_says_what_they_do(capsys):
    for command, wanted in (
        (["draw", "islands", "propose"], ("--profiles", "--presentation", "proposal")),
        (["draw", "islands", "apply"], ("--proposal", "--out-spec", "islands[]")),
        (["draw", "islands"], ("propose", "apply")),
    ):
        with pytest.raises(SystemExit) as exit_info:
            cli.main([*command, "--help"])
        assert exit_info.value.code == 0
        printed = capsys.readouterr().out
        for token in wanted:
            assert token in printed, f"{command} --help does not mention {token}"

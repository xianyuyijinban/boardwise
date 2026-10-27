"""530D: the name per **blob**, the wire viewed as a name carrier, and the partition.

Three clauses of the batch's contract, and each one is a *rule about a rule*
(`evidence/523/DESIGN.md` §7.1, §14.6, `docs/schematic-style-spec.md` §七.5):

**A. naming at the blob's grain** — S-14, 「一条网的每个连通分量，恰好一个名字」.
530D's change is the *grain* of the boundary name, from 520l's 「每岛每跨岛网恰好
一个名」 to the connected component of what is **drawn**; on a page where every net's
own segment is in one piece the two rules draw the same picture, which is why this
batch moves no pin, no stub and no digest (measured: the real flyback page is
byte-identical). The tests below take the grain apart: the real page (one blob per
named net, 22 names for 22 blobs) and a page whose wiring is **refused**, where one
net comes apart into several blobs and S-14 then asks for a name on each.

**B. the wire as a name carrier** — 岳's ruling A: 「名字只住在旗标/标签上」. A wire
is landed with a name exactly when the wire **is** the drawing's label
(`drawapply.wire_carries_its_name`), because on this host a label has no primitive
of its own (`sch.place_netlabel` is unusable, 029, `docs/pits.md` #9) — and every
other wire, a rail's own conductor and an island-internal net's, lands unnamed.
Before this batch every non-flagged wire carried its name, and the host printed a
blue row at the middle of every one of those segments: 8 of the flyback page's 8
hard violations.

**C. the connectivity reading** — with the name off the wire, "which net is this"
is read in two halves (`drawapply._live_problems`, `drawapply.live_partitions`): a
net the page states a name for (a flag, or a label's wire) is read **by name**, and
every other net by **partition equivalence** — 「同一组脚 ⇔ 同一条网」. Both halves
refuse the same two shapes, and the mapping is written out so the reading can be
read: one spec net **drawn as two** and two spec nets **drawn as one**.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutSource, label_wire_indices
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPose, SymbolProfile
from boardwise.engines import drawapply
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il
from boardwise.engines import readability as rb

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


def _library(stem: str) -> dict[str, SymbolProfile]:
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


def _tips(block: il.IslandBlock, book) -> dict[il.IslandPin, tuple[float, float]]:
    return {
        il.IslandPin(part_id=part.part_id, pin=pin.number): il._posed_point(
            pin.tip,
            SymbolPose(rotation=part.rotation, mirror=part.mirror),
            (part.x, part.y),
        )
        for part in block.parts
        for pin in book[part.symbol_ref].pins
    }


def _names_and_blobs(page, circuit, presentation, book) -> tuple[int, int]:
    """S-14's reading: names over every named net, blobs over every named net.

    The scope is the nets the island **names** (a crossing net, or a one-pin net —
    §7.2.4: an island-internal net of a rail or a signal is a pure conductor and
    carries no name at all, which is S-19 and not a violation of S-14).
    """
    subgraphs = {item.island_id: item for item in il.island_subgraphs(circuit, presentation)}
    names = blobs = 0
    for block in page.blocks:
        subgraph = subgraphs[block.island_id]
        here = _tips(block, book)
        for net in list(subgraph.named_nets) + list(subgraph.single_pin_nets):
            blobs += len(il._net_components(net, here, block.segments))
            names += sum(1 for item in block.labels if item.net == net.net_id)
            names += sum(1 for item in block.power_symbols if item.net == net.net_id)
    return names, blobs


# ------------------------------------------------- A. the name is the blob's


def test_the_real_page_names_every_blob_exactly_once() -> None:
    """The acceptance reading: **names − blobs = 0** (S-14, both directions).

    A name short would leave a conductor a reader cannot name; a name extra would
    say one net twice on one blob.  On this page every named net's own segment is in
    one piece, so the count is also the witness that 530D's finer rule changed the
    *statement* and not the picture — while the geometry digest below is the witness
    of every later batch that moved the *drawing*: 532 (row pitch), 201H (the
    transformer's value row), 542 (`FB_SENSE`'s channel off `U4`'s frame),
    542-C11 (two conductors off two text rows' own edges) and 542-B1 (four
    horizontal label carriers).
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    names, blobs = _names_and_blobs(page, circuit, presentation, book)
    assert (names, blobs) == (22, 22), (names, blobs)
    assert names - blobs == 0
    assert page.plan().geometry_sha256() == (
        "bb1a6732c2ada7dead56a54eae853d654327d0a1d5d1ce2d29526d5d27766c64"
    ), (
        "the island picture moved again — that is a *layout* batch's business and "
        "this digest is the witness of when: 532 re-pinned it from a797e3af… when "
        "the rows a part's own drawing occupies started deciding the pitch; 201H "
        "re-pinned it from e165aede… when the transformer's value row was hidden "
        "(S-21) and the digest covers text boxes; 542 re-pinned it from 565ab76d… "
        "when `FB_SENSE` stopped taking the channel inside `U4`'s frame (the "
        "`SEC_GND` boundary stub and its flag followed it; the other four islands "
        "are unchanged). The count this test owns (22 = 22) did not move. The "
        "「parts, segments, junctions, labels and flags are byte-identical」 sentence "
        "that stood here belongs to 201H's re-pin, not to this one: 542's edit is "
        "exactly one wire, one stub and one flag. 542-C11 re-pinned it again from "
        "9bae9deb… and the mover is again a conductor, not a name: `secondary`'s "
        "`SEC_12V` link bends at `x = 875` instead of `872.4402373472949` — which "
        "was `C11`'s value row's own right edge, i.e. zero clearance once the host "
        "lands two decimals — and `feedback`'s `FB_SENSE` run moves `y = 370` → "
        "`y = 372` (host frame 540 → 542; `U4`'s reference row's bottom edge was "
        "the same zero), with `SEC_12V`'s junction following to `875, 95`. `C11`'s "
        "value is still printed (S-21; 37 printed rows, all >= 2 units from every "
        "conductor), so this test's reading is untouched at 22 names for 22 blobs. "
        "542-B1 re-pinned it a fourth time (`bc5e1b1f…` → `bb1a6732…`) and the "
        "movers are **exactly four signal carriers** — S-20's horizontal-word rule, "
        "read off the wire a label hangs on rather than off its text box: `LED_K` in "
        "`feedback` and in `bridge` each gain **one bend** (a 30-unit vertical leg on "
        "the clear stub plus a 35-unit horizontal one, so the host's longest run — "
        "and therefore the row it prints — is the horizontal leg), and `LED_A` in "
        "`feedback` and `VFB_NF` in `control` become **straight horizontal** stubs. "
        "No connection moved: 22 names for 22 blobs, all 44 source pin feet are "
        "still endpoints of a run of their own net, 37 printed rows all >= 2 units "
        "from every conductor, 0 crossings, no diagonal, and the ten rail flags keep "
        "their nets and rotations. The rest of the digest's increment is **rigid "
        "translation**: `primary`'s offset is unchanged, the other four blocks are "
        "packed elsewhere because two of them grew by the bend — which is why "
        "`page.offsets`/`page.bbox()` move here for the first time in this file's "
        "history (530G holds those numbers); island-normalised, `primary` and "
        "`secondary` are unchanged and `feedback`/`bridge`/`control` differ only in "
        "those carriers' labels and segments"
    )


def test_a_net_that_comes_apart_in_one_island_is_named_once_per_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S-14 at the grain where 520l and 530D disagree.

    Every route is refused (`_route` answers ``None``, which is `DESIGN` §4's
    criterion 3 — 「断线打名」), so every link is cut and each net's pins become
    blobs of their own.  What must happen then is that the drawing names **each**
    blob: `secondary`'s `SEC_12V` (three pins, a chain of two links) becomes three
    flag sites instead of one, and the island's name count follows the blob count
    exactly.

    A drawing that named the net once would leave two of those three blobs with no
    name at all — the shape S-14 refuses, and the shape a reader cannot resolve.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    before = _names_and_blobs(page, circuit, presentation, book)
    assert before == (22, 22)

    monkeypatch.setattr(il, "_route", lambda *args, **kwargs: None)
    cut = il.island_page(circuit, presentation, book)
    names, blobs = _names_and_blobs(cut, circuit, presentation, book)
    assert names - blobs == 0, (names, blobs)
    assert blobs > before[1], "the refusal cut nothing, so this measures nothing"

    secondary = next(
        block for block in cut.blocks if block.island_id == "secondary"
    )
    sec_12v = [item.net for item in secondary.power_symbols if item.net == "SEC_12V"]
    assert len(sec_12v) == 3, [item.net for item in secondary.power_symbols]
    notes = " ".join(secondary.notes)
    assert "cut apart" in notes or "not drawn" in notes, secondary.notes


def _two_runs(second) -> tuple[il.IslandNet, dict, list]:
    """One net, one horizontal run, and a second run placed by the caller."""
    pins = {
        il.IslandPin("U1", "1"): (0.0, 0.0),
        il.IslandPin("U1", "2"): (100.0, 0.0),
        il.IslandPin("U1", "3"): second[1],
    }
    segments = [
        il.LayoutSegment(net="NET", points=[(0.0, 0.0), (100.0, 0.0)]),
        il.LayoutSegment(net="NET", points=list(second)),
    ]
    net = il.IslandNet(net_id="NET", pins=tuple(pins))
    return net, pins, segments


def test_two_runs_that_meet_at_a_tee_are_one_blob() -> None:
    """The junction rule: a vertex landing **in** another run's span joins them.

    Hand-built, and it is the reading the editor itself makes — it draws the dot
    there and the two wires are one node (`_junction_dots` declares the same point).
    So S-14 sees **one** blob and gives it one name; a reading that took them apart
    would put two names on one node, which is the "says it twice" S-14 refuses.
    """
    net, tips, segments = _two_runs([(50.0, 0.0), (50.0, 60.0)])
    components = il._net_components(net, tips, segments)
    assert len(components) == 1, [pins for pins, _points in components]
    assert sorted(str(pin) for pin in components[0][0]) == ["U1.1", "U1.2", "U1.3"]


def test_two_runs_that_only_cross_are_two_blobs() -> None:
    """A crossing is not a node: the editor joins nothing, so S-14 sees two.

    The same picture with the vertical run moved so it cuts the horizontal one
    **between** vertices rather than ending on it.  Nothing to draw a dot at, so
    the two runs are two conductors — which is also why `_true_crossing` counts
    this as a crossing and a tee as `landing`.
    """
    net, tips, segments = _two_runs([(50.0, -30.0), (50.0, 30.0)])
    components = il._net_components(net, tips, segments)
    assert len(components) == 2, [pins for pins, _points in components]


def test_a_blob_that_already_carries_a_name_is_not_named_again() -> None:
    """「一坨里已有旗标的不再重复挂标签」 — the guard, read on the drawing itself.

    A name is known to belong to a blob through the **stub that starts on it**: the
    name stands at the stub's far end, so the blob a name belongs to is the one the
    stub's other end is in.  Points, not pins, because two blobs of one net share
    no point — which is exactly what makes the question answerable.
    """
    block = il.IslandBlock(
        island_id="one", role="", anchor="U1", ring_radius=10.0, order=["U1"],
    )
    here = (0.0, 0.0)
    other = (100.0, 100.0)
    block.segments.append(il.LayoutSegment(net="NET", points=[here, (0.0, 30.0)]))
    block.labels.append(il.LayoutLabel(
        net="NET", text="NET", bbox=(0.0, 30.0, 20.0, 40.0), x=0.0, y=30.0,
        part_id="U1",
    ))
    assert il._component_is_named(block, "NET", [here, (0.0, 30.0)])
    assert not il._component_is_named(block, "NET", [other])
    assert not il._component_is_named(block, "OTHER", [here, (0.0, 30.0)])


# ------------------------------- B. a wire carries a name only as a label


def _island_change_plan():
    """The real flyback island page as the **landing** sees it (530D's subject)."""
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    layout = page.plan(source=LayoutSource(
        circuit_sha256=circuit.sha256(), presentation_sha256=presentation.sha256(),
    ))
    lcsc = {
        part.id: (part.params.get("lcsc", "") or "C1") for part in circuit.parts
    }
    return drawapply.module_plan(
        layout, circuit, presentation, book, lcsc_by_part=lcsc,
    ), layout


def test_the_landing_names_a_wire_only_where_the_wire_is_the_label() -> None:
    """Ruling A on the real page, per wire: 12 named wires out of 39.

    The 12 are the boundary labels' own stubs and nothing else.  Every conductor —
    a flagged rail's, an island-internal net's — is landed with its ``net`` set on
    the **plan** and no name passed to ``sch.place_wire``, which is what the host
    needs to stop printing a blue row at the middle of it.
    """
    plan, layout = _island_change_plan()
    named = [wire for wire in plan.change.draw_wires if drawapply.wire_carries_its_name(wire)]
    assert len(plan.change.draw_wires) == 39
    assert len(named) == 12, [(wire.net, wire.purpose) for wire in named]
    assert {wire.net for wire in named} == set(drawapply.label_wire_nets(plan))
    assert {wire.net for wire in named} == {
        label.net for label in layout.labels
    } - {symbol.net for symbol in layout.power_symbols}
    # The conductors still *know* their net — the plan is where the drawing says
    # what belongs to what; only the name it hands the host is withheld.
    assert len(drawapply.unnamed_nets(plan)) == 10
    for wire in plan.change.draw_wires:
        if not drawapply.wire_carries_its_name(wire) and wire.net:
            assert wire.net in drawapply.unnamed_nets(plan)


def test_the_landing_and_the_gate_read_the_same_statement() -> None:
    """The batch's 「同源」 clause, both directions, on the real page.

    The landing marks its wires by ``core.layoutplan.label_wire_indices`` — one
    statement, read by the half that writes the page and by the half that judges it
    (`readability._named_wire_rows`).  They must not drift: a gate that models a row
    nobody prints reports a page that is not on the canvas, and a landing that names
    a wire the gate does not model prints a row nobody is judging.
    """
    plan, layout = _island_change_plan()
    carries = label_wire_indices(layout)
    assert len(carries) == 12
    landed = {
        index for index, wire in enumerate(plan.change.draw_wires)
        if drawapply.wire_carries_its_name(wire)
    }
    assert landed == set(carries), (sorted(landed), sorted(carries))
    rows = rb._named_wire_rows(layout)
    assert {row[3] for row in rows} == {
        layout.segments[index].net for index in carries
    }


def test_the_page_the_gate_reads_has_only_the_transformer_s_own_pin_text() -> None:
    """The gate reading: 530C's 8 → 1 → 0 (531) → **3, and all three are `T1`'s own**.

    530C measured 8 hard violations, all of them rows the host prints over wires that
    are not the name; ruling A removed them, because those wires no longer carry a
    name. The one that was left was the `LED_K` label's own row landing on `R7`, and
    it was reported rather than written off (the stub ladder had no candidate that
    cleared it). **531 removed it by moving `R7` instead**: the placement now measures
    the rows the host prints a part's designator and value in
    (`core.textmetrics.symbol_rows`) and gives them a row pitch that fits, so the
    label's own row has somewhere to be. The page was refused in this test's own
    batch; 531 left it clean.

    **532's reading is three rows, and the sentence is different.** The gate can now
    see a placed part's **pin name and number** (`textmetrics.pin_rows`), and on this
    document the only hard rows left are the transformer's own typography printed
    over its own value row — the class 530C's `text-overlap`-only vocabulary had no
    name for. They are delivered with, named one line each (`drawcompiler.
    island_gate_violations`); what this test still owns is that the row count is
    exactly these three and that none of 530C's own findings came back.

    **201H reads zero, and the sentence behind it is S-21's own.** Both rows ride one
    symbol, so no placement can separate them; the value row is therefore hidden
    (`islandlayout._clear_text_rows`'s own-pin half) and the three `pin-text-press`
    rows go with it. The class is still detected — `test_532` states that on the plan
    that prints the row — and the delivery policy's cap did not move. What this test
    owns now is that the page is clean **without** 530C's findings coming back.
    """
    _plan, layout = _island_change_plan()
    circuit, presentation, book = _flyback()
    _page = il.island_page(circuit, presentation, book)
    checked = rb.check(layout, circuit, presentation, book)
    kinds = {item.kind for item in checked.hard_violations}
    assert kinds == set(), [item.render() for item in checked.hard_violations]
    assert checked.hard_violations == []
    refusing, tolerated = dc.island_gate_violations(checked.hard_violations)
    assert not refusing and not tolerated
    assert not [
        item for item in checked.hard_violations if "CLAMP" in item.render()
    ], "an island-internal net's row is still being modelled"


# ---------------------------------- C. the connectivity reading, both halves


def _names_for(plan) -> dict[tuple[str, str], str]:
    """A live netlist for this plan: the named nets by name, the rest by auto name.

    The editor's own behaviour: a net the page states a name for comes back under
    that name; a net it states none for comes back under an auto name of the
    editor's own choosing (`NET1…`), one per geometric cluster.
    """
    stated = drawapply.named_wire_nets(plan) | {
        item.net for item in plan.change.draw_flags if item.net
    }
    names = drawapply.planned_net_names(plan)
    out: dict[tuple[str, str], str] = {}
    auto = 0
    seen: dict[tuple[str, ...], str] = {}
    for island in plan.change.islands:
        key = tuple(sorted(island.mates))
        if key not in seen:
            net = next((names[pin] for pin in key if names.get(pin)), "")
            if net in stated:
                seen[key] = net
            else:
                auto += 1
                seen[key] = f"NET{auto}"
        designator, _sep, number = island.pin.partition(".")
        out[(designator, number)] = seen[key]
    return out


def test_the_live_mapping_says_how_each_net_was_read() -> None:
    """The mapping itself, written out — the deliverable of the re-verification.

    Three things a reader of `draw apply`'s report has to be able to see: the spec
    net, the name the plan states for it (or ``""`` when it states none), the name
    the editor holds its pins under, and whether that reading was **by name** (a flag
    or a label anchors it) or **by partition** (the editor's own auto name).
    """
    plan, _layout = _island_change_plan()
    live = _names_for(plan)
    rows = {tuple(row["wanted"]): row for row in drawapply.live_partitions(plan, live)}
    assert len(rows) == 16, len(rows)
    labelled = next(row for row in rows.values() if row["net"] == "SW")
    assert labelled["anchored"] and labelled["live"] == "SW"
    assert labelled["liveNames"] == ["SW"]
    # A flagged net is anchored too — by the flag, which is what names it.
    rail = next(
        row for row in rows.values()
        if row["net"] == "PGND" and len(row["pins"]) == 5
    )
    assert rail["anchored"] and rail["live"] == "PGND"
    # An island-internal net states no name and is read by its partition alone.
    internal = next(row for row in rows.values() if row["net"] == "CLAMP")
    assert not internal["anchored"] and internal["live"].startswith("NET")
    assert set(internal["partition"]) == set(internal["pins"])
    assert drawapply._live_problems(plan, live) == []


def test_one_spec_net_drawn_as_two_partitions_is_refused() -> None:
    """「一条 spec 网被画成两个分区」— a conductor (or a name) that did not land."""
    plan, _layout = _island_change_plan()
    live = _names_for(plan)
    split = next(pin for pin in live if live[pin] == "SW")
    live[split] = "NET9"
    problems = drawapply._live_problems(plan, live)
    assert problems and "drawn as 2 partitions" in problems[0], problems


def test_two_spec_nets_drawn_as_one_partition_is_refused() -> None:
    """「两条 spec 网并成一个分区」— a short, read as a short.

    The two internal nets are the ones the editor holds under its own auto names,
    which is what makes the case worth having: a merge between two **unnamed** nets
    has no name to be caught by, so it is the partition reading that has to see it —
    and it sees it from both sides.
    """
    plan, _layout = _island_change_plan()
    live = _names_for(plan)
    spec = {
        (pin.partition(".")[0], pin.partition(".")[2]): net
        for pin, net in drawapply.planned_net_names(plan).items()
    }
    anchored = drawapply.named_wire_nets(plan) | {
        item.net for item in plan.change.draw_flags if item.net
    }
    internal = sorted({
        name for name in spec.values() if name and name not in anchored
    })
    victim = next(pin for pin in live if spec.get(pin) == internal[0])
    mate = next(pin for pin in live if spec.get(pin) == internal[1])
    live[victim] = live[mate]
    problems = drawapply._live_problems(plan, live)
    assert problems, "two spec nets on one live net went unnoticed"
    # Read from both sides: the victim net now has a pin the editor keeps apart
    # ("drawn as 2 partitions"), and the thief's net has a pin it never had.
    assert any("drawn as 2 partitions" in item for item in problems), problems
    assert any(
        "among this plan's pins" in item and ".".join(victim) in item
        for item in problems
    ), problems


def test_a_named_net_under_the_editors_own_auto_name_is_refused() -> None:
    """The half that only ruling A makes necessary: a name that did not land.

    The partition can be perfect and the drawing still wrong — a signal net whose
    label vanished keeps its pins together by geometry, so the membership reading
    says nothing.  Read **by name** where the page states one, exactly the two nets
    here that are anchored by a label: the flag-anchored rails are read at the flag
    (`_flag_problems`, 163b) and the island-internal nets by their partition.
    """
    plan, _layout = _island_change_plan()
    live = _names_for(plan)
    for index, net in enumerate(sorted(drawapply.named_wire_nets(plan))):
        for pin in live:
            if live[pin] == net:
                live[pin] = f"NET{index + 90}"
    problems = drawapply._live_problems(plan, live)
    assert problems, "a label that did not land went unnoticed"
    assert all("the plan states this net's name" in item for item in problems), problems
    named = {
        item.split("name as '")[1].split("'")[0] for item in problems
    }
    assert named == set(drawapply.named_wire_nets(plan)), (named, problems)

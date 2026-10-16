"""bug98-B: the schematic's footprint field holding a **library id**.

Task 151 recorded the observation without fixing it (its own docstring said so):
sixteen placements across ``tests/fixtures`` carry a raw 16-hex library id where
the schematic's declared footprint should be, because the DEVICE library left
``Supplier Footprint`` blank and the instance's own ``Footprint`` attribute —
which stores the *library footprint uuid* — was used as the fallback. The
``pcb-footprint-consistency`` rule could only say 「无从比较」 about those
sixteen.

This batch **resolves them at the model layer**, and the resolution is a lookup,
not a guess: the same archive carries the ``FOOTPRINT`` document that uuid names,
with the footprint's name in its ``META.title``. Measured 2026-10-12 on the
fixtures:

======================  ====================  ==================================
fixture                 references            id -> resolved name
======================  ====================  ==================================
``llc_board.epro2``     C1 C2 C5 C6           ``0733d61b8033ac9c`` ->
                                              ``CAP-SMD_L8.0-W6.0-LS11.4``
``FPC触屏游戏机``        L1                    ``1ffe775752db4b94`` ->
                                              ``IND-SMD_L5.0-W5.0``
``FPC触屏游戏机``        LCD1                  ``ece2497609c798b8`` ->
                                              ``2.4INCH LCD ILI9341 18PIN``
``级联多电平-主拓扑``     C1 C2 C6 C7 C8 C9     ``fd83adcd075d2633`` ->
                        C12 C13               ``CAP-SMD_L8.0-W6.0-LS11.4``
``级联多电平-主拓扑``     U1 U2                 ``819a5d95a71fc1bb`` ->
                                              ``级联H桥驱动``
======================  ====================  ==================================

The flip is one-way and enumerated: 「无从比较」 → 「一致」 on 14 of the 16, and
the remaining two (``级联``'s ``U1``/``U2``) stay 「无从比较」 because the resolved
name carries no comparable token on either side — the verdict is unchanged
there, only the sentence is now about two names instead of a hex string. **No
verdict anywhere gains severity: the rule's comparison logic is untouched.**
"""

from __future__ import annotations

from pathlib import Path

from boardwise.core.geometry import BoardGeometry, ComponentPlacement, PadGeometry
from boardwise.core.model import Component, DesignModel, Pin
from boardwise.engines.pcbreview import run_pcb_review
from boardwise.parsers.schematic import (
    FOOTPRINT_ID_RE,
    _collect_footprint_titles,
    _resolve_declared_footprint,
    build_project_model,
)
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.footprint import LIBRARY_ID_RE, FootprintConsistency

FIXTURES = Path(__file__).parent / "fixtures"
LLC = FIXTURES / "llc_board.epro2"
FPC = FIXTURES / "FPC触屏游戏机_2026-09-27.epro2"
CASCADE = FIXTURES / "级联多电平-主拓扑_2026-09-27.epro2"

RULE_ID = "pcb-footprint-consistency"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rows(path: Path) -> list:
    """The footprint rule's own findings for one fixture, via the real runner."""
    model = build_project_model(path)
    findings, _section = run_pcb_review(
        path, model=model, rules=[FootprintConsistency()]
    )
    return findings


def _summary(rows: list) -> str:
    return [row.message for row in rows if "封装对账" in row.message][0]


def _ctx(board, pcb_model, sch_model) -> PcbReviewContext:
    return PcbReviewContext(
        board=board, board_title="SYNTH", model=sch_model, pcb_model=pcb_model
    )


def _pcb(designator: str, title: str, pins: int) -> tuple[BoardGeometry, DesignModel]:
    pads = [
        PadGeometry(
            id=f"{designator}.{index}", component=designator, pin_number=str(index),
            net="", footprint_layer_id=1, x=0.0, y=0.0, local_x=0.0, local_y=0.0,
            width=30.0, height=30.0, shape="RECT", angle=0.0,
        )
        for index in range(1, pins + 1)
    ]
    board = BoardGeometry(
        source="synthetic", name="SYNTH",
        components=[ComponentPlacement(id="c-1", designator=designator, x=0.0, y=0.0, layer_id=1)],
        pads=pads,
    )
    pcb_model = DesignModel(components={
        designator: Component(
            uid="u-1", designator=designator, footprint=title,
            props={"Footprint": "fp-1"},
        )
    })
    return board, pcb_model


def _sch(designator: str, footprint: str, pins: int, props: dict | None = None) -> DesignModel:
    component = Component(
        uid="s-1", designator=designator, footprint=footprint,
        pins=[Pin(number=str(i + 1), name="", net=None) for i in range(pins)],
    )
    if props:
        component.props.update(props)
    return DesignModel(components={designator: component})


# ---------------------------------------------------------------------------
# the in-archive table, and the shape it keys on
# ---------------------------------------------------------------------------


def test_the_two_id_shape_readers_agree():
    """The parser's and the rule's regexes are one vocabulary, pinned together.

    They are separate objects because ``parsers`` and ``rules`` may each only
    import ``core`` (``tests/test_layer_rules.py``); a drift between them is
    silent in both directions, so the corpus is explicit.
    """
    corpus = [
        "0733d61b8033ac9c",
        "308cffdb9f930ec1_c4dc0f6ef1616584702a893414cd16c7",
        "c4dc0f6ef1616584702a893414cd16c7",
        "CAP-SMD_L8.0-W6.0-LS11.4",
        "0603",
        "",
        "0733d61b8033ac9",
        "0733d61b8033ac9cz",
        "IND-SMD_L5.0-W5.0",
    ]
    for sample in corpus:
        assert bool(FOOTPRINT_ID_RE.match(sample)) == bool(LIBRARY_ID_RE.match(sample)), sample


def test_the_archive_carries_the_id_to_name_table_the_fallback_reads():
    """``_collect_footprint_titles`` reads FOOTPRINT documents' META titles.

    ``_iter_schematic_records`` drops those documents by design, so this is a
    second, page-blind pass over the same decoded stream — and it is the whole
    mapping: nothing is invented for an id the file does not name.
    """
    from boardwise.parsers.epru_stream import load_epru_text

    text, _meta = load_epru_text(LLC)
    titles = _collect_footprint_titles(text)
    assert titles["0733d61b8033ac9c"] == "CAP-SMD_L8.0-W6.0-LS11.4"
    # The table is keyed by FOOTPRINT uuid only: a SYMBOL/DEVICE uuid that this
    # file also carries must not appear.
    assert "be00e56953045bd1" not in titles
    assert all(isinstance(value, str) for value in titles.values())


def test_resolve_declared_footprint_only_fires_on_a_hit():
    """A name, an empty field and an unmapped id all come back unresolvable."""
    titles = {"0733d61b8033ac9c": "CAP-SMD_L8.0-W6.0-LS11.4"}
    assert _resolve_declared_footprint("0603", titles) == ("0603", "")
    assert _resolve_declared_footprint("  ", titles) == ("", "")
    assert _resolve_declared_footprint("0733d61b8033ac9c", titles) == (
        "CAP-SMD_L8.0-W6.0-LS11.4", "0733d61b8033ac9c",
    )
    # An id the file does not name stays an id: "not resolvable" must not be
    # readable as "resolved to nothing".
    assert _resolve_declared_footprint("deadbeefdeadbeef", titles) == (
        "deadbeefdeadbeef", "",
    )


# ---------------------------------------------------------------------------
# the model-layer fallback
# ---------------------------------------------------------------------------


def test_llc_declares_the_resolved_name_and_keeps_the_raw_id():
    """C1/C2/C5/C6: the field becomes the name, the id survives on the props."""
    model = build_project_model(LLC)
    assert model.components["C1"].footprint == "CAP-SMD_L8.0-W6.0-LS11.4"
    props = model.components["C1"].props
    assert props["footprint_library_id"] == "0733d61b8033ac9c"
    assert "footprint=library-id" in props["identity_provenance"]
    for designator in ("C1", "C2", "C5", "C6"):
        component = model.components[designator]
        assert component.footprint == "CAP-SMD_L8.0-W6.0-LS11.4"
        assert component.props["footprint_library_id"] == "0733d61b8033ac9c"


def test_a_resolved_name_is_not_the_pcb_documents_uuid_by_construction():
    """The resolution is a lookup, not the PCB side echoed back.

    ``级联多电平-主拓扑``'s ``U1``/``U2`` are the standing proof: the schematic's
    ``Footprint`` attribute names ``819a5d95a71fc1bb`` while the PCB placement
    names a *different* footprint document — and the two still share the title
    the fallback reads, so the resolution is not two spellings of one lookup.

    The doc-claim on ``_collect_footprint_titles`` ("14 of the 16 to the very
    document the PCB side names, 2 to a different one that shares the title") is
    counted here rather than asserted in prose: this is the whole population of
    library-id footprints in ``tests/fixtures``.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source

    text_model = build_project_model(CASCADE)
    assert text_model.components["U1"].footprint == "级联H桥驱动"
    assert text_model.components["U1"].props["footprint_library_id"] == "819a5d95a71fc1bb"

    source = load_epro2_source(CASCADE)
    pcb_model = build_design_model(source)
    assert pcb_model.components["U1"].props["Footprint"] != "819a5d95a71fc1bb"
    assert pcb_model.components["U1"].footprint == "级联H桥驱动"

    same = different = 0
    for path in (LLC, FPC, CASCADE):
        schematic = build_project_model(path)
        pcb = build_design_model(load_epro2_source(path))
        for designator, component in schematic.components.items():
            identifier = component.props.get("footprint_library_id")
            if not identifier:
                continue
            if pcb.components[designator].props["Footprint"] == identifier:
                same += 1
            else:
                different += 1
    assert (same, different) == (14, 2)


# ---------------------------------------------------------------------------
# the enumerated flip, fixture by fixture
# ---------------------------------------------------------------------------


def test_llc_four_id_pairs_become_comparable_and_no_severity_appears():
    """The 151 finding's four rows are gone; the numbers move 13/30 -> 17/26."""
    rows = _rows(LLC)
    assert [row for row in rows if "库件 id" in row.message] == []
    summary = _summary(rows)
    assert "一致 17" in summary
    assert "无从比较 26" in summary
    assert "尺寸码不符 0" in summary and "封装族不符 0" in summary
    assert "焊盘数不符 0" in summary
    assert [row.severity for row in rows if row.severity == "ERROR"] == []


def test_fpc_two_id_pairs_become_comparable():
    """L1 and LCD1: 一致 48 -> 50, 无从比较 6 -> 4, ERROR unchanged."""
    rows = _rows(FPC)
    assert [row for row in rows if "库件 id" in row.message] == []
    summary = _summary(rows)
    assert "一致 50" in summary
    assert "无从比较 4" in summary
    assert "尺寸码不符 1" in summary  # the board's own, unrelated to this batch
    assert len([row for row in rows if row.severity == "ERROR"]) == 1


def test_cascade_ten_id_pairs_move_and_the_two_titleless_ones_stay_undecidable():
    """The 8 caps agree; ``U1``/``U2`` resolve to a name with no token to compare.

    That pair's verdict is **unchanged** (「无从比较」, INFO): the rule's
    comparison logic is deliberately untouched by this batch, and a name like
    ``级联H桥驱动`` carries no size code, no package family and no dimension
    number — so the two strings being equal is not a token the current
    discipline reads. It is recorded here rather than quietly smoothed over.
    """
    rows = _rows(CASCADE)
    assert [row for row in rows if "库件 id" in row.message] == []
    summary = _summary(rows)
    assert "一致 18" in summary
    assert "无从比较 39" in summary
    undecidable = {
        row.target.component_ref: row.message
        for row in rows if row.target and "无从比较" in row.message
    }
    assert {"U1", "U2"} <= set(undecidable)
    for designator in ("U1", "U2"):
        assert "'级联H桥驱动'" in undecidable[designator]  # both sides, as names
        assert "hex" not in undecidable[designator].lower()


def test_the_hard_rows_are_untouched_by_this_batch():
    """Zero-flip, stated as the thing that matters: ERROR/WARN rows are unmoved.

    Measured before the model-layer fallback and after it, the three fixtures'
    non-INFO rows are identical — llc's pre-existing same-name-two-geometries
    WARN, FPC's ``U4`` size-code ERROR and 级联's ``U3`` presence ERROR are each
    there for their own reason, none of which is a library id. Only INFO rows
    moved; that is what 「无从比较」 翻正 means here, and it is why the batch
    cannot turn a clean board into a defect.
    """
    def hard(path: Path) -> list[tuple[str, str | None]]:
        return sorted(
            (
                row.severity,
                row.target.component_ref if row.target is not None else None,
            )
            for row in _rows(path)
            if row.severity != "INFO"
        )

    assert hard(LLC) == [("WARN", None)]
    assert hard(FPC) == [("ERROR", "U4")]
    assert hard(CASCADE) == [("ERROR", "U3"), ("WARN", None)]


# ---------------------------------------------------------------------------
# the residual capability boundary (the rule's own statement)
# ---------------------------------------------------------------------------


def test_an_id_the_archive_does_not_name_is_reported_as_an_unmapped_id():
    """No document behind the id → 「无从比较」, and the reason says so."""
    board, pcb_model = _pcb("C1", "C0603", 2)
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, _sch("C1", "deadbeefdeadbeef", 2))
    )
    infos = [row for row in findings if row.target is not None]
    assert len(infos) == 1
    assert "无从比较" in infos[0].message
    assert "id 无档内映射" in infos[0].message
    assert "lib.footprint.get" in infos[0].message


def test_the_rule_names_the_reverse_lookup_in_the_evidence_when_it_fired():
    """A resolved pair compares normally, and the evidence says where the name came from."""
    board, pcb_model = _pcb("C1", "C0805", 2)
    sch = _sch("C1", "0805", 2, props={"footprint_library_id": "deadbeefdeadbeef"})
    # 0805 against C0805 agrees, so no per-part row is printed at all — the
    # resolution did not manufacture a finding. The evidence line is read off a
    # real mismatch instead: same props, a land pattern of the other size.
    assert [
        row for row in FootprintConsistency().check(_ctx(board, pcb_model, sch))
        if row.target is not None
    ] == []
    board, pcb_model = _pcb("C1", "C0603", 2)
    errors = [
        row for row in FootprintConsistency().check(_ctx(board, pcb_model, sch))
        if row.severity == "ERROR"
    ]
    assert len(errors) == 1
    assert any("library id 'deadbeefdeadbeef'" in line for line in errors[0].evidence)
    assert any("footprint_library_id" in line for line in errors[0].evidence)


def test_a_name_that_was_not_resolved_from_an_id_carries_no_such_evidence():
    """No id, no line: the evidence must not claim a lookup that never ran."""
    board, pcb_model = _pcb("C1", "C0603", 2)
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, _sch("C1", "0805", 2))
    )
    errors = [row for row in findings if row.severity == "ERROR"]
    assert errors
    assert not any("library id" in line for line in errors[0].evidence)

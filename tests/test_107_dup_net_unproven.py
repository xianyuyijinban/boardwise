"""107: a net whose member list a dropped placement truncated is an **unproven** net.

105 (B4b) made net membership follow the placement the model keeps — the first
copy of a repeated designator, which 049 measured the copper layer agreeing with
— so a second placement of the same name claims no membership. That fixed the
impossible netlist state (one pin on four nets at once), and it left a knowledge
gap behind:

    the DCDC fixture, measured before this batch
      ('100NF','1') was welded into GND, NET1, VCC and VCCA

The dropped copies of ``100NF`` really are drawn on the sheet and really do reach
``VCC`` — the rail the board needs a decoupling capacitor on. 105 therefore gave
``decap-required-caps`` a **true** WARN (``U10 pin5: no grounded capacitor found
on net 'VCC'``), true of the netlist and not true of the board: the part that
would satisfy the requirement may be one the model threw away. 岳's ruling
(2026-10-03) is that a conclusion on such a net is not a confident WARN but an
UNKNOWN that says what we do not know.

So this batch does two things and nothing else:

1. **the fact** — the parser already knows the net name each dropped placement's
   pins read (it is that placement's own cluster), so the guard that skips the
   member writes the name into ``DesignModel.unproven_nets``, the same channel
   the per-page merge uses to refuse (issue #19), carrying its own reason in
   ``unproven_reasons``;
2. **the consumption** — ``rules/unproven.py``'s refusal builders say *that*
   reason instead of the merge's, so every rule that already refuses on an
   unproven net refuses here too, in the same UNKNOWN.

What this file pins:

* the DCDC row, verbatim, before (WARN) and after (UNKNOWN with a missing fact
  that names the duplicate designator and the truncation);
* the two repeat shapes (same page / across pages), each with its own reason;
* that the merge's refusal — B4a's #11 and 076's wording — is **unchanged** for a
  model that carries no reason, and that the safety metadata still survives
  ``reconcile_names`` with the new field riding along (104's defect, four fields
  now);
* and that the 19 boards with no repeated designator file no such fact at all, so
  nothing about them can move.

Every digest and board list below was measured on the pre-107 tree
(``.tmp_107_before``, ``outputs/107/probe_before.json``) or on the delivered
tree, and is quoted in ``outputs/107/SUMMARY.txt``.
"""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

import pytest

from boardwise.core.compare import reconcile_names
from boardwise.core.model import (
    Component,
    DesignModel,
    Net,
    Pin,
)
from boardwise.core.parts import load_parts
from boardwise.engines.review_eval import load_board_model
from boardwise.parsers.schematic import build_schematic_model
from boardwise.rules.connectivity import DuplicateDesignators
from boardwise.rules.decap import DecapRequiredCaps
from boardwise.rules.facts import LdoDropout
from boardwise.rules.unproven import (
    NET_MEMBERSHIP_RULES,
    UNPROVEN_BY_NAME,
    unproven_message,
    unproven_missing_fact,
    unproven_nets,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]
DCDC = FIXTURES / "DCDC-12V9V转5V3V3_2026-09-27.epro2"
LIBRARY = load_parts(str(REPO / "blocklib" / "parts.json"))

#: The DCDC board's one page, quoted rather than re-derived: the reason sentence a
#: reader sees names it, so a test that rebuilt it would agree with a wrong page.
DCDC_PAGE = "339fa01ce62547e0b5badb21a762ec00"

#: ``boardwise.core.model``'s reason codes, written out rather than imported: a
#: test that read a constant back out of the code under test would agree with any
#: spelling of it, and this is a wire other tools read.
WELDED = "welded-by-name"
TRUNCATED = "truncated-by-duplicate-designator"
TRUNCATED_CROSS_PAGE = "truncated-by-cross-page-designator"


# --------------------------------------------------------------------------
# 1. the row this batch exists for
# --------------------------------------------------------------------------


def _dcdc_board() -> DesignModel:
    return load_board_model(str(DCDC)).boards[0]


def _decap_row(board: DesignModel, subject: str):
    for row in DecapRequiredCaps(library=LIBRARY)._rows(board):
        if row[0].subject == subject:
            return row[0], row[1]
    raise AssertionError(f"no decap row for {subject}")


def test_the_dcdc_decap_row_is_unknown_and_says_the_membership_may_be_truncated():
    """105's WARN, word for word, now with the reason it is not a verdict.

    Before this batch the row was ``VIOLATION``/``WARN`` — "no grounded capacitor
    found on net 'VCC' (required 1uF)" — which is true of the netlist and not of
    the board. Both the wording and the level are pinned, because the ruling was
    about this row and not about the mechanism.
    """
    outcome, severity = _decap_row(_dcdc_board(), "U10 pin5")

    assert (outcome.state, severity) == ("UNKNOWN", None)
    assert outcome.message == (
        "U10 pin5: net 'VCC' may have members missing from it (the 2nd and later "
        "placements of '100NF' (4 placements on page '339fa01ce62547e0b5badb21a762ec00') "
        "and '10UF' (2 placements on page '339fa01ce62547e0b5badb21a762ec00') are not in "
        "this netlist), so whether a grounded capacitor of the required value '1uF' sits "
        "on it cannot be established — a placement the model did not keep may be the part "
        "this judgement needs"
    ), outcome.message
    assert outcome.missing_fact == (
        "a netlist in which no placement was left out — this net's membership may be "
        "truncated by a duplicate designator: the 2nd and later placements of '100NF' "
        "(4 placements on page '339fa01ce62547e0b5badb21a762ec00') and '10UF' "
        "(2 placements on page '339fa01ce62547e0b5badb21a762ec00') are not in this netlist"
    ), outcome.missing_fact
    # The evidence the row had before is still its evidence — only the conclusion moved.
    assert outcome.evidence == ["U10 pin5 @ VCC"]
    # …and the sentence says the two things a reader has to be told: 位号重复 and
    # 成员可能截断.
    assert "duplicate designator" in outcome.missing_fact
    assert "membership may be truncated" in outcome.missing_fact


def test_the_duplicate_designator_error_still_fires_verbatim():
    """The clash itself is a finding of its own and is not this batch's to soften.

    ``conn-duplicate-designators`` reads ``duplicate_designators``, not the
    netlist, so both ERROR rows must read exactly as they did before.
    """
    board = _dcdc_board()
    rows = [(row[0].subject, row[1]) for row in DuplicateDesignators()._rows(board)]
    assert rows == [("100NF", "ERROR"), ("10UF", "ERROR")]
    messages = [row[0].message for row in DuplicateDesignators()._rows(board)]
    assert messages == [
        "100NF is used by more than one placed part on one page; "
        "the model kept the first placement",
        "10UF is used by more than one placed part on one page; "
        "the model kept the first placement",
    ], messages


def test_the_refusal_is_not_one_rule_s_privilege():
    """The second rule that reaches ``VCC`` on this board, as a control.

    ``path-ldo-dropout`` prices U10's headroom between ``+5V`` and ``VCC``, and
    the ``VCC`` voltage is inferred from the parts sitting on ``VCC`` — so it
    reads the same truncated member list and owes the same refusal. Before this
    batch it reported a confident OK (1700 mV >= 400 mV).
    """
    board = _dcdc_board()
    row = next(r for r in LdoDropout(library=LIBRARY)._rows(board)
               if r[0].subject == "U10")

    assert (row[0].state, row[1]) == ("UNKNOWN", None)
    assert "net 'VCC' may have members missing from it" in row[0].message
    assert "may be truncated by a duplicate designator" in row[0].missing_fact
    # The rule it belongs to is on the declared list, which is what the report's
    # "N rules refuse" counts.
    assert row[0].rule_id in NET_MEMBERSHIP_RULES


# --------------------------------------------------------------------------
# 2. the fact the parser now records
# --------------------------------------------------------------------------


def test_every_net_a_dropped_placement_would_have_joined_is_listed_as_unproven():
    """The five nets of the DCDC board, and the eight that stay proven.

    ``GND``/``NET1``/``NET2``/``VCC``/``VCCA`` are where the three dropped copies
    of ``100NF`` and the one dropped copy of ``10UF`` reach; the rest of the board
    was untouched by the clash, and a net nothing was dropped from must not be
    marked — a fact that spread one net too far would refuse verdicts the drawing
    does support.
    """
    board = _dcdc_board()

    assert sorted(board.unproven_nets) == ["GND", "NET1", "NET2", "VCC", "VCCA"]
    assert sorted(board.nets) == [
        "+12V", "+5V", "GND", "NET1", "NET10", "NET2", "NET5", "NET6",
        "NET7", "NET8", "NET9", "VCC", "VCCA",
    ]
    for name in ("+12V", "+5V", "NET5", "NET10"):
        assert board.unproven_pages(name) is None, name


def test_the_reason_names_the_placements_that_were_left_out():
    """``(code, sentence)`` per net — the code is what a consumer branches on."""
    board = _dcdc_board()
    code, detail = board.unproven_reason("VCC")

    assert code == TRUNCATED
    assert detail == (
        "the 2nd and later placements of '100NF' "
        "(4 placements on page '339fa01ce62547e0b5badb21a762ec00') and '10UF' "
        "(2 placements on page '339fa01ce62547e0b5badb21a762ec00') are not in this netlist"
    )
    # A net that is not unproven has no reason at all, and reads as the merge's
    # gap — the pre-107 answer — rather than inventing one.
    assert board.unproven_reason("+5V") == (WELDED, "")


def test_the_pages_of_a_truncated_net_are_the_pages_the_dropped_placement_sits_on():
    """``unproven_pages`` keeps answering, and it is not the multi-page answer.

    The value's meaning is "where was this name seen", and for a truncation that
    is where the drawing put the part — one page here. What makes the net
    unproven is the reason, not the page count, which is exactly why the model
    carries the two separately.
    """
    board = _dcdc_board()
    assert board.unproven_pages("VCC") == (DCDC_PAGE,)
    assert board.unproven_pages("GND") == (DCDC_PAGE,)


# --------------------------------------------------------------------------
# 3. the two repeat shapes, synthesised (the same fixtures 105 used)
# --------------------------------------------------------------------------


def _record(type_: str, body: dict | None = None, id_: str | None = None) -> str:
    envelope: dict = {"type": type_, "ticket": 1}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _symbol() -> list[str]:
    """A two-pin part drawn at the origin: pin 1 at (0,0), pin 2 at (20,0)."""
    out = [
        _record("DOCHEAD", {"docType": "SYMBOL", "uuid": "sym-r", "editVersion": "3.2.149"}),
        _record("META", {"title": "R", "docType": "SYMBOL"}, id_="meta-r"),
    ]
    for index, number in enumerate(("1", "2")):
        pin_id = f"sym-r-pin{number}"
        out.append(_record("PIN", {"x": float(index * 20), "y": 0.0, "zIndex": index + 2},
                           id_=pin_id))
        out.append(_record("ATTR", {"parentId": pin_id, "key": "Pin Number", "value": number},
                           id_=f"{pin_id}-n"))
    return out


def _page(uuid: str, parts: list[tuple[str, float, str]]) -> list[str]:
    """One ``SCH_PAGE``: each ``(designator, x, net name)`` gets its own wire."""
    lines = [
        _record("DOCHEAD", {"docType": "SCH_PAGE", "uuid": uuid}),
        _record("CANVAS", {"originX": 0, "originY": 0, "unit": "0.01inch"},
                id_=f"canvas-{uuid}"),
    ]
    for index, (designator, x, net_name) in enumerate(parts):
        part = f"inst-{uuid}-{index}"
        lines.append(_record("COMPONENT", {"partId": part, "x": x, "y": -300.0,
                                           "rotation": 0, "isMirror": False, "zIndex": 10},
                             id_=f"c-{part}"))
        lines.append(_record("ATTR", {"parentId": part, "key": "Designator",
                                      "value": designator}, id_=f"d-{part}"))
        lines.append(_record("ATTR", {"parentId": part, "key": "Symbol",
                                      "value": "sym-r"}, id_=f"s-{part}"))
        group = f"grp-{uuid}-{index}"
        lines.append(_record("WIRE", {"zIndex": 40}, id_=group))
        lines.append(_record("LINE", {"lineGroup": group, "startX": x, "startY": -300.0,
                                      "endX": x + 20.0, "endY": -300.0}))
        lines.append(_record("ATTR", {"parentId": group, "key": "NET", "value": net_name},
                             id_=f"net-{uuid}-{index}"))
    return lines


def _synthetic(tmp_path: Path, name: str, pages: list[list[str]]) -> Path:
    lines: list[str] = []
    for page in pages:
        lines += page
    lines += _symbol()
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("synth.epru", "\n".join(lines) + "\n")
        archive.writestr("project2.json", json.dumps({"title": "synthetic"}))
    return path


def test_two_parts_under_one_name_on_one_page_mark_both_nets_with_that_reason(tmp_path):
    """Same page: two physical parts answer to ``R1`` inside one netlist.

    ``R1`` is kept on ``NA`` and its second copy is on ``NB``, so ``NB`` is a net
    the drawing drew and this netlist could not describe — the case 105 created
    and 107 says out loud.
    """
    path = _synthetic(tmp_path, "same_page.epro2", [
        _page("page-1", [("R1", 300.0, "NA"), ("R1", 700.0, "NB")]),
    ])
    board = build_schematic_model(path)
    board = getattr(board, "boards", None)[0] if getattr(board, "boards", None) else board

    assert board.duplicate_designators == ["R1"]
    assert sorted(board.unproven_nets) == ["NB"], (
        "only the net the dropped copy would have joined is in question — the kept "
        "placement's own net NA is fully described"
    )
    assert board.unproven_reason("NB") == (
        TRUNCATED,
        "the 2nd and later placement of 'R1' (2 placements on page 'page-1') "
        "are not in this netlist",
    )


def test_one_part_on_each_of_two_pages_marks_both_nets_with_the_cross_page_reason(tmp_path):
    """Across pages of one board: one design drawn on two sheets (040b's kind).

    Same refusal, different fact — and the reason says which, because a reader
    who is told "duplicate designator" and is looking at two sheets of one design
    has been told the wrong thing about their drawing.
    """
    path = _synthetic(tmp_path, "cross_page.epro2", [
        _page("page-1", [("R1", 300.0, "NA")]),
        _page("page-2", [("R1", 700.0, "NB")]),
    ])
    board = build_schematic_model(path)
    board = getattr(board, "boards", None)[0] if getattr(board, "boards", None) else board

    assert board.cross_page_designators == {"R1": ["page-1", "page-2"]}
    assert sorted(board.unproven_nets) == ["NB"]
    assert board.unproven_reason("NB") == (
        TRUNCATED_CROSS_PAGE,
        "the 2nd and later placement of 'R1' (one placement on each of pages "
        "'page-1', 'page-2') are not in this netlist",
    )
    assert board.unproven_pages("NB") == ("page-1", "page-2")


def test_a_page_with_no_repeated_designator_files_no_fact_at_all(tmp_path):
    """The zero-movement nail, in miniature: one part on one page names one net."""
    path = _synthetic(tmp_path, "clean.epro2", [
        _page("page-1", [("R1", 300.0, "NA"), ("R2", 700.0, "NB")]),
    ])
    board = build_schematic_model(path)
    board = getattr(board, "boards", None)[0] if getattr(board, "boards", None) else board

    assert board.duplicate_designators == []
    assert board.cross_page_designators == {}
    assert board.unproven_nets == {}
    assert board.unproven_reasons == {}


# --------------------------------------------------------------------------
# 4. the merge's refusal is untouched (issue #19 / 076 / B4a #11)
# --------------------------------------------------------------------------


def _welded_model() -> DesignModel:
    """One net the per-page merge welded, in the pre-107 shape: no reason."""
    model = DesignModel(
        components={"C1": Component(uid="u1", designator="C1", value="1uF")},
        nets={"VCC": Net(name="VCC", pins=[("C1", "1")])},
    )
    model.components["C1"].pins = [Pin(number="1", name="1", net="VCC"),
                                  Pin(number="2", name="2", net="GND")]
    model.unproven_nets = {"VCC": ("page-a", "page-b")}
    return model


def test_a_welded_model_still_refuses_with_the_merge_own_sentence():
    """The wording issue #19 measured, unchanged: a name with no reason is the
    merge's gap, and it says ``agreement by name is not a verified connection``."""
    found = unproven_nets(_welded_model(), ("VCC",))

    assert found == [("VCC", ("page-a", "page-b"))]
    assert unproven_missing_fact(found) == (
        "a verified connection for net 'VCC' was seen on 2 pages of this reading "
        "(page-a, page-b) — this tier cannot attribute a page to a board: "
        f"{UNPROVEN_BY_NAME}"
    )
    assert unproven_message("U1 pin3", found, what="whether a capacitor sits on it") == (
        "U1 pin3: net 'VCC' was seen on 2 pages of this reading (page-a, page-b), "
        "so whether a capacitor sits on it cannot be established — whether those "
        "pages are one board is not in this reading"
    )


def test_a_refusal_still_unpacks_as_the_two_element_tuple_every_caller_reads():
    """Thirty call sites do ``for net, pages in found``; a third element would be
    a silent change to all of them, so the reason rides as an attribute."""
    found = unproven_nets(_welded_model(), ("VCC",))
    (net, pages), = found
    assert (net, pages) == ("VCC", ("page-a", "page-b"))
    assert found[0].truncated is False

    truncated = unproven_nets(
        DesignModel(unproven_nets={"VCC": ("p",)}, unproven_reasons={
            "VCC": (TRUNCATED, "the 2nd and later placement of 'C1'"),
        }),
        ("VCC",),
    )
    assert truncated == [("VCC", ("p",))]
    assert truncated[0].truncated is True


def test_the_safety_fields_and_the_new_reason_survive_a_reconcile():
    """104's #11, one field wider.

    ``reconcile_names`` rebuilds the model from components and nets, so a safety
    field left at its default reads as "there is no gap here" and every refusal
    downstream turns back into a verdict. Four fields now, not three.
    """
    golden = DesignModel(nets={"VCC": Net(name="VCC", pins=[("C1", "1")])})
    candidate = copy.deepcopy(golden)
    candidate.duplicate_designators = ["C1"]
    candidate.cross_page_designators = {"R1": ["page-1", "page-2"]}
    candidate.unproven_nets = {"VCC": ("page-a", "page-b")}
    candidate.unproven_reasons = {
        "VCC": (TRUNCATED,
                "the 2nd and later placement of 'C1' (2 placements on page 'x') "
                "are not in this netlist"),
    }

    out = reconcile_names(candidate, golden)

    assert out.duplicate_designators == ["C1"]
    assert out.cross_page_designators == {"R1": ["page-1", "page-2"]}
    assert out.unproven_nets == {"VCC": ("page-a", "page-b")}
    assert out.unproven_reasons == candidate.unproven_reasons
    assert out.unproven_reason("VCC") == candidate.unproven_reasons["VCC"]
    assert out.unproven_pages("N1") is None
    # The refusal a rule builds from the reconciled model is the refusal the
    # candidate would have produced — the point of #11.
    assert unproven_missing_fact(unproven_nets(out, ("VCC",))) == (
        "a netlist in which no placement was left out — this net's membership may be "
        "truncated by a duplicate designator: the 2nd and later placement of 'C1' "
        "(2 placements on page 'x') are not in this netlist"
    )
    # Copies, not aliases: mutating the result cannot reach the input.
    out.unproven_reasons["VCC"] = (WELDED, "")
    assert candidate.unproven_reasons["VCC"][0] == TRUNCATED


# --------------------------------------------------------------------------
# 5. zero movement, board by board
# --------------------------------------------------------------------------


def _loaded_boards():
    """``(file key, board title, board model)`` for every board in the repository."""
    files = (
        sorted((REPO / "tests" / "fixtures").glob("*.epro2"))
        + sorted((REPO / "tests" / "fixtures").glob("*.enet"))
        + sorted((REPO / "reviewsets").rglob("*.epro2"))
    )
    for path in files:
        key = path.relative_to(REPO).as_posix()
        model = load_board_model(str(path))
        for board in (getattr(model, "boards", None) or [model]):
            title = getattr(getattr(board, "board", None), "title", "") or "<no board>"
            yield key, title, board


def test_no_board_without_a_repeated_designator_files_a_truncation_fact():
    """The untouched boards: the guard that files the fact cannot fire on them.

    Not "their verdicts happen to be the same" — the **input** to every refusal
    is empty on all of them, so no rule on them can read a truncation whatever it
    concludes.

    The count moved 19 -> 20 on 2026-10-07: 岳 supplied the **1.0.0 export** of
    the 毕设FOC board (``ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2``), which
    joined the corpus. Its Board1 *does* repeat designators (9 nets), so it is
    not one of the untouched boards — but it was not there when this number was
    first measured, and a fixture arriving is exactly the kind of event this pin
    exists to surface. The number is a **corpus** fact, not a behaviour claim,
    so it is updated here with the reason recorded rather than loosened.
    """
    checked = 0
    for key, title, board in _loaded_boards():
        if board.duplicate_designators or board.cross_page_designators:
            continue
        assert board.unproven_nets == {}, f"{key} [{title}]"
        assert board.unproven_reasons == {}, f"{key} [{title}]"
        checked += 1
    assert checked == 20, f"the untouched set is 20 boards, {checked} were checked"


#: Which boards file the fact, and which nets — measured on the delivered tree
#: (``outputs/107/probe_after.json``). Five files, 24 boards: the two that repeat
#: are DCDC, 毕设FOC's Board1, 高速电机控制器's 控制板, 毕设滤波采样 and the
#: injected review set, which repeats ``R24`` across pages.
#:
#: **Six entries since 2026-10-07**: 岳's **1.0.0 export** of the 毕设FOC board
#: (``ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2``) has ``Board1: 9``. It is a
#: separate project from the 1.1.0 export already listed, not a rename of it —
#: the two files have different sizes and different contents, and the 1.0.0
#: board's ``U6`` is the ``TPLP2981-30DBVR`` LDO where the 1.1.0 one's is a 2x6
#: 排针 (127b's evidence that the审查对象 was wrong, not the parser).
REPEATED_BOARDS = {
    "DCDC-12V9V转5V3V3_2026-09-27.epro2": {"Board1": 5},
    "ProPrj_毕设FOC驱动板_2026-09-17.epro2": {"Board1": 10},
    "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2": {"Board1": 9},
    "ProPrj_高速电机控制器_2026-09-16.epro2": {"控制板": 17},
    "毕设滤波采样_2026-09-27.epro2": {"Board1": 15},
    "duplicate-designator.epro2": {"Board1": 2},
}


def test_only_the_five_repeated_boards_file_a_fact_and_the_counts_are_pinned():
    """The declared surface, named — so a sixth board appearing is a test failure."""
    found: dict[str, dict[str, int]] = {}
    for key, title, board in _loaded_boards():
        if board.unproven_reasons:
            found.setdefault(Path(key).name, {})[title] = len(board.unproven_reasons)

    assert found == REPEATED_BOARDS, found


@pytest.mark.parametrize("name,titles", sorted(REPEATED_BOARDS.items()))
def test_every_net_the_fact_names_is_a_net_the_board_draws(name, titles):
    """A name that is not in ``model.nets`` would refuse a net nobody drew."""
    boards = {
        title: board
        for key, title, board in _loaded_boards()
        if Path(key).name == name
    }
    for title in titles:
        board = boards[title]
        assert board.unproven_reasons, f"{name} [{title}]"
        for net in board.unproven_reasons:
            assert net in board.nets, f"{name} [{title}]: {net!r} is not in the netlist"
            assert net != "", f"{name} [{title}]"
"""189A2: a mirrored quarter-turn placement, its pins, and the two views.

The reported defect: reading the **schematic** view of an ``.epro2`` gave four
obsolete parts (a rectifier bridge, a TRIAC, a common-mode choke, a connector)
with **every connected pin on its own one-member net** (``NET13``/``NET14``/…),
while the same archive's PCB view (``PAD_NET``) had them wired up. Twelve
phantom "dangling" rows, and one of them grew a phantom power rail out of the
report. Nothing was wrong with the schematic document: the parser was reading
it through the wrong rigid transform.

The parser lands a pin's tip on the page with
:func:`boardwise.core.geometry.transform_point` and resolves pin-to-net by
matching that tip against a wire endpoint (040). That function applied the
mirror **before** the rotation — ``CCW(t) ∘ M`` — and the file means
``M ∘ CCW(t)``. The two agree at 0° and 180° and differ at 90°/270°, which is
why nothing in this repository ever caught it: every mirrored placement in
``tests/fixtures`` sits at 0° or 180°, and no fixture carries the pose that can
tell them apart. The reported board did, and the drawing itself said which
order it meant — twelve mirrored 90° placements land **14/16** of their pins
exactly on a wire endpoint under mirror-last and **4/16** under mirror-first
(and the four are coincidences: a mirrored 90° pose maps a symbol's own ±y onto
±x, which happens to put two pins of a seven-pin connector on two wire ends).

What this file holds, on synthesised boards only:

* the shape itself — a three-pin symbol placed at 90° with ``isMirror``, and the
  net **each** pin lands on (mirror-first swaps/relocates them, so the net names
  are the assertion);
* the transform law it exposed, written out arithmetically, including the pair
  of angles no fixture can distinguish;
* the other half of the pair: ``draw.editor_pose`` tells the editor how to pose
  the part, and the editor's own measured composition (``mirror_x ∘ CW(R)``,
  054) has to land it where the file's transform says it is — the same
  invariant from the writing side;
* the cross-view consistency check (part two of the task book): a pin the
  schematic view leaves alone on a net the PCB view says has company is
  disclosed, in the section and on the report's note line — so the next reader
  hears about it instead of finding it by cross-checking by hand.
"""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

import pytest

from boardwise.core.geometry import transform_point
from boardwise.core.model import BoardModel, BoardRef, Component, DesignModel, Net, Pin, ProjectModel
from boardwise.engines.draw import editor_pose
from boardwise.engines.pcbreview import (
    CROSS_VIEW_MIN_PINS,
    cross_view_lonely_pins,
    cross_view_section,
    schematic_board_for,
)
from boardwise.parsers.schematic import build_project_model

# --------------------------------------------------------------------------
# synthesised streams
# --------------------------------------------------------------------------


def _record(type_: str, body: dict | None = None, id_: str | None = None) -> str:
    envelope: dict = {"type": type_, "ticket": 1}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _symbol(uuid: str, title: str, pins: list[tuple[str, float, float]]) -> list[str]:
    """One ``SYMBOL`` document. ``pins`` are ``(number, x, y)`` in **canvas** space.

    The stream stores y negated (010c), so the writer negates it once here — the
    same single negation ``parsers.schematic._page_y`` undoes on the way back in.
    """
    out = [
        _record("DOCHEAD", {"docType": "SYMBOL", "uuid": uuid, "editVersion": "3.2.186"}),
        _record("META", {"title": title, "docType": "SYMBOL"}, id_=f"meta-{uuid}"),
    ]
    for index, (number, x, y) in enumerate(pins):
        pin_id = f"{uuid}-pin{number}"
        out.append(_record("PIN", {"x": x, "y": -y, "zIndex": index + 1}, id_=pin_id))
        out.append(_record(
            "ATTR", {"parentId": pin_id, "key": "Pin Number", "value": number},
            id_=f"{pin_id}-n",
        ))
    return out


def _component(
    *, part_id: str, designator: str, symbol: str, x: float, y: float,
    rotation: float, mirror: bool, z_index: int,
) -> list[str]:
    """One placed part, in **canvas** coordinates (y negated on the way out)."""
    return [
        _record("COMPONENT", {
            "partId": part_id, "x": x, "y": -y, "rotation": rotation,
            "isMirror": mirror, "zIndex": z_index,
        }, id_=f"c-{part_id}"),
        _record("ATTR", {"parentId": part_id, "key": "Designator", "value": designator},
                id_=f"d-{part_id}"),
        _record("ATTR", {"parentId": part_id, "key": "Symbol", "value": symbol},
                id_=f"s-{part_id}"),
        _record("ATTR", {"parentId": part_id, "key": "Device", "value": f"dev-{symbol}"},
                id_=f"v-{part_id}"),
    ]


def _wire(group: str, points: list[tuple[float, float]], net: str = "") -> list[str]:
    """A ``WIRE`` head plus the ``LINE`` pieces through ``points`` (canvas space)."""
    out = [_record("WIRE", {"zIndex": 40}, id_=group)]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        out.append(_record("LINE", {
            "lineGroup": group, "startX": x0, "startY": -y0,
            "endX": x1, "endY": -y1,
        }, id_=f"{group}-{x0}-{y0}"))
    if net:
        out.append(_record("ATTR", {"parentId": group, "key": "NET", "value": net},
                           id_=f"net-{group}"))
    return out


#: The three-pin symbol used throughout: a one-sided part, so a quarter turn
#: and a mirror move its pins in two independent directions.
MUX_PINS = [("1", -20.0, 10.0), ("2", -20.0, 0.0), ("3", -20.0, -10.0)]


def _board_stream() -> list[str]:
    """The measured shape, drawn out: a 3-pin part mirrored at 90°, wired.

    ``U9`` sits at canvas (100, 100) with ``rotation=90, isMirror=true``. Its
    pins therefore belong at canvas (110, 80) / (100, 80) / (90, 80) — the
    positions this board's wires start from — and ``R9``'s pin 1 joins the first
    of them, so the net the artifact turned into a one-member island has a
    second member to lose.
    """
    lines: list[str] = []
    lines += _symbol("sym-mux3", "MUX3", MUX_PINS)
    lines += _symbol("sym-r2", "R2K", [("1", 0.0, 0.0), ("2", 10.0, 0.0)])
    lines.append(_record("DOCHEAD", {"docType": "SCH_PAGE", "uuid": "page-1"}))
    lines += _component(
        part_id="inst-u9", designator="U9", symbol="sym-mux3",
        x=100.0, y=100.0, rotation=90.0, mirror=True, z_index=1,
    )
    lines += _component(
        part_id="inst-r9", designator="R9", symbol="sym-r2",
        x=160.0, y=50.0, rotation=0.0, mirror=False, z_index=2,
    )
    lines += _wire("g-alpha", [(110.0, 80.0), (110.0, 50.0), (160.0, 50.0)], net="ALPHA")
    lines += _wire("g-beta", [(100.0, 80.0), (100.0, 50.0)], net="BETA")
    lines += _wire("g-gamma", [(90.0, 80.0), (90.0, 50.0)], net="GAMMA")
    lines += _wire("g-tail", [(170.0, 50.0), (170.0, 20.0)], net="TAIL")
    return lines


def _backup(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("synth.epru", "\n".join(lines) + "\n")
        archive.writestr("project2.json", json.dumps({"title": "synthetic"}))
    return path


@pytest.fixture(scope="module")
def mirrored_board(tmp_path_factory) -> BoardModel:
    path = _backup(tmp_path_factory.mktemp("189a2"), "mirrored.epro2", _board_stream())
    project = build_project_model(path)
    assert len(project.boards) == 1
    return project.boards[0]


# --------------------------------------------------------------------------
# 1. the shape: a mirrored quarter turn puts each pin on its own wire
# --------------------------------------------------------------------------


def test_a_mirrored_part_is_posed_rotation_first_then_mirror(mirrored_board):
    """The three pins of the 90°/mirrored part, on the page the drawing says.

    Mirror-first puts them at (90, 120) / (100, 120) / (110, 120) — the other
    half of the pose, 180° away about the part's own origin, where this board
    has no wire at all. So this assertion is the whole defect in one line: the
    nets below can only come out as they do under the measured order.
    """
    component = mirrored_board.components["U9"]
    assert [(pin.number, pin.net) for pin in component.pins] == [
        ("1", "ALPHA"), ("2", "BETA"), ("3", "GAMMA"),
    ]


def test_a_multi_pad_part_is_not_a_single_member_island(mirrored_board):
    """The reported shape, negated: the net the part shares with another part.

    Before the fix every pin of such a part read as its own one-member net —
    ``nets["ALPHA"].pins`` would have been ``[("R9", "1")]``, and the part's own
    pin would not be on it at all.
    """
    assert sorted(mirrored_board.nets["ALPHA"].pins) == [("R9", "1"), ("U9", "1")]
    for name in ("BETA", "GAMMA"):
        assert [member for member in mirrored_board.nets[name].pins
                if member[0] == "U9"], (
            f"{name} must carry U9's own pin; a one-member {name} is the artifact"
        )
    # BETA / GAMMA / TAIL are the three wires this board draws to carry exactly
    # one pin each — deliberately alone. Anything else alone, an auto ``NETn``
    # above all, is the artifact: a U9 pin the parser failed to land on a wire.
    lonely = sorted(
        name for name, net in mirrored_board.nets.items() if len(net.pins) == 1
    )
    assert lonely == ["BETA", "GAMMA", "TAIL"]


def test_the_two_pin_part_still_lands_on_its_own_wires(mirrored_board):
    """The control: an unmirrored placement is untouched by the fix."""
    assert [(pin.number, pin.net) for pin in mirrored_board.components["R9"].pins] == [
        ("1", "ALPHA"), ("2", "TAIL"),
    ]


# --------------------------------------------------------------------------
# 2. the transform law, written out
# --------------------------------------------------------------------------


def _ccw(rotation: float, x: float, y: float) -> tuple[float, float]:
    rad = math.radians(rotation)
    return (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))


def _mirror_x(point: tuple[float, float]) -> tuple[float, float]:
    return (-point[0], point[1])


def test_the_mirror_flips_the_posed_point_not_the_local_one():
    """``M ∘ CCW(t)``, for every angle and both mirror values, over signed points."""
    for rotation in (0.0, 30.0, 90.0, 180.0, 270.0, 315.0):
        for mirror in (False, True):
            for (x, y) in ((-20.0, 10.0), (7.0, -3.0), (0.0, 0.0), (-40.0, 0.0)):
                posed = _ccw(rotation, x, y)
                if mirror:
                    posed = _mirror_x(posed)
                assert transform_point(
                    x, y, rotation=rotation, mirror=mirror, ox=100.0, oy=100.0
                ) == pytest.approx((posed[0] + 100.0, posed[1] + 100.0), abs=1e-6), (
                    f"rotation={rotation} mirror={mirror} point=({x}, {y})"
                )


def test_only_a_quarter_turn_can_tell_the_two_orders_apart():
    """Why no fixture caught it: 0/180 hide the order, 90/270 do not.

    The measured board's mirrored parts all sit at 0° or 180°, where
    ``M ∘ CCW(t)`` and ``CCW(t) ∘ M`` are the same matrix. This pins both halves
    of that statement so a future reader cannot "simplify" the order away.
    """
    point = (-20.0, 10.0)  # the top-left pin of the three-pin symbol
    for rotation in (0.0, 180.0):
        mirror_first = _ccw(rotation, *_mirror_x(point))
        mirror_last = _mirror_x(_ccw(rotation, *point))
        assert mirror_first == pytest.approx(mirror_last)
        assert transform_point(
            *point, rotation=rotation, mirror=True, ox=0.0, oy=0.0
        ) == pytest.approx(mirror_last, abs=1e-6)

    assert transform_point(
        *point, rotation=90.0, mirror=True, ox=0.0, oy=0.0
    ) == (10.0, -20.0)
    assert _ccw(90.0, *_mirror_x(point)) == pytest.approx((-10.0, 20.0)), (
        "mirroring first puts the same pin 180° away from where the drawing has it"
    )


# --------------------------------------------------------------------------
# 3. the other half of the pair: what we hand the editor
# --------------------------------------------------------------------------


def _editor_api_point(
    x: float, y: float, *, rotation: float, mirror: bool, ox: float, oy: float
) -> tuple[float, float]:
    """The editor's own composition, as 054 measured it: ``mirror_x ∘ CW(R)``.

    Written out from the measurement (``outputs/054_c1/08_mirror_probe.json``:
    all eight ``(R, mirror)`` pairs, pins read back with ``sch.component_pins``),
    not from this repository's code — that is the point of the test below.
    """
    rad = math.radians(rotation)
    posed = (x * math.cos(rad) + y * math.sin(rad), -x * math.sin(rad) + y * math.cos(rad))
    if mirror:
        posed = _mirror_x(posed)
    return (posed[0] + ox, posed[1] + oy)


def test_the_editor_is_asked_for_the_pose_the_file_means():
    """``editor_pose`` + the measured API = ``transform_point``. Both halves, one ruler.

    054 reconciled the two by handing a mirrored pose its angle **unchanged**,
    because ``transform_point`` used to compute the other order. With the order
    measured (189A2) the compensation moves with it: the angle is the negation
    in both cases, and the editor lands the part where the file says it is.
    Asked ``rotation=90, mirror=true`` with the angle unchanged, the API lands a
    mirrored quarter turn at (0, 20) where the file means (-10, -20) — the
    failure this test exists to catch.
    """
    for rotation in (0.0, 90.0, 180.0, 270.0):
        for mirror in (False, True):
            asked_rotation, asked_mirror = editor_pose(rotation, mirror)
            assert asked_mirror is mirror, "the mirror flag is passed through"
            for (x, y) in ((-20.0, 10.0), (30.0, -12.0)):
                assert _editor_api_point(
                    x, y, rotation=asked_rotation, mirror=asked_mirror,
                    ox=100.0, oy=100.0,
                ) == pytest.approx(
                    transform_point(
                        x, y, rotation=rotation, mirror=mirror, ox=100.0, oy=100.0
                    ),
                    abs=1e-9,
                ), f"rotation={rotation} mirror={mirror}"


# --------------------------------------------------------------------------
# 4. the cross-view consistency check (task book part two)
# --------------------------------------------------------------------------


def _model(pins: dict[str, list[tuple[str, str | None]]]) -> DesignModel:
    """A tiny model: ``{designator: [(pin number, net), …]}``, nets rebuilt from it."""
    model = DesignModel()
    for designator, rows in pins.items():
        component = Component(uid=designator.lower(), designator=designator)
        for number, net in rows:
            component.pins.append(Pin(number=number, name=number, net=net))
        model.components[designator] = component
    for designator, rows in pins.items():
        for number, net in rows:
            if net:
                model.nets.setdefault(net, Net(name=net)).pins.append((designator, number))
    return model


def test_a_pin_the_schematic_leaves_alone_is_named_with_both_readings():
    """The artifact's own shape: schematic says one member, the board says more."""
    schematic = _model({"U9": [("1", "NET7"), ("2", "BETA"), ("3", "GAMMA")]})
    pcb = _model({"U9": [("1", "ALPHA"), ("2", "BETA"), ("3", "GAMMA")],
                  "R9": [("1", "ALPHA"), ("2", None)]})
    rows = cross_view_lonely_pins(schematic, pcb)
    assert rows == [{
        "designator": "U9",
        "pin": "1",
        "schematicNet": "NET7",
        "schematicMembers": 1,
        "pcbNet": "ALPHA",
        "pcbMembers": 2,
    }]


def test_the_rows_read_in_pin_number_order_not_string_order():
    """``U1.2`` before ``U1.10``: the note prints the first six rows, so order shows."""
    schematic = _model({"U1": [("2", "NET7"), ("10", "NET8"), ("9", "NET9")]})
    pcb = _model({"U1": [("2", "ALPHA"), ("10", "BETA"), ("9", "GAMMA")],
                  "R9": [("1", "ALPHA"), ("2", "BETA"), ("3", "GAMMA")]})
    assert [row["pin"] for row in cross_view_lonely_pins(schematic, pcb)] == [
        "2", "9", "10",
    ]


def test_two_views_that_agree_report_nothing():
    """An empty list is a reading — and the only one that may be read as agreement."""
    left = _model({"U9": [("1", "ALPHA"), ("2", "BETA"), ("3", "GAMMA")],
                   "R9": [("1", "ALPHA")]})
    right = _model({"U9": [("1", "ALPHA"), ("2", "BETA"), ("3", "GAMMA")],
                    "R9": [("1", "ALPHA")]})
    assert cross_view_lonely_pins(left, right) == []


def test_a_two_pin_part_is_out_of_the_checks_scope():
    """「多焊盘器件」 is the floor: a 2-pin part alone on a net is not this question.

    It is a ``min_pins`` reading, not an accident of the data — the same models
    do report the row once the floor is lowered.
    """
    schematic = _model({"R9": [("1", "NET7"), ("2", None)]})
    pcb = _model({"R9": [("1", "ALPHA"), ("2", None)], "U9": [("1", "ALPHA")]})
    assert cross_view_lonely_pins(schematic, pcb) == []
    assert len(cross_view_lonely_pins(schematic, pcb, min_pins=2)) == 1


def test_a_pin_missing_from_the_schematic_view_is_not_a_lonely_pin():
    """A pin the schematic model does not carry has its own channels (020's drops)."""
    schematic = _model({"U9": [("2", "BETA"), ("3", "GAMMA")]})
    pcb = _model({"U9": [("1", "ALPHA"), ("2", "BETA"), ("3", "GAMMA")],
                  "R9": [("1", "ALPHA")]})
    assert cross_view_lonely_pins(schematic, pcb) == []


def test_a_net_the_schematic_admits_is_short_is_not_a_difference():
    """107: a name in ``unproven_nets`` may not be concluded about, either way.

    The net is one member because a dropped placement was not written into it —
    «the schematic leaves this pin alone» would read that gap as a finding. The
    row is dropped instead, and the gap keeps its own disclosure.
    """
    schematic = _model({"U9": [("1", "NET7"), ("2", "BETA"), ("3", "GAMMA")]})
    pcb = _model({"U9": [("1", "ALPHA"), ("2", "BETA"), ("3", "GAMMA")],
                  "R9": [("1", "ALPHA")]})
    assert len(cross_view_lonely_pins(schematic, pcb)) == 1

    schematic.unproven_nets["NET7"] = ()
    assert cross_view_lonely_pins(schematic, pcb) == []


def test_the_check_never_calls_a_part_it_could_not_pair_an_agreement():
    """「没配对」 and 「对上了」 are two statements; only one of them is a reading."""
    unchecked = cross_view_section(None, _model({"U9": [("1", "ALPHA")]}))
    assert unchecked["checked"] is False
    assert "未查" in unchecked["reason"] and "不是一致" in unchecked["reason"]
    assert "lonely" not in unchecked

    no_netlist = cross_view_section(_model({"U9": [("1", None)]}), None)
    assert no_netlist["checked"] is False and no_netlist["reason"]

    checked = cross_view_section(
        _model({"U9": [("1", "ALPHA")]}), _model({"U9": [("1", "ALPHA")]})
    )
    assert checked == {"checked": True, "minPins": CROSS_VIEW_MIN_PINS, "lonely": []}


def test_a_check_that_chokes_is_named_and_leaves_the_pcb_section_alone():
    """The third ``checked: false``: an exception is disclosed, not propagated.

    This reading sits beside the PCB rules, and the runner's contract is that a
    broken check never takes the section down — so the failure has to arrive as
    a *reason* naming itself, never as a section that quietly lost its rules.
    """
    class Exploding:
        components: dict = {}

        @property
        def nets(self):
            raise RuntimeError("model went sideways")

    section = cross_view_section(Exploding(), _model({"U9": [("1", "ALPHA")]}))
    assert section["checked"] is False
    assert "RuntimeError" in section["reason"] and "model went sideways" in section["reason"]
    assert "没查，不是一致" in section["reason"]
    assert "lonely" not in section


def test_the_schematic_board_is_found_by_its_document_link():
    """154's link, and ``None`` — never a guess — when it does not resolve."""
    one = BoardModel(board=BoardRef(uuid="board-1", title="Board1"))
    two = BoardModel(board=BoardRef(uuid="board-2", title="Board2"))
    project = ProjectModel(boards=[one, two])
    assert schematic_board_for(project, "board-2") is two
    assert schematic_board_for(project, "board-9") is None
    # one board, no link to match on: that board is the only candidate
    assert schematic_board_for(project, "") is None  # two boards, no link: no guess
    assert schematic_board_for(BoardModel(board=BoardRef(uuid="board-1")), "") is not None
    assert schematic_board_for(
        BoardModel(board=BoardRef(uuid="board-1")), "board-2"
    ) is None
    assert schematic_board_for(None, "board-1") is None


def test_the_cross_view_check_runs_inside_the_pcb_review_section():
    """The wiring, on a real fixture: the key is there and it was really checked."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "llc_board.epro2"
    from boardwise.engines.pcbreview import run_pcb_review

    model = build_project_model(fixture)
    _findings, section = run_pcb_review(fixture, model=model)
    assert section is not None
    (entry,) = section["boards"]
    assert entry["crossView"]["checked"] is True
    assert entry["crossView"]["minPins"] == CROSS_VIEW_MIN_PINS
    assert entry["crossView"]["lonely"] == []
    # ... and the models it compared are the two views of that same document
    assert schematic_board_for(model, entry["boardUuid"]) is model.boards[0]


# --------------------------------------------------------------------------
# 5. what a person reads
# --------------------------------------------------------------------------


def test_the_report_note_names_the_pins_and_picks_no_side():
    from boardwise.cli import _note_cross_view_lonely

    notes: list[str] = []
    _note_cross_view_lonely(notes, {"boards": [{
        "title": "Board1",
        "crossView": {"checked": True, "minPins": 3, "lonely": [
            {"designator": "U9", "pin": "1", "schematicNet": "NET7",
             "schematicMembers": 1, "pcbNet": "ALPHA", "pcbMembers": 2},
            {"designator": "U9", "pin": "3", "schematicNet": "NET9",
             "schematicMembers": 1, "pcbNet": "GAMMA", "pcbMembers": 4},
        ]},
    }]})
    assert len(notes) == 1
    note = notes[0]
    assert "U9.1" in note and "U9.3" in note
    assert "PAD_NET" in note and "crossView.lonely" in note
    assert "都不是天然权威" in note, (
        "the note says the two views differ; it may not sentence either one"
    )


def test_a_board_with_nothing_to_disclose_adds_no_note():
    from boardwise.cli import _note_cross_view_lonely

    notes: list[str] = []
    for section in (None, {"boards": []}, {"boards": [
        {"title": "Board1", "crossView": {"checked": True, "minPins": 3, "lonely": []}},
        {"title": "Board2", "crossView": {"checked": False, "reason": "x"}},
    ]}):
        _note_cross_view_lonely(notes, section)
    assert notes == []

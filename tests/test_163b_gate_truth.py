"""163b: eight places where a gate answered something it had not checked.

The batch's contract is in `tasks/161-hole-triage.md` (P1–P5, D3, D4, plus the
`status_summary` split 157 left registered). Each section below is one entry, and
each one is written as the **probe the triage asked for**: the smallest offline
configuration in which the old code was silent (or lied) and the new one reports.

Nothing here touches a daemon or the bridge: every seam is a fake object or a
plain geometry dump, because a gate's honesty has to be testable on the desk the
gate was written on.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.bridge import daemon as daemon_module
from boardwise.core.changeplan import (
    ChangePlan,
    PlanChange,
    PlanDrawFlag,
    PlanDrawWire,
    PlanIsland,
    PlanMove,
    PlanSource,
    PlanWireOp,
    move_block_plan,
)
from boardwise.engines import addcomponent, checkup, drawapply, drawlint, moveblock
from boardwise.engines import patchpin

# ---------------------------------------------------------------------------
# shared: a `sch.geometry` dump and a `sch.netlist`-shaped live reading
# ---------------------------------------------------------------------------


def _page(*, parts=(), wires=(), netflags=()) -> dict:
    """A `sch.geometry` dump in the measured shape (036/037's helper's shape)."""
    return {
        "components": [
            {"primitiveId": primitive,
             "state": {"ComponentType": "part", "Designator": designator,
                       "X": x, "Y": y, "Rotation": rotation, "Mirror": False}}
            for designator, primitive, x, y, rotation in parts
        ] + [
            {"primitiveId": f"flag-{index}",
             "state": {"ComponentType": "netflag", "Designator": None, "Net": net,
                       "X": x, "Y": y, "Rotation": 0}}
            for index, (net, x, y) in enumerate(netflags)
        ] + [
            {"primitiveId": "sheet-1",
             "state": {"ComponentType": "sheet", "Designator": "", "X": 0, "Y": 0}},
        ],
        "wires": [
            {"primitiveId": primitive,
             "state": {"Line": [c for point in points for c in point], "Net": net}}
            for primitive, net, points in wires
        ],
        "netlabels": [],
        "pins": [],
        "meta": {"available": {"components": True, "wires": True}},
    }


# ===========================================================================
# P1 — `draw lint --page` must confirm the focus it depends on, and put it back
# ===========================================================================

class _FakeEditor:
    """A `BridgeClient` that behaves like an editor about `doc.open`.

    ``honours`` is the whole point: the real host may refuse to move (a locked
    page, a stale uuid, another window's document), and `sch.geometry` reads
    whatever is focused (pit 44) — so a lint that does not re-read the focus
    reports the wrong page under the right name.
    """

    payload: dict = {}
    honours = True
    focus = ""
    calls: list[tuple[str, dict]] = []

    @classmethod
    def reset(cls, *, payload: dict, honours: bool = True, focus: str = ""):
        cls.payload = dict(payload)
        cls.honours = honours
        cls.focus = focus
        cls.calls = []

    @classmethod
    async def open(cls, uri, token, role, client=""):
        assert role == "cli"
        return cls()

    async def call(self, action, params=None, **kwargs):
        type(self).calls.append((action, dict(params or {})))
        payload = type(self).payload
        if action == "doc.open":
            wanted = str((params or {}).get("uuid") or "")
            if type(self).honours:
                type(self).focus = wanted
            return {"tabId": wanted, "matchesRequest": type(self).honours}
        if action == "doc.list":
            listing = payload.get("doc.list")
            answer = dict(listing) if isinstance(listing, dict) else {}
            answer["active"] = {"uuid": type(self).focus} if type(self).focus else None
            return answer
        return payload.get(action)

    async def close(self):
        pass


@pytest.fixture()
def lint_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    monkeypatch.setattr(
        "boardwise.cli._open_cli",
        lambda args: (_FakeEditor, Exception, 61190, "token"),
    )
    monkeypatch.setattr(
        "boardwise.cli._bridge_uri", lambda port: "ws://127.0.0.1:61190/eda"
    )
    return tmp_path


def _lint_args(*extra: str):
    return cli.build_parser().parse_args(["draw", "lint", *extra])


def _svg_payload(svg: str) -> dict:
    return {
        "format": "image/svg+xml",
        "data": base64.b64encode(svg.encode("utf-8")).decode("ascii"),
    }


TWO_PAGES = {
    "documents": [
        {"uuid": "page-p1", "name": "P1", "type": "page"},
        {"uuid": "page-p24", "name": "P24", "type": "page"},
    ],
}


def test_lint_refuses_a_page_the_editor_did_not_focus(lint_env, capsys):
    """The hole: `doc.open`'s answer was dropped and the focus never re-read.

    `sch.geometry` reads the focused page, so an open the host did not honour
    made this run lint the page it was already on and print it under `--page`'s
    name — a wrong page wearing the right label. The re-read is what refuses it,
    and `sch.geometry` is never called after the refusal.
    """
    _FakeEditor.reset(payload={"doc.list": TWO_PAGES}, honours=False, focus="page-p1")
    code = cli._cmd_draw_lint(_lint_args("--page", "P24"))
    assert code == 3
    err = capsys.readouterr().err
    assert "did not focus page page-p24" in err
    assert "page-p1" in err, "the line says where the editor actually is"
    actions = [action for action, _ in _FakeEditor.calls]
    assert "sch.geometry" not in actions
    assert "export.render" not in actions


def test_lint_re_reads_the_focus_and_restores_it(lint_env, capsys):
    """`doc.open` moves the user's tab, so a read-only verb puts it back.

    The call sequence is the discipline: list → open(target) → list (confirm) →
    geometry → render → open(original). The restore runs in a `finally`, so it
    happens on the success path too, and it is *reported* (the note) rather than
    left for the user to notice.
    """
    _FakeEditor.reset(
        payload={
            "doc.list": TWO_PAGES,
            "sch.geometry": _page(parts=[("U1", "p-U1", 100.0, 100.0, 0.0)]),
            "export.render": _svg_payload(
                '<svg><text style="fill:#0000FF" x="10" y="-10">VCC</text></svg>'
            ),
        },
        focus="page-p1",
    )
    code = cli._cmd_draw_lint(_lint_args("--page", "P24"))
    assert code == 0
    calls = _FakeEditor.calls
    assert [action for action, _ in calls] == [
        "doc.list", "doc.open", "doc.list", "sch.geometry", "export.render", "doc.open",
    ]
    assert calls[1][1]["uuid"] == "page-p24"
    assert calls[2][1] == {}, "the confirm is a bare doc.list"
    assert calls[-1][1]["uuid"] == "page-p1", "the original focus is what is restored"
    assert _FakeEditor.focus == "page-p1"
    assert "焦点已复位到 page-p1" in capsys.readouterr().out


def test_lint_does_not_open_anything_when_nothing_was_focused(lint_env, capsys):
    """Nothing focused before the run = nothing to restore (no invented uuid)."""
    _FakeEditor.reset(
        payload={
            "doc.list": TWO_PAGES,
            "sch.geometry": _page(parts=[("U1", "p-U1", 100.0, 100.0, 0.0)]),
            "export.render": _svg_payload("<svg></svg>"),
        },
        focus="",
    )
    assert cli._cmd_draw_lint(_lint_args("--page", "P24")) == 0
    assert [action for action, _ in _FakeEditor.calls] == [
        "doc.list", "doc.open", "doc.list", "sch.geometry", "export.render",
    ]
    assert "焦点已复位" not in capsys.readouterr().out


# ===========================================================================
# P2 — 90/270 are the sideways flag, not the vertical set
# ===========================================================================


def test_the_vertical_set_is_the_two_angles_the_compiler_writes():
    """`drawcompiler._flag_rotation` answers 0 or 180 and nothing else.

    069 sec.7's acceptance is 「旗标必须竖着」; a set that also spared 90/270
    spared exactly the flat glyph the gate exists for.
    """
    assert drawlint.FLAG_VERTICAL_ROTATIONS == frozenset({0, 180})


def _flag_snapshot(rotation: float) -> dict:
    return {
        "components": [
            {"primitiveId": "sheet1",
             "state": {"PrimitiveType": "Component", "ComponentType": "sheet"}},
            {"primitiveId": "flag-1",
             "state": {"PrimitiveType": "Component", "ComponentType": "netflag",
                       "PrimitiveId": "flag-1", "X": 80, "Y": 745,
                       "Rotation": rotation, "Net": "GND"}},
        ],
        "wires": [], "pins": [], "netlabels": [],
        "bboxes": {"sheet1": {"minX": 0, "minY": 0, "maxX": 1170, "maxY": 825}},
    }


def test_a_sideways_flag_is_reported_and_a_vertical_one_is_not():
    """The probe: rotation 90 used to answer L8 `[]`; it is now an ERROR.

    270 is here as well because it is the angle the host's own render shows on
    P22's turned flag, and 0/180 stay quiet — they are what the compiler emits.
    """
    for rotation in (90, 270):
        findings = drawlint.run_lint(_flag_snapshot(rotation))
        hits = [f for f in findings if f.predicate == "L8-flag-orientation"]
        assert len(hits) == 1, rotation
        assert hits[0].severity == "ERROR"
    for rotation in (0, 180, 360):
        findings = drawlint.run_lint(_flag_snapshot(rotation))
        assert not [f for f in findings if f.predicate == "L8-flag-orientation"]


# ===========================================================================
# P3 — the move's postcondition has to check the old wire is gone
# ===========================================================================

#: The netlist the plan recorded: U1.5 is one net with U2.1, before and after.
_LIVE_GROUP = {("U1", "5"): "GROUP_NET", ("U2", "1"): "GROUP_NET"}


def _move_plan() -> ChangePlan:
    """One part moved (+100, 0) with one wire taken off and drawn again."""
    return move_block_plan(
        PlanSource(input_sha256="a" * 64, page_uuid="page-1"),
        moves=[PlanMove(designator="U1", primitive_id="p-U1",
                        from_at=(300.0, 300.0), from_rotation=0.0,
                        to_at=(400.0, 300.0))],
        wire_ops=[PlanWireOp(
            primitive_id="w-link", kind="redraw", net="GROUP_NET",
            points_before=[(345.0, 310.0), (345.0, 320.0), (355.0, 320.0)],
            points_after=[(445.0, 310.0), (445.0, 320.0), (455.0, 320.0)],
        )],
        islands=[PlanIsland(pin="U1.5", mates=["U2.1"])],
        designators=["U1"], dx=100.0, dy=0.0,
    )


def test_the_move_reports_a_wire_the_delete_left_behind():
    """The probe: a verify page holding the redraw *and* the original wire.

    Both legs of the redraw hold (the part is at its target, a wire ends at both
    promised points), so the canvas leg used to come back empty and the run read
    the move as satisfied. The old wire beside its redrawn copy is the short
    坑 46 names, and `draw discard` already refuses it — this is the same check,
    in the move's own postcondition.
    """
    plan = _move_plan()
    verify = _page(
        parts=[("U1", "p-U1", 400.0, 300.0, 0.0)],
        wires=[
            ("new-w", "GROUP_NET", [(445.0, 310.0), (445.0, 320.0), (455.0, 320.0)]),
            ("w-link", "GROUP_NET", [(345.0, 310.0), (345.0, 320.0), (355.0, 320.0)]),
        ],
    )
    state = moveblock.postcondition_problems(plan, geometry=verify, live=_LIVE_GROUP)
    assert state["canvas"], "the delete did not take and the leg said nothing"
    assert any("w-link" in line for line in state["canvas"])
    assert not moveblock.all_satisfied(state)


def test_the_move_is_quiet_when_the_original_wire_is_gone():
    """The same page without the residue: the leg answers nothing (no new noise).

    Without this half, a check that always reports something would pass the test
    above for the wrong reason.
    """
    plan = _move_plan()
    verify = _page(
        parts=[("U1", "p-U1", 400.0, 300.0, 0.0)],
        wires=[
            ("new-w", "GROUP_NET", [(445.0, 310.0), (445.0, 320.0), (455.0, 320.0)]),
        ],
    )
    assert patchpin.primitive_present(verify, "w-link") is False
    state = moveblock.postcondition_problems(plan, geometry=verify, live=_LIVE_GROUP)
    assert state["canvas"] == []
    assert moveblock.all_satisfied(state)


# ===========================================================================
# P4 — a render that parsed to zero text nodes is not a clean bill for text
# ===========================================================================

STYLE_LESS_RENDER = (
    '<svg xmlns="http://www.w3.org/2000/svg">'
    '<text x="10" y="-10" font-size="7"><tspan>VCC</tspan></text>'
    "</svg>"
)


def test_a_render_with_no_classifiable_text_reads_zero_nodes():
    """The parser keys on the host's inline `style` (measured 2026-10-04).

    A render that does not carry it parses to **zero** text nodes, and every text
    predicate then answers `[]`: L1's text half, L2, L3 and L7 all go quiet while
    the run reports 「no findings」.
    """
    assert drawlint.render_text_nodes(STYLE_LESS_RENDER) == []
    assert drawlint.render_text_nodes(None) == []
    assert drawlint.render_text_nodes(
        '<svg><text style="fill:#0000FF" x="10" y="-10">VCC</text></svg>'
    )


def test_the_clean_sentence_is_not_written_when_the_text_was_not_read():
    """「reads clean」 is a claim about predicates that ran; skipped ones do not.

    `text_readable` is the caller's answer (`render_text_nodes`), and the default
    keeps every existing caller's sentence byte-identical.
    """
    assert "reads clean" in drawlint.render_report([], text_readable=True)
    degraded = drawlint.render_report([], text_readable=False)
    assert "reads clean" not in degraded
    assert "NOT" in degraded and "clean" in degraded
    assert "L1" in degraded and "L7" in degraded


def test_cli_lint_says_the_text_predicates_judged_nothing(tmp_path, capsys):
    """The replay path, offline: the note, the sentence, and the JSON flag.

    Exit stays 0 (no ERROR was found — the change is information, not a new
    verdict), but a machine reading `--json` sees `textReadable: false` instead
    of a clean page it cannot distinguish from a judged one.
    """
    snapshot = _page(parts=[("U1", "p-U1", 100.0, 100.0, 0.0)])
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(snapshot), encoding="utf-8")
    render = tmp_path / "render.svg"
    render.write_text(STYLE_LESS_RENDER, encoding="utf-8")

    code = cli._cmd_draw_lint(_lint_args(
        "--snapshot", str(snap), "--render", str(render),
        "--json", str(tmp_path / "report.json"),
    ))
    assert code == 0
    out = capsys.readouterr().out
    assert "no text node this reader can classify" in out
    assert "reads clean" not in out
    assert "NOT" in out and "called clean" in out
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["textReadable"] is False


def test_cli_lint_with_a_readable_render_still_calls_a_clean_page_clean(tmp_path, capsys):
    """The other direction: a parsed render keeps the sentence honest and unchanged."""
    snapshot = _page(parts=[("U1", "p-U1", 100.0, 100.0, 0.0)])
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(snapshot), encoding="utf-8")
    render = tmp_path / "render.svg"
    render.write_text(
        '<svg><text style="fill:#0000FF" x="10" y="-10">VCC</text></svg>',
        encoding="utf-8",
    )
    assert cli._cmd_draw_lint(_lint_args(
        "--snapshot", str(snap), "--render", str(render),
        "--json", str(tmp_path / "report.json"),
    )) == 0
    out = capsys.readouterr().out
    assert "reads clean" in out
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["textReadable"] is True


# ===========================================================================
# P5 — the flag leg checks which flag, and the unnamed wires check their own net
# ===========================================================================

def test_a_flag_at_the_wrong_point_is_reported_even_though_the_count_is_right():
    """The probe: one flag placed, one flag promised — and it is the wrong point.

    `netflag_count` before/after is a count, and a flag dropped on the wrong pin
    satisfies it exactly. The rail the plan meant to name stays unconnected while
    the report reads +1 as promised.
    """
    plan = ChangePlan(
        source=PlanSource(input_sha256="b" * 64, page_uuid="page-1"),
        change=PlanChange(draw_flags=[
            PlanDrawFlag(net="+5V", kind="Power", symbol_ref="PWR-5V", x=100.0, y=200.0),
        ]),
    )
    wrong_point = _page(netflags=[("+5V", 150.0, 200.0)])
    assert addcomponent.netflag_count(wrong_point) == 1, "the count leg cannot see this"
    state = drawapply.postcondition_problems(plan, geometry=wrong_point)
    assert state["canvas"], "a flag on the wrong point read as landed"
    assert any("no flag is on the page there" in line for line in state["canvas"])

    wrong_net = _page(netflags=[("VCC", 100.0, 200.0)])
    assert addcomponent.netflag_count(wrong_net) == 1
    state = drawapply.postcondition_problems(plan, geometry=wrong_net)
    assert any("is not one of them" in line for line in state["canvas"])

    right = _page(netflags=[("+5V", 100.0, 200.0)])
    assert drawapply.postcondition_problems(plan, geometry=right)["canvas"] == []


def _unnamed_rail_plan() -> ChangePlan:
    """A flagged rail: 069 sec.9 draws its wires **unnamed**, with a flag naming it."""
    return ChangePlan(
        source=PlanSource(input_sha256="c" * 64, page_uuid="page-1"),
        change=PlanChange(
            draw_wires=[PlanDrawWire(net="+5V", points=[
                (500.0, 500.0), (500.0, 600.0), (600.0, 600.0),
            ])],
            draw_flags=[PlanDrawFlag(net="+5V", kind="Power", x=600.0, y=600.0)],
        ),
    )


def test_an_unnamed_net_is_attributed_by_its_own_wiring():
    """The landing itself: the page's wire is unnamed and lies on the plan's own."""
    plan = _unnamed_rail_plan()
    geometry = _page(
        wires=[("w", "", [(500.0, 500.0), (500.0, 600.0), (600.0, 600.0)])],
        netflags=[("+5V", 600.0, 600.0)],
    )
    assert drawapply.postcondition_problems(plan, geometry=geometry)["canvas"] == []


def test_an_unnamed_net_with_no_wiring_of_its_own_is_reported():
    """The probe: the page's vertices are all *other* nets' wiring.

    The plan's rail is nowhere on this page — there is an unnamed wire (so the
    length bucket is satisfied) and a foreign wire, and neither lies on the
    wiring the plan drew. The check used to fall back to **every vertex on the
    page**, so any coincidence between a planned end and some other net's corner
    read as "the redrawn wire landed"; now a net with no wiring of its own is
    reported, named, instead of being answered from the page's vertices in
    general.
    """
    plan = _unnamed_rail_plan()
    geometry = _page(
        wires=[
            ("w-elsewhere", "", [(0.0, 0.0), (300.0, 0.0)]),
            ("w-sig", "SIG", [(700.0, 700.0), (900.0, 900.0)]),
        ],
        netflags=[("+5V", 600.0, 600.0)],
    )
    state = drawapply.postcondition_problems(plan, geometry=geometry)
    canvas = state["canvas"]
    assert canvas, "a rail that is not on the page read as landed"
    assert all("no wire vertex on the page lies on the wiring the plan drew" in line
               for line in canvas)
    assert any("(500, 500)" in line for line in canvas), "the end is named"
    assert any("(600, 600)" in line for line in canvas)


def test_a_page_vertex_touching_the_plan_end_still_counts():
    """The deliberate permissiveness, pinned so nobody "tightens" it by accident.

    The host merges wires that touch into one primitive (pit 32), and 057 E2
    depends on a landing merged with an *existing* wire reaching the later
    range leg (which names the wire that changed) instead of being refused here
    with a blunter sentence. So a vertex that lies on the plan's own wiring
    counts however the page names the wire it came from.
    """
    plan = _unnamed_rail_plan()
    geometry = _page(
        wires=[
            ("w-none", "", [(0.0, 0.0), (300.0, 0.0)]),
            ("w-sig", "SIG", [(500.0, 500.0), (0.0, 0.0)]),
            ("w-other", "OTHER", [(600.0, 600.0), (800.0, 800.0)]),
        ],
        netflags=[("+5V", 600.0, 600.0)],
    )
    assert drawapply.postcondition_problems(plan, geometry=geometry)["canvas"] == []


# ===========================================================================
# D3 — two boards with the same title are two boards, not one
# ===========================================================================

def _two_same_title_boards(findings: list[dict]) -> dict:
    return {
        "model": {
            "view": "schematic",
            "boards": [
                {"uuid": "u1", "title": "Board1", "components": ["R1"]},
                {"uuid": "u2", "title": "Board2", "components": ["R2"]},
            ],
        },
        "pcb_review": {
            "boards": [
                {"boardUuid": "u1", "title": "PCB1", "components": 3},
                {"boardUuid": "u2", "title": "PCB1", "components": 4},
            ],
        },
        "modules": [],
        "summary": {},
        "drc": {},
        "findings": findings,
    }


def _finding(rule_id: str, board: str = "", **extra) -> dict:
    return {
        "rule_id": rule_id, "severity": "WARN", "message": f"{rule_id} fired",
        "refs": [], "board": board, **extra,
    }


def test_a_pcb_title_two_documents_share_is_not_resolved_by_who_is_first():
    """The hole: both boards are titled `PCB1`, and every `PCB1` finding went to
    the first one — the second board's findings silently wore the first's name.
    """
    report = _two_same_title_boards([
        _finding("pcb-frame-a", board="PCB1"),
        _finding("sch-a", board="Board1"),
        _finding("sch-b", board="Board2"),
    ])
    section = checkup.board_report_section(report)
    per_board = [
        {entry["rule_id"] for group in board["groups"] for entry in group["findings"]}
        for board in section["boards"]
    ]
    assert per_board == [{"sch-a"}, {"sch-b"}], "the ambiguous finding is claimed"
    assert [row["rule_id"] for row in section["unassigned"]] == ["pcb-frame-a"]
    assert "无法归因" in section["unassigned"][0]["why"]
    assert "同名" in section["unassigned"][0]["why"]


def test_a_board_uuid_on_the_finding_decides_which_board_it_is():
    """The fix's other half: when the finding carries the uuid, it is not ambiguous."""
    report = _two_same_title_boards([
        _finding("pcb-frame-b", board="PCB1", boardUuid="u2"),
        _finding("pcb-frame-a", board="PCB1", boardUuid="u1"),
    ])
    section = checkup.board_report_section(report)
    per_board = [
        {entry["rule_id"] for group in board["groups"] for entry in group["findings"]}
        for board in section["boards"]
    ]
    assert per_board == [{"pcb-frame-a"}, {"pcb-frame-b"}]
    assert section["unassigned"] == []


def test_a_uuid_the_link_table_does_not_know_is_reported_not_fallen_through():
    """A stale uuid must not silently become "match by title, then" — that is how
    a finding lands on the wrong board while looking attributed."""
    report = _two_same_title_boards([
        _finding("pcb-frame", board="Board1", boardUuid="gone"),
    ])
    section = checkup.board_report_section(report)
    assert [row["rule_id"] for row in section["unassigned"]] == ["pcb-frame"]
    assert "boardUuid gone" in section["unassigned"][0]["why"]
    assert all(not row["findings"] for board in section["boards"] for row in board["groups"])


def test_a_project_level_finding_says_why_it_has_no_board():
    """An unassigned row now carries its reason, and the Markdown prints it."""
    report = _two_same_title_boards([_finding("project-wide")])
    section = checkup.board_report_section(report)
    assert section["unassigned"][0]["why"], "why it is not on a board, in words"
    assert "工程级" in section["unassigned"][0]["why"]
    text = checkup.render_board_report(report, section)
    assert "工程级读数" in text
    assert section["unassigned"][0]["why"] in text


# ===========================================================================
# D4 — the naming tables: which names are evidence, and which are not
# ===========================================================================

#: `(name, is_a_regulator_family)` — every entry here is read as 电源 evidence by
#: the open-ended `LM\d{2,4}` alternative, so the deny-list is what separates the
#: real ones from the false friends 163b added.
_REGULATOR_NAMES = [
    ("LM317", True), ("LM7805", True), ("AMS1117-3.3", True), ("MP1584", True),
    ("LM311", False), ("LM311P", False), ("LM335Z", False),
    ("LM4040", False), ("LM4041", False), ("LM321", False), ("LM2903", False),
    # `LM35` was already denied; the trailing lookahead must not let it swallow
    # `LM335`, and `LM4040` must not be read as the `LM40` of anything.
    ("LM35DZ", False), ("LM358", False),
]

_MCU_NAMES = ["STM32F103C8T6", "GD32F103", "STM8S003K3T6", "MSP430F149",
              "EFM32TG110F32", "PIC16F877A", "PIC12F629", "STC89C52RC",
              "LPC1768", "NRF52832", "BL702", "N76E003"]


@pytest.mark.parametrize("name,is_regulator", _REGULATOR_NAMES)
def test_the_regulator_table_says_which_lm_parts_are_not_supplies(name, is_regulator):
    """A part name is evidence, so the table has to say which names are not.

    `LM311`/`LM335`/`LM4040`/`LM2903`/`LM321` are a comparator, a temperature
    sensor, a shunt reference, a dual comparator and a single op-amp — one
    cluster of any of them was named 电源 by the wide alternative (163b).
    """
    text = checkup._part_text(_component("U1", mpn=name))
    hit = bool(checkup._REGULATOR_PATTERNS.search(text)) and not bool(
        checkup._REGULATOR_FALSE_FRIENDS.search(text)
    )
    assert hit is is_regulator, name


@pytest.mark.parametrize("name", _MCU_NAMES)
def test_every_mcu_family_in_the_table_actually_matches(name):
    """A dead alternative is the same defect as a missing one, and quieter.

    The trailing `(?![0-9])` is why the digit-ending families are spelled
    `\\d*`: `LPC\\d{3}` and `BL7\\d\\d` could never match `LPC1768` / `BL702`, so
    those alternatives were silent no-ops alongside the genuinely missing ones.
    """
    assert checkup._MCU_PATTERNS.search(checkup._part_text(_component("U1", mpn=name))), name


def _component(designator: str, *, mpn: str = "", device_name: str = ""):
    from boardwise.core.model import Component

    return Component(
        uid=f"u-{designator}", designator=designator, mpn=mpn,
        props={"device_name": device_name} if device_name else {},
    )


def _named_cluster(*parts):
    from boardwise.core.model import DesignModel, Net

    model = DesignModel()
    for part in parts:
        model.components[part.designator] = part
    model.nets["SIG"] = Net(name="SIG", pins=[(part.designator, "1") for part in parts])
    modules, _facts = checkup.modules_section(model=model, findings=[], attribution=None)
    return modules[0]["name"]


def test_an_lm311_cluster_is_no_longer_named_电源():
    """End to end: the wide alternative plus the deny-list, through the namer."""
    assert _named_cluster(_component("U1", mpn="LM311P")) == "未命名模块 1"
    assert _named_cluster(_component("U1", mpn="AMS1117-3.3")) == "电源"


def test_an_stm8_cluster_is_named_mcu():
    """The table's missing families, through the namer rather than the regex."""
    for name in ("STM8S003K3T6", "MSP430F149", "EFM32TG110F32", "PIC16F877A"):
        assert _named_cluster(_component("U1", mpn=name)) == "MCU", name


# ===========================================================================
# 157's leftover — the two "not connected" states get two sentences
# ===========================================================================

def test_status_summary_talks_about_the_connector_only():
    """This line is only ever printed by a daemon that answered `ping`.

    「先启动 daemon」 survived a `bridge start`, a restart and an edit, and after
    157 (auto-start) it was also factually wrong on any machine where a command
    had just pulled a daemon up.
    """
    for payload in ({"connector": False}, {"connector": True, "windows": []}, {}):
        line = daemon_module.status_summary(payload)
        assert line.startswith("未连接")
        assert "daemon 在跑" in line
        assert "bridge start" not in line
        assert "boardwise 扩展" in line


def test_the_unreachable_path_talks_about_the_auto_start_instead(
    monkeypatch, tmp_path, capsys
):
    """The other state: 157 starts a daemon for every command that needs one, so
    `daemon not reachable` means *that* failed — the repair is the log tail and a
    foreground run, and the connector half does not belong here.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))

    class _Refuses:
        @classmethod
        async def open(cls, uri, token, role, client=None):
            raise OSError("connection refused")

    import boardwise.bridge.client as client_module

    monkeypatch.setattr(client_module, "BridgeClient", _Refuses)
    args = cli.build_parser().parse_args(["bridge", "status"])
    assert cli._cmd_bridge_status(args) == 2
    out = capsys.readouterr().out
    first = out.splitlines()[0]
    assert first.startswith("未连接")
    assert "自动拉起" in first
    assert "~/.boardwise/log/" in first
    assert "boardwise bridge start" in first
    assert "connector 扩展" not in first, "the connector half belongs to the other state"
    assert "daemon not reachable" in out.splitlines()[1], "the reason stays below"


def test_the_sop_documents_both_states_and_quotes_the_machine():
    """The doc-claims discipline: the SOP's two repairs are the two the code words."""
    sop = (Path(__file__).resolve().parents[1] / "docs" / "review-sop.md").read_text(
        encoding="utf-8"
    )
    section = sop.split("### 3.0")[1].split("### 3.1")[0]
    assert "差的是 connector" in section, "the daemon-up state names the connector"
    assert "daemon not reachable" in section, "the other state is named as the code prints it"
    assert "bridge start" in section, "and both repairs are quoted, not paraphrased"
    assert daemon_module.status_summary({"connector": False}).split("——", 1)[1][:6] in section

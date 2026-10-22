"""533: an island page may not land on a sheet whose title block was not reserved.

The defect this batch closes is a **recurrence**: 530F deviation 4 and 532's page
A both ran `draw plan` without `--page-box`, packed an island page with no sheet,
and landed it — content came to rest inside the title block (532's render: 32
pins and wires inside `x 460..1160, y -190..-10`; the same reading on 530F's
first landing). 530G built the protection (`core.pageframe`, `PageBudget.keepouts`)
but left `--page-box` **optional**, so the protection was only ever as good as the
operator's memory.

Three pieces, each with its own tests below:

* **the page is readable** — `parsers.schematic.sheet_attrs_from_text` reads the
  sheet attributes out of a live document's own record stream (that is what
  `sys.get_document_source` answers), so `draw plan` bound to a live page derives
  the sheet itself instead of asking for `--page-box`;
* **the fact travels** — the compile writes a machine-readable reservation note
  into the plan (`core.pageframe.keep_out_note`), because `draw apply` is a
  different run that sees only the file;
* **the landing checks it** — `draw apply` refuses an island plan that reserved
  nothing, and refuses one whose reservation does not match the sheet it is
  landing on.

The fake editor is `tests/test_054_draw_cli.py`'s (imported, not copied), grown
with the one read this batch adds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core import pageframe
from boardwise.core.changeplan import ChangePlan
from boardwise.engines import drawapply, islandlayout
from boardwise.parsers import schematic
from test_054_draw_cli import (
    CIRCUIT,
    LCSC,
    LIBRARY,
    PAGE_BOX,
    PRESENTATION,
    _FakeEditor,
    _plan,
    _stub_editor,
    _stub_export,
)

SPECS = Path(__file__).resolve().parents[1] / "blocklib" / "specs"
FLYBACK_CIRCUIT = SPECS / "flyback_uc3845.circuit.json"
FLYBACK_PRESENTATION = SPECS / "flyback_uc3845.presentation.json"
FLYBACK_LIBRARY = SPECS / "flyback_uc3845.library.json"
FLYBACK_LCSC = C23242 = "C23242"

#: The sheet the live `test` project's pages declare (533's own measurement:
#: page `692b5a912e94d8d3`, created by `sch.doc.new`, answered 1170x825 with
#: Blade Width 10 and Title Block Position 3).
LIVE_SHEET = {"Width": "1170", "Height": "825", "Blade Width": "10",
              "Title Block Position": "3", "Title Block": "1"}
LIVE_PAGE_BOX = (0.0, 0.0, 1170.0, 825.0)
LIVE_TITLE_BLOCK = (460.0, 10.0, 1160.0, 190.0)


def _record(kind: str, identity: str, body: dict) -> str:
    return (
        json.dumps({"type": kind, "id": identity, "ticket": 1})
        + "||"
        + json.dumps(body)
        + "|"
    )


def _source(attrs: dict, *, attached: bool) -> str:
    """A document source shaped the way the host writes one.

    ``attached`` is the live shape (533 measured): the sheet attributes hang off
    the sheet symbol's own COMPONENT.  ``attached=False`` is the shape a file
    parse leaves them in — loose, with no parent — which is the second home
    :func:`schematic.sheet_attrs_from_text` has to read.
    """
    lines = [_record("DOCHEAD", "", {"docType": "SCH_PAGE", "uuid": "page-1"})]
    if attached:
        lines.append(_record("COMPONENT", "sheet-1",
                             {"x": 0, "y": 0, "rotation": 0, "parentId": ""}))
    for index, (key, value) in enumerate(attrs.items()):
        body = {"key": key, "value": value}
        if attached:
            body["parentId"] = "sheet-1"
        lines.append(_record("ATTR", f"a{index}", body))
    return "\n".join(lines)


class _PageEditor(_FakeEditor):
    """054's fake editor, plus the one read 533 adds."""

    def __init__(self, *args, attrs: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sheet_attrs = dict(LIVE_SHEET if attrs is None else attrs)

    async def call(self, action, params=None, **route):
        if action == "sys.get_document_source":
            self.calls.append(action)
            return {
                "source": "sys_FileManager.getDocumentSource",
                "uuid": self.page,
                "type": "page",
                "data": _source(self.sheet_attrs, attached=True),
            }
        return await super().call(action, params, **route)


def _flyback_plan(tmp_path: Path, *, page_box: str = "", name: str = "plan.json"):
    """A real island-page plan, built by `draw plan` itself (islands + all)."""
    out = tmp_path / name
    argv = [
        "draw", "plan",
        "--circuit", str(FLYBACK_CIRCUIT),
        "--presentation", str(FLYBACK_PRESENTATION),
        "--profiles", str(FLYBACK_LIBRARY),
        "--lcsc", f"R3={FLYBACK_LCSC}", "--lcsc", f"R15={FLYBACK_LCSC}",
        "--out", str(out),
    ]
    if page_box:
        argv += ["--page-box", page_box]
    assert cli.main(argv) == 0
    return out, ChangePlan.load(out)


# --------------------------------------------------------------- the page box


def test_the_page_box_comes_out_of_the_declared_width_and_height():
    assert pageframe.page_box_from_sheet_attrs(LIVE_SHEET) == LIVE_PAGE_BOX
    assert pageframe.title_block_from_sheet_attrs(LIVE_SHEET) == LIVE_TITLE_BLOCK


def test_a_page_that_states_no_size_states_no_box():
    """`None`, never A4 — "the page said nothing" is not "the page is 1170x825"."""
    assert pageframe.page_box_from_sheet_attrs({}) is None
    assert pageframe.page_box_from_sheet_attrs({"Width": "0", "Height": "825"}) is None
    assert pageframe.page_box_from_sheet_attrs({"Width": "abc", "Height": "825"}) is None
    assert pageframe.title_block_from_sheet_attrs({}) is None


def test_the_live_document_shape_is_read():
    """The host attaches the sheet attrs to the sheet symbol's own instance."""
    assert schematic.sheet_attrs_from_text(_source(LIVE_SHEET, attached=True)) == (
        LIVE_SHEET
    )


def test_the_file_shape_is_read_too():
    """The other home: loose ATTRs, which is what `collect_page_layout` reads."""
    assert schematic.sheet_attrs_from_text(_source(LIVE_SHEET, attached=False)) == (
        LIVE_SHEET
    )


def test_an_unreadable_stream_states_nothing():
    assert schematic.sheet_attrs_from_text("") == {}
    assert schematic.sheet_attrs_from_text("not a record stream") == {}


# ---------------------------------------------------- the fact travels with it


def test_the_reservation_note_round_trips():
    note = pageframe.keep_out_note(LIVE_PAGE_BOX, (LIVE_TITLE_BLOCK,))
    assert note.startswith(pageframe.KEEP_OUT_NOTE_PREFIX)
    assert pageframe.page_keep_out_from_notes(["unrelated", note]) == (
        LIVE_PAGE_BOX, LIVE_TITLE_BLOCK,
    )


def test_the_packers_own_keep_out_note_is_not_a_reservation():
    """`islandlayout` writes `S-01 keep-out: N keep-out box(es)` — a *different*
    fact (what the floor was raised by), and reading it as a reservation would let
    an unprotected plan through."""
    packer = "S-01 keep-out: 1 keep-out box(es) share the drawing's x range"
    assert pageframe.page_keep_out_from_notes([packer]) is None
    assert pageframe.page_keep_out_from_notes([]) is None


def test_an_offline_island_plan_says_the_sheet_is_not_reserved(tmp_path, capsys):
    """Offline is allowed — 530G §4's stated limit — and it is *stated*."""
    path, plan = _flyback_plan(tmp_path)
    printed = capsys.readouterr().out
    assert plan.change.draw_notes is not None
    assert islandlayout.ISLAND_PAGE_KIND in plan.change.draw_notes, printed
    assert pageframe.page_keep_out_from_notes(plan.change.draw_notes) is None, (
        "an offline plan must not claim a reservation"
    )
    assert "compiled **offline**" in printed, printed
    assert path.exists()


def test_an_island_plan_packed_for_a_sheet_records_the_reservation(tmp_path):
    _path, plan = _flyback_plan(tmp_path, page_box="0,0,1170,825")
    reserved = pageframe.page_keep_out_from_notes(plan.change.draw_notes)
    assert reserved == (LIVE_PAGE_BOX, LIVE_TITLE_BLOCK), plan.change.draw_notes
    assert islandlayout.ISLAND_PAGE_KIND in plan.change.draw_notes


def test_the_reserved_plan_is_packed_above_the_title_block(tmp_path):
    """The reservation is not a note about the packing — it *is* the packing."""
    _path, plan = _flyback_plan(tmp_path, page_box="0,0,1170,825")
    lowest = min(
        [point[1] for wire in plan.change.draw_wires for point in wire.points]
        + [part.y for part in plan.change.draw_parts]
        + [flag.y for flag in plan.change.draw_flags]
    )
    assert lowest >= LIVE_TITLE_BLOCK[3], lowest


def test_a_single_module_plan_carries_no_island_marker(tmp_path):
    """The guard is scoped to island pages: a module draws its own frame."""
    path, plan = _plan(tmp_path)
    assert islandlayout.ISLAND_PAGE_KIND not in plan.change.draw_notes
    assert not cli._draw_plan_is_island_page(plan)
    assert path.exists()


# ------------------------------------------------------------- the landing


def _apply(tmp_path, plan_path, *, page="page-1", page_box="", extra=()):
    return cli.main([
        "draw", "apply", str(plan_path), "--page", page, "--instance", "inst-1",
        *(["--page-box", page_box] if page_box else []),
        *extra,
        "--json", str(tmp_path / "apply.json"),
    ])


def test_an_unprotected_island_plan_is_refused_before_anything_is_written(
    monkeypatch, tmp_path, capsys
):
    editor = _PageEditor(page="page-1")
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    path, _plan_obj = _flyback_plan(tmp_path)

    code = _apply(tmp_path, path)

    printed = capsys.readouterr().out
    payload = json.loads((tmp_path / "apply.json").read_text(encoding="utf-8"))
    assert code == 5, printed
    assert payload["reason"] == "island_page_title_block_not_reserved"
    assert payload["write"]["calls"] == 0
    assert editor.writes == [], "the refusal happens before the first write"
    assert "530F deviation 4 and 532" in "\n".join(payload["notes"])


def test_a_plan_packed_for_another_sheet_is_refused(monkeypatch, tmp_path, capsys):
    """The block moves with the sheet's width, so a 1655-wide reservation does
    not clear the block on a 1170-wide page."""
    editor = _PageEditor(page="page-1")
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    path, _plan_obj = _flyback_plan(tmp_path, page_box="0,0,1655,1170")

    code = _apply(tmp_path, path)

    payload = json.loads((tmp_path / "apply.json").read_text(encoding="utf-8"))
    assert code == 5, capsys.readouterr().out
    assert payload["reason"] == "landing_sheet_mismatch"
    assert editor.writes == []
    assert payload["titleBlock"]["planRecordedPageBox"] == [0.0, 0.0, 1655.0, 1170.0]
    assert payload["titleBlock"]["livePageBox"] == [0.0, 0.0, 1170.0, 825.0]


def test_a_landing_whose_sheet_cannot_be_read_is_refused(monkeypatch, tmp_path, capsys):
    """No live attributes and no `--page-box`: refuse rather than guess."""
    editor = _PageEditor(page="page-1", attrs={})
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    path, _plan_obj = _flyback_plan(tmp_path, page_box="0,0,1170,825")

    code = _apply(tmp_path, path)

    payload = json.loads((tmp_path / "apply.json").read_text(encoding="utf-8"))
    assert code == 5, capsys.readouterr().out
    assert payload["reason"] == "landing_sheet_unreadable"
    assert editor.writes == []


def test_a_stated_page_box_is_the_fallback_for_an_unreadable_sheet(
    monkeypatch, tmp_path, capsys
):
    editor = _PageEditor(page="page-1", attrs={})
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    path, _plan_obj = _flyback_plan(tmp_path, page_box="0,0,1170,825")

    code = _apply(tmp_path, path, page_box="0,0,1170,825")

    payload = json.loads((tmp_path / "apply.json").read_text(encoding="utf-8"))
    assert payload["reason"] != "landing_sheet_unreadable", capsys.readouterr().out
    assert payload["titleBlock"]["source"] == "--page-box", payload["titleBlock"]
    assert payload["titleBlock"]["statedPageBox"] == [0.0, 0.0, 1170.0, 825.0]


def test_a_protected_island_plan_gets_past_the_guard(monkeypatch, tmp_path):
    """The guard leg lets it through, and the flow goes on to write.

    The landing is *not* driven to a success here: 054's fake editor answers pin
    offsets by LCSC number, and the flyback's 19 symbols are not in its table, so
    the run stops at the pin read-back with exit 3 — which is the fake's limit,
    not this guard's. What this test pins is that the title-block leg decided
    "reserved, and the sheet matches" and the writes were reached.
    """
    editor = _PageEditor(page="page-1")
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    path, _plan_obj = _flyback_plan(tmp_path, page_box="0,0,1170,825")

    _apply(tmp_path, path)

    payload = json.loads((tmp_path / "apply.json").read_text(encoding="utf-8"))
    assert payload["reason"] not in (
        "island_page_title_block_not_reserved", "landing_sheet_mismatch",
        "landing_sheet_unreadable",
    ), payload["reason"]
    assert payload["titleBlock"]["livePageBox"] == [0.0, 0.0, 1170.0, 825.0]
    assert payload["write"]["calls"] > 0, "the guard passed and the writes began"


def test_a_single_module_landing_is_untouched(monkeypatch, tmp_path):
    """No island marker, no title-block leg — the existing path is not moved."""
    editor = _PageEditor(page="page-1")
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    path, _plan_obj = _plan(tmp_path)

    _apply(tmp_path, path)

    payload = json.loads((tmp_path / "apply.json").read_text(encoding="utf-8"))
    assert "titleBlock" not in payload, payload.get("titleBlock")


def test_a_malformed_page_box_is_refused_before_the_bridge_opens(
    monkeypatch, tmp_path, capsys
):
    opened: list[str] = []

    def _open(args):
        opened.append("opened")
        raise AssertionError("the bridge must not open for an unusable --page-box")

    monkeypatch.setattr(cli, "_open_cli", _open)
    path, _plan_obj = _plan(tmp_path)

    code = _apply(tmp_path, path, page_box="0,0,10")

    assert code == 5
    assert "--page-box" in capsys.readouterr().err
    assert opened == []


# ------------------------------------------------------ the plan-side preflight


def test_a_live_bound_island_plan_reads_the_sheet_off_the_page(
    monkeypatch, tmp_path, capsys
):
    """The whole point: no `--page-box`, and the sheet comes from the page."""
    editor = _PageEditor(page="page-1", netlists=[{"components": {}}])
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    out = tmp_path / "plan.json"

    code = cli.main([
        "draw", "plan",
        "--circuit", str(FLYBACK_CIRCUIT),
        "--presentation", str(FLYBACK_PRESENTATION),
        "--profiles", str(FLYBACK_LIBRARY),
        "--lcsc", f"R3={FLYBACK_LCSC}", "--lcsc", f"R15={FLYBACK_LCSC}",
        "--page", "page-1", "--instance", "inst-1",
        "--out", str(out),
    ])

    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "sys.get_document_source" in editor.calls
    plan = ChangePlan.load(out)
    assert pageframe.page_keep_out_from_notes(plan.change.draw_notes) == (
        LIVE_PAGE_BOX, LIVE_TITLE_BLOCK,
    )
    assert "the sheet was read off the live page" in printed


def test_a_live_bound_island_plan_with_no_readable_sheet_is_refused(
    monkeypatch, tmp_path, capsys
):
    editor = _PageEditor(page="page-1", attrs={})
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)

    code = cli.main([
        "draw", "plan",
        "--circuit", str(FLYBACK_CIRCUIT),
        "--presentation", str(FLYBACK_PRESENTATION),
        "--profiles", str(FLYBACK_LIBRARY),
        "--lcsc", f"R3={FLYBACK_LCSC}", "--lcsc", f"R15={FLYBACK_LCSC}",
        "--page", "page-1", "--instance", "inst-1",
        "--out", str(tmp_path / "plan.json"),
    ])

    captured = capsys.readouterr()
    assert code == 5
    assert "S-01" in captured.err and "--page-box" in captured.err, captured.err
    assert not (tmp_path / "plan.json").exists()


def test_an_unreachable_daemon_is_exit_three_not_five(monkeypatch, tmp_path, capsys):
    """`3` = "the page's state cannot be stated", `5` = "the page said nothing
    usable" — the two must not collapse, or "the editor is down" would read as
    "this circuit cannot be drawn"."""

    class _DeadClient:
        @staticmethod
        async def open(*_args, **_kwargs):
            raise OSError("nothing is listening")

    monkeypatch.setattr(cli, "_open_cli", lambda args: (_DeadClient, OSError, 61190, "t"))

    code = cli.main([
        "draw", "plan",
        "--circuit", str(FLYBACK_CIRCUIT),
        "--presentation", str(FLYBACK_PRESENTATION),
        "--profiles", str(FLYBACK_LIBRARY),
        "--lcsc", f"R3={FLYBACK_LCSC}", "--lcsc", f"R15={FLYBACK_LCSC}",
        "--page", "page-1", "--instance", "inst-1",
        "--out", str(tmp_path / "plan.json"),
    ])

    printed = capsys.readouterr().err
    assert code == 3, printed
    assert "daemon not reachable" in printed, printed
    assert not (tmp_path / "plan.json").exists()


def test_a_live_bound_single_module_plan_does_not_read_the_sheet(
    monkeypatch, tmp_path
):
    """The preflight is for island pages only."""
    editor = _PageEditor(page="page-1", netlists=[{"components": {}}])
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    code = cli.main([
        "draw", "plan", "--circuit", str(CIRCUIT), "--presentation", str(PRESENTATION),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX,
        "--lcsc", "R1=C25744", "--lcsc", "R2=C25744",
        "--page", "page-1", "--out", str(tmp_path / "plan.json"),
    ])
    assert code == 0
    assert "sys.get_document_source" not in editor.calls


@pytest.mark.parametrize("box", ["0,0,1170,825", "0,0,1655,1170"])
def test_the_reservation_is_readable_whatever_the_sheet(tmp_path, box):
    _path, plan = _flyback_plan(tmp_path, page_box=box)
    reserved = pageframe.page_keep_out_from_notes(plan.change.draw_notes)
    assert reserved is not None
    assert reserved[0] == tuple(float(item) for item in box.split(","))
    assert reserved[1] == pageframe.title_block_box(reserved[0])


def test_drawapply_still_consumes_the_protected_plan(tmp_path):
    """The plan the guard lets through is one the landing can still build from."""
    _path, plan = _flyback_plan(tmp_path, page_box="0,0,1170,825")
    assert plan.change.kind == "draw-module"
    assert len(plan.change.draw_parts) == 19
    assert drawapply.planned_net_names(plan)


def test_the_guard_scopes_itself_to_island_pages_by_the_plans_own_note(tmp_path):
    _path, island = _flyback_plan(tmp_path, page_box="0,0,1170,825")
    module_path, module = _plan(tmp_path)
    assert cli._draw_plan_is_island_page(island)
    assert not cli._draw_plan_is_island_page(module)
    assert module_path.exists()


def test_lcsc_helper_is_the_one_the_flyback_needs():
    """A guard against the fixture drifting out from under these tests."""
    spec = json.loads(FLYBACK_CIRCUIT.read_text(encoding="utf-8"))
    missing = [
        part["id"] for part in spec["parts"] if not part.get("lcsc")
    ]
    assert missing == ["R3", "R15"], missing
    assert LCSC  # the divider fixture's own pair, imported from 054

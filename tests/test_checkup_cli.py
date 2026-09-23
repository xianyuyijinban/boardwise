"""`boardwise checkup` (025 batch 2): the data path, and the tier it admits to.

What these tests are for. `checkup` is the one command whose *headline* is a
claim about its own input — "tier: project-file" means the whole project was
read, "tier: netlist" means connectivity only. A command like that fails in two
directions, and both are tested here:

* it can **overstate** what it read (report project-file after a per-page merge,
  or report a model after every tier refused);
* it can **understate** and give up when a lower tier would have worked (the
  ladder is the whole feature: a closed project-download gate must fall to
  per-page exports, not to exit 3).

The offline `--file` path and the exit codes are tested the same way, because
they are the same contract: 0 reviewed / 2 unusable input / 3 state not
statable. The editor is a fake client; the *archives* are real ones lifted from
`tests/fixtures/ch340_golden.epro2`, so the parse under test is the real pipeline.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

from boardwise.bridge.protocol import ErrorCodes, BridgeError
from boardwise.cli import (
    _cmd_checkup,
    _cmd_review,
    _merge_schematic_models,
    _write_checkup_report,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "ch340_golden.epro2"
NETLIST = FIXTURES / "ch340_p1_editor_netlist.json"

GOLDEN_BYTES = GOLDEN.read_bytes()

#: A uuid that is not in the fixture, for the "no page was listed" branches.
PAGE_UUID = "6e27da4006bdba32"


def _document_archive(page_uuid: str = PAGE_UUID) -> bytes:
    """A *document* export: one page's records plus the library documents.

    Built from the real project fixture by splitting its record stream at its
    `DOCHEAD` lines — the same grammar `getDocumentFile` returns (batch 1
    measured it: the focused page plus the SYMBOL/DEVICE documents it
    references, and nothing else). Faking the shape by hand would test this
    test's idea of the format instead of the parser's.
    """
    from boardwise.parsers.epru_stream import load_epru_text

    text, _meta = load_epru_text(GOLDEN)
    groups: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    current: tuple | None = None
    for line in text.split("\n"):
        if line.startswith('{"type":"DOCHEAD"'):
            body = json.loads(line.split("||", 1)[1].rstrip("|"))
            current = (body.get("docType"), body.get("uuid"))
            order.append(current)
        if current is not None:
            groups.setdefault(current, []).append(line)
    keep = list(groups[("SCH_PAGE", page_uuid)])
    for key in order:
        if key[0] in ("SYMBOL", "DEVICE", "FOOTPRINT"):
            keep.extend(groups[key])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("page.epru", "\n".join(keep))
    return buffer.getvalue()


def _archive_payload(blob: bytes, *, scope: str, name: str = "ch340_golden.epro2") -> dict:
    return {
        "fileType": "epro2",
        "source": "sys_FileManager.getProjectFile" if scope == "project" else "sys_FileManager.getDocumentFile",
        "scope": scope,
        "encoding": "base64",
        "name": name,
        "mime": "zip",
        "bytes": len(blob),
        "data": base64.b64encode(blob).decode("ascii"),
        "isZip": True,
    }


def _netlist_payload() -> dict:
    """The editor's own netlist answer, as `sch.netlist` returns it."""
    text = json.dumps(json.loads(NETLIST.read_text(encoding="utf-8")), ensure_ascii=False)
    return {"type": "EasyEDA", "source": "getNetlistFile", "size": len(text), "text": text}


class _FakeBridgeClient:
    """A ``BridgeClient`` stand-in (the pattern `tests/test_persistence.py` uses).

    `history` accumulates across connections, because a `checkup` run opens two
    of them — the model ladder's and the DRC stage's — and an assertion about
    "what did the ladder ask for" must not be confused by the second connection's
    calls. `calls` stays per-connection.
    """

    opened = 0
    answers: dict = {}
    fail_open: BaseException | None = None
    calls: list = []
    history: list = []
    history_pairs: list = []
    route_kwargs: list = []

    @classmethod
    async def open(cls, uri, token, role, client=""):
        cls.opened += 1
        cls.calls = []
        cls.route_kwargs = []
        if cls.fail_open is not None:
            raise cls.fail_open
        return cls()

    async def call(self, action, params=None, **kwargs):
        type(self).calls.append(action)
        type(self).history.append(action)
        type(self).history_pairs.append((action, params or {}))
        type(self).route_kwargs.append(kwargs)
        answer = type(self).answers.get(action)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(action, params)
        return {} if answer is None else answer

    async def close(self):
        return None


@pytest.fixture
def fake_bridge(monkeypatch, tmp_path):
    """Isolated ``BOARDWISE_HOME`` (the command opens a CLI token) + fake client."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    import boardwise.bridge.client as client_module

    _FakeBridgeClient.answers = {}
    _FakeBridgeClient.fail_open = None
    _FakeBridgeClient.opened = 0
    _FakeBridgeClient.history = []
    _FakeBridgeClient.history_pairs = []
    monkeypatch.setattr(client_module, "BridgeClient", _FakeBridgeClient)
    return tmp_path


def _checkup_args(**overrides) -> argparse.Namespace:
    base = {"file": "", "project": "", "instance": "", "out": "checkup", "port": None}
    base.update(overrides)
    return argparse.Namespace(**base)


def _live_answers(*, project_refusal: bool = False, page_blob: bytes | None = None,
                  netlist: bool = True, drc: bool = True) -> dict:
    """The fake daemon's answers for one run of the ladder (and of the DRC stage)."""
    answers: dict = {
        "sys.probe": {"version": "3.2.186", "connector": "0.4.15", "topLevel": []},
        "doc.list": {
            "documents": [
                {"uuid": PAGE_UUID, "name": "P1", "type": "page", "active": True},
                {"uuid": "5dc38976c1fa45ce", "name": "PCB1", "type": "pcb"},
            ],
            "active": {"uuid": PAGE_UUID, "type": "page"},
            "projects": [
                {"name": "/test", "friendlyName": "test", "projectUuid": "uuid-test", "focused": True}
            ],
        },
    }
    if project_refusal:
        answers["sys.get_project_file"] = BridgeError(
            ErrorCodes.CONNECTOR_ERROR,
            "sys_FileManager.getProjectFile threw Error: 工程管理权限未启用 — "
            "the type package documents 工程管理 > 下载工程",
        )
    else:
        answers["sys.get_project_file"] = _archive_payload(GOLDEN_BYTES, scope="project")
    if page_blob is not None:
        answers["sys.get_document_file"] = _archive_payload(page_blob, scope="document")
    if netlist:
        answers["sch.netlist"] = _netlist_payload()
    if drc:
        # Clean-but-real shapes by default: the ladder tests are about the *data
        # path*, and a noisy DRC would decide their exit code for them. The
        # measured (dirty) answers live in `_measured_drc_answers` and are used by
        # the DRC tests, which are the ones that should care.
        answers["sch.drc_check"] = {
            "source": "sch_Drc.check", "checked": True, "mode": "counts",
            "counts": [{"type": "warn", "count": 0}], "entries": 1, "total": 0,
            "byType": {"warn": 0}, "passed": True, "elapsedMs": 12,
            "args": {"strict": True, "userInterface": False, "includeVerboseError": True},
            "page": {"uuid": PAGE_UUID, "type": "page"}, "uiRequested": False,
        }
        answers["pcb.drc_check"] = {
            "source": "pcb_Drc.check", "checked": True, "available": True, "mode": "groups",
            "groups": [],
            "counts": {"groups": 0, "returnedGroups": 0, "errors": 0, "errorsSource": "group-count",
                       "items": 0, "byLabel": {}, "jsonChars": 2},
            "truncated": False, "elapsedMs": 271,
            "args": {"strict": True, "userInterface": False, "includeVerboseError": True},
            "page": {"uuid": "5dc38976c1fa45ce", "type": "pcb"}, "uiRequested": False,
        }
    return answers


def _measured_drc_answers() -> dict:
    """The DRC answers the machine actually gave for the test project (batch 1).

    Not invented: `[{type:'warn',count:1}]` identical on all four pages, and one
    `Netlist Error / Import Changes` leaf whose group carries its own `count`
    (`outputs/025_probe_p4_pcb_drc.txt`). This is the content the report's DRC
    sections and its exit code are tested against.
    """
    return {
        "sch.drc_check": {
            "source": "sch_Drc.check", "checked": True, "mode": "counts",
            "counts": [{"type": "warn", "count": 1}], "entries": 1, "total": 1,
            "byType": {"warn": 1}, "passed": False, "elapsedMs": 13,
            "args": {"strict": True, "userInterface": False, "includeVerboseError": True},
            "page": {"uuid": PAGE_UUID, "type": "page"}, "uiRequested": False,
        },
        "pcb.drc_check": {
            "source": "pcb_Drc.check", "checked": True, "available": True, "mode": "groups",
            "groups": [{
                "name": "Netlist Error",
                "list": [{
                    "name": "Netlist Error",
                    "list": [{
                        "visible": True, "errorType": "Netlist Error",
                        "errorObjType": "Netlist Error", "ruleName": "Import Changes",
                        "ruleTypeName": "Import Changes",
                        "obj1": {"typeName": "Schematic Netlist", "suffix": ""},
                        "obj2": {"typeName": "PCB Netlist", "suffix": ""},
                        "objs": ["err0"],
                        "explanation": {
                            "str": "PCB and schematic netlist does not match.", "param": {},
                        },
                        "globalIndex": "err0",
                        "parentId": "DRCTab|_|Errors|_|Netlist Error|_|Netlist Error",
                    }],
                    "count": 1, "title": ["Netlist Error", "(1)"], "visible": True,
                }],
                "visible": True, "count": 1, "title": ["Netlist Error", "(1)"],
            }],
            "counts": {"groups": 1, "returnedGroups": 1, "errors": 1,
                       "errorsSource": "group-count", "items": 1,
                       "byLabel": {"Import Changes": 1}, "jsonChars": 667},
            "truncated": False, "elapsedMs": 271,
            "args": {"strict": True, "userInterface": False, "includeVerboseError": True},
            "page": {"uuid": "5dc38976c1fa45ce", "type": "pcb"}, "uiRequested": False,
        },
    }


# --------------------------------------------------------------------------
# the ladder: which tier runs, and what the report says about it
# --------------------------------------------------------------------------


def test_checkup_reads_the_whole_project_when_the_project_archive_works(
    fake_bridge, capsys, tmp_path
):
    _FakeBridgeClient.answers = _live_answers()
    args = _checkup_args(out=str(tmp_path / "out"))

    assert _cmd_checkup(args) == 0

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    from boardwise.cli import CHECKUP_SCHEMA

    assert report["schema"] == CHECKUP_SCHEMA
    assert report["source"]["tier"] == "project-file"
    assert report["source"]["project"]["friendlyName"] == "test"
    assert report["source"]["pageUuid"] == PAGE_UUID
    assert report["source"]["hostVersion"] == "3.2.186"
    assert report["source"]["connectorVersion"] == "0.4.15"
    assert report["source"]["attempts"][0]["ok"] is True
    assert report["source"]["attempts"][0]["bytes"] == len(GOLDEN_BYTES)
    assert report["model"]["components"] == 17
    assert report["model"]["view"] == "schematic"
    # The ladder stops at the first tier that works: no per-page export ran.
    # The ladder stops at the first tier that works; the DRC stage is a second
    # connection and does not appear in the ladder's own sequence.
    assert _FakeBridgeClient.history[:3] == ["sys.probe", "doc.list", "sys.get_project_file"]
    assert "sch.drc_check" in _FakeBridgeClient.history
    assert "tier project-file" in capsys.readouterr().out


def test_a_closed_project_gate_falls_to_per_page_exports_and_says_so(
    fake_bridge, capsys, tmp_path
):
    """The failure this whole ladder exists for: one gate closed, the other open."""
    _FakeBridgeClient.answers = _live_answers(project_refusal=True, page_blob=_document_archive())
    args = _checkup_args(out=str(tmp_path / "out"))

    assert _cmd_checkup(args) == 0

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["source"]["tier"] == "per-page"
    assert [a["tier"] for a in report["source"]["attempts"]] == ["project-file", "per-page"]
    assert report["source"]["attempts"][0]["ok"] is False
    assert report["source"]["attempts"][0]["code"] == ErrorCodes.CONNECTOR_ERROR
    assert report["source"]["attempts"][1]["ok"] is True
    assert report["model"]["components"] == 17
    notes = " ".join(report["source"]["notes"])
    assert "工程管理 > 下载工程" in notes, "the refusal must name the gate it hit"
    assert "per-page tier: 1/1 page archives parsed" in notes
    # One page is not a merge, and the report must not claim otherwise.
    assert "cross-page connectivity" not in notes
    # The ladder moved the focus and put it back.
    # ladder: open the page, restore. DRC stage: open the page, open the PCB,
    # restore. The focus is put back twice, and the last thing either stage does
    # is put it back where it found it.
    assert _FakeBridgeClient.history.count("doc.open") == 5
    opens = [params.get("uuid") for action, params in _FakeBridgeClient.history_pairs
             if action == "doc.open"]
    assert opens == [PAGE_UUID, PAGE_UUID, PAGE_UUID, "5dc38976c1fa45ce", PAGE_UUID]
    assert "tier per-page" in capsys.readouterr().out


def test_no_usable_export_falls_to_the_netlist_tier_which_is_connectivity_only(
    fake_bridge, capsys, tmp_path
):
    _FakeBridgeClient.answers = _live_answers(project_refusal=True)  # no page archive answer
    _FakeBridgeClient.answers["sys.get_document_file"] = BridgeError(
        ErrorCodes.CONNECTOR_ERROR, "文件导出 permission missing"
    )
    args = _checkup_args(out=str(tmp_path / "out"))

    assert _cmd_checkup(args) == 0

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["source"]["tier"] == "netlist"
    assert report["model"]["components"] == 17
    assert "connectivity only" in " ".join(report["source"]["notes"])
    assert report["model"]["view"] == "schematic", "the view is the report's, not the tier's"
    assert "tier netlist" in capsys.readouterr().out


def test_every_tier_refusing_is_exit_three_and_writes_no_report(
    fake_bridge, capsys, tmp_path
):
    """The direction that must never happen: an empty model reported as a clean pass."""
    _FakeBridgeClient.answers = _live_answers(project_refusal=True)
    _FakeBridgeClient.answers["sys.get_document_file"] = BridgeError(
        ErrorCodes.CONNECTOR_ERROR, "no permission"
    )
    _FakeBridgeClient.answers["sch.netlist"] = BridgeError(
        ErrorCodes.CONNECTOR_ERROR, "both netlist exports failed"
    )
    _FakeBridgeClient.answers["sch.geometry"] = BridgeError(
        ErrorCodes.CONNECTOR_ERROR, "no geometry"
    )
    out_dir = tmp_path / "out"
    args = _checkup_args(out=str(out_dir))

    assert _cmd_checkup(args) == 3
    assert not (out_dir / "report.json").exists()
    assert "在线状态不可陈述" in capsys.readouterr().err


def test_an_unreachable_daemon_is_exit_three(fake_bridge, capsys, tmp_path):
    _FakeBridgeClient.fail_open = OSError("connection refused")
    args = _checkup_args(out=str(tmp_path / "out"))
    assert _cmd_checkup(args) == 3
    assert "daemon not reachable" in capsys.readouterr().err


def test_no_connector_never_becomes_a_model(fake_bridge, capsys, tmp_path):
    _FakeBridgeClient.answers = {
        "sys.probe": BridgeError(ErrorCodes.NO_CONNECTOR, "no connector is connected"),
        "doc.list": BridgeError(ErrorCodes.NO_CONNECTOR, "no connector is connected"),
    }
    args = _checkup_args(out=str(tmp_path / "out"))
    assert _cmd_checkup(args) == 3
    assert "NO_CONNECTOR" in capsys.readouterr().err


# --------------------------------------------------------------------------
# the offline fallback and the argument surface
# --------------------------------------------------------------------------


def test_the_file_fallback_never_touches_the_bridge(fake_bridge, tmp_path):
    args = _checkup_args(file=str(GOLDEN), out=str(tmp_path / "out"))
    assert _cmd_checkup(args) == 0
    assert _FakeBridgeClient.opened == 0, "--file is the disconnected path"

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["source"]["tier"] == "file"
    assert report["source"]["file"] == str(GOLDEN)
    assert report["source"]["project"] is None
    assert report["model"]["components"] == 17
    assert report["model"]["nets"] == 13


def test_batch_four_sections_exist_and_are_empty(tmp_path):
    """What batch 4 still owes is present, empty and marked — and nothing else is.

    Rewritten in batch 3 to go through the **real** `_checkup_report` instead of a
    hand-built copy of its shape. The copy had already gone stale (it still listed
    `drc`/`findings` as pending after batch 3 filled them), which is exactly the
    drift a second spelling of the report invites.
    """
    from boardwise.cli import _checkup_report
    from boardwise.engines.drc import offline_section, summarise
    from boardwise.parsers.schematic import build_schematic_model

    model = build_schematic_model(GOLDEN)
    drc = {"schematic": offline_section("no editor"), "pcb": offline_section("no editor")}
    report = _checkup_report(
        tier="file", source={"file": str(GOLDEN)}, model=model, attempts=[], notes=[],
        drc=drc, findings=[], summary=summarise(drc=drc, findings=[]),
    )
    written = json.loads(_write_checkup_report(
        tmp_path / "nested" / "deep", report).read_text(encoding="utf-8"))

    assert set(written["pending"]) == {"modules", "ai_slots", "reportMd", "canvasImages"}, (
        "drc and findings are batch 3's and are no longer pending"
    )
    assert written["modules"] == []
    assert written["ai_slots"] == {"unknown_parts": [], "canvas_images": [], "summary_template": ""}
    assert written["drc"]["schematic"]["source"] == "offline-not-available"
    assert written["drc"]["schematic"]["checked"] is False
    assert written["summary"]["exitCode"] == 0
    assert written["findings"] == []


def test_file_and_a_window_hint_are_mutually_exclusive(capsys, tmp_path):
    args = _checkup_args(file=str(GOLDEN), project="test", out=str(tmp_path))
    assert _cmd_checkup(args) == 2
    assert "takes no --project/--instance" in capsys.readouterr().err


def test_an_unreadable_file_exits_two(capsys, tmp_path):
    args = _checkup_args(file=str(tmp_path / "nope.epro2"), out=str(tmp_path / "out"))
    assert _cmd_checkup(args) == 2
    assert "boardwise checkup" in capsys.readouterr().err

    # An extension nothing parses is unusable input. (A `.enet` holding `{}` is
    # *not*: it is a well-formed empty netlist, and 0 components is then the
    # honest answer rather than a usage error.)
    wrong = tmp_path / "board.txt"
    wrong.write_text("{}\n", encoding="utf-8")
    args = _checkup_args(file=str(wrong), out=str(tmp_path / "out"))
    assert _cmd_checkup(args) == 2
    assert "unsupported input type" in capsys.readouterr().err


# --------------------------------------------------------------------------
# the merge: what a per-page model can and cannot say
# --------------------------------------------------------------------------


def _component(designator: str, value: str = "1k"):
    from boardwise.core.model import Component

    return Component(uid=f"u-{designator}", designator=designator, value=value)


def _model_with(components: dict, nets: dict):
    from boardwise.core.model import DesignModel, Net

    model = DesignModel()
    for designator, component in components.items():
        model.components[designator] = component
    for name, pins in nets.items():
        model.nets[name] = Net(name=name, pins=list(pins))
    return model


def test_the_merge_unions_components_and_nets_and_records_clashes():
    notes: list[str] = []
    first = _model_with({"R1": _component("R1", "1k")}, {"VCC": [("R1", "1")]})
    second = _model_with(
        {"R1": _component("R1", "2k"), "C1": _component("C1", "100n")},
        {"VCC": [("C1", "1")], "GND": [("C1", "2")]},
    )

    merged = _merge_schematic_models([first, second], notes=notes)

    assert sorted(merged.components) == ["C1", "R1"]
    assert merged.components["R1"].value == "1k", "the first page wins; the clash is recorded"
    assert merged.duplicate_designators == ["R1"]
    assert sorted(merged.nets) == ["GND", "VCC"]
    assert merged.nets["VCC"].pins == [("R1", "1"), ("C1", "1")]
    assert "cross-page connectivity" in " ".join(notes)


def test_a_single_page_merge_adds_no_cross_page_note():
    notes: list[str] = []
    merged = _merge_schematic_models([_model_with({"R1": _component("R1")}, {})], notes=notes)
    assert sorted(merged.components) == ["R1"]
    assert notes == []


# --------------------------------------------------------------------------
# review --live: the same rules over the same ladder
# --------------------------------------------------------------------------


def test_review_live_runs_the_rules_over_the_live_model(fake_bridge, capsys, tmp_path):
    _FakeBridgeClient.answers = _live_answers()
    args = argparse.Namespace(
        file=None, latest=None, json_path=None, md_path=None, view=None, live=True,
        project="", instance="", port=None,
    )
    assert _cmd_review(args) == 0
    printed = capsys.readouterr().out
    assert "live:/test (tier project-file)" in printed
    assert "17 components, 13 nets" in printed
    assert "sys.get_project_file" in _FakeBridgeClient.history


def test_review_live_refuses_a_second_source_and_the_pcb_view(fake_bridge, capsys):
    base = {"json_path": None, "md_path": None, "live": True, "project": "", "instance": "", "port": None}

    with_file = argparse.Namespace(file="x.epro2", latest=None, view=None, **base)
    assert _cmd_review(with_file) == 2
    assert "--live reads the editor" in capsys.readouterr().err

    with_pcb = argparse.Namespace(file=None, latest=None, view="pcb", **base)
    assert _cmd_review(with_pcb) == 2
    assert "yields the schematic view" in capsys.readouterr().err


def test_review_live_with_no_tier_is_exit_three(fake_bridge, capsys):
    _FakeBridgeClient.answers = _live_answers(project_refusal=True)
    _FakeBridgeClient.answers["sys.get_document_file"] = BridgeError(ErrorCodes.NO_CONNECTOR, "gone")
    _FakeBridgeClient.answers["sch.netlist"] = BridgeError(ErrorCodes.NO_CONNECTOR, "gone")
    _FakeBridgeClient.answers["sch.geometry"] = BridgeError(ErrorCodes.NO_CONNECTOR, "gone")
    args = argparse.Namespace(
        file=None, latest=None, json_path=None, md_path=None, view=None, live=True,
        project="", instance="", port=None,
    )
    assert _cmd_review(args) == 3
    assert "在线状态不可陈述" in capsys.readouterr().err


# --------------------------------------------------------------------------
# batch 3: the editor's DRC, the rules' findings, and the exit code they decide
# --------------------------------------------------------------------------


def test_checkup_maps_the_editors_drc_into_both_sections(fake_bridge, capsys, tmp_path):
    """The measured answers: ERC counts (warn 1) and one PCB leaf. Exit 1."""
    _FakeBridgeClient.answers = {**_live_answers(), **_measured_drc_answers()}
    args = _checkup_args(out=str(tmp_path / "out"))

    assert _cmd_checkup(args) == 1

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    drc = report["drc"]
    assert drc["schematic"]["checked"] is True
    assert drc["schematic"]["warn"] == 1 and drc["schematic"]["countsBasis"] == "host-wide"
    assert drc["schematic"]["pagesChecked"] == 1
    assert drc["schematic"]["note"] == "逐条见 findings 段（规则引擎）"
    assert "fatalError" not in drc["schematic"], "a kind the host never stated stays absent"

    pcb = drc["pcb"]
    assert pcb["checked"] is True and pcb["documentUuid"] == "5dc38976c1fa45ce"
    assert pcb["totals"]["leafs"] == 1 and pcb["totals"]["hostErrors"] == 1
    leaf = pcb["groups"][0]["children"][0]["leafs"][0]
    assert leaf["ruleName"] == "Import Changes" and leaf["rendered"] == "verbatim"

    summary = report["summary"]
    assert summary["exitCode"] == 1
    assert summary["countsIncomplete"] is False
    assert [entry["ref"] for entry in summary["errors"]] == [
        "drc.pcb.groups[0].children[0].leafs[0]"
    ]
    assert [entry.get("kind") for entry in summary["warnings"]] == ["warn", None]
    assert summary["warnings"][0]["section"] == "drc.schematic"
    assert summary["warnings"][1]["section"] == "findings" and summary["warnings"][1]["ref"] == "findings[0]"
    printed = capsys.readouterr().out
    assert "drc: schematic: warn 1 [1/1 页, host-wide] | pcb: 1 leaf(s) in 1 group(s)" in printed
    assert "errors: 1" in printed and "reminder: 2 warning(s)" in printed
    assert "exit: 1" in printed


def test_findings_are_filled_and_have_the_same_shape_review_json_uses(
    fake_bridge, tmp_path, monkeypatch
):
    """`checkup`'s findings must be `review --json`'s findings, field for field.

    Two renderings of the same `Finding` are a drift risk, so the assertion is an
    equality against `render_json` rather than a list of expected keys: if the
    review command's output shape ever changes, this goes red with it.
    """
    from boardwise.engines.review import render_json
    from boardwise.cli import _finding_payload

    _FakeBridgeClient.answers = _live_answers()
    args = _checkup_args(out=str(tmp_path / "out"))
    captured: dict = {}
    import boardwise.cli as cli_module

    real_run_review = cli_module.run_review

    def spy(model):
        findings = real_run_review(model)
        captured["findings"] = findings
        return findings

    monkeypatch.setattr(cli_module, "run_review", spy)
    assert _cmd_checkup(args) == 0

    findings = captured["findings"]
    assert findings, "the golden fixture is expected to produce at least one finding"
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["findings"] == [_finding_payload(finding) for finding in findings]
    assert report["findings"] == json.loads(render_json(findings))["findings"]
    # And the shapes really are identical to review's, not merely equal to a copy.
    assert set(report["findings"][0]) >= {"rule_id", "severity", "message", "level", "evidence",
                                         "target", "refs"}


def test_an_error_finding_alone_is_exit_one(fake_bridge, tmp_path, monkeypatch):
    """No shipped fixture yields an ERROR-severity finding (the rules are tuned
    to WARN — measured on ch340_golden / llc_board / the injected boards), so the
    finding is injected here to exercise *the integration*: findings → summary →
    exit code."""
    import boardwise.cli as cli_module
    from boardwise.rules.base import Finding

    _FakeBridgeClient.answers = _live_answers()
    monkeypatch.setattr(
        cli_module, "run_review",
        lambda model: [Finding(rule_id="param-value-mpn-match", severity="ERROR",
                               level="L2", message="U3 value vs MPN", evidence=["U3 pin1 @ VCC"])],
    )
    args = _checkup_args(out=str(tmp_path / "out"))

    assert _cmd_checkup(args) == 1

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["errorCount"] == 1
    assert report["summary"]["errors"][-1]["ruleId"] == "param-value-mpn-match"
    assert report["summary"]["errors"][-1]["ref"] == "findings[0]"
    assert report["findings"][0]["severity"] == "ERROR"


def test_the_offline_fallback_asks_no_editor_and_says_there_was_no_drc(
    fake_bridge, tmp_path
):
    args = _checkup_args(file=str(GOLDEN), out=str(tmp_path / "out"))
    assert _cmd_checkup(args) == 0
    assert _FakeBridgeClient.opened == 0
    assert "sch.drc_check" not in _FakeBridgeClient.history

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    for name in ("schematic", "pcb"):
        section = report["drc"][name]
        assert section["checked"] is False
        assert section["source"] == "offline-not-available"
        assert section["reason"]
        assert "warn" not in section and "totals" not in section


def test_a_drc_that_could_not_run_is_not_a_clean_board(fake_bridge, capsys, tmp_path):
    """Both DRCs refusing must leave the sections un-checked *and* exit 0 —
    which is only honest because the sections carry the reason."""
    answers = _live_answers(drc=False)
    answers["sch.drc_check"] = BridgeError(ErrorCodes.NO_CONNECTOR, "gone")
    answers["pcb.drc_check"] = BridgeError(
        ErrorCodes.CONNECTOR_ERROR, "指定的主题消息在对应的画布内没有相关订阅"
    )
    _FakeBridgeClient.answers = answers
    args = _checkup_args(out=str(tmp_path / "out"))

    assert _cmd_checkup(args) == 0

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["drc"]["schematic"]["checked"] is False
    assert "NO_CONNECTOR" in report["drc"]["schematic"]["reason"]
    assert report["drc"]["pcb"]["checked"] is False
    assert "指定的主题消息" in report["drc"]["pcb"]["reason"]
    assert report["summary"]["errors"] == [] and report["summary"]["exitCode"] == 0
    printed = capsys.readouterr().out
    assert "schematic: not checked" in printed and "pcb: not checked" in printed


def test_every_page_is_opened_and_the_focus_is_put_back(fake_bridge, tmp_path):
    """The page walk is what makes the ERC readings per page; the restore is what
    keeps a read-only command from moving the user's editor."""
    answers = _live_answers()
    answers["doc.list"] = {
        "documents": [
            {"uuid": "page-a", "name": "A", "type": "page"},
            {"uuid": "page-b", "name": "B", "type": "page"},
            {"uuid": "5dc38976c1fa45ce", "name": "PCB1", "type": "pcb"},
        ],
        "active": {"uuid": "page-a", "type": "page"},
        "projects": [{"name": "/test", "friendlyName": "test", "projectUuid": "u", "focused": True}],
    }
    _FakeBridgeClient.answers = answers
    args = _checkup_args(out=str(tmp_path / "out"))

    assert _cmd_checkup(args) == 0

    from boardwise.cli import _read_online_drc

    _FakeBridgeClient.history_pairs = []
    _FakeBridgeClient.history = []
    _read_online_drc(args, notes=[])
    opens = [params.get("uuid") for action, params in _FakeBridgeClient.history_pairs
             if action == "doc.open"]
    assert opens == ["page-a", "page-b", "5dc38976c1fa45ce", "page-a"], (
        "every page, then the PCB, then back to whatever was focused"
    )
    assert _FakeBridgeClient.history.count("sch.drc_check") == 2

    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["drc"]["schematic"]["pagesChecked"] == 2
    assert report["drc"]["schematic"]["countsBasis"] == "host-wide", (
        "the two pages answered the same thing, so the host's counts are reported once"
    )

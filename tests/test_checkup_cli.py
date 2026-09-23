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
    """A ``BridgeClient`` stand-in (the pattern `tests/test_persistence.py` uses)."""

    opened = 0
    answers: dict = {}
    fail_open: BaseException | None = None
    calls: list = []
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
    monkeypatch.setattr(client_module, "BridgeClient", _FakeBridgeClient)
    return tmp_path


def _checkup_args(**overrides) -> argparse.Namespace:
    base = {"file": "", "project": "", "instance": "", "out": "checkup", "port": None}
    base.update(overrides)
    return argparse.Namespace(**base)


def _live_answers(*, project_refusal: bool = False, page_blob: bytes | None = None,
                  netlist: bool = True) -> dict:
    """The fake daemon's answers for one run of the ladder."""
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
    return answers


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
    assert report["schema"] == "boardwise.checkup/1"
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
    assert _FakeBridgeClient.calls == ["sys.probe", "doc.list", "sys.get_project_file"]
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
    assert _FakeBridgeClient.calls.count("doc.open") == 2
    assert _FakeBridgeClient.calls[-1] == "doc.open"
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


def test_batch_three_and_four_sections_exist_and_are_empty(tmp_path):
    """The skeleton is a contract: fields present, empty, and marked as owed."""
    from boardwise.parsers.schematic import build_schematic_model

    model = build_schematic_model(GOLDEN)
    report = {
        "schema": "boardwise.checkup/1",
        "source": {"tier": "file", "attempts": [], "notes": []},
        "model": {"view": "schematic", "components": len(model.components), "nets": len(model.nets),
                  "designators": sorted(model.components), "duplicateDesignators": []},
        "pending": {"drc": "batch 3", "findings": "batch 3/4", "modules": "batch 4",
                    "ai_slots": "batch 4", "reportMd": "batch 4", "canvasImages": "batch 4"},
        "drc": {"schematic": None, "pcb": None},
        "modules": [],
        "findings": [],
        "ai_slots": {"unknown_parts": [], "canvas_images": [], "summary_template": ""},
    }
    path = _write_checkup_report(tmp_path / "nested" / "deep", report)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["drc"] == {"schematic": None, "pcb": None}
    assert written["modules"] == [] and written["findings"] == []
    assert written["ai_slots"] == {"unknown_parts": [], "canvas_images": [], "summary_template": ""}
    assert set(written["pending"]) == {"drc", "findings", "modules", "ai_slots", "reportMd", "canvasImages"}


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
    assert _FakeBridgeClient.calls[-1] == "sys.get_project_file"


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

"""537C3b2b: ``boardwise review-evidence`` — the CLI and its fake-client wiring.

Why this file exists. 537C3b1 built the collector (``engines/liveevidence.py``)
and 537C3b2a the merge (``engines/evidence.merge_live_capture``); neither had a
command, a file on disk, or a report that carried the result. This is that
command, and what it must not do is as important as what it does:

1. **Identity comes from the report, never from a document.** ``expected_project_uuid``
   is read from ``report.source.project.projectUuid``; ``document.uuid`` is a
   page id and comparing it with the focused project would either refuse every
   honest run or "verify" a page against itself.
2. **A report is checked before the daemon is touched.** A missing report is
   exit 3 with zero connections; an evidence section of another schema (or with
   an illegal status) is exit 2 **before navigation**.
3. **The capture lands as bytes, then the merge is attempted.** ``live-evidence.json``
   is stable pretty JSON with its ``bytes``/``sha256`` pointed at from
   ``report.evidence.liveCapture.captureFile``; a merge that refuses the shape
   leaves the report byte-identical and still keeps the capture.
4. **A failed reading is merged as a failed reading.** ``capture.ok`` or the
   process exit code never turn a ``failed``/``missing`` channel into ``ok``, and
   the old ``completion``/``summary`` board conclusions are not rewritten.
5. **``review-summary.md`` is not this command's file.** A sentinel an engineer
   wrote there survives byte for byte; the command never calls
   ``_write_review_summary``.
6. **Exit codes are this collection's own reading** — 0 complete + verified + focus
   restored, 1 anything short of that (an empty expectation included), 2 unusable
   input, 3 nothing may be stated (no report / daemon unreachable / ``doc.list``
   itself failed). None of them is a board verdict.

No daemon, no editor, no project file: the bridge client is an anonymous
stand-in that only records calls, exactly the shape
``tests/test_537c_live_capture.py`` uses.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.engines.evidence import (
    CHANNEL_ORDER,
    EVIDENCE_SCHEMA,
    LIVE_CHANNEL_ORDER,
    LIVE_EVIDENCE_SCHEMA,
    evidence_console_line,
    evidence_section,
)

PROJECT = "proj-synthetic"
PAGES = (("p1", "PWR"), ("p2", "CTRL"))
PCBS = (("b1", "B1"),)
ROUTE = {"target_project": "test2", "target_instance": "win-1"}
CAPTURE_FILE = "live-evidence.json"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"synthetic-capture-body"
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")
REVIEW_SUMMARY_SENTINEL = (
    "# synthetic review summary\n\n"
    "| 位置 | 结论（人写的） | 证据 |\n"
    "| --- | --- | --- |\n"
    "| PWR/TP1 | 这一行是人工分析，命令不得覆盖 | 目测 |\n"
).encode("utf-8")
REPORT_MD_SENTINEL = "STALE report.md — 本命令必须重渲染\n"
BOARD_MD_SENTINEL = "STALE board-report.md — 本命令必须重渲染\n"


# ---------------------------------------------------------------------------
# the anonymous bridge: a client class + the action fake behind it
# ---------------------------------------------------------------------------


class FakeBridgeError(Exception):
    """The shape a real ``BridgeClient.call`` raises (``code`` + ``message``)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def make_listing(
    *,
    pages=PAGES,
    pcbs=PCBS,
    active="p2",
    project_uuid=PROJECT,
) -> dict:
    documents = [
        {"uuid": uuid, "name": name, "type": "page"} for uuid, name in pages
    ] + [{"uuid": uuid, "name": name, "type": "pcb"} for uuid, name in pcbs]
    projects = []
    if project_uuid is not None:
        projects = [{
            "projectUuid": project_uuid,
            "friendlyName": "synthetic",
            "focused": True,
            "schematics": [],
            "pcbs": [],
            "documents": "full",
        }]
    return {
        "documents": documents,
        "projects": projects,
        "active": {"uuid": active} if active else None,
        "count": len(documents),
    }


class FakeClient:
    """An anonymous bridge client: every call is recorded, nothing is executed.

    Same contract as ``tests/test_537c_live_capture.py`` (the collector's fake):
    ``overrides`` maps an action to a payload, an exception, or a
    ``handler(client, params)``; ``document.current`` answers the real host's
    shape (``{"active": {"uuid": ...}}``), never an invented ``document.uuid``.
    """

    def __init__(
        self,
        listing: dict,
        *,
        overrides: dict | None = None,
        ignore_open=(),
        open_fail=(),
        current_problems=None,
    ):
        self.listing = listing
        self.active = (listing.get("active") or {}).get("uuid")
        self.overrides = dict(overrides or {})
        self.ignore_open = set(ignore_open)
        self.open_fail = set(open_fail)
        self.current_problems = list(current_problems or [])
        self.calls: list[dict] = []
        self.close_calls = 0

    def document_type(self, uuid):
        for row in self.listing.get("documents") or []:
            if row.get("uuid") == uuid:
                return row.get("type")
        return "unknown"

    async def call(self, action, params=None, **route):
        params = dict(params or {})
        self.calls.append({
            "action": action,
            "params": params,
            "route": dict(route),
            "active": self.active,
        })
        if action in self.overrides:
            value = self.overrides[action]
            if callable(value):
                value = value(self, params)
            if isinstance(value, BaseException):
                raise value
            return value
        if action == "doc.list":
            return json.loads(json.dumps(self.listing))
        if action == "doc.open":
            uuid = str(params.get("uuid") or "")
            if uuid in self.open_fail:
                raise FakeBridgeError("NOT_FOUND", f"no document {uuid}")
            if uuid not in self.ignore_open:
                self.active = uuid
            return {"opened": uuid}
        if action == "document.current":
            box = {
                "active": {
                    "uuid": self.active,
                    "type": self.document_type(self.active),
                },
                "type": self.document_type(self.active),
                "typeSource": "getCurrentDocumentInfo",
                "tabs": [],
            }
            if self.current_problems:
                box["problems"] = list(self.current_problems)
            return box
        if action in ("sch.readback", "pcb.readback"):
            kind = action.split(".")[0]
            return {
                "kind": kind,
                "components": [],
                "primitives": [],
                "componentCount": 0,
            }
        if action == "pcb.geometry":
            requested = list(params.get("bboxIds") or [])
            return {
                "bboxes": {
                    pid: {"minX": 0, "minY": 0, "maxX": 1, "maxY": 1}
                    for pid in requested
                },
                "meta": {
                    "available": {"bboxes": True},
                    "requested": len(requested),
                    "measured": len(requested),
                },
            }
        if action == "sch.netlist":
            return {"type": "EasyEDA", "text": "NETLIST SYNTHETIC\n"}
        if action == "export.render":
            return {"format": "image/png", "data": PNG_B64}
        raise AssertionError(f"unexpected action {action!r}")

    async def close(self):
        self.close_calls += 1

    def actions(self) -> list[str]:
        return [call["action"] for call in self.calls]


class FakeBridgeClient:
    """``BridgeClient`` stand-in: ``open`` hands back the fake the test built."""

    opened = 0
    uri = ""
    client: FakeClient | None = None
    fail_open: BaseException | None = None

    @classmethod
    async def open(cls, uri, token, role, client=""):
        cls.opened += 1
        cls.uri = uri
        if cls.fail_open is not None:
            raise cls.fail_open
        return cls.client


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    """Patch the one door the CLI dials, and keep the token file out of ``$HOME``."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    import boardwise.bridge.client as client_module

    FakeBridgeClient.opened = 0
    FakeBridgeClient.uri = ""
    FakeBridgeClient.client = None
    FakeBridgeClient.fail_open = None
    monkeypatch.setattr(client_module, "BridgeClient", FakeBridgeClient)

    def connect(listing: dict, **kwargs) -> FakeClient:
        fake = FakeClient(listing, **kwargs)
        FakeBridgeClient.client = fake
        return fake

    return connect


# ---------------------------------------------------------------------------
# a report on disk: the shape `checkup` writes, with a live-shaped evidence row
# ---------------------------------------------------------------------------


def baseline_evidence() -> dict:
    """The six-channel ledger a `checkup` leaves: live rows missing, archive ok."""
    return evidence_section(
        tier="file",
        pcb_review={
            "available": True,
            "boards": [{"title": "B1", "components": 2, "copperLayers": 2}],
        },
    )


def make_report(*, project_uuid=PROJECT, evidence: dict | None = None) -> dict:
    return {
        "schema": "boardwise.checkup/7",
        "source": {
            "tier": "file",
            "tierLabel": "离线归档（file）",
            "project": {"name": "synthetic", "projectUuid": project_uuid},
            "attempts": [],
            "notes": [],
        },
        "model": {"components": 3, "nets": 2},
        "summary": {
            "errorCount": 0,
            "warnCount": 0,
            "infoCount": 0,
            "exitCode": 0,
            "conclusion": "synthetic fixture",
        },
        "completion": {"verdict": "complete", "verdictWhy": [], "warningsPendingTriage": 0},
        "findings": [],
        "modules": [],
        "drc": {},
        "evidence": baseline_evidence() if evidence is None else evidence,
    }


def seed_out_dir(out_dir: Path, report: dict | None = None) -> Path:
    """Write the three products through the real writers, plus a human summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report = make_report() if report is None else report
    cli._write_checkup_report(out_dir, report)
    cli._write_checkup_markdown(out_dir, report)
    cli._write_board_report(out_dir, report)
    (out_dir / "review-summary.md").write_bytes(REVIEW_SUMMARY_SENTINEL)
    return out_dir


def read_report(out_dir: Path) -> dict:
    return json.loads((out_dir / "report.json").read_text(encoding="utf-8"))


def run_cli(*argv: str) -> int:
    return cli.main(["review-evidence", *argv])


def calls_named(client: FakeClient, action: str) -> list[dict]:
    return [call for call in client.calls if call["action"] == action]


def artifact_rows(report: dict, channel: str) -> list[dict]:
    return list(report["evidence"]["channels"][channel]["artifacts"])


# ---------------------------------------------------------------------------
# 1. the full success: three products, one capture, exit 0
# ---------------------------------------------------------------------------


def test_success_writes_the_capture_and_all_three_products(bridge, capsys, tmp_path):
    client = bridge(make_listing())
    out = seed_out_dir(tmp_path / "out")
    before = read_report(out)
    # A PNG already on disk under the name the collector would pick: the
    # collector must pick a new one, and this byte must not move.
    (out / "live-sch-PWR-p1.png").write_bytes(b"sentinel-png-not-a-real-render")

    code = run_cli(
        "--out", str(out), "--project", "test2", "--instance", "win-1",
        "--port", "61191",
    )

    assert code == 0, capsys.readouterr()
    assert FakeBridgeClient.opened == 1
    assert FakeBridgeClient.uri == "ws://127.0.0.1:61191/eda"
    assert client.close_calls == 1, "the CLI owns the client and must close it"

    # Route kwargs reach every action: one route for the whole run.
    assert client.calls[0]["action"] == "doc.list"
    for call in client.calls:
        assert call["route"] == ROUTE, call

    # The capture file is exactly the bytes the report points at.
    capture_path = out / CAPTURE_FILE
    blob = capture_path.read_bytes()
    written = read_report(out)
    files = written["evidence"]["liveCapture"]["captureFile"]
    assert files == {
        "file": CAPTURE_FILE,
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
    }
    capture = json.loads(blob.decode("utf-8"))
    assert blob.endswith(b"\n"), "a machine-managed file ends with one newline"
    assert capture["schema"] == "boardwise.live-evidence/1"
    assert capture["ok"] is True
    assert capture["identity"]["verifiedAgainstReport"] is True
    assert set(capture["channels"]) == {
        "liveSchematic", "livePcb", "schematicImage", "pcbImage",
    }, "the capture file carries exactly the four live rows the merge reads"

    # Four live channels replaced from the capture, archive/datasheets verbatim.
    evidence = written["evidence"]
    assert evidence["schema"] == EVIDENCE_SCHEMA
    assert [evidence["channels"][name]["status"] for name in CHANNEL_ORDER] == [
        "ok", "ok", "ok", "ok", "ok", "ok",
    ]
    assert evidence["delivery"]["status"] == "complete"
    assert evidence["coverage"]["livePcb"] == "ok"

    # The pre-existing PNG keeps its bytes; every artifact the report names is real.
    assert (out / "live-sch-PWR-p1.png").read_bytes() == b"sentinel-png-not-a-real-render"
    for name in ("liveSchematic", "schematicImage", "pcbImage"):
        for row in artifact_rows(written, name):
            artifact = out / row["file"]
            assert artifact.is_file(), row
            data = artifact.read_bytes()
            assert len(data) == row["bytes"]
            assert hashlib.sha256(data).hexdigest() == row["sha256"]

    # The board-level conclusions are the ones the report already carried.
    for key in ("completion", "summary"):
        assert written[key] == before[key], f"{key} 被本命令改写了"
    assert written["conclusion"] == before["conclusion"]
    assert written["board_report"] == before["board_report"]
    assert written["schema"] == before["schema"]
    assert set(written) == set(before), "本命令不新增 report 键"

    # report.md re-rendered from the same reading; board-report.md too.
    report_md = (out / "report.md").read_text(encoding="utf-8")
    assert "## 证据覆盖（evidence）" in report_md
    assert "`livePcb`" in report_md
    board_md = (out / "board-report.md").read_text(encoding="utf-8")
    assert board_md != BOARD_MD_SENTINEL
    assert written["conclusion"]["oneLiner"] in board_md

    # The human summary is not this command's file.
    assert (out / "review-summary.md").read_bytes() == REVIEW_SUMMARY_SENTINEL

    console = capsys.readouterr().out
    assert str(capture_path) in console
    assert "verifiedAgainstReport: True" in console
    assert "restored" in console
    assert evidence_console_line(evidence) in console
    assert "板子通过" not in console
    assert "可以投板" not in console
    assert "不是板级通过" in console


def test_review_summary_sentinel_survives_a_failed_collection(bridge, capsys, tmp_path):
    """Even a failed run must not rebuild the engineer's summary (537C §2)."""
    bridge(make_listing(), overrides={
        "sch.readback": FakeBridgeError("TIMEOUT", "synthetic readback timeout"),
    })
    out = seed_out_dir(tmp_path / "out")
    assert run_cli("--out", str(out)) == 1, capsys.readouterr()
    assert (out / "review-summary.md").read_bytes() == REVIEW_SUMMARY_SENTINEL
    assert not (out / "review-summary.md.bak").exists()


# ---------------------------------------------------------------------------
# 2. identity: an empty expectation is never "verified"
# ---------------------------------------------------------------------------


def test_a_report_without_a_project_uuid_still_discloses_and_exits_one(bridge, capsys, tmp_path):
    client = bridge(make_listing())
    report = make_report(project_uuid="")
    out = seed_out_dir(tmp_path / "out", report)

    code = run_cli("--out", str(out))

    assert code == 1, "expected='' + capture.ok=true 仍是 1：身份没有核实"
    assert client.close_calls == 1
    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    assert capture["ok"] is True, "证据本身是完整的——拒绝的只是身份核实"
    assert capture["identity"]["expectedProjectUuid"] == ""
    assert capture["identity"]["verifiedAgainstReport"] is False
    assert capture["identity"]["ok"] is True, "证据没读错——缺的是可核实的期望身份"

    evidence = read_report(out)["evidence"]
    assert evidence["delivery"]["status"] == "partial"
    codes = [row["code"] for row in evidence["delivery"]["requiredDisclosures"]]
    assert "live-identity-unverified" in codes

    console = capsys.readouterr().out
    assert "verifiedAgainstReport: False" in console
    assert "live-identity-unverified" in console


def test_a_project_uuid_from_the_listing_that_differs_is_exit_one_without_navigation(
    bridge, capsys, tmp_path
):
    client = bridge(make_listing(project_uuid="proj-someone-else"))
    out = seed_out_dir(tmp_path / "out")

    assert run_cli("--out", str(out)) == 1, capsys.readouterr()

    assert client.actions() == ["doc.list"], "身份不一致时不得导航"
    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    assert capture["ok"] is False
    assert capture["identity"]["verifiedAgainstReport"] is False
    assert capture["identity"]["error"]["code"] == "PROJECT_IDENTITY_MISMATCH"
    evidence = read_report(out)["evidence"]
    assert evidence["coverage"]["livePcb"] == "missing", "未采集不是 failed，也不是 ok"


# ---------------------------------------------------------------------------
# 3. a failed reading is merged as failed, successes stay
# ---------------------------------------------------------------------------


def test_one_failed_render_exits_one_and_keeps_the_other_artifacts(bridge, capsys, tmp_path):
    def render(client, params):
        if params.get("pageUuid") == "p1":
            raise FakeBridgeError("TIMEOUT", "synthetic render timeout")
        return {"format": "image/png", "data": PNG_B64}

    bridge(make_listing(), overrides={"export.render": render})
    out = seed_out_dir(tmp_path / "out")

    assert run_cli("--out", str(out)) == 1, capsys.readouterr()

    evidence = read_report(out)["evidence"]
    assert evidence["channels"]["schematicImage"]["status"] == "failed"
    assert evidence["channels"]["liveSchematic"]["status"] == "ok", "readback 与网表仍成功"
    assert evidence["channels"]["livePcb"]["status"] == "ok"
    kept = artifact_rows(read_report(out), "schematicImage")
    assert [row["file"] for row in kept], "已成功的 PNG 必须留在 artifacts 里"
    for row in kept:
        assert (out / row["file"]).is_file()
    netlists = artifact_rows(read_report(out), "liveSchematic")
    assert any(row["kind"] == "netlist" for row in netlists)


def test_a_failed_focus_restore_is_exit_one_and_disclosed(bridge, capsys, tmp_path):
    """The restore attempt is the only one allowed to fail here."""
    opens: list[str] = []

    def open_handler(client, params):
        uuid = str(params.get("uuid") or "")
        opens.append(uuid)
        if uuid == "p2" and opens.count("p2") == 2:
            raise FakeBridgeError("TIMEOUT", "synthetic restore timeout")
        client.active = uuid
        return {"opened": uuid}

    client = bridge(make_listing(), overrides={"doc.open": open_handler})
    out = seed_out_dir(tmp_path / "out")

    assert run_cli("--out", str(out)) == 1, capsys.readouterr()

    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    assert capture["focusRestore"]["ok"] is False
    assert capture["focusRestore"]["status"] == "failed"
    assert capture["focusRestore"]["attempted"] is True
    assert capture["ok"] is False
    assert capture["channels"]["liveSchematic"]["status"] == "ok", "采集本身可以成功"
    evidence = read_report(out)["evidence"]
    codes = [row["code"] for row in evidence["delivery"]["requiredDisclosures"]]
    assert "live-focus-restore-failed" in codes
    assert client.close_calls == 1
    console = capsys.readouterr().out
    assert "focusRestore: failed" in console


# ---------------------------------------------------------------------------
# 4. nothing may be stated: no report, no daemon, no document list
# ---------------------------------------------------------------------------


def test_a_missing_report_is_exit_three_without_touching_the_daemon(bridge, capsys, tmp_path):
    out = tmp_path / "empty"
    out.mkdir()
    assert run_cli("--out", str(out)) == 3
    assert FakeBridgeClient.opened == 0, "报告不存在时不得先连 daemon"
    assert not (out / CAPTURE_FILE).exists()
    assert "report.json" in capsys.readouterr().err


def test_a_daemon_that_cannot_be_reached_leaves_the_report_alone(bridge, capsys, tmp_path):
    FakeBridgeClient.client = None
    FakeBridgeClient.fail_open = OSError("synthetic: daemon not listening")
    out = seed_out_dir(tmp_path / "out")
    report_before = (out / "report.json").read_bytes()
    md_before = (out / "report.md").read_bytes()

    assert run_cli("--out", str(out)) == 3

    assert (out / "report.json").read_bytes() == report_before
    assert (out / "report.md").read_bytes() == md_before
    assert not (out / CAPTURE_FILE).exists()
    assert "报告一个字没动" in capsys.readouterr().err


def test_a_bridge_that_cannot_be_prepared_is_exit_three_and_writes_nothing(
    bridge, capsys, monkeypatch, tmp_path
):
    """``_open_cli`` also starts the daemon and writes the CLI token.

    It runs **before** any connection exists, so its failure is the same "nothing
    may be stated" as a failed open: exit 3 with a sentence, never a traceback —
    and the report, the capture and the review summary stay exactly as they were.
    """
    def explode(args):
        raise OSError("synthetic token preparation failure")

    monkeypatch.setattr(cli, "_open_cli", explode)
    out = seed_out_dir(tmp_path / "out")
    before = {
        name: (out / name).read_bytes()
        for name in ("report.json", "report.md", "board-report.md", "review-summary.md")
    }

    assert run_cli("--out", str(out)) == 3

    for name, blob in before.items():
        assert (out / name).read_bytes() == blob, f"{name} 被改写了"
    assert not (out / CAPTURE_FILE).exists()
    assert FakeBridgeClient.opened == 0
    err = capsys.readouterr().err
    assert "synthetic token preparation failure" in err
    assert "报告一个字没动" in err


def test_a_missing_websockets_install_keeps_its_own_exit_message(
    bridge, capsys, monkeypatch, tmp_path
):
    """``SystemExit`` is ``BaseException`` on purpose: the install hint is not swallowed."""
    def no_websockets(args):
        raise SystemExit("boardwise bridge needs the 'websockets' package")

    monkeypatch.setattr(cli, "_open_cli", no_websockets)
    out = seed_out_dir(tmp_path / "out")
    report_before = (out / "report.json").read_bytes()

    with pytest.raises(SystemExit) as raised:
        run_cli("--out", str(out))

    assert "websockets" in str(raised.value)
    assert (out / "report.json").read_bytes() == report_before
    assert not (out / CAPTURE_FILE).exists()


def test_a_failed_doc_list_is_exit_three_and_the_capture_still_lands(bridge, capsys, tmp_path):
    client = bridge(make_listing(), overrides={
        "doc.list": FakeBridgeError("NO_CONNECTOR", "synthetic: no window attached"),
    })
    out = seed_out_dir(tmp_path / "out")

    assert run_cli("--out", str(out)) == 3, capsys.readouterr()

    assert "doc.open" not in client.actions(), "清单读不到就没有可导航的文档"
    assert client.close_calls == 1
    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    assert capture["ok"] is False
    assert [capture["channels"][name]["status"] for name in capture["channels"]] == [
        "missing", "missing", "missing", "missing",
    ]
    evidence = read_report(out)["evidence"]
    assert evidence["channels"]["livePcb"]["status"] == "missing"
    assert evidence["delivery"]["status"] == "partial", "采集失败按真实失败通道合并"
    assert (out / "review-summary.md").read_bytes() == REVIEW_SUMMARY_SENTINEL


# ---------------------------------------------------------------------------
# 5. unusable input: exit 2, and nothing navigated
# ---------------------------------------------------------------------------


def test_broken_report_json_is_exit_two(bridge, capsys, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "report.json").write_text("{not json", encoding="utf-8")

    assert run_cli("--out", str(out)) == 2
    assert FakeBridgeClient.opened == 0


def _unusable_cases():
    """Four ways a report can be structurally unable to take a capture."""

    def no_section(report):
        report.pop("evidence")
        return "evidence"

    def other_schema(report):
        report["evidence"]["schema"] = "boardwise.review-evidence/0"
        return "schema"

    def missing_channel(report):
        report["evidence"]["channels"].pop("livePcb")
        return "livePcb"

    def illegal_status(report):
        report["evidence"]["channels"]["livePcb"]["status"] = "probably-fine"
        return "probably-fine"

    return [
        pytest.param(no_section, id="no-evidence-section"),
        pytest.param(other_schema, id="other-schema"),
        pytest.param(missing_channel, id="missing-channel"),
        pytest.param(illegal_status, id="illegal-status"),
    ]


@pytest.mark.parametrize("mutate", _unusable_cases())
def test_an_unusable_report_is_exit_two_without_preparing_the_bridge(
    bridge, capsys, monkeypatch, tmp_path, mutate
):
    """The structural gate runs **before** ``_open_cli`` — no daemon, no token.

    Every shape the contract names (no section, another schema, a missing
    channel, an illegal status) is checked here with a spy that would fail the
    test the moment the command asked the bridge to prepare itself: an invalid
    report must not cost a daemon start, a token file, or a navigation.
    """
    prepared: list = []

    def open_cli(args):
        prepared.append(args)
        raise AssertionError("预检没通过就调用了 _open_cli（会起 daemon / 写 token）")

    monkeypatch.setattr(cli, "_open_cli", open_cli)
    report = make_report()
    needle = mutate(report)
    out = seed_out_dir(tmp_path / "out", report)
    report_before = (out / "report.json").read_bytes()

    assert run_cli("--out", str(out)) == 2

    assert prepared == [], "无效报告不得让 _open_cli 准备 daemon"
    assert FakeBridgeClient.opened == 0
    assert (out / "report.json").read_bytes() == report_before
    assert not (out / CAPTURE_FILE).exists()
    assert needle in capsys.readouterr().err


def test_a_merge_that_refuses_the_capture_is_exit_two_and_keeps_the_capture(
    bridge, capsys, monkeypatch, tmp_path
):
    def refuse(evidence, capture):
        raise ValueError("synthetic: capture 缺元数据字段：identity")

    monkeypatch.setattr(cli, "merge_live_capture", refuse)
    bridge(make_listing())
    out = seed_out_dir(tmp_path / "out")
    report_before = (out / "report.json").read_bytes()

    assert run_cli("--out", str(out)) == 2

    assert (out / "report.json").read_bytes() == report_before, "拒绝合并时报告不动"
    assert (out / CAPTURE_FILE).is_file(), "原始采集仍要落盘"
    assert FakeBridgeClient.client.close_calls == 1
    assert "报告一个字没动" in capsys.readouterr().err


def test_a_report_that_cannot_be_written_is_exit_two(bridge, capsys, monkeypatch, tmp_path):
    def explode(out_dir, report):
        raise OSError("synthetic: disk full")

    bridge(make_listing())
    out = seed_out_dir(tmp_path / "out")
    monkeypatch.setattr(cli, "_write_checkup_report", explode)

    assert run_cli("--out", str(out)) == 2
    assert "报告写出失败" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 6. coverage: subsets, unknown ids, and the honest N/A
# ---------------------------------------------------------------------------


def test_an_explicit_subset_is_missing_and_exit_one(bridge, capsys, tmp_path):
    bridge(make_listing())
    out = seed_out_dir(tmp_path / "out")

    assert run_cli("--out", str(out), "--page", "p1", "--pcb", "b1") == 1

    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    assert capture["selection"]["schematic"]["coversAll"] is False
    assert capture["selection"]["pcb"]["coversAll"] is True
    assert capture["ok"] is False
    evidence = read_report(out)["evidence"]
    assert evidence["channels"]["liveSchematic"]["status"] == "missing"
    assert evidence["channels"]["livePcb"]["status"] == "ok"


def test_an_unknown_document_uuid_refuses_before_navigation(bridge, capsys, tmp_path):
    client = bridge(make_listing())
    out = seed_out_dir(tmp_path / "out")

    assert run_cli("--out", str(out), "--page", "nope") == 1

    assert client.actions() == ["doc.list"], "未知文档 id 在任何导航前拒绝"
    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    assert capture["selection"]["error"]["code"] == "UNKNOWN_DOCUMENT_UUID"
    assert capture["ok"] is False
    assert read_report(out)["evidence"]["coverage"]["schematicImage"] == "missing"


def test_a_project_without_a_pcb_is_not_applicable_and_may_exit_zero(bridge, capsys, tmp_path):
    bridge(make_listing(pcbs=()))
    out = seed_out_dir(tmp_path / "out")

    assert run_cli("--out", str(out)) == 0, capsys.readouterr()

    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    assert capture["channels"]["livePcb"]["status"] == "not-applicable"
    assert capture["channels"]["pcbImage"]["status"] == "not-applicable"
    assert capture["ok"] is True
    evidence = read_report(out)["evidence"]
    assert evidence["coverage"]["livePcb"] == "not-applicable"
    assert evidence["delivery"]["status"] == "complete"


# ---------------------------------------------------------------------------
# 7. the pure helpers the command is built from
# ---------------------------------------------------------------------------


def test_the_expected_project_comes_from_the_report_never_from_a_document_uuid():
    report = {
        "source": {"project": {"projectUuid": "proj-from-report"}},
        "documents": [{"uuid": "a-page-uuid"}],
    }
    assert cli._review_evidence_expected_project_uuid(report) == "proj-from-report"
    assert cli._review_evidence_expected_project_uuid({}) == ""
    assert cli._review_evidence_expected_project_uuid(
        {"source": {"project": {"name": "no-uuid"}}}
    ) == ""


def test_the_capture_file_is_stable_pretty_json_and_hashes_its_own_bytes(tmp_path):
    capture = {"schema": "boardwise.live-evidence/1", "ok": True, "b": [2, 1]}
    first = cli._write_live_evidence_capture(tmp_path, capture)
    blob = (tmp_path / CAPTURE_FILE).read_bytes()
    assert first["file"] == CAPTURE_FILE
    assert first["bytes"] == len(blob)
    assert first["sha256"] == hashlib.sha256(blob).hexdigest()
    assert blob.decode("utf-8") == (
        json.dumps(capture, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    # Same capture → same bytes (the hash a later reader compares is reproducible).
    assert cli._write_live_evidence_capture(tmp_path, capture) == first


def test_the_exit_code_reads_ok_and_identity_separately():
    def capture(*, ok, verified, listing_failed=False):
        return {
            "ok": ok,
            "identity": {"verifiedAgainstReport": verified},
            "steps": [
                {"action": "doc.list", "status": "failed" if listing_failed else "ok"}
            ],
        }

    assert cli._review_evidence_exit_code(capture(ok=True, verified=True)) == 0
    assert cli._review_evidence_exit_code(capture(ok=True, verified=False)) == 1
    assert cli._review_evidence_exit_code(capture(ok=False, verified=True)) == 1
    assert cli._review_evidence_exit_code(capture(ok=False, verified=False)) == 1
    assert cli._review_evidence_exit_code(
        capture(ok=False, verified=False, listing_failed=True)
    ) == 3


# ---------------------------------------------------------------------------
# 8. 537C3b3b: the live half of crossView.candidateMappings
# ---------------------------------------------------------------------------
#
# 537C3b3a built the pure `enrich_cross_view_live_candidates`; nothing called it,
# so a report kept whatever live half an older run had written while the new
# capture said something else. The command now owns that call, under four rules:
#
# 1. **strip first, always** — every board/crossView loses its old live half
#    unless *this* run verified the identity and read a live schematic netlist;
# 2. **no netlist is read unless it is needed** — a report with no
#    `candidateMappings` may keep a non-JSON netlist (the pre-537C3b3b suites do);
# 3. **the artifact must prove itself** — `kind=netlist`, `channel=liveSchematic`,
#    exactly one, a bare file name, and the bytes/sha256 it recorded;
# 4. **a bad live netlist is exit 2 and no report moves** — the capture stays for
#    diagnosis, the four report files stay byte-identical.

LIVE_NETLIST_DOC = {
    "version": "2.0.0",
    "components": {
        "g-u9": {
            "props": {"Designator": "U9", "Value": "MCU"},
            "pinInfoMap": {
                # The original session's measured mismatch: the archive mapping
                # names U9.11 while the live same-named net carries U9.33 / PB11.
                "33": {"name": "PB11", "number": "33", "net": "FOC_EN"},
                "11": {"name": "PA1", "number": "11", "net": "OTHER"},
            },
        },
        "g-r1": {
            "props": {"Designator": "R1", "Value": "1k"},
            "pinInfoMap": {
                "1": {"name": "1", "number": "1", "net": "FOC_EN"},
                "2": {"name": "2", "number": "2", "net": ""},
            },
        },
    },
}
LIVE_NETLIST_TEXT = json.dumps(LIVE_NETLIST_DOC, ensure_ascii=False)


def candidate_mapping(**overrides) -> dict:
    mapping = {
        "pcbNet": "FOC_EN",
        "pcbPin": "U9.11",
        "pcbMembers": ["U9.11", "R1.1"],
        "schematicCandidates": ["U9.11", "R1.1"],
        "evidence": {
            "pcb": "archivePcb",
            "schematic": "archiveSchematic",
            "basis": "same-net-name",
        },
    }
    mapping.update(overrides)
    return mapping


def cross_view(*, mappings=None, checked=True, **overrides) -> dict:
    section = {
        "checked": checked,
        "minPins": 2,
        "lonely": [{"net": "FOC_EN", "pin": "U9.11"}],
    }
    if checked:
        section["status"] = "suspected"
        section["candidateMappings"] = (
            [candidate_mapping()] if mappings is None else list(mappings)
        )
    section.update(overrides)
    return section


def report_with_boards(*sections, project_uuid=PROJECT) -> dict:
    report = make_report(project_uuid=project_uuid)
    report["pcb_review"] = {
        "available": True,
        "boards": [
            {"title": f"B{index + 1}", "components": 2, "copperLayers": 2,
             "crossView": section}
            for index, section in enumerate(sections)
        ],
    }
    return report


def synthetic_capture(*, verified=True, live_status="ok", artifacts=None) -> dict:
    """A collector-shaped capture, for the paths a fake client cannot stage."""
    ok = verified and live_status == "ok"
    return {
        "schema": LIVE_EVIDENCE_SCHEMA,
        "ok": ok,
        "executor": "liveevidence/1",
        "identity": {
            "expectedProjectUuid": PROJECT,
            "verifiedAgainstReport": verified,
            "ok": verified,
        },
        "selection": {"schematic": {"coversAll": True}, "pcb": {"coversAll": True}},
        "channels": {
            name: {
                "status": live_status if name == "liveSchematic" else "ok",
                "source": "liveSchematic",
                "detail": "",
                "artifacts": [],
                "errors": [],
                "steps": [],
            }
            for name in LIVE_CHANNEL_ORDER
        },
        "steps": [{"action": "doc.list", "status": "ok"}],
        "artifacts": list(artifacts or []),
        "focusRestore": {
            "ok": True,
            "attempted": True,
            "status": "restored",
            "originalUuid": "p2",
        },
    }


@pytest.fixture
def patch_capture(monkeypatch):
    """Replace the collector with a hand-built capture (the CLI imports it late)."""
    import boardwise.engines.liveevidence as liveevidence

    def install(capture: dict) -> None:
        async def collect(*args, **kwargs):
            return capture

        monkeypatch.setattr(liveevidence, "collect_live_evidence", collect)

    return install


def netlist_artifact(
    out_dir: Path,
    *,
    text: str = LIVE_NETLIST_TEXT,
    blob: bytes | None = None,
    name: str = "live-netlist-synthetic.txt",
    write: bool = True,
    **overrides,
) -> dict:
    """One collector-shaped netlist artifact over a real file in ``out_dir``."""
    data = blob if blob is not None else text.encode("utf-8")
    path = out_dir / name
    if write:
        path.write_bytes(data)
    artifact = {
        "channel": "liveSchematic",
        "documentUuid": "p1",
        "kind": "netlist",
        "page": "PWR",
        "file": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "text/plain",
        "netlistType": "EasyEDA",
    }
    artifact.update(overrides)
    return artifact


def four_reports(out_dir: Path) -> dict:
    return {
        name: (out_dir / name).read_bytes()
        for name in ("report.json", "report.md", "board-report.md", "review-summary.md")
    }


def mapping_of(out_dir: Path, index: int = 0) -> dict:
    return read_report(out_dir)["pcb_review"]["boards"][index][
        "crossView"
    ]["candidateMappings"][0]


def test_verified_live_netlist_fills_the_live_half_of_every_board(bridge, capsys, tmp_path):
    """The live members are the live net's — not the archive refs renamed."""
    client = bridge(make_listing(), overrides={
        "sch.netlist": {"type": "EasyEDA", "text": LIVE_NETLIST_TEXT},
    })
    report = report_with_boards(cross_view(), cross_view())
    out = seed_out_dir(tmp_path / "out", report)
    before = read_report(out)
    archive_before = before["pcb_review"]["boards"][0]["crossView"]["candidateMappings"][0]

    assert run_cli("--out", str(out)) == 0, capsys.readouterr()

    written = read_report(out)
    boards = written["pcb_review"]["boards"]
    assert len(boards) == 2, "每个 board 各自处理"
    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    netlists = [row for row in capture["artifacts"] if row.get("kind") == "netlist"]
    assert len(netlists) == 1, "整次采集只有一份工程级网表"
    artifact = netlists[0]

    for board in boards:
        cross = board["crossView"]
        assert cross["status"] == "suspected", "实时读数不把 crossView 变成 confirmed"
        assert cross["lonely"] == [{"net": "FOC_EN", "pin": "U9.11"}]
        mapping = cross["candidateMappings"][0]
        assert mapping["liveSchematicCandidates"] == [
            {"pin": "R1.1", "pinName": "1"},
            {"pin": "U9.33", "pinName": "PB11"},
        ], "live 网成员是 U9.33/PB11，不是归档的 U9.11"
        evidence = mapping["liveCandidateEvidence"]
        assert evidence["status"] == "ok"
        assert evidence["pcb"] == "archivePcb"
        assert evidence["schematic"] == "liveSchematic"
        assert evidence["basis"] == "same-net-name"
        assert evidence["netlist"]["file"] == artifact["file"]
        assert evidence["netlist"]["sha256"] == artifact["sha256"]
        # The archive half is untouched, field for field.
        for key in ("pcbPin", "pcbNet", "pcbMembers", "schematicCandidates", "evidence"):
            assert mapping[key] == archive_before[key], key

    # The artifact named is the real file with the real hash.
    data = (out / artifact["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == artifact["sha256"]

    # captureFile still names the raw capture — enrichment does not rewrite it.
    blob = (out / CAPTURE_FILE).read_bytes()
    assert written["evidence"]["liveCapture"]["captureFile"] == {
        "file": CAPTURE_FILE,
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
    }

    # Board-level semantics unchanged.
    for key in ("completion", "summary", "conclusion", "board_report", "schema"):
        assert written[key] == before[key], f"{key} 被本命令改写了"
    assert (out / "review-summary.md").read_bytes() == REVIEW_SUMMARY_SENTINEL
    assert client.close_calls == 1

    console = capsys.readouterr().out
    assert "按实时网表补名" in console
    assert "板子通过" not in console and "已确认" not in console


def test_an_unverified_identity_strips_the_old_live_half_without_parsing(
    bridge, capsys, tmp_path, patch_capture
):
    bridge(make_listing())
    stale = candidate_mapping()
    stale["liveSchematicCandidates"] = [{"pin": "U9.11", "pinName": "PA9"}]
    stale["liveCandidateEvidence"] = {
        "status": "ok",
        "pcb": "archivePcb",
        "schematic": "liveSchematic",
        "basis": "same-net-name",
        "netlist": {"file": "old.txt", "sha256": "x" * 64},
    }
    out = seed_out_dir(tmp_path / "out", report_with_boards(cross_view(mappings=[stale])))
    # A netlist whose bytes do not match its hash: reading it would be exit 2.
    artifact = netlist_artifact(out, text="NOT A NETLIST", sha256="0" * 64)
    patch_capture(synthetic_capture(verified=False, live_status="missing", artifacts=[artifact]))

    assert run_cli("--out", str(out)) == 1, capsys.readouterr()

    mapping = mapping_of(out)
    assert "liveSchematicCandidates" not in mapping
    assert "liveCandidateEvidence" not in mapping
    assert mapping["pcbPin"] == "U9.11"
    assert mapping["pcbNet"] == "FOC_EN"
    assert read_report(out)["pcb_review"]["boards"][0]["crossView"]["status"] == "suspected"
    captured = capsys.readouterr()
    assert "实时候选处理失败" not in captured.err
    line = next(row for row in captured.out.splitlines() if "live candidates:" in row)
    assert "旧 live 半边已剥离" in line
    assert "身份未核实" not in line, "剥离原因不许在 console 里凭空编 identity/通道状态"
    assert "不可用" not in line


def test_a_failed_live_schematic_channel_strips_the_old_live_half(
    bridge, capsys, tmp_path, patch_capture
):
    bridge(make_listing())
    stale = candidate_mapping(liveSchematicCandidates=[{"pin": "U9.33", "pinName": "PB11"}],
                              liveCandidateEvidence={"status": "ok"})
    out = seed_out_dir(tmp_path / "out", report_with_boards(cross_view(mappings=[stale])))
    patch_capture(synthetic_capture(verified=True, live_status="failed"))

    assert run_cli("--out", str(out)) == 1, capsys.readouterr()

    mapping = mapping_of(out)
    assert "liveSchematicCandidates" not in mapping
    assert "liveCandidateEvidence" not in mapping
    assert "实时候选处理失败" not in capsys.readouterr().err


def test_a_board_without_candidate_mappings_never_parses_the_netlist(bridge, capsys, tmp_path):
    """The fake client's netlist is not JSON — the old suites must keep passing."""
    bridge(make_listing())
    section = {"checked": True, "minPins": 2, "lonely": [{"net": "FOC_EN", "pin": "U9.11"}]}
    out = seed_out_dir(tmp_path / "out", report_with_boards(section))

    assert run_cli("--out", str(out)) == 0, capsys.readouterr()

    written = read_report(out)
    assert written["pcb_review"]["boards"][0]["crossView"] == section, "没映射就没得补"
    capture = json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))
    assert any(row.get("kind") == "netlist" for row in capture["artifacts"]), "网表照常留档"
    line = next(
        row for row in capsys.readouterr().out.splitlines() if "live candidates:" in row
    )
    assert "没有需要补名" in line
    assert "身份未核实" not in line, "verified+live ok 的 run 不许在 console 谎称身份未核实"
    assert "不可用" not in line


def test_a_repeated_designator_gives_no_partial_live_candidates(
    bridge, capsys, tmp_path, patch_capture
):
    bridge(make_listing())
    doc = {
        "components": {
            "g-a": {
                "props": {"Designator": "U9"},
                "pinInfoMap": {"33": {"name": "PB11", "number": "33", "net": "FOC_EN"}},
            },
            "g-b": {
                "props": {"Designator": "U9"},
                "pinInfoMap": {"40": {"name": "PA0", "number": "40", "net": "FOC_EN"}},
            },
        }
    }
    out = seed_out_dir(tmp_path / "out", report_with_boards(cross_view()))
    patch_capture(synthetic_capture(artifacts=[
        netlist_artifact(out, text=json.dumps(doc)),
    ]))

    assert run_cli("--out", str(out)) == 0, capsys.readouterr()

    mapping = mapping_of(out)
    assert mapping["liveSchematicCandidates"] == [], "歧义位号不给部分候选"
    evidence = mapping["liveCandidateEvidence"]
    assert evidence["status"] == "unavailable"
    assert evidence["ambiguousDesignators"] == ["U9"]
    # The reading is still only a reading: the capture's own ok is untouched.
    assert json.loads((out / CAPTURE_FILE).read_text(encoding="utf-8"))["ok"] is True


def test_a_second_unverified_run_removes_the_live_half_the_first_run_added(
    bridge, capsys, tmp_path
):
    bridge(make_listing(), overrides={
        "sch.netlist": {"type": "EasyEDA", "text": LIVE_NETLIST_TEXT},
    })
    out = seed_out_dir(tmp_path / "out", report_with_boards(cross_view()))

    assert run_cli("--out", str(out)) == 0, capsys.readouterr()
    assert "liveSchematicCandidates" in mapping_of(out)

    # Second run: the focused project is somebody else's → identity unverified,
    # liveSchematic missing → run 1's live half may not survive into this report.
    bridge(make_listing(project_uuid="proj-someone-else"))
    assert run_cli("--out", str(out)) == 1, capsys.readouterr()

    mapping = mapping_of(out)
    assert "liveSchematicCandidates" not in mapping
    assert "liveCandidateEvidence" not in mapping
    assert mapping["pcbPin"] == "U9.11"
    blob = (out / CAPTURE_FILE).read_bytes()
    written = read_report(out)
    assert written["evidence"]["liveCapture"]["captureFile"]["sha256"] == (
        hashlib.sha256(blob).hexdigest()
    )


def _candidate_failure_cases():
    """Every way the live netlist can fail to prove itself."""

    def missing_file(out):
        return [netlist_artifact(out, write=False)], "读不出来"

    def hash_mismatch(out):
        return [netlist_artifact(out, sha256="0" * 64)], "sha256"

    def bytes_mismatch(out):
        artifact = netlist_artifact(out)
        artifact["bytes"] = int(artifact["bytes"]) + 1
        return [artifact], "字节数"

    def no_bytes_record(out):
        artifact = netlist_artifact(out)
        artifact.pop("bytes")
        return [artifact], "bytes"

    def not_utf8(out):
        return [netlist_artifact(out, blob=b"\xff\xfe\x00\x01")], "UTF-8"

    def parse_failure(out):
        return [netlist_artifact(out, text="NETLIST SYNTHETIC\n")], "解析"

    def no_artifact(out):
        return [], "恰好一条"

    def two_artifacts(out):
        first = netlist_artifact(out, name="live-netlist-a.txt")
        second = netlist_artifact(out, name="live-netlist-b.txt")
        return [first, second], "恰好一条"

    def directory_escape(out):
        blob = LIVE_NETLIST_TEXT.encode("utf-8")
        outside = out.parent / "outside-netlist.txt"
        outside.write_bytes(blob)
        artifact = {
            "channel": "liveSchematic",
            "kind": "netlist",
            "file": "../outside-netlist.txt",
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        return [artifact], "单文件名"

    return [
        pytest.param(missing_file, id="missing-file"),
        pytest.param(hash_mismatch, id="hash-mismatch"),
        pytest.param(bytes_mismatch, id="bytes-mismatch"),
        pytest.param(no_bytes_record, id="no-bytes-record"),
        pytest.param(not_utf8, id="not-utf8"),
        pytest.param(parse_failure, id="parse-failure"),
        pytest.param(no_artifact, id="no-artifact"),
        pytest.param(two_artifacts, id="two-artifacts"),
        pytest.param(directory_escape, id="directory-escape"),
    ]


@pytest.mark.parametrize("case", _candidate_failure_cases())
def test_a_bad_live_netlist_is_exit_two_and_no_report_moves(
    bridge, capsys, tmp_path, patch_capture, case
):
    client = bridge(make_listing())
    out = seed_out_dir(tmp_path / "out", report_with_boards(cross_view()))
    artifacts, needle = case(out)
    patch_capture(synthetic_capture(artifacts=artifacts))
    before = four_reports(out)

    assert run_cli("--out", str(out)) == 2

    assert four_reports(out) == before, "四份报告必须逐字节不变"
    assert (out / CAPTURE_FILE).is_file(), "原始采集留作诊断"
    err = capsys.readouterr().err
    assert "实时候选处理失败" in err
    assert str(out / CAPTURE_FILE) in err
    assert needle in err
    assert client.close_calls == 1


def test_a_failed_enrichment_does_not_merge_evidence_into_the_caller_report(
    bridge, capsys, monkeypatch, tmp_path
):
    """The evidence merge is assigned only **after** the candidates succeed.

    Otherwise a run that dies in the live-candidate step would hand its caller a
    report whose evidence section already changed — half an update, even though
    no file moved.
    """
    def boom(report, *, capture, out_dir):
        raise ValueError("synthetic: bad live netlist")

    monkeypatch.setattr(cli, "_enrich_report_cross_view_live_candidates", boom)
    client = bridge(make_listing())
    report = report_with_boards(cross_view())
    before = copy.deepcopy(report)
    out = tmp_path / "out"
    out.mkdir()

    code = asyncio.run(cli._review_evidence_with_client(
        client, out_dir=out, report=report, route_kwargs={},
        page_uuids=None, pcb_uuids=None,
    ))

    assert code == 2
    assert report == before, "候选 helper 失败时 report（含 evidence）必须原样"
    assert "实时候选处理失败" in capsys.readouterr().err
    assert client.close_calls == 0, "client 生命周期由调用方持有（run_in_cli 的 finally）"

"""`boardwise doctor` (012v2 §九) and the `ping` version it compares against.

Doctor exists for the state this project keeps being found in: a daemon that is
not running, an extension that is not loaded, an editor that is older than the
APIs the harness leans on. The check that matters is therefore the *failing*
one — every branch below is exercised as data (`run_doctor` is a pure function of
a `DoctorProbe`), so no test here starts a daemon or needs an editor.

The CLI-level cases use two fakes, and they are deliberate:

- **nothing listening** is the real path — a free port, the real transport, a
  real `OSError` — because "does not crash when disconnected" is the promise;
- **a daemon that answers** is a stub `BridgeClient`, because a doctor test that
  started a daemon would make the suite slower and would still not have an
  editor to point at.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise import __version__
from boardwise.bridge.protocol import BridgeError, ErrorCodes
from boardwise.cli import (
    DOCTOR_PROBE_CHECKS,
    EDITOR_API_FLOOR,
    DoctorProbe,
    _cmd_doctor,
    _repo_connector_version,
    build_parser,
    run_doctor,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: The five methods as `sys.probe` would report them when everything is present.
ALL_PRESENT = {
    namespace: {"present": True, "kind": "object", "checked": len(members),
                "missing": 0, "status": {member: "function" for member in members}}
    for namespace, members in DOCTOR_PROBE_CHECKS.items()
}


def healthy_probe(**overrides) -> DoctorProbe:
    """A probe of a working installation, with fields overridable one at a time."""
    values = {
        "port": 61190,
        "daemon_version": "0.1.0",
        "connector_version": "0.4.5",
        "editor_version": "3.2.186",
        "local_connector_version": "0.4.5",
        "ping": {"pong": True, "version": "0.1.0", "connector": True, "pairedFingerprint": "ab12cd34"},
        "probe": {"version": "3.2.186", "connector": "0.4.5", "topLevel": [], "checks": ALL_PRESENT},
        "documents": {
            "documents": [{"uuid": "page-1", "name": "P1", "type": "page", "active": True}],
            "projects": [{
                "projectUuid": "proj-1-uuid", "name": "/board", "friendlyName": "毕设板",
                "focused": True, "opened": "yes",
                "schematics": [{"uuid": "page-1", "name": "P1", "type": "page"}],
                "pcbs": [{"uuid": "pcb-1", "name": "PCB1", "type": "pcb"}],
            }],
            "active": {"uuid": "page-1", "type": "page", "tabId": "tab-1"},
        },
    }
    values.update(overrides)
    return DoctorProbe(**values)


def check(checks, name):
    [found] = [entry for entry in checks if entry.name == name]
    return found


def test_a_working_installation_is_all_green():
    checks = run_doctor(healthy_probe())
    assert [(entry.name, entry.ok) for entry in checks] == [
        (entry.name, True) for entry in checks
    ], [(entry.name, entry.ok, entry.detail) for entry in checks]
    assert all(entry.fix == "" for entry in checks), "a green line must not carry a fix"
    assert [entry.name for entry in checks] == [
        "daemon", "connector", "methods", "editor-version",
        "daemon-version", "connector-version", "project",
    ]


def test_nothing_listening_is_reported_per_line_with_a_fix():
    checks = run_doctor(DoctorProbe(
        port=61190, daemon_version="0.1.0", local_connector_version="0.4.5",
        ping_error="connection refused",
    ))
    assert [entry.ok for entry in checks] == [False] * 7
    assert all(entry.fix for entry in checks), "every failing line must say what to do"
    assert "connection refused" in check(checks, "daemon").detail
    assert "61190" in check(checks, "daemon").detail
    # A check that could not be made says so instead of pretending it failed.
    assert check(checks, "connector").detail.startswith("未验证")
    assert check(checks, "methods").detail.startswith("未验证")


def test_no_connector_names_the_extension_as_the_thing_to_fix():
    checks = run_doctor(healthy_probe(
        ping={"pong": True, "version": "0.1.0", "connector": False, "pairedFingerprint": None},
        probe=None, probe_error="[NO_CONNECTOR] no connector is connected",
        documents=None, documents_error="[NO_CONNECTOR] no connector is connected",
        connector_version="", editor_version="",
    ))
    assert check(checks, "daemon").ok is True
    assert check(checks, "daemon-version").ok is True
    for name in ("connector", "methods", "editor-version", "connector-version", "project"):
        entry = check(checks, name)
        assert entry.ok is False, name
        assert "立创 EDA Pro" in entry.fix, name
    assert "no connector is connected" in check(checks, "methods").detail


def test_an_editor_below_the_api_floor_is_called_out_with_the_version():
    checks = run_doctor(healthy_probe(
        editor_version="3.2.180",
        probe={"version": "3.2.180", "connector": "0.4.5", "checks": ALL_PRESENT},
    ))
    entry = check(checks, "editor-version")
    assert entry.ok is False
    assert "3.2.180" in entry.detail
    assert "3.2.183" in entry.fix
    # 3.2.183 itself is the floor, not the line above it.
    floor = run_doctor(healthy_probe(
        editor_version="3.2.183",
        probe={"version": "3.2.183", "connector": "0.4.5", "checks": ALL_PRESENT},
    ))
    assert check(floor, "editor-version").ok is True


def test_a_missing_method_is_named_not_counted():
    checks = run_doctor(healthy_probe(probe={
        "version": "3.2.186", "connector": "0.4.5",
        "checks": {
            **ALL_PRESENT,
            "dmt_EditorControl": {
                "present": True, "kind": "object", "checked": 2, "missing": 1,
                "status": {"openDocument": "function", "generateIndicatorMarkers": "undefined"},
                "notes": {"generateIndicatorMarkers": "declared ADD since EDA v3.2.183 on this host"},
            },
        },
    }))
    entry = check(checks, "methods")
    assert entry.ok is False
    assert "dmt_EditorControl.generateIndicatorMarkers=undefined" in entry.detail
    assert "sys.probe" in entry.fix


def test_a_probe_that_answers_but_loses_a_namespace_is_not_green():
    # The whole namespace absent is the other failing shape, and it must not read
    # as "0 of 1 present" and pass.
    checks = run_doctor(healthy_probe(probe={
        "version": "3.2.186", "connector": "0.4.5",
        "checks": {"sch_PrimitiveComponent": {"present": False, "kind": "undefined"}},
    }))
    entry = check(checks, "methods")
    assert entry.ok is False
    assert "sch_PrimitiveComponent.getAll=未报告" in entry.detail


def test_a_stale_daemon_is_diagnosed_as_a_restart():
    checks = run_doctor(healthy_probe(
        daemon_version="0.1.0",
        ping={"pong": True, "version": "0.0.9", "connector": True, "pairedFingerprint": "ab12cd34"},
    ))
    entry = check(checks, "daemon-version")
    assert entry.ok is False
    assert "0.0.9" in entry.detail and "0.1.0" in entry.detail
    assert "重启 daemon" in entry.fix


def test_a_daemon_that_predates_the_version_field_is_not_silently_equal():
    ping = {"pong": True, "connector": True, "pairedFingerprint": "ab12cd34"}
    checks = run_doctor(healthy_probe(ping=ping))
    entry = check(checks, "daemon-version")
    assert entry.ok is False
    assert "没有报告自己的版本" in entry.detail


def test_an_old_connector_bundle_is_diagnosed_as_update_connector():
    checks = run_doctor(healthy_probe(connector_version="0.4.4"))
    entry = check(checks, "connector-version")
    assert entry.ok is False
    assert "0.4.4" in entry.detail and "0.4.5" in entry.detail
    assert "update-connector" in entry.fix


def test_the_connector_version_check_skips_when_there_is_no_repo_manifest():
    checks = run_doctor(healthy_probe(local_connector_version=""))
    entry = check(checks, "connector-version")
    assert entry.ok is True and entry.skipped is True
    assert "跳过比对" in entry.detail


def test_no_open_project_is_reported_as_no_focus():
    checks = run_doctor(healthy_probe(documents={"documents": [], "projects": [], "active": {}}))
    entry = check(checks, "project")
    assert entry.ok is False
    assert "焦点工程" in entry.detail
    assert "打开" in entry.fix


def _focused_project_documents(**overrides):
    """A `doc.list` payload: a readable focused project, no usable active document."""
    documents = {
        "documents": [{"uuid": "page-1", "name": "P1", "type": "page", "active": False}],
        "projects": [{"projectUuid": "proj-1", "friendlyName": "毕设板", "focused": True,
                      "schematics": [{"uuid": "page-1"}], "pcbs": []}],
        "active": None,
    }
    documents.update(overrides)
    return documents


def test_the_normalised_placeholder_reading_does_not_hide_the_focused_project():
    # The machine reading is `active: {"uuid": "0"}` while a project is focused;
    # since connector 0.4.6 it arrives here normalised — `active: null` with the
    # raw reading kept in `notes`. The project is still readable, so the line
    # stays green and says what the reading is worth instead of turning into a
    # second mystery.
    checks = run_doctor(healthy_probe(documents=_focused_project_documents(
        notes=['dmt_SelectControl.getCurrentDocumentInfo: reported uuid "0" for the active '
               'document — the host\'s placeholder for "nothing is focused"; reported as no '
               'active document'],
    )))
    entry = check(checks, "project")
    assert entry.ok is True
    assert "毕设板" in entry.detail
    assert "uuid=0" in entry.detail
    assert "没有焦点文档" in entry.detail


def test_a_connector_older_than_0_4_6_still_reads_as_no_focus():
    # The editor may still be running the previous build — that is why doctor
    # compares versions at all — and that build reports the placeholder in
    # `active` instead of normalising it. Same verdict, same wording.
    checks = run_doctor(healthy_probe(documents=_focused_project_documents(
        active={"uuid": "0", "type": "blank", "tabId": "0"},
    )))
    entry = check(checks, "project")
    assert entry.ok is True
    assert "毕设板" in entry.detail
    assert "uuid=0" in entry.detail


def test_no_focused_document_is_said_plainly():
    # `active: null` with no note is simply "nothing is focused" — doctor must
    # not borrow the placeholder story for it, or every idle editor would read
    # as a host bug.
    checks = run_doctor(healthy_probe(documents=_focused_project_documents()))
    entry = check(checks, "project")
    assert entry.ok is True
    assert "无（编辑器里没有焦点文档）" in entry.detail
    assert "uuid=0" not in entry.detail


def test_the_probe_checks_and_the_generated_api_table_agree():
    """Every spot-checked member must exist in the offline declaration table.

    `connector/src/api-names.ts` is generated from the type package and is what
    `sys.probe` `checks: true` verifies. A doctor check naming a member that is
    not in it would read `undefined` on every host forever — a red line nobody
    can fix, which is exactly the kind of "always failing check" that gets
    ignored.
    """
    source = (ROOT / "connector" / "src" / "api-names.ts").read_text(encoding="utf-8")
    for namespace, members in DOCTOR_PROBE_CHECKS.items():
        assert f"  {namespace}: [" in source, f"{namespace} is not in the generated table"
        block = source.split(f"  {namespace}: [", 1)[1].split("],", 1)[0]
        for member in members:
            assert f"'{member}'" in block, f"{namespace}.{member} is not declared in api-names.ts"


def test_the_version_floor_is_the_one_the_task_book_names():
    assert EDITOR_API_FLOOR == (3, 2, 183)


# --------------------------------------------------------------------------
# the CLI itself
# --------------------------------------------------------------------------


def _env(home: Path, port: int) -> dict:
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["BOARDWISE_HOME"] = str(home)
    env["BOARDWISE_PORT"] = str(port)
    return env


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_doctor_without_a_daemon_exits_1_with_fixes(tmp_path):
    port = _free_port()
    result = subprocess.run(
        [sys.executable, "-m", "boardwise.cli", "doctor", "--port", str(port),
         "--json", str(tmp_path / "doctor.json")],
        capture_output=True, text=True, encoding="utf-8",
        env=_env(tmp_path, port), timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout.count("FAIL") == 7
    assert "boardwise bridge start" in result.stdout
    assert "0/7" in result.stdout
    payload = json.loads((tmp_path / "doctor.json").read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["port"] == port
    assert [entry["name"] for entry in payload["checks"]] == [
        "daemon", "connector", "methods", "editor-version",
        "daemon-version", "connector-version", "project",
    ]
    assert payload["versions"]["daemon"] == __version__
    assert payload["versions"]["connectorRepo"] == json.loads(
        (ROOT / "connector" / "extension.json").read_text(encoding="utf-8")
    )["version"]


class _FakeDaemon:
    """A daemon that answers the three calls doctor makes, and nothing else."""

    def __init__(self, *, ping, probe=None, documents=None, errors=None):
        self.ping = ping
        self.probe = probe
        self.documents = documents
        self.errors = errors or {}
        self.calls = []

    async def call(self, action, params=None):
        self.calls.append(action)
        if action in self.errors:
            raise BridgeError(self.errors[action], f"{action} failed in the stub")
        if action == "ping":
            return self.ping
        if action == "sys.probe":
            assert "checks" in params, "doctor must ask for specific methods"
            assert set(params["checks"]) == set(DOCTOR_PROBE_CHECKS)
            return self.probe
        if action == "doc.list":
            return self.documents
        raise AssertionError(f"doctor called {action}, which it should not need")

    async def close(self):
        pass


@pytest.fixture
def fake_daemon(monkeypatch):
    """Patch `_open_cli` so the CLI runs against a stub without a socket."""
    from boardwise.bridge import protocol

    def install(daemon):
        class Client:
            @classmethod
            async def open(cls, uri, token, role, client=""):
                assert role == "cli"
                return daemon

        monkeypatch.setattr(
            "boardwise.cli._open_cli",
            lambda args: (Client, protocol.BridgeError, 61190, "token"),
        )
        return daemon

    return install


def _doctor_args(tmp_path=None, json_path=None):
    args = build_parser().parse_args(
        ["doctor"] + (["--json", str(json_path)] if json_path else [])
    )
    return args


def test_the_cli_gathers_the_three_payloads_and_goes_green(fake_daemon, capsys, tmp_path):
    # The connector version is read from the repo, not written as a literal:
    # `_cmd_doctor` compares what the editor runs against `connector/extension.json`
    # (that is the check), so a hardcoded fixture version turns this green case
    # red on every release — the 0.4.5 → 0.4.6 bump did exactly that.
    daemon = fake_daemon(_FakeDaemon(
        ping={"pong": True, "version": __version__, "connector": True, "pairedFingerprint": "ab12cd34"},
        probe={"version": "3.2.186", "connector": _repo_connector_version(), "checks": ALL_PRESENT},
        documents={
            "projects": [{"projectUuid": "proj-1", "friendlyName": "毕设板", "focused": True,
                          "schematics": [], "pcbs": []}],
            "active": {"uuid": "page-1", "type": "page"},
        },
    ))
    code = _cmd_doctor(_doctor_args(json_path=tmp_path / "d.json"))
    out = capsys.readouterr().out
    assert code == 0
    assert daemon.calls == ["ping", "sys.probe", "doc.list"]
    assert out.count("PASS") == 7
    assert "毕设板" in out
    assert json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))["ok"] is True


def test_a_daemon_that_answers_without_a_connector_still_reports_every_line(fake_daemon, capsys):
    daemon = fake_daemon(_FakeDaemon(
        ping={"pong": True, "version": __version__, "connector": False, "pairedFingerprint": None},
    ))
    code = _cmd_doctor(_doctor_args())
    out = capsys.readouterr().out
    assert code == 1
    # Nothing beyond ping is attempted when there is no connector to ask — and
    # the lines that follow say "未验证" rather than inventing a verdict.
    assert daemon.calls == ["ping"]
    # Required reading: from the repo, `connector/extension.json` exists, so the
    # connector-version comparison is one of the five failing lines rather than a
    # skip. The two green lines are the daemon (it answered) and the daemon
    # version (this CLI and the stub agree).
    assert out.count("FAIL") == 5
    assert out.count("PASS") == 2
    assert out.count("SKIP") == 0
    assert "未验证" in out


def test_a_connector_that_answers_the_probe_with_an_error_is_not_a_crash(fake_daemon, capsys):
    daemon = fake_daemon(_FakeDaemon(
        ping={"pong": True, "version": __version__, "connector": True, "pairedFingerprint": "ab12cd34"},
        errors={"sys.probe": "CONNECTOR_ERROR", "doc.list": "TIMEOUT"},
    ))
    code = _cmd_doctor(_doctor_args())
    out = capsys.readouterr().out
    assert code == 1
    assert "PASS" in out and "FAIL" in out
    assert "CONNECTOR_ERROR" in out and "TIMEOUT" in out
    assert "Traceback" not in out


def test_doctor_never_needs_an_action_that_is_not_read_only(fake_daemon):
    # A health check that writes would be a trap; the catalogue assertion is
    # cheap and the daemon stub above asserts the action names as well.
    from boardwise.bridge.protocol import action_spec

    for action in ("ping", "sys.probe", "doc.list"):
        spec = action_spec(action)
        assert spec is not None
        assert spec.risk == "read", action
    assert ErrorCodes.NO_CONNECTOR == "NO_CONNECTOR"

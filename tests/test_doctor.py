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
    EDITOR_INSTALL_ENV,
    DoctorProbe,
    _cmd_doctor,
    _editor_version_key,
    _repo_connector_version,
    build_parser,
    run_doctor,
    scan_editor_install,
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
    """A probe of a working installation, with fields overridable one at a time.

    The two offline fields (`offline_editor_*`) stay empty here: this fixture is
    about the bridge path, and each case of the offline pre-check has its own
    test below. A fixture that claimed an install tree would also be a second
    input to the version line, so the floor cases would no longer be testing what
    they say they test.
    """
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


@pytest.fixture(autouse=True)
def _no_real_editor(monkeypatch, tmp_path_factory):
    """The offline pre-check must never read *this* machine's editor.

    `_cmd_doctor` scans the real disk, and two tests below run the real CLI — so
    without this pin their line counts would depend on whether the developer
    happens to have 立创 EDA Pro installed and at which version. Pinning the
    search to an empty directory makes every case the test's own; the tests that
    want a tree to be found pin the variable again, to a tree they built.
    """
    monkeypatch.setenv(EDITOR_INSTALL_ENV, str(tmp_path_factory.mktemp("no-editor")))


def install_tree(root: Path, version: str, name: str = "lceda-pro") -> Path:
    """A directory shaped like an editor install tree, manifest included."""
    tree = root / name
    (tree / "resources" / "app").mkdir(parents=True, exist_ok=True)
    (tree / "resources" / "app" / "package.json").write_text(
        json.dumps({"name": "client.pro.lceda.cn", "version": version}), encoding="utf-8"
    )
    return tree


def test_a_working_installation_is_all_green():
    checks = run_doctor(healthy_probe())
    assert [(entry.name, entry.ok) for entry in checks] == [
        (entry.name, True) for entry in checks
    ], [(entry.name, entry.ok, entry.detail) for entry in checks]
    assert all(entry.fix == "" for entry in checks), "a green line must not carry a fix"
    # The eight lines, the offline pre-check first (issue #3). This probe says
    # nothing about an install tree, so that line is a skip rather than a claim.
    assert [entry.name for entry in checks] == [
        "editor-install", "daemon", "connector", "methods", "editor-version",
        "daemon-version", "connector-version", "project",
    ]
    assert check(checks, "editor-install").skipped is True


def test_nothing_listening_is_reported_per_line_with_a_fix():
    checks = run_doctor(DoctorProbe(
        port=61190, daemon_version="0.1.0", local_connector_version="0.4.5",
        ping_error="connection refused",
    ))
    # Seven red lines; the offline pre-check has no install to read here (no
    # page for it was gathered), so it skips instead of going red.
    assert [entry.ok for entry in checks] == [True] + [False] * 7
    assert check(checks, "editor-install").skipped is True
    assert all(entry.fix for entry in checks if not entry.ok), "every failing line must say what to do"
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
        editor_version="3.2.148",
        probe={"version": "3.2.148", "connector": "0.4.5", "checks": ALL_PRESENT},
    ))
    entry = check(checks, "editor-version")
    assert entry.ok is False
    assert "3.2.148" in entry.detail
    assert "3.2.149" in entry.fix
    # 3.2.149 itself is the floor, not the line above it.
    floor = run_doctor(healthy_probe(
        editor_version="3.2.149",
        probe={"version": "3.2.149", "connector": "0.4.5", "checks": ALL_PRESENT},
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
                # The host's own remark rides along with `status` (the real ones
                # read `declared ADD since EDA v… on this host`): a hint, never
                # the verdict — the member is named from `status` either way.
                "notes": {"generateIndicatorMarkers": "declared in the type package, undefined here"},
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


def test_the_page_count_is_doc_lists_count_not_the_length_of_the_document_list():
    # Measured 2026-09-21: `projects[].schematics` is a *document list* and
    # carries the container schematic node (`schematic1`) next to the four
    # pages, so doctor printed "5 页原理图" for a four-page project. The number
    # it prints is `doc.list`'s own — `schematicPages` / `pcbs` — which is what
    # this test pins, container node and all.
    documents = _focused_project_documents(
        schematicPages=4,
        pcbs=1,
        projects=[{
            "projectUuid": "proj-1", "name": "/test", "friendlyName": "test", "focused": True,
            "schematics": [
                {"uuid": "sch-1", "name": "schematic1", "type": "schematic"},
                {"uuid": "page-1", "name": "P1", "type": "page"},
                {"uuid": "page-2", "name": "P2", "type": "page"},
                {"uuid": "page-3", "name": "P3", "type": "page"},
                {"uuid": "page-4", "name": "P4", "type": "page"},
            ],
            "pcbs": [{"uuid": "pcb-1", "name": "PCB1", "type": "pcb"}],
        }],
    )
    entry = check(run_doctor(healthy_probe(documents=documents)), "project")
    assert entry.ok is True
    assert "4 页原理图 / 1 个 PCB" in entry.detail
    assert "5 页原理图" not in entry.detail


def test_a_payload_without_the_counts_still_reports_the_list_length():
    # An older connector build does not send `schematicPages` / `pcbs`; there
    # the list lengths are the only numbers there are, and a count that may
    # read one high beats a missing one.
    entry = check(run_doctor(healthy_probe(documents=_focused_project_documents())), "project")
    assert entry.ok is True
    assert "1 页原理图 / 0 个 PCB" in entry.detail


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
    assert EDITOR_API_FLOOR == (3, 2, 149)


# --------------------------------------------------------------------------
# the offline pre-check (issue #3)
# --------------------------------------------------------------------------
#
# The complaint: the version gate was the *last* thing decidable, because it sat
# behind daemon → extension → .eext → restart → pairing, while upgrading the
# editor is the first thing to do. It is read from the install tree instead,
# offline, and judged first — so a machine with an old editor says so before the
# user has set anything else up.


def test_the_offline_line_comes_first_and_names_the_tree_it_read():
    checks = run_doctor(healthy_probe(
        offline_editor_path=r"D:\lceda-pro",
        offline_editor_version="3.2.186.b52e3e87",
    ))
    assert [entry.name for entry in checks][0] == "editor-install"
    assert len(checks) == 8
    entry = checks[0]
    assert entry.ok is True and entry.skipped is False
    assert r"D:\lceda-pro" in entry.detail
    assert "3.2.186.b52e3e87" in entry.detail
    assert "resources/app/package.json" in entry.detail


def test_an_old_install_tree_is_red_before_anything_is_connected():
    """The issue's own machine: nothing set up yet, an editor below the floor."""
    checks = run_doctor(DoctorProbe(
        port=61190,
        offline_editor_path=r"D:\lceda-pro",
        offline_editor_version="3.2.148.88089769",
    ))
    entry = checks[0]
    assert entry.name == "editor-install"
    assert entry.ok is False and entry.skipped is False
    assert "3.2.148.88089769" in entry.detail and r"D:\lceda-pro" in entry.detail
    # 直给：先升级，其余都排在它后面；地址按 docs/install.md 的说法。
    assert "先升级编辑器到 ≥3.2.149" in entry.fix
    assert "其余检查项都排在它后面" in entry.fix
    assert "https://pro.easyeda.com/" in entry.fix
    # …and only then the six prerequisites of the bridge path.
    assert [c.name for c in checks][1] == "daemon"


def test_an_old_editor_still_connected_is_red_on_both_version_lines():
    """Same old editor, breadcrumb complete: the offline line still comes first.

    Both lines are red here and they agree, which is the state a user lands in
    after the extension finally connects on a machine that never upgraded — with
    the actionable one (upgrade) printed first.
    """
    checks = run_doctor(healthy_probe(
        editor_version="3.2.148.88089769",
        probe={"version": "3.2.148.88089769", "connector": "0.4.5", "checks": ALL_PRESENT},
        offline_editor_path=r"D:\lceda-pro",
        offline_editor_version="3.2.148.88089769",
    ))
    assert [entry.ok for entry in (check(checks, "editor-install"), check(checks, "editor-version"))] == [False, False]
    assert "先升级编辑器" in check(checks, "editor-install").fix
    assert "升级立创 EDA Pro" in check(checks, "editor-version").fix


def test_an_unreadable_or_absent_install_tree_is_a_skip_not_a_verdict():
    """The distinction the issue author asked to keep: unknown is not red."""
    unreadable = run_doctor(DoctorProbe(
        port=61190, offline_editor_path=r"D:\lceda-pro", offline_editor_version="",
        offline_editor_roots=("D:\\", "C:\\"),
    ))
    entry = unreadable[0]
    assert entry.skipped is True and entry.ok is True
    assert r"D:\lceda-pro" in entry.detail and "跳过" in entry.detail

    absent = run_doctor(DoctorProbe(
        port=61190, offline_editor_roots=("D:\\", r"C:\Program Files"),
    ))
    entry = absent[0]
    assert entry.name == "editor-install"
    assert entry.skipped is True and entry.ok is True
    assert "离线没找到编辑器安装" in entry.detail
    assert "D:\\" in entry.detail and r"C:\Program Files" in entry.detail


def test_a_manifest_without_a_usable_version_is_also_a_skip():
    checks = run_doctor(DoctorProbe(
        port=61190, offline_editor_path=r"D:\lceda-pro", offline_editor_version="not a version",
    ))
    entry = checks[0]
    assert entry.skipped is True and entry.ok is True
    assert "跳过" in entry.detail and "not a version" in entry.detail


def test_the_four_field_version_is_compared_on_its_first_three_fields():
    # The install tree carries a build suffix, `sys.probe` does not: without this
    # the two readings of the same release would look like different releases.
    assert _editor_version_key("3.2.149.88089769") == (3, 2, 149)
    assert _editor_version_key("3.2.186.b52e3e87") == (3, 2, 186)
    assert _editor_version_key("v3.2.149") == (3, 2, 149)
    assert _editor_version_key("") == ()

    checks = run_doctor(healthy_probe(
        offline_editor_path=r"D:\lceda-pro",
        offline_editor_version="3.2.186.b52e3e87",
    ))
    assert all(entry.ok for entry in checks)
    assert "不是正在跑的这个" not in check(checks, "editor-version").detail

    # The floor itself passes with a suffix, and one field below it does not.
    at_floor = run_doctor(DoctorProbe(port=61190, offline_editor_version="3.2.149.71234567"))
    assert at_floor[0].ok is True
    below = run_doctor(DoctorProbe(port=61190, offline_editor_version="3.2.148.71234567"))
    assert below[0].ok is False


def test_the_tree_newer_than_the_running_editor_asks_for_a_restart():
    """Upgraded but not restarted: the fix is a restart, not a download."""
    checks = run_doctor(healthy_probe(
        editor_version="3.2.148",
        probe={"version": "3.2.148", "connector": "0.4.5", "checks": ALL_PRESENT},
        offline_editor_path=r"D:\lceda-pro",
        offline_editor_version="3.2.186.b52e3e87",
    ))
    install = check(checks, "editor-install")
    assert install.skipped is True and install.ok is True
    assert "两处不是同一个安装" in install.detail
    assert "3.2.148" in install.detail and "3.2.186.b52e3e87" in install.detail

    running = check(checks, "editor-version")
    assert running.ok is False
    assert "3.2.148" in running.detail and "3.2.186.b52e3e87" in running.detail
    assert "重启" in running.fix
    assert "Get-Process lceda-pro" in running.fix


def test_a_second_stale_install_on_disk_is_a_note_not_a_red_line():
    """The other direction: the editor in use is fine, the found tree is old.

    Reported (the two readings disagree) but not red — a check that fails on a
    machine where everything works is the false alarm this project keeps
    cleaning up.
    """
    checks = run_doctor(healthy_probe(
        offline_editor_path=r"C:\Program Files\lceda-pro",
        offline_editor_version="3.2.149.88089769",
    ))
    install = check(checks, "editor-install")
    assert install.skipped is True and install.ok is True
    assert "两处不是同一个安装" in install.detail
    assert r"C:\Program Files\lceda-pro" in install.detail

    running = check(checks, "editor-version")
    assert running.ok is True
    assert "不是正在跑的这个" in running.detail
    assert [entry for entry in checks if not entry.ok] == []


def test_scan_editor_install_reads_the_manifest_under_a_root(tmp_path):
    tree = install_tree(tmp_path, "3.2.186.b52e3e87")
    scan = scan_editor_install(roots=[tmp_path])
    assert scan.install is not None
    assert scan.install.path == tree
    assert scan.install.version == "3.2.186.b52e3e87"
    assert scan.roots == (tmp_path,)


def test_scan_editor_install_matches_the_vendors_naming_habit(tmp_path):
    # Not one of the exact names: found by the one-level glob instead, and case
    # does not matter (Windows glob normalises it).
    tree = install_tree(tmp_path, "3.2.190.b0", name="LCEDA-Pro-2")
    scan = scan_editor_install(roots=[tmp_path])
    assert scan.install is not None and scan.install.path == tree
    assert scan.install.version == "3.2.190.b0"


def test_scan_editor_install_tells_a_missing_tree_from_an_unreadable_one(tmp_path):
    empty = tmp_path / "no-editor-here"
    empty.mkdir()
    assert scan_editor_install(roots=[empty]).install is None

    # A directory of the right name with nothing inside: "found, but no version"
    # — a different answer from "found nothing", and doctor says which.
    (tmp_path / "lceda-pro").mkdir()
    scan = scan_editor_install(roots=[tmp_path])
    assert scan.install is not None
    assert scan.install.path == tmp_path / "lceda-pro"
    assert scan.install.version == ""


def test_scan_editor_install_survives_a_broken_manifest(tmp_path):
    tree = install_tree(tmp_path, "3.2.186")
    (tree / "resources" / "app" / "package.json").write_bytes(b"{not json at all")
    scan = scan_editor_install(roots=[tmp_path])
    assert scan.install is not None and scan.install.version == ""


def test_the_pinned_search_replaces_the_built_in_locations(monkeypatch, tmp_path):
    """`BOARDWISE_EDITOR_INSTALL` wins, so a test (or an odd machine) decides."""
    from boardwise.cli import _editor_search_roots

    tree = install_tree(tmp_path, "3.2.186")
    monkeypatch.setenv(EDITOR_INSTALL_ENV, str(tmp_path))
    assert _editor_search_roots() == [tmp_path]
    assert scan_editor_install().install.path == tree

    # Unset, the built-in locations come back (drive roots first, then the two
    # Windows install directories) — asserted as a shape, not as this machine's
    # disk.
    monkeypatch.delenv(EDITOR_INSTALL_ENV)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    roots = _editor_search_roots()
    assert len(roots) == len(set(roots)) and roots, roots
    assert Path(tmp_path / "local" / "Programs") in roots
    assert Path(tmp_path / "pf") in roots


# --------------------------------------------------------------------------
# the CLI itself
# --------------------------------------------------------------------------


def _env(home: Path, port: int, **extra: str) -> dict:
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["BOARDWISE_HOME"] = str(home)
    env["BOARDWISE_PORT"] = str(port)
    env.update(extra)
    return env


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_doctor_without_a_daemon_exits_1_with_fixes(tmp_path):
    port = _free_port()
    empty = tmp_path / "no-editor"
    empty.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "boardwise.cli", "doctor", "--port", str(port),
         "--json", str(tmp_path / "doctor.json")],
        capture_output=True, text=True, encoding="utf-8",
        env=_env(tmp_path, port, BOARDWISE_EDITOR_INSTALL=str(empty)), timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    # Seven red lines and one skip: the offline pre-check looked where it was
    # told to, found nothing, and says so instead of inventing a version.
    assert result.stdout.count("FAIL") == 7
    assert result.stdout.count("SKIP") == 1
    assert "boardwise bridge start" in result.stdout
    assert "1/8" in result.stdout
    payload = json.loads((tmp_path / "doctor.json").read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["port"] == port
    assert [entry["name"] for entry in payload["checks"]] == [
        "editor-install", "daemon", "connector", "methods", "editor-version",
        "daemon-version", "connector-version", "project",
    ]
    assert payload["checks"][0]["skipped"] is True
    assert payload["versions"]["daemon"] == __version__
    assert payload["versions"]["editorInstall"] == ""
    assert payload["versions"]["connectorRepo"] == json.loads(
        (ROOT / "connector" / "extension.json").read_text(encoding="utf-8")
    )["version"]


def test_the_cli_says_upgrade_before_anything_is_connected(tmp_path):
    """End to end, the issue's machine: old editor, no daemon, no extension.

    The one thing this machine can already know is the answer, so it is the one
    thing the report starts with — and it does not need the other six lines to
    have a verdict first.
    """
    port = _free_port()
    install_tree(tmp_path, "3.2.148.88089769")
    result = subprocess.run(
        [sys.executable, "-m", "boardwise.cli", "doctor", "--port", str(port)],
        capture_output=True, text=True, encoding="utf-8",
        env=_env(tmp_path, port, BOARDWISE_EDITOR_INSTALL=str(tmp_path)), timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines[0].lstrip().startswith("FAIL")
    assert "编辑器安装版本 ≥ 3.2.149" in lines[0]
    assert "3.2.148.88089769" in result.stdout
    assert "先升级编辑器到 ≥3.2.149" in result.stdout
    assert "0/8" in result.stdout
    assert "8 项需要处理" in result.stdout
    assert result.stdout.count("FAIL") == 8


class _FakeDaemon:
    """A daemon that answers the three calls doctor makes, and nothing else."""

    def __init__(self, *, ping, probe=None, documents=None, errors=None):
        self.ping = ping
        self.probe = probe
        self.documents = documents
        self.errors = errors or {}
        self.calls = []
        self.targets = []

    async def call(self, action, params=None, *, target_project=None, target_instance=None):
        # The routing hints are part of `BridgeClient.call`'s signature since
        # doctor grew `--project`/`--instance` (028 batch 3a): with several
        # windows connected the daemon refuses to guess, so those checks need a
        # way to name one. Recorded rather than ignored, so a test can assert the
        # hint actually travels.
        self.calls.append(action)
        self.targets.append({"action": action, "project": target_project, "instance": target_instance})
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


def _doctor_args(tmp_path=None, json_path=None, extra=()):
    args = build_parser().parse_args(
        ["doctor"] + (["--json", str(json_path)] if json_path else []) + list(extra)
    )
    return args


def test_the_window_hint_reaches_the_calls_that_need_one(fake_daemon, capsys, tmp_path, monkeypatch):
    # 028 batch 3a. With several editor windows connected the daemon refuses to
    # guess which window a call is about (`WINDOW_UNSPECIFIED`, §3.5), so four of
    # doctor's eight checks can only answer "not verified" — measured on this
    # machine with three windows open: 4/8, purely for lack of a way to name one.
    # The hint must therefore reach the connector-owned calls, and not the
    # daemon-owned `ping` (whose answer is about the daemon, not a window).
    daemon = fake_daemon(_FakeDaemon(
        ping={"pong": True, "version": __version__, "connector": True, "pairedFingerprint": "ab12cd34"},
        probe={"version": "3.2.186", "connector": _repo_connector_version(), "checks": ALL_PRESENT},
        documents={
            "projects": [{"projectUuid": "proj-1", "friendlyName": "test", "focused": True,
                          "schematics": [], "pcbs": []}],
            "active": {"uuid": "page-1", "type": "page"},
        },
    ))
    tree = install_tree(tmp_path, "3.2.186.b52e3e87")
    monkeypatch.setenv(EDITOR_INSTALL_ENV, str(tmp_path))

    code = _cmd_doctor(_doctor_args(extra=["--instance", "inst-abc123"]))
    capsys.readouterr()

    assert code == 0
    hints = {entry["action"]: entry["instance"] for entry in daemon.targets}
    assert hints["sys.probe"] == "inst-abc123"
    assert hints["doc.list"] == "inst-abc123"
    assert hints["ping"] is None, "ping is answered by the daemon, which needs no window"


def test_a_window_hint_is_optional_and_changes_nothing_when_absent(fake_daemon, capsys, tmp_path, monkeypatch):
    # The single-window case (and the case where a project hint is enough) must
    # keep working exactly as before: no hint given, no hint sent.
    daemon = fake_daemon(_FakeDaemon(
        ping={"pong": True, "version": __version__, "connector": True, "pairedFingerprint": "ab12cd34"},
        probe={"version": "3.2.186", "connector": _repo_connector_version(), "checks": ALL_PRESENT},
        documents={
            "projects": [{"projectUuid": "proj-1", "friendlyName": "test", "focused": True,
                          "schematics": [], "pcbs": []}],
            "active": {"uuid": "page-1", "type": "page"},
        },
    ))
    install_tree(tmp_path, "3.2.186.b52e3e87")
    monkeypatch.setenv(EDITOR_INSTALL_ENV, str(tmp_path))

    assert _cmd_doctor(_doctor_args()) == 0
    capsys.readouterr()
    assert {entry["instance"] for entry in daemon.targets} == {None}
    assert {entry["project"] for entry in daemon.targets} == {None}


def test_the_cli_gathers_the_three_payloads_and_goes_green(fake_daemon, capsys, tmp_path, monkeypatch):
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
    # This case *has* an editor on disk, at the version the stub reports: eight
    # green lines, the offline one first. The fixture that pins the search to an
    # empty directory is re-pinned here, to a tree of this test's own making, so
    # the count does not depend on the developer's machine.
    tree = install_tree(tmp_path, "3.2.186.b52e3e87")
    monkeypatch.setenv(EDITOR_INSTALL_ENV, str(tmp_path))
    code = _cmd_doctor(_doctor_args(json_path=tmp_path / "d.json"))
    out = capsys.readouterr().out
    assert code == 0
    assert daemon.calls == ["ping", "sys.probe", "doc.list"]
    assert out.count("PASS") == 8
    assert out.count("FAIL") == 0
    assert out.splitlines()[0].lstrip().startswith("PASS")
    assert str(tree) in out
    assert "毕设板" in out
    payload = json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["versions"]["editorInstall"] == "3.2.186.b52e3e87"
    assert payload["versions"]["editorInstallPath"] == str(tree)


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
    # version (this CLI and the stub agree); the one skip is the offline
    # pre-check, which found no install tree because this test pinned the search
    # to an empty directory.
    assert out.count("FAIL") == 5
    assert out.count("PASS") == 2
    assert out.count("SKIP") == 1
    assert "离线没找到编辑器安装" in out
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

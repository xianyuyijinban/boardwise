"""192C — the shelf CLI and the bridge, from the v0.5.14 hole-finding pass.

Seven holes, one theme: a command that *answers* differently from the shelf the
rest of the project reads, or a sentence that sends the reader somewhere useless.

* **`parts add` vs the merge (high).** The duplicate check read the **user's**
  shelf while every reader reads the merge (191B). So a part the exe's shelf
  already carries — curated, `facts_verified: true`, driving rules — was not a
  duplicate to `parts add`: the command scaffolded `candidate.<mpn>` into the
  user's file, and the merge then dropped the curated entry for it (identity is
  MPN/C-number/shelf key). The check now reads the same merged shelf, refuses and
  names the entry, and `--force` overrides **on purpose** while the write still
  lands only in the user's shelf.
* **`parts show` / `parts missing` attribution (medium).** Both judged the merged
  shelf but reported one path and the merged entry count, so "the shelf does not
  have this part" pointed at a file that does. They now carry `shelfPaths[]` and
  each row's `origin`, the shape `parts list` prints.
* **`_read_default_shelf` blamed `paths[0]` (low).** A broken *bundled* shelf was
  reported as the user's file being unreadable.
* **`update-connector --all` verified every window from a pool (high).** One new
  connection announcing the expected version satisfied **each** target, so a
  window whose write never took effect read `verified`. Multi-window runs now
  need at least one expected-version connection per target window; short of that
  every target is `unconfirmed` (exit non-zero) with the reason in its detail.
* **`--project test` against a window reporting `/test` (medium).** The connector
  reports the project's *friendly name* (leading slash) while `doc.list` reports
  `test`, so the hint the CLI prints as the way to name a window did not route.
  Project hints are compared with the leading `/` and case ignored; the refusal
  prints each window's own name **and** uuid.
* **Two places told the reader to run `bridge start` (medium).** With a daemon
  already running that is a bind failure (`OSError` 10048) and a traceback, and
  it is the wrong advice anyway: the next bridge command auto-starts a daemon.
  Both texts now say to end the old process, and `bridge start` on a busy port
  answers in a sentence instead of a traceback.
* **`_local_action` answered `hello` (low).** Any daemon-owned action this build
  does not know got the handshake's protocol sentence — a fact about the wrong
  thing. It is `UNKNOWN_ACTION` now.

These tests deliberately go through the **production wiring**: the frozen state
is `sys.frozen` + `sys._MEIPASS` + `BOARDWISE_HOME` (the same simulation
`tests/test_191b_shelf_merge.py` uses), so `default_library_paths()` and
`_parts_library_path(writable=True)` decide the paths — a hand-built merge
document would not have caught the hole in the first place.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

from boardwise import cli, resources
from boardwise.bridge.daemon import BridgeDaemon, WindowConnection
from boardwise.bridge.protocol import BridgeError, ErrorCodes
from boardwise.core.parts import SHELF_BUILTIN, SHELF_USER_OVERRIDES
from boardwise.rules.facts import read_default_library

BUNDLE_ENTRY = "ic.newpart"


def _entry(key: str, *, mpn: str = "", lcsc: str = "", value: str = "") -> dict:
    """One shelf entry in the shape the loader validates (as 191B's test file)."""
    return {
        "key": key,
        "value": value,
        "mpn": mpn,
        "lcsc": lcsc,
        "manufacturer": "",
        "deviceUuid": f"device-{key}",
        "libraryUuid": "a" * 32,
        "footprint_name": "SOT-23",
        "footprint_name_verified": None,
        "params": {},
        "datasheetUrl": "",
        "datasheetPdfUrl": "",
        "basic": None,
        "category": "ic.ldo",
        "provenance": {
            "kind": "manual-curation", "source": "", "designators": [], "note": "",
        },
        "notes": [],
    }


def _library(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "kind": "boardwise-part-library",
                "version": 2,
                "sources": [],
                "notes": [],
                "parts": entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture()
def frozen(tmp_path, monkeypatch):
    """A frozen process: one curated entry the exe ships, one entry the user added.

    The bundled entry is the *curated* one the hole is about — facts on it, the
    gate shut (`facts_verified: true`), so a rule acts on it and a candidate that
    shadows it costs a judgement, not just a row.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("BOARDWISE_HOME", str(home))
    bundle = tmp_path / "mei" / resources.FROZEN_SUBDIR / "blocklib" / "parts.json"
    curated = {
        **_entry(BUNDLE_ENTRY, mpn="NEWPART-1", lcsc="C9001"),
        "category": "ic.ldo",
        "facts": {
            "supply_pins": [
                {
                    "pins": ["1"],
                    "name": "VIN",
                    "v_operating": [2.0, 6.0],
                    "provenance": "https://example.invalid/ds.pdf p.3",
                }
            ]
        },
        "facts_verified": True,
    }
    _library(
        bundle,
        [
            curated,
            _entry("res.10k_0402", mpn="RC0402-10K", lcsc="C1001"),
            # A part the `ch340_golden` fixture actually carries, so the
            # `parts missing` test has a row whose entry lives on the exe's shelf.
            _entry("ic.ch340g", mpn="CH340G", lcsc="C14267"),
        ],
    )
    user = home / "parts.json"
    _library(user, [_entry("res.10k_0402", mpn="RC0402-10K", lcsc="C1001")])
    return {"bundle": bundle, "user": user}


def _window(key: str = "w", *, name: str = "", uuid: str = "") -> WindowConnection:
    """A live window with no socket behind it (the daemon only asks its state)."""

    class _Socket:
        state = "OPEN"

    return WindowConnection(
        websocket=_Socket(),
        key=key,
        instance_id=key,
        connector_version="0.5.14",
        project_name=name,
        project_uuid=uuid,
    )


# ---------------------------------------------------------------------------
# 1. `parts add` checks the shelf every reader reads
# ---------------------------------------------------------------------------


def test_parts_add_refuses_to_shadow_a_curated_builtin_entry(frozen, capsys):
    """The hole: the candidate was written, and the merge dropped the curated row.

    Nothing may be written at all — a refusal that still appends is the hole with
    a warning attached — and the merged shelf must still hold the bundled entry
    with its verified facts.
    """
    before = {
        frozen["user"]: frozen["user"].read_bytes(),
        frozen["bundle"]: frozen["bundle"].read_bytes(),
    }
    code = cli.main(["parts", "add", "NEWPART-1", "--lcsc", "C9001"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert BUNDLE_ENTRY in err, err
    assert "--force" in err, err
    assert {path: path.read_bytes() for path in before} == before, "拒绝就是什么都没写"

    row = read_default_library().get(BUNDLE_ENTRY)
    assert row is not None, "内置架那条还在（它并没有被顶掉）"
    assert row.facts_verified and row.facts


def test_parts_add_force_shadows_the_builtin_entry_on_purpose(frozen, capsys):
    """`--force` is the way to say "my entry, not the exe's" — and it says so.

    The write still lands in the user's shelf (the bundle is read-only by
    construction), and the output names what it overrode rather than leaving the
    reader to discover it from the merge labels.
    """
    bundle_before = frozen["bundle"].read_bytes()
    code = cli.main(["parts", "add", "NEWPART-1", "--lcsc", "C9001", "--force"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert BUNDLE_ENTRY in out and "内置架" in out, out
    assert frozen["bundle"].read_bytes() == bundle_before, "内置架是只读的"

    merged = read_default_library()
    assert merged.get(BUNDLE_ENTRY) is None, "内置那条在合并读里让位了（用户架优先）"
    overrode = [part for part in merged.parts if part.mpn == "NEWPART-1"]
    assert len(overrode) == 1
    assert merged.origin_of(overrode[0]) == SHELF_USER_OVERRIDES


def test_parts_add_writes_the_shadowing_entry_into_the_users_shelf(frozen):
    """Where the forced write lands: the file `parts add` always wrote."""
    cli.main(["parts", "add", "NEWPART-1", "--lcsc", "C9001", "--force"])
    written = json.loads(frozen["user"].read_text(encoding="utf-8"))
    keys = [part["key"] for part in written["parts"]]
    assert len(keys) == 2 and "res.10k_0402" in keys, keys
    assert [
        part["key"] for part in written["parts"] if part["mpn"] == "NEWPART-1"
    ] == [cli._candidate_key("NEWPART-1", "C9001")]


# ---------------------------------------------------------------------------
# 2. `parts show` / `parts missing` say which shelf answered
# ---------------------------------------------------------------------------


def test_parts_show_names_the_merged_shelf_and_the_entry_origin(frozen, tmp_path, capsys):
    """`show` judged the merge and reported the user's file (and the merge count)."""
    target = tmp_path / "show.json"
    code = cli.main(["parts", "show", "NEWPART-1", "--json", str(target)])
    captured = capsys.readouterr()
    assert code == 0, captured
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["shelfPaths"] == [str(frozen["user"]), str(frozen["bundle"])]
    assert payload["merged"] is True
    assert payload["origin"] == SHELF_BUILTIN
    assert f"source: {SHELF_BUILTIN}" in captured.out, captured.out
    assert str(frozen["bundle"]) in captured.err, (
        "读到的那一架（内置架）也要出现在话术里"
    )


def test_parts_show_not_found_points_at_the_shelf_it_read(frozen, capsys):
    """The old sentence named one path and the merged count — a file that lied."""
    code = cli.main(["parts", "show", "NOPE-1"])
    err = capsys.readouterr().err
    assert code == 2
    assert str(frozen["user"]) in err and str(frozen["bundle"]) in err, err
    assert "3 条" in err, err


def test_parts_missing_reports_the_merged_shelf(frozen, tmp_path, capsys):
    board = Path(__file__).parent / "fixtures" / "ch340_golden.epro2"
    report_path = tmp_path / "missing.json"
    code = cli.main([
        "parts", "missing", "--file", str(board), "--json", str(report_path),
    ])
    out = capsys.readouterr().out
    assert code == 0, out
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["shelfPaths"] == [str(frozen["user"]), str(frozen["bundle"])]
    assert report["merged"] is True
    assert report["parts"], "夹具上有 U 位号件才对"
    assert any(row["source"] == SHELF_BUILTIN for row in report["parts"]), (
        "命中内置架的行要说它来自内置架"
    )
    assert all(
        row["source"] == str(frozen["user"]) or row["source"] == SHELF_BUILTIN
        or row["source"] in ("", SHELF_USER_OVERRIDES)
        for row in report["parts"]
    )


# ---------------------------------------------------------------------------
# 3. the unreadable shelf is named by its own path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("broken", ["bundle", "user"])
def test_a_shelf_that_cannot_be_read_is_named_by_its_own_path(frozen, capsys, broken):
    """A malformed *bundled* shelf used to be reported as the user's file."""
    victim = frozen[broken]
    victim.write_text("{ this is not json", encoding="utf-8")
    code = cli.main(["parts", "list"])
    err = capsys.readouterr().err
    assert code == 2, err
    other = frozen["user" if broken == "bundle" else "bundle"]
    assert str(victim) in err, err
    assert str(other) not in err, f"点名了不相关的货架：{err}"


# ---------------------------------------------------------------------------
# 4. `update-connector --all`: one pool verdict is not per-window evidence
# ---------------------------------------------------------------------------


def _w(key: str, instance: str, version: str) -> dict:
    return {
        "windowKey": key, "instanceId": instance, "connectorVersion": version,
        "projectName": None,
    }


EXPECTED = "0.5.14"


def _verdicts(before_rows, now_rows, targets):
    from boardwise.cli import _snapshot_identities, _table_verdicts

    return _table_verdicts(
        now_rows,
        expected=EXPECTED,
        before=_snapshot_identities(before_rows),
        targets=targets,
    )


BEFORE_TWO = [_w("A", "inst-a", "0.5.13"), _w("B", "inst-b", "0.5.13")]


def test_two_windows_that_both_reloaded_are_both_verified():
    """The good case still ends in two verdicts — no blanket "unconfirmed"."""
    verdicts = _verdicts(
        BEFORE_TWO,
        [_w("A'", "inst-a2", EXPECTED), _w("B'", "inst-b2", EXPECTED)],
        ["A", "B"],
    )
    assert [verdicts[t][0] for t in ("A", "B")] == ["verified", "verified"], verdicts


def test_one_windows_reload_does_not_verify_the_other():
    """The hole: B's new connection satisfied A's verdict.

    A's page came back running the old build; B's came back right. The daemon's
    table cannot say *which* window a new connection belongs to, so the honest
    answer is "not confirmed for either" — never `verified (0.5.14)` on A.
    """
    verdicts = _verdicts(
        BEFORE_TWO,
        [_w("A'", "inst-a2", "0.5.13"), _w("B'", "inst-b2", EXPECTED)],
        ["A", "B"],
    )
    assert [verdicts[t][0] for t in ("A", "B")] == ["unconfirmed", "unconfirmed"], verdicts
    assert all("0.5.14" in verdicts[t][2] for t in ("A", "B"))


def test_a_window_that_vanished_is_not_verified_by_the_other_ones_reload():
    """Scenario 3: A is simply gone. B's reload is real and still not A's evidence."""
    verdicts = _verdicts(BEFORE_TWO, [_w("B'", "inst-b2", EXPECTED)], ["A", "B"])
    assert [verdicts[t][0] for t in ("A", "B")] == ["unconfirmed", "unconfirmed"], verdicts


def test_a_single_window_still_gets_the_plain_verdict():
    """One target is not a pool: the single-window rule is unchanged.

    (…which is what every caller except `--all` is: `targets` is one key, or the
    unnamed `""` of a one-window daemon.)
    """
    verdicts = _verdicts(
        [_w("A", "inst-a", "0.5.13")], [_w("A'", "inst-a2", "0.5.13")], ["A"]
    )
    assert verdicts["A"][0] == "mismatch", verdicts
    verdicts = _verdicts(
        [_w("A", "inst-a", "0.5.13")], [_w("A'", "inst-a2", EXPECTED)], [""]
    )
    assert verdicts[""][0] == "verified", verdicts


def test_the_reload_states_are_named_where_a_reader_finds_them():
    """`unconfirmed` is its own state, not a relabelled `pending`."""
    assert cli.RELOAD_UNCONFIRMED == "unconfirmed"
    assert cli.RELOAD_UNCONFIRMED not in (
        cli.RELOAD_VERIFIED, cli.RELOAD_MISMATCH, cli.RELOAD_PENDING,
    )


# ---------------------------------------------------------------------------
# 5. the hint `bridge status` prints has to route
# ---------------------------------------------------------------------------


def test_a_friendly_name_project_hint_routes(tmp_path):
    """The connector reports `/test` (friendlyName); `doc.list` reports `test`."""
    daemon = BridgeDaemon(token="t", home=tmp_path)
    daemon.windows["w"] = _window(name="/test", uuid="ea80fff6-0000")
    for hint in ("test", "/test", "TEST", "/Test"):
        assert daemon.route(target_project=hint, action="doc.list").key == "w", hint
    assert daemon.route(target_project="ea80fff6-0000", action="doc.list").key == "w"
    assert daemon.route(target_project="EA80FFF6-0000", action="doc.list").key == "w"


def test_a_hint_that_matches_nothing_refuses_with_both_spellings(tmp_path):
    """Still a refusal — with the window's own name and uuid on it."""
    daemon = BridgeDaemon(token="t", home=tmp_path)
    daemon.windows["w"] = _window(name="/test", uuid="ea80fff6-0000")
    with pytest.raises(BridgeError) as excinfo:
        daemon.route(target_project="other-board", action="doc.list")
    assert excinfo.value.code == ErrorCodes.PROJECT_NOT_CONNECTED
    message = excinfo.value.message
    assert "/test" in message and "ea80fff6-0000" in message, message
    assert "leading" in message or "前导" in message, message


def test_two_windows_that_differ_only_in_case_are_ambiguous(tmp_path):
    """Ignoring case must not pick one: the refusal is the honest answer."""
    daemon = BridgeDaemon(token="t", home=tmp_path)
    daemon.windows["a"] = _window("a", name="/test", uuid="uuid-a")
    daemon.windows["b"] = _window("b", name="test", uuid="uuid-b")
    with pytest.raises(BridgeError) as excinfo:
        daemon.route(target_project="test", action="doc.list")
    assert excinfo.value.code == ErrorCodes.PROJECT_AMBIGUOUS


# ---------------------------------------------------------------------------
# 6. "restart the daemon" must not be "run bridge start and watch it fail"
# ---------------------------------------------------------------------------


def test_the_version_drift_warning_says_how_to_end_the_old_daemon():
    """The advice on the handshake, where every bridge command sees it."""
    from boardwise.bridge.client import daemon_version_warning

    text = daemon_version_warning("0.0.1")
    assert text
    assert "taskkill" in text, text
    assert "自动拉起" in text, text
    assert "`boardwise bridge start` 重启" not in text, text


def test_the_doctors_daemon_version_step_gives_the_same_advice():
    """Two copies of one sentence, pinned together so they cannot drift.

    `client.py` cannot import the CLI (layering), so the sentence exists twice —
    and this is the test that keeps them saying the same thing.
    """
    assert "taskkill" in cli.DAEMON_RESTART_ADVICE
    assert "自动拉起" in cli.DAEMON_RESTART_ADVICE


def test_bridge_start_on_a_busy_port_answers_in_a_sentence(monkeypatch, tmp_path, capsys):
    """187c's advice, followed literally, used to end in an OSError traceback."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    with socket.socket() as busy:
        busy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        busy.bind(("127.0.0.1", 0))
        busy.listen(5)
        port = busy.getsockname()[1]
        code = cli.main(["bridge", "--port", str(port), "start"])
    captured = capsys.readouterr()
    assert code == 2, captured
    assert "Traceback" not in captured.err, captured.err
    assert str(port) in captured.err, captured.err
    assert "taskkill" in captured.err and "自动拉起" in captured.err, captured.err
    assert "--port" in captured.err, "端口不是默认值时话术要能照抄"


# ---------------------------------------------------------------------------
# 7. a daemon-owned action this build does not know
# ---------------------------------------------------------------------------


def test_an_unknown_daemon_owned_action_is_unknown_action(tmp_path):
    """`hello` during the request phase got the handshake's own sentence.

    The daemon's action table is a load-time constant, so a CLI built from a
    newer revision asks an older daemon for daemon-owned actions it has never
    heard of — and "hello may only be sent once" is a fact about the wrong thing.
    """
    daemon = BridgeDaemon(token="t", home=tmp_path)
    with pytest.raises(BridgeError) as excinfo:
        daemon._local_action("hello")
    assert excinfo.value.code == ErrorCodes.UNKNOWN_ACTION
    assert "may only be sent once" not in excinfo.value.message
    assert "hello" in excinfo.value.message

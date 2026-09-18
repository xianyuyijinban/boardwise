"""The third persistence state, and the only thing that can establish it.

`saved_verified` means the content survived a close-and-reopen. No bridge action
can establish it — `doc.open` moves the focused tab without reloading it from
disk and there is no close-project action (M0-P0d audit E) — so the reopen is a
human act and `boardwise persistence` is what turns its result into an exit
code. These tests drive that comparison offline, against the **real** measured
dumps (`tests/fixtures/ch340_p1_editor_netlist.json`,
`ch340_p1_geometry.json`), so the shapes under test are the host's own.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from boardwise.bridge.protocol import ErrorCodes
from boardwise.cli import _cmd_persistence, _compare_persistence
from boardwise.engines.draw import fingerprint_total, geometry_fingerprint

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NETLIST_FIXTURE = FIXTURES / "ch340_p1_editor_netlist.json"
GEOMETRY_FIXTURE = FIXTURES / "ch340_p1_geometry.json"


def _netlist_text() -> str:
    return NETLIST_FIXTURE.read_text(encoding="utf-8")


def _geometry() -> dict:
    return json.loads(GEOMETRY_FIXTURE.read_text(encoding="utf-8"))


def _snapshot(netlist_text: str | None = None, geometry: dict | None = None) -> dict:
    return {
        "netlist": {
            "type": "EasyEDA",
            "source": "getNetlistFile",
            "size": len(netlist_text or ""),
            "text": _netlist_text() if netlist_text is None else netlist_text,
        },
        "geometry": _geometry() if geometry is None else geometry,
    }


def _audit_records(home: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted((home / "audit").glob("*.jsonl")):
        records.extend(
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        )
    return records


# --------------------------------------------------------------------------
# geometry_fingerprint: id-free, or the check would be worthless
# --------------------------------------------------------------------------


def test_the_fingerprint_ignores_generated_ids():
    """The editor mints ids per render; comparing them would always differ.

    Two dumps of the same page that differ only in `primitiveId` must fingerprint
    equal, or every reopened project would report a difference.
    """
    first = _geometry()
    second = json.loads(json.dumps(first))
    for index, entry in enumerate(second["components"]):
        entry["primitiveId"] = f"regenerated-{index}"
        if isinstance(entry.get("state"), dict):
            entry["state"]["PrimitiveId"] = f"regenerated-{index}"
    for index, entry in enumerate(second["wires"]):
        entry["primitiveId"] = f"regenerated-w{index}"

    assert first != second, "the ids really did change"
    assert geometry_fingerprint(first) == geometry_fingerprint(second)


def test_the_fingerprint_counts_the_real_dump_by_list_and_type():
    """Positive control on the measured host shape.

    The dump has no `primitives` list at all (audit, 2026-09-18), so a reader
    looking for one would see an empty page. This pins what is actually there.
    """
    fingerprint = geometry_fingerprint(_geometry())
    assert fingerprint["components"] == 35
    assert fingerprint["components/part"] == 17
    assert fingerprint["components/netflag"] == 17
    assert fingerprint["wires"] == 33
    assert "primitives" not in _geometry(), "the host shape is the four lists"


def test_the_fingerprint_is_empty_rather_than_zero_for_an_unreadable_dump():
    """Empty means "nothing we know how to read" — the caller must not pass it."""
    assert geometry_fingerprint(None) == {}
    assert geometry_fingerprint({}) == {}
    assert geometry_fingerprint({"something": "else"}) == {}


def test_the_total_does_not_double_count_the_per_type_breakdown():
    """Summing the whole fingerprint counts every primitive twice.

    The per-list total and the per-type entries describe the *same* records, so
    the naive `sum(fingerprint.values())` reported 136 for a page holding 68
    primitives (measured while wiring this up).
    """
    fingerprint = geometry_fingerprint(_geometry())
    assert sum(fingerprint.values()) > 68, "the naive sum really does over-count"
    assert fingerprint_total(fingerprint) == 68
    assert fingerprint_total({}) == 0


# --------------------------------------------------------------------------
# the comparison
# --------------------------------------------------------------------------


def test_an_identical_reopen_is_saved_verified(tmp_path, monkeypatch):
    """The pass case — and it is the only one allowed to print `saved_verified`."""
    from boardwise.bridge import daemon as daemon_module

    monkeypatch.setattr(daemon_module, "BOARDWISE_HOME", tmp_path)
    code = _compare_persistence(_snapshot(), _snapshot())

    assert code == 0
    records = _audit_records(tmp_path)
    assert [r["action"] for r in records] == [daemon_module.AUDIT_PERSISTENCE_VERIFIED]
    assert records[0]["persistence"] == "saved_verified"
    assert records[0]["components"] == 17
    assert records[0]["primitives"] == 35 + 33


def test_a_reopen_that_lost_connectivity_is_not_verified(capsys):
    """The regression the upstream issue #216 describes: the page came back wrong."""
    changed = json.loads(_netlist_text())
    first = next(iter(changed["components"].values()))
    pin = next(iter(first["pinInfoMap"].values()))
    pin["net"] = "SOMETHING_ELSE"

    code = _compare_persistence(
        _snapshot(), _snapshot(netlist_text=json.dumps(changed))
    )
    printed = capsys.readouterr().out
    assert code == 1
    assert "NOT what was drawn" in printed
    assert "persistence: NOT saved_verified" in printed
    assert "persistence: saved_verified" not in printed, (
        "a failed comparison may not also print the pass line"
    )


def test_a_reopen_with_a_different_page_is_not_verified(capsys):
    """The geometry half catches content the netlist half cannot see."""
    fewer = _geometry()
    fewer["wires"] = fewer["wires"][:-3]

    code = _compare_persistence(_snapshot(), _snapshot(geometry=fewer))
    printed = capsys.readouterr().out
    assert code == 1
    assert "primitives differ" in printed
    assert "wires/Wire: 33 -> 30" in printed


def test_a_missing_netlist_is_undecidable_not_a_pass(capsys):
    """`sch.netlist` returns nothing for a never-saved project (measured).

    That is the exact shape a failed save leaves behind, so it must read as
    "cannot decide" — never as "identical", which is what an empty-string
    comparison would quietly produce.
    """
    code = _compare_persistence(_snapshot(), _snapshot(netlist_text=""))
    captured = capsys.readouterr()
    assert code == 3
    assert "cannot decide" in captured.err
    assert "saved_verified" not in captured.out


def test_a_missing_geometry_is_undecidable_not_a_pass(capsys):
    code = _compare_persistence(_snapshot(), _snapshot(geometry={}))
    captured = capsys.readouterr()
    assert code == 3
    assert "census came back empty" in captured.err
    assert "saved_verified" not in captured.out


def test_an_unparseable_netlist_is_undecidable(capsys):
    code = _compare_persistence(_snapshot(), _snapshot(netlist_text="{ not json"))
    captured = capsys.readouterr()
    assert code == 3
    assert "malformed" in captured.err


# --------------------------------------------------------------------------
# the command surface
# --------------------------------------------------------------------------


def test_the_command_asks_for_one_of_its_two_modes_before_touching_the_bridge(capsys):
    """No flags is a usage error, not a silent snapshot nobody reads."""
    args = argparse.Namespace(out=None, baseline=None)
    assert _cmd_persistence(args) == 2
    assert "give --out" in capsys.readouterr().err


class _FakeBridgeClient:
    """A ``BridgeClient`` stand-in, so the command's failure paths are testable
    without an editor (the pattern ``test_bridge_cli.py`` uses)."""

    opened_with = ""
    answers: dict = {}
    fail_open: BaseException | None = None
    calls: list = []

    @classmethod
    async def open(cls, uri, token, role, client=""):
        cls.opened_with = uri
        cls.calls = []
        if cls.fail_open is not None:
            raise cls.fail_open
        return cls()

    async def call(self, action, params=None):
        type(self).calls.append(action)
        answer = type(self).answers.get(action)
        if isinstance(answer, BaseException):
            raise answer
        return {} if answer is None else answer

    async def close(self):
        return None


@pytest.fixture
def fake_bridge(monkeypatch, tmp_path):
    """Isolated BOARDWISE_HOME (the command opens a CLI token) + a fake client."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    import boardwise.bridge.client as client_module

    _FakeBridgeClient.fail_open = None
    _FakeBridgeClient.calls = []
    monkeypatch.setattr(client_module, "BridgeClient", _FakeBridgeClient)
    return tmp_path


def test_a_snapshot_writes_the_file_and_says_what_to_do_next(fake_bridge, capsys, tmp_path):
    _FakeBridgeClient.answers = {
        "sch.netlist": {"type": "EasyEDA", "text": _netlist_text()},
        "sch.geometry": _geometry(),
    }
    out = tmp_path / "snap.json"
    args = argparse.Namespace(out=str(out), baseline=None)

    assert _cmd_persistence(args) == 0
    snapshot = json.loads(out.read_text(encoding="utf-8"))
    assert set(snapshot) == {"netlist", "geometry"}
    assert snapshot["netlist"]["text"] == _netlist_text()
    # Read-only: nothing but the two reads reached the editor.
    assert _FakeBridgeClient.calls == ["sch.netlist", "sch.geometry"]
    printed = capsys.readouterr().out
    assert "close the project in the editor, reopen it" in printed


def test_an_action_error_is_reported_and_exits_two(fake_bridge, capsys):
    """A connector-side failure is a usage-level answer, not a traceback.

    Measured 2026-09-18 on this host: `sch.netlist` currently answers
    `CONNECTOR_ERROR: both netlist exports failed` — the export really is the
    fragile step, so the command has to carry that message out intact.
    """
    from boardwise.bridge.protocol import BridgeError

    _FakeBridgeClient.answers = {
        "sch.netlist": BridgeError(
            ErrorCodes.CONNECTOR_ERROR, "both netlist exports failed"
        )
    }
    args = argparse.Namespace(out=None, baseline="whatever.json")
    assert _cmd_persistence(args) == 2
    captured = capsys.readouterr()
    assert "CONNECTOR_ERROR: both netlist exports failed" in captured.err


def test_an_unreachable_daemon_exits_two(fake_bridge, capsys):
    _FakeBridgeClient.fail_open = OSError("connection refused")
    args = argparse.Namespace(out="snap.json", baseline=None)
    assert _cmd_persistence(args) == 2
    assert "daemon not reachable" in capsys.readouterr().err


def test_a_missing_baseline_file_exits_two(fake_bridge, capsys, tmp_path):
    _FakeBridgeClient.answers = {
        "sch.netlist": {"type": "EasyEDA", "text": _netlist_text()},
        "sch.geometry": _geometry(),
    }
    args = argparse.Namespace(out=None, baseline=str(tmp_path / "nope.json"))
    assert _cmd_persistence(args) == 2
    assert "nope.json" in capsys.readouterr().err


def test_the_arguments_parse_as_advertised():
    from boardwise.cli import build_parser

    args = build_parser().parse_args(["persistence", "--out", "s.json"])
    assert (args.command, args.out, args.baseline) == ("persistence", "s.json", None)

    args = build_parser().parse_args(["persistence", "--baseline", "s.json"])
    assert (args.out, args.baseline) == (None, "s.json")

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
import re
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


# --------------------------------------------------------------------------
# the subset rule: "is what I snapshotted still there?"
# --------------------------------------------------------------------------


def _grown_netlist() -> str:
    """The measured netlist plus one component, one net and one net member.

    The shape a snapshot-then-work-on-other-pages run leaves behind: the
    snapshot's own content is untouched, everything new is additive.
    """
    grown = json.loads(_netlist_text())
    grown["components"]["gge999"] = {
        "props": {
            "Designator": "R99",
            "Value": "10k",
            "Footprint": "0402",
            "Supplier Part": "C25744",
        },
        "pinInfoMap": {
            "1": {"name": "1", "number": "1", "net": "GND", "props": {}},
            "2": {"name": "2", "number": "2", "net": "NEWNET", "props": {}},
        },
    }
    return json.dumps(grown)


def test_a_reopen_that_only_gained_content_is_still_verified(capsys, tmp_path, monkeypatch):
    """The subset rule, on the shape that was measured on 2026-09-28.

    A snapshot whose own content came back **complete** was still judged NOT
    saved_verified because 20 components and 40 net members had been drawn on
    other pages after it was taken (all of them "extra in candidate"). What a
    reopen can answer is "did the snapshot's content survive", and content added
    afterwards answers that the same way an unchanged project does.
    """
    from boardwise.bridge import daemon as daemon_module

    monkeypatch.setattr(daemon_module, "BOARDWISE_HOME", tmp_path)
    code = _compare_persistence(_snapshot(), _snapshot(netlist_text=_grown_netlist()))
    printed = capsys.readouterr().out

    assert code == 0, "an additive change is not a failed save"
    assert "persistence: saved_verified" in printed
    assert "the page has since grown" in printed
    assert "extras: 3 item(s)" in printed, "counted and said out loud"
    assert "component extra in candidate" in printed
    assert "net extra in candidate" in printed
    assert "member extra in candidate" in printed
    assert "NOT saved_verified" not in printed
    # Only a pass writes the audit line, and this is a pass.
    records = _audit_records(tmp_path)
    assert [r["action"] for r in records] == [daemon_module.AUDIT_PERSISTENCE_VERIFIED]


def test_an_unchanged_reopen_reports_no_extras(capsys, tmp_path, monkeypatch):
    """`extras: 0` is the unchanged project, and it reads exactly as it did before."""
    from boardwise.bridge import daemon as daemon_module

    monkeypatch.setattr(daemon_module, "BOARDWISE_HOME", tmp_path)
    code = _compare_persistence(_snapshot(), _snapshot())
    printed = capsys.readouterr().out

    assert code == 0
    assert "extras:" not in printed
    assert "persistence: saved_verified" in printed


def test_a_component_lost_in_the_reopen_is_not_verified(capsys):
    """The subset rule is a subset, not a truce: a loss still fails the run."""
    thinned = json.loads(_netlist_text())
    del thinned["components"]["gge57"]

    code = _compare_persistence(_snapshot(), _snapshot(netlist_text=json.dumps(thinned)))
    printed = capsys.readouterr().out
    assert code == 1
    assert "the reopened page is NOT what was drawn" in printed
    assert "component missing in candidate" in printed
    assert "NOT saved_verified" in printed
    assert "persistence: saved_verified" not in printed


def test_a_value_changed_in_the_reopen_is_not_verified(capsys):
    """A field that came back different is a loss of what was snapshotted."""
    changed = json.loads(_netlist_text())
    changed["components"]["gge55"]["props"]["Value"] = "9.1K"

    code = _compare_persistence(_snapshot(), _snapshot(netlist_text=json.dumps(changed)))
    printed = capsys.readouterr().out
    assert code == 1
    assert "value differs" in printed
    assert "1 snapshot item(s) missing or changed" in printed


def test_the_census_tolerates_primitives_gained_but_not_lost(capsys):
    """Same split on the geometry half, in both directions.

    `sch.geometry` reads the focused page, so "gained" here means the page grew
    after the snapshot — as tolerated as the netlist's extras. A primitive the
    snapshot held and the page no longer does is the failure the census exists
    for.
    """
    geometry = _geometry()
    fewer = json.loads(json.dumps(geometry))
    fewer["wires"] = fewer["wires"][:-3]

    code = _compare_persistence(_snapshot(geometry=fewer), _snapshot(geometry=geometry))
    printed = capsys.readouterr().out
    assert code == 0
    assert "primitives gained since the snapshot" in printed
    assert "wires/Wire: 30 -> 33" in printed
    assert "persistence: saved_verified" in printed

    code = _compare_persistence(_snapshot(geometry=geometry), _snapshot(geometry=fewer))
    printed = capsys.readouterr().out
    assert code == 1
    assert "primitives the snapshot had are gone" in printed
    assert "wires/Wire: 33 -> 30" in printed


def test_every_extra_direction_is_declared_and_nothing_else_is():
    """A subset run classifies by direction, so the directions are pinned here.

    Scanned against the module's own literals rather than enumerated by hand: a
    new difference branch in `compare_models` whose direction is "candidate
    only" must be declared in `EXTRA_DETAILS`, or `boardwise persistence
    --baseline` would fail a run for content that was merely added later.
    """
    from boardwise.core import compare as compare_module

    source = Path(compare_module.__file__).read_text(encoding="utf-8")
    literals = set(re.findall(r'"([^"]*extra in candidate)"', source))
    assert literals, "the scan found no directions at all — the pattern drifted"
    assert literals == set(compare_module.EXTRA_DETAILS)


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

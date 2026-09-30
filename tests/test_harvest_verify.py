"""The `--verify` chain, driven by a stub (task 008b, item 2).

The chain is the one measured on the machine on 2026-09-16::

    lib.device.get(device uuid, library uuid) -> item.association.footprintUuid
    lib.footprint.get(that, library uuid)     -> name

Both halves of the *old* behaviour are pinned here as mistakes: asking
`lib.footprint.get` with the uuid the **project** holds fails on the live
library (006b measured the same for project-local symbol uuids), and a silent
failure would leave an entry looking verified when nothing had been checked.

Three failures are exercised because they fail at three different places in the
chain — the device read, the field inside its dump, and the footprint read — and
each one must leave the entry unverified while the rest of the harvest carries on.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from boardwise.engines.harvest import devices_to_verify

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "blocklib" / "sources"
PILLBOX = SOURCES / "smart_pillbox.eprj2"


def _load_tool():
    """`tools/` is not a package, so the module is loaded by path.

    The module is registered in `sys.modules` before it executes: Python 3.14's
    `dataclasses` resolves a class's defining module through `sys.modules`, so a
    path-loaded module that is *not* registered makes every `@dataclass` in it
    fail at import with a `NoneType` error that names nothing useful.
    """
    name = "harvest_parts_tool"
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "harvest_parts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()


class StubBridge:
    """A `BridgeClient` that answers from a table and records every call."""

    def __init__(self, *, device=None, footprint=None):
        self.device = device if device is not None else _ok_device
        self.footprint = footprint if footprint is not None else _ok_footprint
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def call(self, action: str, params: dict):
        self.calls.append((action, params))
        if action == "lib.device.get":
            return _resolve(self.device, params)
        if action == "lib.footprint.get":
            return _resolve(self.footprint, params)
        raise AssertionError(f"unexpected action {action}")

    async def close(self) -> None:
        self.closed = True

    def actions(self) -> list[str]:
        return [action for action, _params in self.calls]


def _resolve(handler, params: dict):
    if isinstance(handler, Exception):
        raise handler
    return handler(params) if callable(handler) else handler


def _ok_device(params: dict) -> dict:
    # `association.footprintUuid` is the field measured on the machine.
    return {"item": {"association": {"footprintUuid": f"fp-{params['uuid'][:8]}"}}}


def _ok_footprint(params: dict) -> dict:
    return {"name": "R0402"}


def run(client: StubBridge, sources=None):
    return asyncio.run(
        TOOL.collect_footprint_names(sources or [PILLBOX], client=client)
    )


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


def test_every_device_is_asked_about_with_the_two_step_chain():
    client = StubBridge()
    answers, problems = run(client)

    wanted = devices_to_verify([PILLBOX])
    assert problems == []
    assert set(answers) == set(wanted)
    assert set(answers.values()) == {"R0402"}
    # the chain: device pair in, then that device's footprint uuid in
    assert client.actions() == ["lib.device.get", "lib.footprint.get"] * len(wanted)
    device_calls = [p for a, p in client.calls if a == "lib.device.get"]
    assert all(set(p) == {"uuid", "libraryUuid"} for p in device_calls)
    assert all(p["uuid"] in {pair[0] for pair in wanted} for p in device_calls)
    footprint_calls = [p for a, p in client.calls if a == "lib.footprint.get"]
    assert all(set(p) == {"uuid", "libraryUuid"} for p in footprint_calls)
    # ...and the footprint uuid came from the *device* dump, not from the project
    assert all(p["uuid"].startswith("fp-") for p in footprint_calls)


def test_the_chain_is_asked_once_per_device_not_once_per_placement():
    client = StubBridge()
    run(client)
    wanted = devices_to_verify([PILLBOX])
    assert len(client.calls) == 2 * len(wanted)


def test_an_injected_client_is_not_closed_by_the_tool():
    """The caller owns what the caller opened."""
    client = StubBridge()
    run(client)
    assert client.closed is False


# --------------------------------------------------------------------------
# the three failures, at the three places the chain can break
# --------------------------------------------------------------------------


def test_a_device_that_cannot_be_read_is_reported_and_changes_nothing_else():
    def device(_params: dict):
        raise RuntimeError("no such device")

    client = StubBridge(device=device)
    answers, problems = run(client)
    assert answers == {}
    assert problems and all("lib.device.get" in line for line in problems)
    # nothing was asked of the footprint action, because nothing got that far
    assert "lib.footprint.get" not in client.actions()


def test_a_device_dump_without_a_footprint_uuid_is_reported_as_unusable():
    client = StubBridge(device={"item": {"association": {"symbolUuid": "s-1"}}})
    answers, problems = run(client)
    assert answers == {}
    assert problems and all("nothing usable" in line for line in problems)
    assert "association.footprintUuid" in problems[0], (
        "the report should name the paths that were tried"
    )
    # the chain stops there rather than calling the footprint action blind
    assert "lib.footprint.get" not in client.actions()


def test_a_footprint_that_cannot_be_read_is_reported():
    client = StubBridge(footprint=RuntimeError("not found"))
    answers, problems = run(client)
    assert answers == {}
    assert problems and all("lib.footprint.get" in line for line in problems)
    assert all("via association.footprintUuid" in line for line in problems)


def test_a_footprint_that_answers_without_a_name_is_reported():
    client = StubBridge(footprint={"found": True, "name": ""})
    answers, problems = run(client)
    assert answers == {}
    assert problems and all("returned no name" in line for line in problems)


def test_one_bad_device_does_not_stop_the_others():
    """Failure is per device: the rest of the shelf still gets verified."""
    seen: list[str] = []

    def device(params: dict):
        seen.append(params["uuid"])
        if len(seen) == 1:
            raise RuntimeError("boom")
        return {"item": {"association": {"footprintUuid": f"fp-{len(seen)}"}}}

    client = StubBridge(device=device)
    answers, problems = run(client)
    wanted = devices_to_verify([PILLBOX])
    assert len(problems) == 1
    assert len(answers) == len(wanted) - 1


# --------------------------------------------------------------------------
# the end of the chain: what the harvest does with the answers
# --------------------------------------------------------------------------


def test_the_answers_feed_the_harvest_and_mark_the_names_verified():
    from boardwise.engines.harvest import harvest_board

    client = StubBridge()
    answers, problems = run(client)
    assert problems == []

    def verifier(device_uuid: str, library_uuid: str):
        return answers.get((device_uuid, library_uuid))

    entries, report = harvest_board(PILLBOX, verifier=verifier)
    assert report.ok
    assert entries
    assert all(entry.footprint_name == "R0402" for entry in entries)
    assert all(entry.footprint_name_verified is True for entry in entries)


def test_a_board_with_no_verifiable_device_is_not_an_error():
    client = StubBridge()
    answers, problems = run(client, sources=[SOURCES / "highspeed_motor_ctrl.eprj2"])
    assert answers == {} and problems == []
    assert client.calls == [], "an unreadable board produced bridge calls"


def test_the_window_hint_rides_every_frame_and_nothing_is_sent_without_one():
    """The daemon refuses an unhinted read as soon as two windows are open (023).

    Measured 2026-09-26 on this machine: 4 editor windows connected, and all 87
    devices came back "the request named no project" — `--verify` answered about
    **0** devices and wrote an unverified shelf. The hint is per *frame*, not per
    connection, so it has to be forwarded on both hops of the chain.

    The second half is the compatibility half: a caller that passes no hint must
    send no hint keyword at all, so a stub (or any pre-023 client) does not have
    to grow a keyword it never reads — which is also what keeps the other tests
    in this file working unchanged.
    """
    class HintRecording(StubBridge):
        def __init__(self):
            super().__init__()
            self.hints: list[dict] = []

        async def call(self, action: str, params: dict, **hints):
            self.hints.append(hints)
            return await super().call(action, params)

    hinted = HintRecording()
    asyncio.run(
        TOOL.collect_footprint_names(
            [PILLBOX], client=hinted,
            target_project="ROBOT ctrl FOC", target_instance="inst-1",
        )
    )
    assert hinted.hints, "no call was made"
    assert all(h == {"target_project": "ROBOT ctrl FOC", "target_instance": "inst-1"}
               for h in hinted.hints)

    plain = HintRecording()
    asyncio.run(TOOL.collect_footprint_names([PILLBOX], client=plain))
    assert plain.hints and all(h == {} for h in plain.hints)

    parser = TOOL.build_parser()
    assert parser.parse_args(["--sources", "x", "--verify"]).project is None
    hinted_args = parser.parse_args(
        ["--sources", "x", "--verify", "--project", "P", "--instance", "I"]
    )
    assert (hinted_args.project, hinted_args.instance) == ("P", "I")


# --------------------------------------------------------------------------
# the default source list (#38)
# --------------------------------------------------------------------------


def test_the_default_sources_are_the_committed_ones():
    """The shipped `--check` run must harvest the six boards the library was
    built from, read from `blocklib/harvest.sources.json`."""
    entries = json.loads(
        (ROOT / "blocklib" / "harvest.sources.json").read_text(encoding="utf-8")
    )
    assert TOOL._default_sources() == [ROOT / entry for entry in entries]
    assert all(path.is_file() for path in TOOL._default_sources()), entries


def test_an_unreadable_source_list_says_which_file(tmp_path):
    missing = tmp_path / "harvest.sources.json"
    monkey = pytest.MonkeyPatch()
    monkey.setattr(TOOL, "DEFAULT_SOURCES_FILE", missing)
    try:
        with pytest.raises(ValueError) as missing_read:
            TOOL._default_sources()
        assert str(missing) in str(missing_read.value)

        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        monkey.setattr(TOOL, "DEFAULT_SOURCES_FILE", broken)
        with pytest.raises(ValueError) as bad_json:
            TOOL._default_sources()
        assert str(broken) in str(bad_json.value)
    finally:
        monkey.undo()


def test_an_explicit_source_list_still_wins(tmp_path):
    """`--sources` is untouched: a named board is harvested even when the
    committed list cannot be read at all (the sidecar is switched off here
    because one board cannot anchor all eleven curated C-numbers)."""
    monkey = pytest.MonkeyPatch()
    monkey.setattr(TOOL, "DEFAULT_SOURCES_FILE", tmp_path / "nope.json")
    try:
        shelf = tmp_path / "shelf.json"
        code = TOOL._cli(
            ["--sources", str(PILLBOX), "--corrections-file", "-", "--out", str(shelf)]
        )
        assert code == 0
        assert json.loads(shelf.read_text(encoding="utf-8"))["parts"]
    finally:
        monkey.undo()


def test_the_shipped_check_run_needs_no_arguments(capsys):
    """The acceptance command: from the repository root, `harvest_parts.py
    --check` with no `--sources` reproduces the committed shelf (1.5 s)."""
    code = TOOL._cli(["--check"])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "matches a fresh harvest" in captured.out

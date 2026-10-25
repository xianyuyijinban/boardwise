"""537C3b1: the independent live evidence collector — fake client only.

Why this file exists. The 537 review's PCB live reading and PCB image were
chained by hand-written shell: a render failure could erase a readback that had
succeeded, a focus that had drifted let the next action read the wrong page, and
the original tab was never put back. The final report had no per-step record of
any of it.

So ``engines.liveevidence.collect_live_evidence`` is tested here against an
**anonymous fake client** (no daemon, no editor, no project file, no shell). The
contract pinned by these tests:

1. ``doc.list`` identity first: an expected project uuid that does not match (or
   cannot be read) is a structured refusal **before any navigation**; an empty
   expectation is allowed but never claims the design was verified.
2. Every selected document is opened and then independently verified through
   ``document.current``'s real ``active.uuid`` (connector 873–944) before one
   byte is read from it.
3. Steps are isolated: ``sch.readback`` / ``sch.netlist`` / ``export.render``
   each fail alone; a PCB render timeout neither erases readback/geometry nor
   stops the next board; geometry is skipped when its readback dependency is
   missing, but an empty board's ``components == []`` is a *success* and still
   calls geometry.
4. Evidence validity is stricter than a transport exit code: readback
   ``problems`` / ``unreadable`` and geometry ``meta.unreadable`` / ``reasons``
   are ``failed`` steps; a render must be ``dict`` + ``format == image/png`` +
   non-empty valid base64, and only then is a uniquely named PNG written (path,
   bytes, sha256 recorded).
5. Coverage is disclosed: an explicit subset that succeeded is ``missing``, not
   ``ok``; no PCB document is ``not-applicable``; no schematic page is
   ``failed``.
6. The original focus is restored in ``finally`` (verified again through
   ``document.current``), a failed restore is disclosed with ``focusRestore.ok =
   false``, and a missing ``active.uuid`` refuses before navigation rather than
   moving the user's editor and reporting it afterwards.
7. ``capture.ok`` is true only when all four live channels are ``ok`` /
   ``not-applicable``, identity has no error, and the focus restoration
   succeeded — never from an unverified identity.
8. The collector never opens or closes the client, and never invokes a shell.

All data is synthetic. No real project name, netlist or image is used.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path

import pytest

SCHEMA = "boardwise.live-evidence/1"
PROJECT = "proj-synthetic"
PAGES = (("p1", "PWR"), ("p2", "CTRL"))
PCBS = (("b1", "B1"),)
ROUTE = {"target_project": "test2", "target_instance": "win-1"}

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"synthetic-png-body"
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")

STEP_KEYS = {
    "documentUuid",
    "action",
    "status",
    "stdout",
    "stderr",
    "exitCode",
    "error",
}
CHANNEL_KEYS = {"status", "source", "detail", "artifacts", "errors", "steps"}
ROOT_KEYS = {
    "schema",
    "ok",
    "executor",
    "identity",
    "selection",
    "channels",
    "steps",
    "artifacts",
    "focusRestore",
}
LIVE_CHANNELS = ["liveSchematic", "livePcb", "schematicImage", "pcbImage"]
SOURCES = {
    "liveSchematic": "live-sch",
    "livePcb": "live-pcb",
    "schematicImage": "image",
    "pcbImage": "image",
}
ALLOWED_ACTIONS = {
    "doc.list",
    "doc.open",
    "document.current",
    "sch.readback",
    "sch.netlist",
    "pcb.readback",
    "pcb.geometry",
    "export.render",
}
READ_ACTIONS = {"sch.readback", "sch.netlist", "pcb.readback", "pcb.geometry", "export.render"}


class FakeBridgeError(Exception):
    """The shape the collector may see from a real ``BridgeClient`` call."""

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
    focused=True,
) -> dict:
    documents = [
        {"uuid": uuid, "name": name, "type": "page"} for uuid, name in pages
    ] + [
        {"uuid": uuid, "name": name, "type": "pcb"} for uuid, name in pcbs
    ]
    projects = []
    if project_uuid is not None:
        projects = [{
            "projectUuid": project_uuid,
            "friendlyName": "synthetic",
            "focused": focused,
            "schematics": [],
            "pcbs": [],
            "documents": "full" if focused else "brief",
        }]
    return {
        "documents": documents,
        "projects": projects,
        "active": {"uuid": active} if active else None,
        "count": len(documents),
    }


class FakeClient:
    """An anonymous bridge client: every call is recorded, nothing is executed.

    ``overrides`` maps an action to either a payload or a ``handler(client,
    params)`` returning a payload (or raising). The default handlers mimic the
    real connector's answer shapes — in particular ``document.current`` answers
    ``{"active": {"uuid": ..., "type": ...}}``, the field the real host uses
    (connector ``documentCurrent``), never an invented ``document.uuid``.
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
        if action == "sch.netlist":
            return {"type": "EasyEDA", "text": "NETLIST SYNTHETIC\n"}
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
        if action == "export.render":
            return {"format": "image/png", "data": PNG_B64}
        raise AssertionError(f"unexpected action {action!r}")

    async def close(self):
        self.close_calls += 1


def collect(
    client,
    tmp_path,
    *,
    expected=PROJECT,
    route=ROUTE,
    page_uuids=None,
    pcb_uuids=None,
    out_name="evidence",
):
    from boardwise.engines.liveevidence import collect_live_evidence

    out_dir = Path(tmp_path) / out_name
    capture = asyncio.run(
        collect_live_evidence(
            client,
            out_dir=out_dir,
            route_kwargs=dict(route) if route is not None else None,
            page_uuids=page_uuids,
            pcb_uuids=pcb_uuids,
            expected_project_uuid=expected,
        )
    )
    return capture, out_dir


def steps_for(capture, document_uuid):
    return [
        step for step in capture["steps"]
        if step["documentUuid"] == document_uuid
    ]


def actions_for(capture, document_uuid):
    return [step["action"] for step in steps_for(capture, document_uuid)]


def step_named(capture, document_uuid, action):
    matches = [
        step for step in capture["steps"]
        if step["documentUuid"] == document_uuid and step["action"] == action
    ]
    assert len(matches) == 1, (document_uuid, action, matches)
    return matches[0]


def calls_named(client, action):
    return [call for call in client.calls if call["action"] == action]


def assert_steps_well_formed(capture):
    assert capture["steps"], "a capture without steps claims evidence it did not record"
    for step in capture["steps"]:
        assert set(step) == STEP_KEYS, step
        assert step["status"] in {"ok", "failed", "skipped"}, step
        assert isinstance(step["documentUuid"], str), step
        assert isinstance(step["action"], str) and step["action"], step
        assert isinstance(step["stdout"], str) and len(step["stdout"]) <= 2000, step
        assert isinstance(step["stderr"], str), step
        if step["status"] == "ok":
            assert step["exitCode"] == 0, step
            assert step["error"] is None, step
        elif step["status"] == "failed":
            assert step["exitCode"] == 1, step
            assert isinstance(step["error"], dict), step
            assert step["error"].get("code") and step["error"].get("message"), step
            assert step["stderr"], step
        else:
            assert step["exitCode"] is None, step
            assert step["error"] is None or isinstance(step["error"], dict), step


# ---------------------------------------------------------------------------
# 1. the happy path: four ok channels, real files, a frozen JSON shape
# ---------------------------------------------------------------------------


def test_all_success_records_the_order_writes_hashed_images_and_a_json_capture(tmp_path):
    listing = make_listing()
    client = FakeClient(listing, overrides={
        "pcb.readback": {
            "kind": "pcb",
            "components": [
                {"primitiveId": "pcb-prim-1", "designator": "R1"},
                {"primitiveId": "pcb-prim-2", "designator": "C1"},
            ],
            "primitives": [],
            "componentCount": 2,
        },
    })

    capture, out_dir = collect(client, tmp_path)

    assert set(capture) == ROOT_KEYS
    assert capture["schema"] == SCHEMA
    assert capture["executor"] == "bridge-client"
    assert capture["ok"] is True
    assert list(capture["channels"]) == LIVE_CHANNELS

    identity = capture["identity"]
    assert identity["ok"] is True
    assert identity["expectedProjectUuid"] == PROJECT
    assert identity["projectUuid"] == PROJECT
    assert identity["verifiedAgainstReport"] is True
    assert identity["error"] is None

    selection = capture["selection"]
    assert selection["ok"] is True
    for kind in ("schematic", "pcb"):
        assert selection[kind]["coversAll"] is True, kind
        assert selection[kind]["explicit"] is False, kind

    assert capture["focusRestore"]["ok"] is True
    assert capture["focusRestore"]["attempted"] is True
    assert capture["focusRestore"]["originalUuid"] == "p2"
    assert capture["focusRestore"]["error"] is None
    assert client.active == "p2", "the collector must put the original tab back"

    # Per-document order is the contract: open → verify focus → readback →
    # (netlist once, on the first schematic page) → render.
    assert actions_for(capture, "p1") == [
        "doc.open", "document.current", "sch.readback", "sch.netlist",
        "export.render",
    ]
    p2_actions = actions_for(capture, "p2")
    assert p2_actions[:4] == [
        "doc.open", "document.current", "sch.readback", "export.render",
    ]
    assert p2_actions[-2:] == ["doc.open", "document.current"], "restore steps"
    assert actions_for(capture, "b1") == [
        "doc.open", "document.current", "pcb.readback", "pcb.geometry",
        "export.render",
    ]

    # The netlist is one call for the whole run, and the rest of the parameters
    # are the ones the real actions take.
    assert len(calls_named(client, "sch.netlist")) == 1
    assert calls_named(client, "sch.netlist")[0]["params"] == {"type": "EasyEDA"}
    for call in calls_named(client, "sch.readback") + calls_named(client, "pcb.readback"):
        assert call["params"].get("includePrimitives") is True
    assert calls_named(client, "pcb.geometry")[0]["params"]["bboxIds"] == [
        "pcb-prim-1", "pcb-prim-2",
    ]
    render_calls = calls_named(client, "export.render")
    assert len(render_calls) == 3
    for call in render_calls:
        assert call["params"]["format"] == "png"
        assert call["params"]["scope"] == "page"
        assert call["params"]["timeoutMs"] == 10000
        assert call["params"]["pageUuid"] in {"p1", "p2", "b1"}
    file_names = [call["params"]["fileName"] for call in render_calls]
    assert len(set(file_names)) == 3, "render file names must be unique"
    assert any(name.startswith("live-sch-") for name in file_names)
    assert any(name.startswith("live-pcb-") for name in file_names)

    assert_steps_well_formed(capture)

    # Artifacts: two schematic PNGs, one PCB PNG, one netlist text — all on
    # disk, relative, and hash-verified.
    artifacts = capture["artifacts"]
    pngs = [row for row in artifacts if str(row["file"]).endswith(".png")]
    netlists = [row for row in artifacts if row.get("kind") == "netlist"]
    assert len(pngs) == 3
    assert len(netlists) == 1
    for row in artifacts:
        assert not Path(row["file"]).is_absolute()
        target = out_dir / row["file"]
        assert target.is_file(), row
        blob = target.read_bytes()
        assert len(blob) == row["bytes"]
        assert hashlib.sha256(blob).hexdigest() == row["sha256"]
        assert row["documentUuid"] in {"p1", "p2", "b1"}
    assert (out_dir / netlists[0]["file"]).read_text(encoding="utf-8") == (
        "NETLIST SYNTHETIC\n"
    )

    for name in LIVE_CHANNELS:
        row = capture["channels"][name]
        assert set(row) == CHANNEL_KEYS, name
        assert row["status"] == "ok", name
        assert row["source"] == SOURCES[name], name
        assert isinstance(row["detail"], str) and row["detail"], name
        assert row["errors"] == [], name
        assert isinstance(row["steps"], list), name

    # Each channel carries only the steps of its own reading.
    live_steps = {step["action"] for step in capture["channels"]["liveSchematic"]["steps"]}
    assert {"doc.open", "document.current", "sch.readback", "sch.netlist"} <= live_steps
    assert "export.render" not in live_steps
    image_steps = {
        step["action"] for step in capture["channels"]["schematicImage"]["steps"]
    }
    assert image_steps == {"doc.open", "document.current", "export.render"}
    pcb_steps = {step["action"] for step in capture["channels"]["livePcb"]["steps"]}
    assert {"pcb.readback", "pcb.geometry"} <= pcb_steps
    assert {
        row["file"] for row in capture["channels"]["schematicImage"]["artifacts"]
    } == {row["file"] for row in pngs if row["channel"] == "schematicImage"}
    assert [row["file"] for row in capture["channels"]["liveSchematic"]["artifacts"]] == [
        netlists[0]["file"],
    ]

    # The whole capture is JSON-serialisable, losslessly.
    assert json.loads(json.dumps(capture, ensure_ascii=False)) == capture

    # The collector neither opens nor closes the client: the CLI owns its life.
    assert client.close_calls == 0


def test_empty_components_on_an_empty_board_still_calls_geometry(tmp_path):
    """Empty components is a valid reading, not a failed readback (pin)."""
    client = FakeClient(make_listing(pages=(), pcbs=(("b1", "B1"),)))

    capture, _ = collect(client, tmp_path)

    readback = step_named(capture, "b1", "pcb.readback")
    geometry = step_named(capture, "b1", "pcb.geometry")
    assert readback["status"] == "ok"
    assert geometry["status"] == "ok"
    assert calls_named(client, "pcb.geometry")[0]["params"]["bboxIds"] == []
    assert capture["channels"]["livePcb"]["status"] == "ok"
    assert capture["channels"]["pcbImage"]["status"] == "ok"


# ---------------------------------------------------------------------------
# 2. focus safety: verify first, never read a wrong page
# ---------------------------------------------------------------------------


def test_one_page_focus_failure_skips_that_page_but_not_the_other(tmp_path):
    listing = make_listing(active="home")
    client = FakeClient(listing, ignore_open={"p1"})

    capture, out_dir = collect(client, tmp_path)

    p1 = steps_for(capture, "p1")
    assert [step["action"] for step in p1] == [
        "doc.open", "document.current", "sch.readback", "sch.netlist",
        "export.render",
    ]
    assert [step["status"] for step in p1] == [
        "ok", "failed", "skipped", "skipped", "skipped",
    ]
    assert p1[1]["error"]["code"] == "FOCUS_MISMATCH"
    for step in p1[2:]:
        assert step["exitCode"] is None
        assert step["error"]["code"] == "SKIPPED"

    # Nothing was read or rendered while the editor was still on the wrong page.
    for call in calls_named(client, "sch.readback") + calls_named(
        client, "sch.netlist"
    ) + calls_named(client, "export.render"):
        assert call["active"] != "home", call
        if call["action"] == "export.render":
            assert call["active"] == call["params"]["pageUuid"], call

    # The other page still ran to completion, and the (project-level) netlist
    # moved to the first page whose focus was actually proven.
    p2_actions = actions_for(capture, "p2")
    assert p2_actions[:5] == [
        "doc.open", "document.current", "sch.readback", "sch.netlist",
        "export.render",
    ]
    assert step_named(capture, "p2", "sch.readback")["status"] == "ok"
    # The netlist is attempted once, on the first page that really focused.
    assert len(calls_named(client, "sch.netlist")) == 1
    assert calls_named(client, "sch.netlist")[0]["active"] == "p2"

    assert capture["channels"]["schematicImage"]["status"] == "failed"
    assert capture["channels"]["liveSchematic"]["status"] == "failed"
    assert capture["channels"]["schematicImage"]["artifacts"], "p2's image survives"
    assert capture["ok"] is False
    assert (out_dir / capture["channels"]["schematicImage"]["artifacts"][0]["file"]).is_file()


def test_current_reporting_another_document_stops_all_reads_and_discloses_restore(tmp_path):
    client = FakeClient(
        make_listing(),
        overrides={
            "document.current": {
                "active": {"uuid": "someone-else", "type": "page"},
                "type": "page",
                "typeSource": "getCurrentDocumentInfo",
            },
        },
    )

    capture, out_dir = collect(client, tmp_path)

    assert not [call for call in client.calls if call["action"] in READ_ACTIONS]
    assert not list(out_dir.glob("*")), "no evidence file may be written for an unverified focus"
    for step in capture["steps"]:
        if step["action"] == "document.current":
            assert step["status"] == "failed"
            assert step["error"]["code"] == "FOCUS_MISMATCH"
    assert capture["focusRestore"]["ok"] is False
    assert capture["focusRestore"]["error"]["code"] == "FOCUS_MISMATCH"
    assert capture["ok"] is False
    for name in LIVE_CHANNELS:
        assert capture["channels"][name]["status"] == "failed", name


def test_document_current_problems_mean_focus_is_not_verified(tmp_path):
    client = FakeClient(make_listing(), current_problems=["stale tab tree"])
    capture, out_dir = collect(client, tmp_path)

    assert not [call for call in client.calls if call["action"] in READ_ACTIONS]
    current = steps_for(capture, "p1")[1]
    assert current["status"] == "failed"
    assert current["error"]["code"] == "FOCUS_UNREADABLE"
    assert capture["ok"] is False


def test_missing_active_uuid_refuses_before_any_navigation(tmp_path):
    """Restoring an unknown "no active page" state cannot be promised after the
    fact, so the collector must not move the tab at all."""
    client = FakeClient(make_listing(active=None))

    capture, out_dir = collect(client, tmp_path)

    assert [call["action"] for call in client.calls] == ["doc.list"]
    restore = capture["focusRestore"]
    assert restore["ok"] is False
    assert restore["attempted"] is False
    assert restore["status"] == "unavailable"
    assert restore["error"]["code"] == "FOCUS_UNAVAILABLE"
    assert restore["originalUuid"] is None
    assert capture["ok"] is False
    assert not list(out_dir.glob("*"))
    for name in LIVE_CHANNELS:
        assert capture["channels"][name]["status"] == "missing", name


def test_when_no_selected_document_needs_navigation_focus_is_not_applicable(tmp_path):
    client = FakeClient(make_listing(active=None))

    capture, _ = collect(client, tmp_path, page_uuids=[], pcb_uuids=[])

    assert not calls_named(client, "doc.open")
    restore = capture["focusRestore"]
    assert restore["ok"] is True
    assert restore["attempted"] is False
    assert restore["status"] == "not-applicable"
    assert capture["channels"]["liveSchematic"]["status"] == "missing"
    assert capture["channels"]["livePcb"]["status"] == "missing"


# ---------------------------------------------------------------------------
# 3. step isolation: one failure never erases the others
# ---------------------------------------------------------------------------


def test_pcb_render_timeout_keeps_readback_and_geometry_and_continues(tmp_path):
    listing = make_listing(pages=(), pcbs=(("b1", "B1"), ("b2", "B2")))

    def render(client, params):
        if params.get("pageUuid") == "b1":
            raise FakeBridgeError("TIMEOUT", "export.render hung on b1")
        return {"format": "image/png", "data": PNG_B64}

    client = FakeClient(listing, overrides={"export.render": render})

    capture, out_dir = collect(client, tmp_path)

    b1 = {step["action"]: step for step in steps_for(capture, "b1")}
    assert b1["pcb.readback"]["status"] == "ok"
    assert b1["pcb.geometry"]["status"] == "ok"
    assert b1["export.render"]["status"] == "failed"
    assert b1["export.render"]["error"]["code"] == "TIMEOUT"
    assert actions_for(capture, "b2") == [
        "doc.open", "document.current", "pcb.readback", "pcb.geometry",
        "export.render",
    ]
    assert step_named(capture, "b2", "export.render")["status"] == "ok"
    assert capture["channels"]["livePcb"]["status"] == "ok"
    assert capture["channels"]["pcbImage"]["status"] == "failed"
    assert [row["documentUuid"] for row in capture["channels"]["pcbImage"]["artifacts"]] == [
        "b2",
    ]
    assert capture["ok"] is False


@pytest.mark.parametrize(
    "readback",
    [
        FakeBridgeError("CONNECTOR_ERROR", "pcb readback exploded"),
        {"kind": "pcb", "components": [], "problems": ["stale view"]},
        {"kind": "pcb", "components": [], "unreadable": 2, "reason": "null holes"},
    ],
    ids=["exception", "problems", "unreadable"],
)
def test_geometry_is_skipped_when_its_readback_dependency_is_missing(
    tmp_path, readback
):
    client = FakeClient(
        make_listing(pages=(), pcbs=(("b1", "B1"),)),
        overrides={"pcb.readback": readback},
    )

    capture, _ = collect(client, tmp_path)

    assert step_named(capture, "b1", "pcb.readback")["status"] == "failed"
    geometry = step_named(capture, "b1", "pcb.geometry")
    assert geometry["status"] == "skipped"
    assert geometry["error"]["code"] == "DEPENDENCY_MISSING"
    assert geometry["exitCode"] is None
    assert not calls_named(client, "pcb.geometry"), "no fake empty-ids geometry call"
    # The render is still attempted independently, and its success is kept.
    assert step_named(capture, "b1", "export.render")["status"] == "ok"
    assert capture["channels"]["livePcb"]["status"] == "failed"
    assert capture["channels"]["pcbImage"]["status"] == "ok"
    assert capture["ok"] is False


def test_a_failed_write_still_runs_the_render_and_keeps_its_image(tmp_path):
    client = FakeClient(
        make_listing(),
        overrides={
            "sch.readback": FakeBridgeError("PAGE_MISMATCH", "focus moved"),
        },
    )

    capture, out_dir = collect(client, tmp_path)

    assert step_named(capture, "p1", "sch.readback")["status"] == "failed"
    assert step_named(capture, "p1", "export.render")["status"] == "ok"
    assert capture["channels"]["liveSchematic"]["status"] == "failed"
    assert capture["channels"]["schematicImage"]["status"] == "ok"
    assert len(list(out_dir.glob("*.png"))) == 3


# ---------------------------------------------------------------------------
# 4. evidence validity: exit 0 is not the same as usable evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "readback",
    [
        {"kind": "sch", "components": [], "problems": ["stale view"]},
        {"kind": "sch", "components": [], "unreadable": 1, "reason": "null hole"},
    ],
    ids=["problems", "unreadable"],
)
def test_readback_problems_or_unreadable_is_a_failed_step_even_on_exit_zero(
    tmp_path, readback
):
    client = FakeClient(make_listing(), overrides={"sch.readback": readback})

    capture, _ = collect(client, tmp_path)

    step = step_named(capture, "p1", "sch.readback")
    assert step["status"] == "failed"
    assert step["error"]["code"] == "READBACK_PROBLEMS"
    assert capture["channels"]["liveSchematic"]["status"] == "failed"
    assert capture["ok"] is False


@pytest.mark.parametrize(
    ("action", "payload", "target", "channel"),
    [
        ("sch.readback", {"kind": "pcb", "components": []}, "p1", "liveSchematic"),
        ("pcb.readback", {"kind": "sch", "components": []}, "b1", "livePcb"),
        ("sch.readback", {"components": []}, "p1", "liveSchematic"),
    ],
    ids=["sch-answered-with-pcb", "pcb-answered-with-sch", "kind-missing"],
)
def test_readback_kind_must_match_the_namespace_that_was_requested(
    tmp_path, action, payload, target, channel
):
    """A read that cannot name its namespace is not a clean read.

    `pcb.readback` returning `kind="sch"` (or no `kind` at all) is exactly the
    wrong-namespace shape 527B's guard exists for; exit 0 must not turn it into
    evidence.
    """
    client = FakeClient(make_listing(), overrides={action: payload})

    capture, _ = collect(client, tmp_path)

    step = step_named(capture, target, action)
    assert step["status"] == "failed"
    assert step["error"]["code"] == "READBACK_KIND_MISMATCH"
    assert capture["channels"][channel]["status"] == "failed"
    assert capture["ok"] is False


def test_geometry_meta_unreadable_is_failed_even_with_bboxes(tmp_path):
    client = FakeClient(
        make_listing(pages=(), pcbs=(("b1", "B1"),)),
        overrides={
            "pcb.geometry": {
                "bboxes": {"pcb-prim-1": {"minX": 0, "minY": 0, "maxX": 1, "maxY": 1}},
                "meta": {"unreadable": ["pcb-prim-1: no finite box"]},
            },
        },
    )

    capture, _ = collect(client, tmp_path)

    step = step_named(capture, "b1", "pcb.geometry")
    assert step["status"] == "failed"
    assert step["error"]["code"] == "GEOMETRY_UNREADABLE"
    assert capture["channels"]["livePcb"]["status"] == "failed"
    assert capture["channels"]["pcbImage"]["status"] == "ok"


@pytest.mark.parametrize(
    ("geometry", "code"),
    [
        ({"bboxes": {}}, "GEOMETRY_NO_META"),
        (
            {"bboxes": {}, "meta": {"available": {"bboxes": False},
                                    "requested": 1, "measured": 0}},
            "GEOMETRY_UNAVAILABLE",
        ),
        (
            {"bboxes": {}, "meta": {"available": {"bboxes": True},
                                    "requested": 2, "measured": 1}},
            "GEOMETRY_INCOMPLETE",
        ),
        (
            {"bboxes": {}, "meta": {"available": {"bboxes": True}}},
            "GEOMETRY_INCOMPLETE",
        ),
    ],
    ids=["no-meta", "bboxes-unavailable", "requested-gt-measured", "no-counts"],
)
def test_geometry_without_a_complete_meta_cannot_be_ok(tmp_path, geometry, code):
    client = FakeClient(
        make_listing(pages=(), pcbs=(("b1", "B1"),)),
        overrides={"pcb.geometry": geometry},
    )

    capture, _ = collect(client, tmp_path)

    step = step_named(capture, "b1", "pcb.geometry")
    assert step["status"] == "failed"
    assert step["error"]["code"] == code
    assert capture["channels"]["livePcb"]["status"] == "failed"
    # The picture is still independent evidence and survives the geometry fail.
    assert capture["channels"]["pcbImage"]["status"] == "ok"
    assert capture["ok"] is False


def test_an_empty_netlist_is_failed_and_not_called_again(tmp_path):
    client = FakeClient(
        make_listing(), overrides={"sch.netlist": {"type": "EasyEDA", "text": "  \n"}}
    )

    capture, _ = collect(client, tmp_path)

    assert len(calls_named(client, "sch.netlist")) == 1
    netlist = step_named(capture, "p1", "sch.netlist")
    assert netlist["status"] == "failed"
    assert netlist["error"]["code"] == "NETLIST_EMPTY"
    assert capture["channels"]["liveSchematic"]["status"] == "failed"
    assert capture["channels"]["schematicImage"]["status"] == "ok"
    assert capture["ok"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"format": "image/png", "data": ""},
        {"format": "image/png", "data": "!!!not-base64!!!"},
        {"format": "application/zip", "data": PNG_B64},
        "not-a-dict",
        {"format": "image/png", "data": base64.b64encode(b"PK\x03\x04zip").decode("ascii")},
    ],
    ids=["empty", "bad-base64", "zip-format", "not-a-dict", "zip-bytes"],
)
def test_invalid_render_payload_is_failed_and_never_written(tmp_path, payload):
    client = FakeClient(
        make_listing(pcbs=()), overrides={"export.render": payload}
    )

    capture, out_dir = collect(client, tmp_path)

    for step in [row for row in capture["steps"] if row["action"] == "export.render"]:
        assert step["status"] == "failed", step
        assert step["error"]["code"].startswith("RENDER_"), step
    assert not list(out_dir.glob("*.png"))
    assert capture["channels"]["schematicImage"]["status"] == "failed"
    assert capture["channels"]["schematicImage"]["artifacts"] == []
    assert capture["ok"] is False


def test_valid_base64_without_a_png_signature_is_not_written(tmp_path):
    """`image/png` + valid base64 is a claim; the 8-byte signature is the file."""
    payload = {
        "format": "image/png",
        "data": base64.b64encode(b"definitely-not-a-png").decode("ascii"),
    }
    client = FakeClient(make_listing(pcbs=()), overrides={"export.render": payload})

    capture, out_dir = collect(client, tmp_path)

    step = step_named(capture, "p1", "export.render")
    assert step["status"] == "failed"
    assert step["error"]["code"] == "RENDER_NOT_IMAGE"
    assert "PNG" in step["error"]["message"]
    assert not list(out_dir.glob("*.png"))
    assert capture["channels"]["schematicImage"]["status"] == "failed"
    assert capture["ok"] is False


def test_an_unusable_doc_list_is_unknown_not_no_documents(tmp_path):
    """A broken listing is not evidence that the project has no PCB/page.

    Missing `documents` (or a non-list, or a thrown call) means the document set
    is unknown: every live channel is ``missing`` and nothing is navigated —
    never `not-applicable` / `failed`, which would claim a confirmed absence.
    """
    base = make_listing()
    cases = {
        "exception": FakeBridgeError("TIMEOUT", "doc.list hung"),
        "missing-documents": {
            key: value for key, value in base.items() if key != "documents"
        },
        "documents-not-a-list": {**base, "documents": "brief"},
    }
    for label, override in cases.items():
        client = FakeClient(base, overrides={"doc.list": override})

        capture, out_dir = collect(client, tmp_path, out_name=f"evidence-{label}")

        assert [call["action"] for call in client.calls] == ["doc.list"], label
        assert capture["ok"] is False, label
        assert capture["focusRestore"]["attempted"] is False, label
        for name in LIVE_CHANNELS:
            assert capture["channels"][name]["status"] == "missing", (label, name)
        listing_step = capture["steps"][0]
        assert listing_step["action"] == "doc.list", label
        assert listing_step["status"] == "failed", label
        if label != "exception":
            assert listing_step["error"]["code"] == "DOC_LIST_INVALID", label
            assert capture["selection"]["schematic"]["available"] == [], label
        assert not list(out_dir.glob("*")), label


# ---------------------------------------------------------------------------
# 5. identity and selection are refusals before navigation
# ---------------------------------------------------------------------------


def test_an_expected_project_mismatch_is_a_structured_refusal(tmp_path):
    client = FakeClient(make_listing())

    capture, out_dir = collect(client, tmp_path, expected="proj-other")

    assert [call["action"] for call in client.calls] == ["doc.list"]
    identity = capture["identity"]
    assert identity["ok"] is False
    assert identity["verifiedAgainstReport"] is False
    assert identity["error"]["code"] == "PROJECT_IDENTITY_MISMATCH"
    assert identity["error"]["expected"] == "proj-other"
    assert identity["error"]["actual"] == PROJECT
    assert capture["ok"] is False
    assert not list(out_dir.glob("*"))
    for name in LIVE_CHANNELS:
        assert capture["channels"][name]["status"] == "missing", name


def test_an_empty_expectation_collects_but_never_claims_verification(tmp_path):
    client = FakeClient(make_listing())

    capture, _ = collect(client, tmp_path, expected="")

    assert capture["identity"]["ok"] is True
    assert capture["identity"]["error"] is None
    assert capture["identity"]["verifiedAgainstReport"] is False
    assert capture["identity"]["projectUuid"] == PROJECT
    assert capture["ok"] is True
    # Nothing in the capture may claim the design identity was confirmed.
    assert capture["identity"].get("verified") is not True


@pytest.mark.parametrize("unknown", ["ghost", "b1"])
def test_an_explicit_id_outside_its_type_is_rejected_before_navigation(
    tmp_path, unknown
):
    client = FakeClient(make_listing())

    capture, out_dir = collect(client, tmp_path, page_uuids=[unknown])

    assert [call["action"] for call in client.calls] == ["doc.list"]
    selection = capture["selection"]
    assert selection["ok"] is False
    assert selection["schematic"]["unknown"] == [unknown]
    assert selection["error"]["code"] == "UNKNOWN_DOCUMENT_UUID"
    assert capture["ok"] is False
    assert not list(out_dir.glob("*"))


def test_an_explicit_subset_that_succeeds_is_missing_not_ok(tmp_path):
    client = FakeClient(make_listing())

    capture, out_dir = collect(client, tmp_path, page_uuids=["p1"])

    assert capture["selection"]["schematic"]["coversAll"] is False
    assert capture["selection"]["schematic"]["explicit"] is True
    # p2 is never *read*; the only p2 `doc.open` left is the final focus restore.
    assert not [call for call in calls_named(client, "sch.readback") if call["active"] == "p2"]
    assert len(calls_named(client, "sch.netlist")) == 1
    assert calls_named(client, "sch.netlist")[0]["active"] == "p1"
    assert step_named(capture, "p1", "sch.readback")["status"] == "ok"
    assert capture["channels"]["liveSchematic"]["status"] == "missing"
    assert capture["channels"]["schematicImage"]["status"] == "missing"
    assert capture["channels"]["livePcb"]["status"] == "ok"
    assert capture["channels"]["pcbImage"]["status"] == "ok"
    assert capture["ok"] is False
    assert len(list(out_dir.glob("*.png"))) == 2  # p1 + b1


def test_no_pcb_document_is_not_applicable_not_missing(tmp_path):
    client = FakeClient(make_listing(pcbs=()))

    capture, _ = collect(client, tmp_path)

    assert capture["channels"]["livePcb"]["status"] == "not-applicable"
    assert capture["channels"]["pcbImage"]["status"] == "not-applicable"
    assert not calls_named(client, "pcb.readback")
    assert not calls_named(client, "export.render") or all(
        call["params"]["pageUuid"] in {"p1", "p2"}
        for call in calls_named(client, "export.render")
    )
    assert capture["channels"]["liveSchematic"]["status"] == "ok"
    assert capture["channels"]["schematicImage"]["status"] == "ok"
    assert capture["ok"] is True


def test_no_schematic_page_is_failed_not_missing(tmp_path):
    client = FakeClient(make_listing(pages=(), pcbs=(("b1", "B1"),)))

    capture, _ = collect(client, tmp_path)

    assert capture["channels"]["liveSchematic"]["status"] == "failed"
    assert capture["channels"]["schematicImage"]["status"] == "failed"
    assert not calls_named(client, "sch.readback")
    assert not calls_named(client, "sch.netlist")


# ---------------------------------------------------------------------------
# 6. failure isolation in the finally: focus is restored or disclosed
# ---------------------------------------------------------------------------


def test_an_unexpected_exception_still_restores_the_original_focus(tmp_path):
    client = FakeClient(
        make_listing(),
        overrides={"sch.readback": RuntimeError("synthetic boom")},
    )

    capture, _ = collect(client, tmp_path)

    step = step_named(capture, "p1", "sch.readback")
    assert step["status"] == "failed"
    assert step["error"]["code"] == "RuntimeError"
    assert "synthetic boom" in step["error"]["message"]
    assert capture["focusRestore"]["ok"] is True
    assert capture["focusRestore"]["attempted"] is True
    assert client.active == "p2"
    assert actions_for(capture, "p2")[-2:] == ["doc.open", "document.current"]
    assert capture["ok"] is False


def test_a_failed_restore_is_disclosed_and_never_silently_ignored(tmp_path):
    # (a) the restore call itself refuses.
    client = FakeClient(
        make_listing(pages=(("p1", "PWR"),)),
        open_fail={"p2"},
    )
    capture, _ = collect(client, tmp_path)
    restore = capture["focusRestore"]
    assert restore["ok"] is False
    assert restore["attempted"] is True
    assert restore["error"]["code"] == "NOT_FOUND"
    assert capture["ok"] is False

    # (b) the restore call answers but the editor stays elsewhere: the second
    # `document.current` is what catches it.
    client2 = FakeClient(
        make_listing(pages=(("p1", "PWR"),)),
        ignore_open={"p2"},
    )
    capture2, _ = collect(client2, tmp_path, out_name="evidence-2")
    restore2 = capture2["focusRestore"]
    assert restore2["ok"] is False
    assert restore2["error"]["code"] == "FOCUS_MISMATCH"
    assert capture2["ok"] is False


# ---------------------------------------------------------------------------
# 7. transport discipline: route kwargs, no shell, no client lifecycle
# ---------------------------------------------------------------------------


def test_route_kwargs_are_passed_to_every_single_call(tmp_path):
    client = FakeClient(make_listing())
    collect(client, tmp_path)

    assert len(client.calls) > 8
    for call in client.calls:
        assert call["route"] == ROUTE, call

    client2 = FakeClient(make_listing())
    collect(client2, tmp_path, route=None, out_name="evidence-2")
    for call in client2.calls:
        assert call["route"] == {}, call


def test_the_collector_has_no_shell_and_no_client_lifecycle(tmp_path):
    from boardwise.engines import liveevidence

    source = Path(liveevidence.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "shell=True",
        "Popen",
        "create_subprocess",
        "from boardwise import cli",
        "import boardwise.cli",
        "from .checkup",
        "from boardwise.engines.checkup",
    ):
        assert forbidden not in source, forbidden
    assert ".close(" not in source and "client.close" not in source, (
        "the CLI owns the client's lifecycle"
    )

    client = FakeClient(make_listing())
    capture, _ = collect(client, tmp_path)
    assert client.close_calls == 0
    assert {call["action"] for call in client.calls} <= ALLOWED_ACTIONS
    assert_steps_well_formed(capture)

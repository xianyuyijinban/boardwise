"""054 stage C1: `draw compile` / `draw plan` / `draw apply`, against a fake editor.

The seams are named, the way 036's are:

* **the editor** is a fake that keeps a *mutable page* — `place_component`,
  `place_wire` and `place_power` really land in it, and `sch.geometry` /
  `sch.component_pins` are read back from it. That is what makes "the read-back
  decided the run" a claim about the flow rather than about a fixture someone
  wrote twice: the only way the happy path passes is if the writes put the plan's
  own geometry on the fake canvas;
* **the netlist** is hand-written per test (`sch.netlist` answers a payload the
  test chose) — the net partition is the *expectation*, and deriving it from the
  implementation would be the second judgement this repo forbids;
* **the project export** is monkeypatched (`cli._live_project_export` /
  `cli._model_from_export` / `cli._baseline_findings`), because a fixture cannot
  grow a part between two reads;
* **the specs** are the hand-written fixtures under `tests/fixtures/drawapply/`.

What each of the seven acceptance cases (054 §五) needs is asserted here for the
ones a fake can decide — C1-C6 offline. C7 (a daemon pulled out mid-run) is a real
machine case and is reported by the batch, not faked.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.changeplan import DRAW_MODULE_KIND, ChangePlan
from boardwise.engines import drawapply

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "drawapply"
CIRCUIT = FIXTURES / "divider.circuit.json"
PRESENTATION = FIXTURES / "divider.presentation.json"
LIBRARY = FIXTURES / "library.json"
PAGE_BOX = "0,-1000,1200,0"
LCSC = {"R1": "C25744", "R2": "C25744"}
FRAME = {"minX": 0, "minY": -1000, "maxX": 1200, "maxY": 0}

#: The pin geometry the fake library answers with, keyed by LCSC number. `R0402`
#: in the fixture library has its tips 50 units above and below the origin, and a
#: fake that answered anything else would be the C6 failure on purpose.
PIN_OFFSETS = {"C25744": {"1": (0.0, 50.0), "2": (0.0, -50.0)}}


class _BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _FakeEditor:
    """A page that the draw flow can really write to, and read back from."""

    def __init__(
        self,
        *,
        page: str = "page-1",
        exists: bool = True,
        pin_offsets: dict | None = None,
        netlists: list[dict] | None = None,
        save_ok: bool = True,
        unresolved: tuple[str, ...] = (),
        timeouts: tuple[str, ...] = (),
        render_ok: bool = True,
        value_write_lands: bool = True,
        document_source: str = "",
        source_write_lands: bool = True,
        source_uuid: str | None = None,
        source_type: str = "page",
        source_grow_on_write: int = 0,
        source_hide_truncated: bool = False,
        active_page: str | None = None,
        focus_refused: bool = False,
    ):
        self.page = page
        self.exists = exists
        self.components: dict[str, dict] = {}
        self.wires: list[dict] = []
        self.flags: list[dict] = []
        self.pin_offsets = pin_offsets if pin_offsets is not None else PIN_OFFSETS
        self.netlists = list(netlists or [])
        self.netlist_reads = 0
        self.calls: list[str] = []
        self.writes: list[tuple[str, dict]] = []
        self.save_ok = save_ok
        self.unresolved = set(unresolved)
        self.timeouts = set(timeouts)
        self.render_ok = render_ok
        self.created = False
        #: The attribute map the page keeps per part (`OtherProperty`), and
        #: whether `sch.set_component_attribute` actually lands in it — the
        #: second one is how 055 G2's "the value did not land" is faked.
        self.values: dict[str, dict] = {}
        self.value_write_lands = value_write_lands
        #: 180: the host library's ground-flag devices, keyed by device name
        #: (`Ground-PGND` -> {"uuid": …, "libraryUuid": …}). Empty means "the
        #: library carries no per-net ground symbol", so the flow falls back to
        #: `sch.place_power` exactly as before; a test that fills it exercises the
        #: by-symbol path.
        self.ground_symbols: dict[str, dict] = {}
        #: 180 审计 LOW-c1 的判别台架：按网名拒放（per-action 的 `unresolved`
        #: 做不到只拒一颗旗）。
        self.place_power_refused: set[str] = set()
        #: 542: the page's own document stream, as `sys.get_document_source`
        #: answers it, and whether `sys.set_document_source` actually stores what
        #: it was told — the second one is how "the host said yes and changed
        #: nothing" (`532`'s live failure mode) is faked.
        self.document_source = document_source
        self.source_write_lands = source_write_lands
        #: 542 F1: the envelope the connector puts around that stream
        #: (`actions.ts` `sysGetDocumentSource`): the document it names (`uuid`,
        #: `type`) and whether `data` is the **whole** stream (`chars` vs
        #: `maxChars`).  `source_uuid` lets a test answer with somebody else's
        #: document; the default is the active page, which is what the real
        #: read answers.
        self.source_uuid = source_uuid
        self.source_type = source_type
        #: How many characters the host's own re-serialisation adds to the stored
        #: document, so a write can push it past `maxChars` between the two reads.
        self.source_grow_on_write = source_grow_on_write
        #: 542 F1 (review): an envelope that never says whether the text is all of
        #: it — no `truncated` key at all.  Silence is not `false`.
        self.source_hide_truncated = source_hide_truncated
        #: The params of every `sys.get_document_source` call, so a test can state
        #: that the read named the page it stands behind.
        self.source_requests: list[dict] = []
        #: Which document the editor says is **active** (`doc.list`'s `active`),
        #: when that is not the page the plan names — the one state 5c refuses on.
        self.active_page = active_page
        #: `doc.focus` answers, and the focus does not move (a host that refuses
        #: to bring the page forward is exactly what 5c has to notice).
        self.focus_refused = focus_refused

    # ---------------------------------------------------------- the page

    def add(self, designator: str, x: float, y: float, *, rotation: float = 0.0,
            mirror: bool = False, lcsc: str = "C25744",
            value: str | None = None) -> None:
        self.components[designator] = {
            "x": x, "y": y, "rotation": rotation, "mirror": mirror, "lcsc": lcsc,
        }
        if value is not None:
            self.set_value(designator, value)

    def set_value(self, designator: str, value: str) -> None:
        """Write `OtherProperty.Value` the way the editor does — one key at a time."""
        self.values.setdefault(designator, {})["Value"] = value

    def wire(self, net: str, points) -> None:
        self.wires.append({"net": net, "points": [list(point) for point in points]})

    def flag(self, net: str, x: float, y: float) -> None:
        self.flags.append({"net": net, "x": x, "y": y})

    def geometry(self) -> dict:
        return {
            "components": [
                {"primitiveId": f"c-{name}",
                 "state": {"Designator": name, "X": item["x"], "Y": item["y"],
                           "ComponentType": "part", "Rotation": item["rotation"],
                           "Mirror": item["mirror"],
                           **({"OtherProperty": dict(self.values[name])}
                              if name in self.values else {})}}
                for name, item in sorted(self.components.items())
            ]
            + ([{"primitiveId": "sheet-1",
                 "state": {"ComponentType": "sheet", "Designator": "", "X": 0, "Y": 0}}]
               if self.exists else [])
            + [
                {"primitiveId": f"flag-{index}",
                 "state": {"ComponentType": "netflag", "Designator": None,
                           "Net": item["net"], "X": item["x"], "Y": item["y"]}}
                for index, item in enumerate(self.flags)
            ],
            "wires": [
                {"primitiveId": f"w-{index}",
                 "state": {"Line": [c for point in item["points"] for c in point],
                           "Net": item["net"]}}
                for index, item in enumerate(self.wires)
            ],
            "netlabels": [],
            "bboxes": {"sheet-1": FRAME},
            "meta": {"available": {"components": True, "wires": True, "bboxes": True}},
        }

    # --------------------------------------------------------- the calls

    async def call(self, action, params=None, **_route):
        params = params or {}
        self.calls.append(action)
        if action in self.unresolved:
            raise _BridgeError("CONNECTOR_ERROR", f"the editor refused {action}")
        if action in self.timeouts:
            # A timeout is not a refusal: the write may have landed. The flow must
            # read the page back and must NOT retry (016 §4 protection 4).
            self.timeouts.discard(action)
            raise _BridgeError("TIMEOUT", f"{action} did not answer within 30 s")
        if action == "doc.list":
            documents = (
                [{"uuid": self.page, "name": "boardwise draw", "type": "sch"}]
                if self.exists else []
            )
            active = (
                self.active_page if self.active_page is not None else self.page
            ) if self.exists else None
            return {
                "documents": documents,
                "projects": [{"projectUuid": "proj-1", "name": "test", "focused": True}],
                "active": {"uuid": active, "type": "sch"},
                "count": len(documents),
            }
        if action == "doc.focus":
            if not self.focus_refused:
                self.page = str(params.get("pageUuid") or self.page)
                self.active_page = None
            return {"activated": not self.focus_refused, "tabId": "tab",
                    "documentType": "sch"}
        if action == "sys.get_document_source":
            # 542: the value-row flags live in the document, so this is the read
            # 5c's own postcondition is stated against.  The envelope is the
            # connector's (actions.ts `sysGetDocumentSource`): `uuid`/`type` name
            # the document, `chars`/`maxChars`/`truncated` say whether `data` is
            # all of it — and a `uuid` naming a document that is not active is
            # refused there (`DOC_NOT_ACTIVE`), so it is refused here.
            self.source_requests.append(dict(params))
            requested = str(params.get("uuid") or "").strip()
            if requested and requested != self.page:
                raise _BridgeError(
                    "DOC_NOT_ACTIVE",
                    f"sys.get_document_source reads the active document only, and "
                    f"{self.page!r} is the active one",
                )
            max_chars = int(params.get("maxChars") or 65_536)
            source = self.document_source
            answer = {
                "source": "sys_FileManager.getDocumentSource",
                "uuid": self.source_uuid if self.source_uuid is not None else self.page,
                "type": self.source_type,
                "chars": len(source),
                "maxChars": max_chars,
                "truncated": len(source) > max_chars,
                "data": source[:max_chars],
            }
            if self.source_hide_truncated:
                # The stream is cut and the envelope keeps silent about it — the
                # shape 542 F1's review asked for: only an explicit `false` may
                # be read as "this is the whole document".
                answer.pop("truncated")
            return answer
        if action == "sys.set_document_source":
            self.writes.append((action, params))
            if self.source_write_lands:
                self.document_source = str(params.get("source") or "")
                if self.source_grow_on_write:
                    filler = (
                        '{"type":"COMPONENT","id":"grown","ticket":1}'
                        '||{"x":0,"y":0}|'
                    )
                    pad = (filler * (self.source_grow_on_write // len(filler) + 1))[
                        : self.source_grow_on_write
                    ]
                    self.document_source += "\n" + pad + "\n"
            return {"uuid": str(params.get("uuid") or self.page), "written": True}
        if action == "sys.identity":
            return {"consistent": True, "consistentBasis": "project-uuid",
                    "pageUuid": self.page}
        if action == "sch.geometry":
            return self.geometry()
        if action == "sch.netlist":
            index = min(self.netlist_reads, len(self.netlists) - 1)
            self.netlist_reads += 1
            payload = self.netlists[index] if self.netlists else {"components": {}}
            return {"type": params.get("type"), "text": json.dumps(payload)}
        if action == "sch.component_pins":
            primitive = str(params.get("primitiveId") or "")
            designator = primitive[2:] if primitive.startswith("c-") else ""
            component = self.components.get(designator)
            offsets = self.pin_offsets.get(
                (component or {}).get("lcsc", ""), {}
            )
            pins = []
            for number, (dx, dy) in sorted(offsets.items()):
                rotation = float((component or {}).get("rotation") or 0.0)
                mirror = bool((component or {}).get("mirror"))
                x, y = float((component or {}).get("x") or 0.0), float(
                    (component or {}).get("y") or 0.0
                )
                # The editor's own composition, measured on 3.2.186
                # (`draw.editor_pose`, `outputs/054_c1/08_mirror_probe.json`):
                # **clockwise** rotation, then a mirror about the canvas vertical
                # axis. Since 189A2 that is the same *order* as
                # `core.geometry.transform_point`'s (mirror last); the two differ
                # only in their operators, CW against CCW, which is why the
                # negation is what makes them land in one place.
                if rotation == 90:
                    dx, dy = dy, -dx
                elif rotation == 180:
                    dx, dy = -dx, -dy
                elif rotation == 270:
                    dx, dy = -dy, dx
                if mirror:
                    dx = -dx
                pins.append({"X": x + dx, "Y": y + dy, "PinNumber": number,
                             "PinName": number, "Rotation": rotation, "PinLength": 10})
            return {"primitiveId": primitive, "returned": len(pins), "pins": pins}
        if action == "sch.doc.new":
            self.writes.append((action, params))
            self.created = True
            self.exists = True
            self.page = "page-created"
            return {"schematicUuid": "sheet-created", "pageUuid": self.page}
        if action == "sch.place_component":
            self.writes.append((action, params))
            device_uuid = str(params.get("deviceUuid") or "")
            ground = next(
                (name for name, device in self.ground_symbols.items()
                 if str(device.get("uuid") or "") == device_uuid),
                "",
            )
            if ground:
                # 180: a ground flag placed **by its library symbol** — the host
                # lands a `netflag` (no designator), which the live probe confirmed
                # for `Ground-PGND`. It is a flag, not a numbered part.
                net = ground[len("Ground-"):] if ground.startswith("Ground-") else ground
                self.flag(net, float(params.get("x") or 0.0),
                          float(params.get("y") or 0.0))
                return {"uuid": f"flag-{len(self.flags)}", "resolvedBy": "uuid",
                        "device": {"uuid": device_uuid,
                                   "libraryUuid": str(params.get("libraryUuid") or ""),
                                   "name": ground}}
            self.add(
                str(params.get("designator") or ""), float(params.get("x") or 0.0),
                float(params.get("y") or 0.0),
                rotation=float(params.get("rotation") or 0.0),
                mirror=bool(params.get("mirror")),
                lcsc=str(params.get("lcsc") or ""),
            )
            return {"uuid": f"c-{params.get('designator')}", "resolvedBy": "lcsc",
                    "device": {"name": params.get("lcsc")}}
        if action == "sch.place_wire":
            self.writes.append((action, params))
            self.wire(str(params.get("net") or ""), params.get("points") or [])
            return {"uuid": f"w-{len(self.wires)}", "net": params.get("net")}
        if action == "sch.set_component_attribute":
            # The connector's own contract (actions.ts): one merged write of
            # `otherProperty`, then a read-back, and `applied` = the read-back
            # equals the target. A fake that answered `applied: true` without
            # storing the value would make 055 G2's independent read-back the only
            # thing standing between the flow and a wrong conclusion.
            self.writes.append((action, params))
            primitive = str(params.get("primitiveId") or "")
            designator = primitive[2:] if primitive.startswith("c-") else ""
            key = str(params.get("key") or "Value")
            value = str(params.get("value") or "")
            if not designator or designator not in self.components:
                raise _BridgeError("NOT_FOUND", f"no primitive {primitive!r} on the page")
            if self.value_write_lands:
                self.set_value(designator, value)
            read_back = self.values.get(designator, {}).get(key, "")
            return {
                "primitiveId": primitive,
                "attributes": {key: value},
                "applied": self.value_write_lands and read_back == value,
                "wrote": True,
                "otherPropertyAfter": dict(self.values.get(designator, {})),
                **({} if read_back == value else {
                    "mismatched": [f"{key}: wanted {value!r}, read {read_back!r}"],
                }),
            }
        if action == "lib.device.search":
            # 180: `draw apply` looks up `Ground-<net>` before falling back to
            # `sch.place_power`. Read-only, and an exact-name match only — the same
            # rule the flow applies to the answer.
            keyword = str(params.get("keyword") or "")
            items = [
                {"name": name, **dict(device)}
                for name, device in self.ground_symbols.items() if name == keyword
            ]
            return {"keyword": keyword, "returned": len(items), "shown": len(items),
                    "items": items}
        if action == "sch.place_power":
            net = str(params.get("net") or "")
            if net in self.place_power_refused:
                raise _BridgeError("CONNECTOR_ERROR",
                                   f"the editor refused the flag for {net}")
            self.writes.append((action, params))
            self.flag(net, float(params.get("x") or 0.0),
                      float(params.get("y") or 0.0))
            return {"uuid": f"flag-{len(self.flags)}"}
        if action == "sch.doc.save":
            if not self.save_ok:
                raise _BridgeError("CONNECTOR_ERROR", "the editor refused the save")
            self.writes.append((action, params))
            return {"saved": True}
        if action == "export.render":
            self.render_format = str(params.get("format") or "")
            if not self.render_ok:
                return None
            blob = b"\x89PNG\r\n\x1a\n" + b"boardwise fake render"
            return {"format": "png", "scope": "page", "pageUuid": self.page,
                    "activatedPageUuid": self.page,
                    "encoding": "base64", "data": base64.b64encode(blob).decode("ascii")}
        raise AssertionError(f"the flow called {action}, which this fake does not answer")

    async def close(self):
        return None


def _stub_editor(monkeypatch, editor: _FakeEditor) -> None:
    class _Client:
        @staticmethod
        async def open(*_args, **_kwargs):
            return editor

    monkeypatch.setattr(
        cli, "_open_cli", lambda args: (_Client, _BridgeError, 61190, "tok")
    )


def _stub_export(monkeypatch, *, components=None, findings=None, sequence=None):
    """Serve the live export, its model and the findings baseline.

    ``intent`` is the contract the walk carries since 094 A3b — the double takes
    the keyword and answers the same list, because what these tests read is *when*
    the baseline is taken, not what a contract would add to it.
    """
    models = list(sequence) if sequence is not None else None

    async def _export(call, notes):
        return b"export-bytes"

    def _parse(blob, notes):
        if models is not None:
            return models.pop(0) if models else None
        return type("Model", (), {"components": dict(components or {})})()

    monkeypatch.setattr(cli, "_live_project_export", _export)
    monkeypatch.setattr(cli, "_model_from_export", _parse)
    monkeypatch.setattr(
        cli, "_baseline_findings", lambda model, intent=None: list(findings or [])
    )


def _plan(tmp_path: Path, *, page: str = "", pool=(), name: str = "plan.json",
          page_editor=None):
    """The fixture drawing as a plan, built the way `draw plan` builds it.

    ``page_editor`` supplies the page the plan records a census of — the shape a
    plan built against a page that already holds something has (036b's pool, and
    055 G2's "the write's scope is this plan's parts").
    """
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec
    from boardwise.engines import drawcompiler

    circuit = CircuitSpec.load(CIRCUIT)
    presentation = PresentationSpec.load(PRESENTATION)
    profiles = drawapply.load_library(LIBRARY)
    compiled = drawcompiler.compile(
        circuit, presentation, profiles,
        drawcompiler.CompileBudget(
            page_box=tuple(float(item) for item in PAGE_BOX.split(","))
        ),
    )
    assert compiled.ok, compiled.render_failures()
    layout = compiled.candidates[0]
    baseline = None
    if page:
        baseline = drawapply.canvas_census(
            (page_editor or _FakeEditor(page=page)).geometry()
        )
        baseline.page_uuid = page
    plan = drawapply.module_plan(
        layout, circuit, presentation, profiles,
        lcsc_by_part=LCSC, pool=list(pool), baseline=baseline,
    )
    path = tmp_path / name
    plan.dump(path)
    return path, plan


def _live_netlist_for(plan: ChangePlan) -> dict:
    """The netlist the plan says the finished page must show, hand-written.

    A net the plan **states a name for** comes back under that name — a flag's own
    net, or the name a label's wire carries — because that is what the editor does
    with the flag/wire it was given; a net the plan states no name for lands under
    the editor's own auto name (530D, 岳's ruling A: the name lives on a flag or a
    label, so the wires of an unnamed net carry nothing for the netlist to read).
    """
    live = {"components": {}}
    stated = drawapply.planned_net_names(plan)
    for index, island in enumerate(sorted(
        {tuple(item.mates) for item in plan.change.islands}
    )):
        name = next(
            (stated[member] for member in sorted(island) if member in stated),
            f"NET{index + 1}",
        )
        for member in island:
            designator, _sep, pin = member.partition(".")
            entry = live["components"].setdefault(
                f"c{len(live['components'])}",
                {"props": {"Designator": designator}, "pinInfoMap": {}},
            )
            entry["pinInfoMap"][pin] = {"net": name}
    return live


def _page_with(plan: ChangePlan) -> _FakeEditor:
    """An editor whose page already *is* the plan — including the written values."""
    editor = _FakeEditor(page="page-1", netlists=[_live_netlist_for(plan)])
    for part in plan.change.draw_parts:
        editor.add(part.designator, part.x, part.y, rotation=part.rotation,
                   mirror=part.mirror, lcsc=part.lcsc,
                   value=part.value if part.value_key else None)
    # A flagged net's wires are drawn **unnamed** (069 sec.9: the flag states the
    # name), so a page that already holds this plan holds them the same way.
    for wire in plan.change.draw_wires:
        editor.wire(
            wire.net if drawapply.wire_carries_its_name(wire) else "", wire.points
        )
    for flag in plan.change.draw_flags:
        editor.flag(flag.net, flag.x, flag.y)
    return editor


# ------------------------------------------------------------- draw compile


def test_draw_compile_writes_previews_and_exits_zero(tmp_path, capsys):
    out = tmp_path / "previews"
    report = tmp_path / "compile.json"
    code = cli.main([
        "draw", "compile",
        "--circuit", str(CIRCUIT),
        "--presentation", str(PRESENTATION),
        "--profiles", str(LIBRARY),
        "--page-box", PAGE_BOX,
        "--out", str(out),
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "candidate(s)" in printed and "ranked" in printed
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] and payload["candidates"]
    written = sorted(path.name for path in out.iterdir())
    assert "cand1.svg" in written and "cand1.layout.json" in written
    assert payload["previews"], "the report says where the pictures went"


def test_draw_compile_refuses_a_circuit_it_cannot_draw(tmp_path, capsys):
    spec = json.loads(CIRCUIT.read_text(encoding="utf-8"))
    # A net member naming a pin the symbol does not carry: the compiler refuses it
    # in its own vocabulary (a category from 053 §四), rather than drawing it.
    spec["nets"][1]["members"] = ["R1.2", "R2.9"]
    broken = tmp_path / "broken.circuit.json"
    broken.write_text(json.dumps(spec), encoding="utf-8")
    code = cli.main([
        "draw", "compile", "--circuit", str(broken),
        "--presentation", str(PRESENTATION), "--profiles", str(LIBRARY),
        "--out", str(tmp_path / "out"),
    ])
    captured = capsys.readouterr()
    assert code == 5
    assert "0 candidate(s)" in captured.out and "failure(s)" in captured.out


def test_draw_compile_refuses_an_unreadable_input(tmp_path, capsys):
    code = cli.main([
        "draw", "compile", "--circuit", str(tmp_path / "missing.json"),
        "--presentation", str(PRESENTATION), "--profiles", str(LIBRARY),
    ])
    assert code == 5
    assert "cannot be read" in capsys.readouterr().err


# ---------------------------------------------------------------- draw plan


def test_draw_plan_offline_writes_a_plan_and_says_the_pool_is_empty(tmp_path, capsys):
    out = tmp_path / "plan.json"
    code = cli.main([
        "draw", "plan", "--circuit", str(CIRCUIT), "--presentation", str(PRESENTATION),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX,
        "--lcsc", "R1=C25744", "--lcsc", "R2=C25744", "--out", str(out),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    plan = ChangePlan.load(out)
    assert plan.change.kind == DRAW_MODULE_KIND
    assert [part.designator for part in plan.change.draw_parts] == ["R1", "R2"]
    assert "empty (offline)" in printed
    assert plan.change.draw_downgrades, "the label downgrade is declared, not dropped"


def test_draw_plan_refuses_a_part_with_no_lcsc(tmp_path, capsys):
    spec = json.loads(CIRCUIT.read_text(encoding="utf-8"))
    spec["parts"][0].pop("lcsc")
    stripped = tmp_path / "no-lcsc.circuit.json"
    stripped.write_text(json.dumps(spec), encoding="utf-8")
    code = cli.main([
        "draw", "plan", "--circuit", str(stripped), "--presentation",
        str(PRESENTATION), "--profiles", str(LIBRARY), "--page-box", PAGE_BOX,
        "--lcsc", "R2=C25744",
    ])
    assert code == 5
    assert "R1" in capsys.readouterr().err


def test_draw_plan_refuses_a_candidate_out_of_range(tmp_path, capsys):
    code = cli.main([
        "draw", "plan", "--circuit", str(CIRCUIT), "--presentation", str(PRESENTATION),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX, "--candidate", "99",
        "--lcsc", "R1=C25744", "--lcsc", "R2=C25744",
    ])
    assert code == 5
    assert "out of range" in capsys.readouterr().err


def test_draw_plan_reads_the_pool_from_the_page_and_the_project(
    monkeypatch, tmp_path, capsys
):
    """036b's pool: the page alone is not the pool, and the plan says which it used."""
    editor = _FakeEditor(page="page-1")
    _stub_editor(monkeypatch, editor)
    # A designator that exists **only in the project export** — another page's R1.
    _stub_export(monkeypatch, components={"R1": object()}, findings=["rule|X|Y"])
    out = tmp_path / "plan.json"
    code = cli.main([
        "draw", "plan", "--circuit", str(CIRCUIT), "--presentation", str(PRESENTATION),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX,
        "--lcsc", "R1=C25744", "--lcsc", "R2=C25744",
        "--page", "page-1", "--out", str(out),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    plan = ChangePlan.load(out)
    # The page has no parts, so a page-only pool would have given R1/R2. The
    # project export's R1 pushes both numbers up, which is the whole point.
    assert [part.designator for part in plan.change.draw_parts] == ["R2", "R3"]
    assert plan.source.page_uuid == "page-1"
    assert plan.change.draw_baseline.page_uuid == "page-1"
    assert plan.change.draw_baseline.findings_read is True
    assert plan.change.baseline_findings == ["rule|X|Y"]
    assert "the project export" in printed


# --------------------------------------------------------------- draw apply


def test_the_first_apply_lands_the_drawing_on_a_new_page(monkeypatch, tmp_path, capsys):
    """C1, end to end on a fake: page, parts, pins, wires, flags, range, save, render."""
    plan_path, plan = _plan(tmp_path)
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)]
    )
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    render = tmp_path / "render.png"

    code = cli.main([
        "draw", "apply", str(plan_path), "--project", "test", "--new-page",
        "--page-name", "054 C1", "--json", str(report), "--render", str(render),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert editor.created, "the run created the page it landed on"
    assert [action for action, _params in editor.writes] == [
        "sch.doc.new",
        "sch.place_component", "sch.place_component",
        "sch.set_component_attribute", "sch.set_component_attribute",
        "sch.place_wire", "sch.place_wire", "sch.place_wire", "sch.place_wire",
        "sch.place_power", "sch.place_power",
        "sch.doc.save",
    ], "the order 055 §二 fixes: parts, values, pins, wires, flags, save"
    # 055 G2: every write went to a part this plan placed, one key each.
    value_writes = [params for action, params in editor.writes
                    if action == "sch.set_component_attribute"]
    assert [item["primitiveId"] for item in value_writes] == ["c-R1", "c-R2"], (
        "the write's scope is the plan's own parts — nothing outside it is touched"
    )
    assert {item["key"] for item in value_writes} == {"Value"}
    assert [item["value"] for item in value_writes] == ["10k", "10k"]
    assert all(item["pageUuid"] == editor.page for item in value_writes), (
        "every write carries the page guard (SKILL §4: 写动作一律带 pageUuid)"
    )
    assert editor.values == {"R1": {"Value": "10k"}, "R2": {"Value": "10k"}}
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["persistence"] == "saved_unverified"
    assert payload["verification"]["ok"] is True
    assert payload["range"]["added"] == ["R1", "R2"]
    assert payload["range"]["flags"] == {"before": 0, "after": 2, "expected": 2}
    assert payload["page"]["created"] is True
    assert payload["page"]["censusBefore"]["components"] == []
    assert payload["page"]["censusAfter"]["components"] == ["R1", "R2"]
    assert payload["page"]["censusAfter"]["wireCount"] == len(plan.change.draw_wires)
    assert payload["write"]["pinReadback"]["problems"] == []
    assert payload["write"]["pool"]["source"].startswith("the page's designators")
    assert payload["render"]["bytes"] == len(render.read_bytes())
    assert render.read_bytes().startswith(b"\x89PNG")
    assert editor.calls.count("export.render") == 1
    assert editor.render_format == "png", (
        "the connector's vocabulary is png|svg|pdf — the live C1 run asked for "
        "`image/png` and the editor answered BAD_REQUEST"
    )
    assert payload["plan"]["kind"] == DRAW_MODULE_KIND
    assert payload["guards"]["problems"] == []
    assert payload["guards"]["checked"]["census"] is False, (
        "this plan records no census (it was built offline), and the report says so "
        "rather than reporting an unchecked leg as a pass"
    )
    assert payload["findings"]["new"] == []


def _load_plan(tmp_path: Path):
    return _plan(tmp_path)


def test_the_pin_readback_stops_the_run_before_any_wire(monkeypatch, tmp_path, capsys):
    """Protection 3, with the library answering a *different* geometry (C6's editor half)."""
    plan_path, plan = _plan(tmp_path)
    editor = _FakeEditor(
        exists=False,
        pin_offsets={"C25744": {"1": (0.0, 20.0), "2": (0.0, -20.0)}},
        netlists=[{"components": {}}, _live_netlist_for(plan)],
    )
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main([
        "draw", "apply", str(plan_path), "--new-page", "--project", "test",
    ])
    printed = capsys.readouterr().out
    assert code == 3, printed
    actions = [action for action, _params in editor.writes]
    assert "sch.place_wire" not in actions and "sch.place_power" not in actions
    assert "sch.doc.save" not in actions, "a wrong pin read-back never saves"
    assert "tolerance" in printed or "054 C6" in printed


def test_a_rotated_part_is_placed_at_the_editors_own_angle(monkeypatch, tmp_path, capsys):
    """The editor's rotation parameter is the layout's angle **negated** (010c/029).

    A 90° plan part has to be handed to the editor as 270°, or its two pads come
    back exchanged and the pin read-back below refuses a placement that was
    actually right. The fake answers `sch.component_pins` in the editor's own
    clockwise convention, so this test fails if either side of that pair moves.
    """
    from boardwise.core.geometry import transform_point

    plan_path, plan = _plan(tmp_path)
    part = plan.change.draw_parts[0]
    part.rotation = 90.0
    posed = [
        type(pin)(
            number=pin.number,
            dx=transform_point(pin.dx, pin.dy, rotation=90, mirror=False, ox=0, oy=0)[0],
            dy=transform_point(pin.dx, pin.dy, rotation=90, mirror=False, ox=0, oy=0)[1],
        )
        for pin in part.pins
    ]
    part.pins = posed
    plan.dump(plan_path)
    assert ChangePlan.load(plan_path).change.draw_parts[0].rotation == 90

    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)]
    )
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main(["draw", "apply", str(plan_path), "--new-page", "--project", "test"])
    printed = capsys.readouterr().out
    assert code == 0, printed
    placed = {
        params["designator"]: params
        for action, params in editor.writes if action == "sch.place_component"
    }
    assert placed[part.designator]["rotation"] == 270, (
        "the layout's 90° is the editor's 270°: `draw._editor_rotation`'s whole point"
    )
    assert placed[part.designator]["x"] == part.x and placed[part.designator]["y"] == part.y


def test_a_mirrored_part_is_placed_at_the_negated_angle_too(monkeypatch, tmp_path, capsys):
    """The mirror case: the editor mirrors **after** rotating — same as the layout.

    **189A2 flipped this expectation** (it used to assert ``rotation == 90``, and
    ``editor_pose`` used to hand a mirrored pose its angle unchanged). 054 read
    the API's composition as `mirror_x ∘ CW(R)` and the layout's as
    `CCW(R) ∘ mirror_x`, and reconciled them by *not* negating for a mirrored
    part. 189A2 measured the layout's order against a real drawing (the wire
    endpoints) and it is `mirror_x ∘ CCW(angle)` — the **same** order as the API
    — so the two transforms now differ only in their operators and the angle
    relation is one rule again: ``R = -angle``, mirror or no mirror.

    ``0`` and ``180`` are their own negation, so nothing 054 actually placed is
    affected; only a mirrored ``90``/``270`` part is, and the assertion below is
    where that is pinned. The end-to-end half of this test is unchanged and is
    the real acceptance: the fake editor implements the **measured** API
    composition, so `code == 0` with no ``verification_disagrees`` line means the
    plan's expectation and the editor's landing point still agree.
    """
    from boardwise.core.geometry import transform_point

    plan_path, plan = _plan(tmp_path)
    part = plan.change.draw_parts[0]
    part.rotation = 90.0
    part.mirror = True
    part.pins = [
        type(pin)(
            number=pin.number,
            dx=transform_point(pin.dx, pin.dy, rotation=90, mirror=True, ox=0, oy=0)[0],
            dy=transform_point(pin.dx, pin.dy, rotation=90, mirror=True, ox=0, oy=0)[1],
        )
        for pin in part.pins
    ]
    plan.dump(plan_path)

    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)]
    )
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main(["draw", "apply", str(plan_path), "--new-page", "--project", "test"])
    printed = capsys.readouterr().out
    assert code == 0, printed
    placed = {
        params["designator"]: params
        for action, params in editor.writes if action == "sch.place_component"
    }
    assert placed[part.designator]["rotation"] == 270, (
        "the layout's 90° is the editor's 270°, mirrored or not (189A2)"
    )
    assert placed[part.designator]["mirror"] is True
    assert "verification_disagrees" not in printed


# --------------------------------------------------- the value write (055 G2)


def test_the_apply_writes_each_parts_value_and_reads_it_back(monkeypatch, tmp_path, capsys):
    """055 G2: the CircuitSpec's value is the design value, so it lands on the part."""
    plan_path, plan = _plan(tmp_path)
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)]
    )
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    code = cli.main([
        "draw", "apply", str(plan_path), "--new-page", "--project", "test",
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    payload = json.loads(report.read_text(encoding="utf-8"))
    values = payload["write"]["values"]
    assert [item["designator"] for item in values] == ["R1", "R2"]
    assert [item["key"] for item in values] == ["Value", "Value"]
    assert [item["value"] for item in values] == ["10k", "10k"]
    assert [item["readBack"] for item in values] == ["10k", "10k"], (
        "the read-back is the page's own answer, not the write's"
    )
    assert all(item["applied"] for item in values)
    assert payload["write"]["valueReadback"]["problems"] == []
    assert payload["write"]["valueReadback"]["written"] == 2
    assert payload["verification"]["canvas"] == []
    assert "sch.set_component_attribute" in payload["write"]["valueChannel"]


def test_a_value_that_does_not_land_stops_the_run_before_any_wire(monkeypatch, tmp_path, capsys):
    """The write's own postcondition: the page must state the value the plan wrote."""
    plan_path, plan = _plan(tmp_path)
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        value_write_lands=False,      # the host accepts the call and stores nothing
    )
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    code = cli.main([
        "draw", "apply", str(plan_path), "--new-page", "--project", "test",
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 3, printed
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["reason"] == "value_readback_disagrees"
    problems = payload["write"]["valueReadback"]["problems"]
    assert len(problems) == 2, problems
    assert "R1 is on the page but states no Value at all" in problems[0]
    assert "the plan writes '10k'" in problems[0]
    assert "R2 is on the page but states no Value at all" in problems[1]
    actions = [action for action, _params in editor.writes]
    assert "sch.place_wire" not in actions and "sch.place_power" not in actions
    assert "sch.doc.save" not in actions, "a value that did not land never saves"
    assert any("写值与回读不符" in item for item in payload["notes"])


def test_the_value_write_never_touches_a_part_outside_the_plan(monkeypatch, tmp_path, capsys):
    """036's scope guard, one level down: this module's parts, and nothing else."""
    page = _FakeEditor(page="page-1")
    page.add("U9", 500.0, -500.0, lcsc="C25744", value="SOMEBODY-ELSES-VALUE")
    plan_path, plan = _plan(tmp_path, page="page-1", page_editor=page)
    page.netlists = [_live_netlist_for(plan)]
    _stub_editor(monkeypatch, page)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main(["draw", "apply", str(plan_path), "--page", "page-1"])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert [params["primitiveId"] for action, params in page.writes
            if action == "sch.set_component_attribute"] == ["c-R1", "c-R2"]
    assert page.values["U9"] == {"Value": "SOMEBODY-ELSES-VALUE"}, (
        "范围外一个属性不动 (055 §二)"
    )
    assert page.values["R1"] == {"Value": "10k"}
    assert page.values["R2"] == {"Value": "10k"}


def test_a_repeat_apply_writes_nothing_at_all(monkeypatch, tmp_path, capsys):
    """C4: the plan's own postconditions, read on the page, say `already_applied`.

    The values are part of those postconditions since 055 G2, so a repeat run
    also says the design values are already on the page.
    """
    plan_path, plan = _plan(tmp_path)
    editor = _page_with(plan)
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main(["draw", "apply", str(plan_path), "--page", "page-1"])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "already_applied" in printed
    assert editor.writes == [], "a repeat run writes nothing"


def test_a_repeat_apply_of_a_page_bound_plan_writes_nothing(monkeypatch, tmp_path, capsys):
    """C4 with a plan that **recorded** its census: the probe answers before it.

    The live C1 run is exactly this shape, and the first cut of the census guard
    refused it (`guard_refused`, exit 4): the plan's baseline is the *empty* page
    it was built against, and after the drawing lands the page no longer matches
    it. The order in the flow is the fix — a page whose primitives are this
    drawing's own work is not a page somebody changed.
    """
    plan_path, plan = _plan(tmp_path, page="page-1")
    assert plan.change.draw_baseline.digest, "the plan recorded a baseline"
    editor = _page_with(plan)
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main(["draw", "apply", str(plan_path)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "already_applied" in printed
    assert editor.writes == []


def test_a_page_with_somebody_elses_part_refuses_before_the_writes(
    monkeypatch, tmp_path, capsys
):
    """C5's other shape: the page changed, and not into the plan's own drawing."""
    plan_path, plan = _plan(tmp_path, page="page-1")
    editor = _FakeEditor(page="page-1", netlists=[{"components": {}}])
    editor.add("U9", 500.0, 500.0)
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    code = cli.main(["draw", "apply", str(plan_path), "--json", str(report)])
    printed = capsys.readouterr().out
    assert code == 4, printed
    assert editor.writes == []
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["reason"] == "canvas_changed"
    assert any("054 C5" in item for item in payload["guards"]["problems"])


def test_a_hand_moved_part_refuses_and_writes_nothing(monkeypatch, tmp_path, capsys):
    """C5: somebody moved a part — the page is no longer the plan's."""
    plan_path, plan = _plan(tmp_path)
    editor = _page_with(plan)
    editor.components["R1"]["x"] += 25.0
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main(["draw", "apply", str(plan_path), "--page", "page-1"])
    printed = capsys.readouterr().out
    assert code == 4, printed
    assert editor.writes == []
    assert "postconditions do not hold" in printed


def test_a_canvas_that_is_not_the_expected_census_refuses(monkeypatch, tmp_path, capsys):
    """C5's other door: the digest a previous run's report quoted."""
    plan_path, plan = _plan(tmp_path)
    editor = _page_with(plan)
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main([
        "draw", "apply", str(plan_path), "--page", "page-1", "--expect-census", "0" * 64,
    ])
    printed = capsys.readouterr().out
    assert code == 4, printed
    assert editor.writes == []
    assert "expected" in printed


def test_a_library_whose_geometry_moved_refuses_before_any_write(monkeypatch, tmp_path, capsys):
    """C6's pre-write leg: the profiles document is not the one the plan was built from."""
    plan_path, _plan_ = _plan(tmp_path)
    payload = json.loads(LIBRARY.read_text(encoding="utf-8"))
    for entry in payload["profiles"]:
        if entry["symbolRef"] == "R0402":
            entry["pins"][0]["tip"] = [0.0, 25.0]
            entry["pins"][1]["tip"] = [0.0, -25.0]
    moved = tmp_path / "library-moved.json"
    moved.write_text(json.dumps(payload), encoding="utf-8")
    editor = _FakeEditor(page="page-1")
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main([
        "draw", "apply", str(plan_path), "--page", "page-1",
        "--circuit", str(CIRCUIT), "--presentation", str(PRESENTATION),
        "--profiles", str(moved),
    ])
    printed = capsys.readouterr().out
    assert code == 4, printed
    assert editor.writes == []
    assert "R0402" in printed and "geometry changed" in printed


def test_a_program_that_changed_refuses(monkeypatch, tmp_path, capsys):
    """The stale guard, on the circuit spec: the drawing's input is not the file now."""
    plan_path, _plan_ = _plan(tmp_path)
    spec = json.loads(CIRCUIT.read_text(encoding="utf-8"))
    spec["parts"][1]["value"] = "4k7"
    changed = tmp_path / "changed.circuit.json"
    changed.write_text(json.dumps(spec), encoding="utf-8")
    editor = _FakeEditor(page="page-1")
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main([
        "draw", "apply", str(plan_path), "--page", "page-1", "--circuit", str(changed),
    ])
    printed = capsys.readouterr().out
    assert code == 4, printed
    assert editor.writes == []
    assert "circuitSha256" in printed and "recompile" in printed


def test_a_designator_the_project_already_uses_refuses(monkeypatch, tmp_path, capsys):
    """036b's measured failure, refused instead of reproduced: the pool is the project's."""
    plan_path, _plan_ = _plan(tmp_path)
    editor = _FakeEditor(page="page-1")  # the page itself is empty
    _stub_editor(monkeypatch, editor)
    # …but another page of the project already has an R1.
    _stub_export(monkeypatch, components={"R1": object()}, findings=[])
    code = cli.main(["draw", "apply", str(plan_path), "--page", "page-1"])
    printed = capsys.readouterr().out
    assert code == 4, printed
    assert editor.writes == []
    assert "R1" in printed and "taken between plan and apply" in printed


def test_a_part_left_behind_by_a_half_done_run_is_not_drawn_again(monkeypatch, tmp_path, capsys):
    plan_path, plan = _plan(tmp_path)
    editor = _FakeEditor(page="page-1", netlists=[{"components": {}}])
    part = plan.change.draw_parts[0]
    editor.add(part.designator, part.x, part.y, lcsc=part.lcsc)
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    code = cli.main(["draw", "apply", str(plan_path), "--page", "page-1"])
    printed = capsys.readouterr().out
    assert code == 4, printed
    assert editor.writes == []
    assert "postconditions do not hold" in printed


def test_apply_refuses_a_plan_of_another_kind(tmp_path, capsys):
    from boardwise.core.changeplan import component_value_plan, sha256_of

    other = component_value_plan(
        source=type(_plan(tmp_path)[1].source)(input_sha256=sha256_of(CIRCUIT)),
        designator="R1", before="10k", after="4k7",
    )
    path = tmp_path / "value.json"
    other.dump(path)
    code = cli.main(["draw", "apply", str(path), "--new-page"])
    assert code == 5
    assert "draw-module" in capsys.readouterr().err


def test_apply_refuses_an_unbound_plan_without_a_page(tmp_path, capsys):
    plan_path, _plan_ = _plan(tmp_path)
    code = cli.main(["draw", "apply", str(plan_path)])
    assert code == 5
    assert "--page" in capsys.readouterr().err


def test_apply_reports_that_the_state_cannot_be_stated_without_a_daemon(monkeypatch, tmp_path, capsys):
    plan_path, _plan_ = _plan(tmp_path)

    class _Client:
        @staticmethod
        async def open(*_args, **_kwargs):
            raise OSError("the daemon is not listening")

    monkeypatch.setattr(
        cli, "_open_cli", lambda args: (_Client, _BridgeError, 61190, "tok")
    )
    code = cli.main(["draw", "apply", str(plan_path), "--new-page"])
    assert code == 3
    assert "daemon not reachable" in capsys.readouterr().err


def test_a_write_that_times_out_is_read_back_and_never_retried(monkeypatch, tmp_path, capsys):
    """C7's logic, offline: a placement whose outcome is **unknown**.

    A timeout is not a refusal — the part may be on the page — so the flow reads
    the page back, reports `unknown` (exit 3) when it did not land, and issues no
    second placement and no save. Nothing is retried: a retry of a write whose
    outcome is unknown is how one part becomes two.
    """
    plan_path, plan = _plan(tmp_path)
    editor = _FakeEditor(
        exists=False,
        netlists=[{"components": {}}, _live_netlist_for(plan)],
        timeouts=("sch.place_component",),
    )
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    code = cli.main([
        "draw", "apply", str(plan_path), "--new-page", "--project", "test",
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 3, printed
    assert editor.calls.count("sch.place_component") == 1, (
        "a timed-out write is not retried — one attempt, then a read-back"
    )
    assert "sch.place_wire" not in editor.calls and "sch.doc.save" not in editor.calls
    assert editor.calls.count("sch.geometry") >= 2, (
        "the page is read back after the unknown write"
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["reason"] == "place_unanswered"
    assert any("UNKNOWN" in item or "unknown" in item for item in payload["notes"])


def test_a_new_finding_stops_the_run_before_the_save(monkeypatch, tmp_path, capsys):
    """036's rule: the finding set may shrink, never grow."""
    plan_path, plan = _plan(tmp_path)
    editor = _FakeEditor(exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)])
    _stub_editor(monkeypatch, editor)
    _stub_export(
        monkeypatch,
        sequence=[
            type("Model", (), {"components": {}})(),
            type("Model", (), {"components": {}})(),
        ],
        findings=["rule|new|thing"],
    )
    # The baseline findings are read twice (before the run and after it); the
    # second read is the one that grew, so the stub answers two different sets.
    calls = {"n": 0}

    def _findings(model, intent=None):
        calls["n"] += 1
        return [] if calls["n"] == 1 else ["rule|new|thing"]

    monkeypatch.setattr(cli, "_baseline_findings", _findings)
    code = cli.main(["draw", "apply", str(plan_path), "--new-page", "--project", "test"])
    printed = capsys.readouterr().out
    assert code == 2, printed
    assert "sch.doc.save" not in [action for action, _params in editor.writes]
    assert "new_finding" in printed or "新增 finding" in printed


# ---------------------------------- 542: the hidden value rows must be *read back*


def _document_source(rows: dict[str, str]) -> str:
    """A page document shaped the way `sys.get_document_source` answers one.

    One line per record (`<head>||<body>|`), carrying the two ATTR records `532`
    measured the rows out of: a `Designator` ATTR (`value` = the designator,
    `parentId` = the component) and that component's `Name` ATTR — the value row,
    whose `valueVisible` is the flag. ``rows`` maps a designator to the raw JSON
    text its row states (`"true"`, `"false"`, `"null"`, or `""` for "no such
    key at all"), so a test can hand back a flag that is not a boolean.
    """
    lines = [
        json.dumps({"type": "DOCHEAD", "id": "", "ticket": 1})
        + "||" + json.dumps({"docType": "SCH_PAGE", "uuid": "page-1"}) + "|"
    ]
    for index, (designator, flag) in enumerate(rows.items()):
        component = f"comp-{index}"
        lines.append(
            json.dumps({"type": "COMPONENT", "id": component, "ticket": 1})
            + "||" + json.dumps({"x": 0, "y": 0, "parentId": ""}) + "|"
        )
        lines.append(
            json.dumps({"type": "ATTR", "id": f"a{index}d", "ticket": 1})
            + "||"
            + json.dumps({"key": "Designator", "value": designator,
                          "parentId": component})
            + "|"
        )
        body = (
            '{"key":"Name","value":"={Value}","parentId":"%s"%s}'
            % (component, f',"valueVisible":{flag}' if flag else "")
        )
        lines.append(
            json.dumps({"type": "ATTR", "id": f"a{index}n", "ticket": 1})
            + "||" + body + "|"
        )
    return "\n".join(lines)


def _plan_hiding(tmp_path: Path, *hidden: str):
    """The fixture drawing's plan, with these parts' value rows declared hidden.

    `532` states the row is not printed as `valueVisible: false` on the plan's own
    part (`PlanDrawPart.value_visible`), so that is what this sets — the plan is
    then dumped and re-loaded by `draw apply` like any other.
    """
    path, plan = _plan(tmp_path)
    for part in plan.change.draw_parts:
        if part.designator in hidden:
            part.value_visible = False
    plan.dump(path)
    _reloaded = ChangePlan.load(path)
    assert [item.designator for item in _reloaded.change.draw_parts
            if not item.value_visible] == list(hidden), (
        "the plan on disk must carry the declared visibility, or the run under "
        "test is not the one this test is about"
    )
    return path, _reloaded


def _apply(monkeypatch, tmp_path: Path, plan_path: Path, editor: _FakeEditor, capsys):
    """Run `draw apply` against ``editor`` and read the report it wrote."""
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    code = cli.main([
        "draw", "apply", str(plan_path), "--new-page", "--project", "test",
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    payload = (json.loads(report.read_text(encoding="utf-8"))
               if report.exists() else {})
    return code, payload, printed


def _nothing_was_drawn(editor: _FakeEditor, payload: dict) -> None:
    """The one claim every 542 refusal makes: it stopped before the canvas."""
    actions = [action for action, _params in editor.writes]
    assert "sch.place_wire" not in actions, actions
    assert "sch.place_power" not in actions, actions
    assert "sch.doc.save" not in actions, actions
    assert "export.render" not in editor.calls, editor.calls
    assert payload["outcome"] == "unknown", payload.get("outcome")
    assert payload["ok"] is False


def test_a_hidden_row_that_stays_printed_stops_the_run_before_any_wire(
    monkeypatch, tmp_path, capsys,
):
    """The write answered "done" and the document still prints the row (532's shape).

    A page that says `valueVisible: true` after the write is the *plan's* claim
    refuted by the document, and it is not a note: the host will paint a value the
    drawing stated is hidden, which is the 531 defect — refused before the wires.
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=_document_source({"R1": "true", "R2": "true"}),
        source_write_lands=False,   # the host accepts the call and stores nothing
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_still_visible", payload.get("reason")
    hidden = payload["write"]["hiddenValues"]
    assert hidden["declared"] == ["R1"]
    assert hidden["written"] == ["R1"]
    assert hidden["readBack"] != "confirmed"
    assert hidden.get("confirmed", []) == [], (
        "a row the document still prints is never reported as confirmed"
    )
    assert editor.calls.count("sys.set_document_source") == 1, (
        "one attempt, then the document decides — a write whose outcome is "
        "disagreed with is never retried"
    )
    _nothing_was_drawn(editor, payload)
    assert any("值行" in item or "value row" in item for item in payload["notes"])


def test_a_row_the_document_does_not_carry_is_not_already(
    monkeypatch, tmp_path, capsys,
):
    """No record for the row is `missing` — never `already`, and never a pass.

    `532`'s reader reports a designator with no `Name` record as missing; the
    plan states that row is not printed, and a document that holds no such record
    cannot confirm it (the render is what would decide, and the run has not
    reached a render).
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=_document_source({"R2": "true"}),
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_row_missing", payload.get("reason")
    hidden = payload["write"]["hiddenValues"]
    assert hidden["missing"] == ["R1"]
    assert hidden["readBack"] != "already", (
        "a missing row must not be read as the already-hidden state"
    )
    assert "sys.set_document_source" not in editor.calls
    _nothing_was_drawn(editor, payload)


def test_an_empty_document_is_not_already_either(monkeypatch, tmp_path, capsys):
    """The empty source is the degenerate case of the same rule, not a special one."""
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source="",
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_row_missing", payload.get("reason")
    hidden = payload["write"]["hiddenValues"]
    assert hidden["written"] == [] and hidden["missing"] == ["R1"]
    assert hidden["readBack"] != "already"
    assert "sys.set_document_source" not in editor.calls
    _nothing_was_drawn(editor, payload)


def test_a_flag_that_is_not_false_is_not_already(monkeypatch, tmp_path, capsys):
    """`rewritten == source` is not the postcondition; *each row reads false* is.

    A row whose flag is `null` cannot be flipped (`hide_value_rows` only writes
    `true` → `false`) and cannot be read as false — so the document changed
    nothing and states nothing, and "already" would be a pass this page never
    earned.
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=_document_source({"R1": "null", "R2": "true"}),
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_unconfirmed", payload.get("reason")
    hidden = payload["write"]["hiddenValues"]
    assert hidden["readBack"] != "already"
    assert hidden.get("confirmed", []) == []
    assert "sys.set_document_source" not in editor.calls, (
        "there was nothing to write; what failed is the read-back"
    )
    _nothing_was_drawn(editor, payload)


def test_a_page_the_editor_will_not_focus_stops_the_run(
    monkeypatch, tmp_path, capsys,
):
    """The flags live in the **active** document, so an unfocusable page is a stop.

    `sys.set_document_source` reads and rewrites only the focused document; a
    write aimed at a page the editor will not bring forward would edit the wrong
    file, so this refuses rather than reporting the rows as handled.
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=_document_source({"R1": "true", "R2": "true"}),
        active_page="page-other", focus_refused=True,
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_page_not_active", (
        payload.get("reason")
    )
    assert payload["write"]["hiddenValues"]["readBack"] == "page_not_active"
    assert "sys.set_document_source" not in editor.calls
    _nothing_was_drawn(editor, payload)


def test_a_row_already_false_is_not_written_and_the_run_continues(
    monkeypatch, tmp_path, capsys,
):
    """The protection's other half: the state the plan asks for is a pass.

    `R1` is already `valueVisible: false`, so there is nothing to write and no
    document write happens at all — and the run still lands the drawing (this is
    the path a second apply takes, and refusing it would break idempotence).
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=_document_source({"R1": "false", "R2": "true"}),
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 0, printed
    hidden = payload["write"]["hiddenValues"]
    assert hidden["readBack"] == "already"
    assert hidden["confirmed"] == ["R1"], (
        "the pass is stated as the flag that was read, not as a write that happened"
    )
    assert hidden["missing"] == []
    actions = [action for action, _params in editor.writes]
    assert "sys.set_document_source" not in actions, (
        "an already-hidden row is not rewritten — the page keeps the document it had"
    )
    assert "sch.place_wire" in actions and "sch.doc.save" in actions
    assert payload["write"]["pinReadback"]["problems"] == []
    assert payload["verification"]["ok"] is True


# ------------------ 542 F1: the whole-page read is an envelope, not a string


SOURCE_CAP = 4_000_000
TAIL_MARKER = '{"type":"WIRE","id":"TAIL_MARKER"}||{"net":"VIN"}|'


def _document_source_padded(rows: dict[str, str], total: int, *, tail: str = "") -> str:
    """`_document_source`, padded with whole record lines to exactly ``total``.

    The rows under test stay at the **front** — a page's first parts are, and that
    is what makes the truncation dangerous: `hide_value_rows` finds them in the
    prefix of a cut stream and happily rewrites it.  ``tail`` goes past the cap,
    so a read of the stream answers the front and loses it.
    """
    base = _document_source(rows)
    filler = '{"type":"COMPONENT","id":"filler","ticket":1}||{"x":0,"y":0}|'
    lines = [base]
    length = len(base) + 1
    while length < total:
        lines.append(filler)
        length += len(filler) + 1
    body = "\n".join(lines)
    while len(body) > total:
        body = body.rsplit("\n", 1)[0]
    body += "\n" * (total - len(body))
    assert len(body) == total, (len(body), total)
    assert base in body
    return body + tail


def test_a_truncated_page_read_is_never_rewritten(monkeypatch, tmp_path, capsys):
    """542 F1: 4,000,000 of 4,000,116 characters is the front of the page.

    `hide_value_rows` finds R1's `Name` ATTR in the prefix (it is at the front, as
    a real page's first parts are), flips it, and the pre-fix flow wrote the cut
    stream back — the document lost everything past `maxChars` (the probe's
    `TAIL_MARKER`), and the run went on to draw.  A read that does not answer the
    whole page cannot be the basis of a rewrite, so this stops **before**
    `sys.set_document_source`, and the page keeps the document it had.
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    source = _document_source_padded(
        {"R1": "true", "R2": "true"}, SOURCE_CAP, tail="\n" + TAIL_MARKER + "\n"
    )
    assert len(source) > SOURCE_CAP
    assert "R1" in source[:SOURCE_CAP], "the target row is in the prefix, by design"
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=source,
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_source_unverified", (
        payload.get("reason")
    )
    assert "sys.set_document_source" not in editor.calls, (
        "a truncated read must not be rewritten: the write would store the front "
        "of the page and drop the rest"
    )
    assert editor.document_source == source, "the page keeps the document it had"
    assert "TAIL_MARKER" in editor.document_source
    envelope = payload["write"]["hiddenValues"]["sourceEnvelope"]
    assert envelope["truncated"] is True
    assert envelope["maxChars"] == SOURCE_CAP
    assert envelope["chars"] == len(source)
    assert envelope["problem"].startswith(
        f"the answer is the first {SOURCE_CAP} of {len(source)} character(s)"
    ), (
        "the refusal has to be the truncation arm: uuid and type were answered "
        "correctly, so a different problem would mean the test proved the wrong thing"
    )
    assert envelope["uuid"] and envelope["type"] == "page"
    assert payload["write"]["hiddenValues"]["readBack"] == "source_unverified"
    assert all(request.get("uuid") for request in editor.source_requests), (
        "the read stands behind a page, so it names the page it read — every time"
    )
    _nothing_was_drawn(editor, payload)


def test_a_write_that_grows_the_page_past_the_cap_is_not_confirmed(
    monkeypatch, tmp_path, capsys,
):
    """A complete read before the write, a cut one after it: still no confirmation.

    The host re-serialises the page on `set_document_source`, so the stored
    document can be longer than the text that was handed to it.  The read-back is
    then the front of the page — it may even show R1's flag flipped, since R1 is
    early in the stream — and the pre-fix flow called that `confirmed` and drew.
    One write, no retry, and no pass from a stream that does not answer the page.
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    source = _document_source_padded({"R1": "true", "R2": "true"}, SOURCE_CAP - 100)
    assert len(source) < SOURCE_CAP, "the pre-write read has to be complete"
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=source, source_grow_on_write=400,
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_readback_unverified", (
        payload.get("reason")
    )
    assert editor.calls.count("sys.set_document_source") == 1, (
        "one write, then the document decides — a read that is not the page is "
        "never retried"
    )
    assert len(editor.document_source) > SOURCE_CAP, (
        "the write grew the document past the cap, or this test proves nothing"
    )
    hidden = payload["write"]["hiddenValues"]
    assert hidden["readBack"] != "confirmed"
    assert hidden["confirmed"] == [], (
        "a truncated read-back is not the page, so it cannot confirm a row"
    )
    assert hidden["readBackEnvelope"]["truncated"] is True
    assert hidden["readBackEnvelope"]["chars"] > SOURCE_CAP
    _nothing_was_drawn(editor, payload)


@pytest.mark.parametrize(
    "answer",
    [
        {"source_uuid": "page-other"},
        {"source_type": "sch"},
    ],
    ids=["the-answer-names-another-document", "the-answer-is-not-a-page"],
)
def test_a_read_of_some_other_document_is_not_this_pages_source(
    monkeypatch, tmp_path, capsys, answer,
):
    """The envelope's other two refusals: wrong `uuid`, wrong `type`.

    `sys.get_document_source` names the document it answered (`uuid`, `type`), and
    a caller that does not check them is reading whatever was in front of the
    editor — `178b`'s failure mode, where page B's source answered for page A.
    These flags are page state, so a read of some other document is not this
    page's source, and nothing is written from it.
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    source = _document_source({"R1": "true", "R2": "true"})
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=source, **answer,
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_source_unverified", (
        payload.get("reason")
    )
    assert "sys.set_document_source" not in editor.calls, (
        "the flags belong to the plan's page; another document's source is not it"
    )
    assert editor.document_source == source
    envelope = payload["write"]["hiddenValues"]["sourceEnvelope"]
    assert envelope["uuid"] or envelope["type"], "the refusal names what it read"
    assert {request.get("uuid") for request in editor.source_requests} == {editor.page}
    _nothing_was_drawn(editor, payload)


def test_a_read_that_does_not_say_it_was_complete_is_not_trusted(
    monkeypatch, tmp_path, capsys,
):
    """A missing `truncated` is not a `false` — 542 F1's fail-closed direction.

    The envelope exists so a caller can tell a whole page from its front.  An
    answer that names the page, is a page, and hands back 4,000,000 characters of
    a 4,000,116-character stream while **omitting** `truncated` has not said the
    read was complete; reading that silence as "complete" is how the pre-fix flow
    applied the cut page (tail dropped, then wires).  Only an explicit
    `truncated: false` may be trusted.
    """
    plan_path, plan = _plan_hiding(tmp_path, "R1")
    source = _document_source_padded(
        {"R1": "true", "R2": "true"}, SOURCE_CAP, tail="\n" + TAIL_MARKER + "\n"
    )
    assert len(source) > SOURCE_CAP
    editor = _FakeEditor(
        exists=False, netlists=[{"components": {}}, _live_netlist_for(plan)],
        document_source=source, source_hide_truncated=True,
    )
    code, payload, printed = _apply(monkeypatch, tmp_path, plan_path, editor, capsys)
    assert code == 3, printed
    assert payload["reason"] == "value_visibility_source_unverified", (
        payload.get("reason")
    )
    assert "sys.set_document_source" not in editor.calls, (
        "an envelope that never says `truncated: false` is not the page, so there "
        "is nothing to rewrite from"
    )
    assert editor.document_source == source, "nothing was cut off the page"
    assert "TAIL_MARKER" in editor.document_source
    envelope = payload["write"]["hiddenValues"]["sourceEnvelope"]
    assert envelope["truncated"] is None, "the answer did not carry the field"
    assert "truncated" in envelope["problem"], envelope["problem"]
    _nothing_was_drawn(editor, payload)

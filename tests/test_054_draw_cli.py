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

    # ---------------------------------------------------------- the page

    def add(self, designator: str, x: float, y: float, *, rotation: float = 0.0,
            mirror: bool = False, lcsc: str = "C25744") -> None:
        self.components[designator] = {
            "x": x, "y": y, "rotation": rotation, "mirror": mirror, "lcsc": lcsc,
        }

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
                           "Mirror": item["mirror"]}}
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
            return {
                "documents": documents,
                "projects": [{"projectUuid": "proj-1", "name": "test", "focused": True}],
                "active": {"uuid": self.page if self.exists else None, "type": "sch"},
                "count": len(documents),
            }
        if action == "doc.focus":
            self.page = str(params.get("pageUuid") or self.page)
            return {"activated": True, "tabId": "tab", "documentType": "sch"}
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
                # axis — mirror *after* rotation, which is the opposite order to
                # `core.geometry.transform_point`'s.
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
        if action == "sch.place_power":
            self.writes.append((action, params))
            self.flag(str(params.get("net") or ""), float(params.get("x") or 0.0),
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
    """Serve the live export, its model and the findings baseline."""
    models = list(sequence) if sequence is not None else None

    async def _export(call, notes):
        return b"export-bytes"

    def _parse(blob, notes):
        if models is not None:
            return models.pop(0) if models else None
        return type("Model", (), {"components": dict(components or {})})()

    monkeypatch.setattr(cli, "_live_project_export", _export)
    monkeypatch.setattr(cli, "_model_from_export", _parse)
    monkeypatch.setattr(cli, "_baseline_findings", lambda model: list(findings or []))


def _plan(tmp_path: Path, *, page: str = "", pool=(), name: str = "plan.json"):
    """The fixture drawing as a plan, built the way `draw plan` builds it."""
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
            _FakeEditor(page=page).geometry()
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
    """The netlist the plan says the finished page must show, hand-written."""
    live = {"components": {}}
    for index, island in enumerate(sorted(
        {tuple(item.mates) for item in plan.change.islands}
    )):
        name = f"NET{index + 1}"
        for member in island:
            designator, _sep, pin = member.partition(".")
            entry = live["components"].setdefault(
                f"c{len(live['components'])}",
                {"props": {"Designator": designator}, "pinInfoMap": {}},
            )
            entry["pinInfoMap"][pin] = {"net": name}
    return live


def _page_with(plan: ChangePlan) -> _FakeEditor:
    """An editor whose page already *is* the plan."""
    editor = _FakeEditor(page="page-1", netlists=[_live_netlist_for(plan)])
    for part in plan.change.draw_parts:
        editor.add(part.designator, part.x, part.y, rotation=part.rotation,
                   mirror=part.mirror, lcsc=part.lcsc)
    for wire in plan.change.draw_wires:
        editor.wire(wire.net, wire.points)
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
        "sch.place_wire", "sch.place_wire", "sch.place_wire", "sch.place_wire",
        "sch.place_power", "sch.place_power",
        "sch.doc.save",
    ], "the order the task book fixes: parts, pins, wires, flags, save"
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


def test_a_mirrored_part_is_placed_at_its_own_angle(monkeypatch, tmp_path, capsys):
    """The mirror case: the editor mirrors **after** rotating (054's measurement).

    `editor_pose` hands a mirrored pose its angle unchanged, because the API's
    composition is `mirror_x ∘ CW(R)` and the layout's is `CCW(R) ∘ mirror_x`.
    Sending the negated angle (which is right for `mirror=False`) puts the two
    pads the wrong way round — the failure the first live C1 run hit.
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
    assert placed[part.designator]["rotation"] == 90
    assert placed[part.designator]["mirror"] is True
    assert "verification_disagrees" not in printed


def test_a_repeat_apply_writes_nothing_at_all(monkeypatch, tmp_path, capsys):
    """C4: the plan's own postconditions, read on the page, say `already_applied`."""
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

    def _findings(model):
        calls["n"] += 1
        return [] if calls["n"] == 1 else ["rule|new|thing"]

    monkeypatch.setattr(cli, "_baseline_findings", _findings)
    code = cli.main(["draw", "apply", str(plan_path), "--new-page", "--project", "test"])
    printed = capsys.readouterr().out
    assert code == 2, printed
    assert "sch.doc.save" not in [action for action, _params in editor.writes]
    assert "new_finding" in printed or "新增 finding" in printed

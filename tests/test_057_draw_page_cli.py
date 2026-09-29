"""057 stage C2b: a page document through `draw compile|plan|apply` and `draw discard`.

The editor half of the page compiler, against a fake editor whose page really
changes. The seams are 054's (see `test_054_draw_cli`), with three additions
this batch needs:

* **stable primitive ids** — every part, wire and flag the fake holds keeps the
  id it was given, across deletes, because "everything that was not the plan's
  is field-for-field what it was" (057 sec.2) is judged by primitive id, and a
  fake that renumbered its wires after a delete would make that claim untestable;
* **measured extents** — `sch.geometry` with ``bboxIds`` answers each requested
  component's box (origin, pin tips and a small body), which is what the census
  keep-outs are built from;
* **deletes** — `sch.delete_primitives` really removes, one id at a time, and
  answers the connector's own ``{deleted, notFound, failed}`` shape.

The netlist is hand-written from the plan's own islands (054's rule: the
expectation is the test's, never derived from the implementation). The specs are
hand-written JSON (056's rule), written to ``tmp_path``.

E1–E7 are the task book's real-machine scenes; what a fake can decide about each
is decided here, and the real-machine half is the runbook's
(`tools/057_live_runbook.md`).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.changeplan import DRAW_MODULE_KIND, ChangePlan
from boardwise.core.pagelayoutplan import PageLayoutPlan
from boardwise.engines import drawapply, pagecompiler

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "drawapply"
LIBRARY = FIXTURES / "library.json"
PAGE_BOX = "0,0,1169,826"
SHEET = {"minX": 0, "minY": 0, "maxX": 1169, "maxY": 826}
PROV = "verified_recipe"

#: The pin geometry the fake editor answers with, keyed by LCSC number — the
#: fixture library's own geometry (R0402 ±50 vertical, C0402 ±40, the AMS1117
#: with VIN left, VOUT right, GND below), so a correct landing reads back clean.
PIN_OFFSETS = {
    "C25744": {"1": (0.0, 50.0), "2": (0.0, -50.0)},
    "C15525": {"1": (0.0, 40.0), "2": (0.0, -40.0)},
    "C45783": {"1": (0.0, 40.0), "2": (0.0, -40.0)},
    "C6186": {"3": (-60.0, 0.0), "2": (60.0, 0.0), "1": (0.0, -60.0)},
}


class _BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------ the specs


def part(part_id, symbol, value, lcsc):
    return {"id": part_id, "symbolRef": symbol, "value": value, "lcsc": lcsc,
            "provenance": PROV}


def net(net_id, cls, members):
    return {"id": net_id, "class": cls, "members": members, "provenance": PROV}


def page_circuit() -> dict:
    """An LDO and a divider sharing the input rail and the ground (056 scene 1's shape)."""
    return {
        "parts": [
            part("U1", "AMS1117-3.3", "AMS1117-3.3", "C6186"),
            part("C1", "C0402", "10uF", "C15525"),
            part("C2", "C0402", "22uF", "C45783"),
            part("R1", "R0402", "10k", "C25744"),
            part("R2", "R0402", "10k", "C25744"),
        ],
        "nets": [
            net("VIN", "power", ["U1.3", "C1.1", "R1.1"]),
            net("3V3", "power", ["U1.2", "C2.1"]),
            net("TAP", "signal", ["R1.2", "R2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2", "R2.2"]),
        ],
    }


def page_presentation(**extra) -> dict:
    payload = {
        "modules": [
            {"id": "pwr", "parts": ["U1", "C1", "C2"], "role": "regulator",
             "grammarRef": "ldo"},
            {"id": "sense", "parts": ["R1", "R2"], "role": "divider",
             "grammarRef": "voltage-divider"},
        ],
        "flow": [["pwr", "sense"]],
        "portRoles": {"VIN": "input", "3V3": "output"},
        "directWiringObligations": [
            {"nets": ["VIN", "3V3"], "note": "the regulator's own rails are wired"},
        ],
    }
    payload.update(extra)
    return payload


def write_specs(tmp_path: Path, *, circuit=None, presentation=None) -> tuple[Path, Path]:
    circuit_path = tmp_path / "page.circuit.json"
    presentation_path = tmp_path / "page.presentation.json"
    circuit_path.write_text(json.dumps(circuit or page_circuit()), encoding="utf-8")
    presentation_path.write_text(
        json.dumps(presentation or page_presentation()), encoding="utf-8"
    )
    return circuit_path, presentation_path


# ----------------------------------------------------------- the fake editor


class _PageEditor:
    """A schematic page with stable ids, measured extents and real deletes."""

    def __init__(self, *, page: str = "page-1", netlists=None, save_ok: bool = True,
                 timeouts=(), merge_wires_into: str = ""):
        self.page = page
        self.items: dict[str, dict] = {}
        self.order: list[str] = []
        self.counter = 0
        self.calls: list[str] = []
        self.writes: list[tuple[str, dict]] = []
        self.deletes: list[list[str]] = []
        self.netlists = list(netlists or [])
        self.netlist_reads = 0
        self.save_ok = save_ok
        self.timeouts = set(timeouts)
        #: The id of an existing wire the host "merges" every new wire of the same
        #: net into (pit 32) — how a landing that changes somebody else's wire is
        #: faked.
        self.merge_wires_into = merge_wires_into

    # ------------------------------------------------------------ the page

    def _new(self, prefix: str, item: dict, ident: str = "") -> str:
        self.counter += 1
        ident = ident or f"{prefix}-{self.counter}"
        self.items[ident] = item
        self.order.append(ident)
        return ident

    def add_part(self, designator, x, y, *, lcsc="C25744", value=None, rotation=0.0,
                 mirror=False, ident=""):
        item = {"kind": "part", "designator": designator, "x": float(x), "y": float(y),
                "rotation": float(rotation), "mirror": bool(mirror), "lcsc": lcsc,
                "value": value}
        return self._new("c", item, ident)

    def add_wire(self, net_name, points, ident=""):
        return self._new("w", {"kind": "wire", "net": net_name,
                               "points": [list(point) for point in points]}, ident)

    def add_flag(self, net_name, x, y, ident=""):
        return self._new("f", {"kind": "netflag", "net": net_name, "x": float(x),
                               "y": float(y)}, ident)

    def parts(self) -> dict[str, dict]:
        return {ident: item for ident, item in self.items.items() if item["kind"] == "part"}

    def pins_of(self, item) -> dict[str, tuple[float, float]]:
        out = {}
        for number, (dx, dy) in sorted(PIN_OFFSETS.get(item["lcsc"], {}).items()):
            rotation = item["rotation"]
            # The editor's own composition (054 pit 29): clockwise rotation, then a
            # mirror about the canvas vertical axis.
            if rotation == 90:
                dx, dy = dy, -dx
            elif rotation == 180:
                dx, dy = -dx, -dy
            elif rotation == 270:
                dx, dy = -dy, dx
            if item["mirror"]:
                dx = -dx
            out[number] = (item["x"] + dx, item["y"] + dy)
        return out

    def extent(self, item) -> dict:
        if item["kind"] == "netflag":
            box = (item["x"] - 6, item["y"] - 2, item["x"] + 6, item["y"] + 18)
        else:
            points = list(self.pins_of(item).values()) + [(item["x"], item["y"])]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            box = (min(xs) - 10, min(ys) - 10, max(xs) + 10, max(ys) + 10)
        return {"minX": box[0], "minY": box[1], "maxX": box[2], "maxY": box[3]}

    def geometry(self, bbox_ids=()) -> dict:
        components = [{"primitiveId": "sheet-1",
                       "state": {"ComponentType": "sheet", "Designator": "", "X": 0, "Y": 0}}]
        wires = []
        for ident in self.order:
            item = self.items[ident]
            if item["kind"] == "part":
                state = {"ComponentType": "part", "Designator": item["designator"],
                         "X": item["x"], "Y": item["y"], "Rotation": item["rotation"],
                         "Mirror": item["mirror"], "SupplierId": item["lcsc"]}
                if item["value"] is not None:
                    state["OtherProperty"] = {"Value": item["value"]}
                components.append({"primitiveId": ident, "state": state})
            elif item["kind"] == "netflag":
                components.append({"primitiveId": ident, "state": {
                    "ComponentType": "netflag", "Designator": None, "Net": item["net"],
                    "X": item["x"], "Y": item["y"], "Rotation": 0, "Mirror": False}})
            else:
                wires.append({"primitiveId": ident, "state": {
                    "Line": [c for point in item["points"] for c in point],
                    "Net": item["net"]}})
        bboxes = {"sheet-1": SHEET}
        for ident in bbox_ids:
            if ident in self.items and self.items[ident]["kind"] != "wire":
                bboxes[ident] = self.extent(self.items[ident])
        return {"components": components, "wires": wires, "pins": [], "netlabels": [],
                "bboxes": bboxes, "meta": {"available": {"components": True}}}

    # ----------------------------------------------------------- the calls

    async def call(self, action, params=None, **_route):
        params = params or {}
        self.calls.append(action)
        if action in self.timeouts:
            self.timeouts.discard(action)
            raise _BridgeError("TIMEOUT", f"{action} did not answer within 30 s")
        if action == "doc.list":
            return {
                "documents": [{"uuid": self.page, "name": "P1", "type": "sch"}],
                "projects": [{"projectUuid": "proj-1", "name": "test", "focused": True}],
                "active": {"uuid": self.page, "type": "sch"},
            }
        if action == "doc.focus":
            return {"activated": True}
        if action == "sys.identity":
            return {"consistent": True, "consistentBasis": "project-uuid"}
        if action == "sch.geometry":
            return self.geometry(params.get("bboxIds") or ())
        if action == "sch.netlist":
            index = min(self.netlist_reads, len(self.netlists) - 1)
            self.netlist_reads += 1
            payload = self.netlists[index] if self.netlists else {"components": {}}
            return {"type": params.get("type"), "text": json.dumps(payload)}
        if action == "sch.component_pins":
            item = self.items.get(str(params.get("primitiveId") or ""))
            pins = [
                {"X": x, "Y": y, "PinNumber": number, "PinName": number}
                for number, (x, y) in sorted((self.pins_of(item) if item else {}).items())
            ]
            return {"primitiveId": params.get("primitiveId"), "pins": pins}
        if action == "sch.place_component":
            self.writes.append((action, params))
            ident = self.add_part(
                str(params.get("designator") or ""), params.get("x"), params.get("y"),
                lcsc=str(params.get("lcsc") or ""),
                rotation=float(params.get("rotation") or 0.0),
                mirror=bool(params.get("mirror")),
            )
            return {"uuid": ident}
        if action == "sch.set_component_attribute":
            self.writes.append((action, params))
            item = self.items[str(params.get("primitiveId"))]
            item["value"] = str(params.get("value") or "")
            return {"applied": True, "readBackAfter": item["value"]}
        if action == "sch.place_wire":
            self.writes.append((action, params))
            net_name = str(params.get("net") or "")
            target = self.items.get(self.merge_wires_into)
            if target is not None and target["net"] == net_name:
                # The host merges a touching wire into the existing primitive.
                target["points"].extend(list(point) for point in params.get("points") or [])
                return {"uuid": self.merge_wires_into}
            return {"uuid": self.add_wire(net_name, params.get("points") or [])}
        if action == "sch.place_power":
            self.writes.append((action, params))
            return {"uuid": self.add_flag(str(params.get("net") or ""), params.get("x"),
                                          params.get("y"))}
        if action == "sch.delete_primitives":
            self.writes.append((action, params))
            ids = [str(item) for item in params.get("primitiveIds") or []]
            self.deletes.append(ids)
            deleted = [ident for ident in ids if ident in self.items]
            for ident in deleted:
                del self.items[ident]
                self.order.remove(ident)
            return {"deleted": deleted,
                    "notFound": [ident for ident in ids if ident not in deleted],
                    "failed": []}
        if action == "sch.doc.save":
            if not self.save_ok:
                raise _BridgeError("CONNECTOR_ERROR", "the editor refused the save")
            self.writes.append((action, params))
            return {"saved": True}
        if action == "export.render":
            blob = b"\x89PNG\r\n\x1a\n" + b"fake page render"
            return {"format": "png", "scope": "page", "pageUuid": self.page,
                    "data": base64.b64encode(blob).decode("ascii")}
        raise AssertionError(f"the flow called {action}, which this fake does not answer")

    async def close(self):
        return None

    def snapshot(self) -> dict:
        return json.loads(json.dumps(self.items))


def _stub_editor(monkeypatch, editor) -> None:
    class _Client:
        @staticmethod
        async def open(*_args, **_kwargs):
            return editor

    monkeypatch.setattr(cli, "_open_cli", lambda args: (_Client, _BridgeError, 61190, "tok"))


def _stub_export(monkeypatch, *, components=None, findings=None, sequence=None):
    """Serve the live export and the findings (a list per read when `sequence`)."""
    reads = list(sequence) if sequence is not None else None

    async def _export(call, notes):
        return b"export-bytes"

    def _parse(blob, notes):
        return type("Model", (), {"components": dict(components or {})})()

    def _findings(model):
        if reads is not None:
            return list(reads.pop(0)) if reads else []
        return list(findings or [])

    monkeypatch.setattr(cli, "_live_project_export", _export)
    monkeypatch.setattr(cli, "_model_from_export", _parse)
    monkeypatch.setattr(cli, "_baseline_findings", _findings)


def _netlist_for(plan: ChangePlan, *, split: str = "") -> dict:
    """The netlist the plan says the page must show; ``split`` breaks one net in two."""
    live = {"components": {}}
    for index, island in enumerate(sorted({tuple(item.mates) for item in plan.change.islands})):
        name = f"NET{index + 1}"
        for position, member in enumerate(island):
            designator, _sep, pin = member.partition(".")
            if split and split in island and position % 2:
                # The pin is on a net of its own — the same-named net did not merge.
                pin_net = f"{name}_ISLAND"
            else:
                pin_net = name
            entry = live["components"].setdefault(
                designator, {"props": {"Designator": designator}, "pinInfoMap": {}},
            )
            entry["pinInfoMap"][pin] = {"net": pin_net}
    return live


def _plan_args(circuit, presentation, *rest):
    return ["draw", "plan", "--circuit", str(circuit), "--presentation", str(presentation),
            "--profiles", str(LIBRARY), "--page-box", PAGE_BOX, *rest]


def _plan_page(monkeypatch, tmp_path, editor, *, findings=(), extra=()):
    """`draw plan` bound to the fake page — the census is read, the keep-outs made."""
    circuit, presentation = write_specs(tmp_path)
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch, findings=list(findings))
    out = tmp_path / "plan.json"
    code = cli.main(_plan_args(circuit, presentation, "--page", editor.page,
                               "--out", str(out), "--json", str(tmp_path / "plan.report.json"),
                               *extra))
    return code, out, circuit, presentation


def _apply(editor, plan_path, circuit, presentation, tmp_path, *extra):
    report = tmp_path / "apply.json"
    code = cli.main([
        "draw", "apply", str(plan_path), "--project", "test",
        "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(LIBRARY), "--json", str(report),
        "--render", str(tmp_path / "render.png"), *extra,
    ])
    return code, json.loads(report.read_text(encoding="utf-8"))


# -------------------------------------------------------------- draw compile


def test_a_page_presentation_compiles_to_page_documents_on_the_same_command(tmp_path, capsys):
    """057 sec.1: `modules[]` of a page -> page.json candidates, frames in the SVG."""
    circuit, presentation = write_specs(tmp_path)
    out = tmp_path / "previews"
    report = tmp_path / "compile.json"
    code = cli.main([
        "draw", "compile", "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX, "--out", str(out),
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "page of 2 module(s)" in printed
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["document"] == "page" and payload["pages"]
    document = PageLayoutPlan.load(out / "cand1.page.json")
    assert [module.id for module in document.modules] == ["pwr", "sense"]
    assert payload["pages"][0]["geometrySha256"] == document.page_geometry_sha256()
    svg = (out / "cand1.svg").read_text(encoding="utf-8")
    assert "pwr" in svg and "sense" in svg, "the module frames are drawn and named"
    assert not (out / "cand1.layout.json").exists(), "a page writes page documents"


def test_a_page_compile_without_a_sheet_is_refused_by_name(tmp_path, capsys):
    circuit, presentation = write_specs(tmp_path)
    code = cli.main([
        "draw", "compile", "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(LIBRARY), "--out", str(tmp_path / "out"),
    ])
    assert code == 5
    assert "--page-box" in capsys.readouterr().err


def test_what_makes_a_presentation_a_page():
    """The single-module documents keep their path (the 054 fixture is one module)."""
    from boardwise.core.presentationspec import PresentationSpec

    single = PresentationSpec.load(FIXTURES / "divider.presentation.json")
    assert not pagecompiler.wants_page(single)
    assert pagecompiler.wants_page(PresentationSpec.from_dict(page_presentation()))
    one_with_flow = page_presentation()
    one_with_flow["modules"] = one_with_flow["modules"][:1]
    one_with_flow["modules"][0]["parts"] = ["U1", "C1", "C2"]
    one_with_flow.pop("flow")
    assert pagecompiler.wants_page(PresentationSpec.from_dict(one_with_flow)), (
        "a module that states its own grammar is a page statement"
    )
    locked = {"grammarRef": "voltage-divider",
              "modules": [{"id": "d", "parts": ["R1", "R2"], "role": "divider"}],
              "userLocks": [{"partId": "R1", "x": 100, "y": 100, "scope": "page"}]}
    assert pagecompiler.wants_page(PresentationSpec.from_dict(locked))


# ----------------------------------------------------------------- draw plan


def test_an_offline_page_plan_is_a_draw_module_plan_of_the_pages_drawing(tmp_path, capsys):
    circuit, presentation = write_specs(tmp_path)
    out = tmp_path / "plan.json"
    code = cli.main(_plan_args(circuit, presentation, "--out", str(out)))
    printed = capsys.readouterr().out
    assert code == 0, printed
    plan = ChangePlan.load(out)
    page = PageLayoutPlan.load(tmp_path / "plan.page.json")
    assert plan.change.kind == DRAW_MODULE_KIND
    # The page's guard evidence is its `plan` field's (057 sec.1): the layout digest
    # the plan carries is the merged drawing's, not a second one invented for pages.
    assert plan.change.layout_sha256 == page.plan.geometry_sha256()
    assert plan.change.circuit_sha256 == page.plan.source.circuit_sha256
    assert plan.target.module.startswith("page pwr+sense")
    assert sorted(part.designator for part in plan.change.draw_parts) == [
        "C1", "C2", "R1", "R2", "U1"
    ]


def test_a_page_label_no_wire_reaches_becomes_a_named_stub(tmp_path, capsys):
    """G4's ground: the divider's VIN pin must carry the name, or it never merges.

    069 sec.7 moved the *default* for a rail from a label to a flag, so the label
    this test is about now comes from the one route a rail can still take one: a
    library that carries no flag symbol for the net (`_net_style`'s "the library
    carries no flag symbol" answer). The downgrade it exercises — a label at a bare
    pin tip is not placeable on this host, so a named stub carries the name — is
    unchanged either way.
    """
    circuit, presentation = write_specs(tmp_path)
    book = json.loads(LIBRARY.read_text(encoding="utf-8"))
    book["profiles"] = [
        profile for profile in book["profiles"]
        if profile["symbolRef"] != "PWR-VIN"
    ]
    flagged_less = tmp_path / "library.no-PWR-VIN.json"
    flagged_less.write_text(json.dumps(book), encoding="utf-8")
    out = tmp_path / "plan.json"
    assert cli.main([
        "draw", "plan", "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(flagged_less), "--page-box", PAGE_BOX, "--out", str(out),
    ]) == 0
    capsys.readouterr()
    plan = ChangePlan.load(out)
    page = PageLayoutPlan.load(tmp_path / "plan.page.json")
    labels = {(label.net, label.x, label.y) for label in page.plan.labels}
    assert any(net_name == "VIN" for net_name, _x, _y in labels)
    stubs = [wire for wire in plan.change.draw_wires if wire.purpose.startswith("name stub")]
    assert stubs, "a label at a bare pin tip is carried by a named stub"
    for stub in stubs:
        assert (stub.net, stub.points[0][0], stub.points[0][1]) in labels
        assert len(stub.points) == 2
        length = abs(stub.points[1][0] - stub.points[0][0]) + abs(
            stub.points[1][1] - stub.points[0][1])
        assert 0 < length <= drawapply.LABEL_STUB_LENGTH
        assert stub.from_pin, "the stub leaves the pin the label sat on"
    assert any("stub" in line for line in plan.change.draw_downgrades)


# ------------------------------------------------------------ E1: empty page


def test_e1_an_empty_page_lands_the_whole_page_and_reads_the_shared_nets_back(
    monkeypatch, tmp_path, capsys
):
    """E1 + E4 (fake half): compile -> plan -> apply; the shared nets are one net."""
    editor = _PageEditor()
    code, plan_path, circuit, presentation = _plan_page(monkeypatch, tmp_path, editor)
    assert code == 0, capsys.readouterr()
    plan = ChangePlan.load(plan_path)
    editor.netlists = [{"components": {}}, _netlist_for(plan)]
    code, report = _apply(editor, plan_path, circuit, presentation, tmp_path,
                          "--layout", str(tmp_path / "plan.page.json"))
    assert code == 0, capsys.readouterr().out
    assert report["outcome"] == "applied"
    assert report["guards"]["checked"]["layoutSha256"] is True
    nets = {tuple(row["pins"]): row for row in report["verification"]["nets"]}
    cross = [row for row in nets.values() if row["crossModule"]]
    assert cross, "VIN and GND span both modules"
    assert all(row["oneNet"] for row in cross)
    assert {tuple(sorted(row["modules"])) for row in cross} == {("pwr", "sense")}
    assert report["range"]["outOfScope"]["changed"] == []
    assert "sch.doc.save" in [action for action, _params in editor.writes]


def test_e4_a_shared_net_that_did_not_merge_is_not_saved(monkeypatch, tmp_path, capsys):
    """A cross-module net whose two ends stayed two islands is a read-back failure."""
    editor = _PageEditor()
    code, plan_path, circuit, presentation = _plan_page(monkeypatch, tmp_path, editor)
    assert code == 0
    plan = ChangePlan.load(plan_path)
    vin = next(
        member for island in plan.change.islands for member in island.mates
        if member.startswith("R") and len(island.mates) == 3
    )
    editor.netlists = [{"components": {}}, _netlist_for(plan, split=vin)]
    code, report = _apply(editor, plan_path, circuit, presentation, tmp_path)
    assert code == 3
    assert report["reason"] == "verification_disagrees"
    assert "sch.doc.save" not in [action for action, _params in editor.writes]


def test_e4_findings_are_judged_by_identity_not_by_count(monkeypatch, tmp_path, capsys):
    """One finding resolved and another created: the count is equal, the run is not clean."""
    editor = _PageEditor()
    circuit, presentation = write_specs(tmp_path)
    _stub_editor(monkeypatch, editor)
    before = ["decap-required-caps|WARN|U9|2|3V3"]
    after = ["decap-required-caps|WARN|U1|2|3V3"]
    _stub_export(monkeypatch, sequence=[before, after])
    out = tmp_path / "plan.json"
    assert cli.main(_plan_args(circuit, presentation, "--page", "page-1", "--out", str(out))) == 0
    plan = ChangePlan.load(out)
    assert plan.change.baseline_findings == before
    editor.netlists = [{"components": {}}, _netlist_for(plan)]
    code, report = _apply(editor, out, circuit, presentation, tmp_path)
    assert code == 2
    assert report["reason"] == "new_findings"
    assert report["findings"]["new"] == after
    assert report["findings"]["resolved"] == before


def test_e4_a_finding_the_page_resolves_is_reported_resolved(monkeypatch, tmp_path, capsys):
    editor = _PageEditor()
    circuit, presentation = write_specs(tmp_path)
    _stub_editor(monkeypatch, editor)
    before = ["decap-required-caps|WARN|U9|2|3V3"]
    _stub_export(monkeypatch, sequence=[before, []])
    out = tmp_path / "plan.json"
    assert cli.main(_plan_args(circuit, presentation, "--page", "page-1", "--out", str(out))) == 0
    plan = ChangePlan.load(out)
    editor.netlists = [{"components": {}}, _netlist_for(plan)]
    code, report = _apply(editor, out, circuit, presentation, tmp_path)
    assert code == 0, report["notes"]
    assert report["findings"]["resolved"] == before and report["findings"]["new"] == []


# ------------------------------------------------------- E2: a non-empty page


def _seed(editor: _PageEditor) -> None:
    """What was on the page before: a part, a wire and a flag in the top-left corner."""
    editor.add_part("R9", 80, 700, lcsc="C25744", value="1k", ident="c-old-R9")
    editor.add_wire("OLD", [(80, 750), (200, 750)], ident="w-old-1")
    editor.add_flag("GND", 80, 640, ident="f-old-1")


def test_e2_the_census_becomes_keepouts_and_the_page_goes_around_them(
    monkeypatch, tmp_path, capsys
):
    editor = _PageEditor()
    _seed(editor)
    before = editor.snapshot()
    code, plan_path, circuit, presentation = _plan_page(monkeypatch, tmp_path, editor)
    printed = capsys.readouterr().out
    assert code == 0, printed
    report = json.loads((tmp_path / "plan.report.json").read_text(encoding="utf-8"))
    assert report["live"]["keepouts"] >= 3, "a part, a wire segment and a flag"
    assert any("R9" in row["from"] for row in report["keepouts"])
    boxes = [tuple(row["box"]) for row in report["keepouts"]]
    page = PageLayoutPlan.load(tmp_path / "plan.page.json")
    for module in page.modules:
        for box in boxes:
            overlap = (min(module.frame[2], box[2]) - max(module.frame[0], box[0]) > 0
                       and min(module.frame[3], box[3]) - max(module.frame[1], box[1]) > 0)
            assert not overlap, f"{module.id} sits on {box}"
    plan = ChangePlan.load(plan_path)
    editor.netlists = [{"components": {}}, _netlist_for(plan)]
    code, applied = _apply(editor, plan_path, circuit, presentation, tmp_path)
    assert code == 0, applied["notes"]
    assert applied["range"]["outOfScope"] == {
        "items": 3, "changed": [], "basis": applied["range"]["outOfScope"]["basis"],
    }
    for ident, item in before.items():
        assert editor.items[ident] == item, f"{ident} was touched"


def test_e2_a_page_the_census_fills_is_presentation_poor_naming_what_is_there(
    monkeypatch, tmp_path, capsys
):
    editor = _PageEditor()
    for row in range(8):
        for column in range(12):
            editor.add_part(f"R{100 + row * 12 + column}", 50 + column * 95,
                            60 + row * 100, lcsc="C25744", value="1k")
    code, _plan_path, _circuit, _presentation = _plan_page(monkeypatch, tmp_path, editor)
    captured = capsys.readouterr()
    assert code == 5
    assert "presentation-poor" in captured.err
    assert "existing R1" in captured.err, "the keep-out is named by what is there"
    assert not editor.writes


def test_e2_a_landing_that_changes_an_existing_wire_is_not_saved(
    monkeypatch, tmp_path, capsys
):
    """057 sec.2's hard line: one existing primitive changed = the run failed."""
    editor = _PageEditor()
    editor.add_wire("GND", [(1100, 60), (1120, 60)], ident="w-old-gnd")
    code, plan_path, circuit, presentation = _plan_page(monkeypatch, tmp_path, editor)
    assert code == 0
    plan = ChangePlan.load(plan_path)
    if not any(wire.net == "GND" for wire in plan.change.draw_wires):
        pytest.skip("this page draws no GND wire to merge")
    editor.merge_wires_into = "w-old-gnd"
    editor.netlists = [{"components": {}}, _netlist_for(plan)]
    code, report = _apply(editor, plan_path, circuit, presentation, tmp_path)
    assert code == 2
    assert report["reason"] == "range_out_of_scope"
    assert any("w-old-gnd" in line for line in report["range"]["outOfScope"]["changed"])
    assert "sch.doc.save" not in [action for action, _params in editor.writes]


# -------------------------------------------------------------- E3: page locks


def test_e3_a_page_locked_part_reads_back_at_its_lock_point(monkeypatch, tmp_path, capsys):
    editor = _PageEditor()
    lock = {"partId": "R1", "x": 800, "y": 500, "scope": "page"}
    circuit, presentation = write_specs(
        tmp_path, presentation=page_presentation(userLocks=[lock]),
    )
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    out = tmp_path / "plan.json"
    assert cli.main(_plan_args(circuit, presentation, "--page", "page-1", "--out", str(out))) == 0
    plan = ChangePlan.load(out)
    r1 = next(part for part in plan.change.draw_parts if part.spec_id == "R1")
    assert (r1.x, r1.y) == (800.0, 500.0)
    editor.netlists = [{"components": {}}, _netlist_for(plan)]
    code, report = _apply(editor, out, circuit, presentation, tmp_path)
    assert code == 0, report["notes"]
    placed = next(item for item in editor.items.values()
                  if item["kind"] == "part" and item["designator"] == r1.designator)
    assert (placed["x"], placed["y"]) == (800.0, 500.0)


@pytest.mark.parametrize(
    "locks, named",
    [
        (
            [{"partId": "R1", "x": 800, "y": 500, "scope": "page"},
             {"partId": "R2", "x": 800, "y": 500, "scope": "page"}],
            ("userLocks[R1@page]", "userLocks[R2@page]"),
        ),
        ([{"partId": "R1", "x": 5000, "y": 500, "scope": "page"}], ("userLocks[R1@page]",)),
        ([{"partId": "U1", "x": 25, "y": 25, "scope": "page"}], ("userLocks[U1@page]",)),
    ],
    ids=["two-locks-disagree", "lock-off-the-page", "frame-off-the-page"],
)
def test_e3_a_lock_that_cannot_hold_is_presentation_poor_and_named(
    tmp_path, capsys, locks, named
):
    circuit, presentation = write_specs(
        tmp_path, presentation=page_presentation(userLocks=locks),
    )
    code = cli.main(_plan_args(circuit, presentation, "--out", str(tmp_path / "p.json")))
    err = capsys.readouterr().err
    assert code == 5
    assert "presentation-poor" in err
    for name in named:
        assert name in err


# ------------------------------------------------------------- E5: discard


def _landed(monkeypatch, tmp_path, capsys, *, seed=True):
    editor = _PageEditor()
    if seed:
        _seed(editor)
    code, plan_path, circuit, presentation = _plan_page(monkeypatch, tmp_path, editor)
    assert code == 0
    plan = ChangePlan.load(plan_path)
    editor.netlists = [{"components": {}}, _netlist_for(plan)]
    code, _report = _apply(editor, plan_path, circuit, presentation, tmp_path)
    assert code == 0, _report["notes"]
    capsys.readouterr()
    return editor, plan_path, plan, circuit, presentation


def _discard(plan_path, *extra, report_name="discard.json", tmp_path=None):
    target = (tmp_path or Path(plan_path).parent) / report_name
    code = cli.main(["draw", "discard", str(plan_path), "--project", "test",
                     "--json", str(target), *extra])
    return code, json.loads(target.read_text(encoding="utf-8"))


def test_e5_discard_deletes_the_plans_drawing_lines_first_and_nothing_else(
    monkeypatch, tmp_path, capsys
):
    editor, plan_path, plan, _circuit, _presentation = _landed(monkeypatch, tmp_path, capsys)
    old = {ident: item for ident, item in editor.snapshot().items() if "old" in ident}
    writes_before = len(editor.writes)
    code, report = _discard(plan_path, "--save")
    assert code == 0, report["notes"]
    assert report["outcome"] == "discarded"
    phases = [row["phase"] for row in report["deletes"]]
    assert phases == sorted(phases, key=["wires", "flags", "parts"].index)
    assert phases[-1] == "parts" and phases[0] == "wires"
    # Only the seeded primitives are left, exactly as they were.
    assert editor.snapshot() == old
    assert report["verify"]["remaining"] == [] and report["verify"]["outOfScope"] == []
    assert ("sch.doc.save", {}) in editor.writes[writes_before:]


def test_e5_a_second_discard_finds_nothing_and_writes_nothing(monkeypatch, tmp_path, capsys):
    editor, plan_path, _plan, _circuit, _presentation = _landed(monkeypatch, tmp_path, capsys)
    assert _discard(plan_path)[0] == 0
    deletes = len(editor.deletes)
    code, report = _discard(plan_path, report_name="second.json")
    assert code == 0
    assert report["outcome"] == "nothing_to_discard"
    assert len(editor.deletes) == deletes, "idempotent: zero deletes the second time"


def test_e5_one_part_that_is_not_the_plans_refuses_the_whole_batch(
    monkeypatch, tmp_path, capsys
):
    editor, plan_path, plan, _circuit, _presentation = _landed(monkeypatch, tmp_path, capsys)
    victim = plan.change.draw_parts[0]
    for item in editor.items.values():
        if item["kind"] == "part" and item["designator"] == victim.designator:
            item["value"] = "somebody else's value"
    snapshot = editor.snapshot()
    code, report = _discard(plan_path)
    assert code == 4
    assert report["reason"] == "identity_mismatch"
    assert any(victim.designator in line for line in report["selection"]["mismatches"])
    assert not editor.deletes, "not half a batch: nothing is deleted"
    assert editor.snapshot() == snapshot


def test_e5_a_moved_part_refuses_the_whole_batch(monkeypatch, tmp_path, capsys):
    editor, plan_path, plan, _circuit, _presentation = _landed(monkeypatch, tmp_path, capsys)
    victim = plan.change.draw_parts[-1]
    for item in editor.items.values():
        if item["kind"] == "part" and item["designator"] == victim.designator:
            item["x"] += 50
    code, report = _discard(plan_path)
    assert code == 4 and not editor.deletes
    assert any("the plan put it at" in line for line in report["selection"]["mismatches"])


def test_e5_a_wire_the_host_merged_with_a_foreign_one_is_never_deleted(
    monkeypatch, tmp_path, capsys
):
    editor, plan_path, plan, _circuit, _presentation = _landed(monkeypatch, tmp_path, capsys)
    wire = plan.change.draw_wires[0]
    for item in editor.items.values():
        if item["kind"] == "wire" and item["net"] == wire.net and list(
            wire.points[0]) in item["points"]:
            item["points"].append([9999.0, 9999.0])
            break
    code, report = _discard(plan_path)
    assert code == 4 and not editor.deletes
    assert any("merged" in line for line in report["selection"]["mismatches"])


def test_e5_a_delete_that_times_out_is_read_back_and_never_retried(
    monkeypatch, tmp_path, capsys
):
    editor, plan_path, _plan, _circuit, _presentation = _landed(monkeypatch, tmp_path, capsys)
    editor.timeouts = {"sch.delete_primitives"}
    code, report = _discard(plan_path, "--save")
    assert code == 3
    assert report["reason"] == "delete_unanswered"
    assert editor.calls.count("sch.delete_primitives") == 1
    assert "sch.doc.save" not in editor.calls[-3:]


def test_e5_a_page_document_is_discarded_by_position(monkeypatch, tmp_path, capsys):
    editor, _plan_path, plan, circuit, presentation = _landed(monkeypatch, tmp_path, capsys)
    old = {ident: item for ident, item in editor.snapshot().items() if "old" in ident}
    code, report = _discard(
        tmp_path / "plan.page.json", "--page", "page-1", "--circuit", str(circuit),
        "--presentation", str(presentation), "--profiles", str(LIBRARY),
    )
    assert code == 0, report["notes"]
    assert report["identifiedBy"].startswith("position")
    assert editor.snapshot() == old


# ------------------------------------------------------ E7: a stale page plan


def test_e7_a_changed_canvas_refuses_the_old_plan_before_any_write(
    monkeypatch, tmp_path, capsys
):
    editor = _PageEditor()
    code, plan_path, circuit, presentation = _plan_page(monkeypatch, tmp_path, editor)
    assert code == 0
    editor.add_part("R50", 1000, 100, lcsc="C25744", value="1k")
    code, report = _apply(editor, plan_path, circuit, presentation, tmp_path)
    assert code == 4
    assert report["reason"] == "canvas_changed"
    assert not editor.writes


def test_e7_a_page_document_whose_frames_were_built_on_is_refused(
    monkeypatch, tmp_path, capsys
):
    circuit, presentation = write_specs(tmp_path)
    out = tmp_path / "previews"
    assert cli.main([
        "draw", "compile", "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX, "--out", str(out),
    ]) == 0
    capsys.readouterr()
    document = PageLayoutPlan.load(out / "cand1.page.json")
    frame = document.modules[0].frame
    editor = _PageEditor()
    editor.add_part("R77", (frame[0] + frame[2]) / 2, (frame[1] + frame[3]) / 2,
                    lcsc="C25744", value="1k")
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    code, report = _apply(editor, out / "cand1.page.json", circuit, presentation, tmp_path,
                          "--page", "page-1")
    assert code == 4
    assert report["reason"] == "canvas_changed"
    assert any("R77" in line for line in report["guards"]["problems"])
    assert not editor.writes


def test_a_page_document_lands_directly_on_a_free_page(monkeypatch, tmp_path, capsys):
    """057 sec.1: `draw apply page.json` passes the `plan` field to the same flow."""
    circuit, presentation = write_specs(tmp_path)
    out = tmp_path / "previews"
    assert cli.main([
        "draw", "compile", "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX, "--out", str(out),
    ]) == 0
    capsys.readouterr()
    document = out / "cand1.page.json"
    page = PageLayoutPlan.load(document)
    editor = _PageEditor()
    _stub_editor(monkeypatch, editor)
    _stub_export(monkeypatch)
    rebuilt = cli._draw_plan_from_page(
        page, *cli._draw_inputs(type("A", (), {
            "circuit": str(circuit), "presentation": str(presentation),
            "profiles": str(LIBRARY)})()),
    )
    editor.netlists = [{"components": {}}, _netlist_for(rebuilt)]
    code, report = _apply(editor, document, circuit, presentation, tmp_path, "--page", "page-1")
    assert code == 0, report["notes"]
    assert report["document"] == "page"
    assert report["builtPlan"]["change"]["layoutSha256"] == page.plan.geometry_sha256()
    assert report["guards"]["checked"]["layoutSha256"] is True


def test_a_page_document_compiled_from_other_specs_is_refused_offline(
    monkeypatch, tmp_path, capsys
):
    circuit, presentation = write_specs(tmp_path)
    out = tmp_path / "previews"
    assert cli.main([
        "draw", "compile", "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX, "--out", str(out),
    ]) == 0
    changed = page_circuit()
    changed["parts"][3]["value"] = "12k"
    circuit.write_text(json.dumps(changed), encoding="utf-8")
    opened = []
    monkeypatch.setattr(cli, "_open_cli", lambda args: opened.append(1) or (_ for _ in ()).throw(
        AssertionError("the daemon must not be contacted")))
    code, report = _apply(None, out / "cand1.page.json", circuit, presentation, tmp_path,
                          "--page", "page-1")
    assert code == 4 and report["reason"] == "guard_refused"
    assert not opened


def test_a_page_document_needs_its_specs(tmp_path, capsys):
    circuit, presentation = write_specs(tmp_path)
    out = tmp_path / "previews"
    assert cli.main([
        "draw", "compile", "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX, "--out", str(out),
    ]) == 0
    code = cli.main(["draw", "apply", str(out / "cand1.page.json"), "--page", "page-1"])
    assert code == 5
    assert "--circuit" in capsys.readouterr().err


def test_a_layout_guard_given_another_page_refuses(monkeypatch, tmp_path, capsys):
    editor = _PageEditor()
    code, plan_path, circuit, presentation = _plan_page(monkeypatch, tmp_path, editor)
    assert code == 0
    other = tmp_path / "other"
    assert cli.main([
        "draw", "compile", "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(LIBRARY), "--page-box", PAGE_BOX, "--out", str(other),
    ]) == 0
    pages = sorted(other.glob("cand*.page.json"))
    mine = PageLayoutPlan.load(tmp_path / "plan.page.json").page_geometry_sha256()
    foreign = next(
        (path for path in pages if PageLayoutPlan.load(path).page_geometry_sha256() != mine),
        None,
    )
    if foreign is None:
        pytest.skip("the compile produced a single page")
    code, report = _apply(editor, plan_path, circuit, presentation, tmp_path,
                          "--layout", str(foreign))
    assert code == 4 and report["reason"] == "guard_refused"
    assert not editor.writes

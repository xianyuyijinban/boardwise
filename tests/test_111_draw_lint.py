"""Task 111: `draw lint` — the readability checker as a machine gate.

Nine geometric predicates over one page's read-only snapshot. Each predicate
maps to a defect class 110's re-review caught by eye (the task book's
predicate table), and each test below says which.

The calibration discipline is the point of the whole batch: **zero false
positives on the accepted pages outrank recall** (岳 will be flooded by a
noisy gate; a quiet one still has the human eye behind it). The live-page
pins — P22/P23/P24 zero ERROR/WARN, P1's pre-fix defects all caught — are
only meaningful together with that discipline, and the synthetic cases here
pin each predicate's hit/miss shape at the unit level so a threshold change
that quietly moves the calibration shows up as a red test, not as a surprise
on the next real page.

The real-page snapshots live in `outputs/111/` (gitignored): the tests skip
when they are absent, because the synthetic fixtures carry the predicate
logic and the real pages carry the calibration evidence (outputs/111/SUMMARY
records the numbers this batch measured).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from boardwise.engines import drawlint

REAL_DIR = Path(__file__).resolve().parents[1] / "outputs" / "111"
REAL_PAGES = ("P1", "P22", "P23", "P24")


def _sheet_box() -> dict:
    return {
        "primitiveId": "sheet1",
        "state": {
            "PrimitiveType": "Component",
            "ComponentType": "sheet",
            "PrimitiveId": "sheet1",
        },
    }


def _part(designator: str, x: float, y: float, primitive: str = "") -> dict:
    return {
        "primitiveId": primitive or f"part-{designator}",
        "state": {
            "PrimitiveType": "Component",
            "ComponentType": "part",
            "PrimitiveId": primitive or f"part-{designator}",
            "Designator": designator,
            "X": x,
            "Y": y,
            "Rotation": 0,
            "Mirror": False,
        },
    }


def _flag(net: str, x: float, y: float, rotation: float = 0) -> dict:
    return {
        "primitiveId": f"flag-{net}-{x}-{y}",
        "state": {
            "PrimitiveType": "Component",
            "ComponentType": "netflag",
            "PrimitiveId": f"flag-{net}-{x}-{y}",
            "X": x,
            "Y": y,
            "Rotation": rotation,
            "Net": net,
        },
    }


def _wire(primitive: str, net: str, *points: float) -> dict:
    return {
        "primitiveId": primitive,
        "state": {
            "PrimitiveType": "Wire",
            "PrimitiveId": primitive,
            "Net": net,
            "Line": list(points),
        },
    }


def _snapshot(*components: dict, wires: list[dict] | None = None) -> dict:
    return {
        "components": [_sheet_box(), *components],
        "wires": wires or [],
        "pins": [],
        "netlabels": [],
        "bboxes": {"sheet1": {"minX": 0, "minY": 0, "maxX": 1170, "maxY": 825}},
        "meta": {"sheets": ["sheet1"]},
    }


def _text_node(x: float, y_svg: float, text: str, *, fill: str, part_attr: bool = False,
               anchor: str = "start") -> str:
    partid = ' c_partid="part_attr"' if part_attr else ""
    return (
        f'<text style="font-family:\'Arial\';font-size:7.148342059336824px;'
        f'font-style:normal;font-weight:normal;fill:{fill};stroke:none;"'
        f'{partid} x="{x}" y="{y_svg}" text-anchor="{anchor}" '
        f'transform="rotate(0, {x}, {y_svg})" '
        f'dominant-baseline="ideographic"><tspan xml:space="preserve" '
        f'x="{x}" dx="0" dy="0">{text}</tspan></text>'
    )


def _svg(*nodes: str) -> str:
    return "<svg>" + "".join(nodes) + "</svg>"


BLUE = drawlint.FILL_VALUE
NAVY = drawlint.FILL_DESIGNATOR


def _lint(snapshot: dict, svg: str | None = None, **kwargs):
    return drawlint.run_lint(snapshot, svg, **kwargs)


def _by_predicate(findings) -> dict:
    out: dict[str, list] = {}
    for finding in findings:
        out.setdefault(finding.predicate, []).append(finding)
    return out


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def real_pages():
    """The four captured live snapshots + renders, skipped when absent."""
    needed = [REAL_DIR / f"geo_{page}_live.json" for page in REAL_PAGES]
    renders = {
        "P22": REAL_DIR / "render_P22.svg",
        "P23": REAL_DIR / "render_P23.svg",
        "P24": REAL_DIR / "render_P24.svg",
        "P1": REAL_DIR / "render_P1.svg",
    }
    if not all(path.exists() for path in needed) or not all(
        path.exists() for path in renders.values()
    ):
        pytest.skip(
            "outputs/111/ live captures are not on this machine — the synthetic "
            "cases above carry the predicate logic; the calibration evidence "
            "lives in outputs/111/SUMMARY"
        )
    return {
        page: {
            "snapshot": json.loads(
                (REAL_DIR / f"geo_{page}_live.json").read_text(encoding="utf-8")
            ),
            "render": (REAL_DIR / f"render_{page}.svg").read_text(encoding="utf-8"),
        }
        for page in REAL_PAGES
    }


# ------------------------------------------------------------------ L1

def test_l1_fires_when_a_wire_runs_through_a_label():
    """110: the ST horizontal printed through the "VCC" label.

    The label has a carrier of its own (a VCC stub ending at the flag); the
    ST wire crosses the label's glyphs mid-row, deep past the graze floor.
    """
    snapshot = _snapshot(
        wires=[
            _wire("wVCC", "VCC", 430, 560, 445, 560),
            _wire("wST", "ST", 460, 540, 460, 590),
        ],
    )
    svg = _svg(_text_node(445, -550, "VCC", fill=BLUE))
    hits = _by_predicate(_lint(snapshot, svg))["L1-text-on-wire"]
    assert len(hits) == 1
    assert hits[0].severity == "ERROR"
    assert "VCC" in hits[0].message
    assert "ST" in hits[0].message


def test_l1_spares_a_label_sitting_on_its_own_net():
    """The host draws a net's name ON its conductor — that is the name's job."""
    snapshot = _snapshot(
        wires=[
            _wire("w1", "ST", 400, 570, 500, 570),
            _wire("w2", "OTHER", 400, 700, 500, 700),
        ],
    )
    svg = _svg(_text_node(400, -570, "ST", fill=BLUE))
    assert _by_predicate(_lint(snapshot, svg)).get("L1-text-on-wire") is None


def test_l1_spares_a_border_graze_at_estimate_precision():
    """P24's parallel stub labels graze a neighbour wire by < 6 units — the
    estimate cannot resolve a 2-unit glyph overlap, so the ruler ignores it."""
    snapshot = _snapshot(
        wires=[
            _wire("w1", "RXD", 280, 725, 290, 725),
            _wire("w2", "TXD", 280, 730, 290, 730),
        ],
    )
    svg = _svg(_text_node(285, -725, "RXD", fill=BLUE))
    assert _by_predicate(_lint(snapshot, svg)).get("L1-text-on-wire") is None


# ------------------------------------------------------------------ L2

def test_l2_fires_when_two_labels_stack():
    """110: HVDC/VDC stacked over COMP — one text row over the other's glyphs."""
    snapshot = _snapshot()
    svg = _svg(
        _text_node(455, -570, "HVDC", fill=BLUE),
        _text_node(455, -573, "VDC", fill=BLUE),
    )
    hits = _by_predicate(_lint(snapshot, svg))["L2-text-on-text"]
    assert len(hits) == 1
    assert hits[0].severity == "ERROR"


def test_l2_spares_a_designator_and_its_own_value_row():
    """One symbol's identity rows are column-stacked by construction (099c)."""
    snapshot = _snapshot()
    svg = _svg(
        _text_node(455, -720, "C20", fill=NAVY, part_attr=True),
        _text_node(455, -710, "100nF", fill=BLUE, part_attr=True),
    )
    assert _by_predicate(_lint(snapshot, svg)).get("L2-text-on-text") is None


def test_l2_spares_two_texts_a_row_apart():
    """The gap floor: side-by-side text a full row apart is readable."""
    snapshot = _snapshot()
    svg = _svg(
        _text_node(100, -500, "5V0", fill=BLUE),
        _text_node(300, -520, "GND", fill=BLUE),
    )
    assert _by_predicate(_lint(snapshot, svg)).get("L2-text-on-text") is None


# ------------------------------------------------------------------ L3

def test_l3_fires_when_text_spans_two_bodies():
    """110: CS_FILT 竖排贴器件 — text over more than one symbol."""
    snapshot = _snapshot(
        _part("U1", 100, 100),
        _part("U2", 160, 100),
    )
    for part in snapshot["components"]:
        if part["state"].get("ComponentType") == "part":
            pass
    sheet = drawlint.Sheet(snapshot)
    sheet.parts[0].local_body = (-20, -10, 20, 10)
    sheet.parts[1].local_body = (-20, -10, 20, 10)
    box = drawlint.TextBox("TXT", (120, 95, 150, 105), kind="annotation",
                           anchor=(120, 100))
    sheet.texts = [box]
    hits = drawlint.check_text_on_part(sheet)
    assert len(hits) == 2  # foreign to both bodies
    assert all(h.severity == "ERROR" for h in hits)
    assert {h.objects[1] for h in hits} == {"U1", "U2"}


def test_l3_spares_a_row_inside_exactly_one_body():
    """A symbol's own row inside its own body is 099c's own text."""
    snapshot = _snapshot(_part("U1", 100, 100))
    sheet = drawlint.Sheet(snapshot)
    sheet.parts[0].local_body = (-30, -20, 30, 20)
    sheet.texts = [
        drawlint.TextBox("U1", (85, 112, 105, 122), kind="designator",
                         anchor=(85, 110)),
        drawlint.TextBox("UC3845B", (85, 92, 135, 102), kind="value",
                         anchor=(85, 90)),
    ]
    assert drawlint.check_text_on_part(sheet) == []


# ------------------------------------------------------------------ L4

def test_l4_fires_when_a_wire_crosses_a_body_mid_span():
    """110: a segment crossing a pin (or body) half-way along its run."""
    snapshot = _snapshot(_part("U1", 300, 300))
    wires = [_wire("w1", "SIG", 250, 300, 350, 300)]
    snap = _snapshot(*snapshot["components"], wires=wires)
    sheet = drawlint.Sheet(snap)
    sheet.parts[0].local_body = (-20, -10, 20, 10)
    hits = drawlint.check_wire_through_part(sheet)
    assert len(hits) == 1
    assert hits[0].severity == "ERROR"


def test_l4_spares_a_wire_landing_on_its_own_pin():
    """Pit 24's rule: the pin is the connection point, not a crossing."""
    snapshot = _snapshot(_part("U1", 300, 300))
    wires = [_wire("w1", "SIG", 320, 300, 360, 300)]
    snap = _snapshot(*snapshot["components"], wires=wires)
    sheet = drawlint.Sheet(snap)
    sheet.parts[0].local_body = (-20, -10, 20, 10)
    pins = {"U1": {"1": (320, 300)}}
    assert drawlint.check_wire_through_part(sheet, pins) == []


# ------------------------------------------------------------------ L5

def test_l5_fires_on_two_same_net_labels_on_different_wires():
    """110: the feedback region naming one net repeatedly."""
    snapshot = _snapshot(
        wires=[
            _wire("w1", "FB", 200, 100, 260, 100),
            _wire("w2", "FB", 280, 100, 330, 100),
        ],
    )
    svg = _svg(
        _text_node(255, -100, "FB", fill=BLUE),
        _text_node(285, -100, "FB", fill=BLUE),
    )
    hits = _by_predicate(_lint(snapshot, svg))["L5-duplicate-annotation"]
    assert len(hits) == 1
    assert hits[0].severity == "ERROR"


def test_l5_spares_a_flag_and_its_own_name():
    """P22's four GND flags each with its name — one statement each."""
    snapshot = _snapshot(_flag("GND", 50, 695))
    svg = _svg(_text_node(50, -720, "GND", fill=BLUE))
    assert _by_predicate(_lint(snapshot, svg)).get("L5-duplicate-annotation") is None


def test_l5_spares_two_flags_of_one_net():
    """Rail distribution: many flags of one net are the point."""
    snapshot = _snapshot(_flag("GND", 50, 695), _flag("GND", 200, 695))
    svg = _svg(_text_node(50, -720, "GND", fill=BLUE))
    assert _by_predicate(_lint(snapshot, svg)).get("L5-duplicate-annotation") is None


# ------------------------------------------------------------------ L6

def test_l6_counts_a_crossing_as_info():
    """110: CS_FILT × HVDC 十字 — real, and never a refusal."""
    snapshot = _snapshot(
        wires=[
            _wire("w1", "CS_FILT", 100, 100, 200, 200),
            _wire("w2", "HVDC", 100, 200, 200, 100),
        ],
    )
    hits = _by_predicate(_lint(snapshot))["L6-wire-crossing"]
    assert len(hits) == 1
    assert hits[0].severity == "INFO"


def test_l6_spares_a_t_junction():
    """An endpoint on another wire's span is a splice, not a crossing."""
    snapshot = _snapshot(
        wires=[
            _wire("w1", "A", 100, 100, 200, 100),
            _wire("w2", "B", 150, 100, 150, 200),
        ],
    )
    assert _by_predicate(_lint(snapshot)).get("L6-wire-crossing") is None


# ------------------------------------------------------------------ L7

def test_l7_warns_when_a_label_hugs_a_foreign_wire():
    """110: the U3-region label crowding."""
    snapshot = _snapshot(
        wires=[
            _wire("w1", "FB", 200, 100, 260, 100),
            _wire("w2", "OTHER", 200, 101, 260, 101),
        ],
    )
    svg = _svg(_text_node(200, -100, "FB", fill=BLUE))
    hits = _by_predicate(_lint(snapshot, svg))["L7-label-wire-clearance"]
    assert hits
    assert hits[0].severity == "WARN"


def test_l7_spares_a_label_a_row_from_a_foreign_wire():
    """P22/P23/P24 keep every label a full text row from foreign conductors."""
    snapshot = _snapshot(
        wires=[
            _wire("w1", "FB", 200, 100, 260, 100),
            _wire("w2", "OTHER", 200, 120, 260, 120),
        ],
    )
    svg = _svg(_text_node(200, -100, "FB", fill=BLUE))
    assert _by_predicate(_lint(snapshot, svg)).get("L7-label-wire-clearance") is None


# ------------------------------------------------------------------ L8

def test_l8_fires_on_a_tilted_flag():
    """岳's flag rule: the bar reads from the vertical set only."""
    snapshot = _snapshot(_flag("+5V", 100, 100, rotation=45))
    hits = _by_predicate(_lint(snapshot))["L8-flag-orientation"]
    assert len(hits) == 1
    assert hits[0].severity == "ERROR"


def test_l8_spares_the_vertical_set():
    snapshot = _snapshot(
        _flag("GND", 50, 695, rotation=0),
        _flag("GND", 110, 525, rotation=180),
        _flag("GND", 80, 745, rotation=270),
    )
    assert _by_predicate(_lint(snapshot)).get("L8-flag-orientation") is None


# ------------------------------------------------------------------ L9

def test_l9_reports_an_under_filled_sheet_as_info():
    """110's pre-fix page: the layout distribution note (never a refusal)."""
    snapshot = _snapshot(
        _part("R1", 20, 20),
        wires=[_wire("w1", "A", 30, 30, 40, 40)],
    )
    hits = _by_predicate(_lint(snapshot))["L9-board-fill"]
    assert len(hits) == 1
    assert hits[0].severity == "INFO"


def test_l9_stays_quiet_on_a_spread_page():
    snapshot = _snapshot(
        _part("R1", 100, 100),
        _part("U1", 900, 600),
        wires=[_wire("w1", "A", 100, 100, 900, 600)],
    )
    assert _by_predicate(_lint(snapshot)).get("L9-board-fill") is None


# ------------------------------------------------------- real-page pins

def test_accepted_pages_have_zero_error_and_warn(real_pages):
    """The hard pin: P22/P23/P24 (accepted 2026-10-04) — zero ERROR/WARN.

    INFO findings are reported and do not count (the task book's #55 split).
    111a's L5b is the documented exception, enumerated in
    test_111a_draw_lint_addendum.py: P22's TAP double-end-label (and its 3V3
    pair) plus P23's TAP and P24's XI hit the host DRC on the accepted pages
    too — true positives by the oracle's own editor DRC run, excluded here by
    predicate name, not by relaxing the pin.
    """
    for page in ("P22", "P23", "P24"):
        data = real_pages[page]
        findings = drawlint.run_lint(data["snapshot"], data["render"])
        bad = [
            f for f in findings
            if f.severity in ("ERROR", "WARN")
            and f.predicate != "L5-wire-multiname"
        ]
        assert bad == [], (
            f"{page}: zero-false-positive pin broken: "
            + "; ".join(f"{f.predicate}: {f.message}" for f in bad)
        )


def test_p1_pre_fix_defects_are_caught(real_pages):
    """The other hard pin: 110 P1's pre-fix layout — the gate must fire.

    The 110 re-review's eye-caught classes all map to predicates here: text
    printed through a conductor (L1), stacked text (L2), the CS_FILT × HVDC
    crossing (L6). The page's own snapshot carries the defects the fix
    cleaned up, so a quiet run means the predicates regressed.
    """
    data = real_pages["P1"]
    findings = drawlint.run_lint(data["snapshot"], data["render"])
    by_predicate = _by_predicate(findings)
    assert by_predicate.get("L1-text-on-wire"), "L1 lost the text-through-wire class"
    assert by_predicate.get("L2-text-on-text"), "L2 lost the stacked-text class"
    assert by_predicate.get("L6-wire-crossing"), "L6 lost the crossing count"
    errors = [f for f in findings if f.severity == "ERROR"]
    assert errors, "the gate must exit 1 on the pre-fix page"


# ------------------------------------------------------------ CLI shape

def test_cli_draw_lint_replay_exit_codes(tmp_path, capsys):
    """Exit 0 no ERROR / 1 ERROR findings / 2 bad input, on the replay path."""
    from boardwise import cli as cli_module

    snapshot = _snapshot(
        wires=[
            _wire("wVCC", "VCC", 430, 560, 445, 560),
            _wire("wST", "ST", 460, 540, 460, 590),
        ],
    )
    svg = _svg(_text_node(445, -550, "VCC", fill=BLUE))
    snap_path = tmp_path / "snap.json"
    render_path = tmp_path / "render.svg"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    render_path.write_text(svg, encoding="utf-8")

    parser = cli_module.build_parser()
    clean_snapshot = _snapshot()
    clean_snap = tmp_path / "clean.json"
    clean_snap.write_text(json.dumps(clean_snapshot), encoding="utf-8")
    clean_render = tmp_path / "clean.svg"
    clean_render.write_text(_svg(), encoding="utf-8")

    args = parser.parse_args([
        "draw", "lint", "--snapshot", str(clean_snap),
        "--render", str(clean_render),
    ])
    assert cli_module._cmd_draw_lint(args) == 0

    args = parser.parse_args([
        "draw", "lint", "--snapshot", str(snap_path),
        "--render", str(render_path),
        "--json", str(tmp_path / "report.json"),
    ])
    assert cli_module._cmd_draw_lint(args) == 1
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["exitCode"] == 1
    assert report["counts"]["ERROR"] >= 1
    assert report["source"] == "replay"

    args = parser.parse_args([
        "draw", "lint", "--snapshot", str(tmp_path / "missing.json"),
    ])
    assert cli_module._cmd_draw_lint(args) == 2


def test_cli_draw_lint_refuses_snapshot_with_page(tmp_path):
    """A captured pair and a live page are two sources — the CLI refuses."""
    from boardwise import cli as cli_module

    snap = tmp_path / "snap.json"
    snap.write_text("{}", encoding="utf-8")
    parser = cli_module.build_parser()
    args = parser.parse_args([
        "draw", "lint", "--snapshot", str(snap), "--page", "whatever",
    ])
    assert cli_module._cmd_draw_lint(args) == 2


def test_cli_draw_lint_without_render_notes_unreadable_text(tmp_path, capsys):
    """A replay without the render sidecar answers 'unreadable' — a note,
    not a crash: only wire/flag geometry is judged."""
    from boardwise import cli as cli_module

    snapshot = _snapshot(_flag("+5V", 100, 100, rotation=45))
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(snapshot), encoding="utf-8")
    parser = cli_module.build_parser()
    args = parser.parse_args(["draw", "lint", "--snapshot", str(snap)])
    assert cli_module._cmd_draw_lint(args) == 1
    out = capsys.readouterr().out
    assert "L8-flag-orientation" in out


# ------------------------------------------------------- live CLI path

class _FakeBridgeClient:
    """The live-path seam: `BridgeClient.open` answers a scripted daemon.

    The 111 live regression this guards against: the replay path was tested,
    the live path (`asyncio.run(run())` inside `_cmd_draw_lint`) was not, and
    a missing name inside it only exploded the first time a real `--page` run
    touched it (caught by the oracle running the command, 2026-10-04). The
    fake here drives the same live block the real daemon drives — doc.list,
    doc.open, sch.geometry, export.render, client.close — without a socket.
    """

    def __init__(self, answers: dict[str, object], calls: list[str]):
        self._answers = answers
        self._calls = calls

    @classmethod
    def with_answers(cls, answers: dict[str, object]):
        calls: list[str] = []
        return cls(answers, calls), calls

    async def call(self, action, params=None, **kwargs):
        self._calls.append(action)
        answer = self._answers.get(action)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close(self):
        pass


def _install_live_daemon(monkeypatch, answers: dict[str, object]):
    """Point `_cmd_draw_lint`'s live ladder at a scripted fake daemon."""
    from boardwise.bridge.protocol import BridgeError

    client, calls = _FakeBridgeClient.with_answers(answers)
    client_obj = client

    class Client:
        @classmethod
        async def open(cls, uri, token, role, client=""):
            assert role == "cli"
            return client_obj

    monkeypatch.setattr(
        "boardwise.cli._open_cli",
        lambda args: (Client, BridgeError, 61190, "token"),
    )
    # The fake never dials: pin the uri builder so no real endpoint leaks in.
    monkeypatch.setattr(
        "boardwise.cli._bridge_uri", lambda port: "ws://127.0.0.1:61190/eda"
    )
    return calls


def test_cli_draw_lint_live_page_happy_path(monkeypatch, tmp_path, capsys):
    """`draw lint --page P24` against a fake daemon: doc.open is called, the
    geometry and render are read, findings come out, exit code is the counts.

    This is the test that was missing: it executes `_cmd_draw_lint`'s
    `asyncio.run` live block end-to-end, so a NameError-class break in that
    path can never again hide behind the replay tests.
    """
    from boardwise import cli as cli_module

    geometry = _snapshot(
        _flag("+5V", 100, 100, rotation=45),
        wires=[
            _wire("wVCC", "VCC", 430, 560, 445, 560),
            _wire("wST", "ST", 460, 540, 460, 590),
        ],
    )
    svg = _svg(
        _text_node(445, -550, "VCC", fill=BLUE),
    )
    render_payload = {
        "format": "image/svg+xml",
        "data": base64.b64encode(svg.encode("utf-8")).decode("ascii"),
    }
    listing = {
        "documents": [
            {"uuid": "page-p24", "name": "P24", "type": "page"},
        ],
    }
    answers = {
        "doc.list": listing,
        "doc.open": {"tabId": "page-p24", "matchesRequest": True},
        "sch.geometry": geometry,
        "export.render": render_payload,
    }
    calls = _install_live_daemon(monkeypatch, answers)

    parser = cli_module.build_parser()
    args = parser.parse_args([
        "draw", "lint", "--page", "P24",
        "--json", str(tmp_path / "report.json"),
    ])
    assert cli_module._cmd_draw_lint(args) == 1

    assert calls == ["doc.list", "doc.open", "sch.geometry", "export.render"]
    out = capsys.readouterr().out
    assert "P24" in out
    assert "L1-text-on-wire" in out
    assert "L8-flag-orientation" in out
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["source"] == "live"
    assert report["page"] == "P24"
    assert report["counts"]["ERROR"] >= 2
    assert report["exitCode"] == 1


def test_cli_draw_lint_live_focuses_the_requested_page(monkeypatch):
    """`--page` focuses before reading (pit 44: sch.geometry reads the focused
    page) — doc.open must precede sch.geometry, never be skipped."""
    from boardwise import cli as cli_module

    listing = {
        "documents": [
            {"uuid": "page-p1", "name": "P1", "type": "page"},
            {"uuid": "page-p24", "name": "P24", "type": "page"},
        ],
    }
    answers = {
        "doc.list": listing,
        "doc.open": {"tabId": "page-p24", "matchesRequest": True},
        "sch.geometry": _snapshot(),
        "export.render": None,
    }
    calls = _install_live_daemon(monkeypatch, answers)

    parser = cli_module.build_parser()
    args = parser.parse_args(["draw", "lint", "--page", "P24"])
    assert cli_module._cmd_draw_lint(args) == 0
    assert calls[:2] == ["doc.list", "doc.open"]
    assert "sch.geometry" in calls


def test_cli_draw_lint_live_unknown_page_returns_3(monkeypatch, capsys):
    """A page the focused project does not list is R3's 'stop and say so':
    exit 3, no geometry read, no doc.open — not a guess."""
    from boardwise import cli as cli_module

    listing = {
        "documents": [
            {"uuid": "page-p1", "name": "P1", "type": "page"},
        ],
    }
    answers = {"doc.list": listing}
    calls = _install_live_daemon(monkeypatch, answers)

    parser = cli_module.build_parser()
    args = parser.parse_args(["draw", "lint", "--page", "P99"])
    assert cli_module._cmd_draw_lint(args) == 3
    assert calls == ["doc.list"]
    assert "doc.open" not in calls
    err = capsys.readouterr().err
    assert "不可陈述" in err


def test_cli_draw_lint_live_unreadable_geometry_returns_3(monkeypatch, capsys):
    """`sch.geometry` answering nothing readable is 'state cannot be stated'
    (exit 3) — never a silent clean page."""
    from boardwise import cli as cli_module

    answers = {
        "doc.list": {"documents": [{"uuid": "p1", "name": "P1", "type": "page"}]},
        "doc.open": {"matchesRequest": True},
        "sch.geometry": {"components": []},
        "export.render": None,
    }
    calls = _install_live_daemon(monkeypatch, answers)

    parser = cli_module.build_parser()
    args = parser.parse_args(["draw", "lint", "--page", "P1"])
    assert cli_module._cmd_draw_lint(args) == 3
    assert calls == ["doc.list", "doc.open", "sch.geometry"]


def test_cli_draw_lint_live_defaults_to_focused_page(monkeypatch, tmp_path):
    """No `--page`: no doc.open, one geometry read of whatever is focused."""
    from boardwise import cli as cli_module

    geometry = _snapshot()
    answers = {
        "sch.geometry": geometry,
        "export.render": {
            "format": "image/svg+xml",
            "data": base64.b64encode(_svg().encode("utf-8")).decode("ascii"),
        },
    }
    calls = _install_live_daemon(monkeypatch, answers)

    parser = cli_module.build_parser()
    args = parser.parse_args(["draw", "lint"])
    assert cli_module._cmd_draw_lint(args) == 0
    assert "doc.open" not in calls
    assert calls == ["sch.geometry", "export.render"]

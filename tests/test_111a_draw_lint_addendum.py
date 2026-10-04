"""Task 111a: the draw-lint addendum — L10 out-of-bounds, L5b same-name
wire segments, L6 clustered crossings with the conditional WARN.

Three predicates over the same snapshots and the same calibration discipline
as 111 (outputs/111/SUMMARY.md): zero false positives on the accepted pages
P22/P23/P24 outrank recall, and every threshold in the engine's comments
names the page distribution that measured it (2026-10-04).

Real-page snapshots live in `outputs/111/` (gitignored): the tests skip when
they are absent — the synthetic fixtures carry the predicate logic, the real
pages carry the calibration evidence. P22's TAP double-end-label WARNs are
enumerated expectations here (§规则二 of tasks/111a): they are true positives
the host DRC reports on the accepted page too, not false ones.
"""

from __future__ import annotations

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


# ------------------------------------------------------------------ L10

def test_l10_fires_when_a_flag_anchor_leaves_the_sheet():
    """岳's evidence: the +12V flag at (1160,325) names past the 1170 edge.

    The anchor itself sits inside; its name's estimated box runs off the
    right edge (P1: the SEC_12V name box reaches 1173.9) — so the name text
    box is the object that must be caught, and the anchor point with it.
    """
    snapshot = _snapshot(_flag("+12V", 1160, 325))
    svg = _svg(_text_node(1160, -325, "+12V", fill=BLUE))
    hits = _by_predicate(_lint(snapshot, svg))["L10-out-of-bounds"]
    assert len(hits) == 1
    assert hits[0].severity == "ERROR"
    assert hits[0].estimate is True
    assert "beyond" in hits[0].message


def test_l10_spares_an_object_touching_the_edge():
    """The eps: a box that only reaches the edge is inside, not out (R19's
    top rides the frame without crossing — 岳 measured it legal)."""
    snapshot = _snapshot(
        _part("R19", 1100, 40),
        wires=[_wire("w1", "A", 1115, 20, 1170, 20)],
    )
    svg = _svg(
        _text_node(1130, -30, "R19", fill=NAVY, part_attr=True),
    )
    sheet = drawlint.Sheet(snapshot, render_svg=svg)
    sheet.parts[0].local_body = (-30, -20, 30, 20)
    assert drawlint.check_out_of_bounds(sheet) == []


def test_l10_skips_silently_without_a_sheet_box():
    """No sheet frame in the snapshot → the predicate says nothing (L9's
    honest-degradation shape)."""
    snapshot = _snapshot(_flag("+12V", 5000, 5000))
    snapshot["bboxes"] = {}
    assert _by_predicate(_lint(snapshot)).get("L10-out-of-bounds") is None


def test_l10_spares_the_accepted_pages(real_pages):
    """P22/P23/P24's closest object sits 35 units inside — the 0.5 eps is
    far below the accepted pages' measured minimum margin."""
    for page in ("P22", "P23", "P24"):
        data = real_pages[page]
        findings = drawlint.run_lint(data["snapshot"], data["render"])
        assert not _by_predicate(findings).get("L10-out-of-bounds"), (
            f"{page}: L10 must stay silent on an accepted page"
        )


def test_l10_catches_the_p1_pre_fix_out_of_bounds_texts(real_pages):
    """P1 pre-fix: the +12V family's name boxes run past x=1170 — the defect
    岳 caught by eye must be an ERROR here. The flag the addendum calls
    「+12V 旗」 names its net SEC_12V on the page (its value row even prints
    '+12V'); its name box reaches 1173.9, 3.9 past the edge. The other hits
    are the same corner's texts (220uF/25V-SMT value, SEC_SW name, ...)."""
    data = real_pages["P1"]
    findings = drawlint.run_lint(data["snapshot"], data["render"])
    hits = _by_predicate(findings)["L10-out-of-bounds"]
    assert hits, "L10 lost the +12V out-of-bounds class on P1"
    assert all(h.severity == "ERROR" for h in hits)
    texts = {h.objects[0] for h in hits}
    assert "SEC_12V" in texts, f"SEC_12V (the +12V flag's name) must hit: {texts}"
    assert "220uF/25V-SMT" in texts
    assert len(hits) >= 5


# ------------------------------------------------------------------ L5b

def test_l5b_warns_when_one_wire_carries_two_same_net_labels():
    """The host DRC shape: `wire $1N77 has multiple net names LED_A, LED_A`
    — the named-stub technique backs one wire primitive with two same-name
    annotations. WARN, not ERROR (the page reads; the host will complain)."""
    snapshot = _snapshot(
        wires=[_wire("wLED", "LED_A", 100, 100, 160, 100)],
    )
    svg = _svg(
        _text_node(110, -100, "LED_A", fill=BLUE),
        _text_node(140, -100, "LED_A", fill=BLUE),
    )
    hits = _by_predicate(_lint(snapshot, svg))["L5-wire-multiname"]
    assert len(hits) == 1
    assert hits[0].severity == "WARN"
    assert "多个网络名" in hits[0].message
    assert "LED_A" in hits[0].message


def test_l5b_spares_a_single_label_on_its_wire():
    """One name per wire is the whole point of a label."""
    snapshot = _snapshot(
        wires=[_wire("w1", "LED_A", 100, 100, 160, 100)],
    )
    svg = _svg(_text_node(120, -100, "LED_A", fill=BLUE))
    assert _by_predicate(_lint(snapshot, svg)).get("L5-wire-multiname") is None


def test_l5b_counts_flags_and_different_nets_neither():
    """Only annotations count (a flag + its name in one region is existing
    L5's business), and two labels of *different* nets on one carrier are
    not a multiname — they are a different (host-side) problem."""
    snapshot = _snapshot(
        _flag("GND", 50, 130),
        wires=[
            _wire("w1", "TAP", 100, 100, 160, 100),
            _wire("w2", "MIXED", 100, 200, 160, 200),
        ],
    )
    svg = _svg(
        _text_node(50, -130, "GND", fill=BLUE),
        _text_node(110, -100, "TAP", fill=BLUE),
        _text_node(110, -200, "MIXED", fill=BLUE),
    )
    assert _by_predicate(_lint(snapshot, svg)).get("L5-wire-multiname") is None


def test_l5b_enumerates_the_accepted_pages_tap_multinames(real_pages):
    """P22's TAP double-end-label (and P23's, P24's XI) hit the host DRC on
    the accepted pages too — true positives, enumerated, not silence:
    P22 wire d214df2a (TAP) ×2; P23 wire fbb0811b (TAP) ×2;
    P24 wire bd0ecf4e (XI) ×2. P22 also carries wire 0f9776dd (3V3) ×2.
    P1 pre-fix carries the $1N family (LED_A/SW×2/RTCT/CS_FILT/HVDC...)."""
    expectations = {
        "P22": [("d214df2a", "TAP", 2), ("0f9776dd", "3V3", 2)],
        "P23": [("fbb0811b", "TAP", 2)],
        "P24": [("bd0ecf4e", "XI", 2)],
    }
    for page, expected in expectations.items():
        data = real_pages[page]
        findings = drawlint.run_lint(data["snapshot"], data["render"])
        hits = _by_predicate(findings)["L5-wire-multiname"]
        got = sorted(
            (h.objects[0][:8], h.objects[1], h.objects[2]) for h in hits
        )
        assert got == sorted(expected), f"{page}: L5b hits {got} != {expected}"


def test_l5b_p1_prefix_names_the_host_drc_wires(real_pages):
    """P1 pre-fix: the wires the host DRC named by net all show up —
    LED_A, RTCT, CS_FILT, SW (two primitives), HVDC, SRC..."""
    data = real_pages["P1"]
    findings = drawlint.run_lint(data["snapshot"], data["render"])
    hits = _by_predicate(findings)["L5-wire-multiname"]
    nets = {h.objects[1] for h in hits}
    for net in ("LED_A", "RTCT", "CS_FILT", "SW", "HVDC", "SRC", "ST"):
        assert net in nets, f"P1 pre-fix: L5b lost the {net} multiname wire"
    # counts are per (carrier, net): HVDC's 18 labels ride one primitive,
    # CS_FILT's five ride theirs (the probe's dfbfbbe6/fcc78f98 columns)
    counts = {(h.objects[0][:8], h.objects[1]): h.objects[2] for h in hits}
    assert ("dfbfbbe6", "HVDC") in counts
    hvdc_total = sum(n for (p, net), n in counts.items() if net == "HVDC")
    assert hvdc_total == 18 + 2  # 18 on dfbfbbe6 + 2 on the ST carrier ceab0771
    csfilt_total = sum(n for (p, net), n in counts.items() if net == "CS_FILT")
    assert csfilt_total == 5
    assert ("e32bcb6d", "LED_A") in counts
    assert all(h.severity == "WARN" for h in hits)


# ------------------------------------------------------------------ L6

def test_l6_clusters_one_primitive_pairs_crossings():
    """The pre-fix P1 shape: SW × HVDC crossed 8 reported times at the same
    corner because both wires run many segments — one unordered pair with
    close crossing points is one cluster, reported once."""
    snapshot = _snapshot(
        wires=[
            _wire("wA", "SW", 0, 0, 60, 0, 60, 40, 120, 40),
            _wire("wB", "HVDC", 30, 40, 30, -20, 90, -20, 90, 40),
        ],
    )
    hits = _by_predicate(_lint(snapshot))["L6-wire-crossing"]
    assert hits, "the synthetic pair must still cross"
    assert all(h.severity == "INFO" for h in hits)


def test_l6_warns_when_one_pair_crosses_repeatedly():
    """L6_CLUSTER_WARN: the same two primitives crossing ≥3 times — one
    wiggle of either wire would end it (岳's '不必要交叉')."""
    snapshot = _snapshot(
        wires=[
            _wire("wA", "A", 0, 0, 30, 0, 30, 30, 60, 30, 60, 60, 90, 60),
            _wire("wB", "B", 15, 60, 15, -10, 45, 60, 45, -10, 75, 60, 75, -10),
        ],
    )
    hits = _by_predicate(_lint(snapshot))["L6-wire-crossing"]
    warns = [h for h in hits if h.severity == "WARN"]
    assert len(warns) == 1
    assert "3" in warns[0].message  # the crossing count is in the message
    # every other row stays INFO (a ≤2-crossing cluster is the legal shape)
    assert all(
        h.severity == "INFO" and "2 time(s)" in h.message
        for h in hits
        if h.severity != "WARN"
    )


def test_l6_warns_when_the_page_crosses_everywhere():
    """L6_PAGE_WARN: many distinct pairs each crossing once — the page's
    routing asks for an eye. The threshold is calibrated above the accepted
    pages' cluster counts (P22 1, P23 1, P24 2)."""
    wires = []
    for k in range(9):  # 9 horizontal runs × 9 vertical runs = 9 clusters
        wires.append(_wire(f"h{k}", f"N{k}", 0, 10 + 20 * k, 200, 10 + 20 * k))
        wires.append(_wire(f"v{k}", f"M{k}", 10 + 20 * k, 0, 10 + 20 * k, 200))
    snapshot = _snapshot(wires=wires)
    hits = _by_predicate(_lint(snapshot))["L6-wire-crossing"]
    warns = [h for h in hits if h.severity == "WARN"]
    assert len(warns) == 1
    assert "page" in warns[0].message


def test_l6_keeps_a_single_crossing_info():
    """110's CS_FILT × HVDC 十字 and every 1-2 crossing cluster stay INFO —
    the number only tells the eye where to look."""
    snapshot = _snapshot(
        wires=[
            _wire("w1", "CS_FILT", 100, 100, 200, 200),
            _wire("w2", "HVDC", 100, 200, 200, 100),
        ],
    )
    hits = _by_predicate(_lint(snapshot))["L6-wire-crossing"]
    assert len(hits) == 1
    assert hits[0].severity == "INFO"


def test_l6_accepted_pages_keep_only_info(real_pages):
    """The two-crossing cluster (P23's f69c826c×992caa15 double-cross, and
    P24's XO×孤立段 double-cross the task book names) must stay below
    L6_CLUSTER_WARN — the accepted pages keep zero L6 WARN. (Their L5b
    TAP/XI/3V3 multiname WARNs are the enumerated true positives of
    test_l5b_enumerates_*, not this test's subject.)"""
    for page in ("P22", "P23", "P24"):
        data = real_pages[page]
        findings = drawlint.run_lint(data["snapshot"], data["render"])
        bad = [
            f for f in findings
            if f.severity == "WARN" and f.predicate == "L6-wire-crossing"
        ]
        assert bad == [], f"{page}: L6 must not warn on an accepted page"


def test_l6_p1_prefix_cluster_count_drops_below_44(real_pages):
    """The 44 per-segment INFO rows collapse into per-pair clusters (P1
    pre-fix measured 31 clusters at gap 20), and the repeated pairs warn."""
    data = real_pages["P1"]
    findings = drawlint.run_lint(data["snapshot"], data["render"])
    hits = _by_predicate(findings)["L6-wire-crossing"]
    assert 0 < len(hits) < 44, f"P1 L6 rows {len(hits)} must collapse below 44"
    warns = [h for h in hits if h.severity == "WARN"]
    assert warns, "P1's repeated pairs (HVDC ×8+ / ×27) must warn"
    assert any(f.severity == "INFO" for f in findings) or warns


# ------------------------------------------------------------ L9 policy

def test_l9_stays_info_when_l6_would_warn(real_pages):
    """The WARN upgrade touches L6 only: L9's fill note keeps its INFO
    severity even on the worst page (the #55 split stays intact)."""
    data = real_pages["P1"]
    findings = drawlint.run_lint(data["snapshot"], data["render"])
    fills = [f for f in findings if f.predicate == "L9-board-fill"]
    assert all(f.severity == "INFO" for f in fills)

"""禁布区侵入 — ``pcb-keepout-violation`` (R2-1).

162b parsed every ``REGION`` record into :attr:`BoardGeometry.prohibit_regions`
and left it unread. This module is its first reader: for each **keepout** the
designer drew, the board's own elements of the kinds that keepout forbids are
tested against its area, on its layer.

**What a keepout forbids is the editor's reading, not ours.** The file writes
``prohibitType`` as a list of words — ``["COPPER"]`` on the one fixture board
that has keepouts — while both format specifications document only numeric
codes. Both vocabularies, and the meaning of each word, are taken from the
calibrated host's own code (立创 EDA Pro 3.2.186, ``pro-pcb`` / ``pro-mgr``
bundles, read offline from the official installer):

* the word set is ``COMPONENT / VIA / TRACK / FILL / COPPER / PLANE``, and the
  numeric codes map as ``1 → TRACK+FILL, 2 → COMPONENT, 3 → VIA,
  4 → COPPER+PLANE, 5 → TRACK, 6 → FILL, 7 → COPPER, 8 → PLANE``
  (:data:`PROHIBIT_CODES`) — so ``COPPER`` is code 7, 「禁止覆铜」;
* the DRC's own test (``checkProhibitXXX``) applies a keepout to an object when
  ``region.layer == object.layer`` **or the region is on layer 12** (multi), and
  then by kind: ``TRACK`` → tracks, ``FILL`` → fill areas, ``COMPONENT`` →
  components, ``COPPER`` → **poured copper** (the pour *result*), ``PLANE`` →
  plane zones. :data:`FORBIDS` is that table.

Two consequences shape the rule:

* A ``COPPER`` keepout is about the **pour result**, not the pour outline the
  designer drew (the outline crossing a keepout is how a keepout is *used*), and
  not about pads or tracks. The result's voids matter — the pour engine cuts a
  void around every copper keepout — so the result is read through
  :attr:`PourShape.rings` (outline + voids, arcs expanded), never through
  :attr:`PourShape.points` (outline only, arcs as chords). On 高速电机控制器 PCB2
  the bottom ``PGND`` pour carries a void of r 97.94 around each of its five
  keepout circles of r 93.84: the 4-mil pour clearance. Read without the voids,
  every keepout on that board would be "violated".
* The host DRC ignores ``VIA`` (its ``parseType`` has no ``VIA`` branch on
  3.2.186). This rule does check vias in a ``VIA`` keepout — the word is in the
  vocabulary and the spec calls it 禁止过孔 — and the row says the host would not
  have.

**The measurement.** Every area is eroded by :data:`KEEPOUT_TOLERANCE_MIL`
before it is tested (a circle loses that much radius; a convex polygon's edges
move in by it), so copper that merely *touches* a keepout's edge, or sits on it
within the arc-expansion error, is not an intrusion. An element intrudes when
its copper meets the eroded area:

* a track is a capsule (its centreline thickened by half its width);
* a via is a disc (``via_diameter``);
* a component is its **pads** (:func:`~boardwise.core.measure.pad_corners` —
  a round pad is its circumscribed rectangle, so this over-reaches by at most
  the corner of that rectangle); its body outline is not read;
* a fill / poured island is its outline **minus its voids**: it intrudes when
  one of its rings crosses into the area, or when the area lies inside the
  outline and in none of the voids.

**What this rule cannot see** (said on every row it writes):

* ``PLANE`` — inner electrical planes are not modelled; a ``PLANE`` keepout is
  listed as not judged.
* a poured island whose parent ``POUR`` is not in the file has no layer
  (``poured_orphans``); it cannot be placed on or off the keepout's layer and is
  counted, not judged.
* a non-convex polygonal keepout is not eroded (no robust inset here); it is
  tested as drawn, which makes an exactly-touching element count.
* a word outside the vocabulary: if the keepout's layer carries copper inside
  it, the row is an ``INFO`` that names the word and says it was not judged —
  never a guess at what the word forbids.

**Severity.** A judged intrusion is ``WARN``: a keepout is the designer's own
constraint, so an element inside it is a defect of the layout, not a style
note — but no ruling on PCB keepout severity exists in this repository, and
``ERROR`` would be the first PCB rule to block 投板 on its own. Left to the
main agent's ruling (R2 PR).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from ...core.geometry import MULTI_LAYER_ID, BoardGeometry, Point, ProhibitRegion
from ...core.measure import pad_corners, point_in_polygon, point_segment_distance, via_layers
from .base import PcbReviewContext, PcbRule

__all__ = [
    "FORBIDS",
    "KEEPOUT_TOLERANCE_MIL",
    "PROHIBIT_CODES",
    "PROHIBIT_WORDS",
    "KeepoutViolation",
    "prohibited_kinds",
]

#: How far an element must reach into a keepout before it counts, in mils.
#: Below the 4-mil pour clearance the fixtures show by a factor of 40, and above
#: the 0.05-mil chord error of an expanded arc.
KEEPOUT_TOLERANCE_MIL = 0.1

#: The words the host writes in ``prohibitType`` (3.2.186's enum).
PROHIBIT_WORDS = frozenset({"COMPONENT", "VIA", "TRACK", "FILL", "COPPER", "PLANE"})

#: The numeric codes of the format specifications, translated exactly as the
#: host translates them (1 and 4 are the deprecated combined codes).
PROHIBIT_CODES: dict[int, tuple[str, ...]] = {
    1: ("TRACK", "FILL"),
    2: ("COMPONENT",),
    3: ("VIA",),
    4: ("COPPER", "PLANE"),
    5: ("TRACK",),
    6: ("FILL",),
    7: ("COPPER",),
    8: ("PLANE",),
}

#: Word → what it forbids, in the row's words (the host DRC's class per word).
FORBIDS: dict[str, str] = {
    "TRACK": "走线",
    "FILL": "填充区域",
    "COPPER": "覆铜（铺铜结果）",
    "COMPONENT": "元件（以焊盘判）",
    "VIA": "过孔",
    "PLANE": "内电层",
}


def prohibited_kinds(tokens: list[str]) -> tuple[list[str], list[str]]:
    """``(words, unknown)`` — a region's ``prohibitType`` read through the host's table.

    A numeric code (int or a numeric string) expands through
    :data:`PROHIBIT_CODES`; a word is upper-cased and kept when it is in
    :data:`PROHIBIT_WORDS`. Anything else is returned in ``unknown`` verbatim.
    The words come back in a fixed order and without duplicates.
    """
    words: set[str] = set()
    unknown: list[str] = []
    for raw in tokens:
        token = str(raw).strip()
        if token.lstrip("-").isdigit() and int(token) in PROHIBIT_CODES:
            words.update(PROHIBIT_CODES[int(token)])
        elif token.upper() in PROHIBIT_WORDS:
            words.add(token.upper())
        else:
            unknown.append(token)
    order = ["COPPER", "FILL", "TRACK", "VIA", "COMPONENT", "PLANE"]
    return [word for word in order if word in words], unknown


# ---------------------------------------------------------------------------
# geometry: the eroded keepout area and the three element shapes
# ---------------------------------------------------------------------------


@dataclass
class _Area:
    """A keepout's area after erosion: a circle, or a polygon."""

    centre: Point | None = None
    radius: float = 0.0
    polygon: list[Point] = field(default_factory=list)
    eroded: bool = True

    @property
    def inner_point(self) -> Point:
        if self.centre is not None:
            return self.centre
        xs = [p.x for p in self.polygon]
        ys = [p.y for p in self.polygon]
        guess = Point(sum(xs) / len(xs), sum(ys) / len(ys))
        return guess


def _signed_area(polygon: list[Point]) -> float:
    total = 0.0
    for index, p in enumerate(polygon):
        q = polygon[(index + 1) % len(polygon)]
        total += p.x * q.y - q.x * p.y
    return total / 2.0


def _is_convex(polygon: list[Point]) -> bool:
    sign = 0
    count = len(polygon)
    for index in range(count):
        a, b, c = polygon[index], polygon[(index + 1) % count], polygon[(index + 2) % count]
        cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x)
        if abs(cross) <= 1e-12:
            continue
        if sign == 0:
            sign = 1 if cross > 0 else -1
        elif (cross > 0) != (sign > 0):
            return False
    return True


def _inset_convex(polygon: list[Point], by: float) -> list[Point] | None:
    """A convex polygon with every edge moved inward by ``by`` (``None`` if it vanishes)."""
    ccw = polygon if _signed_area(polygon) > 0 else list(reversed(polygon))
    count = len(ccw)
    lines = []
    for index in range(count):
        a, b = ccw[index], ccw[(index + 1) % count]
        dx, dy = b.x - a.x, b.y - a.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 1e-12:
            continue
        nx, ny = -dy / length, dx / length  # left normal = inward for a CCW ring
        lines.append((Point(a.x + nx * by, a.y + ny * by), dx, dy))
    out: list[Point] = []
    for index in range(len(lines)):
        (p1, d1x, d1y), (p2, d2x, d2y) = lines[index - 1], lines[index]
        denominator = d1x * d2y - d1y * d2x
        if abs(denominator) <= 1e-12:
            out.append(p2)
            continue
        t = ((p2.x - p1.x) * d2y - (p2.y - p1.y) * d2x) / denominator
        out.append(Point(p1.x + d1x * t, p1.y + d1y * t))
    if len(out) < 3 or _signed_area(out) <= 0:
        return None
    return out


def _region_area(region: ProhibitRegion) -> _Area | None:
    """The keepout's area eroded by the tolerance, or ``None`` when it has none."""
    if region.radius is not None and region.points:
        radius = region.radius - KEEPOUT_TOLERANCE_MIL
        return _Area(centre=region.points[0], radius=radius) if radius > 0 else None
    outline = region.rings[0] if region.rings else region.points
    if len(outline) < 3:
        return None
    if _is_convex(outline):
        inset = _inset_convex(outline, KEEPOUT_TOLERANCE_MIL)
        return _Area(polygon=inset) if inset else None
    return _Area(polygon=list(outline), eroded=False)


def _segments_meet(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    def orient(a: Point, b: Point, c: Point) -> float:
        return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)

    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return True
    return (
        (abs(d1) <= 1e-12 and point_segment_distance(p1, p3, p4) <= 1e-9)
        or (abs(d2) <= 1e-12 and point_segment_distance(p2, p3, p4) <= 1e-9)
        or (abs(d3) <= 1e-12 and point_segment_distance(p3, p1, p2) <= 1e-9)
        or (abs(d4) <= 1e-12 and point_segment_distance(p4, p1, p2) <= 1e-9)
    )


def _segment_gap(p1: Point, p2: Point, p3: Point, p4: Point) -> float:
    if _segments_meet(p1, p2, p3, p4):
        return 0.0
    return min(
        point_segment_distance(p1, p3, p4),
        point_segment_distance(p2, p3, p4),
        point_segment_distance(p3, p1, p2),
        point_segment_distance(p4, p1, p2),
    )


def _edges(ring: list[Point]):
    count = len(ring)
    return ((ring[index], ring[(index + 1) % count]) for index in range(count))


def _capsule_meets(a: Point, b: Point, half_width: float, area: _Area) -> bool:
    """Does the segment ``ab`` thickened by ``half_width`` reach into ``area``?"""
    if area.centre is not None:
        return point_segment_distance(area.centre, a, b) < area.radius + half_width
    if point_in_polygon(a, area.polygon) or point_in_polygon(b, area.polygon):
        return True
    return any(_segment_gap(a, b, c, d) < half_width or _segments_meet(a, b, c, d) for c, d in _edges(area.polygon))


def _rings_meet(rings: list[list[Point]], area: _Area) -> bool:
    """Does the region ``rings[0]`` minus ``rings[1:]`` reach into ``area``?

    If any ring edge enters the area, copper is on one side of that edge inside
    the area. If none does, the area is wholly inside or wholly outside each
    ring, and one interior point of the area decides: inside the outline and in
    no void means the area sits in copper.
    """
    for ring in rings:
        for a, b in _edges(ring):
            if _capsule_meets(a, b, 0.0, area):
                return True
    probe = area.inner_point
    if area.centre is None and not point_in_polygon(probe, area.polygon):
        probe = area.polygon[0]
    outline, voids = rings[0], rings[1:]
    return point_in_polygon(probe, outline) and not any(point_in_polygon(probe, void) for void in voids)


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------


def _on_layer(region: ProhibitRegion, layer_id: int | None) -> bool:
    """The host's layer test: same layer, or the keepout is on the multi layer."""
    return region.layer_id == MULTI_LAYER_ID or (layer_id is not None and layer_id == region.layer_id)


@dataclass
class _Intrusion:
    word: str
    label: str
    net: str | None
    component: str = ""


class KeepoutViolation(PcbRule):
    """Board elements inside a keepout of a kind that keepout forbids (R2-1)."""

    id = "pcb-keepout-violation"
    title = "禁布区侵入"
    level = "L1-pcb-geometry"
    source = (
        "设计者自己画的 REGION 禁布区（162b 解析）；类型词表、数字码映射与「哪类图元受哪种"
        "禁布约束、按什么层」取自立创 EDA Pro 3.2.186 自身代码（drcWorker checkProhibitXXX），"
        "非推测；容差 0.1 mil 为本规则自定（低于夹具上 4 mil 铺铜间距 40 倍）"
    )

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        findings: list[Finding] = []
        for region in getattr(board, "prohibit_regions", []) or []:
            if str(region.region_type or "PROHIBIT").upper() != "PROHIBIT":
                continue  # a CONSTRAINT area is a rule area, not a keepout
            area = _region_area(region)
            if area is None:
                continue
            words, unknown = prohibited_kinds(region.prohibit_types)
            intrusions, orphans = self._intrusions(board, region, area, words)
            finding = self._finding(ctx, region, area, words, unknown, intrusions, orphans)
            if finding is not None:
                findings.append(finding)
        return findings

    def _intrusions(
        self, board: BoardGeometry, region: ProhibitRegion, area: _Area, words: list[str]
    ) -> tuple[list[_Intrusion], int]:
        found: list[_Intrusion] = []
        orphans = 0
        if "TRACK" in words:
            for track in board.tracks:
                if _on_layer(region, track.layer_id) and _capsule_meets(
                    track.start, track.end, max(track.width, 0.0) / 2.0, area
                ):
                    found.append(_Intrusion("TRACK", f"track {track.id} (w {track.width:g})", track.net))
        for word, kind in (("FILL", "fill"), ("COPPER", "poured")):
            if word not in words:
                continue
            for pour in board.pours:
                if pour.kind != kind:
                    continue
                rings = pour.rings or ([pour.points] if len(pour.points) >= 3 else [])
                if not rings:
                    continue
                if pour.layer_id is None:
                    if _rings_meet(rings, area):
                        orphans += 1
                    continue
                if _on_layer(region, pour.layer_id) and _rings_meet(rings, area):
                    found.append(_Intrusion(word, f"{kind} {pour.id}", pour.net))
        if "VIA" in words:
            for via in board.vias:
                if (region.layer_id == MULTI_LAYER_ID or region.layer_id in via_layers(board, via)) and _capsule_meets(
                    via.center, via.center, max(via.via_diameter, 0.0) / 2.0, area
                ):
                    found.append(_Intrusion("VIA", f"via {via.id} (d {via.via_diameter:g})", via.net))
        if "COMPONENT" in words:
            pads_of: dict[str, list] = {}
            for pad in board.pads:
                pads_of.setdefault(pad.component_id or "", []).append(pad)
            for component in board.components:
                if not _on_layer(region, component.layer_id):
                    continue
                inside = [
                    pad for pad in pads_of.get(component.id, [])
                    if _rings_meet([pad_corners(pad)], area)
                ]
                if inside:
                    pins = ",".join(str(pad.pin_number) for pad in inside)
                    nets = sorted({pad.net for pad in inside if pad.net})
                    found.append(_Intrusion(
                        "COMPONENT",
                        f"component {component.designator or component.id} (pads {pins})",
                        nets[0] if len(nets) == 1 else None,
                        component=component.designator or "",
                    ))
        return found, orphans

    def _finding(self, ctx, region, area, words, unknown, intrusions, orphans) -> Finding | None:
        where = (
            f"circle r {region.radius:g} at ({region.points[0].x:g}, {region.points[0].y:g})"
            if area.centre is not None
            else f"polygon of {len(area.polygon)} vertices"
        )
        identity = (
            f"keepout {region.id} ({region.name or 'unnamed'}) on layer {region.layer_id}: "
            f"prohibitType {region.prohibit_types} → "
            + (", ".join(f"{w}={FORBIDS[w]}" for w in words) or "(nothing this rule reads)")
            + f"; {where}"
        )
        blind = []
        if "PLANE" in words:
            blind.append("PLANE (内电层) is not modelled here — not judged")
        if orphans:
            blind.append(
                f"{orphans} poured island(s) without a parent POUR (no layer) reach this area — "
                "not judged, their layer is unknown"
            )
        if not area.eroded:
            blind.append("non-convex keepout tested as drawn (no tolerance erosion): a touching element counts")
        if "COMPONENT" in words:
            blind.append("components judged by their pads (round pads as their circumscribed rectangle); body outline not read")
        if "VIA" in words:
            blind.append("the host DRC (3.2.186) does not check VIA keepouts — this rule does")
        if intrusions:
            nets = sorted({i.net for i in intrusions if i.net})
            listed = "; ".join(f"[{i.word}] {i.label}" + (f" net {i.net}" if i.net else "") for i in intrusions)
            message = (
                f"禁布区 {region.name or region.id}（层 {region.layer_id}）内有 {len(intrusions)} 处它禁止的图元："
                f"{listed}。本规则看不到：内电层、无父 POUR 的铺铜岛的层、元件本体外形。"
            )
            return Finding(
                rule_id=self.id,
                severity="WARN",
                level=self.level,
                message=message,
                evidence=[identity, *(f"intrudes: [{i.word}] {i.label}" + (f" @ {i.net}" if i.net else "") for i in intrusions), *blind],
                target=FindingTarget(
                    primitive_id=region.id,
                    component_ref=next((i.component for i in intrusions if i.component), ""),
                    net_refs=nets,
                ),
            )
        if unknown:
            copper = self._intrusions(board=ctx.board, region=region, area=area, words=sorted(PROHIBIT_WORDS - {"PLANE"}))[0]
            if not copper:
                return None
            listed = "; ".join(f"{i.label}" + (f" net {i.net}" if i.net else "") for i in copper)
            return Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message=(
                    f"禁布区 {region.name or region.id}（层 {region.layer_id}）的类型 {unknown} 不在宿主词表内，"
                    f"它禁止什么不确定，不判；区内现有：{listed}"
                ),
                evidence=[identity, f"unknown prohibitType words: {unknown}", *(f"inside: {i.label}" for i in copper), *blind],
                target=FindingTarget(primitive_id=region.id, net_refs=sorted({i.net for i in copper if i.net})),
            )
        return None

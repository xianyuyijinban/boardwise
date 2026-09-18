"""The draw flow: golden model -> bridge actions -> candidate -> diff (006/006b).

``run_draw`` orchestrates everything the ``boardwise draw`` CLI needs, one
awaitable step at a time, against an already-open :class:`BridgeClient`:

0. read the **measured sheet frame** off the focused page (read-only), then
   build the *complete* plan offline — since task 006b that means **replaying
   the golden page's own layout** (``engines.replay``: the human's placements,
   rotations, wires and label anchors, translated into the measured drawing
   area) with the generic solver as the fallback for boards without reference
   geometry;
1. run the **self-check gate** — all five hard constraints plus the annotation
   lint on the finished geometry; any violation aborts the run *before a
   single bridge call*;
2. print the gate summary and wait for the human confirm callback — only then
   create the blank page;
3. place every component (LCSC / keyword resolution happens editor-side; a
   failed resolution is recorded, not fatal), replay the wires, and name the
   nets exactly where the plan says (power/ground flags for rails, net
   *labels* for signals — 岳翔宇's rule; net ports are the solver's last
   resort);
4. build the candidate model — netlist export first, geometry readback as the
   fallback — and diff it against the golden model per pin;
5. render the page with ``export.render`` (a *document* render, not a viewport
   screenshot: the measured host returns cached frames from
   ``getCurrentRenderedAreaImage``) for the acceptance image.

Everything that did not go as planned lands in :class:`DrawResult` — failed
placements, replaced devices, unplaceable pins — because the acceptance
report must list them, not hide them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from boardwise.core.candidate import (
    GeometryError,
    NetlistFormatError,
    field_of,
    as_float,
    candidate_from_geometry,
    candidate_from_netlist,
)
from boardwise.core.compare import ComparisonReport, compare_models
from boardwise.core.model import DesignModel
from boardwise.core.overrides import AppliedOverrides, apply_overrides
from boardwise.core.verify import PlacementReport
from boardwise.engines import layout
from boardwise.engines.generate import (
    ActionPlan,
    canvas_pin_offsets,
    generate_plan,
    strip_dangling_nets,
)
from boardwise.engines.replay import (
    SheetFrame,
    replay_or_solver,
    sheet_frame_from_geometry,
)
from boardwise.parsers.schematic import PageLayout


@dataclass
class StepRecord:
    """One executed bridge action and how it went."""

    action: str
    summary: str
    ok: bool
    detail: str = ""


@dataclass
class DrawResult:
    """Everything the acceptance report is made of."""

    plan: ActionPlan
    records: list[StepRecord] = field(default_factory=list)
    #: "golden replay" or "generic solver" — a silently different layout
    #: strategy is exactly what makes a failure unreproducible.
    plan_source: str = ""
    #: The signal-naming policy the plan was built under (006b revision 3).
    naming_strategy: str = ""
    frame: SheetFrame | None = None
    netlist_probe: dict[str, Any] | None = None
    #: Page primitive-type census taken only when the netlist export fails;
    #: it is what tells "a port poisoned the exporter" apart from "our parser
    #: is wrong" (006b §A hypothesis).
    netlist_census: dict[str, int] | None = None
    candidate_source: str = ""
    missing_pins: list[tuple[str, str, str]] = field(default_factory=list)
    comparison: ComparisonReport | None = None
    #: F2 — the per-designator placement verdict from the pre-wire readback.
    #: ``None`` means the readback never happened (the page was not drawable),
    #: which is different from "every part matched".
    placement_report: PlacementReport | None = None
    #: §G — golden corrections applied from the sidecar, one report line each
    #: ("U3 value: 黄金 1kΩ → 2.2kΩ [provenance]"). Empty means no sidecar.
    override_lines: list[str] = field(default_factory=list)
    #: designator -> package name, resolved library-side for the diff.
    footprint_names: dict[str, str] = field(default_factory=dict)
    #: F3 — designators whose wire endpoints were moved from the golden pin
    #: tip to the placed symbol's actual pin, with the pin count remapped.
    remapped: dict[str, str] = field(default_factory=dict)
    #: Component-level gaps that are the editor enriching library metadata
    #: (golden attr empty, candidate filled) — expected, not drawing errors.
    enrichment_notes: list[str] = field(default_factory=list)
    #: ``export.render`` output — the acceptance image (document render).
    render_b64: str | None = None
    #: ``export.screenshot`` output — kept only as a diagnostic, never as
    #: evidence (the viewport capture returns cached frames on this host).
    screenshot_b64: str | None = None

    @property
    def failures(self) -> list[StepRecord]:
        return [r for r in self.records if not r.ok]

    @property
    def zero_diff(self) -> bool:
        """The acceptance gate: per-pin plus presence, per the task.

        Component-level *attribute* gaps that are pure library enrichment
        (golden empty, candidate filled) do not fail the run — they are
        reported separately. A wrong footprint/value where the golden side
        has one still fails, as it should.
        """
        report = self.comparison
        if report is None:
            return False
        return not (
            report.net_differences
            or report.pin_differences
            or any(
                d.detail.startswith("component ")
                for d in report.component_differences
            )
        )


class DrawAborted(Exception):
    """The human said no at the gate."""


class SelfCheckFailed(Exception):
    """The plan violates a hard constraint; nothing may execute."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(f"{len(violations)} self-check violation(s)")


async def _call(
    client: Any,
    action: str,
    params: dict[str, Any],
    records: list[StepRecord],
    summary: str,
) -> dict[str, Any] | None:
    """One bridge call, recorded. Returns ``data`` or ``None`` on failure."""
    try:
        data = await client.call(action, params)
        records.append(StepRecord(action, summary, True))
        return data
    except Exception as exc:  # noqa: BLE001 — every failure is a report row
        message = getattr(exc, "message", None) or str(exc)
        records.append(StepRecord(action, summary, False, message))
        return None


def _census_types(geometry: dict[str, Any] | None) -> dict[str, int]:
    """Count page primitives by their editor-reported type.

    The ``sch.geometry`` dump is a list of primitive records whose type tag
    lives under one of a few keys depending on the host build. Anything
    unreadable is reported as ``"<unlabelled>"`` rather than dropped — a
    silent bucket is exactly the trap this census exists to avoid.
    """
    census: dict[str, int] = {}
    primitives = (geometry or {}).get("primitives")
    if not isinstance(primitives, list):
        return census
    for prim in primitives:
        tag = "<unlabelled>"
        if isinstance(prim, dict):
            for key in ("type", "primitiveType", "kind", "className", "name"):
                value = prim.get(key)
                if isinstance(value, str) and value:
                    tag = value
                    break
        census[tag] = census.get(tag, 0) + 1
    return census


async def _census_primitives(client: Any, records: list[StepRecord]) -> dict[str, int] | None:
    """Read the page's primitive types, for the netlist-failure post-mortem."""
    geometry = await _call(
        client, "sch.geometry", {}, records, "census page primitives (netlist failed)"
    )
    if geometry is None:
        return None
    census = _census_types(geometry)
    if not census:
        records.append(
            StepRecord(
                "candidate.census", "census page primitives", False,
                "geometry dump carried no primitive list",
            )
        )
        return None
    rendered = ", ".join(f"{k}={v}" for k, v in sorted(census.items()))
    records.append(StepRecord("candidate.census", "census page primitives", True, rendered))
    return census


def pin_positions_from_geometry(geo: dict[str, Any]) -> dict[tuple[str, str], tuple[float, float]]:
    """(designator, pin number) -> page point, from a ``sch.geometry`` dump.

    Mirrors :func:`boardwise.core.candidate.candidate_from_geometry` pin
    attachment: an explicit designator field on the pin when the editor
    exposes one, nearest-component otherwise. Kept for the diagnostic path —
    the measured host returns no pin primitives on a schematic page.
    """
    positions: dict[tuple[str, str], tuple[float, float]] = {}
    component_pos: list[tuple[str, float, float]] = []
    for entry in geo.get("components") or []:
        state = entry.get("state") or {}
        designator = str(field_of(state, "Designator", "Name") or "").strip()
        x, y = as_float(field_of(state, "X")), as_float(field_of(state, "Y"))
        if designator and not designator.endswith("?") and x is not None and y is not None:
            component_pos.append((designator, x, y))

    def nearest(x: float, y: float) -> str | None:
        best, best_d = None, float("inf")
        for des, cx, cy in component_pos:
            d = (cx - x) ** 2 + (cy - y) ** 2
            if d < best_d:
                best, best_d = des, d
        return best

    for entry in geo.get("pins") or []:
        state = entry.get("state") or {}
        number = str(field_of(state, "PinNumber", "Number") or "").strip()
        x, y = as_float(field_of(state, "X")), as_float(field_of(state, "Y"))
        if not number or x is None or y is None:
            continue
        owner = str(field_of(state, "Designator") or "").strip()
        if owner not in {d for d, _x, _y in component_pos}:
            owner = nearest(x, y) or ""
        if owner:
            positions[(owner, number)] = (x, y)
    return positions


def _reconcile_derived_names(
    golden: DesignModel,
    candidate: DesignModel,
    pin_maps: dict[str, Any] | None = None,
) -> int:
    """Rename candidate nets to the golden's, matched by exact membership.

    Returns how many were renamed. Only a candidate net whose member set is
    *identical* to a golden net is renamed, so a genuinely drawn-differently
    cluster keeps its own name and still surfaces in the diff. This exists for
    the clusters neither side ever named: the golden parser calls them
    ``NET1..N``, the editor calls them ``$11N…``, and reporting each as
    "missing" plus "extra" buries the real differences.

    ``pin_maps`` translates the comparison into *golden* addressing first: a
    drifted part's placed pins carry pad-name numbers (``A5``), so without the
    translation the same two-member cluster looks different on each side and
    the rename never fires — measured 2026-09-15 (NET6 vs $16N3, electrically
    the same wire F3 had just connected).
    """
    translate: dict[tuple[str, str], tuple[str, str]] = {}
    for designator, pin_map in (pin_maps or {}).items():
        if pin_map is None:
            continue
        for golden_number, placed_number in pin_map.pairs.items():
            translate[(designator, str(placed_number))] = (
                designator, str(golden_number),
            )

    def members(pins) -> frozenset:
        return frozenset(translate.get(pin, pin) for pin in pins)

    golden_by_members: dict[frozenset, str] = {}
    for name, net in golden.nets.items():
        golden_by_members.setdefault(members(net.pins), name)

    renamed: dict[str, str] = {}
    taken: set[str] = set()
    for name, net in candidate.nets.items():
        if name in golden.nets:
            continue  # already the right name; leave it alone
        match = golden_by_members.get(members(net.pins))
        if match and match not in taken and match != name:
            renamed[name] = match
            taken.add(match)

    if not renamed:
        return 0
    for component in candidate.components.values():
        for pin in component.pins:
            if pin.net in renamed:
                pin.net = renamed[pin.net]
    for old, new in renamed.items():
        net = candidate.nets.pop(old, None)
        if net is None:
            continue
        net.name = new
        candidate.nets[new] = net
    return len(renamed)


_UUID_LIKE = re.compile(r"^[0-9a-f]{16}$|^[0-9a-f]{32}$")



async def _settled_netlist(
    client: Any,
    records: list[StepRecord],
    attempts: int = 4,
) -> tuple[dict[str, Any] | None, int, bool]:
    """Export until two consecutive reads agree; return the last one.

    A save sits between every pair, because the staleness is not the file being
    dirty (the flow always saved) but the editor's connectivity recompute
    lagging the wire creation. ``settled`` says whether agreement was reached
    — a caller that gave up is reporting a read it does not trust, which is
    different from a read it does.
    """
    previous: str | None = None
    last: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        await _call(client, "sch.doc.save", {}, records, f"save project (attempt {attempt})")
        last = await _call(
            client, "sch.netlist", {"type": "EasyEDA"}, records,
            f"export editor netlist (attempt {attempt})",
        )
        text = (last or {}).get("text") or ""
        if previous is not None and text == previous:
            return last, attempt, True
        previous = text
    return last, attempts, False


async def _resolve_placed_footprints(
    client: Any,
    placed_devices: dict[str, tuple[str, str]],
    expected: dict[str, str],
    records: list[StepRecord],
) -> tuple[dict[str, str], list[str]]:
    """designator -> package name, resolved through the library, plus problems.

    The netlist exports a footprint *document uuid* that belongs to the project
    (measured 2026-09-15: `lib_Footprint.get` refuses it with and without a
    library uuid), so it cannot be turned into a name directly. The route that
    works is the device the editor actually placed: `place_component` hands
    back its device uuid pair, `lib_Device.get` carries `association.footprint`
    and `lib_Footprint.get` names that footprint. Nothing here is our intent —
    every name comes from the library entry for the placed device.

    ``expected`` is the override sidecar's `expect_footprint`: when it is set
    the resolved name must match it, and a mismatch is returned as a problem.
    That is what makes "is R24 really a 0402?" a measurement rather than a
    claim.
    """
    names: dict[str, str] = {}
    problems: list[str] = []
    by_device: dict[tuple[str, str], str] = {}
    for designator, (device_uuid, library_uuid) in sorted(placed_devices.items()):
        if not device_uuid:
            continue
        key = (device_uuid, library_uuid)
        if key not in by_device:
            device = await _call(
                client, "lib.device.get",
                {"uuid": device_uuid, "libraryUuid": library_uuid},
                records, f"resolve placed device of {designator}",
            )
            association = ((device or {}).get("item") or {}).get("association") or {}
            footprint = association.get("footprint") or {}
            footprint_uuid = footprint.get("uuid")
            name = ""
            if footprint_uuid:
                read = await _call(
                    client, "lib.footprint.get",
                    {
                        "uuid": footprint_uuid,
                        "libraryUuid": footprint.get("libraryUuid") or library_uuid,
                    },
                    records, f"resolve footprint of the device placed as {designator}",
                )
                name = str((read or {}).get("name") or "").strip()
            by_device[key] = name
        name = by_device[key]
        if name:
            names[designator] = name
        want = expected.get(designator, "")
        if want and name and name != want:
            problems.append(
                f"{designator}: placed package is {name!r}, the override expects {want!r}"
            )
    return names, problems


def _orthogonalize(
    points: list[tuple[float, float]],
    original: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """Make a polyline orthogonal and free of redundant vertices.

    The editor's wire `create` rejects diagonal segments ("create failed!",
    reproduced 2026-09-15 twice on the same two polylines). Snapping one end
    of an orthogonal wire while the other end keeps its golden coordinate
    turns the segment between them diagonal — the golden endpoint was a few
    units off the pin tip, so the exact-match snap had skipped it.

    The L-split follows the *original* segment's axis, not a fixed order: the
    golden routing is the intent, and a blind horizontal-first split re-routes
    wires through neighbouring nets (measured 2026-09-15 — D+/D- detoured into
    +5V and merged with it).
    """
    # 1. drop consecutive duplicates (a snap can fold two points onto one).
    deduped: list[tuple[float, float]] = []
    for point in points:
        if deduped and deduped[-1] == point:
            continue
        deduped.append(point)
    # 2. split diagonal segments into an L, along the original segment's axis.
    lshaped: list[tuple[float, float]] = deduped[:1]
    for index, (x, y) in enumerate(deduped[1:]):
        a = lshaped[-1]
        if x == a[0] or y == a[1]:
            lshaped.append((x, y))
            continue
        horizontal_first = True
        if original is not None and index + 1 < len(original):
            prior = original[index + 1]
            before = original[index]
            if prior[1] != before[1] and prior[0] == before[0]:
                horizontal_first = False
        lshaped.append((x, a[1]) if horizontal_first else (a[0], y))
        lshaped.append((x, y))
    # 3. drop vertices that only continue the previous straight run.
    final: list[tuple[float, float]] = lshaped[:1]
    for point in lshaped[1:]:
        if len(final) >= 2:
            a, b = final[-2], final[-1]
            cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
            along = (b[0] - a[0]) * (point[0] - b[0]) + (b[1] - a[1]) * (point[1] - b[1])
            if cross == 0 and along > 0:
                final[-1] = point
                continue
        final.append(point)
    return final if len(final) >= 2 else points


async def _snap_drifted_pins(
    client: Any,
    plan: ActionPlan,
    drifted: list[Any],
    placed_ids: dict[str, str],
    records: list[StepRecord],
) -> int:
    """真 F3 — aim the plan's wire endpoints at the *placed* pin positions.

    The replay points every wire at the golden pin tip. For a part whose
    library symbol was redrawn (the F2 verdict "drifted") those tips do not
    exist on the placed page, so the wire misses. The seventh path —
    `sch.component_pins` — hands back the placed component's actual pin
    coordinates, so each endpoint that was aimed at a golden tip moves onto
    the real one, translated through F2's pin map.

    Returns how many points moved. Snapping touches wire points and name
    anchors alike: a point that coincides with a pin tip is a connection
    point wherever it sits in the polyline, so every match is moved, not just
    the polyline's ends.
    """
    snaps: dict[tuple[float, float], tuple[float, float]] = {}
    for check in drifted:
        designator = check.designator
        primitive_id = placed_ids.get(designator)
        if not primitive_id or check.pin_map is None or not check.pin_map.pairs:
            continue
        read = await _call(
            client, "sch.component_pins", {"primitiveId": primitive_id}, records,
            f"read placed pins of {designator} (F3 snap)",
        )
        if not read or not isinstance(read.get("pins"), list):
            continue
        actual: dict[str, tuple[float, float]] = {}
        for pin in read["pins"]:
            number = pin.get("PinNumber")
            x = pin.get("X")
            y = pin.get("Y")
            if number is None or x is None or y is None:
                continue
            actual[str(number)] = (float(x), float(y))
        for golden_number, placed_number in check.pin_map.pairs.items():
            tip = plan.pin_positions.get((designator, golden_number))
            target = actual.get(placed_number)
            if tip is None or target is None:
                continue
            snaps[(round(tip[0], 3), round(tip[1], 3))] = target
    if not snaps:
        return 0

    # Golden wire endpoints do not always sit *exactly* on the golden pin tip
    # (measured: 4 units off on a VBUS run), so the lookup is by nearest tip
    # within a tolerance rather than by exact coordinate — an endpoint that
    # misses the snap leaves its wire half-moved, and a half-moved orthogonal
    # wire is diagonal, which the editor refuses to create.
    tips = list(snaps.items())

    def snap_point(point: tuple[float, float]) -> tuple[float, float] | None:
        x, y = point
        exact = snaps.get((round(x, 3), round(y, 3)))
        if exact is not None:
            return exact
        best: tuple[float, float] | None = None
        best_distance = 6.0
        for (tip_x, tip_y), target in tips:
            distance = ((tip_x - x) ** 2 + (tip_y - y) ** 2) ** 0.5
            if distance <= best_distance:
                best_distance = distance
                best = target
        return best

    moved = 0

    def replace(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        nonlocal moved
        # **Keep the golden run, add a stub.** Moving the endpoint re-routes
        # the wire, and inside the drifted part's dense pin field (USB1: a
        # dozen pins 10 units apart) a re-route crosses a neighbouring net and
        # merges with it — measured twice on 2026-09-15. Instead the polyline
        # still passes through the golden tip and gains one straight segment
        # from there to the placed pin, so the golden routing is untouched and
        # only a stub is new.
        out: list[tuple[float, float]] = []
        last = len(points) - 1
        for index, (x, y) in enumerate(points):
            snap = snap_point((x, y))
            if snap is None:
                out.append((x, y))
                continue
            moved += 1
            if index == 0:
                out.append(snap)
                out.append((x, y))
            elif index == last:
                out.append((x, y))
                out.append(snap)
            else:
                # a junction mid-run: reach the pin and come back to the run
                out.append((x, y))
                out.append(snap)
                out.append((x, y))
        return out

    for step in plan.wires:
        step.points = _orthogonalize(replace(step.points), original=step.points)
    for step in plan.net_names:
        snap = snap_point((step.x, step.y))
        if snap is not None:
            moved += 1
            step.x, step.y = snap
    return moved


def _editor_rotation(rotation: float) -> float:
    """The angle to hand the editor, which is **not** the file's angle.

    The golden file's instance rotation is clockwise in *y-up* space (pinned in
    005), and `_rotated_canvas_offsets` faithfully reproduces it when computing
    where each pin tip lands — which is where the replayed wire endpoints go.

    The editor's `rotation` parameter, however, turns the symbol the *other*
    way round: measured 2026-09-14, every part replayed at ``90`` or ``270``
    came back with its pins exchanged, while ``0`` and ``180`` were correct.
    That is the exact signature of a sign flip — negating an angle leaves 0 and
    180 untouched and swaps 90 with 270. The visible consequence was the eight
    two-pin passives (C25, C3, C4, C5, C6, C7, C9, U3) reporting pin 1 where
    the golden has pin 2, and their wire endpoints missing the pin tips.

    So the replay keeps the golden angle for its own geometry, and this one
    function translates it at the API boundary — the only place the two
    conventions meet.
    """
    return (-float(rotation)) % 360.0


def print_gate(plan: ActionPlan, model: DesignModel, source: str, frame: SheetFrame | None) -> None:
    """The gate: what will happen, in full, before anything executes."""
    print(f"GATE: {plan.summary()}  [plan source: {source}]")
    print(f"      golden model: {len(model.components)} components, {len(model.nets)} nets")
    if frame is not None:
        print(f"      {frame.render()}")
    decorative = plan.decorative_names
    signals = [s for s in plan.net_names if s.kind in ("text", "label", "port")]
    if decorative:
        # Said at the gate, not buried in a footnote: signal names drawn as
        # text are visible but carry no connectivity of their own.
        print(
            f"      naming: {plan.naming_strategy} — {len(decorative)} signal name(s) "
            "are drawn as TEXT (decorative, not native net labels)"
        )
    elif signals:
        print(f"      naming: {plan.naming_strategy} — {len(signals)} signal name(s) as native labels")
    else:
        print(
            f"      naming: {plan.naming_strategy} — no signal name primitive; "
            "names ride on the wires / are derived by the editor"
        )
    for step in plan.placements:
        how = step.lcsc or step.keyword or "(no resolution info)"
        pose = f"rot {step.rotation:.0f}" + (" mirror" if step.mirror else "")
        print(f"  place {step.designator:8} at ({step.x:.0f}, {step.y:.0f})  {pose:14} via {how}")
    for note in plan.notes:
        print(f"  note: {note}")
    nc = ", ".join(f"{des}.{pin}" for des, pin in plan.nc_pins) or "(none)"
    print(f"  NC pins (left open): {nc}")
    print(f"  net names ({len(plan.net_names)}):")
    for step in plan.net_names:
        print(f"    {step.kind:7} {step.net} at ({step.x:.0f},{step.y:.0f})")
    print(f"  wires: {len(plan.wires)} polylines")


def print_self_check(plan: ActionPlan) -> list[str]:
    """Rendered self-check + lint lines; empty means the plan may execute."""
    return [v.render() for v in plan.violations]


async def _verify_placements(
    client: Any,
    golden: DesignModel,
    plan: ActionPlan,
    result: "DrawResult",
    page_uuid: Any,
) -> tuple[DesignModel | None, dict[str, Any], "PlacementReport | None"]:
    """F2 — read the freshly placed parts back and map them to the golden.

    Returns ``(placed_model, pin_maps, report)``. The report is ``None`` when
    the readback could not happen at all — the netlist export is the one
    measured-fragile step on this host, and *not knowing* must stay distinct
    from *knowing the page is fine*. A missing report therefore does not block
    the draw (that would regress 006's working boards); a report that is
    present and *not ok* does.

    The candidate is built with the same reader the final diff uses, so the
    map and the verdict can never disagree about what was placed.
    """
    from boardwise.core.verify import verify_placements

    await _call(client, "sch.doc.save", {}, result.records, "save before readback")
    netlist = await _call(
        client, "sch.netlist", {"type": "EasyEDA"}, result.records,
        "export netlist (placement verification readback)",
    )
    result.netlist_probe = netlist
    if not (netlist and isinstance(netlist.get("text"), str)):
        result.records.append(
            StepRecord(
                "verify.placements", "placement verification readback", False,
                "no netlist text — cannot verify the placements; drawing continues "
                "unverified (the final diff still runs)",
            )
        )
        return None, {}, None
    try:
        placed = candidate_from_netlist(netlist["text"], netlist.get("type", "EasyEDA"))
    except NetlistFormatError as exc:
        result.records.append(
            StepRecord("verify.placements", "parse readback netlist", False, str(exc))
        )
        return None, {}, None

    report = verify_placements(golden, placed)
    pin_maps = {c.designator: c.pin_map for c in report.checks if c.pin_map is not None}
    result.placement_report = report
    result.remapped = {
        c.designator: c.pin_map.detail
        for c in report.checks
        if c.kind == "drifted" and c.pin_map is not None
    }
    summary = (
        f"{len(report.checks)} parts verified "
        f"({len(report.drifted)} drifted with the library version)"
    )
    result.records.append(StepRecord("verify.placements", summary, report.ok,
                                     "" if report.ok else report.blocks()))
    return placed, pin_maps, report


async def run_draw(
    client: Any,
    model: DesignModel,
    *,
    confirm: Callable[[], bool],
    offsets: dict[str, dict[str, tuple[float, float]]],
    symbol_defs: dict[str, dict[str, tuple[float, float]]] | None = None,
    page_layout: PageLayout | None = None,
    bodies: dict[str, tuple[float, float, float, float]] | None = None,
    prefer_replay: bool = True,
    strategy: str | None = None,
    overrides: "AppliedOverrides | None" = None,
) -> DrawResult:
    """Execute the whole flow against ``client``. See the module docstring.

    ``offsets`` are *file-space* symbol offsets (from
    ``parsers.schematic.build_pin_offsets``); the plan builder converts them
    to canvas space. ``symbol_defs`` (symbol uuid -> pin offsets) feeds the
    geometry-path candidate builder. ``page_layout`` + ``bodies`` are the
    golden page's own geometry (``collect_page_layout`` /
    ``collect_symbol_bodies``) — with them the plan is a **replay**, without
    them the generic solver runs. ``strategy`` is the signal-naming policy
    (``wire`` / ``text`` / ``label`` / ``none``; default ``text``).
    """
    # dangling single-member nets name nothing (measured on the golden
    # board's leftover wire stubs); both sides must treat them as open
    model = strip_dangling_nets(model)

    # --- gate 0: the golden corrections, before a single coordinate is
    # computed. The fixture is evidence and never edited (§G.3); the sidecar
    # carries the corrections, and every hit is reported with its provenance
    # so the diff cannot quietly become "compared against a value we chose".
    override_lines: list[str] = []
    override_problem = ""
    if overrides is not None and overrides.active:
        override_lines = apply_overrides(model, overrides)
        if overrides.unknown:
            override_problem = (
                "sidecar names unknown designator(s): " + ", ".join(overrides.unknown)
            )

    # --- gate 0a: the measured frame, from the focused page (read-only)
    #
    # Read *before* anything is created so the gate still precedes every
    # mutation: the new page shares the schematic's template, so the frame it
    # will have is the frame the focused page has. When the host exposes no
    # sheet (or no bbox), the replay refuses and the solver takes over with a
    # note — never a nominal A4.
    frame: SheetFrame | None = None
    if page_layout is not None and prefer_replay:
        probe_geo = await _call(
            client, "sch.geometry", {}, [], "read the sheet frame (read-only)"
        )
        if probe_geo is not None:
            frame = sheet_frame_from_geometry(
                probe_geo,
                declared=page_layout.sheet_attrs,
                origin=page_layout.sheet_origin,
            )

    plan, plan_source = replay_or_solver(
        model,
        page_layout,
        frame,
        offsets,
        bodies=bodies,
        prefer_replay=prefer_replay,
        strategy=strategy,
    )

    # --- gate 0b: the self-check + lint. Any violation aborts before a
    # single bridge mutation — revision 3's "没有通过自检前不许再碰编辑器".
    report = print_self_check(plan)
    if report:
        print(f"SELF-CHECK FAILED — {len(report)} violation(s); nothing will be executed:")
        for line in report:
            print(f"  {line}")
        raise SelfCheckFailed(report)
    print(layout.lint_report(plan.violations)[-1])

    print_gate(plan, model, plan_source, frame)
    if override_lines:
        # Said at the gate, not buried: the plan below is built against a
        # *corrected* golden, and a reader must see which values differ from
        # the fixture and on whose authority.
        print(f"  golden overrides ({len(override_lines)}):")
        for line in override_lines:
            print(f"    {line}")
    if not confirm():
        raise DrawAborted("aborted at the gate")

    result = DrawResult(plan=plan, plan_source=plan_source, frame=frame, naming_strategy=plan.naming_strategy)
    result.override_lines = list(override_lines)
    if override_lines:
        result.records.append(
            StepRecord(
                "plan.overrides",
                f"{len(override_lines)} golden override(s) applied",
                not override_problem,
                override_problem,
            )
        )

    # --- 1. a blank page to draw on (focused; see sch.doc.new)
    #
    # `sch.doc.new` is a `create` action, so the daemon refuses it without an
    # explicit confirmation (006c: creating a document is the one thing that
    # must be asked for). The asking happened at this flow's own execution
    # gate — `print_gate` + `confirm()` ran before any of this — so the
    # confirmation travels with the call rather than being demanded twice.
    page = await _call(
        client, "sch.doc.new", {"confirm": True}, result.records,
        "create blank schematic page",
    )
    if page is None:
        return result
    page_uuid = page.get("pageUuid")

    # --- 2. placements (mirror verbatim; rotation sign-corrected — see
    # `_editor_rotation` for the measurement that forced it)
    placed_ids: dict[str, str] = {}
    #: designator -> the library device pair `place_component` resolved to;
    #: the route to a footprint *name* (see `_resolve_placed_footprints`).
    placed_devices: dict[str, tuple[str, str]] = {}
    for step in plan.placements:
        params: dict[str, Any] = {
            "x": step.x,
            "y": step.y,
            "rotation": _editor_rotation(step.rotation),
            "mirror": step.mirror,
            "designator": step.designator,
            "pageUuid": page_uuid,
        }
        params.update(step.resolution())
        summary = f"place {step.designator} ({step.lcsc or step.keyword or '?'})"
        placed = await _call(client, "sch.place_component", params, result.records, summary)
        # The placed component's primitive id — the key the seventh path
        # (`sch.component_pins`) needs to hand back real pin coordinates.
        if placed and isinstance(placed.get("uuid"), str):
            placed_ids[step.designator] = placed["uuid"]
        device = (placed or {}).get("device") or {}
        if isinstance(device.get("uuid"), str):
            placed_devices[step.designator] = (
                device["uuid"], str(device.get("libraryUuid") or ""),
            )

    # --- 2a. §G.4 — write the attributes the netlist export otherwise leaves
    # empty, so both sides of the diff compare the same field.
    #
    # Measured 2026-09-15: the candidate lacks `Value` on 8 parts and
    # `Supplier Footprint` on 20 — the latter falls back to a *project-local*
    # footprint uuid, which `lib_Footprint.get` refuses (with and without a
    # library uuid), so those rows cannot be aligned by lookup. The library
    # footprint name is a different vocabulary anyway ("C0603" vs the golden's
    # "0603"), which is why the name is used as an independent package check
    # (`expect_footprint`) and the human label is what gets written.
    for step in plan.placements:
        primitive_id = placed_ids.get(step.designator)
        if not primitive_id:
            continue
        # One call, whole map: `modify`'s otherProperty *replaces* the map, so
        # writing key by key keeps only the last one (§J.1, measured on C1).
        wanted = {
            key: value
            for key, value in (
                ("Value", step.value), ("Supplier Footprint", step.footprint),
            )
            if value
        }
        if not wanted:
            continue
        applied = await _call(
            client, "sch.set_component_attribute",
            {"primitiveId": primitive_id, "attributes": wanted, "pageUuid": page_uuid},
            result.records,
            f"set {'+'.join(sorted(wanted))}="
            + "/".join(wanted[k] for k in sorted(wanted))
            + f" on {step.designator}",
        )
        # §J.1: the action defines `applied` as "the read-back equals the
        # target". A caller that ignores it turns a silent no-op into a green
        # report — which is exactly how the whole-map replacement stayed
        # invisible for a round.
        if applied is not None and applied.get("applied") is False:
            reason = ", ".join(applied.get("mismatched") or []) or "the read-back did not match"
            result.records.append(
                StepRecord(
                    "verify.attributes",
                    f"read back attributes of {step.designator}",
                    False,
                    reason,
                )
            )

    # --- 2b. F2 — read the placements back and verify them AGAINST THE
    # GOLDEN, *before* a single wire is drawn.
    #
    # Round 4 (task 006b §E) replayed every wire at the *golden* pin tip on
    # the assumption that the library would resolve to the same symbol. It did
    # not: a 0402 became a 0603 and USB1's pins were renumbered, so all 51
    # differences were endpoints that missed their pin. Verifying here — after
    # the parts exist but before the copper — turns that class of failure into
    # a refusal or a remap instead of a silently broken page.
    #
    # The save is not decoration: the netlist export returns nothing for a
    # never-saved project (measured 2026-09-13).
    placed_model, pin_maps, placement_report = await _verify_placements(
        client, model, plan, result, page_uuid
    )
    if placement_report is not None and not placement_report.ok:
        # fail fast: the geometry cannot be trusted, so the wires would only
        # draw a broken page. Record the reason and stop.
        result.records.append(
            StepRecord(
                "verify.placements",
                "placement gate (FAIL FAST)",
                False,
                placement_report.blocks(),
            )
        )
        return result

    # --- 2c. 真 F3 — for every part F2 called *drifted*, read the placed
    # component's actual pin coordinates and move the plan's endpoints onto
    # them. Nothing else in the plan changes: a point that is not a golden
    # pin tip of a drifted part stays exactly where the golden put it.
    drifted = placement_report.drifted if placement_report is not None else []
    if drifted and placed_ids:
        moved = await _snap_drifted_pins(
            client, plan, drifted, placed_ids, result.records
        )
        if moved:
            result.records.append(
                StepRecord(
                    "plan.snap_drifted_pins",
                    f"{moved} point(s) snapped to placed pin positions",
                    True,
                    "the golden pin tips of drifted parts do not exist on the "
                    "placed page; endpoints aimed at them moved onto the real "
                    "pins through F2's pin map",
                )
            )
            # Snapping adds a stub, and a stub is a new run whose endpoint can
            # land inside another run — so the junction rule has to be applied
            # again *after* the geometry changed, not only when the plan was
            # built.
            from boardwise.engines.replay import split_at_junctions

            plan.wires, resplit = split_at_junctions(plan.wires)
            if resplit:
                result.records.append(
                    StepRecord(
                        "plan.split_junctions",
                        f"{resplit} run(s) split at T-junctions after snapping",
                        True,
                        "the editor merges polylines that share an endpoint and "
                        "can then bury a pin tip mid-polyline; every touching "
                        "run must end at the junction",
                    )
                )
            # Snapping adds a stub, and a stub is a new run whose endpoint can
            # land inside another run — so the junction rule has to be applied
            # again *after* the geometry changed, not only when the plan was
            # built.
            from boardwise.engines.replay import split_at_junctions

            plan.wires, resplit = split_at_junctions(plan.wires)
            if resplit:
                result.records.append(
                    StepRecord(
                        "plan.split_junctions",
                        f"{resplit} run(s) split at T-junctions after snapping",
                        True,
                        "the editor merges polylines that share an endpoint and "
                        "can then bury a pin tip mid-polyline; every touching "
                        "run must end at the junction",
                    )
                )

    # --- 3. wires and net names, exactly where the plan computed them
    for step in plan.wires:
        params = {
            "points": [[x, y] for x, y in step.points],
            # An empty name means "the source did not name this wire": pass
            # nothing and let the editor derive it, instead of inventing one.
            "net": step.net or None,
            "pageUuid": page_uuid,
        }
        # The coordinates travel in the summary: "create failed!" is the
        # editor's own rejection and, without the geometry, it costs a whole
        # cleanup-and-rerun cycle to know *which* polyline it refused.
        summary = (
            f"wire {step.net or '(unnamed)'} ({len(step.points)} pts) "
            + " ".join(f"({x:.0f},{y:.0f})" for x, y in step.points)
        )
        await _call(
            client, "sch.place_wire", params, result.records, summary,
        )
    for step in plan.net_names:
        if step.kind == "text":
            # The decorative signal name: a text primitive beside the wire.
            # `decorative: true` is stated on the action itself, so the report
            # cannot present it as a native net label by accident.
            params = {
                "content": step.net, "x": step.x, "y": step.y,
                "rotation": step.rotation, "pageUuid": page_uuid,
            }
            summary = f"label net {step.net} (text, decorative)"
            action = "sch.place_text"
        elif step.kind == "label":
            params = {"net": step.net, "x": step.x, "y": step.y, "pageUuid": page_uuid}
            summary = f"label net {step.net}"
            action = "sch.place_netlabel"
        elif step.kind == "port":
            params = {
                "direction": "BI", "net": step.net, "x": step.x, "y": step.y,
                "pageUuid": page_uuid,
            }
            summary = f"name net {step.net} (port)"
            action = "sch.place_netport"
        else:
            params = {
                "kind": step.kind, "net": step.net, "x": step.x, "y": step.y,
                # Same convention as `place_component` — measured 2026-09-15:
                # the seven flag symbols in the golden all keep their pin at
                # (0, 0), so the placement origin *is* the connection point
                # and a flag connected either way round. What the un-flipped
                # angle got wrong was the **visual** direction: a Ground flag
                # at rot 90/270 pointed away from its wire while still landing
                # on it, which reads as "floating" to a human and hid behind a
                # clean netlist until the orientation was questioned.
                "rotation": _editor_rotation(step.rotation),
                "mirror": step.mirror,
                "pageUuid": page_uuid,
            }
            summary = f"name net {step.net} ({step.kind} flag)"
            action = "sch.place_power"
        await _call(client, action, params, result.records, summary)

    # --- 4. the candidate model for the verdict.
    #
    # It MUST be read *now*, after the wires: step 2b's readback predates the
    # copper, so reusing it here would diff an unwired page and report every
    # pin as unconnected. Measured 2026-09-14 — 54 phantom pin differences and
    # 13 "net missing" rows, all of them from that one shortcut. The placement
    # gate keeps its own readback; the verdict gets a fresh one.
    candidate: DesignModel | None = None
    # The export is taken **twice**. Measured 2026-09-15: the editor recomputes
    # connectivity after the wires are created, and an export taken right after
    # the last create returns the pre-recompute netlist — the run reported
    # U1.16 as unconnected while the very same page, re-exported moments later,
    # had it in VCC. The second export is the verdict's source; when the two
    # disagree that is recorded, because a stale read is worth knowing about.
    netlist, exports, settled = await _settled_netlist(client, result.records)
    if exports > 1:
        result.records.append(
            StepRecord(
                "verify.netlist_freshness",
                f"{exports} exports needed before two agreed"
                + ("" if settled else " (gave up; using the last read)"),
                settled,
                "the editor recomputes connectivity after the wires land, so the "
                "first export can describe the page as it was before the last "
                "wire — measured 2026-09-15: U1.16 read as unconnected on a page "
                "that was already correct",
            )
        )
    result.netlist_probe = netlist
    if netlist and isinstance(netlist.get("text"), str):
        try:
            candidate = candidate_from_netlist(netlist["text"], netlist.get("type", "EasyEDA"))
            result.candidate_source = "netlist export"
        except NetlistFormatError as exc:
            result.records.append(
                StepRecord("candidate.netlist", "parse editor netlist", False, str(exc))
            )
    if candidate is None:
        # The netlist export is the authority; when it comes back empty or
        # unparseable we must say *which* primitives are on the page, or the
        # post-mortem has nothing to chew on. The open hypothesis (task 006b
        # §A) is that a net-port primitive poisons the exporter — a census of
        # types separates "the exporter broke on a port" from "the page is
        # fine and our parser is the problem".
        result.netlist_census = await _census_primitives(client, result.records)
        geo2 = await _call(
            client, "sch.geometry", {}, result.records,
            "read final geometry (fallback candidate source)",
        )
        if geo2 is not None:
            try:
                candidate = candidate_from_geometry(
                    geo2,
                    symbol_defs=symbol_defs,
                    part_positions={
                        (step.x, step.y): step.designator for step in plan.placements
                    },
                    part_positions_canvas=True,
                )
                result.candidate_source = "geometry readback"
            except GeometryError as exc:
                result.records.append(
                    StepRecord("candidate.geometry", "parse geometry", False, str(exc))
                )
    if candidate is None:
        result.records.append(
            StepRecord("candidate", "build candidate model", False, "no candidate source worked")
        )
        return result

    # --- 4b. scope check. `getNetlistFile` exports the *project*, not the page
    # we just drew, so leftover pages from earlier runs are in this model.
    # Measured 2026-09-14: three drawn pages produced 51 designators, and the
    # golden-named parts sat on the page an earlier run had abandoned before
    # reaching the wires — every pin then read as unconnected. Say it out loud
    # rather than letting the diff look like 54 broken connections.
    # --- 4a. §G.4 — turn the candidate's footprint *uuids* back into package
    # names. The golden side reads `Supplier Footprint` (a semantic string);
    # the netlist export gives a document uuid, so 20 of the 25 rows were the
    # same package written two ways. `lib_footprint.get` is the editor's own
    # answer to "what is this uuid called", which makes the two sides
    # comparable without either side guessing.
    expected_footprints = {
        d: str(model.components[d].props.get("expect_footprint", ""))
        for d in model.components
        if model.components[d].props.get("expect_footprint")
    }
    result.footprint_names, footprint_problems = await _resolve_placed_footprints(
        client, placed_devices, expected_footprints, result.records
    )
    # §J.2: the library-resolved name must NOT become the diff operand. The
    # operand stays the netlist's `Supplier Footprint` — the field the write
    # above populates — so both sides compare the same vocabulary. Replacing
    # it with the library name ('C0603') guaranteed a mismatch against the
    # golden's label ('0603') no matter what the write achieved: a
    # constructive mismatch, not a data problem.
    if result.footprint_names:
        # §G.1/§I: the two vocabularies side by side — the label the board now
        # carries, and the library's own name for the package the placed
        # device resolved to. The library name is *evidence for the human*,
        # never a diff operand (§J.2).
        listed = ", ".join(
            f"{d}: label={(model.components[d].footprint if d in model.components else '')!r} library={n!r}"
            for d, n in sorted(result.footprint_names.items())
        )
        result.records.append(
            StepRecord("verify.footprints", "packages (label vs library name)", True, listed)
        )
    result.records.append(
        StepRecord(
            "verify.footprints", "package verification (§G.1)",
            not footprint_problems,
            "; ".join(footprint_problems),
        )
    )

    extra = sorted(set(candidate.components) - set(model.components))
    if extra:
        result.records.append(
            StepRecord(
                "candidate.scope",
                "netlist scope check",
                False,
                f"{len(extra)} designator(s) outside the golden model "
                f"(e.g. {', '.join(extra[:6])}): the netlist is project-scoped, "
                "so other pages are inside this diff — remove them before "
                "trusting the verdict",
            )
        )
        # A polluted candidate makes the whole verdict meaningless, so stop
        # here rather than print 200 rows of garbage that would bury the one
        # real difference underneath.
        return result

    # --- 5. the verdict. Two translations, both of them *addressing* only:
    #
    # (a) net names: the editor names a cluster it had to derive `$11N…` while
    #     the golden side names the same cluster `NET1..N`. A name is only
    #     rewritten when the two clusters have *exactly* the same members, so
    #     this can never hide a real connectivity difference — measured
    #     2026-09-14 on the machine, where the alternative was 44 rows of
    #     "net missing" + "net extra" for nets that were in fact identical.
    # (b) pin numbers: the maps from step 2b.
    candidate = strip_dangling_nets(candidate)
    renamed = _reconcile_derived_names(model, candidate, pin_maps)
    if renamed:
        result.records.append(
            StepRecord(
                "candidate.reconcile",
                f"{renamed} net(s) renamed by membership",
                True,
                "the editor derives its own names ($11N…) for clusters the "
                "golden source left unnamed; matched by members, not by name",
            )
        )
    result.comparison = compare_models(model, candidate, pin_maps=pin_maps)
    result.enrichment_notes = _split_enrichment(result.comparison, result.candidate_source)

    # pins the plan could not position at all (no offsets, no geometry)
    placed_pins = {
        (place.designator, number)
        for place in plan.geometry
        for number in (offsets.get(place.designator) or {})
    }
    for net_name, net in model.nets.items():
        for des, pin in net.pins:
            if (des, pin) not in placed_pins:
                result.missing_pins.append((net_name, des, pin))

    # --- 6. the acceptance image: a document render, not a viewport capture
    rendered = await _call(
        client, "export.render", {}, result.records, "render the document (acceptance image)"
    )
    if rendered and rendered.get("data"):
        result.render_b64 = rendered["data"]
    shot = await _call(
        client, "export.screenshot", {"fit": True}, result.records,
        "capture canvas screenshot (diagnostic only)",
    )
    if shot and shot.get("data"):
        result.screenshot_b64 = shot["data"]
    return result


#: Attribute gaps where one side simply cannot know: the editor fills empty
#: golden attributes from the library device (netlist path, measured: golden
#: U1 carries empty value/footprint/lcsc while the netlist reports
#: CH340G / SOP-16 uuid / C14267), and the geometry readback cannot read
#: attributes at all (its state carries only a Name template). Neither is a
#: drawing error; a real mismatch (both sides know, values differ) stays one.
_ENRICHABLE_DETAILS = frozenset({"footprint differs", "value differs", "lcsc differs"})


def _split_enrichment(
    report: ComparisonReport, candidate_source: str
) -> list[str]:
    """Remove non-verdict attribute rows from the report, return them as notes.

    Mutates ``report`` on purpose: the rendered diff should show only what a
    human would consider wrong. Netlist path: golden-empty attributes the
    editor enriched. Geometry path: ALL attribute rows — the instrument
    cannot read them; component presence and per-pin connectivity carry the
    verdict instead.
    """
    notes: list[str] = []
    kept: list[Any] = []
    geometry_path = "geometry" in candidate_source
    for d in report.component_differences:
        if d.detail in _ENRICHABLE_DETAILS and (
            not d.golden.strip() or (geometry_path and not d.candidate.strip())
        ):
            notes.append(
                f"{d.subject}: {d.detail} (golden={d.golden!r}, candidate={d.candidate!r})"
            )
        else:
            kept.append(d)
    report.component_differences[:] = kept
    return notes


def confirm_interactive() -> bool:
    """The default gate callback: ask on stdin."""
    try:
        answer = input("execute this plan? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")

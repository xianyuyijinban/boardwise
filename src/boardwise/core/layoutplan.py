"""LayoutPlan: the drawing the tool computed (053 stage A, 052 sec.4).

The third contract, and the only one this batch defines without producing: it is
"工具算出的图" — the plan the phase-B compiler emits, that the independent
readability checker consumes, and that an operator authorises before anything
touches the editor. Shape and serialisation only; nothing here lays anything
out.

What the plan has to carry, and why each item is not optional:

* **per part**, the symbol it was drawn with and that symbol's geometry hash —
  "实际符号版本/几何哈希" (052 sec.4). A plan whose symbol changed underneath it
  is stale, and the hash is how that is detectable without re-reading the
  library;
* **every line, junction, label, power symbol and text box**. "每段文字的 bbox"
  is a hard requirement of the readability contract (053 sec.2: 文字 bbox 不相交),
  so a text or label entry without a box is refused by the schema — a checker
  that received an unbounded text would have nothing to test;
* **the two source hashes**: a plan compiles a CircuitSpec and a PresentationSpec,
  and a plan that cannot say which ones cannot be judged stale;
* **the target snapshot** (project / page / host versions, and the page digest)
  plus an **evidence slot** in the shape the checker will fill
  (`hardViolations` / `grammarFindings` / `softMetrics` with a reason per
  metric). A plan is not "checked" because nobody looked: an empty slot says
  so, and :attr:`LayoutEvidence.verdict` is derived from what is there.

What it deliberately does not check: that the parts are the ones the
CircuitSpec declares, that the poses are legal for their profiles, or that the
nets are the declared nets. Every one of those needs a second document, and
they belong to the checker — whose whole point (052 sec.8) is that it works
from the plan and the specs alone, with no access to the compiler's insides.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .symbolprofile import Box, POSE_ROTATIONS, check_box

__all__ = [
    "EVIDENCE_VERDICT_FAIL",
    "EVIDENCE_VERDICT_NOT_RUN",
    "EVIDENCE_VERDICT_PASS",
    "LAYOUT_PLAN_KIND",
    "LAYOUT_PLAN_VERSION",
    "LayoutEvidence",
    "LayoutJunction",
    "LayoutLabel",
    "LayoutPart",
    "LayoutPlan",
    "LayoutPlanError",
    "LayoutPowerSymbol",
    "LayoutSegment",
    "LayoutSource",
    "LayoutTarget",
    "LayoutText",
]

#: Identifies the document; see `circuitspec.CIRCUIT_SPEC_KIND` for the rule.
LAYOUT_PLAN_KIND = "boardwise-layout-plan"

#: Same rule as `changeplan.PLAN_VERSION`: a plan from a future build is refused
#: rather than half-understood.
LAYOUT_PLAN_VERSION = 1

#: The three answers `LayoutEvidence.verdict` can give. `not-run` is a state of
#: its own so that "no violations found" can never be confused with "not looked
#: at" — the difference the whole evidence slot exists for.
EVIDENCE_VERDICT_PASS = "pass"
EVIDENCE_VERDICT_FAIL = "fail"
EVIDENCE_VERDICT_NOT_RUN = "not-run"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

_TOP_KEYS = (
    "kind",
    "planVersion",
    "source",
    "target",
    "parts",
    "segments",
    "junctions",
    "labels",
    "powerSymbols",
    "texts",
    "evidence",
    "notes",
    # Derived, but the writer emits them, so the reader accepts them — and
    # checks them (see `from_dict`): a document that states a verdict its own
    # findings contradict is refused rather than believed.
    "verdict",
    "geometrySha256",
)
_SOURCE_KEYS = ("circuitSha256", "presentationSha256")
_TARGET_KEYS = (
    "projectUuid",
    "boardUuid",
    "pageUuid",
    "hostVersion",
    "connectorVersion",
    "snapshotSha256",
)
_PART_KEYS = (
    "partId",
    "reference",
    "symbolRef",
    "symbolHash",
    "x",
    "y",
    "rotation",
    "mirror",
)
_SEGMENT_KEYS = ("net", "points")
_JUNCTION_KEYS = ("net", "x", "y")
_LABEL_KEYS = ("net", "text", "x", "y", "rotation", "bbox")
_POWER_KEYS = ("symbolRef", "symbolHash", "net", "x", "y", "rotation")
_TEXT_KEYS = ("kind", "text", "partId", "x", "y", "rotation", "bbox")
_EVIDENCE_KEYS = (
    "checker",
    "hardViolations",
    "grammarFindings",
    "softMetrics",
    "softReasons",
    "notes",
)


class LayoutPlanError(ValueError):
    """The plan is not one this build can read."""


@dataclass
class LayoutSource:
    """The two specs this plan was compiled from, by digest."""

    circuit_sha256: str = ""
    presentation_sha256: str = ""


@dataclass
class LayoutTarget:
    """Where the plan will land, and what it saw there.

    ``snapshot_sha256`` is empty for a plan compiled **offline** — the phase-B
    acceptance runs against no editor at all — so an empty digest is a fact
    ("not bound to a live page yet"), not a missing guard. When it is set it is
    the page digest the plan was built against, exactly as
    `changeplan.PlanSource.input_sha256` is for a local edit.
    """

    project_uuid: str = ""
    board_uuid: str = ""
    page_uuid: str = ""
    host_version: str = ""
    connector_version: str = ""
    snapshot_sha256: str = ""


@dataclass
class LayoutPart:
    """One placed part: which symbol, at which hash, at which pose and point.

    ``reference`` is the designator the plan *assigns* — a CircuitSpec id is not
    a designator (see `circuitspec.SpecPart`), so the landing step names the
    part, and it may still be empty in a plan that has not landed. `symbol_hash`
    is the profile's :meth:`~boardwise.core.symbolprofile.SymbolProfile.geometry_hash`.
    """

    part_id: str
    symbol_ref: str = ""
    symbol_hash: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    mirror: bool = False
    reference: str = ""


@dataclass
class LayoutSegment:
    """One drawn wire: its net and its polyline, in canvas units."""

    net: str
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class LayoutJunction:
    """A dot where a wire branches — expected only where a tees."""

    net: str
    x: float = 0.0
    y: float = 0.0


@dataclass
class LayoutLabel:
    """A net label: text that *means* a net, with the box it occupies.

    The box is required, and the checker reads these boxes together with
    `LayoutText`'s when it tests for overlap — a label is text on the canvas
    whether or not it is also electrical. Required in the *type* as well as in
    the reader, so a plan built in process cannot be one the schema would refuse.
    """

    net: str
    text: str
    bbox: Box
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0


@dataclass
class LayoutPowerSymbol:
    """A real rail symbol placed on a pin (the connector's own net flag).

    Carries the symbol and its hash like a part: it is a library component, so
    the editor's netlist sees the connection, and a stale glyph is the same
    problem as a stale part.
    """

    symbol_ref: str
    symbol_hash: str = ""
    net: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0


@dataclass
class LayoutText:
    """One piece of text the plan places, **with the box it occupies**.

    ``kind`` is free ("reference" / "value" / "pinName" / "note"); ``part_id``
    ties it to a part when it belongs to one. The box is not optional — not in
    the reader and not here, because 053 sec.2's readability contract measures
    text overlap against it and a box estimated from character count is exactly
    the shortcut 052 sec.7 rules out ("不能只靠字符数估算").
    """

    kind: str
    text: str
    bbox: Box
    part_id: str = ""
    x: float | None = None
    y: float | None = None
    rotation: float = 0.0


@dataclass
class LayoutEvidence:
    """The acceptance slot: what the checker found, or that it has not run.

    Shaped after the checker's declared output (053 sec.2,
    ``{hardViolations, grammarFindings, softMetrics}``) plus a reason per soft
    metric — 052 sec.6: "保留原始指标和具体原因，不能只报 aesthetics=4.2". So a
    metric must have a reason, and a reason must belong to a metric; both are
    checked.
    """

    checker: str = ""
    hard_violations: list[str] = field(default_factory=list)
    grammar_findings: list[str] = field(default_factory=list)
    #: Raw values, never a total. Layered ranking with no cross-layer offset is
    #: the caller's rule (052 sec.6); this slot deliberately has no "score".
    soft_metrics: dict[str, float] = field(default_factory=dict)
    #: metric -> why it is not perfect, in one line.
    soft_reasons: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def checked(self) -> bool:
        """Did anything look at this plan?"""
        return bool(
            self.checker
            or self.hard_violations
            or self.grammar_findings
            or self.soft_metrics
            or self.notes
        )

    @property
    def verdict(self) -> str:
        """Derived: ``not-run`` until something is recorded, then pass/fail."""
        if not self.checked:
            return EVIDENCE_VERDICT_NOT_RUN
        return EVIDENCE_VERDICT_FAIL if self.hard_violations else EVIDENCE_VERDICT_PASS


@dataclass
class LayoutPlan:
    """One compiled drawing, as data."""

    source: LayoutSource = field(default_factory=LayoutSource)
    target: LayoutTarget = field(default_factory=LayoutTarget)
    parts: list[LayoutPart] = field(default_factory=list)
    segments: list[LayoutSegment] = field(default_factory=list)
    junctions: list[LayoutJunction] = field(default_factory=list)
    labels: list[LayoutLabel] = field(default_factory=list)
    power_symbols: list[LayoutPowerSymbol] = field(default_factory=list)
    texts: list[LayoutText] = field(default_factory=list)
    evidence: LayoutEvidence = field(default_factory=LayoutEvidence)
    notes: list[str] = field(default_factory=list)
    plan_version: int = LAYOUT_PLAN_VERSION

    # ------------------------------------------------------------ derived

    def part(self, part_id: str) -> LayoutPart | None:
        """The placement of this spec part, or ``None``."""
        for item in self.parts:
            if item.part_id == part_id:
                return item
        return None

    def all_text_boxes(self) -> list[tuple[str, Box]]:
        """Every text box on the page, labelled, labels included.

        The one reading the readability contract's "文字 bbox 不相交" needs: a
        label is text, so checking the two lists separately would miss the
        collision between them.
        """
        boxes: list[tuple[str, Box]] = [
            (f"texts[{item.kind}]{item.text!r}", item.bbox) for item in self.texts
        ]
        boxes.extend(
            (f"labels[{item.net}]{item.text!r}", item.bbox) for item in self.labels
        )
        return boxes

    def _geometry_payload(self) -> dict[str, Any]:
        """Everything that *is* the layout, in one place.

        Shared by :meth:`geometry_json` and :meth:`to_jsonable` deliberately: the
        digest a preview binds to has to be a digest of the same picture the
        document states, and two copies of this block could drift by one field
        without anything noticing.
        """
        return {
            "source": {
                "circuitSha256": self.source.circuit_sha256,
                "presentationSha256": self.source.presentation_sha256,
            },
            "parts": [
                {
                    "partId": item.part_id,
                    "reference": item.reference,
                    "symbolRef": item.symbol_ref,
                    "symbolHash": item.symbol_hash,
                    "x": item.x,
                    "y": item.y,
                    "rotation": item.rotation,
                    "mirror": item.mirror,
                }
                for item in self.parts
            ],
            "segments": [
                {"net": item.net, "points": [list(point) for point in item.points]}
                for item in self.segments
            ],
            "junctions": [
                {"net": item.net, "x": item.x, "y": item.y} for item in self.junctions
            ],
            "labels": [
                {
                    "net": item.net,
                    "text": item.text,
                    "x": item.x,
                    "y": item.y,
                    "rotation": item.rotation,
                    "bbox": list(item.bbox),
                }
                for item in self.labels
            ],
            "powerSymbols": [
                {
                    "symbolRef": item.symbol_ref,
                    "symbolHash": item.symbol_hash,
                    "net": item.net,
                    "x": item.x,
                    "y": item.y,
                    "rotation": item.rotation,
                }
                for item in self.power_symbols
            ],
            "texts": [
                {
                    "kind": item.kind,
                    "text": item.text,
                    "partId": item.part_id,
                    "x": item.x,
                    "y": item.y,
                    "rotation": item.rotation,
                    "bbox": list(item.bbox),
                }
                for item in self.texts
            ],
        }

    def geometry_json(self) -> str:
        """Canonical JSON of everything that *is* the layout (see `geometry_sha256`)."""
        return json.dumps(
            self._geometry_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def geometry_sha256(self) -> str:
        """The plan's identity as a *picture*, for binding a preview to it.

        052 sec.4: "预览绑定具体计划；实质版式改变 → 旧预览失效重新检查". So the
        digest covers where everything is — the two source hashes, the parts
        (symbol, hash, pose, point, reference), segments, junctions, labels,
        power symbols and text boxes — and **excludes** the evidence, the notes
        and the target. Re-checking a plan does not change the picture, and a
        preview invalidated by its own report would be useless; a page digest
        that changed would only mean the plan needs re-binding, which is the
        target's question and not the geometry's.
        """
        return hashlib.sha256(self.geometry_json().encode("utf-8")).hexdigest()

    # --------------------------------------------------------------- JSON

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "kind": LAYOUT_PLAN_KIND,
            "planVersion": self.plan_version,
            **self._geometry_payload(),
            "target": {
                "projectUuid": self.target.project_uuid,
                "boardUuid": self.target.board_uuid,
                "pageUuid": self.target.page_uuid,
                "hostVersion": self.target.host_version,
                "connectorVersion": self.target.connector_version,
                "snapshotSha256": self.target.snapshot_sha256,
            },
            "evidence": {
                "checker": self.evidence.checker,
                "hardViolations": list(self.evidence.hard_violations),
                "grammarFindings": list(self.evidence.grammar_findings),
                "softMetrics": dict(self.evidence.soft_metrics),
                "softReasons": dict(self.evidence.soft_reasons),
                "notes": list(self.evidence.notes),
            },
            # Derived, written for the consumer that only reads the document.
            # A verdict is not an input: `from_dict` refuses a stated one, so no
            # plan can claim to have passed a check whose findings contradict it.
            "verdict": self.evidence.verdict,
            "geometrySha256": self.geometry_sha256(),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> LayoutPlan:
        """Read a plan and refuse the shapes the checker could not trust."""
        root = _object(payload, "$")
        _check_keys(root, _TOP_KEYS, "$")
        kind = root.get("kind")
        if kind is not None and kind != LAYOUT_PLAN_KIND:
            raise LayoutPlanError(f"$.kind is {kind!r}, expected {LAYOUT_PLAN_KIND!r}")
        version = root.get("planVersion", LAYOUT_PLAN_VERSION)
        if version != LAYOUT_PLAN_VERSION:
            raise LayoutPlanError(
                f"$.planVersion is {version!r}, this build reads "
                f"{LAYOUT_PLAN_VERSION} — recompile the plan"
            )
        source = _source_from(root.get("source"))
        target = _target_from(root.get("target"))
        parts = _parts_from(root.get("parts"))
        plan = cls(
            source=source,
            target=target,
            parts=parts,
            segments=_segments_from(root.get("segments")),
            junctions=_junctions_from(root.get("junctions")),
            labels=_labels_from(root.get("labels")),
            power_symbols=_power_symbols_from(root.get("powerSymbols")),
            texts=_texts_from(root.get("texts")),
            evidence=_evidence_from(root.get("evidence")),
            notes=_text_list(root.get("notes"), "$.notes"),
            plan_version=int(version),
        )
        _check_derived(root, plan)
        return plan

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_jsonable(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> LayoutPlan:
        """Read a plan file. Every failure is a :class:`LayoutPlanError`."""
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise LayoutPlanError(f"{source}: cannot be read ({exc})") from exc
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise LayoutPlanError(f"{source}: is not JSON ({exc})") from exc
        try:
            return cls.from_dict(payload)
        except LayoutPlanError as exc:
            raise LayoutPlanError(f"{source}: {exc}") from exc


# ------------------------------------------------------------------ readers


def _source_from(value: Any) -> LayoutSource:
    body = _object(value, "source")
    _check_keys(body, _SOURCE_KEYS, "source")
    return LayoutSource(
        circuit_sha256=_digest(body.get("circuitSha256"), "source.circuitSha256"),
        presentation_sha256=_digest(
            body.get("presentationSha256"), "source.presentationSha256"
        ),
    )


def _target_from(value: Any) -> LayoutTarget:
    if value is None:
        return LayoutTarget()
    body = _object(value, "target")
    _check_keys(body, _TARGET_KEYS, "target")
    snapshot = body.get("snapshotSha256")
    return LayoutTarget(
        project_uuid=_text(body.get("projectUuid"), "target.projectUuid"),
        board_uuid=_text(body.get("boardUuid"), "target.boardUuid"),
        page_uuid=_text(body.get("pageUuid"), "target.pageUuid"),
        host_version=_text(body.get("hostVersion"), "target.hostVersion"),
        connector_version=_text(body.get("connectorVersion"), "target.connectorVersion"),
        # Absent or empty both mean "not bound to a live page yet" (an offline
        # plan); a value that is there has to be a real digest.
        snapshot_sha256="" if not snapshot else _digest(snapshot, "target.snapshotSha256"),
    )


def _parts_from(value: Any) -> list[LayoutPart]:
    raw = _list(value, "parts")
    if not raw:
        raise LayoutPlanError(
            "$.parts is empty — a plan describes a drawing, and a drawing with no "
            "parts is not a compilation of any circuit"
        )
    out: list[LayoutPart] = []
    seen: dict[str, int] = {}
    references: dict[str, str] = {}
    for index, item in enumerate(raw):
        spot = f"parts[{index}]"
        body = _object(item, spot)
        _check_keys(body, _PART_KEYS, spot)
        part_id = _text(body.get("partId"), f"{spot}.partId", required=True)
        if part_id in seen:
            raise LayoutPlanError(
                f"{spot}.partId is {part_id!r}, already placed at parts[{seen[part_id]}] "
                "— one part lands once"
            )
        seen[part_id] = index
        reference = _text(body.get("reference"), f"{spot}.reference")
        if reference:
            if reference in references:
                raise LayoutPlanError(
                    f"{spot}.reference is {reference!r}, already used by "
                    f"{references[reference]!r} — two parts cannot carry one "
                    "designator on a page"
                )
            references[reference] = part_id
        out.append(LayoutPart(
            part_id=part_id,
            symbol_ref=_text(body.get("symbolRef"), f"{spot}.symbolRef", required=True),
            symbol_hash=_digest(body.get("symbolHash"), f"{spot}.symbolHash"),
            x=_number(body.get("x"), f"{spot}.x"),
            y=_number(body.get("y"), f"{spot}.y"),
            rotation=_pose(body.get("rotation", 0), f"{spot}.rotation"),
            mirror=_boolean(body.get("mirror", False), f"{spot}.mirror"),
            reference=reference,
        ))
    return out


def _segments_from(value: Any) -> list[LayoutSegment]:
    out: list[LayoutSegment] = []
    for index, item in enumerate(_list(value, "segments")):
        spot = f"segments[{index}]"
        body = _object(item, spot)
        _check_keys(body, _SEGMENT_KEYS, spot)
        net = _text(body.get("net"), f"{spot}.net", required=True)
        points = [
            _point(pair, f"{spot}.points[{point_index}]")
            for point_index, pair in enumerate(_list(body.get("points"), f"{spot}.points"))
        ]
        if len(points) < 2:
            raise LayoutPlanError(
                f"{spot} has {len(points)} point(s) — a segment is at least two, or "
                "it draws nothing (and a checker cannot test where a wire ends)"
            )
        for point_index in range(1, len(points)):
            if points[point_index] == points[point_index - 1]:
                raise LayoutPlanError(
                    f"{spot}.points[{point_index}] repeats the previous point "
                    f"({points[point_index][0]:g}, {points[point_index][1]:g}) — a "
                    "zero-length segment is not a wire"
                )
        out.append(LayoutSegment(net=net, points=points))
    return out


def _junctions_from(value: Any) -> list[LayoutJunction]:
    out: list[LayoutJunction] = []
    for index, item in enumerate(_list(value, "junctions")):
        spot = f"junctions[{index}]"
        body = _object(item, spot)
        _check_keys(body, _JUNCTION_KEYS, spot)
        out.append(LayoutJunction(
            net=_text(body.get("net"), f"{spot}.net", required=True),
            x=_number(body.get("x"), f"{spot}.x"),
            y=_number(body.get("y"), f"{spot}.y"),
        ))
    return out


def _labels_from(value: Any) -> list[LayoutLabel]:
    out: list[LayoutLabel] = []
    for index, item in enumerate(_list(value, "labels")):
        spot = f"labels[{index}]"
        body = _object(item, spot)
        _check_keys(body, _LABEL_KEYS, spot)
        out.append(LayoutLabel(
            net=_text(body.get("net"), f"{spot}.net", required=True),
            text=_text(body.get("text"), f"{spot}.text", required=True),
            x=_number(body.get("x"), f"{spot}.x"),
            y=_number(body.get("y"), f"{spot}.y"),
            rotation=_pose(body.get("rotation", 0), f"{spot}.rotation"),
            bbox=_required_box(body.get("bbox"), f"{spot}.bbox"),
        ))
    return out


def _power_symbols_from(value: Any) -> list[LayoutPowerSymbol]:
    out: list[LayoutPowerSymbol] = []
    for index, item in enumerate(_list(value, "powerSymbols")):
        spot = f"powerSymbols[{index}]"
        body = _object(item, spot)
        _check_keys(body, _POWER_KEYS, spot)
        out.append(LayoutPowerSymbol(
            symbol_ref=_text(body.get("symbolRef"), f"{spot}.symbolRef", required=True),
            symbol_hash=_digest(body.get("symbolHash"), f"{spot}.symbolHash"),
            net=_text(body.get("net"), f"{spot}.net", required=True),
            x=_number(body.get("x"), f"{spot}.x"),
            y=_number(body.get("y"), f"{spot}.y"),
            rotation=_pose(body.get("rotation", 0), f"{spot}.rotation"),
        ))
    return out


def _texts_from(value: Any) -> list[LayoutText]:
    out: list[LayoutText] = []
    for index, item in enumerate(_list(value, "texts")):
        spot = f"texts[{index}]"
        body = _object(item, spot)
        _check_keys(body, _TEXT_KEYS, spot)
        x = body.get("x")
        y = body.get("y")
        out.append(LayoutText(
            kind=_text(body.get("kind"), f"{spot}.kind", required=True),
            text=_text(body.get("text"), f"{spot}.text", required=True),
            bbox=_required_box(body.get("bbox"), f"{spot}.bbox"),
            part_id=_text(body.get("partId"), f"{spot}.partId"),
            x=None if x is None else _number(x, f"{spot}.x"),
            y=None if y is None else _number(y, f"{spot}.y"),
            # Typography, not a symbol pose: a text may sit at any angle the
            # drawing wants, so the finite pose set does not apply here.
            rotation=_number(body.get("rotation", 0), f"{spot}.rotation"),
        ))
    return out


def _check_derived(root: dict[str, Any], plan: LayoutPlan) -> None:
    """The two derived fields, checked rather than read.

    `verdict` and `geometrySha256` are computed from the document, and the
    writer emits them for consumers that only read. A stated value that
    disagrees is refused, not ignored: a plan claiming `pass` while carrying
    hard violations is exactly the claim the evidence slot exists to make
    impossible, and a stale geometry digest would let a preview be bound to the
    wrong picture.
    """
    if "verdict" in root:
        stated = root["verdict"]
        if stated != plan.evidence.verdict:
            raise LayoutPlanError(
                f"$.verdict is {stated!r} but this plan's evidence gives "
                f"{plan.evidence.verdict!r} ({len(plan.evidence.hard_violations)} "
                "hard violation(s)) — the verdict is computed from the findings, "
                "not chosen"
            )
    if "geometrySha256" in root:
        stated = root["geometrySha256"]
        computed = plan.geometry_sha256()
        if stated != computed:
            raise LayoutPlanError(
                f"$.geometrySha256 is {stated!r} but this plan's geometry hashes to "
                f"{computed!r} — a preview bound to the stated value would not be "
                "bound to this picture (052 sec.4)"
            )


def _evidence_from(value: Any) -> LayoutEvidence:
    if value is None:
        return LayoutEvidence()
    body = _object(value, "evidence")
    _check_keys(body, _EVIDENCE_KEYS, "evidence")
    metrics: dict[str, float] = {}
    raw_metrics = body.get("softMetrics")
    if raw_metrics is not None:
        for key, item in _object(raw_metrics, "evidence.softMetrics").items():
            metrics[str(key)] = _number(item, f"evidence.softMetrics.{key}")
    reasons: dict[str, str] = {}
    raw_reasons = body.get("softReasons")
    if raw_reasons is not None:
        for key, item in _object(raw_reasons, "evidence.softReasons").items():
            if str(key) not in metrics:
                raise LayoutPlanError(
                    f"evidence.softReasons.{key} gives a reason for a metric that "
                    "is not in evidence.softMetrics — 052 sec.6 keeps the raw value "
                    "*and* the reason, and a reason without a value is neither"
                )
            reasons[str(key)] = _text(item, f"evidence.softReasons.{key}", required=True)
    return LayoutEvidence(
        checker=_text(body.get("checker"), "evidence.checker"),
        hard_violations=_text_list(body.get("hardViolations"), "evidence.hardViolations"),
        grammar_findings=_text_list(
            body.get("grammarFindings"), "evidence.grammarFindings"
        ),
        soft_metrics=metrics,
        soft_reasons=reasons,
        notes=_text_list(body.get("notes"), "evidence.notes"),
    )


# ------------------------------------------------------------------ helpers


def _required_box(value: Any, where: str) -> Box:
    """A text box that must be there: 053 sec.2, "每段文字的 bbox"."""
    box = check_box(value, where, LayoutPlanError)
    if box is None:
        raise LayoutPlanError(
            f"{where} is missing — every piece of text carries the box it occupies, "
            "because the readability contract measures overlap against it and a box "
            "estimated from the character count is the shortcut 052 sec.7 rules out"
        )
    return box


def _digest(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise LayoutPlanError(
            f"{where} must be 64 hex characters (a sha256), got {value!r}"
        )
    return value


def _point(value: Any, where: str) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) < 2
        or any(isinstance(item, bool) or not isinstance(item, (int, float))
               for item in value[:2])
    ):
        raise LayoutPlanError(f"{where} must be [x, y] in canvas units, got {value!r}")
    return (float(value[0]), float(value[1]))


def _number(value: Any, where: str) -> float:
    if value is None:
        raise LayoutPlanError(
            f"{where} is required — a plan is a record of where everything is"
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LayoutPlanError(
            f"{where} must be a number in canvas units, got {value!r}"
        )
    return float(value)


def _pose(value: Any, where: str) -> float:
    """A pose rotation: one of the finite set the symbols are drawn in."""
    number = _number(value, where)
    if number not in POSE_ROTATIONS:
        raise LayoutPlanError(
            f"{where} is {value!r}; expected one of "
            f"{', '.join(str(item) for item in POSE_ROTATIONS)} degrees — the "
            "finite legal pose set (052 sec.6), and a pose outside it is one no "
            "SymbolProfile can allow"
        )
    return number


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise LayoutPlanError(f"{where} must be a boolean, got {value!r}")
    return value


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LayoutPlanError(
            f"{where} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LayoutPlanError(f"$.{where} must be a list, got {value!r}")
    return value


def _text(value: Any, where: str, required: bool = False) -> str:
    if value is None:
        if required:
            raise LayoutPlanError(f"{where} is required and missing")
        return ""
    if not isinstance(value, str):
        raise LayoutPlanError(f"{where} must be a string, got {value!r}")
    if required and not value.strip():
        raise LayoutPlanError(f"{where} is empty")
    return value.strip()


def _text_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise LayoutPlanError(f"{where} must be a list of strings, got {value!r}")
    return list(value)


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise LayoutPlanError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(allowed)} — the schema is closed on purpose: a key this "
            "build does not read would otherwise be geometry nobody draws"
        )

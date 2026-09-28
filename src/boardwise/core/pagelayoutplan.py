"""PageLayoutPlan: the page the tool computed, as data (056 sec.6's increment).

053's :class:`~boardwise.core.layoutplan.LayoutPlan` is one drawing. 056 asks for
the layer above it: a **page** made of several module drawings, placed, and
connected across their boundaries. That page needs to say four things a single
plan cannot, and this module is where they are written:

* **which module owns which parts**, and which grammar drew it. The module split
  is an input (it comes from `PresentationSpec.modules`) but the *page document*
  has to carry it, because the page is what a consumer lands: a reader of the
  file must be able to say "this frame is the regulator group, and the two parts
  inside it are its own";
* **where each module's frame ended up** — ``origin`` (the translation applied to
  the module-local plan) and ``frame`` (the box the module's own drawing occupies
  once placed, its annotations included). The frame is what a page-level keep-out
  or a user lock has to be tested against (057), and it is the rigid body the
  placement treated it as;
* **the ports**: for every shared net, the point inside the module at which the
  module states that net to the page — a label, a flag, or one end of a whole
  cross-module wire — and which module it connects to. This is 057's G4 ground:
  the *same-name* label is how two module drawings become one net in an editor
  whose netlist is project-level (054 C7's measured behaviour), and the port
  table is the page's own record of where each of those names sits;
* **the flow the page was placed under** (the presentation's module-level flow,
  normalised), so a reviewer can see the reading order the ranking was measured
  against rather than having to re-derive it from coordinates.

**The drawing itself is not re-specified here.** ``plan`` is a plain
:class:`LayoutPlan` — the merged page drawing, in exactly the 053 schema, which is
what makes it landable by the existing `draw apply` path without a second
plan dialect. Its ``evidence`` slot carries the nine readability constraints'
verdict on the *merged* drawing; the page-level domain (056 sec.3: frames apart,
no wire through a frame, one expression per shared net, …) lives in its own
``pageEvidence`` slot with its own checker name, because the two vocabularies
answer different questions and merging them would make "which layer refused"
unanswerable.

**Two derived fields, written and checked**: ``verdict`` (fail if either evidence
carries a hard violation, ``not-run`` when neither has been filled) and
``geometrySha256``. The digest covers the page's own facts (the module frames,
origins, ports, the flow, the page box) **plus the merged plan's geometry
digest** — the page picture is those two things, and a digest over one of them
would let a preview be bound to a page whose drawing had moved.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .layoutplan import (
    EVIDENCE_VERDICT_FAIL,
    EVIDENCE_VERDICT_NOT_RUN,
    EVIDENCE_VERDICT_PASS,
    LAYOUT_PLAN_KIND,
    LayoutEvidence,
    LayoutPlan,
)
from .presentationspec import FlowEdge
from .symbolprofile import Box, check_box

__all__ = [
    "PAGE_LAYOUT_PLAN_KIND",
    "PAGE_LAYOUT_PLAN_VERSION",
    "PAGE_PORT_FLAG",
    "PAGE_PORT_KINDS",
    "PAGE_PORT_LABEL",
    "PAGE_PORT_WIRE",
    "PageLayoutPlan",
    "PageLayoutPlanError",
    "PageModule",
    "PagePort",
]

#: Identifies the document; see `circuitspec.CIRCUIT_SPEC_KIND` for the rule.
PAGE_LAYOUT_PLAN_KIND = "boardwise-page-layout-plan"

#: Same rule as `changeplan.PLAN_VERSION`: a document from a future build is
#: refused rather than half-understood.
PAGE_LAYOUT_PLAN_VERSION = 1

#: How a port states its net to the page. ``label`` is a net label at the point,
#: ``flag`` a rail/ground symbol, ``wire`` one end of a whole cross-module wire
#: (056 sec.2's `main-path` exception: the connection *is* the drawing).
PAGE_PORT_LABEL = "label"
PAGE_PORT_FLAG = "flag"
PAGE_PORT_WIRE = "wire"
PAGE_PORT_KINDS: tuple[str, ...] = (PAGE_PORT_LABEL, PAGE_PORT_FLAG, PAGE_PORT_WIRE)

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

_TOP_KEYS = (
    "kind",
    "planVersion",
    "source",
    "pageBox",
    "flow",
    "modules",
    "plan",
    "pageEvidence",
    "notes",
    # Derived, written for the consumer that only reads, and checked on the way
    # back in (see `_check_derived`).
    "verdict",
    "geometrySha256",
)
_SOURCE_KEYS = ("circuitSha256", "presentationSha256")
_MODULE_KEYS = (
    "id",
    "grammarRef",
    "parts",
    "origin",
    "frame",
    "internalGeometrySha256",
    "ports",
)
_PORT_KEYS = ("module", "net", "kind", "x", "y", "partner")
_FLOW_KEYS = ("from", "to", "mainPath")
_EVIDENCE_KEYS = (
    "checker",
    "hardViolations",
    "grammarFindings",
    "softMetrics",
    "softReasons",
    "notes",
)


class PageLayoutPlanError(ValueError):
    """The page document is not one this build can read."""


@dataclass
class PagePort:
    """One point at which a module states a shared net to the page.

    ``x``/``y`` are page coordinates of the *anchor* — the electrical fact: a
    label's anchor joins the node it touches, and a flag or a wire end is a
    conductor at that point. ``partner`` names the module on the other side of
    the connection (empty when the page did not connect this net onward), and
    ``kind`` is one of :data:`PAGE_PORT_KINDS`.
    """

    module: str
    net: str
    kind: str = PAGE_PORT_LABEL
    x: float = 0.0
    y: float = 0.0
    partner: str = ""


@dataclass
class PageModule:
    """One module as it ended up on the page: its frame, its origin, its ports.

    ``origin`` is the translation the page applied to the module-local plan
    (the plan itself is not stored: the module was compiled as a call, and what
    the page keeps is where it landed and the digest of the local drawing it
    came from). ``frame`` is the box the module occupies — its own annotation
    allowance included — and it is a *stated* fact, which the page checker
    verifies against the geometry rather than assuming.
    """

    id: str
    grammar_ref: str = ""
    parts: list[str] = field(default_factory=list)
    origin: tuple[float, float] = (0.0, 0.0)
    frame: Box = (0.0, 0.0, 0.0, 0.0)
    internal_geometry_sha256: str = ""
    ports: list[PagePort] = field(default_factory=list)

    def port(self, net: str) -> PagePort | None:
        """The port at which this module states `net`, or ``None``."""
        for item in self.ports:
            if item.net == net:
                return item
        return None


@dataclass
class PageLayoutPlan:
    """One compiled page: the merged drawing, the modules, the ports, the flow.

    ``source`` is not stored twice: the page's two input digests are the merged
    plan's own (``plan.source``), and `from_dict` refuses a document whose stated
    source disagrees with them.
    """

    plan: LayoutPlan = field(default_factory=LayoutPlan)
    modules: list[PageModule] = field(default_factory=list)
    flow: list[FlowEdge] = field(default_factory=list)
    page_box: Box | None = None
    page_evidence: LayoutEvidence = field(default_factory=LayoutEvidence)
    notes: list[str] = field(default_factory=list)
    plan_version: int = PAGE_LAYOUT_PLAN_VERSION

    # ------------------------------------------------------------ derived

    def module(self, module_id: str) -> PageModule | None:
        """The placed module with this id, or ``None``."""
        for item in self.modules:
            if item.id == module_id:
                return item
        return None

    def port_kinds(self) -> dict[str, set[str]]:
        """``net -> the kinds the page states it with`` — the consistency check's view."""
        out: dict[str, set[str]] = {}
        for module in self.modules:
            for port in module.ports:
                out.setdefault(port.net, set()).add(port.kind)
        return out

    @property
    def verdict(self) -> str:
        """Fail if either layer recorded a hard violation, else pass/not-run.

        Two evidence slots, one verdict: a plan whose *drawing* is clean but
        whose page domain is not is not a page a caller may land, so the
        document cannot report `pass` by looking at one slot (052 sec.8's point,
        applied to the page).
        """
        violations = (
            len(self.plan.evidence.hard_violations)
            + len(self.page_evidence.hard_violations)
        )
        if violations:
            return EVIDENCE_VERDICT_FAIL
        if not (self.plan.evidence.checked or self.page_evidence.checked):
            return EVIDENCE_VERDICT_NOT_RUN
        return EVIDENCE_VERDICT_PASS

    def _page_payload(self) -> dict[str, Any]:
        """Everything that *is* the page, in one place (see `page_geometry_sha256`).

        The flow is deliberately **not** here: it is an input (the presentation
        spec's own digest already covers it) and a reading order the placement
        respected, not something the page draws. Two pages with the same frames and
        the same ports are the same page picture even if the document repeats a
        different flow.
        """
        return {
            "source": {
                "circuitSha256": self.plan.source.circuit_sha256,
                "presentationSha256": self.plan.source.presentation_sha256,
            },
            "pageBox": None if self.page_box is None else list(self.page_box),
            "modules": [
                {
                    "id": module.id,
                    "grammarRef": module.grammar_ref,
                    "parts": list(module.parts),
                    "origin": list(module.origin),
                    "frame": list(module.frame),
                    "internalGeometrySha256": module.internal_geometry_sha256,
                    "ports": [
                        {
                            "module": port.module,
                            "net": port.net,
                            "kind": port.kind,
                            "x": port.x,
                            "y": port.y,
                            "partner": port.partner,
                        }
                        for port in module.ports
                    ],
                }
                for module in self.modules
            ],
            # The page picture is the module placement *and* the drawing: the
            # drawing's own digest is what binds the two, and re-running the
            # checkers does not move it.
            "planGeometrySha256": self.plan.geometry_sha256(),
        }

    def page_geometry_json(self) -> str:
        """Canonical JSON of everything that *is* the page."""
        return json.dumps(
            self._page_payload(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        )

    def page_geometry_sha256(self) -> str:
        """The page's identity as a picture — what a page preview binds to."""
        return hashlib.sha256(self.page_geometry_json().encode("utf-8")).hexdigest()

    # --------------------------------------------------------------- JSON

    def to_jsonable(self) -> dict[str, Any]:
        payload = self._page_payload()
        # `planGeometrySha256` is the digest's binding, not a key of the document:
        # the merged plan is written out in full under `plan`, and a second copy of
        # its hash would be a value a reader could believe instead of recompute.
        payload.pop("planGeometrySha256", None)
        return {
            "kind": PAGE_LAYOUT_PLAN_KIND,
            "planVersion": self.plan_version,
            **payload,
            "flow": [
                {
                    "from": edge.from_module,
                    "to": edge.to_module,
                    "mainPath": edge.main_path,
                }
                for edge in self.flow
            ],
            "plan": self.plan.to_jsonable(),
            "pageEvidence": {
                "checker": self.page_evidence.checker,
                "hardViolations": list(self.page_evidence.hard_violations),
                "grammarFindings": list(self.page_evidence.grammar_findings),
                "softMetrics": dict(self.page_evidence.soft_metrics),
                "softReasons": dict(self.page_evidence.soft_reasons),
                "notes": list(self.page_evidence.notes),
            },
            "verdict": self.verdict,
            "geometrySha256": self.page_geometry_sha256(),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> PageLayoutPlan:
        root = _object(payload, "$")
        _check_keys(root, _TOP_KEYS, "$")
        kind = root.get("kind")
        if kind is not None and kind != PAGE_LAYOUT_PLAN_KIND:
            raise PageLayoutPlanError(
                f"$.kind is {kind!r}, expected {PAGE_LAYOUT_PLAN_KIND!r}"
            )
        version = root.get("planVersion", PAGE_LAYOUT_PLAN_VERSION)
        if version != PAGE_LAYOUT_PLAN_VERSION:
            raise PageLayoutPlanError(
                f"$.planVersion is {version!r}, this build reads "
                f"{PAGE_LAYOUT_PLAN_VERSION} — recompile the page"
            )
        source = _object(root.get("source"), "source")
        _check_keys(source, _SOURCE_KEYS, "source")
        modules = _modules_from(root.get("modules"))
        plan = _plan_from(root.get("plan"))
        page = cls(
            plan=plan,
            modules=modules,
            flow=_flow_from(root.get("flow"), {module.id for module in modules}),
            page_box=_box_or_none(root.get("pageBox"), "$.pageBox"),
            page_evidence=_evidence_from(root.get("pageEvidence")),
            notes=_text_list(root.get("notes"), "$.notes"),
            plan_version=int(version),
        )
        if plan.source.circuit_sha256 != _digest(
            source.get("circuitSha256"), "source.circuitSha256"
        ) or plan.source.presentation_sha256 != _digest(
            source.get("presentationSha256"), "source.presentationSha256"
        ):
            raise PageLayoutPlanError(
                "$.source is not the merged plan's own source — the page and the "
                "drawing it places would then be two documents about two circuits, "
                "and nothing downstream could tell which one a consumer believed"
            )
        _check_derived(root, page)
        return page

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_jsonable(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> PageLayoutPlan:
        """Read a page document. Every failure is a :class:`PageLayoutPlanError`."""
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise PageLayoutPlanError(f"{source}: cannot be read ({exc})") from exc
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise PageLayoutPlanError(f"{source}: is not JSON ({exc})") from exc
        try:
            return cls.from_dict(payload)
        except PageLayoutPlanError as exc:
            raise PageLayoutPlanError(f"{source}: {exc}") from exc


# ------------------------------------------------------------------ readers


def _modules_from(value: Any) -> list[PageModule]:
    raw = _list(value, "modules")
    if not raw:
        raise PageLayoutPlanError(
            "$.modules is empty — a page with no module is not a page, and the "
            "layer above the single-module compiler exists precisely to say which "
            "groups are on it"
        )
    out: list[PageModule] = []
    seen: set[str] = set()
    claimed: dict[str, str] = {}
    for index, item in enumerate(raw):
        spot = f"modules[{index}]"
        body = _object(item, spot)
        _check_keys(body, _MODULE_KEYS, spot)
        module_id = _text(body.get("id"), f"{spot}.id", required=True)
        if module_id in seen:
            raise PageLayoutPlanError(
                f"{spot}.id is {module_id!r}, already used — one id is one module"
            )
        seen.add(module_id)
        parts = _text_list(body.get("parts"), f"{spot}.parts")
        if not parts:
            raise PageLayoutPlanError(f"{spot}.parts is empty")
        for part_id in parts:
            if part_id in claimed:
                raise PageLayoutPlanError(
                    f"{spot}.parts names {part_id!r}, already placed inside "
                    f"{claimed[part_id]!r} — a part belongs to one module on the "
                    "page, and two frames claiming it would draw it twice"
                )
            claimed[part_id] = module_id
        out.append(PageModule(
            id=module_id,
            grammar_ref=_text(body.get("grammarRef"), f"{spot}.grammarRef"),
            parts=parts,
            origin=_point(body.get("origin"), f"{spot}.origin"),
            frame=_box(body.get("frame"), f"{spot}.frame"),
            internal_geometry_sha256=_digest(
                body.get("internalGeometrySha256"), f"{spot}.internalGeometrySha256"
            ),
            ports=_ports_from(body.get("ports"), f"{spot}.ports", module_id),
        ))
    ids = {module.id for module in out}
    for module in out:
        for port in module.ports:
            if port.partner and port.partner not in ids:
                raise PageLayoutPlanError(
                    f"modules[{module.id}].ports[{port.net}].partner is "
                    f"{port.partner!r}, which is not a module of this page"
                )
    return out


def _ports_from(value: Any, where: str, module_id: str) -> list[PagePort]:
    out: list[PagePort] = []
    seen: set[str] = set()
    for index, item in enumerate(_list(value, where)):
        spot = f"{where}[{index}]"
        body = _object(item, spot)
        _check_keys(body, _PORT_KEYS, spot)
        net = _text(body.get("net"), f"{spot}.net", required=True)
        if net in seen:
            raise PageLayoutPlanError(
                f"{spot}.net is {net!r}, already a port of this module — one net "
                "is stated to the page once per module (a second statement is the "
                "wire-and-label mix the page domain refuses)"
            )
        seen.add(net)
        kind = _text(body.get("kind"), f"{spot}.kind", required=True)
        if kind not in PAGE_PORT_KINDS:
            raise PageLayoutPlanError(
                f"{spot}.kind is {kind!r}; expected one of "
                f"{', '.join(PAGE_PORT_KINDS)}"
            )
        owner = _text(body.get("module"), f"{spot}.module") or module_id
        if owner != module_id:
            raise PageLayoutPlanError(
                f"{spot}.module is {owner!r} but the port sits under "
                f"{module_id!r} — the port is a fact about the module that states "
                "the net, so the two have to agree"
            )
        out.append(PagePort(
            module=owner,
            net=net,
            kind=kind,
            x=_number(body.get("x"), f"{spot}.x"),
            y=_number(body.get("y"), f"{spot}.y"),
            partner=_text(body.get("partner"), f"{spot}.partner"),
        ))
    return out


def _flow_from(value: Any, module_ids: set[str]) -> list[FlowEdge]:
    out: list[FlowEdge] = []
    for index, item in enumerate(_list(value, "flow")):
        spot = f"flow[{index}]"
        body = _object(item, spot)
        _check_keys(body, _FLOW_KEYS, spot)
        edge = FlowEdge(
            from_module=_text(body.get("from"), f"{spot}.from", required=True),
            to_module=_text(body.get("to"), f"{spot}.to", required=True),
            main_path=_boolean(body.get("mainPath", False), f"{spot}.mainPath"),
        )
        for name in (edge.from_module, edge.to_module):
            if name not in module_ids:
                raise PageLayoutPlanError(
                    f"{spot} names module {name!r}, which this page does not place "
                    f"({', '.join(sorted(module_ids))})"
                )
        out.append(edge)
    return out


def _plan_from(value: Any) -> LayoutPlan:
    """The merged drawing, read by the 053 schema's own reader.

    Read through :meth:`LayoutPlan.from_dict` rather than re-implemented: the page
    document may not be a second dialect of a plan, and the schema's own
    refusals (a stated verdict its findings contradict, a stale geometry digest)
    have to fire here too.
    """
    if not isinstance(value, dict) or value.get("kind", LAYOUT_PLAN_KIND) != LAYOUT_PLAN_KIND:
        raise PageLayoutPlanError(
            "$.plan must be a "
            f"{LAYOUT_PLAN_KIND!r} document — the page places a plan, it does not "
            "restate the drawing in its own shape"
        )
    try:
        return LayoutPlan.from_dict(value)
    except Exception as exc:  # LayoutPlanError, re-labelled with the path
        raise PageLayoutPlanError(f"$.plan: {exc}") from exc


def _evidence_from(value: Any) -> LayoutEvidence:
    if value is None:
        return LayoutEvidence()
    body = _object(value, "pageEvidence")
    _check_keys(body, _EVIDENCE_KEYS, "pageEvidence")
    metrics: dict[str, float] = {}
    raw_metrics = body.get("softMetrics")
    if raw_metrics is not None:
        for key, item in _object(raw_metrics, "pageEvidence.softMetrics").items():
            metrics[str(key)] = _number(item, f"pageEvidence.softMetrics.{key}")
    reasons: dict[str, str] = {}
    raw_reasons = body.get("softReasons")
    if raw_reasons is not None:
        for key, item in _object(raw_reasons, "pageEvidence.softReasons").items():
            if str(key) not in metrics:
                raise PageLayoutPlanError(
                    f"pageEvidence.softReasons.{key} gives a reason for a metric "
                    "that is not in pageEvidence.softMetrics"
                )
            reasons[str(key)] = _text(
                item, f"pageEvidence.softReasons.{key}", required=True
            )
    return LayoutEvidence(
        checker=_text(body.get("checker"), "pageEvidence.checker"),
        hard_violations=_text_list(
            body.get("hardViolations"), "pageEvidence.hardViolations"
        ),
        grammar_findings=_text_list(
            body.get("grammarFindings"), "pageEvidence.grammarFindings"
        ),
        soft_metrics=metrics,
        soft_reasons=reasons,
        notes=_text_list(body.get("notes"), "pageEvidence.notes"),
    )


def _check_derived(root: dict[str, Any], page: PageLayoutPlan) -> None:
    """`verdict` and `geometrySha256` are computed from the document, never read.

    The same rule `layoutplan._check_derived` applies, for the same reason: a page
    claiming `pass` while a layer recorded a violation is exactly the claim the
    two evidence slots exist to make impossible, and a stale page digest would
    let a preview be bound to the wrong page.
    """
    if "verdict" in root:
        stated = root["verdict"]
        if stated != page.verdict:
            raise PageLayoutPlanError(
                f"$.verdict is {stated!r} but this page's evidence gives "
                f"{page.verdict!r} ({len(page.plan.evidence.hard_violations)} "
                "drawing violation(s), "
                f"{len(page.page_evidence.hard_violations)} page violation(s)) — "
                "the verdict is computed from the findings, not chosen"
            )
    if "geometrySha256" in root:
        stated = root["geometrySha256"]
        computed = page.page_geometry_sha256()
        if stated != computed:
            raise PageLayoutPlanError(
                f"$.geometrySha256 is {stated!r} but this page hashes to "
                f"{computed!r} — a preview bound to the stated value would not be "
                "bound to this page"
            )


# ------------------------------------------------------------------ helpers


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PageLayoutPlanError(
            f"{where} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PageLayoutPlanError(f"$.{where} must be a list, got {value!r}")
    return value


def _text(value: Any, where: str, required: bool = False) -> str:
    if value is None:
        if required:
            raise PageLayoutPlanError(f"{where} is required and missing")
        return ""
    if not isinstance(value, str):
        raise PageLayoutPlanError(f"{where} must be a string, got {value!r}")
    if required and not value.strip():
        raise PageLayoutPlanError(f"{where} is empty")
    return value.strip()


def _text_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PageLayoutPlanError(f"{where} must be a list of strings, got {value!r}")
    return list(value)


def _number(value: Any, where: str) -> float:
    if value is None:
        raise PageLayoutPlanError(
            f"{where} is required — a page is a record of where everything is"
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PageLayoutPlanError(
            f"{where} must be a number in canvas units, got {value!r}"
        )
    return float(value)


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise PageLayoutPlanError(f"{where} must be a boolean, got {value!r}")
    return value


def _digest(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise PageLayoutPlanError(
            f"{where} must be 64 hex characters (a sha256), got {value!r}"
        )
    return value


def _box(value: Any, where: str) -> Box:
    box = check_box(value, where, PageLayoutPlanError)
    if box is None:
        raise PageLayoutPlanError(
            f"{where} is required — a module frame is the box the module occupies, "
            "and a frame the page does not state is one nothing can test against"
        )
    return box


def _box_or_none(value: Any, where: str) -> Box | None:
    return check_box(value, where, PageLayoutPlanError)


def _point(value: Any, where: str) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) < 2
        or any(isinstance(item, bool) or not isinstance(item, (int, float))
               for item in value[:2])
    ):
        raise PageLayoutPlanError(f"{where} must be [x, y] in canvas units, got {value!r}")
    return (float(value[0]), float(value[1]))


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise PageLayoutPlanError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(allowed)} — the schema is closed on purpose: a key this "
            "build does not read would otherwise be page geometry nobody draws"
        )

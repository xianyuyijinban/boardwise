"""PresentationSpec: how a circuit should **read** (053 stage A, 052 sec.4).

The second contract. The same netlist has many electrically equivalent drawings,
and this is the one that says which expression the author wants: which parts
form a module, which chain is the main path, which ports the circuit exposes,
which drawing grammar applies, where labels are allowed instead of wires, and
where the engineer has already decided a part's place.

Two properties are enforced here rather than trusted:

* **The model entry point does not accept coordinates.** The only place a
  coordinate may appear in this document is :attr:`PresentationSpec.user_locks`
  (an engineer's decision). Anywhere else — a `parts` entry carrying an `x`, a
  `wirePoints` list, a connector action — is refused by :func:`_refuse_coordinates`
  **before** anything is parsed, so the answer is a refusal and not a silent
  clean-up (052 sec.4: "默认模型入口不接受原始坐标、wire points 和 connector
  动作；工程师显式锁定或手工编辑仍有合法入口").
* **The label policy's hard-coded half.** 053 sec.7: "标签策略硬编码：局部直连
  义务优先，跨模块/高扇出才许标签". So `local` may only be `wire`; the two
  outer cases may be `wire` (a stricter choice) or `label`.

**A module is a group on a page, and a page holds several of them.** The module
list is not decoration: the phase-C page compiler (056) compiles *each module on
its own* — as a call to the single-module pipeline — and places the resulting
frames on the page. So a module may state the two things that are true of one
group and not of the page:

* `grammar_ref` — which drawing grammar the module follows. A single-grammar
  page states it once at the top; a page that mixes an LDO with a divider states
  it per module, and a module that states none inherits the document's.
* `presentation` — the module's own overrides, of which this build reads
  `sidePreferences`: the sides a grammar should read along are a property of the
  *symbols in that group* (the repo's measured AMS1117 puts its input and output
  on the same side), and one page can hold a group whose symbols want the
  default sides and one whose symbols do not.

`flow` is the module-level main-flow partial order — "this group feeds that
one". It is a **soft** reading aid and never a hard constraint: the page
compiler places modules in an order that respects it, and a diagram that
contradicts it is a ranking loss rather than a refusal. The two forms are the
plain pair (``["pwr", "sense"]``) and the object
(``{"from": "pwr", "to": "sense", "mainPath": true}``); `mainPath` marks the
edge the reader is meant to follow, which is the one edge the page may draw as a
*whole wire* across the module boundary instead of naming it at both ends.

What this module deliberately does **not** check: that `modules[*].parts`,
`flow` endpoints, `mainPaths` steps and `userLocks[*].partId` name parts and
modules that exist. Those are CircuitSpec facts (and module-name facts), and the
cross-check belongs to whoever holds both documents — the phase-B compiler and,
for modules, the page compiler. Validating them here would either duplicate the
circuit schema in this file or accept a document that silently refers to nothing.

**Serialisation stays byte-stable for a document that says nothing new.** The
`grammarRef` / `presentation` / `branchOrder` keys of a module and the top-level
`flow` list are written **only when stated**, because a LayoutPlan's geometry
digest pins the presentation digest: an untouched 053 spec has to hash — and
therefore compile — to exactly the plan it did before this batch. The fields are
additions, not changes: absent reads as "this module inherits" (or, for the
order, "no order stated"), and a page that declares no flow is the page whose
modules are read in name order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .circuitspec import PORT_DIRECTIONS
from .symbolprofile import POSE_ROTATIONS

__all__ = [
    "DEFAULT_SIDE_PREFERENCES",
    "GRAMMARS",
    "LABEL_LABEL",
    "LABEL_MODES",
    "LABEL_WIRE",
    "LOCK_SCOPES",
    "LOCK_SCOPE_MODULE",
    "LOCK_SCOPE_PAGE",
    "MODULE_PRESENTATION_KEYS",
    "PATH_STEP_NET",
    "PATH_STEP_PART",
    "PRESENTATION_SPEC_KIND",
    "PRESENTATION_SPEC_VERSION",
    "SIDES",
    "_FLOW_EDGE_KEYS",
    "DirectWiringObligation",
    "FlowEdge",
    "LabelPolicy",
    "PresentationModule",
    "PresentationPath",
    "PresentationSpec",
    "PresentationSpecError",
    "UserLock",
    "main_path_wire",
    "presentation_sha256",
]

#: Identifies the document; see `circuitspec.CIRCUIT_SPEC_KIND` for the rule.
PRESENTATION_SPEC_KIND = "boardwise-presentation-spec"

#: Same rule as `changeplan.PLAN_VERSION`: a stated version this build does not
#: have is refused rather than guessed at.
PRESENTATION_SPEC_VERSION = 1

#: The drawing grammars this build knows (053 sec.2 — "本批只认这三个字面量", 088
#: adds the fourth, `power-entry`, and 098 the fifth, `ic-periphery`). Empty means
#: the spec does not choose one; a literal that is not in this tuple is a refusal,
#: not a fallback to a generic layout: a grammar is a set of promises about what
#: will be visible, and pretending to keep promises nobody wrote is worse than
#: saying the grammar is not known.
GRAMMARS: tuple[str, ...] = (
    "voltage-divider", "rc-lowpass", "ldo", "power-entry", "ic-periphery",
)

#: How a net may be expressed locally (052 sec.5: a key local topology is drawn
#: as wire; a label across modules or at high fan-out).
LABEL_WIRE = "wire"
LABEL_LABEL = "label"
LABEL_MODES: tuple[str, ...] = (LABEL_WIRE, LABEL_LABEL)

#: The four sides a preference may name. Preferences are defaults; a user lock
#: wins over them (053 sec.2: "默认可被锁定覆盖").
SIDES: tuple[str, ...] = ("left", "right", "top", "bottom")

#: The book's defaults: an input enters from the left, an output leaves to the
#: right, a rail is above and ground below. Defaults, not rules — 052 sec.6 says
#: outright that "all signals left to right" is not a global law.
DEFAULT_SIDE_PREFERENCES: dict[str, str] = {
    "input": "left",
    "output": "right",
    "power": "top",
    "gnd": "bottom",
}

#: A path step names what it is: a chain mixes parts and nets, and an untyped
#: string would leave the reader guessing which of the two an id is.
PATH_STEP_PART = "part:"
PATH_STEP_NET = "net:"

_TOP_KEYS = (
    "kind",
    "specVersion",
    "modules",
    "flow",
    "mainPaths",
    "feedbackPaths",
    "portRoles",
    "grammarRef",
    "directWiringObligations",
    "labelPolicy",
    "sidePreferences",
    "userLocks",
)
_MODULE_KEYS = (
    "id", "parts", "role", "grammarRef", "presentation", "branchOrder", "core",
)
#: What a module's own `presentation` object may override. Closed for the same
#: reason every schema here is closed: a key this build does not read would be
#: an intent nobody honours. The side preferences are the ones a *group's
#: symbols* decide; `userLocks` and the label policy are page-wide facts.
MODULE_PRESENTATION_KEYS = ("sidePreferences",)
_PATH_KEYS = ("id", "chain", "note")
_FLOW_EDGE_KEYS = ("from", "to", "mainPath")
_OBLIGATION_KEYS = ("nets", "note")
_LABEL_POLICY_KEYS = ("local", "crossModule", "highFanout")
_LOCK_KEYS = ("partId", "x", "y", "rotation", "scope")

#: What a lock's coordinates are relative to (057 sec.3). ``module`` — the
#: default, and the only reading before 057 — is the module's own drawing: the
#: page translates the lock with its module. ``page`` pins the part to a point
#: of the *page*: the page compiler derives the module's origin from it.
LOCK_SCOPE_MODULE = "module"
LOCK_SCOPE_PAGE = "page"
LOCK_SCOPES: tuple[str, ...] = (LOCK_SCOPE_MODULE, LOCK_SCOPE_PAGE)

#: Keys that mean "a place on the canvas" — refused everywhere except inside a
#: `userLocks` entry (052 sec.4).
_COORDINATE_KEYS = frozenset({
    "x", "y", "rotation", "angle", "mirror", "isMirror", "dx", "dy",
    "x1", "y1", "x2", "y2",
    "points", "point", "wirePoints", "polyline", "waypoints", "route",
    "segments", "junctions", "bbox", "at", "anchor",
    "connectorAction", "connectorActions", "actions", "primitiveId",
})


class PresentationSpecError(ValueError):
    """The presentation spec is not one this build can read."""


@dataclass
class PresentationModule:
    """One functional group: its parts, what the group is for, and how it draws.

    The module is what makes "电容归侧" decidable — a decoupling capacitor and
    the IC it belongs to are one group, and a group has one place on the page.
    It is also the unit the page compiler (056) compiles: each module goes
    through the single-module pipeline on its own, so the two fields below are
    *this group's* answers rather than the page's.

    ``grammar_ref`` empty means "the document's grammar"; ``side_preferences``
    empty means "the document's sides". Both are overrides, and both are
    per-group because both are properties of the symbols in the group (053
    sec.3's measured AMS1117 needs a non-default output side; a divider's
    default sides are fine) rather than of the page they sit on.

    ``branch_order`` is the group's own statement of the order its parallel
    branches are drawn in, **from the inlet end outwards** — 088b §二, 岳
    2026-10-02: a TVS belongs nearest the inlet so a spike is clamped before it
    reaches anything else, and *which* part is the TVS is a fact about values and
    packages, which no grammar may read (053 sec.6). So the order is declared
    here and the grammar only carries it out (see `power_entry`): the document
    states the intent, the grammar keeps the evidence. Empty means "no order
    stated" — the drawing then keeps 088's designator order, and a document that
    states nothing serialises exactly as it did before this field existed.

    ``core`` is the group's own statement of **which part the drawing is arranged
    around** (098 §一) — the one fact a grammar cannot derive from the partition,
    because every part of a module is a shape with pins and nothing about the
    connections says which of them the others hang off. It is an optional key for
    the same reason `branch_order` is: absent means "not stated" (the grammar then
    reads the intent, then the partition, and refuses when none of them answers), a
    key this build does not read would be an intent nobody honours, and a document
    that states nothing serialises exactly as it did before the field existed —
    same bytes, same digest, same plan.
    """

    id: str
    parts: list[str] = field(default_factory=list)
    role: str = ""
    grammar_ref: str = ""
    side_preferences: dict[str, str] = field(default_factory=dict)
    branch_order: list[str] = field(default_factory=list)
    core: str = ""


@dataclass(frozen=True)
class FlowEdge:
    """One module-level flow direction: ``from`` feeds ``to`` (056 sec.1).

    A partial order, not a path: the page compiler places the modules in an
    order that respects every edge, and a page that states no edge is read in
    module-name order. ``main_path`` marks the edge the reader is meant to
    follow — the one case where the cross-module connection may be drawn as a
    whole wire instead of naming the net at both ends (056 sec.2).
    """

    from_module: str
    to_module: str
    main_path: bool = False


@dataclass
class PresentationPath:
    """A chain the drawing must keep recognisable (main or feedback path).

    ``chain`` is ordered and typed: ``"net:VIN"``, ``"part:R1"``, ``"part:C1"``…
    The order is the electrical direction the reader should follow, which is the
    whole point of declaring it — 052 sec.6: a feedback channel stays visible,
    it is not flattened into an acyclic left-to-right picture.
    """

    id: str = ""
    chain: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class DirectWiringObligation:
    """A local topology that must be **wired**, not expressed with a label.

    052 sec.5: "关键局部拓扑优先直连". Stated per net because the label decision
    is made per net; a pin-level obligation would be a second way of saying it,
    checked against nothing this document carries.
    """

    nets: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class LabelPolicy:
    """When a label may stand in for a wire (053 sec.2, hard-coded in sec.7)."""

    local: str = LABEL_WIRE
    cross_module: str = LABEL_LABEL
    high_fanout: str = LABEL_LABEL


@dataclass
class UserLock:
    """A part the engineer has already placed (052 sec.4).

    The one legitimate coordinate in this document, and the one input the
    compiler may not quietly ignore: 053 sec.5 scenario 12 requires a lock that
    conflicts with the grammar to be *reported*, never dropped.

    ``scope`` says what ``x``/``y`` are measured in (057 sec.3):

    * ``module`` (the default, and every lock written before 057) — the
      module's own drawing. The page translates the lock with its module;
      ``rotation`` is part of the lock.
    * ``page`` — the page itself. The part lands at exactly ``(x, y)`` in every
      page candidate, and the page compiler derives the module's origin from it
      (``origin = P − L(generation)``). A page lock pins a **position**: the
      part's pose is its module's drawing (a module lock states it), so a page
      lock carries no rotation.

    One part may carry one lock of each scope: the module lock arranges the part
    inside its module, the page lock puts that arrangement on the page.
    """

    part_id: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scope: str = LOCK_SCOPE_MODULE

    @property
    def is_page(self) -> bool:
        return self.scope == LOCK_SCOPE_PAGE


@dataclass
class PresentationSpec:
    """The whole presentation intent, in normal form."""

    modules: list[PresentationModule] = field(default_factory=list)
    #: Module-level flow directions (056 sec.1). A partial order over module ids:
    #: the page compiler reads it to order the page and to find the edges it may
    #: wire as one whole connection. Empty = read the modules in name order.
    flow: list[FlowEdge] = field(default_factory=list)
    main_paths: list[PresentationPath] = field(default_factory=list)
    feedback_paths: list[PresentationPath] = field(default_factory=list)
    #: net id -> one of :data:`PORT_DIRECTIONS`. The same vocabulary the
    #: CircuitSpec's `openInterfaces` uses, defined once in `circuitspec.py`.
    port_roles: dict[str, str] = field(default_factory=dict)
    #: Which grammar the drawing follows, or "" when the spec does not choose.
    grammar_ref: str = ""
    direct_wiring_obligations: list[DirectWiringObligation] = field(default_factory=list)
    label_policy: LabelPolicy = field(default_factory=LabelPolicy)
    side_preferences: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_SIDE_PREFERENCES)
    )
    user_locks: list[UserLock] = field(default_factory=list)
    spec_version: int = PRESENTATION_SPEC_VERSION

    # ------------------------------------------------------------ derived

    def locked_part_ids(self) -> list[str]:
        return [lock.part_id for lock in self.user_locks]

    def page_locks(self) -> list[UserLock]:
        """The locks measured on the page (057 sec.3), in document order."""
        return [lock for lock in self.user_locks if lock.is_page]

    def side_for(self, role: str) -> str:
        """The preferred side for a role, or "" when the spec has no preference."""
        return self.side_preferences.get(role, "")

    def module(self, module_id: str) -> PresentationModule | None:
        """The module with this id, or ``None``."""
        for item in self.modules:
            if item.id == module_id:
                return item
        return None

    def modules_of_part(self, part_id: str) -> list[str]:
        """Every module that claims this part — one, none, or the contradiction."""
        return [item.id for item in self.modules if part_id in item.parts]

    def sides_for_module(self, module: PresentationModule) -> dict[str, str]:
        """The sides a module draws with: the document's, overridden by its own."""
        merged = dict(self.side_preferences)
        merged.update(module.side_preferences)
        return merged

    def main_path_edges(self) -> list[FlowEdge]:
        """The flow edges marked `mainPath` (056 sec.2's whole-wire exception)."""
        return [edge for edge in self.flow if edge.main_path]

    # --------------------------------------------------------------- JSON

    def to_jsonable(self) -> dict[str, Any]:
        """Coordinates appear exactly once, under `userLocks`.

        The per-module `grammarRef` / `presentation` and the top-level `flow`
        are written **only when stated**: a document that says nothing new
        serialises exactly as it did before the page layer existed, which is what
        keeps an existing spec's digest (and therefore every plan compiled from
        it) byte-identical (053B's scene hashes are a contract).
        """
        return {
            "kind": PRESENTATION_SPEC_KIND,
            "specVersion": self.spec_version,
            "modules": [_module_json(module) for module in self.modules],
            **(
                {"flow": [
                    {"from": edge.from_module, "to": edge.to_module,
                     "mainPath": edge.main_path}
                    for edge in self.flow
                ]}
                if self.flow
                else {}
            ),
            "mainPaths": [_path_json(path) for path in self.main_paths],
            "feedbackPaths": [_path_json(path) for path in self.feedback_paths],
            "portRoles": dict(self.port_roles),
            "grammarRef": self.grammar_ref,
            "directWiringObligations": [
                {"nets": list(item.nets), "note": item.note}
                for item in self.direct_wiring_obligations
            ],
            "labelPolicy": {
                "local": self.label_policy.local,
                "crossModule": self.label_policy.cross_module,
                "highFanout": self.label_policy.high_fanout,
            },
            "sidePreferences": dict(self.side_preferences),
            "userLocks": [_lock_json(lock) for lock in self.user_locks],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> PresentationSpec:
        _refuse_coordinates(payload, "$")
        root = _object(payload, "$")
        _check_keys(root, _TOP_KEYS, "$")
        version = root.get("specVersion", PRESENTATION_SPEC_VERSION)
        if version != PRESENTATION_SPEC_VERSION:
            raise PresentationSpecError(
                f"$.specVersion is {version!r}, this build reads "
                f"{PRESENTATION_SPEC_VERSION} — regenerate the spec"
            )
        return cls(
            modules=_modules_from(root),
            flow=_flow_from(root),
            main_paths=_paths_from(root, "mainPaths"),
            feedback_paths=_paths_from(root, "feedbackPaths"),
            port_roles=_port_roles(root),
            grammar_ref=_grammar(root),
            direct_wiring_obligations=_obligations_from(root),
            label_policy=_label_policy(root),
            side_preferences=_side_preferences(root),
            user_locks=_locks_from(root),
        )

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_jsonable(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> PresentationSpec:
        """Read a spec file. Every failure is a :class:`PresentationSpecError`."""
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise PresentationSpecError(f"{source}: cannot be read ({exc})") from exc
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise PresentationSpecError(f"{source}: is not JSON ({exc})") from exc
        try:
            return cls.from_dict(payload)
        except PresentationSpecError as exc:
            raise PresentationSpecError(f"{source}: {exc}") from exc

    def sha256(self) -> str:
        """Digest of the canonical form — the second hash a LayoutPlan pins."""
        return presentation_sha256(self)


def presentation_sha256(spec: PresentationSpec) -> str:
    """sha256 of the spec's canonical JSON (see :func:`circuitspec.spec_sha256`)."""
    text = json.dumps(
        spec.to_jsonable(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main_path_wire(
    spec: PresentationSpec, net_class: str | None, modules: Sequence[str]
) -> bool:
    """Is this crossing net **one whole wire** on the page, rather than a name?

    A net that crosses a module boundary is stated by its name at both ends — a
    flag for a ground or a rail, a label otherwise (:class:`LabelPolicy`'s
    ``crossModule``). The one exception is the flow edge the presentation itself
    marks ``mainPath``: that mark asks for **one run** from port to port
    (056 sec.2), which a name at each end cannot keep. 069 sec.7 keeps a *rail*
    on the same terms — "a rail is a bus at any fan-out": the member count that
    used to decide it is gone, and the flag is what 岳 reads. A **ground is never
    a wire**, so a `mainPath` mark on one is refused and named rather than
    quietly downgraded (056 sec.3).

    This function is the **single source** of that decision (096), and the two
    callers ask it instead of keeping a copy: the page compiler picks each
    port's style with it (`pagecompiler._net_style`), and the page checker
    decides with it which cross-module wire may satisfy a ``mainPath`` edge
    (`readability._check_main_paths`). The copy the checker used to keep —
    "`power` with more than `high_fanout` members is a bus" — is exactly what
    made the same net a wire to the compiler and a bus to the checker, so a
    four-member rail marked `mainPath` was drawn as a wire and refused in the
    same pass.

    ``modules`` are the modules that own the net (the rule needs exactly two),
    and ``net_class`` is the net's class in the circuit — ``None`` for a net the
    circuit does not state, which the compiler refuses elsewhere rather than
    here.
    """
    if net_class == "gnd":
        return False
    pair = set(modules)
    return len(pair) == 2 and any(
        edge.main_path and {edge.from_module, edge.to_module} == pair
        for edge in spec.flow
    )


# ------------------------------------------------------------------ readers


def _path_json(path: PresentationPath) -> dict[str, Any]:
    return {"id": path.id, "chain": list(path.chain), "note": path.note}


def _lock_json(lock: UserLock) -> dict[str, Any]:
    """One lock, in the shape its scope has.

    A module lock serialises exactly as every lock did before 057 (no `scope`
    key): a spec that says nothing new keeps its digest, and with it every plan
    compiled from it (the same rule the module overrides and `flow` follow). A
    page lock states its scope and no rotation — it pins a position.
    """
    if lock.is_page:
        return {"partId": lock.part_id, "x": lock.x, "y": lock.y, "scope": lock.scope}
    return {
        "partId": lock.part_id,
        "x": lock.x,
        "y": lock.y,
        "rotation": lock.rotation,
    }


def _module_json(module: PresentationModule) -> dict[str, Any]:
    """One module, with its overrides written only when it states them."""
    out: dict[str, Any] = {
        "id": module.id, "parts": list(module.parts), "role": module.role,
    }
    if module.grammar_ref:
        out["grammarRef"] = module.grammar_ref
    if module.side_preferences:
        out["presentation"] = {"sidePreferences": dict(module.side_preferences)}
    if module.branch_order:
        out["branchOrder"] = list(module.branch_order)
    if module.core:
        out["core"] = module.core
    return out


def _modules_from(root: dict[str, Any]) -> list[PresentationModule]:
    out: list[PresentationModule] = []
    seen: set[str] = set()
    for index, item in enumerate(_list(root.get("modules"), "modules")):
        spot = f"modules[{index}]"
        body = _object(item, spot)
        _check_keys(body, _MODULE_KEYS, spot)
        module_id = _text(body.get("id"), f"{spot}.id", required=True)
        if module_id in seen:
            raise PresentationSpecError(
                f"{spot}.id is {module_id!r}, already used — one id is one module"
            )
        seen.add(module_id)
        parts = _text_list(body.get("parts"), f"{spot}.parts")
        if not parts:
            raise PresentationSpecError(
                f"{spot}.parts is empty — a module with no parts is a caption, "
                "not a group the layout can place"
            )
        out.append(PresentationModule(
            id=module_id,
            parts=parts,
            role=_text(body.get("role"), f"{spot}.role", required=True),
            grammar_ref=_module_grammar(body.get("grammarRef"), f"{spot}.grammarRef"),
            side_preferences=_module_presentation(body.get("presentation"), spot),
            branch_order=_module_branch_order(body.get("branchOrder"), spot, parts),
            core=_module_core(body.get("core"), f"{spot}.core"),
        ))
    return out


def _module_core(value: Any, where: str) -> str:
    """A module's stated core, or ``""`` for "not stated".

    098 §一: the core is the group's own part, so the only thing this document can
    decide about it is that it is a part id written down — whether the circuit
    declares it, and whether it carries enough pins to be the part the others hang
    off, are readings of the *circuit* and belong to the grammar (the same split
    `branchOrder` uses, and the same reason the module's `parts` are not
    cross-checked here).
    """
    if value is None or value == "":
        return ""
    return _text(value, where, required=True)


def _module_branch_order(
    value: Any, where: str, parts: Sequence[str]
) -> list[str]:
    """A module's stated branch order, checked against its own ``parts``.

    Two things are decidable from this document alone, and both are refused here
    rather than left to the grammar: a designator named twice ("one branch has
    one place in the order") and a designator the module's own ``parts`` does not
    list — the order is stated over *this* group, and a designator from outside
    it is a statement about somebody else's parts. Whether a named part is a
    *branch* at all is a reading of the circuit (the topology), so that half
    belongs to the grammar and is refused there (088b §二).
    """
    designators = _text_list(value, f"{where}.branchOrder")
    if not designators:
        return []
    seen: set[str] = set()
    for index, designator in enumerate(designators):
        spot = f"{where}.branchOrder[{index}]"
        if designator in seen:
            raise PresentationSpecError(
                f"{spot} is {designator!r}, already named — one branch has one "
                "place in the order, and a repeat says two different things "
                "about where it goes"
            )
        seen.add(designator)
        if designator not in parts:
            raise PresentationSpecError(
                f"{spot} is {designator!r}, which {where}.parts does not list "
                f"({', '.join(parts)}) — the order is stated over this group's "
                "own parts, and a designator outside it is a statement about "
                "another group's drawing"
            )
    return designators


def _module_grammar(value: Any, where: str) -> str:
    """A module's own grammar, or "" for "the document's"."""
    if value is None or value == "":
        return ""
    grammar = _text(value, where, required=True)
    if grammar not in GRAMMARS:
        raise PresentationSpecError(
            f"{where} is {grammar!r}; this build knows {', '.join(GRAMMARS)} — a "
            "module states one of them or states nothing and inherits the "
            "document's grammarRef"
        )
    return grammar


def _module_presentation(value: Any, where: str) -> dict[str, str]:
    """A module's `presentation` overrides: this build reads side preferences."""
    if value is None:
        return {}
    body = _object(value, f"{where}.presentation")
    _check_keys(body, MODULE_PRESENTATION_KEYS, f"{where}.presentation")
    raw = body.get("sidePreferences")
    if raw is None:
        return {}
    sides = _object(raw, f"{where}.presentation.sidePreferences")
    out: dict[str, str] = {}
    for role, side in sides.items():
        if side not in SIDES:
            raise PresentationSpecError(
                f"{where}.presentation.sidePreferences.{role} is {side!r}; "
                f"expected one of {', '.join(SIDES)}"
            )
        out[str(role)] = side
    return out


def _flow_from(root: dict[str, Any]) -> list[FlowEdge]:
    """The module-level flow edges, in the two forms the spec accepts.

    A plain pair (``["pwr", "sense"]``) states direction and nothing else, and
    the object form adds the one thing a pair cannot carry — `mainPath`. Both
    normalise to :class:`FlowEdge`, so the compiler reads one shape.
    """
    out: list[FlowEdge] = []
    seen: set[tuple[str, str, bool]] = set()
    for index, item in enumerate(_list(root.get("flow"), "flow")):
        spot = f"flow[{index}]"
        if isinstance(item, list):
            if len(item) != 2:
                raise PresentationSpecError(
                    f"{spot} is a list of {len(item)} entr(ies); the short form of "
                    "a flow edge is a pair ['<from module>', '<to module>'] — the "
                    "object form {'from': …, 'to': …, 'mainPath': …} carries the "
                    "main-path mark"
                )
            edge = FlowEdge(
                from_module=_text(item[0], f"{spot}[0]", required=True),
                to_module=_text(item[1], f"{spot}[1]", required=True),
            )
        else:
            body = _object(item, spot)
            _check_keys(body, _FLOW_EDGE_KEYS, spot)
            mark = body.get("mainPath", False)
            if not isinstance(mark, bool):
                raise PresentationSpecError(
                    f"{spot}.mainPath must be a boolean, got {mark!r}"
                )
            edge = FlowEdge(
                from_module=_text(body.get("from"), f"{spot}.from", required=True),
                to_module=_text(body.get("to"), f"{spot}.to", required=True),
                main_path=mark,
            )
        if edge.from_module == edge.to_module:
            raise PresentationSpecError(
                f"{spot} flows from {edge.from_module!r} to itself — a group does "
                "not feed itself, and an edge like this says nothing about order"
            )
        key = (edge.from_module, edge.to_module, edge.main_path)
        if key in seen:
            raise PresentationSpecError(
                f"{spot} repeats the edge "
                f"{edge.from_module!r} -> {edge.to_module!r}"
                + (" (mainPath)" if edge.main_path else "")
                + " — one direction is one edge"
            )
        seen.add(key)
        out.append(edge)
    return out


def _paths_from(root: dict[str, Any], key: str) -> list[PresentationPath]:
    out: list[PresentationPath] = []
    for index, item in enumerate(_list(root.get(key), key)):
        spot = f"{key}[{index}]"
        body = _object(item, spot)
        _check_keys(body, _PATH_KEYS, spot)
        chain = _text_list(body.get("chain"), f"{spot}.chain")
        if not chain:
            raise PresentationSpecError(
                f"{spot}.chain is empty — a path with no steps says nothing about "
                "what the reader should be able to follow"
            )
        for step_index, step in enumerate(chain):
            _path_step(step, f"{spot}.chain[{step_index}]")
        if len(set(chain)) != len(chain):
            raise PresentationSpecError(
                f"{spot}.chain names the same step twice ({', '.join(chain)}) — a "
                "path visits each element once"
            )
        out.append(PresentationPath(
            id=_text(body.get("id"), f"{spot}.id"),
            chain=chain,
            note=_text(body.get("note"), f"{spot}.note"),
        ))
    return out


def _path_step(step: str, where: str) -> None:
    for prefix in (PATH_STEP_PART, PATH_STEP_NET):
        if step.startswith(prefix):
            if not step[len(prefix):].strip():
                raise PresentationSpecError(
                    f"{where} is {step!r} with nothing after {prefix!r}"
                )
            return
    raise PresentationSpecError(
        f"{where} is {step!r}; a path step names what it is — "
        f"'{PATH_STEP_PART}<partId>' or '{PATH_STEP_NET}<netId>'"
    )


def _obligations_from(root: dict[str, Any]) -> list[DirectWiringObligation]:
    out: list[DirectWiringObligation] = []
    for index, item in enumerate(
        _list(root.get("directWiringObligations"), "directWiringObligations")
    ):
        spot = f"directWiringObligations[{index}]"
        body = _object(item, spot)
        _check_keys(body, _OBLIGATION_KEYS, spot)
        nets = _text_list(body.get("nets"), f"{spot}.nets")
        if not nets:
            raise PresentationSpecError(
                f"{spot}.nets is empty — an obligation with no net obliges nothing "
                "(the local connection it protects is named by a net)"
            )
        out.append(DirectWiringObligation(
            nets=nets, note=_text(body.get("note"), f"{spot}.note")
        ))
    return out


def _label_policy(root: dict[str, Any]) -> LabelPolicy:
    value = root.get("labelPolicy")
    if value is None:
        return LabelPolicy()
    body = _object(value, "labelPolicy")
    _check_keys(body, _LABEL_POLICY_KEYS, "labelPolicy")
    local = body.get("local", LABEL_WIRE)
    if local != LABEL_WIRE:
        raise PresentationSpecError(
            f"labelPolicy.local is {local!r}; it may only be {LABEL_WIRE!r} — a "
            "key local topology is drawn as a wire, and the label exception "
            "applies across modules or at high fan-out (053 sec.7, 052 sec.5)"
        )
    out = LabelPolicy(local=LABEL_WIRE)
    for key, attribute in (("crossModule", "cross_module"), ("highFanout", "high_fanout")):
        mode = body.get(key, getattr(out, attribute))
        if mode not in LABEL_MODES:
            raise PresentationSpecError(
                f"labelPolicy.{key} is {mode!r}; expected one of "
                f"{', '.join(LABEL_MODES)}"
            )
        setattr(out, attribute, mode)
    return out


def _side_preferences(root: dict[str, Any]) -> dict[str, str]:
    out = dict(DEFAULT_SIDE_PREFERENCES)
    value = root.get("sidePreferences")
    if value is None:
        return out
    body = _object(value, "sidePreferences")
    for role, side in body.items():
        if side not in SIDES:
            raise PresentationSpecError(
                f"sidePreferences.{role} is {side!r}; expected one of "
                f"{', '.join(SIDES)}"
            )
        out[str(role)] = side
    return out


def _port_roles(root: dict[str, Any]) -> dict[str, str]:
    value = root.get("portRoles")
    if value is None:
        return {}
    body = _object(value, "portRoles")
    out: dict[str, str] = {}
    for net_id, direction in body.items():
        if not str(net_id).strip():
            raise PresentationSpecError("portRoles has an empty net id")
        if direction not in PORT_DIRECTIONS:
            raise PresentationSpecError(
                f"portRoles[{net_id}] is {direction!r}; expected one of "
                f"{', '.join(PORT_DIRECTIONS)}"
            )
        out[str(net_id)] = direction
    return out


def _grammar(root: dict[str, Any]) -> str:
    value = root.get("grammarRef", "")
    if value not in ("", *GRAMMARS):
        raise PresentationSpecError(
            f"$.grammarRef is {value!r}; this build knows "
            f"{', '.join(GRAMMARS)} — a grammar is a promise about what the "
            "drawing will make visible, and an unknown one is refused rather "
            "than replaced with a generic layout"
        )
    return str(value)


def _locks_from(root: dict[str, Any]) -> list[UserLock]:
    out: list[UserLock] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(_list(root.get("userLocks"), "userLocks")):
        spot = f"userLocks[{index}]"
        body = _object(item, spot)
        _check_keys(body, _LOCK_KEYS, spot)
        part_id = _text(body.get("partId"), f"{spot}.partId", required=True)
        scope = body.get("scope", LOCK_SCOPE_MODULE)
        if scope not in LOCK_SCOPES:
            raise PresentationSpecError(
                f"{spot}.scope is {scope!r}; expected one of {', '.join(LOCK_SCOPES)} "
                "— a lock is measured in its module's drawing or on the page"
            )
        if (part_id, scope) in seen:
            raise PresentationSpecError(
                f"{spot}.partId is {part_id!r}, already locked"
                + (" on the page" if scope == LOCK_SCOPE_PAGE else "")
                + " — two locks on one part are two answers to where it goes"
            )
        seen.add((part_id, scope))
        numbers = [_number(body.get(key), f"{spot}.{key}") for key in ("x", "y")]
        if scope == LOCK_SCOPE_PAGE:
            if "rotation" in body:
                raise PresentationSpecError(
                    f"{spot} is a page lock with a rotation — a page lock pins where "
                    "the part lands on the page, and its pose belongs to the module's "
                    "drawing: state the pose with a module lock on the same part "
                    "(the two scopes may be combined, 057 sec.3)"
                )
            out.append(UserLock(
                part_id=part_id, x=numbers[0], y=numbers[1], scope=LOCK_SCOPE_PAGE,
            ))
            continue
        rotation = _number(body.get("rotation", 0), f"{spot}.rotation")
        if rotation not in POSE_ROTATIONS:
            raise PresentationSpecError(
                f"{spot}.rotation is {rotation!r}; a lock names one of the poses "
                f"the symbols are drawn in ({', '.join(str(r) for r in POSE_ROTATIONS)} "
                "degrees, 052 sec.6's finite legal pose set)"
            )
        out.append(UserLock(
            part_id=part_id, x=numbers[0], y=numbers[1], rotation=rotation
        ))
    return out


# ------------------------------------------------------------------ helpers


def _refuse_coordinates(payload: Any, path: str, *, locked: bool = False) -> None:
    """Coordinates are refused everywhere except inside a `userLocks` entry.

    Runs on the raw payload before parsing (052 sec.4): the point is that the
    model entry point does not accept a coordinate at all, and a refusal that
    named the offending path is what teaches the next attempt. A lock is the
    engineer's own decision, so it is the one place the rule does not apply.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if not (locked and key in _LOCK_KEYS) and key in _COORDINATE_KEYS:
                raise PresentationSpecError(
                    f"{path}.{key} is a coordinate-shaped key ({key!r}); the model "
                    "entry point does not accept raw coordinates, wire points or "
                    "connector actions — coordinates are compiled from this spec "
                    "(053 sec.2), and the only legitimate coordinate entry is "
                    "userLocks"
                )
            # The exemption is the lock's own three keys, not its subtree:
            # `wirePoints` smuggled into a lock is still a coordinate-shaped key.
            _refuse_coordinates(value, f"{path}.{key}", locked=key == "userLocks")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _refuse_coordinates(value, f"{path}[{index}]", locked=locked)


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PresentationSpecError(
            f"{where} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PresentationSpecError(f"$.{where} must be a list, got {value!r}")
    return value


def _text(value: Any, where: str, required: bool = False) -> str:
    if value is None:
        if required:
            raise PresentationSpecError(f"{where} is required and missing")
        return ""
    if not isinstance(value, str):
        raise PresentationSpecError(f"{where} must be a string, got {value!r}")
    if required and not value.strip():
        raise PresentationSpecError(f"{where} is empty")
    return value.strip()


def _text_list(value: Any, where: str) -> list[str]:
    raw = _list(value, where)
    out: list[str] = []
    for index, item in enumerate(raw):
        out.append(_text(item, f"{where}[{index}]", required=True))
    return out


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PresentationSpecError(
            f"{where} must be a number in canvas units, got {value!r}"
        )
    return float(value)


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise PresentationSpecError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(allowed)} — the schema is closed on purpose: a key this "
            "build does not read would otherwise be an intent nobody honours"
        )

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

What this module deliberately does **not** check: that `modules[*].parts`,
`mainPaths` steps and `userLocks[*].partId` name parts that exist. Those are
CircuitSpec facts, and the cross-check belongs to whoever holds both documents —
the phase-B compiler. Validating them here would either duplicate the circuit
schema in this file or accept a document that silently refers to nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .circuitspec import PORT_DIRECTIONS
from .symbolprofile import POSE_ROTATIONS

__all__ = [
    "DEFAULT_SIDE_PREFERENCES",
    "GRAMMARS",
    "LABEL_LABEL",
    "LABEL_MODES",
    "LABEL_WIRE",
    "PATH_STEP_NET",
    "PATH_STEP_PART",
    "PRESENTATION_SPEC_KIND",
    "PRESENTATION_SPEC_VERSION",
    "SIDES",
    "DirectWiringObligation",
    "LabelPolicy",
    "PresentationModule",
    "PresentationPath",
    "PresentationSpec",
    "PresentationSpecError",
    "UserLock",
    "presentation_sha256",
]

#: Identifies the document; see `circuitspec.CIRCUIT_SPEC_KIND` for the rule.
PRESENTATION_SPEC_KIND = "boardwise-presentation-spec"

#: Same rule as `changeplan.PLAN_VERSION`: a stated version this build does not
#: have is refused rather than guessed at.
PRESENTATION_SPEC_VERSION = 1

#: The three drawing grammars this build knows (053 sec.2 — "本批只认这三个字面
#: 量"). Empty means the spec does not choose one; a fourth literal is a refusal,
#: not a fallback to a generic layout: a grammar is a set of promises about what
#: will be visible, and pretending to keep promises nobody wrote is worse than
#: saying the grammar is not known.
GRAMMARS: tuple[str, ...] = ("voltage-divider", "rc-lowpass", "ldo")

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
    "mainPaths",
    "feedbackPaths",
    "portRoles",
    "grammarRef",
    "directWiringObligations",
    "labelPolicy",
    "sidePreferences",
    "userLocks",
)
_MODULE_KEYS = ("id", "parts", "role")
_PATH_KEYS = ("id", "chain", "note")
_OBLIGATION_KEYS = ("nets", "note")
_LABEL_POLICY_KEYS = ("local", "crossModule", "highFanout")
_LOCK_KEYS = ("partId", "x", "y", "rotation")

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
    """One functional group: its parts and what the group is for.

    The module is what makes "电容归侧" decidable — a decoupling capacitor and
    the IC it belongs to are one group, and a group has one place on the page.
    """

    id: str
    parts: list[str] = field(default_factory=list)
    role: str = ""


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
    """

    part_id: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0


@dataclass
class PresentationSpec:
    """The whole presentation intent, in normal form."""

    modules: list[PresentationModule] = field(default_factory=list)
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

    def side_for(self, role: str) -> str:
        """The preferred side for a role, or "" when the spec has no preference."""
        return self.side_preferences.get(role, "")

    # --------------------------------------------------------------- JSON

    def to_jsonable(self) -> dict[str, Any]:
        """Coordinates appear exactly once, under `userLocks`."""
        return {
            "kind": PRESENTATION_SPEC_KIND,
            "specVersion": self.spec_version,
            "modules": [
                {"id": module.id, "parts": list(module.parts), "role": module.role}
                for module in self.modules
            ],
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
            "userLocks": [
                {
                    "partId": lock.part_id,
                    "x": lock.x,
                    "y": lock.y,
                    "rotation": lock.rotation,
                }
                for lock in self.user_locks
            ],
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


# ------------------------------------------------------------------ readers


def _path_json(path: PresentationPath) -> dict[str, Any]:
    return {"id": path.id, "chain": list(path.chain), "note": path.note}


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
        ))
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
    seen: set[str] = set()
    for index, item in enumerate(_list(root.get("userLocks"), "userLocks")):
        spot = f"userLocks[{index}]"
        body = _object(item, spot)
        _check_keys(body, _LOCK_KEYS, spot)
        part_id = _text(body.get("partId"), f"{spot}.partId", required=True)
        if part_id in seen:
            raise PresentationSpecError(
                f"{spot}.partId is {part_id!r}, already locked — two locks on one "
                "part are two answers to where it goes"
            )
        seen.add(part_id)
        numbers = [_number(body.get(key), f"{spot}.{key}") for key in ("x", "y")]
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

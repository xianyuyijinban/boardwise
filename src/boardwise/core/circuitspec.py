"""CircuitSpec: what a circuit **is** (053 stage A, 052 sec.4).

The first of the three data contracts the drawing compiler is built on. Its job
is the electrical meaning, and only that: which parts exist, numbered by a
**stable logical id**, and which of their pins are one node. Nothing here knows
about pages, coordinates, symbols or text — that is `presentationspec.py`
(how it should read) and `layoutplan.py` (what the tool computed).

Four decisions worth stating, because everything else follows from them:

* **The id is not a designator and not a host id.** `R1` is assigned when a
  part lands on a page, and a `primitiveId` only exists inside the editor; a
  spec naming parts by either would break the moment the editor renumbered
  something. The id is the spec's own name for the part, and it is what every
  other fact (members, NC, interfaces) refers to. Corollary: an id may not
  contain ``.``, because ``<partId>.<pin>`` has to split unambiguously.
* **pairwise connections are input sugar.** An author may write
  ``connections: [{from, to}]`` and the spec normalises it into "one net, many
  members" (052 sec.4). The normal form is the *partition*, never the pair list:
  the pair list is one way of typing the partition, not a second structure to
  keep in sync.
* **"no connection given" is not NC.** A pin nothing mentions is simply
  unmentioned; ``nc`` says it explicitly and is the only way to say it.
* **every fact says how it is known, and absence is not confirmation.** Every
  fact (part, net, NC, interface) carries a provenance from
  :data:`PROVENANCE_KINDS`; an `ai_asserted` fact makes the whole spec a draft,
  and so does a fact that states nothing at all. 052 sec.4: "电气依据未确认的
  输出只能是明确标注的草稿". A flag that only fired on the literal string
  `ai_asserted` would be switched off by simply not writing the field, so the
  unstated case counts too.

What this module deliberately does **not** check: whether a pin name exists on
the part. A CircuitSpec states which pins it uses; whether ``<partId>.<pin>`` is
a real pin of that symbol is a question for the SymbolProfile (phase A's fourth
contract), and asking it here would need a library the spec does not carry.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "AUTO_NET_PREFIX",
    "CIRCUIT_SPEC_KIND",
    "CIRCUIT_SPEC_VERSION",
    "DEFAULT_NET_CLASS",
    "NET_CLASSES",
    "NET_SCOPES",
    "PORT_DIRECTIONS",
    "PROVENANCE_AI",
    "PROVENANCE_ENGINEER",
    "PROVENANCE_KINDS",
    "PROVENANCE_VERIFIED",
    "CircuitSpec",
    "CircuitSpecError",
    "SpecNet",
    "SpecNoConnect",
    "SpecOpenInterface",
    "SpecPart",
    "spec_sha256",
]

#: Identifies the document, the way `blocklib` templates and the port-metadata
#: sidecar do. A document whose kind is something else is a refusal, not a
#: half-understood structure.
CIRCUIT_SPEC_KIND = "boardwise-circuit-spec"

#: The spec version this build reads. Same rule as `changeplan.PLAN_VERSION`:
#: a stated version this build does not have is refused rather than guessed at.
CIRCUIT_SPEC_VERSION = 1

#: The four net classes (053 sec.2). The class is part of the *circuit*
#: contract, not a presentation preference: "this is ground" is what the net is,
#: and the drawing side reads it (a rail gets a power symbol, a signal a label).
NET_CLASSES: tuple[str, ...] = ("power", "gnd", "signal", "other")

#: The class a net gets when nothing said (a net built purely from `connections`
#: sugar). Documented as a default rather than a measurement: it is the book's
#: neutral case for a pin-to-pin connection, and a net that really is power or
#: ground must be declared in `nets` with its class.
DEFAULT_NET_CLASS = "signal"

#: Where a net lives: one page, or the whole project (052 sec.4: "记录页/工程
#: 作用域"). Empty means the spec does not say, kept distinct from `page`
#: because "cannot tell" and "one page" are different answers — the
#: port-metadata sidecar's rule (008c), applied to nets.
NET_SCOPES: tuple[str, ...] = ("page", "project")

#: The provenance three-state of 052 sec.4.
PROVENANCE_VERIFIED = "verified_recipe"
PROVENANCE_ENGINEER = "engineer_confirmed"
PROVENANCE_AI = "ai_asserted"
PROVENANCE_KINDS: tuple[str, ...] = (
    PROVENANCE_VERIFIED,
    PROVENANCE_ENGINEER,
    PROVENANCE_AI,
)

#: Weakest first: a merged fact is only as good as its weakest part, so a net
#: built from a verified recipe and an AI guess is an AI guess. Absence ("" ) is
#: weaker than all three.
_PROVENANCE_RANK = {PROVENANCE_AI: 0, PROVENANCE_ENGINEER: 1, PROVENANCE_VERIFIED: 2}

#: What an open interface's `direction` may say — the same vocabulary
#: `PresentationSpec.portRoles` uses. Defined once, here, because the two must
#: agree about what a port direction is.
PORT_DIRECTIONS: tuple[str, ...] = ("source", "load", "input", "output", "feedback")

#: The id prefix of a net the spec had to name itself (a `connections`-only
#: component). Visible in the id on purpose: a synthesized name that looked like
#: an authored one would be read as a declaration.
AUTO_NET_PREFIX = "auto:"

_TOP_KEYS = (
    "kind",
    "specVersion",
    "parts",
    "nets",
    "nc",
    "openInterfaces",
    "operatingConditions",
    "connections",
    "draft",
)
_PART_KEYS = ("id", "symbolRef", "value", "mpn", "lcsc", "params", "provenance")
_NET_KEYS = ("id", "class", "members", "provenance", "memberProvenance", "scope")
_NC_KEYS = ("pin", "provenance")
_INTERFACE_KEYS = ("net", "direction", "role", "provenance", "part")
_CONNECTION_KEYS = ("from", "to", "provenance")

#: Keys that mean "a place on the canvas". A CircuitSpec is *meaning*, so no
#: coordinate may appear in one at all (052 sec.4: the model entry point does
#: not accept raw coordinates). Refused by :func:`_refuse_coordinates`, which
#: walks the raw payload before anything is parsed — the refusal has to name the
#: offending path, and a parse that dropped the key would leave nothing to name.
_COORDINATE_KEYS = frozenset({
    "x", "y", "rotation", "angle", "mirror", "isMirror", "dx", "dy",
    "x1", "y1", "x2", "y2",
    "points", "point", "wirePoints", "polyline", "waypoints", "route",
    "segments", "junctions", "bbox", "at",
    "connectorAction", "connectorActions", "actions", "primitiveId",
})


class CircuitSpecError(ValueError):
    """The spec is not one this build can read.

    Every message names the path and the reason: a model writes these, and
    "invalid spec" alone sends it back to the schema with nothing to compare
    against.
    """


@dataclass
class SpecPart:
    """One part as a *logical* element: an id, a symbol to instantiate, a value.

    `symbol_ref` is the library symbol the part is drawn with — not a geometry:
    the pin tips, body extent and legal poses come from the SymbolProfile built
    from that symbol (053 sec.2). `value` is optional because the parser has
    already measured that a real part often has none (only 10 of 47 placed
    devices on the golden board define `Value`; the DEVICE title is the
    fallback), so a spec that forced a value would force an invented one.
    """

    id: str
    symbol_ref: str = ""
    value: str = ""
    mpn: str = ""
    lcsc: str = ""
    #: Free device parameters ("tolerance": "1%"). Values are **strings**, what
    #: was written on the part: the repo has read a display value as a quantity
    #: twice already (046/048), and a spec does not do it implicitly.
    params: dict[str, str] = field(default_factory=dict)
    provenance: str = ""


@dataclass
class SpecNet:
    """One node: an id, a class, and the pins that are electrically one.

    ``members`` are ``<partId>.<pin>`` strings. The membership is the fact
    (052 sec.4: a readback compares partitions and naming semantics, never the
    editor's auto-generated net name strings), which is why a synthesized net's
    id is derived from its own membership — see :func:`_auto_net_id`.

    ``member_provenance`` records only the members whose provenance **differs**
    from the net's own; a member that is not listed carries the net's. The
    common case stays readable, and the case that matters — a net one of whose
    connections is still an AI assertion — is not lost.
    """

    id: str
    cls: str = DEFAULT_NET_CLASS
    members: list[str] = field(default_factory=list)
    provenance: str = ""
    member_provenance: dict[str, str] = field(default_factory=dict)
    #: `page` / `project`, or "" when the spec does not say.
    scope: str = ""


@dataclass
class SpecNoConnect:
    """One pin the design deliberately leaves unconnected.

    Explicit because "nothing mentioned this pin" and "this pin is NC" are
    different facts, and only the second is a decision the drawing must respect
    (053 sec.2: "没给连接" ≠ NC).
    """

    pin: str
    provenance: str = ""


@dataclass
class SpecOpenInterface:
    """A net the circuit exposes rather than terminates (a port).

    An open interface is *not* a dangling error — 052 sec.6 says so by name
    ("开放接口和显式 NC 不是非法悬空"). Recording it is what lets the
    readability checker tell the two apart.

    ``part`` (088, **optional**) says *which connector part* realises this open
    interface: the fact a net's endpoint is a component, rather than a name
    floating on a wire. A ``direction`` of `input`/`source` is the direction a
    supply enters from, and without ``part`` the drawing grammar cannot tell a
    feeding connector from a parallel branch — the two are isomorphic on the
    drawing (`power-entry` §一). It is optional on purpose: an interface that
    states no part is an ordinary open interface, and a document written before
    this field existed must still round-trip byte for byte (the field is only
    written when it says something). Nothing here checks that the part exists —
    that is a grammar's judgment to report with its own wording, not a parser's.
    """

    net: str
    direction: str = ""
    role: str = ""
    provenance: str = ""
    part: str = ""


@dataclass
class CircuitSpec:
    """The whole circuit fact set, in normal form."""

    parts: list[SpecPart] = field(default_factory=list)
    nets: list[SpecNet] = field(default_factory=list)
    nc: list[SpecNoConnect] = field(default_factory=list)
    open_interfaces: list[SpecOpenInterface] = field(default_factory=list)
    #: Working conditions (voltage / current / frequency). Free keys, flat
    #: scalar values: the slot is reserved here and nothing in this batch reads
    #: it, so a nested shape would be a guess about what a later stage wants.
    operating_conditions: dict[str, Any] = field(default_factory=dict)
    spec_version: int = CIRCUIT_SPEC_VERSION

    # ------------------------------------------------------------ derived

    @property
    def draft(self) -> bool:
        """Is any fact in this spec unconfirmed? (052 sec.4)

        True when a fact is `ai_asserted` **or** says nothing. The second half
        is the load-bearing one: a flag a missing field could switch off would
        be no protection at all.
        """
        return bool(self.draft_reasons)

    @property
    def draft_reasons(self) -> list[str]:
        """Which facts make this a draft, one line each, sorted for stability.

        A bare boolean would leave the reader asking "which claim?", and 052
        sec.4's point is that the unconfirmed claim is *shown*.
        """
        reasons: set[str] = set()
        for part in self.parts:
            reasons.update(_draft_lines(part.provenance, f"part {part.id}"))
        for net in self.nets:
            reasons.update(_draft_lines(net.provenance, f"net {net.id}"))
            for member, provenance in net.member_provenance.items():
                reasons.update(
                    _draft_lines(provenance, f"net {net.id} member {member}")
                )
        for item in self.nc:
            reasons.update(_draft_lines(item.provenance, f"NC {item.pin}"))
        for interface in self.open_interfaces:
            reasons.update(
                _draft_lines(interface.provenance, f"open interface {interface.net}")
            )
        return sorted(reasons)

    def part(self, part_id: str) -> SpecPart | None:
        """The part with this id, or ``None``."""
        for item in self.parts:
            if item.id == part_id:
                return item
        return None

    def net(self, net_id: str) -> SpecNet | None:
        """The net with this id, or ``None``."""
        for item in self.nets:
            if item.id == net_id:
                return item
        return None

    def net_of_pin(self, pin: str) -> str | None:
        """The net a ``<partId>.<pin>`` sits on, or ``None`` for NC/unmentioned."""
        for net in self.nets:
            if pin in net.members:
                return net.id
        return None

    def part_ids(self) -> list[str]:
        return [part.id for part in self.parts]

    def net_ids(self) -> list[str]:
        return [net.id for net in self.nets]

    # --------------------------------------------------------------- JSON

    def to_jsonable(self) -> dict[str, Any]:
        """The normal form: sugar gone, every fact labelled or visibly bare."""
        return {
            "kind": CIRCUIT_SPEC_KIND,
            "specVersion": self.spec_version,
            "parts": [
                {
                    "id": part.id,
                    "symbolRef": part.symbol_ref,
                    "value": part.value,
                    "mpn": part.mpn,
                    "lcsc": part.lcsc,
                    "params": dict(part.params),
                    "provenance": part.provenance,
                }
                for part in self.parts
            ],
            "nets": [
                {
                    "id": net.id,
                    "class": net.cls,
                    "members": list(net.members),
                    "provenance": net.provenance,
                    **(
                        {"memberProvenance": dict(net.member_provenance)}
                        if net.member_provenance
                        else {}
                    ),
                    "scope": net.scope,
                }
                for net in self.nets
            ],
            "nc": [
                {"pin": item.pin, "provenance": item.provenance} for item in self.nc
            ],
            "openInterfaces": [
                {
                    "net": interface.net,
                    "direction": interface.direction,
                    "role": interface.role,
                    "provenance": interface.provenance,
                    # Optional (088): written only when it says something, so a
                    # document that does not use it hashes and round-trips as
                    # it did before the field existed.
                    **({"part": interface.part} if interface.part else {}),
                }
                for interface in self.open_interfaces
            ],
            "operatingConditions": dict(self.operating_conditions),
            # Derived, written for the consumer that only reads the document —
            # and *checked* on the way back in (see `from_dict`), so a
            # hand-written `draft: false` cannot silence it.
            "draft": self.draft,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> CircuitSpec:
        """Read a spec, normalise the sugar, refuse the contradictions.

        The refusals are the contract (053 sec.2): a member naming a part that
        does not exist, one pin on two nets, an NC pin that is also a net
        member, a connection that would join two named nets.
        """
        _refuse_coordinates(payload, "$")
        root = _object(payload, "$")
        _check_keys(root, _TOP_KEYS, "$")
        version = root.get("specVersion", CIRCUIT_SPEC_VERSION)
        if version != CIRCUIT_SPEC_VERSION:
            raise CircuitSpecError(
                f"$.specVersion is {version!r}, this build reads "
                f"{CIRCUIT_SPEC_VERSION} — regenerate the spec"
            )
        parts = _parts_from(root)
        by_id = {part.id: part for part in parts}
        nets = _nets_from(root, by_id)
        nc = _nc_from(root, by_id, nets)
        interfaces = _interfaces_from(root, {net.id for net in nets})
        spec = cls(
            parts=parts,
            nets=nets,
            nc=nc,
            open_interfaces=interfaces,
            operating_conditions=_operating_conditions(root),
        )
        _check_stated_draft(root, spec)
        return spec

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_jsonable(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> CircuitSpec:
        """Read a spec file. Every failure is a :class:`CircuitSpecError`."""
        return _load(cls, path)

    def sha256(self) -> str:
        """Digest of the normal form — the input hash a LayoutPlan records."""
        return spec_sha256(self)


def spec_sha256(spec: CircuitSpec) -> str:
    """sha256 of the spec's canonical JSON: what a LayoutPlan pins as its source.

    Canonical means sorted keys and no whitespace, over the **normal form**
    rather than the raw file: a re-indented file, or one whose keys were
    reordered, hashes the same — while a changed fact does not, including a
    changed net class or provenance. A plan built from a verified spec is
    therefore not the plan built from the same circuit stated as an AI guess.
    """
    text = json.dumps(
        spec.to_jsonable(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- parts


def _parts_from(root: dict[str, Any]) -> list[SpecPart]:
    raw = _list(root.get("parts"), "parts")
    if not raw:
        raise CircuitSpecError(
            "$.parts is empty — a circuit with no parts is not a circuit"
        )
    parts: list[SpecPart] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        spot = f"parts[{index}]"
        body = _object(item, spot)
        _check_keys(body, _PART_KEYS, spot)
        part_id = _text(body.get("id"), f"{spot}.id", required=True)
        if "." in part_id:
            raise CircuitSpecError(
                f"{spot}.id is {part_id!r}, which contains '.' — a member is "
                "written '<partId>.<pin>', so a dotted part id cannot be split "
                "back unambiguously"
            )
        if part_id in seen:
            raise CircuitSpecError(
                f"{spot}.id is {part_id!r}, already used — one id is one part"
            )
        seen.add(part_id)
        parts.append(SpecPart(
            id=part_id,
            symbol_ref=_text(body.get("symbolRef"), f"{spot}.symbolRef", required=True),
            value=_text(body.get("value"), f"{spot}.value"),
            mpn=_text(body.get("mpn"), f"{spot}.mpn"),
            lcsc=_text(body.get("lcsc"), f"{spot}.lcsc"),
            params=_string_map(body.get("params"), f"{spot}.params"),
            provenance=_provenance(body.get("provenance"), f"{spot}.provenance"),
        ))
    return parts


# ---------------------------------------------------------------------- nets


def _nets_from(root: dict[str, Any], parts: dict[str, SpecPart]) -> list[SpecNet]:
    """Declared nets plus the `connections` sugar, normalised into one partition.

    One union-find over pins:

    1. every declared net's members are checked (a pin sits on one declared net
       only, and a repeated member is refused) and registered;
    2. every connection unions its two pins; a component that ends up touching
       two *named* nets is refused, because joining them would need a name the
       spec does not give;
    3. a component that touches a declared net joins it, and a component that
       touches none becomes a synthesized net;
    4. a pin's provenance is the weakest label any fact about it carried, and a
       net is no more confirmed than its weakest member.

    The named-net merge check is done on the finished components rather than per
    connection: two named nets can be joined *indirectly*, through a chain of
    unnamed pins, which no per-connection check would see.
    """
    union = _UnionFind()
    declared: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, item in enumerate(_list(root.get("nets"), "nets")):
        spot = f"nets[{index}]"
        body = _object(item, spot)
        _check_keys(body, _NET_KEYS, spot)
        net_id = _text(body.get("id"), f"{spot}.id", required=True)
        if net_id in declared:
            raise CircuitSpecError(
                f"{spot}.id is {net_id!r}, already declared — one id is one net"
            )
        cls = body.get("class", DEFAULT_NET_CLASS)
        if cls not in NET_CLASSES:
            raise CircuitSpecError(
                f"{spot}.class is {cls!r}; expected one of {', '.join(NET_CLASSES)}"
            )
        scope = body.get("scope", "")
        if scope not in ("", *NET_SCOPES):
            raise CircuitSpecError(
                f"{spot}.scope is {scope!r}; expected one of "
                f"{', '.join(NET_SCOPES)}, or empty when the spec does not say"
            )
        members = _pin_list(body.get("members"), f"{spot}.members", parts)
        if not members:
            raise CircuitSpecError(
                f"{spot}.members is empty — a net that connects nothing is not a net"
            )
        for pin in members:
            union.find(pin)  # declared pins take part in the merge below
        declared[net_id] = {
            "cls": cls,
            "scope": scope,
            "provenance": _provenance(body.get("provenance"), f"{spot}.provenance"),
            "member_provenance": _member_provenance(
                body.get("memberProvenance"), members, f"{spot}.memberProvenance"
            ),
            "members": list(members),
        }
        order.append(net_id)
    _check_one_net_per_pin(declared)

    owner = {
        pin: net_id
        for net_id, info in declared.items()
        for pin in info["members"]
    }

    labels: dict[str, str] = {}
    for index, item in enumerate(_list(root.get("connections"), "connections")):
        spot = f"connections[{index}]"
        body = _object(item, spot)
        _check_keys(body, _CONNECTION_KEYS, spot)
        left = _pin_ref(body.get("from"), f"{spot}.from", parts)
        right = _pin_ref(body.get("to"), f"{spot}.to", parts)
        if left == right:
            raise CircuitSpecError(
                f"{spot} connects {left} to itself — a pin cannot be its own "
                "connection"
            )
        provenance = _provenance(body.get("provenance"), f"{spot}.provenance")
        union.union(left, right)
        for pin in (left, right):
            # The first label for a pin is the label; folding it against the
            # default "" would throw it away ("" is the weakest, by design).
            known = labels.get(pin)
            labels[pin] = provenance if known is None else _weaker(known, provenance)

    nets = [
        SpecNet(
            id=net_id,
            cls=declared[net_id]["cls"],
            members=list(declared[net_id]["members"]),
            provenance=declared[net_id]["provenance"],
            member_provenance=dict(declared[net_id]["member_provenance"]),
            scope=declared[net_id]["scope"],
        )
        for net_id in order
    ]
    by_id = {net.id: net for net in nets}
    synthesized: list[SpecNet] = []

    for members in union.components():
        touched: list[str] = []
        for pin in members:
            net_id = owner.get(pin)
            if net_id and net_id not in touched:
                touched.append(net_id)
        if len(touched) > 1:
            raise CircuitSpecError(
                "the connections sugar would merge "
                + " and ".join(repr(name) for name in sorted(touched))
                + " into one node (" + ", ".join(members) + ") — joining two "
                "named nets needs a name this spec does not give; declare one net "
                "with every member instead"
            )
        if touched:
            net = by_id[touched[0]]
            for pin in members:
                if pin not in net.members:
                    # The sugar speaks about pins the declared net did not list.
                    # Refusing them would be the other silent choice: they are
                    # part of the same node by construction (step 2).
                    net.members.append(pin)
                if pin in labels:
                    net.member_provenance[pin] = _weaker(
                        net.member_provenance.get(pin, net.provenance), labels[pin]
                    )
            continue
        if len(members) == 1:
            raise CircuitSpecError(
                f"the connections sugar left {members[0]} on a node of its own — "
                "a connection always has two distinct ends"
            )
        net_id = _auto_net_id(members)
        if net_id in by_id:
            raise CircuitSpecError(f"two synthesized nets both computed id {net_id!r}")
        net = SpecNet(
            id=net_id,
            cls=DEFAULT_NET_CLASS,
            members=list(members),
            provenance=_weakest_first(labels.get(pin, "") for pin in members) or "",
        )
        synthesized.append(net)
        by_id[net_id] = net

    synthesized.sort(key=lambda net: net.id)
    nets.extend(synthesized)

    # Canonical: a net is as confirmed as its weakest member, and a member entry
    # equal to the net's own provenance carries no information.
    for net in nets:
        weakest_member = _weakest_first(net.member_provenance.values())
        if weakest_member is not None:
            net.provenance = _weaker(net.provenance, weakest_member)
        net.member_provenance = {
            pin: label
            for pin, label in sorted(net.member_provenance.items())
            if label != net.provenance
        }
    return nets


def _auto_net_id(members: Iterable[str]) -> str:
    """A synthesized net's id **is** its partition.

    Deliberately membership-derived: the partition is the fact, and an id that
    survived a membership change would name something no longer true (052
    sec.4's reason for comparing partitions rather than auto net names). Sorted,
    so the id does not depend on the order the sugar happened to be written in.
    """
    return AUTO_NET_PREFIX + "|".join(sorted(members))


def _check_one_net_per_pin(declared: dict[str, dict[str, Any]]) -> None:
    seen: dict[str, str] = {}
    for net_id, info in declared.items():
        for pin in info["members"]:
            if pin in seen:
                raise CircuitSpecError(
                    f"{pin} is a member of both {seen[pin]!r} and {net_id!r} — one "
                    "pin is on one node, and two nets claiming it is a short"
                )
            seen[pin] = net_id


def _member_provenance(value: Any, members: list[str], where: str) -> dict[str, str]:
    if value is None:
        return {}
    body = _object(value, where)
    out: dict[str, str] = {}
    for pin, raw in body.items():
        if pin not in members:
            raise CircuitSpecError(
                f"{where} names {pin!r}, which is not a member of this net "
                f"({', '.join(members)})"
            )
        out[pin] = _provenance(raw, f"{where}.{pin}")
    return out


# ------------------------------------------------------------------------ nc


def _nc_from(
    root: dict[str, Any], parts: dict[str, SpecPart], nets: list[SpecNet]
) -> list[SpecNoConnect]:
    """Explicit no-connects. A pin on a net may not also be NC.

    Two spellings are accepted: the book's plain ``"<partId>.<pin>"`` (which
    states no basis, and therefore makes the spec a draft) and an object with
    its own ``provenance``.
    """
    out: list[SpecNoConnect] = []
    for index, item in enumerate(_list(root.get("nc"), "nc")):
        spot = f"nc[{index}]"
        if isinstance(item, str):
            out.append(SpecNoConnect(pin=_pin_ref(item, spot, parts), provenance=""))
            continue
        body = _object(item, spot)
        _check_keys(body, _NC_KEYS, spot)
        out.append(SpecNoConnect(
            pin=_pin_ref(body.get("pin"), f"{spot}.pin", parts),
            provenance=_provenance(body.get("provenance"), f"{spot}.provenance"),
        ))
    seen: set[str] = set()
    for item in out:
        if item.pin in seen:
            raise CircuitSpecError(
                f"nc lists {item.pin} twice — one pin, one no-connect claim"
            )
        seen.add(item.pin)
    connected = {pin for net in nets for pin in net.members}
    for item in out:
        if item.pin in connected:
            net_id = next(net.id for net in nets if item.pin in net.members)
            raise CircuitSpecError(
                f"nc says {item.pin} is not connected but it is a member of net "
                f"{net_id!r} — NC is explicit precisely so it cannot contradict "
                "the wiring (053 sec.2)"
            )
    return out


# ------------------------------------------------------------ open interfaces


def _interfaces_from(root: dict[str, Any], net_ids: set[str]) -> list[SpecOpenInterface]:
    out: list[SpecOpenInterface] = []
    for index, item in enumerate(_list(root.get("openInterfaces"), "openInterfaces")):
        spot = f"openInterfaces[{index}]"
        body = _object(item, spot)
        _check_keys(body, _INTERFACE_KEYS, spot)
        net_id = _text(body.get("net"), f"{spot}.net", required=True)
        if net_id not in net_ids:
            raise CircuitSpecError(
                f"{spot}.net is {net_id!r}, which is not one of this spec's nets "
                f"({', '.join(sorted(net_ids)) or 'none'})"
            )
        direction = body.get("direction", "")
        if direction not in ("", *PORT_DIRECTIONS):
            raise CircuitSpecError(
                f"{spot}.direction is {direction!r}; expected one of "
                f"{', '.join(PORT_DIRECTIONS)}, or empty when the spec does not say"
            )
        out.append(SpecOpenInterface(
            net=net_id,
            direction=direction,
            role=_text(body.get("role"), f"{spot}.role", required=True),
            provenance=_provenance(body.get("provenance"), f"{spot}.provenance"),
            # 088's optional key. Not checked against `parts` here on purpose:
            # naming a part that does not exist is a circuit the *grammar*
            # refuses with its own wording, and a parser that guessed would
            # take that message away from the layer that can explain it.
            part=_text(body.get("part"), f"{spot}.part"),
        ))
    return out


def _operating_conditions(root: dict[str, Any]) -> dict[str, Any]:
    value = root.get("operatingConditions")
    if value is None:
        return {}
    body = _object(value, "operatingConditions")
    out: dict[str, Any] = {}
    for key, item in body.items():
        if not isinstance(item, (str, int, float)) or isinstance(item, bool):
            raise CircuitSpecError(
                f"operatingConditions.{key} is {item!r}; expected a number or a "
                "string — the slot is reserved for flat working conditions "
                "(voltage / current / frequency), and a nested shape would be a "
                "guess about what a later stage wants"
            )
        out[str(key)] = item
    return out


def _check_stated_draft(root: dict[str, Any], spec: CircuitSpec) -> None:
    """A stated `draft` may be stricter than the derived one, never looser."""
    if "draft" not in root:
        return
    stated = root["draft"]
    if not isinstance(stated, bool):
        raise CircuitSpecError(
            f"$.draft must be a boolean, got {stated!r} — it is derived from the "
            "spec's provenance, not chosen"
        )
    if not stated and spec.draft:
        raise CircuitSpecError(
            "$.draft is false but this spec is a draft: "
            + "; ".join(spec.draft_reasons[:3])
            + " (052 sec.4: an unconfirmed electrical claim may leave the tool "
            "only as an explicitly labelled draft)"
        )


# ------------------------------------------------------------------ helpers


def _draft_lines(provenance: str, what: str) -> list[str]:
    if provenance == PROVENANCE_AI:
        return [
            f"{what}: ai_asserted — an unconfirmed electrical claim may leave the "
            "tool only as an explicitly labelled draft (052 sec.4)"
        ]
    if not provenance:
        # Covers both readings of "": the fact stated nothing, or it was weakened
        # by a fact it is built from. Naming only the first would misreport a
        # declared net that an unlabelled connection joined.
        return [
            f"{what}: no confirmed basis (no provenance stated, or weakened by a "
            "fact it is built from) — abstaining from a claim is not evidence for "
            "one, so this spec is a draft until a basis is named"
        ]
    return []


def _weaker(left: str, right: str) -> str:
    """The weaker of two provenance labels; "" (unstated) is the weakest."""
    rank_left = _PROVENANCE_RANK.get(left, -1) if left else -1
    rank_right = _PROVENANCE_RANK.get(right, -1) if right else -1
    return left if rank_left <= rank_right else right


def _weakest_first(values: Iterable[str]) -> str | None:
    """The weakest of the labels, or ``None`` when there were none.

    ``None`` and ``""`` are different answers and the callers need both: no
    labels at all means "this fold says nothing", while a label of ``""`` is an
    unstated basis that has to weaken whatever it joins.
    """
    out: str | None = None
    for value in values:
        out = value if out is None else _weaker(out, value)
    return out


def _provenance(value: Any, where: str) -> str:
    """One fact's basis: the three-state, or "" for "the spec does not say".

    An explicit ``""`` is the same answer as an absent key, and is accepted so
    that a document written by :meth:`CircuitSpec.to_jsonable` reads back
    byte-identically (the writer always names the field, so that a reader of the
    file sees the unstated basis rather than a gap).
    """
    if value is None:
        return ""
    if not isinstance(value, str) or (value and value not in PROVENANCE_KINDS):
        raise CircuitSpecError(
            f"{where} is {value!r}; expected one of {', '.join(PROVENANCE_KINDS)}, or "
            "absent — a fact whose basis is not stated is a draft (052 sec.4), "
            "which is not the same as a fact that is confirmed"
        )
    return value


def _pin_ref(value: Any, where: str, parts: dict[str, SpecPart]) -> str:
    text = _text(value, where, required=True)
    part_id, _, pin = text.partition(".")
    if not part_id or not pin:
        raise CircuitSpecError(f"{where} is {text!r}; a pin is written '<partId>.<pin>'")
    if part_id not in parts:
        raise CircuitSpecError(
            f"{where} names part {part_id!r}, which this spec does not declare "
            f"({', '.join(sorted(parts))}) — a connection to a part that does not "
            "exist is a connection to nothing"
        )
    return f"{part_id}.{pin}"


def _pin_list(value: Any, where: str, parts: dict[str, SpecPart]) -> list[str]:
    raw = _list(value, where)
    return [_pin_ref(item, f"{where}[{index}]", parts) for index, item in enumerate(raw)]


def _string_map(value: Any, where: str) -> dict[str, str]:
    if value is None:
        return {}
    body = _object(value, where)
    out: dict[str, str] = {}
    for key, item in body.items():
        if not isinstance(item, str):
            raise CircuitSpecError(
                f"{where}.{key} is {item!r}; a parameter value must be a string as "
                "written on the part (the repo has read a display value as a "
                "quantity twice already — 046/048 — so the spec does not do it "
                "implicitly)"
            )
        out[str(key)] = item
    return out


class _UnionFind:
    """Minimal union-find over pin strings, with a canonical component order."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, node: str) -> str:
        self._parent.setdefault(node, node)
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:  # path compression
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self._parent[root_right] = root_left

    def components(self) -> list[list[str]]:
        groups: dict[str, list[str]] = {}
        for node in self._parent:
            groups.setdefault(self.find(node), []).append(node)
        return [sorted(group) for _, group in sorted(groups.items())]


def _refuse_coordinates(payload: Any, path: str) -> None:
    """No coordinate may appear in a CircuitSpec, anywhere (052 sec.4).

    A CircuitSpec is meaning; where things sit is compiled, not asserted. The
    walk runs on the raw payload before parsing so the refusal can name the
    offending path — the key is refused, not cleaned away.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            spot = f"{path}.{key}"
            if key in _COORDINATE_KEYS:
                raise CircuitSpecError(
                    f"{spot} is a coordinate-shaped key ({key!r}) and a CircuitSpec "
                    "is meaning, not geometry — placement is compiled from the "
                    "spec (052 sec.4), and the only place a coordinate is accepted "
                    "in this pipeline is PresentationSpec.userLocks"
                )
            _refuse_coordinates(value, spot)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _refuse_coordinates(value, f"{path}[{index}]")


def _load(cls: Any, path: str | Path) -> Any:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise CircuitSpecError(f"{source}: cannot be read ({exc})") from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise CircuitSpecError(f"{source}: is not JSON ({exc})") from exc
    try:
        return cls.from_dict(payload)
    except CircuitSpecError as exc:
        raise CircuitSpecError(f"{source}: {exc}") from exc


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CircuitSpecError(
            f"{where} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CircuitSpecError(f"$.{where} must be a list, got {value!r}")
    return value


def _text(value: Any, where: str, required: bool = False) -> str:
    if value is None:
        if required:
            raise CircuitSpecError(f"{where} is required and missing")
        return ""
    if not isinstance(value, str):
        raise CircuitSpecError(f"{where} must be a string, got {value!r}")
    if required and not value.strip():
        raise CircuitSpecError(f"{where} is empty")
    return value.strip()


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise CircuitSpecError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(allowed)} — the schema is closed on purpose: a key this "
            "build does not read would otherwise be a fact nobody checks"
        )

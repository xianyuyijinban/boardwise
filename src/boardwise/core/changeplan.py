"""ChangePlan: the contract between a review finding and a local edit (016).

The M3 loop is *read -> find -> explain -> preview a local change -> the user
authorises it -> change only the parts involved -> read back -> review again*.
This module owns the middle of it: the plan a human authorises, its JSON form,
and the read-only helpers the three `boardwise edit` commands share.

Two decisions worth stating here, because everything else follows from them:

* **A model never writes an API call directly.** The plan is data — a
  designator, a before and an after — validated on load. An executable plan is
  therefore inspectable, diffable and refusable *before* anything touches the
  editor, which is what makes the four protections (016 sec.4) checkable.
* **The plan carries a designator, not a primitiveId.** Measured: the offline
  parser's ``Component.uid`` is the symbol uuid / part id
  (``parsers/schematic.py``), and a designator -> live primitiveId resolution
  only exists inside the connector (``actions.ts``, the review.mark geometry
  path). So the id is resolved **at apply time** from ``sch.geometry`` on the
  guarded page, and the plan admits it does not know it. This is the one
  deliberate deviation from the schema as first written, and it is a fact about
  the data rather than a preference.

Nothing here talks to the bridge: the module is offline and pure so the plan
format can be tested — and refused — without a daemon, an editor or a socket.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ADD_COMPONENT_KIND",
    "COMPONENT_VALUE_KIND",
    "CONNECTION_KINDS",
    "CONNECTION_LABEL",
    "CONNECTION_POWER_FLAG",
    "CONNECTION_WIRE",
    "INSERT_SUBCIRCUIT_KIND",
    "INSERT_TEMPLATES",
    "MOVE_BLOCK_KIND",
    "MOVE_GRID",
    "PLAN_VERSION",
    "SUPPORTED_KINDS",
    "TEMPLATE_DIVIDER",
    "TEMPLATE_RC_LOWPASS",
    "ChangePlan",
    "ChangePlanError",
    "PageComponent",
    "PageLookup",
    "ATTACHMENT_KINDS",
    "PATCH_PIN_KIND",
    "PlanAttachment",
    "PlanChange",
    "PlanConnection",
    "PlanIsland",
    "PlanMove",
    "PlanPart",
    "PlanSource",
    "PlanTarget",
    "PlanWireOp",
    "add_component_plan",
    "component_value_plan",
    "insert_subcircuit_plan",
    "move_block_plan",
    "patch_pin_plan",
    "resolve_on_page",
    "sha256_of",
]

#: The plan schema version this build reads. A plan from a future build is
#: refused rather than half-understood: the fields are the contract.
PLAN_VERSION = 1

#: The change kinds this build executes. `add-component` joined in 029-a: it
#: creates a part (place + connect + designator) where `component-value` only
#: rewrote an attribute, which is why the plan grew a part/connection payload and
#: why apply grew a second flow (see `core/addcomponent.py`).
COMPONENT_VALUE_KIND = "component-value"
ADD_COMPONENT_KIND = "add-component"
#: 035: one pin's connection repaired — disconnect what should not be there,
#: connect what should be, or both (the shelf's NC / must_connect obligations).
PATCH_PIN_KIND = "patch-pin"
#: 036: a whole sub-circuit inserted — two parts, their wiring, and (for
#: `rc-lowpass`) the wire that has to come off first. The first kind with **no
#: driving rule**: the plan states its own postconditions and they are what the
#: idempotence probe and the read-back read (there is no rule to re-run).
INSERT_SUBCIRCUIT_KIND = "insert-subcircuit"
#: 037: a block moved locally — the last M3 slice, and the second kind with no
#: driving rule. The caller names the group and the delta; the plan records every
#: part's pose before it moves, the wires it will redraw, and its own
#: postconditions (the poses *and* the netlist identity).
MOVE_BLOCK_KIND = "move-block"
SUPPORTED_KINDS: tuple[str, ...] = (
    COMPONENT_VALUE_KIND,
    ADD_COMPONENT_KIND,
    PATCH_PIN_KIND,
    INSERT_SUBCIRCUIT_KIND,
    MOVE_BLOCK_KIND,
)

#: The routing/landing grid a local move has to stay on (029's
#: `engines/layout.GRID`, echoed here because `core` may not import `engines`).
#: A delta off this grid leaves the moved pins off-grid, and the wire redrawn to
#: them can never join the old routing cleanly.
MOVE_GRID = 5.0

#: 036: the sub-circuit templates this build can insert. The vocabulary lives
#: beside the other kinds' vocabularies rather than in `engines/subcircuit.py`
#: because the *plan's validation* has to refuse a template this build cannot
#: execute, and `core` may not import `engines` (tests/test_layer_rules.py).
TEMPLATE_RC_LOWPASS = "rc-lowpass"
TEMPLATE_DIVIDER = "divider"
INSERT_TEMPLATES: tuple[str, ...] = (TEMPLATE_RC_LOWPASS, TEMPLATE_DIVIDER)

#: Where the *other* kinds belong, quoted in the refusal so the reader is not
#: left guessing whether the plan is broken or merely early. Empty since 037:
#: every M3 kind is executable now, and the refusal text says so without a hint
#: (an empty table must not print "one of the M3 follow-ups").
_LATER_KINDS = {}

#: What a `patch-pin` disconnect may take off a pin (035 §2). Two, and both have
#: to be *proven on the canvas*: a wire whose endpoint lands exactly on the pin,
#: or a net label sitting exactly on it. Anything else — a wire passing through
#: the pin mid-segment, a net flag, a second attachment — is a refusal, because a
#: repair that deletes the wrong thing is worse than no repair.
ATTACHMENT_WIRE = "wire"
ATTACHMENT_NETLABEL = "netlabel"
ATTACHMENT_KINDS: tuple[str, ...] = (ATTACHMENT_WIRE, ATTACHMENT_NETLABEL)

#: How an added part is connected to the net it decouples. Three, and each one
#: is a claim about what will be on the page:
#:
#: * `wire` draws a short segment from the part's own pin to an existing segment
#:   of that net;
#: * `label` puts the page's own name for that net on a stub (only where the page
#:   already names it that way — a name is a convention, not a connection);
#: * `power-flag` places a real ground/power symbol on the pin (029-d). It is the
#:   only mechanism that can *create* a rail connection where the page has none,
#:   and it is a library component, so the editor's own netlist carries it.
#:
#: There is no "whichever works" option: an all-pin label would *look* connected
#: while saying nothing about where the current goes (岳 M2 red line), and a
#: dangling wire named after the net is the same lie in copper (029-d forbids it
#: by name).
CONNECTION_WIRE = "wire"
CONNECTION_LABEL = "label"
CONNECTION_POWER_FLAG = "power-flag"
CONNECTION_KINDS: tuple[str, ...] = (CONNECTION_WIRE, CONNECTION_LABEL, CONNECTION_POWER_FLAG)

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")


class ChangePlanError(Exception):
    """The plan is not a plan this build can execute.

    Every message names the field and the reason: this exception is what the
    CLI turns into exit code 5, and "invalid plan" alone would send the reader
    back to the schema with nothing to compare against.
    """


def sha256_of(path: str | Path) -> str:
    """Hex digest of a file's bytes, read in chunks.

    The plan's ``inputSha256`` is the *whole file*, not the parsed model: the
    protection it buys is "the snapshot this plan was built against is still
    the file on disk", and a byte-exact question has a byte-exact answer.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class PlanSource:
    """What the plan was built from, so a stale plan can be refused."""

    input_sha256: str = ""
    project_uuid: str = ""
    page_uuid: str = ""
    host_version: str = ""
    connector_version: str = ""


@dataclass
class PlanTarget:
    """The component the plan touches — for both kinds, with two readings.

    `component-value`: the one component whose attribute changes.
    `add-component`: the component the plan will *create* (`designator` is the
    assigned one) plus the anchor it hangs off — the missing decoupling
    capacitor and the IC whose supply pin needs it. The placement and connection
    fields are empty for `component-value`, so a value plan serialises exactly
    the shape it always did.

    ``primitive_id`` is empty offline by construction (see the module
    docstring) and is filled in by the apply report, never by the plan: for
    `add-component` the primitive does not exist yet, which is the 016 §二.3
    lesson in its purest form.
    """

    designator: str = ""
    primitive_id: str = ""
    expected_value: str = ""
    #: `patch-pin` only: **which pin** of `designator` the plan repairs. A pin
    #: is named by its component plus this number, which is the pair the findings
    #: and the netlist both speak (035 §二).
    pin: str = ""
    #: `add-component` only: the anchor this part is added for (the IC whose
    #: supply pin the finding named).
    anchor: str = ""
    #: `add-component` only: the designator the apply will *set* when it places
    #: the part. Equal to `designator` today; kept separate so a future slice can
    #: let the editor renumber without the meaning of `designator` drifting.
    assigned_designator: str = ""
    #: `add-component` only: the landing spot, in canvas units (the same grid
    #: `sch.place_component` and `sch.geometry` speak).
    x: float | None = None
    y: float | None = None
    #: `add-component` only: one of CONNECTION_KINDS. A summary of the first
    #: declared connection (the plan's oldest shape, kept so a reader of the
    #: target block alone still learns the mode); since 029-c the
    #: **per-connection** ``change.connections[*].kind`` is what apply executes,
    #: and the two differ whenever a plan mixes a wire with a flag.
    connection: str = ""
    #: Why that connection, in one line (the segment it reaches, the label it
    #: copies, or the flag it places). Written into the plan because "it
    #: connected somehow" is not a reviewable claim.
    connection_detail: str = ""
    #: `insert-subcircuit` only: the **net** a `divider` hangs off, when the
    #: anchor is not a component pin at all (036's second template starts from a
    #: net's own wire, not from a part). Exactly one of (designator, pin) /
    #: anchor_net is set, and the validation enforces it.
    anchor_net: str = ""


@dataclass
class PlanPart:
    """The part to place, as the shelf or the operator stated it (029 §二.2).

    `insert-subcircuit` places **two** of these at once, so the fields the
    single-part kinds could keep in the target block — which part, and where it
    lands — live here for that kind: ``designator`` (allocated from the page's
    own pool), ``role`` (which slot of the template this is) and the landing
    coordinates. The 029 shape is untouched: those keys are written only for the
    insert kind, and a 029 plan still serialises exactly what it always did.
    """

    lcsc: str = ""
    value: str = ""
    footprint: str = ""
    designator: str = ""
    role: str = ""
    x: float | None = None
    y: float | None = None
    #: `insert-subcircuit` only: the rotation the template asks for, in degrees.
    #: `divider`'s second resistor is turned 180° so the two pins that form the
    #: tap face each other; apply places the part with exactly this rotation.
    rotation: int = 0


@dataclass
class PlanConnection:
    """One pin of the new part, the net it must reach, **and how** (029-c §①).

    ``kind`` is not optional for an `add-component` plan: 029-b measured what a
    plan without it does — the ground end was left to "whatever the landing spot
    happened to touch", the netlist readback said `2→GND MISSING`, and the run
    failed after placing a part. Every declared connection now carries its own
    decision, its own evidence line and (for a wire) the point it reaches, so
    apply executes exactly what the human authorised — one connection at a time.
    """

    pin: str = ""
    net: str = ""
    kind: str = ""      # wire | label | power-flag; required by the validation
    detail: str = ""
    #: Where a `wire` connection ends (a vertex of that net's own wiring). A
    #: `power-flag` reaches a coordinate too — the *pin's own* — but that one is
    #: not known until the part is placed, so apply reads it there rather than
    #: pretending the plan could have known it.
    to: tuple[float, float] | None = None
    #: `insert-subcircuit` only: which of the plan's parts this pin belongs to.
    #: 029 had exactly one part, so `pin` alone was unambiguous; a two-part
    #: insert is not, and "1" meaning R1.1 or C1.1 depending on position is the
    #: kind of ambiguity that plans exist to remove.
    designator: str = ""
    #: `insert-subcircuit` only: the wire ends on **another plan part's pin**,
    #: named ``<designator>.<pin>``. Both ends of such a wire belong to parts this
    #: plan places, so neither coordinate exists until apply reads them back.
    to_pin: str = ""


@dataclass
class PlanMove:
    """One part of a `move-block`, as a pose before and a point after (037 §1).

    ``from_`` is the pose the plan was built on — x, y **and rotation** — because
    that is the stale judgement at apply time: a part somebody nudged by hand is
    no longer the part this plan measured, and moving it by the planned delta
    would land it somewhere nobody authorised. ``to`` is where it goes; the
    rotation does not change (a local move translates, it does not re-orient).
    """

    designator: str = ""
    primitive_id: str = ""
    from_at: tuple[float, float] | None = None
    from_rotation: float = 0.0
    to_at: tuple[float, float] | None = None


@dataclass
class PlanWireOp:
    """One wire a `move-block` takes off and draws again (037 §1, heavy path).

    Why redraw at all is measured, not assumed: on 3.2.186 ``sch.modify_primitive``
    moves the part and leaves the wire where it was (probe, `outputs/037_probe.txt`),
    so the connection would break. ``points_before`` is what the wire is today and
    ``points_after`` what it becomes — same shape shifted by the delta for a wire
    inside the group, an orthogonal route from the moved pin to the **original far
    point** for a wire that leaves the group. ``net`` is carried so the redrawn
    wire joins the same net it did (and an unnamed wire stays unnamed).
    """

    primitive_id: str = ""
    kind: str = "redraw"
    net: str = ""
    points_before: list[tuple[float, float]] = field(default_factory=list)
    points_after: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class PlanIsland:
    """One moved pin and the pins it shared a net with (037's netlist identity).

    Stored as **pins**, never as net names: an auto-named net is renumbered by the
    editor whenever the wiring changes (measured 035/036), and equality of two
    meaningless names is not evidence. "Which pins are together" is the fact the
    move has to preserve, so that is what the plan records and what the probe
    re-reads.
    """

    pin: str = ""
    mates: list[str] = field(default_factory=list)


@dataclass
class PlanAttachment:
    """The thing a `patch-pin` disconnect takes off a pin (035 §2).

    ``primitive_id`` is the canvas id that will be deleted, and ``at`` is the
    coordinate that *proves* the attachment lands on the pin — recorded in the
    plan because "there was something attached" is not reviewable, and because
    apply re-checks it before deleting anything.
    """

    kind: str = ""          # wire | netlabel — see ATTACHMENT_KINDS
    primitive_id: str = ""
    detail: str = ""
    at: tuple[float, float] | None = None


@dataclass
class PlanChange:
    """The change itself, in whichever shape its kind uses.

    `component-value` reads ``before``/``after``; `add-component` reads
    ``part``, ``connections`` and ``recipe_source``. Both are kept on one class
    because the *contract* is one class — a plan is one authorised change — and
    a second class would fork every reader (validation, serialisation, the
    refusal text, apply's dispatch) to save two empty fields.
    """

    kind: str = COMPONENT_VALUE_KIND
    before: str = ""
    after: str = ""
    part: PlanPart | None = None
    connections: list[PlanConnection] = field(default_factory=list)
    #: `insert-subcircuit` only: which template this is (036's vocabulary lives
    #: beside the other kind constants), and the parts it places — plural, which
    #: is why this kind carries its own ``parts`` rather than 029's single
    #: ``part``. A plan is readable as *what will be on the board afterwards*:
    #: template, parts with values and numbers and landing spots, connections,
    #: and whatever has to come off first.
    template: str = ""
    parts: list[PlanPart] = field(default_factory=list)
    #: `insert-subcircuit` only: the findings the project reported when the plan
    #: was built, as rule/subject/message signatures. apply re-runs every rule on
    #: a fresh export afterwards and refuses to save when the set **grew** — an
    #: insert may resolve findings or leave them, never create one (there is no
    #: rule for this kind, so "did it break something?" has to be answered by the
    #: rules that do exist).
    baseline_findings: list[str] = field(default_factory=list)
    #: `move-block` only: every part's pose before and after, in plan order, and
    #: the wires the run takes off and draws again. Together they are the whole
    #: change: "which parts move where, which wires follow".
    moves: list[PlanMove] = field(default_factory=list)
    wire_ops: list[PlanWireOp] = field(default_factory=list)
    #: `move-block` only: for every pin of every moved part, the pins it shared a
    #: net with when the plan was built. This is the netlist-identity claim — a
    #: move must not change any connection (037 §一, the acceptance's main
    #: judgement) — and it is checkable before the writes too, which is how the
    #: probe answers `already_applied`.
    islands: list[PlanIsland] = field(default_factory=list)
    #: `patch-pin` only: the net the pin is on today ("" = it reaches none) and
    #: the net it must end up on ("" = the repair is to **disconnect** it). The
    #: two together are the plan's whole claim, and `before != after` is
    #: enforced — a plan that changes nothing is not a change.
    before_net: str = ""
    after_net: str = ""
    #: `patch-pin` only: what the disconnect leg removes. Required whenever
    #: `before_net` is non-empty: leaving a net means taking off the thing that
    #: attaches the pin to it, and adding a *new* connection while the old one is
    #: still there would short the two nets together.
    attachment: PlanAttachment | None = None
    #: Where the part came from: ``facts:<lcsc>`` when the shelf supplied it,
    #: ``operator:<lcsc>`` when ``--lcsc`` did. Recorded rather than implied,
    #: because the acceptance question "was this a verified recipe?" is
    #: unanswerable from the part fields alone.
    recipe_source: str = ""


@dataclass
class ChangePlan:
    """One authorised local change, as data.

    ``preconditions`` and ``expected_postcondition`` are prose for the human
    who signs the plan; each one is re-checked by ``edit apply`` (016 sec.3)
    and reported with its own verdict, so a plan cannot quietly stop being
    true between preview and apply.
    """

    source: PlanSource = field(default_factory=PlanSource)
    target: PlanTarget = field(default_factory=PlanTarget)
    change: PlanChange = field(default_factory=PlanChange)
    preconditions: list[str] = field(default_factory=list)
    expected_postcondition: list[str] = field(default_factory=list)
    plan_version: int = PLAN_VERSION

    # ---------------------------------------------------------------- JSON

    def to_jsonable(self) -> dict[str, Any]:
        """The schema as written (camelCase, 016 sec.2.2).

        Kind-aware on purpose: a `component-value` plan serialises **exactly** the
        five keys it always did (a round-trip test pins that equality), and the
        `add-component` keys appear only for that kind. Adding "empty" keys to
        every plan would have made every 016 plan a slightly different document
        than the one its own tests describe.
        """
        target: dict[str, Any] = {
            "primitiveId": self.target.primitive_id,
            "designator": self.target.designator,
            "expectedValue": self.target.expected_value,
        }
        change: dict[str, Any] = {
            "kind": self.change.kind,
            "before": self.change.before,
            "after": self.change.after,
        }
        if self.change.kind == PATCH_PIN_KIND:
            target.update({"pin": self.target.pin})
            change = {
                "kind": self.change.kind,
                "beforeNet": self.change.before_net,
                "afterNet": self.change.after_net,
                "connections": [
                    {
                        "pin": item.pin,
                        "net": item.net,
                        "kind": item.kind,
                        "detail": item.detail,
                        **({"to": list(item.to)} if item.to else {}),
                    }
                    for item in self.change.connections
                ],
                **(
                    {
                        "attachment": {
                            "kind": self.change.attachment.kind,
                            "primitiveId": self.change.attachment.primitive_id,
                            "detail": self.change.attachment.detail,
                            **(
                                {"at": list(self.change.attachment.at)}
                                if self.change.attachment.at
                                else {}
                            ),
                        }
                    }
                    if self.change.attachment
                    else {}
                ),
            }
        if self.change.kind == ADD_COMPONENT_KIND:
            target.update({
                "anchor": self.target.anchor,
                "assignedDesignator": self.target.assigned_designator,
                "x": self.target.x,
                "y": self.target.y,
                "connection": self.target.connection,
                "connectionDetail": self.target.connection_detail,
            })
            change = {
                "kind": self.change.kind,
                "part": {
                    "lcsc": (self.change.part or PlanPart()).lcsc,
                    "value": (self.change.part or PlanPart()).value,
                    "footprint": (self.change.part or PlanPart()).footprint,
                },
                "connections": [
                    {
                        "pin": item.pin,
                        "net": item.net,
                        "kind": item.kind,
                        "detail": item.detail,
                        **({"to": list(item.to)} if item.to else {}),
                    }
                    for item in self.change.connections
                ],
                "recipeSource": self.change.recipe_source,
            }
        if self.change.kind == INSERT_SUBCIRCUIT_KIND:
            target.update({
                "anchor": self.target.anchor,
                "anchorNet": self.target.anchor_net,
                "pin": self.target.pin,
                "x": self.target.x,
                "y": self.target.y,
            })
            change = {
                "kind": self.change.kind,
                "template": self.change.template,
                "parts": [
                    {
                        "designator": item.designator,
                        "role": item.role,
                        "lcsc": item.lcsc,
                        "value": item.value,
                        "footprint": item.footprint,
                        "x": item.x,
                        "y": item.y,
                        "rotation": item.rotation,
                    }
                    for item in self.change.parts
                ],
                "connections": [
                    {
                        "designator": item.designator,
                        "pin": item.pin,
                        "net": item.net,
                        "kind": item.kind,
                        "detail": item.detail,
                        **({"to": list(item.to)} if item.to else {}),
                        **({"toPin": item.to_pin} if item.to_pin else {}),
                    }
                    for item in self.change.connections
                ],
                "beforeNet": self.change.before_net,
                **(
                    {
                        "attachment": {
                            "kind": self.change.attachment.kind,
                            "primitiveId": self.change.attachment.primitive_id,
                            "detail": self.change.attachment.detail,
                            **(
                                {"at": list(self.change.attachment.at)}
                                if self.change.attachment.at
                                else {}
                            ),
                        }
                    }
                    if self.change.attachment
                    else {}
                ),
                "baselineFindings": list(self.change.baseline_findings),
            }
        if self.change.kind == MOVE_BLOCK_KIND:
            target.update({
                "designators": [item.designator for item in self.change.moves],
                "dx": self.target.x,
                "dy": self.target.y,
            })
            change = {
                "kind": self.change.kind,
                "moves": [
                    {
                        "designator": item.designator,
                        "primitiveId": item.primitive_id,
                        "from": {
                            "x": (item.from_at or (0.0, 0.0))[0],
                            "y": (item.from_at or (0.0, 0.0))[1],
                            "rotation": item.from_rotation,
                        },
                        "to": {
                            "x": (item.to_at or (0.0, 0.0))[0],
                            "y": (item.to_at or (0.0, 0.0))[1],
                        },
                    }
                    for item in self.change.moves
                ],
                "wireOps": [
                    {
                        "primitiveId": item.primitive_id,
                        "kind": item.kind,
                        "net": item.net,
                        "pointsBefore": [list(point) for point in item.points_before],
                        "pointsAfter": [list(point) for point in item.points_after],
                    }
                    for item in self.change.wire_ops
                ],
                "islands": [
                    {"pin": item.pin, "mates": list(item.mates)}
                    for item in self.change.islands
                ],
                "baselineFindings": list(self.change.baseline_findings),
            }
        return {
            "planVersion": self.plan_version,
            "source": {
                "inputSha256": self.source.input_sha256,
                "projectUuid": self.source.project_uuid,
                "pageUuid": self.source.page_uuid,
                "hostVersion": self.source.host_version,
                "connectorVersion": self.source.connector_version,
            },
            "target": target,
            "change": change,
            "preconditions": list(self.preconditions),
            "expectedPostcondition": list(self.expected_postcondition),
        }

    @classmethod
    def from_jsonable(cls, payload: Any) -> ChangePlan:
        """Read a plan and refuse anything this build cannot execute.

        The validation is the whole point of the format: an executable plan is
        only safe if "what it means" is decidable before it runs.
        """
        if not isinstance(payload, dict):
            raise ChangePlanError(
                "the plan must be a JSON object, not "
                f"{type(payload).__name__}"
            )
        version = payload.get("planVersion")
        if version != PLAN_VERSION:
            raise ChangePlanError(
                f"planVersion is {version!r}, this build reads {PLAN_VERSION} "
                "— regenerate the plan with `boardwise edit plan`"
            )
        source = _object(payload, "source")
        target = _object(payload, "target")
        change = _object(payload, "change")

        kind = change.get("kind")
        if kind not in SUPPORTED_KINDS:
            later = _LATER_KINDS.get(str(kind))
            hint = (
                f" — {kind!r} is one of the M3 follow-ups ({later}), not part "
                "of task 016's single-device slice"
                if later else ""
            )
            raise ChangePlanError(
                f"change.kind is {kind!r}; this build executes "
                f"{', '.join(SUPPORTED_KINDS)} only{hint}"
            )
        digest = source.get("inputSha256")
        if not isinstance(digest, str) or not _SHA256_RE.match(digest):
            raise ChangePlanError(
                "source.inputSha256 must be 64 hex characters (the sha256 of "
                f"the snapshot the plan was built from), got {digest!r}"
            )
        if kind == INSERT_SUBCIRCUIT_KIND:
            # No `target.designator` requirement here: a `divider` anchors on a
            # **net**, not on a component, so the insert reader checks the pair
            # (designator+pin) / anchorNet itself.
            return cls(
                source=_source_from(source, digest),
                target=_insert_target_from(target),
                change=_insert_change_from(change),
                preconditions=_string_list(payload, "preconditions"),
                expected_postcondition=_string_list(payload, "expectedPostcondition"),
            )
        if kind == MOVE_BLOCK_KIND:
            # Also no `target.designator`: a move is about a *group*, and the
            # group lives in `change.moves` (the target block names it for a
            # reader, and carries the delta the caller asked for).
            return cls(
                source=_source_from(source, digest),
                target=_move_target_from(target),
                change=_move_change_from(change),
                preconditions=_string_list(payload, "preconditions"),
                expected_postcondition=_string_list(payload, "expectedPostcondition"),
            )
        designator = target.get("designator")
        if not isinstance(designator, str) or not designator.strip():
            raise ChangePlanError(
                f"target.designator must name the component, got {designator!r}"
            )
        if kind == PATCH_PIN_KIND:
            return cls(
                source=_source_from(source, digest),
                target=_patch_pin_target_from(target, designator.strip()),
                change=_patch_pin_change_from(change),
                preconditions=_string_list(payload, "preconditions"),
                expected_postcondition=_string_list(payload, "expectedPostcondition"),
            )
        if kind == ADD_COMPONENT_KIND:
            return cls(
                source=_source_from(source, digest),
                target=_add_target_from(target, designator.strip()),
                change=_add_change_from(change),
                preconditions=_string_list(payload, "preconditions"),
                expected_postcondition=_string_list(payload, "expectedPostcondition"),
            )
        before, after = change.get("before"), change.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            raise ChangePlanError(
                "change.before and change.after must both be strings, got "
                f"{before!r} / {after!r}"
            )
        if before == after:
            raise ChangePlanError(
                f"change.before and change.after are both {before!r} — a plan "
                "that changes nothing is not a change"
            )
        if not after:
            # Measured (actions.ts, sch.set_component_attribute): the connector
            # drops empty attribute values, so this plan would report success
            # for a write it never sent. Refused here rather than at the wire.
            raise ChangePlanError(
                "change.after is empty — the connector skips empty attribute "
                "values, so this plan could not do what it says"
            )
        return cls(
            source=_source_from(source, digest),
            target=PlanTarget(
                designator=designator.strip(),
                primitive_id=str(target.get("primitiveId") or ""),
                expected_value=str(target.get("expectedValue") or ""),
            ),
            change=PlanChange(
                kind=str(kind), before=before, after=after,
            ),
            preconditions=_string_list(payload, "preconditions"),
            expected_postcondition=_string_list(
                payload, "expectedPostcondition"
            ),
        )

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_jsonable(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> ChangePlan:
        """Read a plan file. Every failure is a :class:`ChangePlanError`."""
        source_path = Path(path)
        try:
            text = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ChangePlanError(f"{source_path}: cannot be read ({exc})") from exc
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise ChangePlanError(f"{source_path}: is not JSON ({exc})") from exc
        try:
            return cls.from_jsonable(payload)
        except ChangePlanError as exc:
            raise ChangePlanError(f"{source_path}: {exc}") from exc


def _source_from(source: dict[str, Any], digest: str) -> PlanSource:
    """The `source` block both kinds share (016 §2.2)."""
    return PlanSource(
        input_sha256=digest,
        project_uuid=str(source.get("projectUuid") or ""),
        page_uuid=str(source.get("pageUuid") or ""),
        host_version=str(source.get("hostVersion") or ""),
        connector_version=str(source.get("connectorVersion") or ""),
    )


def _add_target_from(target: dict[str, Any], designator: str) -> PlanTarget:
    """Read an `add-component` target, refusing anything apply cannot execute.

    Every field here is one apply *needs*: the anchor to hang the spot off, the
    connection mode so the write is a decision and not a choice made at the
    wire, and the landing coordinates so two runs land in the same place.
    """
    anchor = target.get("anchor")
    if not isinstance(anchor, str) or not anchor.strip():
        raise ChangePlanError(
            "target.anchor must name the component this part is added for "
            f"(the IC whose pin the finding named), got {anchor!r}"
        )
    connection = target.get("connection")
    if connection not in CONNECTION_KINDS:
        raise ChangePlanError(
            "target.connection must be one of "
            f"{', '.join(CONNECTION_KINDS)}, got {connection!r} — the plan has "
            "to say how the part joins its net; \"whichever works\" is the "
            "silent choice this field exists to forbid (029 §二.4)"
        )
    numbers: dict[str, float] = {}
    for name in ("x", "y"):
        value = target.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ChangePlanError(
                f"target.{name} must be a number in canvas units, got {value!r}"
            )
        numbers[name] = float(value)
    return PlanTarget(
        designator=designator,
        primitive_id=str(target.get("primitiveId") or ""),
        expected_value=str(target.get("expectedValue") or ""),
        anchor=anchor.strip(),
        assigned_designator=str(target.get("assignedDesignator") or designator),
        x=numbers["x"],
        y=numbers["y"],
        connection=str(connection),
        connection_detail=str(target.get("connectionDetail") or ""),
    )


def _add_change_from(change: dict[str, Any]) -> PlanChange:
    """Read an `add-component` change: the part and the pins it must reach."""
    part = change.get("part")
    if not isinstance(part, dict):
        raise ChangePlanError(
            f"change.part must be a JSON object, got {type(part).__name__}"
        )
    lcsc = str(part.get("lcsc") or "").strip()
    if not lcsc:
        raise ChangePlanError(
            "change.part.lcsc is empty — a part with no orderable number is not "
            "a recipe, and \"we will work it out at the wire\" is how the wrong "
            "capacitor gets placed (029 §二.2)"
        )
    value = str(part.get("value") or "").strip()
    if not value:
        raise ChangePlanError(
            "change.part.value is empty — the recipe's value is what the "
            "read-back compares and what the re-review judges"
        )
    raw = change.get("connections")
    if not isinstance(raw, list) or len(raw) < 2:
        raise ChangePlanError(
            "change.connections must list at least the part's two pins (the "
            f"net it decouples and its ground), got {raw!r}"
        )
    connections: list[PlanConnection] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ChangePlanError(
                f"change.connections[{index}] must be an object, got {item!r}"
            )
        pin = str(item.get("pin") or "").strip()
        net = str(item.get("net") or "").strip()
        if not pin or not net:
            raise ChangePlanError(
                f"change.connections[{index}] needs both pin and net, got {item!r}"
            )
        kind = item.get("kind")
        if kind not in CONNECTION_KINDS:
            raise ChangePlanError(
                f"change.connections[{index}].kind must be one of "
                f"{', '.join(CONNECTION_KINDS)}, got {kind!r} — every declared "
                "connection says how it is made; leaving it to apply is the bug "
                "029-b measured (placement succeeded, GND never connected)"
            )
        target = item.get("to")
        point: tuple[float, float] | None = None
        if kind == CONNECTION_WIRE:
            if not (isinstance(target, (list, tuple)) and len(target) >= 2
                    and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                            for value in target[:2])):
                raise ChangePlanError(
                    f"change.connections[{index}].to must be [x, y] for a wire "
                    f"connection (the vertex of that net it reaches), got {target!r}"
                )
            point = (float(target[0]), float(target[1]))
        connections.append(
            PlanConnection(pin=pin, net=net, kind=str(kind),
                           detail=str(item.get("detail") or ""), to=point)
        )
    return PlanChange(
        kind=ADD_COMPONENT_KIND,
        part=PlanPart(
            lcsc=lcsc,
            value=value,
            footprint=str(part.get("footprint") or ""),
        ),
        connections=connections,
        recipe_source=str(change.get("recipeSource") or ""),
    )


#: The connection kinds an `insert-subcircuit` may declare. The `label` option is
#: absent on purpose: the host's net-label API is measured unusable (SKILL pit 9,
#: ``sch_PrimitiveNetLabel: absent``), so a plan that leaned on it could not be
#: executed — and a kind the page cannot carry is not a decision, it is a hope.
INSERT_CONNECTION_KINDS: tuple[str, ...] = (CONNECTION_WIRE, CONNECTION_POWER_FLAG)


def _insert_independent_point(value: Any) -> tuple[float, float] | None:
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value[:2])
    ):
        return (float(value[0]), float(value[1]))
    return None


def _move_target_from(target: dict[str, Any]) -> PlanTarget:
    """Read a `move-block` target: the group as named, and the delta requested.

    The delta is part of the target because it is what the caller *asked for*
    (`--dx/--dy`), while `change.moves` is what the page said the parts are and
    where each one will be. Both are checked against the grid, and the two must
    agree — a plan whose delta does not match its moves is a plan whose two halves
    describe different changes.
    """
    raw = target.get("designators")
    names = [str(item).strip() for item in (raw or []) if str(item).strip()]
    if not names:
        raise ChangePlanError(
            "target.designators must name the group this move covers (the designators "
            f"the caller passed), got {raw!r}"
        )
    numbers = {}
    for key in ("dx", "dy"):
        value = target.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ChangePlanError(
                f"target.{key} must be a number in canvas units, got {value!r}"
            )
        numbers[key] = float(value)
    designator = str(target.get("designator") or "").strip()
    return PlanTarget(
        designator=designator or ", ".join(names),
        primitive_id=str(target.get("primitiveId") or ""),
        expected_value=str(target.get("expectedValue") or ""),
        x=numbers["dx"],
        y=numbers["dy"],
    )


def _grid_aligned(value: float, grid: float = MOVE_GRID) -> bool:
    """Is this coordinate a whole number of grid steps? (037 §一: off-grid refuses.)"""
    return abs(round(value / grid) * grid - value) <= 1e-6


def _move_point(value: Any, where: str) -> tuple[float, float]:
    if not isinstance(value, dict):
        raise ChangePlanError(
            f"change.moves[*].{where} must be an object with x and y, got {value!r}"
        )
    out = []
    for key in ("x", "y"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise ChangePlanError(
                f"change.moves[*].{where}.{key} must be a number in canvas units, "
                f"got {number!r}"
            )
        if not _grid_aligned(float(number)):
            raise ChangePlanError(
                f"change.moves[*].{where}.{key} is {number!r}, which is not a multiple of "
                f"the {MOVE_GRID:g}-unit grid — a move off the grid leaves the pins off the "
                "grid and the wires can never join the old routing (037 §一)"
            )
        out.append(float(number))
    return (out[0], out[1])


def _move_change_from(change: dict[str, Any]) -> PlanChange:
    """Read a `move-block` change: the parts, the wires, and the identity claim.

    Five invariants, each one a way for the plan to look executable and not be:

    * at least one move, each naming a part, its canvas id, a **grid-aligned**
      pose before and a grid-aligned point after, with the rotation it had;
    * every wire op names a wire and says what it was and what it becomes;
    * the designators are pairwise distinct (one designator, one part);
    * the recorded islands name the moved pins and their mates;
    * the baseline findings are listed, because "no new findings" cannot be
      judged without them (036's rule, unchanged).
    """
    raw = change.get("moves")
    if not isinstance(raw, list) or not raw:
        raise ChangePlanError(
            f"change.moves must list the parts this plan moves, got {raw!r}"
        )
    moves: list[PlanMove] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ChangePlanError(f"change.moves[{index}] must be an object, got {item!r}")
        designator = str(item.get("designator") or "").strip()
        if not designator:
            raise ChangePlanError(
                f"change.moves[{index}].designator is empty — a move is named by the part "
                "it moves"
            )
        if designator in seen:
            raise ChangePlanError(
                f"change.moves lists {designator!r} twice — one designator is one part "
                "(and two entries would fight over where it lands)"
            )
        seen.add(designator)
        primitive_id = str(item.get("primitiveId") or "").strip()
        if not primitive_id:
            raise ChangePlanError(
                f"change.moves[{index}].primitiveId is empty — the write is by canvas id, "
                "so a move without one cannot say what it will touch"
            )
        before = item.get("from")
        after = item.get("to")
        rotation = (before or {}).get("rotation") if isinstance(before, dict) else None
        if isinstance(rotation, bool) or not isinstance(rotation, (int, float)):
            raise ChangePlanError(
                f"change.moves[{index}].from.rotation must be a number, got {rotation!r} — "
                "it is the pose the plan was built on, and apply re-reads it"
            )
        moves.append(PlanMove(
            designator=designator, primitive_id=primitive_id,
            from_at=_move_point(before, "from"), from_rotation=float(rotation),
            to_at=_move_point(after, "to"),
        ))
    raw_ops = change.get("wireOps")
    if raw_ops is not None and not isinstance(raw_ops, list):
        raise ChangePlanError(
            f"change.wireOps must be a list, got {raw_ops!r}"
        )
    ops: list[PlanWireOp] = []
    for index, item in enumerate(raw_ops or []):
        if not isinstance(item, dict):
            raise ChangePlanError(f"change.wireOps[{index}] must be an object, got {item!r}")
        primitive_id = str(item.get("primitiveId") or "").strip()
        if not primitive_id:
            raise ChangePlanError(
                f"change.wireOps[{index}].primitiveId is empty — the wire this plan takes "
                "off is named by its canvas id (035 §2's rule, same reason)"
            )
        kind = str(item.get("kind") or "").strip()
        if kind != "redraw":
            raise ChangePlanError(
                f"change.wireOps[{index}].kind is {kind!r}; this build redraws wires "
                "(the host does not drag them — measured, `outputs/037_probe.txt`)"
            )
        before = _move_points_list(item.get("pointsBefore"), f"change.wireOps[{index}].pointsBefore")
        after = _move_points_list(item.get("pointsAfter"), f"change.wireOps[{index}].pointsAfter")
        if len(before) < 2 or len(after) < 2:
            raise ChangePlanError(
                f"change.wireOps[{index}] needs at least two points on each side, got "
                f"{len(before)} and {len(after)}"
            )
        ops.append(PlanWireOp(
            primitive_id=primitive_id, kind=kind, net=str(item.get("net") or ""),
            points_before=before, points_after=after,
        ))
    raw_islands = change.get("islands")
    if not isinstance(raw_islands, list) or not raw_islands:
        raise ChangePlanError(
            "change.islands must record, for every pin of every moved part, the pins it "
            f"shared a net with — that is the netlist-identity claim, got {raw_islands!r}"
        )
    islands: list[PlanIsland] = []
    for index, item in enumerate(raw_islands):
        if not isinstance(item, dict):
            raise ChangePlanError(
                f"change.islands[{index}] must be an object, got {item!r}"
            )
        pin = str(item.get("pin") or "").strip()
        if "." not in pin:
            raise ChangePlanError(
                f"change.islands[{index}].pin is {pin!r}; it must be <designator>.<pin>"
            )
        mates = item.get("mates")
        if not isinstance(mates, list):
            raise ChangePlanError(
                f"change.islands[{index}].mates must be a list, got {mates!r}"
            )
        islands.append(PlanIsland(pin=pin, mates=[str(mate) for mate in mates]))
    baseline = change.get("baselineFindings")
    if not isinstance(baseline, list) or any(not isinstance(item, str) for item in baseline):
        raise ChangePlanError(
            "change.baselineFindings must be a list of the finding signatures the project "
            f"reported when this plan was built, got {baseline!r}"
        )
    return PlanChange(
        kind=MOVE_BLOCK_KIND,
        moves=moves,
        wire_ops=ops,
        islands=islands,
        baseline_findings=[str(item) for item in baseline],
    )


def _move_points_list(value: Any, where: str) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        raise ChangePlanError(f"{where} must be a list of [x, y] pairs, got {value!r}")
    out: list[tuple[float, float]] = []
    for index, pair in enumerate(value):
        if (
            not isinstance(pair, (list, tuple)) or len(pair) < 2
            or any(isinstance(item, bool) or not isinstance(item, (int, float))
                   for item in pair[:2])
        ):
            raise ChangePlanError(
                f"{where}[{index}] must be [x, y] in canvas units, got {pair!r}"
            )
        out.append((float(pair[0]), float(pair[1])))
    return out


def _insert_target_from(target: dict[str, Any]) -> PlanTarget:
    """Read an `insert-subcircuit` target: the **anchor**, which may be a pin or a net.

    `rc-lowpass` hangs off one pin of one component (the wire that joins that pin
    to its net is what comes off first), so its anchor is ``designator`` +
    ``pin``. `divider` hangs off a **net** — the stub the divider taps — because
    there is no component to name: the anchor is ``anchorNet`` plus the vertex the
    plan recorded. Exactly one of the two shapes, and the point is required either
    way: apply re-reads it before writing anything.
    """
    anchor = str(target.get("anchor") or "").strip()
    anchor_net = str(target.get("anchorNet") or "").strip()
    pin = str(target.get("pin") or "").strip()
    designator = str(target.get("designator") or "").strip()
    if bool(anchor_net) == bool(designator and pin):
        raise ChangePlanError(
            "an insert-subcircuit target anchors on exactly one thing: either a "
            "component pin (target.designator + target.pin, what rc-lowpass hangs "
            "off) or a net (target.anchorNet, what divider taps) — got "
            f"designator={designator!r} pin={pin!r} anchorNet={anchor_net!r}"
        )
    point = _insert_independent_point([target.get("x"), target.get("y")])
    if point is None:
        raise ChangePlanError(
            "target.x/target.y must be the anchor point in canvas units (the pin's "
            f"coordinates, or the net vertex the plan taps), got "
            f"{target.get('x')!r} / {target.get('y')!r}"
        )
    return PlanTarget(
        designator=designator,
        primitive_id=str(target.get("primitiveId") or ""),
        expected_value=str(target.get("expectedValue") or ""),
        pin=pin,
        anchor=anchor or designator,
        anchor_net=anchor_net,
        x=point[0],
        y=point[1],
    )


def _insert_change_from(change: dict[str, Any]) -> PlanChange:
    """Read an `insert-subcircuit` change, refusing anything apply cannot execute.

    Five invariants, each with a refusal of its own because each one is a way for
    the plan to *look* executable and not be:

    * the template is one this build has;
    * every part states its designator, its recipe (lcsc **and** value) and where
      it lands, and no two parts share a number;
    * every connection names one of those parts, a pin, a net, and a kind from
      :data:`INSERT_CONNECTION_KINDS` — a wire also says where it ends, either at
      a recorded point or at another planned part's pin;
    * `rc-lowpass` has exactly one attachment and a non-empty ``beforeNet`` (it
      removes a wire); `divider` has neither (it removes nothing);
    * the baseline findings are listed, because apply's "no new findings" check
      has nothing to compare against otherwise.
    """
    template = str(change.get("template") or "").strip()
    if template not in INSERT_TEMPLATES:
        raise ChangePlanError(
            f"change.template is {template!r}; this build inserts "
            f"{', '.join(INSERT_TEMPLATES)} only"
        )
    raw_parts = change.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ChangePlanError(
            f"change.parts must list the parts to place, got {raw_parts!r}"
        )
    parts: list[PlanPart] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_parts):
        if not isinstance(item, dict):
            raise ChangePlanError(
                f"change.parts[{index}] must be an object, got {item!r}"
            )
        designator = str(item.get("designator") or "").strip()
        if not designator:
            raise ChangePlanError(
                f"change.parts[{index}].designator is empty — a template's parts are "
                "planned by number so two runs land the same ones (026/029's rule)"
            )
        if designator in seen:
            raise ChangePlanError(
                f"change.parts lists {designator!r} twice — two parts cannot share a "
                "designator, and one of them would silently not be placed"
            )
        seen.add(designator)
        lcsc = str(item.get("lcsc") or "").strip()
        if not lcsc:
            raise ChangePlanError(
                f"change.parts[{index}].lcsc is empty — a part with no orderable number "
                "is not a recipe (029 §二.2)"
            )
        value = str(item.get("value") or "").strip()
        if not value:
            raise ChangePlanError(
                f"change.parts[{index}].value is empty — the value is what the read-back "
                "and the human reviewing the plan compare"
            )
        point = _insert_independent_point([item.get("x"), item.get("y")])
        if point is None:
            raise ChangePlanError(
                f"change.parts[{index}].x/.y must be the landing point in canvas units, "
                f"got {item.get('x')!r} / {item.get('y')!r} — apply places the part there "
                "and the read-back checks it is still there"
            )
        parts.append(PlanPart(
            lcsc=lcsc, value=value, footprint=str(item.get("footprint") or ""),
            designator=designator, role=str(item.get("role") or ""),
            x=point[0], y=point[1], rotation=int(item.get("rotation") or 0),
        ))
    raw = change.get("connections")
    if not isinstance(raw, list) or not raw:
        raise ChangePlanError(
            f"change.connections must list the wires the template draws, got {raw!r}"
        )
    connections: list[PlanConnection] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ChangePlanError(
                f"change.connections[{index}] must be an object, got {item!r}"
            )
        designator = str(item.get("designator") or "").strip()
        if designator not in seen:
            raise ChangePlanError(
                f"change.connections[{index}].designator is {designator!r}, which is not "
                f"one of the parts this plan places ({', '.join(sorted(seen))}) — a "
                "connection to a part nobody planned is a connection to nothing"
            )
        pin = str(item.get("pin") or "").strip()
        net = str(item.get("net") or "").strip()
        if not pin or not net:
            raise ChangePlanError(
                f"change.connections[{index}] needs both pin and net, got {item!r}"
            )
        kind = item.get("kind")
        if kind not in INSERT_CONNECTION_KINDS:
            raise ChangePlanError(
                f"change.connections[{index}].kind must be one of "
                f"{', '.join(INSERT_CONNECTION_KINDS)}, got {kind!r} — 本机 "
                "`sch.place_netlabel` 不可用（SKILL 坑 9），label 不作为连接手段"
            )
        point = _insert_independent_point(item.get("to"))
        to_pin = str(item.get("toPin") or "").strip()
        if kind == CONNECTION_WIRE:
            if point is None and not to_pin:
                raise ChangePlanError(
                    f"change.connections[{index}] is a wire with neither `to` (a point) "
                    "nor `toPin` (another planned part's pin) — where the wire ends is "
                    "the one thing apply cannot decide for itself"
                )
            if point is not None and to_pin:
                raise ChangePlanError(
                    f"change.connections[{index}] says both `to` and `toPin`; a wire has "
                    "one far end"
                )
            if to_pin:
                target_part, _, target_pin = to_pin.partition(".")
                if target_part not in seen or not target_pin:
                    raise ChangePlanError(
                        f"change.connections[{index}].toPin is {to_pin!r}, which does not "
                        f"name a pin of a planned part ({', '.join(sorted(seen))})"
                    )
        elif point is not None or to_pin:
            raise ChangePlanError(
                f"change.connections[{index}] is a {kind} connection with a far-end "
                "point; a rail flag is placed on the part's own pin (029-d)"
            )
        connections.append(PlanConnection(
            designator=designator, pin=pin, net=net, kind=str(kind),
            detail=str(item.get("detail") or ""), to=point, to_pin=to_pin,
        ))
    covered = {item.designator for item in connections}
    unconnected = sorted(seen - covered)
    if unconnected:
        raise ChangePlanError(
            f"change.parts lists {', '.join(unconnected)} but no connection mentions "
            "them — a part placed and left unconnected is the half-done state this "
            "kind exists to prevent"
        )
    before_net = str(change.get("beforeNet") or "").strip()
    attachment = _insert_attachment_from(change)
    if template == TEMPLATE_RC_LOWPASS:
        if attachment is None:
            raise ChangePlanError(
                "an rc-lowpass plan must name the attachment it removes "
                "(change.attachment) — the anchor pin is wired to its net by definition, "
                "and inserting the series resistor means taking that wire off first"
            )
        if not before_net:
            raise ChangePlanError(
                "an rc-lowpass plan must state change.beforeNet — the net the anchor pin "
                "is on today, which the series resistor's far side goes back to"
            )
    else:
        if attachment is not None:
            raise ChangePlanError(
                "a divider plan removes nothing, so it must not carry "
                "change.attachment — a plan that says it will delete something the "
                "template never removes is not what it claims to be"
            )
        if before_net:
            raise ChangePlanError(
                "a divider plan must leave change.beforeNet empty — nothing is being "
                f"disconnected, got {before_net!r}"
            )
    baseline = change.get("baselineFindings")
    if not isinstance(baseline, list) or any(not isinstance(item, str) for item in baseline):
        raise ChangePlanError(
            "change.baselineFindings must be a list of the finding signatures the "
            "project reported when this plan was built — apply re-runs every rule "
            "afterwards and refuses to save when the set grew, which it cannot do "
            f"without a baseline, got {baseline!r}"
        )
    return PlanChange(
        kind=INSERT_SUBCIRCUIT_KIND,
        template=template,
        parts=parts,
        connections=connections,
        before_net=before_net,
        attachment=attachment,
        baseline_findings=[str(item) for item in baseline],
    )


def _insert_attachment_from(change: dict[str, Any]) -> PlanAttachment | None:
    """The attachment an `insert-subcircuit` removes, if it declares one."""
    raw = change.get("attachment")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ChangePlanError(
            f"change.attachment must be an object, got {type(raw).__name__}"
        )
    kind = raw.get("kind")
    if kind not in ATTACHMENT_KINDS:
        raise ChangePlanError(
            f"change.attachment.kind must be one of {', '.join(ATTACHMENT_KINDS)}, "
            f"got {kind!r}"
        )
    primitive_id = str(raw.get("primitiveId") or "").strip()
    if not primitive_id:
        raise ChangePlanError(
            "change.attachment.primitiveId is empty — the removal is by canvas id, so a "
            "plan without one cannot say what it will delete (035 §2)"
        )
    point = _insert_independent_point(raw.get("at"))
    if point is None:
        raise ChangePlanError(
            f"change.attachment.at must be the coordinate that proves the attachment "
            f"lands on the pin, got {raw.get('at')!r}"
        )
    return PlanAttachment(
        kind=str(kind), primitive_id=primitive_id,
        detail=str(raw.get("detail") or ""), at=point,
    )


def add_component_plan(
    source: PlanSource,
    *,
    anchor: str,
    designator: str,
    part: PlanPart,
    connections: list[PlanConnection],
    x: float,
    y: float,
    recipe_source: str,
    connection: str = "",
    connection_detail: str = "",
) -> ChangePlan:
    """The second plan shape: a part that does not exist yet (029 §二.2).

    ``designator`` is the *assigned* one (see `PlanTarget`), and the
    preconditions are generated from the same values apply will re-read, so they
    cannot drift: the anchor, the designator pool, the landing spot and the
    recipe are exactly the four things apply checks before it writes anything.

    The expected postcondition states the *range* obligation in as many words
    ("exactly one component and its connections"), because that is the acceptance
    criterion (§一: a difference that is not +1 part +k connections is an
    accident, even when the board looks better).
    """
    if connection and connection not in CONNECTION_KINDS:
        raise ValueError(
            f"connection must be one of {', '.join(CONNECTION_KINDS)}, got {connection!r}"
        )
    if source.page_uuid:
        page_line = f"pageUuid {source.page_uuid} is still the focused page"
    else:
        page_line = (
            "the page the editor has focused is the plan's page (this plan "
            "carries no pageUuid, so there is no page guard to enforce)"
        )
    return ChangePlan(
        source=source,
        target=PlanTarget(
            designator=designator,
            expected_value=part.value,
            anchor=anchor,
            assigned_designator=designator,
            x=float(x),
            y=float(y),
            connection=connection or (connections[0].kind if connections else ""),
            connection_detail=connection_detail
            or (connections[0].detail if connections else ""),
        ),
        change=PlanChange(
            kind=ADD_COMPONENT_KIND,
            part=part,
            connections=list(connections),
            recipe_source=recipe_source,
        ),
        preconditions=[
            page_line,
            f"anchor {anchor} still resolves on the page",
            f"designator {designator} is still unused on the page",
            f"the landing spot ({x:g}, {y:g}) is still unoccupied",
            f"the recipe {part.value!r} ({part.lcsc}) is still the one this plan was built from",
        ],
        expected_postcondition=[
            f"{designator} exists on the page with value {part.value!r}",
            "its pins sit on "
            + "; ".join(
                f"{item.pin}→{item.net} via {item.kind}"
                + (f" to ({item.to[0]:g}, {item.to[1]:g})" if item.to else "")
                for item in connections
            ),
            "the page gained exactly one component and its connections — nothing else moved",
            "target review finding is resolved",
        ],
    )


def move_block_plan(
    source: PlanSource,
    *,
    moves: list[PlanMove],
    wire_ops: list[PlanWireOp],
    islands: list[PlanIsland],
    designators: list[str],
    dx: float,
    dy: float,
    baseline_findings: list[str] | None = None,
) -> ChangePlan:
    """The fifth plan shape: a group of parts moves by a delta (037).

    No rule drives this one either, so the plan states what it will do and what
    "done" means:

    * every moved part's **target pose** (and the pose it was measured at — the
      stale judgement);
    * every wire it takes off and draws again, with both shapes;
    * the **netlist identity**: for each pin of each moved part, the pins it
      shared a net with. A move must not change a single connection — that is the
      acceptance's main judgement (037 §一) — and pin sets are the reading that
      survives the editor renaming an auto net (035/036's lesson).

    The preconditions apply re-checks are the poses, the wires' presence and the
    two designator/geometry facts; the postconditions are the target poses, the
    islands, the redrawn wires' endpoints and "no new findings".
    """
    if not moves:
        raise ValueError("a move-block plan needs at least one move")
    if source.page_uuid:
        page_line = f"pageUuid {source.page_uuid} is still the focused page"
    else:
        page_line = (
            "the page the editor has focused is the plan's page (this plan carries "
            "no pageUuid, so there is no page guard to enforce)"
        )
    names = ", ".join(item.designator for item in moves)
    return ChangePlan(
        source=source,
        target=PlanTarget(
            designator=names,
            x=float(dx),
            y=float(dy),
        ),
        change=PlanChange(
            kind=MOVE_BLOCK_KIND,
            moves=list(moves),
            wire_ops=list(wire_ops),
            islands=list(islands),
            baseline_findings=list(baseline_findings or []),
        ),
        preconditions=[
            page_line,
            f"every part of the group ({names}) is still where the plan measured it",
            "the wires the plan takes off are still on the page",
            f"the landing area {dx:g} right / {dy:g} down of the group is still free",
            "the recipes and designators are still the ones this plan was built from",
        ],
        expected_postcondition=[
            "every part of the group is at its planned point: "
            + "; ".join(
                f"{item.designator} → ({item.to_at[0]:g}, {item.to_at[1]:g})"
                for item in moves
            ),
            f"the netlist is identical: {len(islands)} pin(s) keep exactly the mates they "
            "had (no connection changes)",
            (
                f"the {len(wire_ops)} wire(s) the plan redraws end where the plan says, and "
                "nothing else vanished"
                if wire_ops
                else "no wire changes: the host moved the parts without dragging them"
            ),
            "no rule reports a finding it did not report before",
        ],
    )


def insert_subcircuit_plan(
    source: PlanSource,
    *,
    template: str,
    parts: list[PlanPart],
    connections: list[PlanConnection],
    anchor: str = "",
    anchor_net: str = "",
    anchor_pin: str = "",
    anchor_at: tuple[float, float] | None = None,
    attachment: PlanAttachment | None = None,
    before_net: str = "",
    baseline_findings: list[str] | None = None,
) -> ChangePlan:
    """The fourth plan shape: a sub-circuit, with its own postconditions (036).

    There is no finding and no rule here, so the plan has to say *for itself*
    what "done" means — and the two lists below are that statement, generated from
    the same values apply will re-read so they cannot drift:

    * ``preconditions`` — the anchor, the thing to remove (if any), the two
      designators and the two landing spots. Apply re-checks every one of them
      against the live page before the first write.
    * ``expected_postcondition`` — the two parts on the page at their spots, the
      new node as **one island** in the editor's own netlist, the old net on the
      resistor's far side, the ground leg on its rail, nothing else moved, and no
      rule reporting anything it did not report before. Apply re-reads all of it
      afterwards, and the *same* function answers "already done" before the writes
      (`engines/subcircuit.postcondition_problems`).
    """
    if template not in INSERT_TEMPLATES:
        raise ValueError(
            f"template must be one of {', '.join(INSERT_TEMPLATES)}, got {template!r}"
        )
    if not parts:
        raise ValueError("an insert-subcircuit plan needs at least one part")
    if source.page_uuid:
        page_line = f"pageUuid {source.page_uuid} is still the focused page"
    else:
        page_line = (
            "the page the editor has focused is the plan's page (this plan "
            "carries no pageUuid, so there is no page guard to enforce)"
        )
    anchor_at = anchor_at or (0.0, 0.0)
    preconditions = [page_line]
    if template == TEMPLATE_RC_LOWPASS:
        preconditions.append(
            f"anchor {anchor} pin{anchor_pin} still resolves on the page"
        )
        preconditions.append(
            f"the anchor pin is still on net {before_net!r}"
        )
        if attachment is not None:
            preconditions.append(
                f"the attachment to remove ({attachment.kind} {attachment.primitive_id}) "
                f"is still on the pin at ({anchor_at[0]:g}, {anchor_at[1]:g})"
            )
    else:
        preconditions.append(
            f"the anchor net {anchor_net!r} still has a vertex at "
            f"({anchor_at[0]:g}, {anchor_at[1]:g})"
        )
    preconditions.append(
        "designators "
        + ", ".join(item.designator for item in parts)
        + " are still unused on the page"
    )
    preconditions.append(
        "the landing spots "
        + ", ".join(f"({float(item.x or 0.0):g}, {float(item.y or 0.0):g})" for item in parts)
        + " are still unoccupied"
    )
    preconditions.append(
        "the recipes "
        + ", ".join(f"{item.designator}={item.value!r} ({item.lcsc})" for item in parts)
        + " are still the ones this plan was built from"
    )
    node_pins = [
        f"{item.designator}.{item.pin}" for item in connections if item.net == "X"
    ]
    ground_pins = [
        f"{item.designator}.{item.pin}" for item in connections if item.net == "GND"
    ]
    far_side = [
        f"{item.designator}.{item.pin}→{item.net}" for item in connections
        if item.net not in ("X", "GND")
    ]
    return ChangePlan(
        source=source,
        target=PlanTarget(
            designator=anchor,
            anchor=anchor or anchor_net,
            anchor_net=anchor_net,
            pin=anchor_pin,
            x=anchor_at[0],
            y=anchor_at[1],
        ),
        change=PlanChange(
            kind=INSERT_SUBCIRCUIT_KIND,
            template=template,
            parts=list(parts),
            connections=list(connections),
            attachment=attachment,
            before_net=before_net,
            baseline_findings=list(baseline_findings or []),
        ),
        preconditions=preconditions,
        expected_postcondition=[
            ", ".join(
                f"{item.designator} ({item.value!r}, {item.lcsc}) at "
                f"({float(item.x or 0.0):g}, {float(item.y or 0.0):g})"
                for item in parts
            )
            + " are on the page",
            f"the new node 'X' is one island in the editor's own netlist: "
            + (", ".join(node_pins) or "(none declared)"),
            *(
                [f"the anchor pin left its old net and " + ", ".join(far_side) + " is on it"]
                if far_side
                else []
            ),
            f"the ground leg ({', '.join(ground_pins) or '(none declared)'}) is on 'GND'",
            "the page gained exactly the planned parts and their wires — nothing else moved",
            "no rule reports a finding it did not report before",
        ],
    )


def _patch_pin_target_from(target: dict[str, Any], designator: str) -> PlanTarget:
    """Read a `patch-pin` target: the component **and the pin** it repairs."""
    pin = str(target.get("pin") or "").strip()
    if not pin:
        raise ChangePlanError(
            "target.pin is empty — patch-pin repairs one named pin, and a plan "
            "that does not say which one cannot be reviewed or re-checked "
            "(035 §二)"
        )
    return PlanTarget(
        designator=designator,
        primitive_id=str(target.get("primitiveId") or ""),
        expected_value=str(target.get("expectedValue") or ""),
        pin=pin,
    )


def _patch_pin_change_from(change: dict[str, Any]) -> PlanChange:
    """Read a `patch-pin` change, and refuse the shapes that cannot be executed.

    The invariants are the plan's meaning, so they are checked here rather than
    discovered at the wire:

    * ``beforeNet != afterNet`` — a plan that changes nothing is not a change;
    * a non-empty ``beforeNet`` **requires** an attachment: leaving a net means
      taking off what attaches the pin to it (and connecting the new net while
      the old attachment is still there would short the two together);
    * a non-empty ``afterNet`` requires exactly one connection, in
      `CONNECTION_KINDS`, with a destination for a `wire`;
    * an empty ``afterNet`` (a pure disconnect) requires **no** connection —
      "disconnect, and also draw something" is not a shape this slice executes.
    """
    before = change.get("beforeNet", "")
    after = change.get("afterNet", "")
    if not isinstance(before, str) or not isinstance(after, str):
        raise ChangePlanError(
            f"change.beforeNet/change.afterNet must be strings, got {before!r} / {after!r}"
        )
    if before == after:
        raise ChangePlanError(
            f"change.beforeNet and change.afterNet are both {before!r} — a plan "
            "that changes nothing is not a change"
        )
    raw = change.get("connections", [])
    if not isinstance(raw, list):
        raise ChangePlanError(
            f"change.connections must be a list, got {raw!r}"
        )
    connections: list[PlanConnection] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ChangePlanError(
                f"change.connections[{index}] must be an object, got {item!r}"
            )
        kind = item.get("kind")
        if kind not in CONNECTION_KINDS:
            raise ChangePlanError(
                f"change.connections[{index}].kind must be one of "
                f"{', '.join(CONNECTION_KINDS)}, got {kind!r} — the connect leg "
                "says how it is made, and \"whichever works\" is the silent "
                "choice this field exists to forbid (029 §二.4)"
            )
        target = item.get("to")
        point: tuple[float, float] | None = None
        if kind == CONNECTION_WIRE:
            if not (isinstance(target, (list, tuple)) and len(target) >= 2
                    and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                            for value in target[:2])):
                raise ChangePlanError(
                    f"change.connections[{index}].to must be [x, y] for a wire "
                    f"connection (the vertex of that net it reaches), got {target!r}"
                )
            point = (float(target[0]), float(target[1]))
        net = str(item.get("net") or "").strip()
        if not net:
            raise ChangePlanError(
                f"change.connections[{index}].net is empty — the connect leg must "
                "name the net the pin is being joined to"
            )
        connections.append(
            PlanConnection(pin=str(item.get("pin") or ""), net=net,
                           kind=str(kind), detail=str(item.get("detail") or ""),
                           to=point)
        )
    attachment_raw = change.get("attachment")
    attachment: PlanAttachment | None = None
    if attachment_raw is not None:
        if not isinstance(attachment_raw, dict):
            raise ChangePlanError(
                f"change.attachment must be an object, got {attachment_raw!r}"
            )
        attachment_kind = attachment_raw.get("kind")
        if attachment_kind not in ATTACHMENT_KINDS:
            raise ChangePlanError(
                f"change.attachment.kind must be one of "
                f"{', '.join(ATTACHMENT_KINDS)}, got {attachment_kind!r} — only the "
                "two attachments that can be proven on the canvas are recognised "
                "(035 §2)"
            )
        attachment_id = str(attachment_raw.get("primitiveId") or "").strip()
        if not attachment_id:
            raise ChangePlanError(
                "change.attachment.primitiveId is empty — a disconnect without the "
                "id of the thing to delete cannot be executed, only guessed at"
            )
        at = attachment_raw.get("at")
        point = None
        if isinstance(at, (list, tuple)) and len(at) >= 2:
            point = (float(at[0]), float(at[1]))
        attachment = PlanAttachment(
            kind=str(attachment_kind),
            primitive_id=attachment_id,
            detail=str(attachment_raw.get("detail") or ""),
            at=point,
        )
    if before and attachment is None:
        raise ChangePlanError(
            f"change.beforeNet is {before!r} but the plan carries no attachment — "
            "leaving a net means taking off the thing that attaches the pin to it "
            "(035 §2; connecting the new net alongside the old one would short them)"
        )
    if not after and connections:
        raise ChangePlanError(
            "change.afterNet is empty (a disconnect) but the plan also carries "
            f"{len(connections)} connection(s) — this slice executes one shape at a "
            "time; say what should happen with one of them"
        )
    if after:
        if len(connections) != 1:
            raise ChangePlanError(
                f"change.afterNet is {after!r}, so the plan must carry exactly one "
                f"connection making that true, got {len(connections)}"
            )
        if connections[0].net != after:
            raise ChangePlanError(
                f"the connection names net {connections[0].net!r} but "
                f"change.afterNet is {after!r} — they have to agree, or the plan "
                "would do one thing and claim another"
            )
    return PlanChange(
        kind=PATCH_PIN_KIND,
        before=before,
        after=after,
        before_net=before,
        after_net=after,
        connections=connections,
        attachment=attachment,
    )


def patch_pin_plan(
    source: PlanSource,
    *,
    designator: str,
    pin: str,
    before_net: str,
    after_net: str,
    connection: str = "",
    connection_detail: str = "",
    to: tuple[float, float] | None = None,
    attachment: PlanAttachment | None = None,
    attachment_detail: str = "",
) -> ChangePlan:
    """The third plan shape: **one pin's connection** repaired (035).

    Three forms come out of the same builder, because they are one claim with two
    ends: the net the pin is on now and the net it must be on.

    * ``before="" , after=T`` — **connect**: the pin reaches nothing and must
      reach ``T``;
    * ``before=N, after=""`` — **disconnect**: the pin sits on ``N`` and must
      reach nothing;
    * ``before=N, after=T`` — **reconnect**: both, in that order (off ``N``, onto
      ``T``).

    ``attachment`` is what a disconnect takes off the pin, and the two invariants
    `from_jsonable` enforces (an attachment whenever ``before`` is non-empty, no
    connection when ``after`` is empty) are enforced here too, so a plan built in
    process cannot be one the reader would refuse.
    """
    if not designator.strip():
        raise ValueError("designator is empty")
    if not str(pin).strip():
        raise ValueError("pin is empty — patch-pin repairs one named pin")
    if before_net == after_net:
        raise ValueError(
            f"before_net and after_net are both {before_net!r} — nothing to change"
        )
    if before_net and attachment is None:
        raise ValueError(
            f"before_net is {before_net!r} but no attachment was given — leaving a "
            "net means taking off what attaches the pin to it"
        )
    if connection and connection not in CONNECTION_KINDS:
        raise ValueError(
            f"connection must be one of {', '.join(CONNECTION_KINDS)}, got {connection!r}"
        )
    if after_net and not connection:
        raise ValueError(
            f"after_net is {after_net!r} but no connection mechanism was chosen"
        )
    if not after_net and connection:
        raise ValueError(
            "after_net is empty (a disconnect) but a connection mechanism was given"
        )
    connections = (
        [PlanConnection(pin=str(pin), net=after_net, kind=connection,
                        detail=connection_detail, to=to)]
        if after_net
        else []
    )
    if source.page_uuid:
        page_line = f"pageUuid {source.page_uuid} is still the focused page"
    else:
        page_line = (
            "the page the editor has focused is the plan's page (this plan "
            "carries no pageUuid, so there is no page guard to enforce)"
        )
    preconditions = [page_line, f"{designator} pin{pin} still resolves on the page"]
    postconditions: list[str] = []
    if before_net:
        preconditions.append(
            f"{designator} pin{pin} is still on net {before_net!r}"
        )
        preconditions.append(
            f"the attachment to remove ({attachment.kind if attachment else '?'} "
            f"{attachment.primitive_id if attachment else '?'}) is still on the pin"
            + (f" at ({attachment.at[0]:g}, {attachment.at[1]:g})" if attachment and attachment.at else "")
        )
        postconditions.append(
            f"{designator} pin{pin} no longer touches net {before_net!r}"
        )
    else:
        preconditions.append(
            f"{designator} pin{pin} still reaches no net"
        )
    if after_net:
        preconditions.append(
            f"the recipe this plan was built against still asks for {after_net!r}"
        )
        postconditions.append(
            f"{designator} pin{pin} sits on {after_net!r} via {connection}"
            + (f" to ({to[0]:g}, {to[1]:g})" if to else "")
        )
    postconditions.append(
        "the netlist changed exactly as promised and nowhere else"
    )
    postconditions.append("the target review finding is resolved")
    return ChangePlan(
        source=source,
        target=PlanTarget(designator=designator, expected_value=after_net, pin=str(pin)),
        change=PlanChange(
            kind=PATCH_PIN_KIND,
            before=before_net,
            after=after_net,
            before_net=before_net,
            after_net=after_net,
            connections=connections,
            attachment=attachment,
        ),
        preconditions=preconditions,
        expected_postcondition=postconditions,
    )


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ChangePlanError(
            f"{key} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ChangePlanError(f"{key} must be a list of strings, got {value!r}")
    return list(value)


def component_value_plan(
    source: PlanSource,
    *,
    designator: str,
    before: str,
    after: str,
    primitive_id: str = "",
) -> ChangePlan:
    """The one plan shape this slice builds: one component, one value.

    The precondition lines are generated from the values rather than written by
    hand, so they cannot drift away from what ``edit apply`` will actually
    re-check. When the plan has no ``pageUuid`` the page precondition says so:
    the connector's page guard is skipped for an empty uuid (measured,
    ``actions.ts``: ``guardPage`` returns early), and a plan claiming a guard it
    does not have is exactly the dishonesty the guard exists to prevent.
    """
    if source.page_uuid:
        page_line = f"pageUuid {source.page_uuid} is still the focused page"
    else:
        page_line = (
            "the page the editor has focused is the plan's page (this plan "
            "carries no pageUuid, so there is no page guard to enforce)"
        )
    return ChangePlan(
        source=source,
        target=PlanTarget(
            designator=designator,
            primitive_id=primitive_id,
            expected_value=before,
        ),
        change=PlanChange(
            kind=COMPONENT_VALUE_KIND, before=before, after=after
        ),
        preconditions=[
            page_line,
            f"designator {designator} still resolves on the page",
            f"Value is still {before}",
        ],
        expected_postcondition=[
            f"Value reads back as {after}",
            "target review finding is resolved",
        ],
    )


# --------------------------------------------------------------------------
# reading a live page dump (`sch.geometry`), offline and pure
# --------------------------------------------------------------------------


@dataclass
class PageComponent:
    """One component as the live page states it."""

    primitive_id: str
    designator: str
    value: str
    #: Where ``value`` was read from (``"OtherProperty.Value"`` or
    #: ``"Value"``), or ``""`` when the page states no value at all. Reported
    #: rather than hidden: "the value is empty" and "this primitive has no
    #: Value key" are different facts, and only the second one means a plan
    #: cannot be checked against this page.
    value_key: str = ""


@dataclass
class PageLookup:
    """The result of a designator-to-primitive resolution."""

    component: PageComponent | None = None
    #: How many primitives on the page carry this designator. More than one is
    #: ambiguity, and ambiguity is refused by the callers rather than guessed
    #: away ("the two U3s" is a real board state — 011c's CONN-1).
    matching: int = 0

    @property
    def ambiguous(self) -> bool:
        return self.matching > 1


def _state_of(entry: Any) -> dict[str, Any]:
    state = (entry or {}).get("state") if isinstance(entry, dict) else None
    return state if isinstance(state, dict) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _other_property(state: dict[str, Any]) -> dict[str, Any]:
    other = state.get("OtherProperty")
    return other if isinstance(other, dict) else {}


def resolve_on_page(geometry: Any, designator: str) -> PageLookup:
    """Find ``designator`` in a ``sch.geometry`` dump.

    Read exactly the way the connector's own resolution does it
    (``actions.ts``: ``state.Designator || state.OtherProperty.Designator``,
    upper-cased, first match wins) so the id this returns is the id the host
    would act on. The *value* is then read from ``OtherProperty.Value`` — that
    is the channel ``sch.set_component_attribute`` writes to, so comparing
    against anywhere else would compare against a copy that cannot change.
    """
    wanted = designator.strip().upper()
    if not wanted or not isinstance(geometry, dict):
        return PageLookup()
    found: PageComponent | None = None
    matching = 0
    for entry in geometry.get("components") or []:
        state = _state_of(entry)
        name = _text(state.get("Designator")) or _text(
            _other_property(state).get("Designator")
        )
        if name.upper() != wanted:
            continue
        matching += 1
        if found is not None:
            continue
        other = _other_property(state)
        if "Value" in other:
            value, key = _text(other.get("Value")), "OtherProperty.Value"
        elif "Value" in state:
            value, key = _text(state.get("Value")), "Value"
        else:
            value, key = "", ""
        found = PageComponent(
            primitive_id=str(
                (entry or {}).get("primitiveId")
                if isinstance(entry, dict) and entry.get("primitiveId")
                else ""
            ),
            designator=name,
            value=value,
            value_key=key,
        )
    return PageLookup(component=found, matching=matching)

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
    "COMPONENT_VALUE_KIND",
    "PLAN_VERSION",
    "SUPPORTED_KINDS",
    "ChangePlan",
    "ChangePlanError",
    "PageComponent",
    "PageLookup",
    "PlanChange",
    "PlanSource",
    "PlanTarget",
    "component_value_plan",
    "resolve_on_page",
    "sha256_of",
]

#: The plan schema version this build reads. A plan from a future build is
#: refused rather than half-understood: the fields are the contract.
PLAN_VERSION = 1

#: The only change kind this slice executes. The others are named so a refusal
#: can say which M3 follow-up owns them instead of "unknown kind".
COMPONENT_VALUE_KIND = "component-value"
SUPPORTED_KINDS: tuple[str, ...] = (COMPONENT_VALUE_KIND,)

#: Where the *other* kinds belong, quoted in the refusal so the reader is not
#: left guessing whether the plan is broken or merely early.
_LATER_KINDS = {
    "add-component": "adding a part",
    "patch-pin": "repairing a single pin",
    "insert-subcircuit": "inserting an RC / divider sub-circuit",
    "move-block": "moving a functional block",
}

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
    """The one component the plan touches.

    ``primitive_id`` is empty offline by construction (see the module
    docstring) and is filled in by the apply report, never by the plan.
    """

    designator: str = ""
    primitive_id: str = ""
    expected_value: str = ""


@dataclass
class PlanChange:
    """The property change itself: one key, one before, one after."""

    kind: str = COMPONENT_VALUE_KIND
    before: str = ""
    after: str = ""


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
        """The schema as written (camelCase, 016 sec.2.2)."""
        return {
            "planVersion": self.plan_version,
            "source": {
                "inputSha256": self.source.input_sha256,
                "projectUuid": self.source.project_uuid,
                "pageUuid": self.source.page_uuid,
                "hostVersion": self.source.host_version,
                "connectorVersion": self.source.connector_version,
            },
            "target": {
                "primitiveId": self.target.primitive_id,
                "designator": self.target.designator,
                "expectedValue": self.target.expected_value,
            },
            "change": {
                "kind": self.change.kind,
                "before": self.change.before,
                "after": self.change.after,
            },
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
        designator = target.get("designator")
        if not isinstance(designator, str) or not designator.strip():
            raise ChangePlanError(
                f"target.designator must name the component, got {designator!r}"
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
            source=PlanSource(
                input_sha256=digest,
                project_uuid=str(source.get("projectUuid") or ""),
                page_uuid=str(source.get("pageUuid") or ""),
                host_version=str(source.get("hostVersion") or ""),
                connector_version=str(source.get("connectorVersion") or ""),
            ),
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

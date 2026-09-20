"""Review annotation sets: the ground-truth format for measuring rules.

Task 011a. An annotation set is one board's oracle record: every *known*
defect, every deliberate *exception* (something that looks like a violation
but is intended), and every open *query* the oracle has not ruled on yet.
The metrics harness (``engines/review_eval.py``) pairs these records against
rule findings; nothing in this module knows which rules exist — hint strings
are validated against the rule registry by the caller, because ``core`` must
not import ``engines``.

Discipline (task 011 sec.6): the human oracle has the final word. A set whose
``reviewed_by`` is empty is a *draft*: the harness runs it, but every report
says so, so draft numbers are never mistaken for audited ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Bumped when the schema changes incompatibly; loaders reject other values.
SCHEMA = "boardwise-review-annotations/1"

#: ``kind`` of an annotation item.
#: - ``defect``: a real hardware fault the rules SHOULD flag.
#: - ``exception``: intended design; rules must NOT flag it.
#: - ``query``: undecided — excluded from every metric, counted separately.
KINDS = ("defect", "exception", "query")

#: Dev/holdout assignment. Holdout items are excluded from harness runs by
#: default so rule tuning cannot peek at them (task 011 sec.6.2).
SPLITS = ("dev", "holdout")

#: Severity a defect is expected to draw. Required for defects: the headline
#: metric (task 011 sec.10) is precision on *high-priority confirmed* issues,
#: and "high-priority" needs the expected severity on the record.
SEVERITIES = ("ERROR", "WARN", "INFO")


class AnnotationError(ValueError):
    """Raised for any malformed annotation set."""


@dataclass
class Item:
    """One oracle record about one ref on one board."""

    ref: str
    rule_hint: str
    kind: str
    note: str
    severity: str = ""
    split: str = ""

    @property
    def effective_split(self) -> str:
        return self.split  # the set fills the default at load time


@dataclass
class Observation:
    """A free-form note the harness never matches on."""

    topic: str
    note: str
    ref: str = ""


@dataclass
class AnnotationSet:
    """One board's oracle record, validated."""

    board: str
    source: str
    items: list[Item] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    split_default: str = "dev"
    reviewed_by: str = ""
    reviewed_at: str = ""
    notes: str = ""

    def items_for_split(self, split: str) -> list[Item]:
        """Items in effect for a harness run restricted to ``split``."""
        if split == "all":
            return list(self.items)
        return [item for item in self.items if item.effective_split == split]

    @property
    def is_reviewed(self) -> bool:
        return bool(self.reviewed_by)


_ITEM_KEYS = ("ref", "rule_hint", "kind", "severity", "split", "note")
_OBSERVATION_KEYS = ("ref", "topic", "note")


def _as_str(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise AnnotationError(f"{where}: expected a string, got {type(value).__name__}")
    return value


def _require_str(body: dict[str, Any], key: str, where: str) -> str:
    value = _as_str(body.get(key), f"{where}.{key}")
    if not value.strip():
        raise AnnotationError(f"{where}.{key}: must be a non-empty string")
    return value


def _item_from_json(raw: Any, where: str, split_default: str) -> Item:
    if not isinstance(raw, dict):
        raise AnnotationError(f"{where}: expected an object, got {type(raw).__name__}")
    unknown = sorted(set(raw) - set(_ITEM_KEYS))
    if unknown:
        raise AnnotationError(f"{where}: unknown key(s) {unknown}; allowed {_ITEM_KEYS}")
    ref = _require_str(raw, "ref", where)
    kind = _require_str(raw, "kind", where)
    if kind not in KINDS:
        raise AnnotationError(f"{where}.kind: {kind!r} not in {KINDS}")
    note = _require_str(raw, "note", where)
    rule_hint = _as_str(raw.get("rule_hint", ""), f"{where}.rule_hint")
    if kind in ("defect", "exception") and not rule_hint.strip():
        raise AnnotationError(
            f"{where}.rule_hint: a {kind} must name the rule that should "
            "(or must not) fire; queries may leave it empty"
        )
    severity = _as_str(raw.get("severity", ""), f"{where}.severity")
    if kind == "defect":
        if not severity:
            raise AnnotationError(
                f"{where}.severity: a defect must state the severity it "
                f"should draw, one of {SEVERITIES}"
            )
        if severity not in SEVERITIES:
            raise AnnotationError(f"{where}.severity: {severity!r} not in {SEVERITIES}")
    elif severity:
        raise AnnotationError(
            f"{where}.severity: only defects carry an expected severity"
        )
    split = _as_str(raw.get("split", ""), f"{where}.split")
    if not split:
        split = split_default
    elif split not in SPLITS:
        raise AnnotationError(f"{where}.split: {split!r} not in {SPLITS}")
    return Item(
        ref=ref,
        rule_hint=rule_hint,
        kind=kind,
        note=note,
        severity=severity,
        split=split,
    )


def _observation_from_json(raw: Any, where: str) -> Observation:
    if not isinstance(raw, dict):
        raise AnnotationError(f"{where}: expected an object, got {type(raw).__name__}")
    unknown = sorted(set(raw) - set(_OBSERVATION_KEYS))
    if unknown:
        raise AnnotationError(f"{where}: unknown key(s) {unknown}")
    topic = _require_str(raw, "topic", where)
    note = _require_str(raw, "note", where)
    ref = _as_str(raw.get("ref", ""), f"{where}.ref")
    return Observation(topic=topic, note=note, ref=ref)


def annotations_from_json(raw: Any, where: str = "<annotations>") -> AnnotationSet:
    """Validate one annotation-set JSON document into an :class:`AnnotationSet`."""
    if not isinstance(raw, dict):
        raise AnnotationError(f"{where}: expected an object, got {type(raw).__name__}")
    if raw.get("schema") != SCHEMA:
        raise AnnotationError(
            f"{where}.schema: expected {SCHEMA!r}, got {raw.get('schema')!r}"
        )
    allowed = {
        "schema", "board", "source", "items", "observations",
        "split_default", "reviewed_by", "reviewed_at", "notes",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise AnnotationError(f"{where}: unknown key(s) {unknown}; allowed {sorted(allowed)}")
    board = _require_str(raw, "board", where)
    source = _require_str(raw, "source", where)
    split_default = _as_str(raw.get("split_default", "dev"), f"{where}.split_default") or "dev"
    if split_default not in SPLITS:
        raise AnnotationError(f"{where}.split_default: {split_default!r} not in {SPLITS}")
    items_raw = raw.get("items", [])
    if not isinstance(items_raw, list):
        raise AnnotationError(f"{where}.items: expected a list")
    items = [
        _item_from_json(entry, f"{where}.items[{i}]", split_default)
        for i, entry in enumerate(items_raw)
    ]
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.ref, item.rule_hint, item.kind)
        if key in seen:
            raise AnnotationError(
                f"{where}: duplicate annotation for ref {item.ref!r} "
                f"(hint {item.rule_hint!r}, kind {item.kind!r})"
            )
        seen.add(key)
    observations_raw = raw.get("observations", [])
    if not isinstance(observations_raw, list):
        raise AnnotationError(f"{where}.observations: expected a list")
    observations = [
        _observation_from_json(entry, f"{where}.observations[{i}]")
        for i, entry in enumerate(observations_raw)
    ]
    return AnnotationSet(
        board=board,
        source=source,
        items=items,
        observations=observations,
        split_default=split_default,
        reviewed_by=_as_str(raw.get("reviewed_by", ""), f"{where}.reviewed_by"),
        reviewed_at=_as_str(raw.get("reviewed_at", ""), f"{where}.reviewed_at"),
        notes=_as_str(raw.get("notes", ""), f"{where}.notes"),
    )


def load_annotations(path: str | Path) -> AnnotationSet:
    """Load and validate one annotation-set file."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AnnotationError(f"{path}: invalid JSON: {exc}") from exc
    return annotations_from_json(raw, str(path))

"""DesignIntent: what the board is **for** — the fourth data contract (090 A1).

The three contracts before it say how a circuit is built (`CircuitSpec`), how it
should read (`PresentationSpec`) and where things go (`LayoutPlan`). None of them
says *why*: a rail's target voltage, a shunt's accepted bit-loss, the reason R4
was chosen over an amplifier. 052 measured what that hole costs — a rule that
sees an MPN disagreeing with a Value cannot tell which side is right (17 parts on
one board had the wrong MPN and the right value), and the ROBOT ctrl FOC blind
review passed a U-phase current chain whose signal cannot physically close (a
bidirectional phase current into a single-supply ADC with no bias). Both are
questions about *intent*, and until now no artifact held it.

This is that artifact. It is deliberately **prior** to the other three: intent is
what the circuit is judged against, so it is written before anything is drawn and
it is where a conflict is resolved.

The document (design-intent-channel.md §二):

.. code-block:: jsonc

    {
      "intentVersion": 1,
      "requirements": {                       // 需求层：这块板要干什么
        "rails":   [{"net": "+12V", "targetVoltage": "12V", "provenance": "user_stated"}],
        "signals": [{"net": "U+", "kind": "current-sense", "polarity": "bidirectional",
                     "provenance": "verified_recipe"}],
        "buses":   [{"family": "CAN", "completeness": "两端 120Ω…"}]
      },
      "blocks":    [{"id": "senseU", "kind": "current-sense", "requires": ["bias-reference"]}],
      "decisions": [{"subject": "R4", "decision": "0.1Ω 直采", "provenance": "user_stated"}]
    }

Four rules, and each one exists because its absence was measured:

1. **The schema is closed, and an optional field is not written when it says
   nothing.** An unknown key is refused with its path named (the 053 §2 discipline
   every contract here follows): a key this build does not read would be a fact
   nobody checks. A slot that has no answer is *absent*, never empty — the owed
   key comes from the enumeration (:func:`reuse_slots`), not from the file.
2. **Provenance travels with every entry**, over the repo's one three-state
   (`user_stated` > `verified_recipe` > `ai_asserted`; the ranking itself lives in
   `core/circuitspec.py` and is shared, see :func:`weakest_provenance`). An entry
   that states no basis is `ai_asserted` — **visible as a draft**, so an AI's
   guess can never be read as an engineer's requirement (052 §4).
3. **The tool validates and asks; it never rewrites a judgement.** A rail with no
   voltage declaration is reported as a missing slot (`intent-missing`, the
   wording `facts-missing` already uses for a fact the compiler needed), and a
   bidirectional current-sense signal with no closure declaration gets a
   *hint* — the question A3 turns into a rule. Neither refuses the document. A
   signal may also **waive** the closure outright (`closure: "waived"`, 094 A3b:
   F1's R4 decision — "0.1Ω 直采，不加放大器，接受只有正半轴"), and that is a
   declaration like any other: the rule that checks the closure grades it by who
   said so and quotes the rationale, rather than asking the same question again.
4. **An answer, once written, is never lost.** Regeneration (:func:`merge`) adds
   the slots the drawing now owes, marks the objects that disappeared `stale`,
   and touches nothing else: every existing entry's bytes come back identical.
   That is the 052 §2.2 accident (`targetVoltage: 3.3V` came back as `TODO`)
   closed by construction.

**Where it lands.** `~/.boardwise/design-intent/<projectUuid>.json` for a live
run, or wherever `--intent <path>` points (offline, tests, a second profile) —
`boardwise_home()` is the same user directory the settings file uses. A run
**reads** the contract; it writes one only where a caller asked for it to be
regenerated (`boardwise arch --intent`), because a generator that silently
creates files in a user's home is a generator nobody can predict.

**Reuse, not a second opinion.** *Which* rails, chains and bus families exist,
and *which* keys each of them owes, is enumerated by
`core/architecture.generate_architecture` (044 M1 / 053 §2.2) — the same
enumeration that renders `architecture.md` and the slot table of
`design-intent.md`. This module maps that enumeration onto the three sections
above (:func:`reuse_slots`) and never re-derives a rail or a chain itself: two
enumerators would be two answers to "what is this board made of".

Offline and self-contained: text in, text out. No network, no clock, no editor.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .architecture import (
    ANALOG_SLOTS,
    BUS_SLOTS,
    CONTROL_SLOTS,
    INTENT_FILE_NAME,
    INTENT_SLOTS,
    POWER_SLOTS,
    SLOT_LABELS,
    TODO,
)
from .circuitspec import (
    PROVENANCE_AI,
    PROVENANCE_USER_STATED,
    PROVENANCE_VERIFIED,
    weakest_provenance,
)

__all__ = [
    "BIAS_TOKENS",
    "CLOSURE_TOKENS",
    "CLOSURE_WAIVED",
    "CONTRACT_DIR_NAME",
    "DesignIntent",
    "DesignIntentError",
    "INTENT_VERSION",
    "INTENT_MISSING",
    "IntentBlock",
    "IntentBus",
    "IntentDecision",
    "IntentRail",
    "IntentSignal",
    "IntentSource",
    "REQUIRED_SLOTS",
    "SECTION_BLOCKS",
    "SECTION_BUSES",
    "SECTION_DECISIONS",
    "SECTION_RAILS",
    "SECTION_SIGNALS",
    "classify_slots",
    "closure_hints",
    "default_contract_path",
    "empty_entry",
    "intent_sha256",
    "merge",
    "render_json",
    "render_markdown",
    "reuse_slots",
    "validate",
    "weakest_provenance",
    "write_path",
]

#: The document's own version. Same rule as `CircuitSpec.specVersion` and
#: `changeplan.PLAN_VERSION`: a version this build does not read is refused, not
#: guessed at.
INTENT_VERSION = 1

#: The user-level directory the contract lands in, under `boardwise_home()`.
CONTRACT_DIR_NAME = "design-intent"

#: The provenance of everything in this document, strongest first — the design
#: doc's own three words, printed in this order wherever they are listed. The
#: *ranking* is `core/circuitspec.py`'s table; this tuple fixes the spelling and
#: the reading order only.
PROVENANCE_KINDS: tuple[str, ...] = (
    PROVENANCE_USER_STATED,
    PROVENANCE_VERIFIED,
    PROVENANCE_AI,
)

#: An entry that states no basis is a draft. Spelled, not implied: the reader
#: sees `ai_asserted` on the row rather than an empty field it has to interpret.
DEFAULT_PROVENANCE = PROVENANCE_AI

#: The token a **missing answer** is reported with — `facts-missing`'s family, the
#: drawing compiler's own word for "a fact a consumer needed was not stated"
#: (090 §一). Single-sourced here since 091 A2a, because two layers report it now:
#: the report's `intent` section (`engines.checkup`) and a rule's finding
#: (`rules.params`) — and `rules` may not import `engines` (006c's table), so the
#: one string needs a home both layers are allowed to read.
INTENT_MISSING = "intent-missing"

#: The three sections of `requirements`. `buses` is this batch's addition to the
#: design doc's two lists (see the module docstring): the enumeration owes
#: `completeness`/`consistency` per bus family, and every owed slot needs a home
#: in the contract or the two views would disagree.
SECTION_RAILS = "rails"
SECTION_SIGNALS = "signals"
SECTION_BUSES = "buses"
SECTION_BLOCKS = "blocks"
SECTION_DECISIONS = "decisions"
REQUIREMENT_SECTIONS: tuple[str, ...] = (SECTION_RAILS, SECTION_SIGNALS, SECTION_BUSES)
ENTRY_SECTIONS: tuple[str, ...] = (
    SECTION_RAILS, SECTION_SIGNALS, SECTION_BUSES, SECTION_BLOCKS, SECTION_DECISIONS,
)

#: The identity key of each section — the one every entry must state, and the
#: join key the merge matches on.
IDENTITY_KEYS: dict[str, str] = {
    SECTION_RAILS: "net",
    SECTION_SIGNALS: "net",
    SECTION_BUSES: "family",
    SECTION_BLOCKS: "id",
    SECTION_DECISIONS: "subject",
}

_TOP_KEYS: tuple[str, ...] = ("intentVersion", "requirements", "blocks", "decisions")
_REQUIREMENT_KEYS: tuple[str, ...] = ("rails", "signals", "buses")


def _unique(*groups: Iterable[str]) -> tuple[str, ...]:
    """One vocabulary, first mention wins — `consistency` is a slot of three
    chain kinds and must be one key here, not three."""
    out: list[str] = []
    for group in groups:
        for item in group:
            if item not in out:
                out.append(item)
    return tuple(out)


#: The slots each section may answer, in the order they are written. Every one of
#: them is an architecture slot key (`core/architecture.py`'s vocabularies) —
#: this module invents no key of its own, and the extras below are the few
#: semantic fields the design doc's own example carries that the 044 skeleton
#: does not enumerate (`role`, `kind`, `adcSwing`, `requires`/`feeds`).
RAIL_SLOT_KEYS: tuple[str, ...] = _unique(POWER_SLOTS, INTENT_SLOTS)
SIGNAL_SLOT_KEYS: tuple[str, ...] = _unique(ANALOG_SLOTS, CONTROL_SLOTS, INTENT_SLOTS)
BUS_SLOT_KEYS: tuple[str, ...] = _unique(BUS_SLOTS)

#: The keys each section's entries may carry, closed. `provenance` and `stale`
#: are on every entry; `stale` is written only when it is true (rule 1).
ENTRY_KEYS: dict[str, tuple[str, ...]] = {
    SECTION_RAILS: ("net", *RAIL_SLOT_KEYS, "role", "provenance", "stale"),
    SECTION_SIGNALS: (
        "net", *SIGNAL_SLOT_KEYS, "kind", "adcSwing", "requires", "closure",
        "provenance", "stale",
    ),
    SECTION_BUSES: ("family", *BUS_SLOT_KEYS, "provenance", "stale"),
    SECTION_BLOCKS: ("id", "kind", "parts", "requires", "feeds", "provenance", "stale"),
    SECTION_DECISIONS: ("subject", "decision", "rationale", "value", "provenance", "stale"),
}

#: The question each section answers, printed in the rendered view and in the
#: report's intent section so a reader knows what they are being asked.
SECTION_TITLES: dict[str, str] = {
    SECTION_RAILS: "轨（这块板要吃/要给什么电压电流）",
    SECTION_SIGNALS: "信号（每条链测什么、极性与参考点）",
    SECTION_BUSES: "总线（每一类的成员是否完整）",
    SECTION_BLOCKS: "功能块（由谁实现、闭合关系）",
    SECTION_DECISIONS: "决策（为什么是它——修复时那一半依据）",
}

#: The slots a section **must** answer for its entry to be judged at all, by the
#: design doc's own two examples: a rail with no voltage declaration, and a
#: signal whose polarity decides whether its chain can close (A3's first rule is
#: 单端 ADC 不许直吃双极性信号). Everything else is owed and listed, but only
#: these are reported as `intent-missing`.
REQUIRED_SLOTS: dict[str, tuple[str, ...]] = {
    SECTION_RAILS: ("targetVoltage",),
    SECTION_SIGNALS: ("polarity",),
}

#: The closure tokens this batch asks about by name: the bias family the ROBOT
#: ctrl FOC case (F1) is missing. What a closure declaration may name is
#: deliberately **not** a closed enum — A3's first 5–8 rules come from real cases
#: (`pullup`, `isolation`, `gain-stage`, …) and will bring their own tokens; what
#: is fixed here is only the two token fields' *shape* (a list of strings).
BIAS_TOKENS: tuple[str, ...] = ("bias-reference", "bias", "reference")

#: The signal kind and polarity the closure question is asked about (the F1
#: shape: a bidirectional phase current into a single-supply ADC).
KIND_CURRENT_SENSE = "current-sense"
POLARITY_BIDIRECTIONAL = "bidirectional"

#: The one value ``signals[].closure`` accepts (094 A3b): the engineer says the
#: chain's closure is **given up on purpose** — F1's R4 decision ("0.1Ω 直采，不加
#: 放大器，接受只有正半轴"). It is the counterpart of `requires`: `requires` names
#: what the chain needs, `closure: "waived"` says the need is knowingly unmet, and
#: the rule that checks the closure reads it before looking at the drawing so the
#: board is not judged against a requirement its author withdrew.
#:
#: **A closed token list, unlike `requires`' free vocabulary.** `requires` names
#: relationships that come from real cases and will keep arriving (`pullup`,
#: `isolation`, `gain-stage`…), so this module only fixes its shape; a *waiver*
#: is one decision with one spelling, and a token a consumer does not read would
#: be a declaration nobody grades (rule 1: an unknown key is refused, and an
#: unknown value of a known key is the same hole one level down).
CLOSURE_WAIVED = "waived"
CLOSURE_TOKENS: tuple[str, ...] = (CLOSURE_WAIVED,)

#: The two token families a markdown view may print for a stale slot. Same words
#: the merged architecture view uses (`architecture.STALE_MARK`), shortened to
#: the line budget of a table row.
STALE_REASON = "stale：图纸里已无此对象"


class DesignIntentError(ValueError):
    """The document is not one this build can read.

    Structural only: every message names the path and the reason. A *question*
    about an entry (a slot the document does not answer) is never an exception —
    that is :func:`validate`'s job, and refusing to read a draft would make the
    contract unusable exactly while it is being written.
    """


# ---------------------------------------------------------------------------
# the entries
# ---------------------------------------------------------------------------


@dataclass
class IntentRail:
    """One rail the board must provide (需求层).

    ``slots`` holds the answers, keyed by the architecture slot key (``voltage``,
    ``source``, ``targetVoltage``, ``continuousCurrent``, ``peakCurrent``,
    ``operatingCases``). Only the ones that were stated are in the dict and only
    they reach the file — an unanswered slot is the enumeration's business, not
    this document's (which is what keeps a draft from looking complete).
    """

    net: str
    slots: dict[str, str] = field(default_factory=dict)
    #: The rail's role (bus / logic / analog / aux…) — free text, because the
    #: roles a board uses are the engineer's words, not this build's.
    role: str = ""
    provenance: str = DEFAULT_PROVENANCE
    stale: bool = False

    @property
    def identity(self) -> str:
        return self.net

    def value(self, key: str) -> str:
        return self.slots.get(key, "")

    def to_jsonable(self) -> dict[str, Any]:
        body: dict[str, Any] = {"net": self.net}
        _write_slots(body, self.slots, RAIL_SLOT_KEYS)
        if self.role:
            body["role"] = self.role
        return _with_meta(body, self.provenance, self.stale)


@dataclass
class IntentSignal:
    """One signal chain's meaning (需求层).

    ``kind`` is the chain's own word for itself (``current-sense``, ``pwm``,
    ``reset``…). ``requires`` is **the closure declaration**: what this chain
    needs from elsewhere to be valid end to end — the statement the F1 bias case
    was missing. ``adc_swing`` is the input range the chain lands on (the fact
    A3's single-ended-ADC rule will compare a bidirectional signal against).

    ``closure`` is the **waiver** (094 A3b), written under the same key in the
    file and read by :attr:`waived`: the chain's closure is given up on purpose,
    with the reason in ``decisions[]`` where every other reason lives. It is a
    declaration, not a silence — A3b's rule files an INFO row quoting the
    rationale for a `user_stated` waiver and a WARN for a draft one (052 §4: a
    draft may not exempt itself), while a signal that says nothing is judged
    against the drawing as before.
    """

    net: str
    slots: dict[str, str] = field(default_factory=dict)
    kind: str = ""
    adc_swing: str = ""
    requires: list[str] = field(default_factory=list)
    closure: str = ""
    provenance: str = DEFAULT_PROVENANCE
    stale: bool = False

    @property
    def identity(self) -> str:
        return self.net

    def value(self, key: str) -> str:
        return self.slots.get(key, "")

    @property
    def polarity(self) -> str:
        return self.slots.get("polarity", "")

    @property
    def waived(self) -> bool:
        """Has the contract given up on this chain's closure (094 A3b)?"""
        return self.closure == CLOSURE_WAIVED

    def to_jsonable(self) -> dict[str, Any]:
        body: dict[str, Any] = {"net": self.net}
        _write_slots(body, self.slots, SIGNAL_SLOT_KEYS)
        if self.kind:
            body["kind"] = self.kind
        if self.adc_swing:
            body["adcSwing"] = self.adc_swing
        if self.requires:
            body["requires"] = list(self.requires)
        if self.closure:
            body["closure"] = self.closure
        return _with_meta(body, self.provenance, self.stale)


@dataclass
class IntentBus:
    """One bus family's completeness judgement (需求层)."""

    family: str
    slots: dict[str, str] = field(default_factory=dict)
    provenance: str = DEFAULT_PROVENANCE
    stale: bool = False

    @property
    def identity(self) -> str:
        return self.family

    def value(self, key: str) -> str:
        return self.slots.get(key, "")

    def to_jsonable(self) -> dict[str, Any]:
        body: dict[str, Any] = {"family": self.family}
        _write_slots(body, self.slots, BUS_SLOT_KEYS)
        return _with_meta(body, self.provenance, self.stale)


@dataclass
class IntentBlock:
    """One functional block and its closure relations (架构层).

    Not enumerated from the netlist: a block is a *claim* about which parts
    realise which job, and the tool has no business inventing one (044's chains
    are the tool's own reading and live in `architecture.md`). What the tool does
    with it is A3's question — ``requires``/``feeds`` are the facts that checker
    will read.
    """

    id: str
    kind: str = ""
    parts: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    feeds: list[str] = field(default_factory=list)
    provenance: str = DEFAULT_PROVENANCE
    stale: bool = False

    @property
    def identity(self) -> str:
        return self.id

    def value(self, key: str) -> str:
        return ""

    def to_jsonable(self) -> dict[str, Any]:
        body: dict[str, Any] = {"id": self.id}
        if self.kind:
            body["kind"] = self.kind
        if self.parts:
            body["parts"] = list(self.parts)
        if self.requires:
            body["requires"] = list(self.requires)
        if self.feeds:
            body["feeds"] = list(self.feeds)
        return _with_meta(body, self.provenance, self.stale)


@dataclass
class IntentDecision:
    """One decision and why it was made (决策层) — the repairing half of 052.

    When a rule sees an MPN disagreeing with a Value, the answer to "which side is
    right?" is a decision recorded here: what was chosen and what was accepted.

    ``stated_value`` is the **machine-readable** half of that answer (091 A2a),
    written in the file under the key ``value``: ``decision`` is prose
    (``"0.1Ω 直采，不加放大器"``) and a rule comparing two strings cannot read a
    quantity out of prose. It is the number the design *chose* for this subject,
    so a rule that finds the board's Value and the MPN disagreeing can say which
    of the two the design stands behind. Optional, and absent when unstated (rule
    1) — a decision with prose only is still a decision, and a consumer that
    needs the number reports a missing `decisions[].value` rather than guessing
    one out of the sentence.
    """

    subject: str
    decision: str
    rationale: str = ""
    stated_value: str = ""
    provenance: str = DEFAULT_PROVENANCE
    stale: bool = False

    @property
    def identity(self) -> str:
        return self.subject

    def value(self, key: str) -> str:
        return ""

    def to_jsonable(self) -> dict[str, Any]:
        body: dict[str, Any] = {"subject": self.subject, "decision": self.decision}
        if self.rationale:
            body["rationale"] = self.rationale
        if self.stated_value:
            body["value"] = self.stated_value
        return _with_meta(body, self.provenance, self.stale)


def _write_slots(body: dict[str, Any], slots: dict[str, str], keys: tuple[str, ...]) -> None:
    """Write the stated answers, in the vocabulary's own order, nothing empty.

    The order is the enumeration's, so two runs of the same document differ only
    where a value differs — which is what makes the byte comparison of a merged
    file meaningful at all.
    """
    for key in keys:
        value = str(slots.get(key, "") or "")
        if value:
            body[key] = value


def _with_meta(body: dict[str, Any], provenance: str, stale: bool) -> dict[str, Any]:
    """`provenance` on every entry (rule 2), `stale` only when it is true."""
    body["provenance"] = provenance or DEFAULT_PROVENANCE
    if stale:
        body["stale"] = True
    return body


# ---------------------------------------------------------------------------
# the document
# ---------------------------------------------------------------------------


@dataclass
class DesignIntent:
    """The whole intent document, in normal form."""

    rails: list[IntentRail] = field(default_factory=list)
    signals: list[IntentSignal] = field(default_factory=list)
    buses: list[IntentBus] = field(default_factory=list)
    blocks: list[IntentBlock] = field(default_factory=list)
    decisions: list[IntentDecision] = field(default_factory=list)
    intent_version: int = INTENT_VERSION

    # ------------------------------------------------------------ lookups

    def entries(self, section: str) -> list[Any]:
        """The entries of one section, in document order."""
        return list(getattr(self, section))

    def entry(self, section: str, identity: str) -> Any | None:
        """The entry of ``section`` whose identity is ``identity``, or ``None``."""
        if section not in ENTRY_SECTIONS:
            raise DesignIntentError(
                f"unknown section {section!r}; the sections are "
                + ", ".join(ENTRY_SECTIONS)
            )
        for item in self.entries(section):
            if item.identity == identity:
                return item
        return None

    def all_provenances(self) -> list[str]:
        """Every entry's provenance, in document order — the weakest-rule input."""
        out: list[str] = []
        for section in ENTRY_SECTIONS:
            out.extend(entry.provenance for entry in self.entries(section))
        return out

    @property
    def provenance(self) -> str:
        """The document's own tier: its **weakest** entry (052 §4).

        One `ai_asserted` rail makes the whole document a draft, and that is the
        point: a conclusion may not be built on an AI's guess as if it were a
        requirement. The same ranking the drawing grammar uses, from the same
        table (`core/circuitspec.weakest_provenance`).
        """
        return weakest_provenance(*self.all_provenances())

    @property
    def draft(self) -> bool:
        """Is any entry an unconfirmed claim (or an empty document)?"""
        return bool(self.draft_reasons)

    @property
    def draft_reasons(self) -> list[str]:
        """Which entries make this a draft, one line each, sorted for stability."""
        reasons = [
            f"{section} {entry.identity!r}: {entry.provenance} — "
            "an unconfirmed requirement may only be read as a hint (052 §4), never "
            "as the yardstick a rule judges a board against"
            for section in ENTRY_SECTIONS
            for entry in self.entries(section)
            if entry.provenance == PROVENANCE_AI
        ]
        if not self.all_provenances():
            reasons.append(
                "the document states nothing at all — abstaining is not evidence, "
                "so an empty contract is a draft"
            )
        return sorted(reasons)

    # --------------------------------------------------------------- JSON

    def to_jsonable(self) -> dict[str, Any]:
        """The normal form: three sections, no empty field, provenance on a row."""
        return {
            "intentVersion": self.intent_version,
            "requirements": {
                SECTION_RAILS: [entry.to_jsonable() for entry in self.rails],
                SECTION_SIGNALS: [entry.to_jsonable() for entry in self.signals],
                SECTION_BUSES: [entry.to_jsonable() for entry in self.buses],
            },
            "blocks": [entry.to_jsonable() for entry in self.blocks],
            "decisions": [entry.to_jsonable() for entry in self.decisions],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> DesignIntent:
        """Read a document, refusing anything this build cannot read.

        Structural refusals only: an unknown key (the closed schema), a missing
        identity, a wrong type, an unknown provenance token, a stated
        `intentVersion` this build does not have. **A missing answer is not one of
        them** — that is a slot the document still owes, reported by
        :func:`validate`.
        """
        root = _object(payload, "$")
        _check_keys(root, _TOP_KEYS, "$")
        version = root.get("intentVersion", INTENT_VERSION)
        if version != INTENT_VERSION:
            raise DesignIntentError(
                f"$.intentVersion is {version!r}, this build reads {INTENT_VERSION} — "
                "regenerate the contract"
            )
        # A section that is absent is empty, not an error: a person writing the
        # first contract writes one section and stops, and refusing the document
        # would make the contract unusable exactly while it is being written. The
        # writer still writes all three (the normal form has one shape).
        requirements = root.get("requirements")
        if requirements is None:
            requirements = {}
        else:
            requirements = _object(requirements, "requirements")
        _check_keys(requirements, _REQUIREMENT_KEYS, "requirements")
        rails = _entries_from(
            requirements.get(SECTION_RAILS), f"requirements.{SECTION_RAILS}", IntentRail
        )
        signals = _entries_from(
            requirements.get(SECTION_SIGNALS), f"requirements.{SECTION_SIGNALS}", IntentSignal
        )
        buses = _entries_from(
            requirements.get(SECTION_BUSES), f"requirements.{SECTION_BUSES}", IntentBus
        )
        blocks = _entries_from(root.get("blocks"), "blocks", IntentBlock)
        decisions = _entries_from(root.get("decisions"), "decisions", IntentDecision)
        return cls(
            rails=rails, signals=signals, buses=buses,
            blocks=blocks, decisions=decisions,
        )

    def dump(self, path: str | Path) -> None:
        """Write the canonical text: two-space indent, one entry per line, LF.

        The format is part of the contract, not a preference: the merge's promise
        ("every existing entry comes back byte-identical") is only checkable while
        the writer is a pure function of the document.
        """
        Path(path).write_text(render_json(self), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> DesignIntent:
        """Read a contract file. Every failure is a :class:`DesignIntentError`."""
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise DesignIntentError(f"{source}: cannot be read ({exc})") from exc
        return parse_json(text, where=str(source))

    def sha256(self) -> str:
        """Digest of the normal form — what a consumer pins as its source."""
        return intent_sha256(self)

    def copy(self) -> DesignIntent:
        """A deep-enough copy: the merge never mutates the document it was given."""
        return replace(
            self,
            rails=[replace(entry, slots=dict(entry.slots)) for entry in self.rails],
            signals=[
                replace(entry, slots=dict(entry.slots), requires=list(entry.requires))
                for entry in self.signals
            ],
            buses=[replace(entry, slots=dict(entry.slots)) for entry in self.buses],
            blocks=[
                replace(
                    entry, parts=list(entry.parts),
                    requires=list(entry.requires), feeds=list(entry.feeds),
                )
                for entry in self.blocks
            ],
            decisions=[replace(entry) for entry in self.decisions],
        )

    def set_entry(self, section: str, entry: Any) -> None:
        """Replace (or prepend) one entry — the merge's only writer."""
        items = getattr(self, section)
        for index, item in enumerate(items):
            if item.identity == entry.identity:
                items[index] = entry
                return
        items.insert(0, entry)


def render_json(document: DesignIntent) -> str:
    """The canonical file text of one document."""
    return json.dumps(document.to_jsonable(), ensure_ascii=False, indent=2) + "\n"


def parse_json(text: str, *, where: str = "design-intent.json") -> DesignIntent:
    """Parse a contract's text, with every failure wrapped in this module's error."""
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise DesignIntentError(f"{where}: is not JSON ({exc})") from exc
    try:
        return DesignIntent.from_dict(payload)
    except DesignIntentError as exc:
        raise DesignIntentError(f"{where}: {exc}") from exc


def intent_sha256(document: DesignIntent) -> str:
    """sha256 of the canonical JSON: sorted keys, no whitespace, over the normal form.

    A re-indented file, or one whose keys were reordered, hashes the same; a
    changed fact does not — including a changed provenance, so a requirement an
    engineer stated and the same words an AI guessed are two different documents.
    """
    text = json.dumps(
        document.to_jsonable(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------- the landing spot


def contract_filename(project_uuid: str) -> str:
    """``<projectUuid>.json`` — the contract's name in the user-level directory."""
    return f"{_segment(project_uuid) or 'project'}.json"


def default_contract_path(project_uuid: str, home: Path | None = None) -> Path:
    """``<boardwise home>/design-intent/<projectUuid>.json``.

    The same user directory `~/.boardwise/config.json` lives in, so a second
    profile (`BOARDWISE_HOME`) moves both together — and a test never has to touch
    the real one.
    """
    from .config import boardwise_home

    return (home or boardwise_home()) / CONTRACT_DIR_NAME / contract_filename(project_uuid)


# ------------------------------------------------------ the reader's carrier


@dataclass(frozen=True)
class IntentSource:
    """A contract **as it was read**: the document, and where it came from (091 A2a).

    A consumer — a rule, a checker — is handed one of these rather than a bare
    :class:`DesignIntent`, for one reason the document cannot answer about itself:
    the questions it owes are answered **by path** ("写进哪个文件哪个键", 090 §一's
    own discipline), and a `DesignIntent` does not know which file it was read
    from. The path travels beside it so a finding can name the file a reader has
    to edit; it is empty for a document somebody built in memory (a test, a caller
    with no file), and a consumer then says where the file is to be found rather
    than inventing a name.

    **Why this lives in `core`** (006c's layer table): reading an intent is a
    consumer's job, `rules` may import `core` and nothing above it, and `engines`
    may import both — so a carrier both need has exactly one legal home, and it is
    this module. The layer rule is also why the *wording* of a consumer's
    question is not shared from here: the sentence is the consumer's own (the
    layer-legal half, :func:`write_path`, is what is reused).
    """

    document: DesignIntent = field(default_factory=DesignIntent)
    path: str = ""

    @classmethod
    def load(cls, path: str | Path) -> IntentSource:
        """Read a contract file, remembering where it came from."""
        source = Path(path)
        return cls(document=DesignIntent.load(source), path=str(source))

    def decision(self, subject: str) -> IntentDecision | None:
        """The decision whose ``subject`` is this identity, or ``None``.

        Exact match only: the subject is the designator as the contract spells it,
        and a rule asking about ``R4`` gets the answer meant for ``R4`` (090's
        identity rule — one entry is one object, and a loose match would hand a
        rule somebody else's decision).
        """
        return self.document.entry(SECTION_DECISIONS, subject)


def _segment(text: str) -> str:
    """One path segment: a project uuid with a slash in it must not invent a level."""
    return "".join(ch for ch in str(text or "") if ch not in '\\/:*?"<>|').strip()


# ---------------------------------------------------------------------------
# reuse: the architecture's enumeration -> the contract's three sections
# ---------------------------------------------------------------------------

#: Which contract section an architecture slot's ``sectionKind`` lands in, when
#: the slot is not part of the `intent:` family (those are placed by object; see
#: :func:`classify_slots`). One table, and it is the whole mapping: `power` is a
#: rail, `analog`/`control` are signals, `bus` is a bus family.
_KIND_SECTIONS: dict[str, str] = {
    "power": SECTION_RAILS,
    "analog": SECTION_SIGNALS,
    "control": SECTION_SIGNALS,
    "bus": SECTION_BUSES,
}

#: The sectionKind whose slots belong to an object the other kinds already placed
#: (the 044 skeleton asks every rail *and* every chain the same four
#: design-intent questions).
_KIND_INTENT = "intent"


def classify_slots(
    slots: Iterable[dict],
) -> tuple[dict[str, dict[str, list[dict]]], list[dict]]:
    """``(groups, unmapped)`` — the architecture's slots, grouped by object.

    ``groups`` is ``{section: {object: [slot record, …]}}`` with the records in
    the order the enumeration wrote them (power tree → analog → control → bus →
    intent), which is also the order :data:`RAIL_SLOT_KEYS` and
    :data:`SIGNAL_SLOT_KEYS` are declared in — so a document written from this
    enumeration is already in the schema's order.

    ``unmapped`` is every record this mapping could not place (a `sectionKind`
    from a future batch, an `intent:` slot whose object no longer exists in the
    drawing). It is **returned rather than dropped**: a slot nobody counts is
    exactly the silent loss the whole channel exists to prevent.
    """
    groups: dict[str, dict[str, list[dict]]] = {
        SECTION_RAILS: {}, SECTION_SIGNALS: {}, SECTION_BUSES: {},
    }
    rail_objects: set[str] = set()
    chain_objects: set[str] = set()
    intent_slots: list[dict] = []
    unmapped: list[dict] = []
    for slot in slots:
        kind = str(slot.get("sectionKind") or "")
        obj = str(slot.get("object") or "")
        if kind == _KIND_INTENT:
            intent_slots.append(slot)
            continue
        section = _KIND_SECTIONS.get(kind)
        if section is None:
            unmapped.append(slot)
            continue
        groups[section].setdefault(obj, []).append(slot)
        (rail_objects if section == SECTION_RAILS else chain_objects).add(obj)
    for slot in intent_slots:
        obj = str(slot.get("object") or "")
        if obj in rail_objects and obj in groups[SECTION_RAILS]:
            groups[SECTION_RAILS][obj].append(slot)
        elif obj in chain_objects:
            groups[SECTION_SIGNALS].setdefault(obj, []).append(slot)
        else:
            unmapped.append(slot)
    return groups, unmapped


def reuse_slots(slots: Iterable[dict]) -> dict[str, dict[str, list[dict]]]:
    """The enumeration, grouped — the only door between architecture and contract."""
    groups, _unmapped = classify_slots(slots)
    return groups


#: The entry class each section instantiates. Kept as data so the parser and the
#: merge cannot drift apart about which section is which.
_ENTRY_CLASSES: dict[str, Any] = {
    SECTION_RAILS: IntentRail,
    SECTION_SIGNALS: IntentSignal,
    SECTION_BUSES: IntentBus,
    SECTION_BLOCKS: IntentBlock,
    SECTION_DECISIONS: IntentDecision,
}


def _section_of(cls: type) -> str:
    """The section an entry class belongs to — the reverse of the table above."""
    for section, candidate in _ENTRY_CLASSES.items():
        if candidate is cls:
            return section
    raise DesignIntentError(f"{cls.__name__} is not an entry of this contract")


def empty_entry(section: str, identity: str) -> Any:
    """A new entry with every slot owed and none answered — a TODO skeleton line.

    Only the three enumerated sections can have one: a block or a decision is a
    claim somebody made, and the tool has no enumeration to invent either from
    (asking for one is a programming error, not a document defect).
    """
    if section == SECTION_RAILS:
        return IntentRail(net=identity)
    if section == SECTION_SIGNALS:
        return IntentSignal(net=identity)
    if section == SECTION_BUSES:
        return IntentBus(family=identity)
    raise DesignIntentError(
        f"{section!r} is not an enumerated section — only "
        + ", ".join(REQUIREMENT_SECTIONS)
        + " get a TODO skeleton entry (a block or a decision is a claim, and the "
        "tool does not invent one)"
    )


# ---------------------------------------------------------------------------
# the merge — 090 §二's persistence discipline
# ---------------------------------------------------------------------------


def merge(
    document: DesignIntent,
    slots: Iterable[dict],
) -> tuple[DesignIntent, dict]:
    """``(regenerated document, facts)`` — skeleton ⊕ answers, 090 §二.

    Three rules, and the first one is the whole batch:

    * **an answer is never lost.** Every entry the document already has comes
      back with its values, its provenance and its position — the regenerated
      text differs from the old one by *insertions* (and by a `stale` mark, which
      is the one edit the discipline asks for). This closes 052 §2.2 by
      construction: a filled `targetVoltage: 3.3V` cannot come back as `TODO`
      because nothing in this function ever writes over a filled value.
    * **the enumeration sets the owed slots.** An object the drawing now has and
      the document does not speak about gets an entry with no answers at all —
      the TODO skeleton of that object, **inserted at the front of its section**
      so that not one existing line moves (the new line carries the separating
      comma; appending would instead touch the previous entry's last line).
    * **a disappeared object is marked, not deleted.** Its entry keeps every byte
      and gains ``stale: true``; deleting it is a later batch's decision, and a
      slot that vanishes silently is the failure this file exists to stop.

    ``facts`` is the reading a report is built from: what was added, what went
    stale, how many slots the enumeration owes, which of them are answered, which
    are owed, which the document states that the enumeration no longer asks for,
    and the two questions the document asks back (a required slot missing, a
    bidirectional current-sense signal with no closure declaration).
    """
    slot_list = list(slots)
    groups, unmapped = classify_slots(slot_list)
    document = document.copy()
    added: list[str] = []
    stale_entries: list[str] = []

    for section in REQUIREMENT_SECTIONS:
        fresh: list[Any] = []
        for identity in groups[section]:
            if document.entry(section, identity) is None:
                fresh.append(empty_entry(section, identity))
                added.append(f"{section}:{identity}")
        if fresh:
            setattr(document, section, [*fresh, *document.entries(section)])

    for section in REQUIREMENT_SECTIONS:
        updated: list[Any] = []
        for entry in document.entries(section):
            if entry.identity in groups[section] or entry.stale:
                updated.append(entry)
                continue
            updated.append(replace(entry, stale=True))
            stale_entries.append(f"{section}:{entry.identity}")
        setattr(document, section, updated)

    filled = 0
    missing: list[dict] = []
    for section in REQUIREMENT_SECTIONS:
        for identity, records in groups[section].items():
            entry = document.entry(section, identity)
            for record in records:
                key = str(record.get("key") or "")
                value = entry.value(key) if entry is not None else ""
                if value:
                    filled += 1
                    continue
                missing.append(_missing_row(section, identity, key, record))
    extras = _unregistered_answers(document, groups)
    facts = {
        "slots": len(slot_list),
        "filled": filled,
        "missing": missing,
        "missingCount": len(missing),
        "required": [row for row in missing if row["required"]],
        "requiredMissingCount": sum(1 for row in missing if row["required"]),
        "added": added,
        "stale": stale_entries,
        "staleEntries": [
            {"section": section, "object": entry.identity}
            for section in REQUIREMENT_SECTIONS
            for entry in document.entries(section)
            if entry.stale
        ],
        "extras": extras,
        "unmapped": [
            {"id": str(record.get("id") or ""), "key": str(record.get("key") or "")}
            for record in unmapped
        ],
        "hints": closure_hints(document),
        "provenance": document.provenance,
        "draft": document.draft,
        "draftReasons": document.draft_reasons,
    }
    return document, facts


def validate(document: DesignIntent, slots: Iterable[dict]) -> dict:
    """:func:`merge`'s reading, without producing the new document.

    The same facts, so a caller that only wants to *ask* (a report, a test) cannot
    get a different answer from a caller that regenerates — and **nothing here
    raises**: a rail with no voltage declaration is a slot this function reports,
    never a document it refuses (090 §一).
    """
    return merge(document, slots)[1]


def _missing_row(section: str, identity: str, key: str, record: dict) -> dict:
    """One owed slot, named the way a reader has to act on it."""
    return {
        "id": str(record.get("id") or ""),
        "section": section,
        "object": identity,
        "key": key,
        "label": SLOT_LABELS.get(key, ""),
        "where": _where(section, identity, record),
        "write": write_path(section, identity, key),
        "required": key in REQUIRED_SLOTS.get(section, ()),
    }


def _where(section: str, identity: str, record: dict) -> str:
    """``轨 `+12V` `` / ``链 `U+` `` — the object as the report's own words say it."""
    if section == SECTION_RAILS:
        return f"轨 `{identity}`"
    if section == SECTION_SIGNALS:
        kind = str(record.get("sectionKind") or "")
        return f"{'控制链' if kind == 'control' else '模拟链'} `{identity}`"
    return f"总线 `{identity}`（{record.get('sectionKind') or 'bus'}）"


def write_path(section: str, identity: str, key: str) -> str:
    """Where in the contract one answer goes — the key a reader has to type.

    A `net`/`family`-keyed selector rather than an array index, because an index
    moves the moment an entry is inserted above it (and A1 inserts at the front on
    purpose).
    """
    identity_key = IDENTITY_KEYS[section]
    if section == SECTION_BLOCKS:
        return f"{section}[{identity_key}={identity}].{key}"
    if section == SECTION_DECISIONS:
        return f"{section}[{identity_key}={identity!r}].{key}"
    return f"requirements.{section}[{identity_key}={identity}].{key}"


def _unregistered_answers(
    document: DesignIntent, groups: dict[str, dict[str, list[dict]]]
) -> list[dict]:
    """Answers the document carries for slots the enumeration no longer asks for.

    Asked **per object**, not per section: the vocabulary is one per section
    (`range` is a signal slot), while what a given object owes is decided by the
    drawing — a control chain is not asked for `range`, so an answer there is a
    fact this pass reports instead of quietly keeping or dropping.

    Kept, reported, never removed: a question that stopped being asked is exactly
    the kind of thing a silent regeneration would hide (`merge`'s third rule, one
    level down from a whole entry).
    """
    out: list[dict] = []
    for section, keys in (
        (SECTION_RAILS, RAIL_SLOT_KEYS),
        (SECTION_SIGNALS, SIGNAL_SLOT_KEYS),
        (SECTION_BUSES, BUS_SLOT_KEYS),
    ):
        for entry in document.entries(section):
            asked = {
                str(record.get("key") or "")
                for record in groups[section].get(entry.identity, [])
            }
            for key in keys:
                if entry.value(key) and key not in asked:
                    out.append({
                        "section": section,
                        "object": entry.identity,
                        "key": key,
                        "value": entry.value(key),
                        "write": write_path(section, entry.identity, key),
                    })
    return out


def closure_hints(document: DesignIntent) -> list[dict]:
    """The questions the contract asks back, in the `intent-missing` family (090 §一).

    One rule in this batch, and it is the case the whole architecture channel was
    built for (the ROBOT ctrl FOC bias hole, F1): a **bidirectional**
    current-sense signal can only be read by its ADC if something biases it into
    the ADC's window, and the document has to *say* so — `requires:
    ["bias-reference"]` on the signal or on the block that realises the chain.

    A1 only wires the question: the closure declaration is looked for **anywhere**
    in the document (any block's or signal's `requires` in the bias family), and
    the hint names the signal and the statement to write. Making the answer
    chain-specific is A3's rule, and it will read the very field this hint points
    at. A hint never refuses the document — 090 §一 is explicit about that.
    """
    declared = {
        token
        for entry in [*document.blocks, *document.signals]
        for token in entry.requires
    }
    if any(token in BIAS_TOKENS for token in declared):
        return []
    out: list[dict] = []
    for signal in document.signals:
        if signal.kind != KIND_CURRENT_SENSE or signal.polarity != POLARITY_BIDIRECTIONAL:
            continue
        out.append({
            "token": "closure-undeclared",
            "section": SECTION_SIGNALS,
            "object": signal.net,
            "signal": signal.net,
            "where": f"链 `{signal.net}`",
            "missing": "requires: [\"bias-reference\"]",
            "write": (
                "requirements.signals[net=" + signal.net + "].requires"
                " 或 blocks[id=…].requires"
            ),
            "why": (
                "双向电流采样信号要落进单电源 ADC 的窗口，必须有偏置/参考把它抬起来；"
                "合同里没有任何 `requires: [\"bias-reference\"]` 类的闭合声明"
            ),
        })
    return out


# ---------------------------------------------------------------------------
# the human view
# ---------------------------------------------------------------------------


def render_markdown(
    document: DesignIntent,
    slots: Iterable[dict],
    *,
    contract_file: str = "",
    project_uuid: str = "",
    board_uuid: str = "",
) -> str:
    """The contract as ``design-intent.md`` — the same table the 053 §2.2 channel reads.

    One row per enumerated slot (``稳定 ID | 槽位 | 值 | 来源 | sig=``), which is
    the format `core.architecture.parse_intent` already reads — so this view is
    not a second channel but the *same* one, rendered from the contract instead of
    from an all-TODO template. A slot the contract answers shows its value and the
    provenance of the entry it lives on; a slot it does not shows `TODO`.

    Entries the contract carries for objects the drawing no longer has are listed
    as prose, never as slot rows: a row would invent a slot id the enumeration
    never wrote, and `parse_intent` would faithfully read that invention back.
    """
    slot_list = list(slots)
    if slot_list:
        project_uuid = _id_part(slot_list[0].get("id"), 0) or project_uuid
        board_uuid = _id_part(slot_list[0].get("id"), 1) or board_uuid
    groups, _unmapped = classify_slots(slot_list)
    lines: list[str] = [
        f"# 设计意图（{INTENT_FILE_NAME}）",
        "",
        "> **本文件由 DesignIntent 合同渲染——JSON 是源，手填无效**（"
        + (f"合同：`{contract_file}`" if contract_file else "合同：见 checkup 报告的 intent 节")
        + "）。"
        "要留住的答案请写进合同；这一页是给人和模型读的视图，每次生成都会按合同重写。",
        "> 值格式：自由文本；「来源」列是**该条条目**的 provenance（"
        + " > ".join(PROVENANCE_KINDS) + "；缺省 = `" + DEFAULT_PROVENANCE + "`，即草稿）。",
        "> 稳定 ID：`<projectUuid>/<boardUuid>/<sectionKey>/<slotKey>`；"
        "`sectionKey` = `<节>:<对象>`（节：power / analog / control / bus / intent）。",
        "> 「sig=」列是该槽**关联对象的签名**（电源树节点集 / 链路器件序列 / 总线成员集）。"
        "图纸一变，checkup 会把该槽标 stale，但**不会改写这一行**。",
        "> 没答的槽写 `" + TODO + "`（欠账不是空白）：逐槽填进合同，填不出来就显式问工程师。",
        "",
        f"projectUuid: {project_uuid or '（未知）'}",
        f"contract: {contract_file or '（未指定）'}",
        "generator: boardwise.core.designintent（090 A1：合同是源，本文件是它的视图）",
        "",
    ]
    if not slot_list:
        lines.append("（这次没有枚举出任何槽位：没有电源轨、没有链、没有命中协议网名的网。）")
        lines.append("")
    for section in REQUIREMENT_SECTIONS:
        for identity, records in groups[section].items():
            entry = document.entry(section, identity)
            board = str(records[0].get("board") or "")
            lines.append(f"### {SECTION_TITLES[section]} —— `{identity}`" + (f"（{board}）" if board else ""))
            lines.append("")
            lines.append("| 稳定 ID | 槽位 | 值 | 来源 | sig= |")
            lines.append("|---|---|---|---|---|")
            for record in records:
                key = str(record.get("key") or "")
                label = SLOT_LABELS.get(key, "")
                shown = f"{key} · {label}" if label else key
                value = entry.value(key) if entry is not None else ""
                source = entry.provenance if entry is not None and value else TODO
                lines.append(
                    f"| {record.get('id')} | {_cell(record.get('object'))} · {_cell(shown)} "
                    f"| {_cell(value) or TODO} | {_cell(source) or TODO} "
                    f"| sig={record.get('signature') or ''} |"
                )
            lines.append("")
    orphans: list[tuple[str, Any]] = [
        (section, entry)
        for section in REQUIREMENT_SECTIONS
        for entry in document.entries(section)
        if entry.identity not in groups[section]
    ]
    if orphans:
        # Prose, not rows: a row here would invent a slot id the enumeration
        # never wrote, and `parse_intent` would read that invention back as a
        # real slot (see the docstring).
        lines.append(f"### 合同里有、图纸里已没有的对象（{len(orphans)}，不删只标）")
        lines.append("")
        for section, entry in orphans:
            stated = "、".join(
                f"{key}=`{value}`" for key, value in entry.slots.items() if value
            )
            lines.append(
                f"- `{entry.identity}`（{SECTION_TITLES[section]}）—— {STALE_REASON}"
                + (f"；合同里记着：{stated}" if stated else "；合同里没答任何槽")
                + f"（{entry.provenance}）"
            )
        lines.append("")
    blocks = document.blocks
    if blocks:
        lines.append(f"### {SECTION_TITLES[SECTION_BLOCKS]}（{len(blocks)}）")
        lines.append("")
        for block in blocks:
            lines.append(
                f"- `{block.id}`"
                + (f" — {block.kind}" if block.kind else "")
                + (f"；parts：{'、'.join(block.parts)}" if block.parts else "")
                + (f"；requires：{'、'.join(block.requires)}" if block.requires else "")
                + (f"；feeds：{'、'.join(block.feeds)}" if block.feeds else "")
                + f"（{block.provenance}）"
            )
        lines.append("")
    decisions = document.decisions
    if decisions:
        lines.append(f"### {SECTION_TITLES[SECTION_DECISIONS]}（{len(decisions)}）")
        lines.append("")
        for decision in decisions:
            lines.append(
                f"- `{decision.subject}`：{decision.decision}"
                + (f" —— {decision.rationale}" if decision.rationale else "")
                + (f"；机读值 value：`{decision.stated_value}`"
                   if decision.stated_value else "")
                + f"（{decision.provenance}）"
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _cell(text: Any) -> str:
    """One table cell: no pipes, no newlines (the 053 template's own rule)."""
    return str("" if text is None else text).replace("|", "\\|").replace("\n", " ").strip()


def _id_part(slot_id_text: Any, index: int) -> str:
    parts = str(slot_id_text or "").split("/")
    return parts[index] if len(parts) == 4 else ""


# ---------------------------------------------------------------------------
# reading and writing, one entry at a time
# ---------------------------------------------------------------------------

_TYPED_FIELDS: dict[type, tuple[str, ...]] = {
    IntentRail: ("net",),
    IntentSignal: ("net",),
    IntentBus: ("family",),
    IntentBlock: ("id",),
    IntentDecision: ("subject", "decision"),
}

_LIST_FIELDS: dict[type, tuple[str, ...]] = {
    IntentSignal: ("requires",),
    IntentBlock: ("parts", "requires", "feeds"),
}

_SLOT_VOCABULARY: dict[type, tuple[str, ...]] = {
    IntentRail: RAIL_SLOT_KEYS,
    IntentSignal: SIGNAL_SLOT_KEYS,
    IntentBus: BUS_SLOT_KEYS,
}

#: The fields whose JSON spelling differs from the attribute's — two reasons, one
#: table: `adcSwing` is camelCase because its slot key is a name written by hand,
#: and `value` is the contract's own word for a decision's machine-readable
#: statement (091 A2a) while the attribute is ``stated_value`` — `IntentDecision`
#: already owns ``value(key)``, the entry protocol, and a field cannot shadow it.
_RENAMED = {"adcSwing": "adc_swing", "value": "stated_value"}


def _entries_from(raw: Any, where: str, cls: type) -> list[Any]:
    """One section's entries, each checked field by field."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DesignIntentError(
            f"{where} must be a JSON array of entries, got {type(raw).__name__}"
        )
    section = _section_of(cls)
    allowed = ENTRY_KEYS[section]
    identity_key = IDENTITY_KEYS[section]
    out: list[Any] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        spot = f"{where}[{index}]"
        body = _object(item, spot)
        _check_keys(body, allowed, spot)
        kwargs: dict[str, Any] = {}
        for name in _TYPED_FIELDS[cls]:
            text = _text(body.get(name), f"{spot}.{name}", required=True)
            kwargs[_RENAMED.get(name, name)] = text
        identity = str(kwargs[identity_key])
        if identity in seen:
            raise DesignIntentError(
                f"{spot} states {identity_key} {identity!r} twice — "
                "one entry is one object"
            )
        seen.add(identity)
        for name in allowed:
            if name in _TYPED_FIELDS[cls] or name in ("provenance", "stale"):
                continue
            if name in _LIST_FIELDS.get(cls, ()):
                kwargs[_RENAMED.get(name, name)] = _text_list(
                    body.get(name), f"{spot}.{name}"
                )
            elif name == "closure":
                kwargs["closure"] = _closure_token(body.get(name), f"{spot}.{name}")
            elif name in _SLOT_VOCABULARY.get(cls, ()):
                value = _text(body.get(name), f"{spot}.{name}")
                if value:
                    kwargs.setdefault("slots", {})[name] = value
            else:
                kwargs[_RENAMED.get(name, name)] = _text(body.get(name), f"{spot}.{name}")
        kwargs["provenance"] = _provenance(body.get("provenance"), f"{spot}.provenance")
        kwargs["stale"] = _boolean(body.get("stale"), f"{spot}.stale")
        out.append(cls(**kwargs))
    return out


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DesignIntentError(
            f"{where} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _text(value: Any, where: str, required: bool = False) -> str:
    if value is None:
        if required:
            raise DesignIntentError(f"{where} is required and missing")
        return ""
    if not isinstance(value, str):
        raise DesignIntentError(
            f"{where} must be a string, got {value!r} — every value in this "
            "contract is what was written (a display value read as a quantity is "
            "046/048's defect, and this contract does not repeat it)"
        )
    if required and not value.strip():
        raise DesignIntentError(f"{where} is empty")
    return value.strip()


def _text_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DesignIntentError(
            f"{where} must be an array of strings, got {value!r} — `requires`/`feeds`/"
            "`parts` name tokens and logical ids, not structures"
        )
    return [item.strip() for item in value if item.strip()]


def _closure_token(value: Any, where: str) -> str:
    """The signal's waiver token, or nothing — an unreadable one is refused.

    ``""`` (absent) is the normal case and is not written back (rule 1). A value
    this build does not read is refused by name: `closure` is a *declaration*, and
    one no consumer grades is exactly the "fact nobody checks" the closed schema
    exists to stop — the same reading `provenance` gets one function down.
    """
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or value not in CLOSURE_TOKENS:
        raise DesignIntentError(
            f"{where} is {value!r}; expected {', '.join(CLOSURE_TOKENS)}, or absent — "
            "a closure token this build does not read would be a declaration nobody "
            "grades"
        )
    return value


def _boolean(value: Any, where: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise DesignIntentError(
            f"{where} must be true or false, got {value!r} — `stale` is the "
            "generator's own mark (an answer the drawing has moved out from "
            "under), not a preference"
        )
    return value


def _provenance(value: Any, where: str) -> str:
    """One entry's basis: the three-state, or the draft default when unstated."""
    if value is None or value == "":
        return DEFAULT_PROVENANCE
    if not isinstance(value, str) or value not in PROVENANCE_KINDS:
        raise DesignIntentError(
            f"{where} is {value!r}; expected one of {', '.join(PROVENANCE_KINDS)}, or "
            "absent — an entry with no stated basis is read as "
            f"`{DEFAULT_PROVENANCE}` (052 §4: a guess must be visible as a guess)"
        )
    return value


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise DesignIntentError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(allowed)} — the schema is closed on purpose: a key this "
            "build does not read would be a fact nobody checks"
        )

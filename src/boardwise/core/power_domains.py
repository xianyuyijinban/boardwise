"""Net voltage-domain inference (task 011c sec.3.1).

The shared dependency of the PWR-1/PWR-2/PATH-1 rules: given a schematic
model and the curated part library, answer "what voltage is this net at, and
who says so". Only two evidence sources exist, both conservative:

1. **the net's own name**, through a whitelist of numeric forms (``+5V``,
   ``5V0``, ``3V3``, ``3.3V``, ``1V8``...). A bare ``VCC``/``VDD``/``VBUS``
   is **never** guessed: names lie, and the 011 family exists because a name
   that reads like a rail is not a declaration;
2. **the facts library's regulator outputs**: an ``ic.ldo`` entry puts a
   voltage on the net its output pin sits on. The voltage itself comes either
   from the entry's own facts — ``ldo.fixed_output``, ``{volts, provenance}``,
   the page-cited shape issue #17 point two added — or, when the entry
   declares none, from **decoding the MPN suffix** (RT9013-**33**GB -> 3.3 V).
   Which of the two it was is carried in the ``source`` string, because a
   suffix decode is a *guess* and a report that prints it next to a datasheet
   fact is claiming more than it knows. The output *pin* comes from the
   entry's own facts (its output-capacitor pin, i.e. the required cap that is
   not on a supply pin), and needs to be *unambiguous*; the output *voltage*
   never comes from a net name, which would be the tail wagging the dog.

Resolution is deliberately strict: one distinct value -> KNOWN (with its
source string quoted verbatim in reports); several disagreeing values ->
CONFLICT (an UNKNOWN, listing every source); no candidate at all -> UNKNOWN.
Every consumer therefore treats "unknown domain" as a first-class answer,
never as zero volts and never as "whatever the name looks like".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import DesignModel
from .partkind import CATEGORY_ABSENT, CATEGORY_GATED, category_verdict
from .parts import (
    FACTS_TRUST_MACHINE,
    FACTS_TRUST_MEANING,
    FACTS_TRUST_VERIFIED,
    PartEntry,
    PartLibrary,
    machine_trust_note,
    resolve_component_facts,
)

#: 527D3: the shelf word that makes a part a speaker here, in one place.
_LDO_CATEGORIES: frozenset[str] = frozenset({"ic.ldo"})

#: Domain states. KNOWN and CONFLICT/UNKNOWN mirror the harness's honesty
#: split: KNOWN asserts, the other two explain why they cannot.
KNOWN = "KNOWN"
CONFLICT = "CONFLICT"
UNKNOWN = "UNKNOWN"

# ``+5V`` / ``12V`` / ``3.3V`` — optional plus, number, trailing V.
_V_FORM = re.compile(r"^\+?(\d+(?:\.\d+)?)V$")
# ``5V0`` / ``3V3`` / ``1V8`` — the ShortJam commas-free rail style. Exactly
# one decimal digit: ``12V34`` is not a rail anyone names. The optional plus is
# here for the same reason it is on :data:`_V_FORM` (issue #71): ``+3V3`` is a
# standard rail name and the mid-letter half of the vocabulary was the only
# half where the ``+`` was missing, so ``+3V3`` priced as an unknown net while
# ``+5V`` priced as 5 V.
_MN_FORM = re.compile(r"^\+?(\d+)V(\d)$")

#: Families whose base part number **ends in digits that name the part, not a
#: voltage** (issue #17 point one). The classic adjustable regulators and the
#: fixed-or-adjustable families built on the same numbers:
#:
#: * ``LM117``/``LM217``/``LM317``, ``LM137``/``LM237``/``LM337`` — the
#:   three-terminal adjustable regulators;
#: * ``LM138``/``LM238``/``LM338``, ``LM350``, ``LM396`` — the high-current
#:   adjustable ones;
#: * ``LM723``, ``TL783``, ``LT1033`` — older / high-voltage / negative
#:   adjustable regulators;
#: * ``LT1083``/``LT1084``/``LT1085``/``LT1086`` and the AMS/LD clones — the
#:   low-dropout 5A/3A family, adjustable unless told otherwise;
#: * the ``1117`` family (``LM1117``/``AMS1117``/``SPX1117``/``LD1117``/
#:   ``NCP1117``/``TLV1117``/``AP1117``/``IL1117``...) and Richtek's ``RT9013``
#:   — the two the issue measured, and the two a board really does carry;
#: * ``LT3080``/``LT3081``/``LT3082``/``LT3095`` — adjustable by design.
#:
#: Reading ``LM317`` as 1.7 V, ``LM337`` as 3.7 V, ``AMS1117`` as 1.7 V or
#: ``RT9013`` as 1.3 V is fabrication dressed as a datasheet fact, and it
#: reached ERROR-level rules as ``state=KNOWN, source="U1 LM317 output"``.
#:
#: The match is on the **numeric stem**, guarded by a non-digit on either side,
#: so that any vendor's prefix is covered instead of listed: "LM317 and friends"
#: is a family, not a spelling. ``317`` is therefore refused inside ``R1117`` or
#: ``AMS1117`` while ``TPS61175`` (where ``117`` sits between digits) stays out
#: of it.
#:
#: This is a list of **known** families, not a proof that the class is closed:
#: an adjustable part outside it still has its name read as a voltage, and the
#: designed answer for such a part is the other half of issue #17 — a curated
#: ``ldo.fixed_output`` fact, or extending this list (which is cheap and
#: explicit; guessing is what a rule may not do).
_ADJUSTABLE_STEM = re.compile(
    r"(?<![0-9])(?:"
    r"117|137|217|237|317|337"          # LM117/217/317, LM137/237/337
    r"|138|238|338|350|396"             # LM138/238/338, LM350, LM396
    r"|723|783|1033"                    # LM723, TL783, LT1033
    r"|1083|1084|1085|1086"             # LT1083..LT1086 (+ AMS/LD clones)
    r"|1117|9013"                       # the 1117 family, RT9013 (#17's two)
    r"|3080|3081|3082|3095"             # LT3080/3081/3082/3095
    r")(?![0-9])"
)

#: What a **fixed** output voltage may look like when a guarded family writes it
#: into the part number: a *delimited* suffix, in the two shapes this reader has
#: always documented — ``-3.3``/``-1.8V`` (dotted) and ``-33``/``-33GB``/
#: ``-50SX`` (two digits, optionally followed by a packaging token). A guarded
#: family with no such suffix (``LM317``, ``AMS1117``, ``RT9013``) has no fixed
#: output this reader may claim.
#:
#: Applied **only** to the tail of a guarded family: a fixed LDO outside those
#: families keeps the looser reading it always had, because an undelimited
#: voltage tail is how fixed LDOs are normally named (TLV70233, TPS7A2033), and
#: #17 is about name-bearing digits, not about re-writing the decoder.
_FIXED_SUFFIX_FORMS = (
    re.compile(r"[-_/.](\d)\.(\d)V?$"),
    re.compile(r"[-_/.](\d)(\d)(?:GB|G|B|SX|S|A)?$"),
)


def voltage_from_net_name(name: str | None) -> tuple[float, str] | None:
    """Decode a whitelisted rail name into ``(volts, source)`` — or None.

    The source string is what rules quote verbatim. Anything the whitelist
    does not recognise (``VCC``, ``VBUS``, ``VEE``, ``NET7``) returns None:
    not guessed, not zero.
    """
    if not name:
        return None
    m = _V_FORM.match(name)
    if m:
        volts = float(m.group(1))
        return volts, f"net name {name!r}"
    m = _MN_FORM.match(name)
    if m:
        volts = float(f"{m.group(1)}.{m.group(2)}")
        return volts, f"net name {name!r}"
    return None


def _fixed_suffix_voltage(tail: str) -> float | None:
    """The voltage written into a delimited suffix, or None.

    ``-3.3`` -> 3.3, ``-33GB`` -> 3.3, ``-ADJ``/``T``/``""`` -> None. See
    :data:`_FIXED_SUFFIX_FORMS` for which shapes count and why only a guarded
    family's tail is read with these.
    """
    for form in _FIXED_SUFFIX_FORMS:
        m = form.search(tail)
        if m:
            return float(f"{m.group(1)}.{m.group(2)}")
    return None


def ldo_output_voltage(mpn: str) -> float | None:
    """Decode an LDO's fixed output voltage from its MPN suffix.

    ``RT9013-33GB`` -> 3.3, ``AMS1117-3.3`` -> 3.3. Returns None for anything
    the two known suffix shapes do not match: adjustable parts (``AMS1117-ADJ``)
    have no fixed output, and guessing one from the preceding digits would be
    fabrication. Issue #17 point one extended that promise to the adjustable
    families spelled **without** their ``ADJ`` marker — ``LM317``, ``LM337``,
    ``LM117``, ``LM1117``, ``AMS1117``, ``RT9013``, ``1117`` and the rest of
    :data:`_ADJUSTABLE_STEM` — whose trailing digits are the model number:
    only an explicit, delimited fixed-output suffix may name a voltage there.

    This is the **fallback** reader. A shelf entry whose facts declare
    ``ldo.fixed_output`` never reaches it (see :func:`ldo_output_voltage_facts`),
    and the domain source says which of the two answered.
    """
    if not mpn:
        return None
    stem = _ADJUSTABLE_STEM.search(mpn)
    if stem is not None:
        return _fixed_suffix_voltage(mpn[stem.end():])
    m = re.search(r"(\d)\.(\d)V?$", mpn)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(\d)(\d)(?:GB|G|B|SX|S|A)?$", mpn)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    return None


def ldo_output_voltage_facts(entry: PartEntry) -> tuple[float, str] | None:
    """The output voltage the entry's **facts** declare, with its citation.

    Reads ``ldo.fixed_output`` (``{"volts": 3.3, "provenance": "…, p.3 …"}``) —
    the optional fact issue #17 point two added to the vocabulary so a curated
    part can name its output voltage with the datasheet page it came from,
    instead of leaving the answer to an MPN suffix decode. Entries that declare
    none (every shelf entry as of this batch) return None and the decode stands
    in, reported as the guess it is.

    ``entry.facts or {}`` and not ``entry.facts``: since 039 a candidate entry
    (`facts_verified: false`) reads as no facts, and this reader is called for
    every shelf entry whose category is `ic.ldo` — including one that only
    claims to be an LDO. Reading the claim here would be the gate leaking.
    """
    record = ((entry.facts or {}).get("ldo") or {}).get("fixed_output")
    if not isinstance(record, dict):
        return None
    volts = record.get("volts")
    provenance = record.get("provenance")
    if isinstance(volts, bool) or not isinstance(volts, (int, float)) or volts <= 0:
        return None
    if not isinstance(provenance, str) or not provenance.strip():
        return None
    return float(volts), provenance


def ldo_output_pin(entry: PartEntry) -> str | None:
    """The LDO's output pin, from its own facts: the required capacitor that
    is not on a supply pin. Both measured entries (RT9013: caps on 1/5 with
    VIN on 1; AMS1117: cap on 2 with VIN on 3) resolve unambiguously; an entry
    that does not gets None and contributes no domain.

    Ambiguity is the whole test since issue #17 point two: this reader used to
    return the **first** non-supply cap pin, so an entry with two of them
    (measured: caps on 2 and 5 with VIN on 3) answered ``"5"`` — one of two
    candidates reported as a fact. The promise above has been in this docstring
    since 011c; now the code keeps it. One pin recorded twice (a mode tag, a
    re-read) is still one pin, hence the set.

    ``entry.facts or {}`` and not ``entry.facts``: since 039 a candidate entry
    (`facts_verified: false`) reads as no facts, and this reader is called for
    every shelf entry whose category is `ic.ldo` — including one that only claims
    to be an LDO. Reading the claim here would be the gate leaking.
    """
    supply = {
        pin
        for record in (entry.facts or {}).get("supply_pins", [])
        for pin in record.get("pins", [])
    }
    candidates = {
        cap.get("pin")
        for cap in (entry.facts or {}).get("required_caps", [])
        if cap.get("pin") and cap.get("pin") not in supply
    }
    if len(candidates) != 1:
        return None
    return next(iter(candidates))


@dataclass
class DomainGuess:
    """One net's voltage verdict, with the evidence attached.

    ``source`` is the winning evidence string (KNOWN) or empty; ``detail``
    carries every candidate seen, so a CONFLICT can name both sides and an
    UNKNOWN can say "nobody speaks for this net".
    """

    net: str
    state: str
    volts: float | None = None
    source: str = ""
    detail: str = ""

    @property
    def is_known(self) -> bool:
        return self.state == KNOWN and self.volts is not None


def _facts_entry(
    model: DesignModel, library: PartLibrary
) -> dict[str, PartEntry]:
    """One shelf lookup per component, by the identity chain, resolved once."""
    entries: dict[str, PartEntry] = {}
    for comp in model.components.values():
        entry, _matched = resolve_component_facts(library, comp)
        if entry is not None:
            entries[comp.designator] = entry
    return entries


def infer_net_domains(
    model: DesignModel,
    library: PartLibrary,
    *,
    allow_machine: bool = False,
) -> dict[str, DomainGuess]:
    """Voltage verdicts for every net that has at least one candidate source.

    Nets with no candidate get no entry here; rules that need one must treat
    the absence as UNKNOWN with their own missing_fact (the caller knows what
    it asked for).

    ``allow_machine`` (522) is the **second** half of the tier gate, and it is
    here because this function is where an LDO's datasheet fact stops being one
    rule's input and becomes everybody's: ``ldo.fixed_output`` names an output
    rail's voltage, and from then on *any* rule that quotes a domain is reading
    that entry. So the tier question has to be asked **once, here**, or a
    conclusion rule would inherit a machine-verified fact through the net
    domain without its own gate ever seeing it.

    Default ``False`` — conservative, and byte-identical to 011c for every entry
    a human curated. A caller whose own rule may act on the machine tier
    (:attr:`boardwise.rules.facts.FactsRule.REQUIRES_HUMAN_VERIFIED` ``False``)
    passes ``True`` and gets that entry's declared output voltage too. A
    machine-verified entry under ``allow_machine=False`` is skipped exactly the
    way a candidate is: the domain inference falls back to the net's name and the
    MPN-suffix decode, both of which say what they are.
    """
    candidates: dict[str, list[tuple[float, str]]] = {}

    for name in model.nets:
        hit = voltage_from_net_name(name)
        if hit is not None:
            candidates.setdefault(name, []).append(hit)

    #: 527D3: nets a **gated** class would have spoken for — the shelf calls the
    #: part an LDO and this tier may not read that class. Collected rather than
    #: dropped: a machine-granted (or draft) class must not let a rail lose its
    #: only declared source without a word, which is exactly the shape the raw
    #: `entry.category` read left behind. See the loop after the candidates.
    gated_notes: dict[str, str] = {}

    entries = _facts_entry(model, library)
    for comp in model.components.values():
        entry = entries.get(comp.designator)
        verdict = category_verdict(
            entry, _LDO_CATEGORIES, allow_machine=allow_machine
        )
        if verdict == CATEGORY_ABSENT:
            continue
        if verdict == CATEGORY_GATED:
            # 527D3: the shelf names an LDO here and this tier may not read it —
            # a machine-granted class for a conclusion caller, or a draft at any
            # tier. The part does **not** name the rail (522's line), and the net
            # gets an UNKNOWN guess below so the caller's `why_not` says which
            # review is owed instead of 「no source names this voltage」.
            #
            # The sentence is `machine_trust_note`'s (core's own, and the one
            # every machine-tier finding already carries); a draft has no such
            # note — `machine_trust_note` is empty for it — so that case names the
            # tier through `FACTS_TRUST_MEANING`, the shelf's own vocabulary,
            # rather than growing a third sentence about the same gate.
            tier = str(getattr(entry, "category_trust", FACTS_TRUST_VERIFIED))
            note = machine_trust_note(entry) or (
                f"分类档位 {tier}：{FACTS_TRUST_MEANING.get(tier, tier)}"
            )
            out_pin = ldo_output_pin(entry)
            pin = (
                next((p for p in comp.pins if p.number == out_pin), None)
                if out_pin
                else None
            )
            if pin is not None and pin.net:
                gated_notes.setdefault(
                    pin.net,
                    f"{comp.designator} 的货架分类 {entry.category!r} 未采信"
                    f"（{note}），所以它**没有**为这条网声明电压",
                )
            continue
        if entry.facts_trust == FACTS_TRUST_MACHINE and not allow_machine:
            # 522: this entry's facts are in `facts` (the calculation rules read
            # them) but nobody signed them, so they may not name a rail for a
            # rule that draws a conclusion. Same read as a candidate's absent
            # facts, for the same reason.
            continue
        mpn = entry.mpn or comp.mpn
        declared = ldo_output_voltage_facts(entry)
        if declared is not None:
            volts, where = declared
            how = f"declared by the entry's datasheet facts ({where})"
            if entry.facts_trust == FACTS_TRUST_MACHINE:
                # 522 §5.5: the source string is what rules quote verbatim, so
                # the caveat rides in it and every row that names this rail
                # carries it without each rule having to remember. Same sentence
                # every finding uses (`machine_trust_note`), not a second wording.
                how += f" —— {machine_trust_note(entry)}"
        else:
            volts = ldo_output_voltage(mpn)
            # Issue #17 point two: the report has to be able to tell a decoded
            # suffix from a cited fact. Stated in the source string, which is
            # what rules quote verbatim (`… at 3.3 V — {source}`).
            how = ("decoded from the MPN suffix — a guess: no datasheet fact "
                   "declares it")
        out_pin = ldo_output_pin(entry)
        if volts is None or out_pin is None:
            continue
        pin = next((p for p in comp.pins if p.number == out_pin), None)
        if pin is not None and pin.net:
            candidates.setdefault(pin.net, []).append(
                (volts, f"{comp.designator} {mpn} output, {how}")
            )

    guesses: dict[str, DomainGuess] = {}
    for net, found in candidates.items():
        distinct = sorted({volts for volts, _ in found})
        if len(distinct) == 1:
            guesses[net] = DomainGuess(
                net=net,
                state=KNOWN,
                volts=distinct[0],
                source=found[0][1],
                detail="; ".join(f"{v} V per {s}" for v, s in found),
            )
        else:
            guesses[net] = DomainGuess(
                net=net,
                state=CONFLICT,
                volts=None,
                detail="; ".join(f"{v} V per {s}" for v, s in found)
                + " — the sources disagree, so no voltage is asserted",
            )
    # 527D3: the third state. A net a gated class would have spoken for gets a
    # guess of its own when nothing else speaks for it — an **UNKNOWN** whose
    # `detail` is the tier sentence, which `domain_of` hands back as the caller's
    # `why_not`. Without it the answer would be the same 「no source names the
    # voltage of net X」 a net nobody mentions gets, and a rail that lost its only
    # declared source to the tier gate would say nothing about why.
    for net, note in gated_notes.items():
        held = guesses.get(net)
        if held is None:
            guesses[net] = DomainGuess(net=net, state=UNKNOWN, detail=note)
        elif note not in held.detail:
            held.detail = f"{held.detail}; {note}" if held.detail else note
    return guesses


def domain_of(
    guesses: dict[str, DomainGuess], net: str | None
) -> tuple[float | None, str, str]:
    """The voltage of one net, as ``(volts, source, why_not)``.

    KNOWN returns ``(volts, source, "")``. Anything else returns
    ``(None, "", reason)`` where the reason is a ready-made missing_fact:
    an absent entry is "no source names this net's voltage", a CONFLICT
    quotes both sides. ``None``/empty net names are unknown too.

    527D3: an **UNKNOWN**-state guess (the one :func:`infer_net_domains` now
    writes when the only class that would have spoken for a net was gated at this
    tier) returns its own ``detail`` — the tier sentence — rather than the
    CONFLICT wording below. Before that change no such guess existed, so the
    branch is new behaviour for a state that was previously unreachable rather
    than a re-wording of an existing one.
    """
    if not net:
        return None, "", "the pin has no net"
    guess = guesses.get(net)
    if guess is None:
        return None, "", f"no source names the voltage of net {net!r}"
    if guess.is_known:
        return guess.volts, guess.source, ""
    if guess.state == UNKNOWN:
        return None, "", guess.detail or (
            f"no source names the voltage of net {net!r}"
        )
    return None, "", (
        f"net {net!r} has conflicting voltage sources: {guess.detail}"
    )

"""One place decides what a part **is** (task 190, 岳 2026-10-16 ⑦).

Before this module there were two spellings of the same question inside one
repository: 189B's ``rules/pcb/derating.METADATA_TYPE_KEYS`` (read the library
metadata — ``Type`` / ``LCSC Part Name`` / ``Supplier Footprint`` — and never the
designator) and 127b's ``rules/pcb/distance.classify_device`` (read the shelf
category, then the part's own name/footprint words, and only **last** the
designator table). Two orders, four call sites, and one measured consequence —
the reported case 岳 opened ⑦ with: a ``U``-designated 330 kΩ resistor
(``FRC1206J334TS``) was asked for a decoupling capacitor because its *designator*
letter was the only signal the L1 rule read.

What this module is: the same judgement, in one entry point, with the **basis**
returned next to the answer so a report can say which signal decided it —
「它这么判，是因为货架这么写 / 立创元数据这么写 / 只有位号前缀可读」.
:class:`PartKind` is that pair; a caller that only wants a yes/no maps it
(``kind == KIND_IC``) and a caller that has to explain itself quotes
:attr:`PartKind.reason`.

**The read order, and why it is not negotiable.**

1. **the shelf** (:data:`boardwise.core.parts.PartEntry.category`) — the
   curated declaration, the strongest signal when an entry has one. The 039
   gate applies when the entry is read here (:func:`_shelf_declaration`): an
   entry whose ``facts_verified`` is false is *unclassified* as far as rules
   are concerned (038/039 批①), the exact discipline ``rules.facts`` applies at
   its own choke point. An entry with no category does not stop the read — it
   has said nothing about the part's kind, which is different from saying
   "not an IC".
2. **the declarations about the part itself** — the 立创 metadata fields
   (189B's :data:`METADATA_TYPE_KEYS`, read off ``props``) and then the part's own
   ``footprint`` / ``value`` / ``mpn`` / ``device_name`` (127b's
   ``DeviceFacts.text``). Both are the drawing's own words about the part, not
   ours, and :data:`DECLARATION_WORDS` is the vocabulary. Metadata is scanned
   before the part's own text because 189B established that order on the one
   board that forced it: the type was written in ``LCSC Part Name`` while
   ``Type`` was empty.
3. **the designator prefix** — :func:`boardwise.core.parts.designator_category`,
   the project's own table, and **only** a fallback: it is the last thing read
   and the reason says so. Two rules refine it, and both are reused from the
   batch that measured them rather than re-argued:

   * **the pin floor** (:data:`MIN_IC_PINS`, 127b): a part with fewer than
     three pins cannot be an IC — a two-pin part has no decoupling requirement
     and no supply rail of its own — so an **IC** answer on a two-pin part is
     refused and the basis reads :data:`BASIS_PIN_FLOOR`. Two limits on that,
     both deliberate. It can only ever refuse an *IC*: a two-pin part is still a
     resistor or a capacitor, and a floor that swallowed those would empty the
     decoupling rule's capacitor set. And it only applies when the caller
     **supplied a pin count** (:attr:`PartDeclarations.pins`): 「this model read
     two pins」 is evidence, 「nobody counted」 is not, and a caller that never
     counted must not get the verdict by accident — ``rules/sensebias`` and
     ``rules/pcb/derating`` both ask this reader without a count.
   * **:data:`NON_IC_DESIGNATOR_PREFIXES`** (127b): prefixes that never name an
     IC (a TVS array, a four-contact relay), which the designator table either
     answers with a non-IC family or does not know at all.

Nothing declares the part and the table does not know its prefix → kind
:data:`KIND_UNKNOWN` with :data:`BASIS_NONE`: the honest "we looked and the
drawing said nothing", which a caller must distinguish from "we did not look".

**The shelf is the caller's to supply** (``library=``), because the path this
process reads its shelf from is resolved in ``boardwise.rules.facts``
(:func:`~boardwise.rules.facts.default_library_path`: the user shelf when frozen,
``blocklib/parts.json`` in a checkout) and ``core`` may not import ``rules``
(006c's executable constitution, ``tests/test_layer_rules.py``). A caller that
has no shelf omits it, and the read says so by falling through to the next
step — which is what the L1 connectivity rules do deliberately: that module
states its own boundary ("no datasheet knowledge") in its docstring, and a rule
that suddenly read ``blocklib/parts.json`` would be claiming a source it never
had.

**What is *not* here.** The value's own grammar (a ``Value`` field written in
ohms or farads is a declaration too, and 189B's door 1) stays with the rule that
measured it: it is a parser over one field, not a kind vocabulary, and folding
two use-cases into one table is how the two口径 this module exists to collapse
were created. The kind of a part is what its *declarations* say; how to read its
value is ``core.values``' question.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

#: The part-kind vocabulary. One name per answer a rule in this repository asks
#: for, and :data:`KIND_UNKNOWN` is a **third** answer rather than a fallback:
#: 「声明说它不是 IC」 and 「没人说过它是什么」 are different sentences, and the
#: 039 gate exists because collapsing them is how a machine gets to grade its
#: own homework.
KIND_IC = "ic"
KIND_RESISTOR = "resistor"
KIND_CAPACITOR = "capacitor"
KIND_INDUCTOR = "inductor"
KIND_DIODE = "diode"
KIND_LED = "led"
KIND_TRANSISTOR = "transistor"
KIND_CONNECTOR = "connector"
KIND_CRYSTAL = "crystal"
KIND_THERMISTOR = "thermistor"
KIND_TRANSFORMER = "transformer"
KIND_SWITCH = "switch"
KIND_BUZZER = "buzzer"
KIND_FUSE = "fuse"
KIND_TESTPOINT = "testpoint"
KIND_RELAY = "relay"
KIND_UNKNOWN = "unknown"

#: Which signal decided the kind — the second half of the reading, and the
#: reason the task book asks for a ``basis``: 「前缀只在元数据读不出时兜底，
#: 且兜底要能在报告里看出来」. :data:`BASIS_NONE` is not a signal at all, it is
#: the absence of one.
BASIS_SHELF = "shelf"
BASIS_METADATA = "metadata"
BASIS_PREFIX = "prefix"
BASIS_PIN_FLOOR = "pin-floor"
BASIS_NONE = ""

#: The 立创 metadata fields that state what a part is, in reading priority
#: (189B ⑦, moved here in 190 so the reading has one home). ``Type`` is the
#: library's own electrical class; ``LCSC Part Name`` is the catalogue's
#: product string, which is where the measured board wrote the type while
#: ``Type`` was empty (``330kΩ ±1% 1/4W 厚膜电阻``); ``Supplier Footprint`` is the
#: supplier's footprint string, read so that "the metadata face" is taken in one
#: call instead of a caller guessing at field names.
METADATA_TYPE_KEYS: tuple[str, ...] = ("Type", "LCSC Part Name", "Supplier Footprint")

#: A part with fewer than three pins is not an IC (127b's floor, moved here in
#: 190 with the judgement it belongs to). **Necessary, never sufficient**: being
#: many-pinned makes nothing an IC, and a two-pin part cannot have a decoupling
#: requirement in any meaningful sense — the 毕设FOC blind review's five false
#: positives were transistors and 2x6 headers. What 190 adds is the second
#: half: the same floor has to hold for the *designator* answer too, because
#: 「U4 是一颗 330 kΩ 电阻」 is the case the letter used to decide unopposed.
MIN_IC_PINS = 3

#: A designator prefix that is never an IC, whatever the shelf says. The pin
#: floor already excludes ``R`` / ``C`` / ``L`` (two pins); this table is for the
#: parts that are **many**-pinned and still not an IC — a four-diode TVS array, a
#: multi-contact relay. Its two halves are answered at different steps: ``D`` /
#: ``K`` / ``T`` are in :data:`boardwise.core.parts.DESIGNATOR_CATEGORIES` and come
#: back as a non-IC family, while ``TVS`` / ``RELAY`` / ``XFMR`` are prefixes the
#: table does not know and are refused here by name.
NON_IC_DESIGNATOR_PREFIXES: frozenset[str] = frozenset(
    {"D", "K", "T", "TVS", "RELAY", "XFMR"}
)

#: Footprint / value / MPN **words that name a header or a connector**, and are
#: therefore never an IC (127b, moved here in 190 with the judgement). This is
#: the harder half of the U-designator problem: the designator says ``U`` (so the
#: table calls it an IC) and the part says ``PZ2.54-2*6`` / ``PZ2.54-2x6P TP`` /
#: ``PZ254V-11-04P`` — a 排针, a row of 2.54 mm holes. Measured on the fixture:
#: U4 and U6 (PCB1) and U1 and U2 (PCB3) are all ``PZ2.54``-family parts and all
#: four carry ``Designator: 'U?'``, which is precisely why the prefix cannot be
#: trusted on its own. Matched case-insensitively as a **substring** of the
#: part's own text, because these are the library's names and not ours: the same
#: header family is spelled ``PZ2.54-2*6``, ``HX PZ2.54-2x6P TP``,
#: ``PZ254V-11-04P`` and ``HDR-TH_4P-P2.54`` on four different parts.
CONNECTOR_WORDS: tuple[str, ...] = (
    "PZ2.54", "PZ254", "HDR", "HEADER", "CONN", "TYPE-C", "USB", "MX1.25", "XT60",
)

#: Words that name a **transistor** (MOSFET / BJT). A power MOSFET's drain sits
#: on a supply rail and its gate on a driver output, so a pin-count IC test reads
#: its ``+24V`` drain as 「an IC's supply net」 and asks for a bypass capacitor
#: beside it — exactly the false positive 岳 ruled on (裁定 1). Matched against
#: the same text, for the same reason.
#:
#: The order is a **priority order**, not a set: it is scanned in order and the
#: first hit is the reason quoted in the evidence, so a part named
#: ``MCAC53N06Y-TP`` in an ``DFN(5x6)`` package is reported as 「transistor
#: (``MCAC``)」 rather than as its package — the MPN is the part's identity and
#: the package is a consequence of it.
TRANSISTOR_WORDS: tuple[str, ...] = (
    "MOS", "MOSFET", "N-CH", "P-CH", "2N7002", "MCAC",
)
#: 190f：封装词（``DFN`` / ``SOT-23``）曾在上表里——封装不定型，SOT-23-6 的电源 IC、
#: DFN 的 MCU 都会被读成晶体管而离开 IC 题面。``MCAC`` 这类 MPN 词已足够认出 127b
#: 的那颗 MOSFET。

#: Words that name a **magnetic** part — a transformer or a common-mode choke.
#: 127b carried ``XFMR`` / ``TRANSFORMER`` as "a passive", which stopped the IC
#: question correctly and said nothing about the kind; 190 names the kind,
#: because a caller that reads parts (rather than only asking "is it an IC?")
#: would otherwise have to re-spell this list.
TRANSFORMER_WORDS: tuple[str, ...] = ("XFMR", "TRANSFORMER", "变压器", "共模")

#: Words that name a passive family in the part's own name or footprint. 127b's
#: ``PASSIVE_WORDS`` split into the two kinds it actually named: a
#: ``RES-TH_L9.5…`` / ``RES_…`` footprint is a resistor, a ``CAP-``/``CAP_`` one
#: is a capacitor, and 190's reading keeps the distinction because callers now
#: use the answer for more than the IC question (the decoupling rule asks "is
#: this a capacitor?" about the *other* side of the same net).
RESISTOR_WORDS: tuple[str, ...] = ("RES-", "RES_", "电阻", "resistor")
CAPACITOR_WORDS: tuple[str, ...] = ("CAP-", "CAP_", "电容", "capacitor", "mlcc")
INDUCTOR_WORDS: tuple[str, ...] = ("电感", "inductor", "磁珠", "ferrite bead")

#: Thermal parts, and the reason this table is scanned **before** the resistor
#: one: ``热敏电阻`` contains ``电阻``. 190's ruling (岳 10-16 ⑦'s 遗留) is that an
#: NTC/PTC is a **thermistor**, its own kind — it is sold as a resistor-shaped
#: chip and its footprint really is a chip resistor's, but its value is a
#: temperature curve, not an ohms reading, so it must not enter the resistance
#: derating or value-code paths. ``NTC``/``PTC`` are read as substrings of the
#: part's own name (``HNTC0603-103F3450FA``, ``NTC2.5D-9SM20E``) because that is
#: where such a part states it — measured on the FPC fixture's ``R2`` and on
#: 实板A's ``NTC2``, both of which carry the letters only in their part number.
THERMISTOR_WORDS: tuple[str, ...] = ("热敏", "thermistor", "ntc", "ptc")

#: Words that name a diode (including the protection families). ``TVS`` is also
#: a designator prefix in :data:`NON_IC_DESIGNATOR_PREFIXES`; here it is the word
#: a part's own description may carry.
DIODE_WORDS: tuple[str, ...] = ("二极管", "diode", "tvs", "zener", "schottky", "整流")

#: Words that name a crystal / resonator. 127b's ``rules/connectivity`` reads
#: crystals by an ``X``/``Y`` designator or a MHz/KHz value; this is the same
#: family as a *kind*, for a part whose own name says so.
CRYSTAL_WORDS: tuple[str, ...] = ("晶振", "crystal", "resonator", "振荡器")

#: The vocabulary, in the order it is scanned, as ``(kind, label, words)``.
#:
#: The order is a **priority order** and each step is a stop, exactly as 127b's
#: was: thermistor before resistor (see :data:`THERMISTOR_WORDS`), the named
#: passives before the two "shape" families, and connector/transistor in their
#: 127b positions relative to each other. ``label`` is the phrase the reason
#: quotes — it carries 127b's own spellings (``connector/header``,
#: ``transistor``) so the evidence a reader already saw keeps reading the same
#: way.
DECLARATION_WORDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (KIND_THERMISTOR, "thermistor", THERMISTOR_WORDS),
    (KIND_RESISTOR, "resistor", RESISTOR_WORDS),
    (KIND_CAPACITOR, "capacitor", CAPACITOR_WORDS),
    (KIND_INDUCTOR, "inductor", INDUCTOR_WORDS),
    (KIND_DIODE, "diode", DIODE_WORDS),
    (KIND_CRYSTAL, "crystal", CRYSTAL_WORDS),
    (KIND_CONNECTOR, "connector/header", CONNECTOR_WORDS),
    (KIND_TRANSISTOR, "transistor", TRANSISTOR_WORDS),
    (KIND_TRANSFORMER, "transformer", TRANSFORMER_WORDS),
)

#: Shelf/designator category string -> kind. The keys are
#: :data:`boardwise.core.parts.DESIGNATOR_CATEGORIES`' own values (``res``,
#: ``cap``, ``conn`` … — that table is spelled for a shelf address, not for a
#: kind) plus the ``category`` strings this repository's shelf really carries
#: (``ic``, ``ic.ldo``, ``fet``, ``connector``, ``diode``, ``led`` — measured
#: over all 109 entries of ``blocklib/parts.json`` on 2026-10-16).
#:
#: A shelf category is **hierarchical** (``ic.motor-driver``), so the head
#: decides: anything starting with ``ic`` is an IC, and the rest is exact. An
#: unknown string falls through: a category nobody taught this table is not a
#: kind, it is a word we do not know.
CATEGORY_KINDS: dict[str, str] = {
    "ic": KIND_IC,
    "res": KIND_RESISTOR,
    "resistor": KIND_RESISTOR,
    "cap": KIND_CAPACITOR,
    "capacitor": KIND_CAPACITOR,
    "ind": KIND_INDUCTOR,
    "inductor": KIND_INDUCTOR,
    "diode": KIND_DIODE,
    "led": KIND_LED,
    "fet": KIND_TRANSISTOR,
    "transistor": KIND_TRANSISTOR,
    "conn": KIND_CONNECTOR,
    "connector": KIND_CONNECTOR,
    "xtal": KIND_CRYSTAL,
    "crystal": KIND_CRYSTAL,
    "thermistor": KIND_THERMISTOR,
    "transformer": KIND_TRANSFORMER,
    "sw": KIND_SWITCH,
    "buzzer": KIND_BUZZER,
    "fuse": KIND_FUSE,
    "testpoint": KIND_TESTPOINT,
    "relay": KIND_RELAY,
}

#: The label each kind is quoted as when the reason names it.
_KIND_LABEL: dict[str, str] = {
    KIND_IC: "IC",
    KIND_RESISTOR: "resistor",
    KIND_CAPACITOR: "capacitor",
    KIND_INDUCTOR: "inductor",
    KIND_DIODE: "diode",
    KIND_LED: "LED",
    KIND_TRANSISTOR: "transistor",
    KIND_CONNECTOR: "connector/header",
    KIND_CRYSTAL: "crystal",
    KIND_THERMISTOR: "thermistor",
    KIND_TRANSFORMER: "transformer",
    KIND_SWITCH: "switch",
    KIND_BUZZER: "buzzer",
    KIND_FUSE: "fuse",
    KIND_TESTPOINT: "test point",
    KIND_RELAY: "relay",
}

#: The same table's IC rows. ``DESIGNATOR_CATEGORIES`` spells ``U`` / ``IC`` /
#: ``DRV`` as ``ic``, and a shelf category is hierarchical, so both are read by
#: head rather than by spelling the two lists twice.
_IC_PREFIX = "ic"


@dataclass(frozen=True)
class PartKind:
    """What a part is, and which signal said so.

    ``kind`` is one of the module's ``KIND_*`` names; ``basis`` is one of the
    ``BASIS_*`` names and is the half a reviewer argues with — a reading whose
    basis is :data:`BASIS_PREFIX` is a *fallback*, and one whose kind is
    :data:`KIND_UNKNOWN` with :data:`BASIS_NONE` is "nobody declared it".
    ``reason`` is one sentence quoting the word, category or designator that
    decided it, written to be pasted into a finding's evidence (which is the
    difference between 「we looked and it is not an IC」 and 「we did not look」).
    """

    kind: str = KIND_UNKNOWN
    basis: str = BASIS_NONE
    reason: str = ""

    @property
    def declared(self) -> bool:
        """Whether a **declaration** (the shelf or the part's own fields) decided it.

        The distinction a rule needs when a fallback is too weak for its own
        subject: the derating rule judges chip resistors and refuses to read a
        designator letter as an electrical fact (189B ⑦), so it keeps only a
        reading whose basis is :data:`BASIS_SHELF` or :data:`BASIS_METADATA`.
        """
        return self.basis in (BASIS_SHELF, BASIS_METADATA)

    @property
    def is_ic(self) -> bool:
        return self.kind == KIND_IC


@dataclass(frozen=True)
class PartDeclarations:
    """What a caller knows about one part, in the four shapes this reader takes.

    Every field is optional because every caller reads a different amount:
    ``distance`` has already resolved the shelf and composed the part's text
    (:func:`boardwise.rules.pcb.distance.device_facts`), ``derating`` has read the
    立创 metadata off a PCB-side placement, and the L1 connectivity rules have
    nothing but the netlist model. A field left empty is "this caller did not
    read that", never "it is not there" — which is why
    :func:`declarations_of` exists as the reader for a caller that *has* the
    component.
    """

    designator: str = ""
    #: The shelf's own category, when the caller has read it. Used **as
    #: given**: a caller that resolved an entry has done the reading, and the
    #: 039 gate is applied by :func:`classify_part` only on the ``library=`` path,
    #: where this module does the resolving itself (see :func:`_shelf_declaration`).
    shelf_category: str = ""
    #: The 立创 metadata fields' text (189B ⑦): :data:`METADATA_TYPE_KEYS`
    #: joined, in that priority order.
    metadata: str = ""
    #: The part's own words (127b): ``footprint``, ``value``, ``mpn`` and the
    #: placement's ``device_name``. Lower-cased by the reader — the vocabulary is
    #: matched case-insensitively and these are the library's spellings, not ours.
    text: str = ""
    #: How many pins this reading sees, or ``None`` for "not counted". ``None``
    #: and ``2`` are different answers: only a counted part can be refused by the
    #: floor, and a caller that never counted pins must not get a pin-floor
    #: verdict by accident.
    pins: int | None = None

    def merged(self, other: "PartDeclarations | None") -> "PartDeclarations":
        """``self`` with every field ``other`` set (non-empty) replaced by it.

        The caller's own reading wins field by field, because it is the more
        specific one: ``derating`` passes the 立创 metadata it read off the
        *PCB-side* placement while the component it hands over may be the
        schematic's, and a caller that counted pins passes a count this module
        cannot make for a synthetic model.
        """
        if other is None:
            return self
        changes: dict[str, Any] = {}
        for field_name in ("designator", "shelf_category", "metadata", "text"):
            value = getattr(other, field_name)
            if value:
                changes[field_name] = value
        if other.pins is not None:
            changes["pins"] = other.pins
        return replace(self, **changes) if changes else self


def declarations_of(component: object) -> PartDeclarations:
    """Read what a parsed :class:`~boardwise.core.model.Component` declares.

    Duck-typed like 127b's ``device_facts``: anything carrying ``designator`` /
    ``value`` / ``footprint`` / ``mpn`` / ``props`` / ``pins`` is enough (the
    PCB-side and schematic-side components are two different classes over the
    same shape, and the tests build both).
    """
    props = getattr(component, "props", None) or {}
    metadata = " ".join(
        str(props.get(key) or "").strip()
        for key in METADATA_TYPE_KEYS
        if str(props.get(key) or "").strip()
    )
    text = " ".join(
        str(getattr(component, name, "") or "")
        for name in ("footprint", "value", "mpn")
    )
    text = f"{text} {props.get('device_name') or ''}"
    pins = getattr(component, "pins", None)
    return PartDeclarations(
        designator=str(getattr(component, "designator", "") or ""),
        metadata=metadata,
        text=text.lower(),
        pins=len(pins) if pins is not None else None,
    )


def _prefix_of(designator: str) -> str:
    """The whole leading alphabetic run of a designator, upper-cased (127b)."""
    text = str(designator or "").strip()
    run = ""
    for char in text:
        if not char.isalpha():
            break
        run += char
    return run.upper()


def kind_of_category(category: str) -> str:
    """The kind a shelf/designator category names, or :data:`KIND_UNKNOWN`.

    Hierarchical rows are read by head (``ic.motor-driver`` -> :data:`KIND_IC`);
    :data:`CATEGORY_KINDS`' exact rows answer the rest. A string this table does
    not know is not a kind — the same refusal ``rules.facts._category_state``
    makes when it will not guess from a category it has never seen.
    """
    text = str(category or "").strip()
    if not text:
        return KIND_UNKNOWN
    if text == _IC_PREFIX or text.startswith(f"{_IC_PREFIX}."):
        return KIND_IC
    return CATEGORY_KINDS.get(text, KIND_UNKNOWN)


def _hit(text: str, words: tuple[str, ...]) -> str:
    """The first word of ``words`` occurring in ``text``, or ``""`` (127b)."""
    for word in words:
        if word.lower() in text:
            return word
    return ""


def _kind_of_words(text: str) -> tuple[str, str, str]:
    """``(kind, label, hit word)`` for a declaration text, or unknowns.

    The text is lower-cased here rather than by the caller (127b's
    ``device_facts`` did it at the door): the vocabulary is matched
    case-insensitively and these are the library's spellings, so a caller that
    forgets would silently stop matching ``Resistor`` and ``HEADER``.
    """
    if not text:
        return KIND_UNKNOWN, "", ""
    lowered = text.lower()
    for kind, label, words in DECLARATION_WORDS:
        hit = _hit(lowered, words)
        if hit:
            return kind, label, hit
    return KIND_UNKNOWN, "", ""


def _shelf_declaration(entry: object | None) -> str:
    """The category an entry declares, or ``""`` when it declares nothing.

    **The 039 gate, applied where the entry is read rather than where a rule
    remembers to.** An entry whose ``facts_verified`` is false is a candidate a
    machine drafted, so its category is not a declaration a rule may act on —
    this is the same judgement ``rules.facts._category_state`` makes, and for the
    same reason: no partial trust. An entry with no category declares nothing
    about the part's kind and the read falls through to the next step.
    """
    if entry is None or not getattr(entry, "facts_verified", True):
        return ""
    return str(getattr(entry, "category", "") or "").strip()


def classify_part(
    component: object | None = None,
    facts: PartDeclarations | None = None,
    library: object | None = None,
    *,
    pin_floor: bool = True,
) -> PartKind:
    """What this part is, and why — see the module docstring for the read order.

    ``component`` is read by :func:`declarations_of`; ``facts`` is a caller's own
    reading which wins field by field (:meth:`PartDeclarations.merged`), so a
    caller that already resolved the shelf or counted pins does not read twice.
    ``library`` is the shelf to consult **when neither of those declared a
    category and the caller has no reading of its own**: this module resolves the
    entry through the identity chain (MPN → C-number → device name,
    :func:`boardwise.core.parts.resolve_component_facts`) and applies the 039
    gate. Omitting it is not "no shelf exists", it is "this caller did not hand
    one over", and the reading then simply starts at the declarations.

    ``pin_floor=False`` is a caller saying **its question is not about pin
    counts**: the three-pin necessary condition is then not applied, whatever the
    model's count is. Two measured reasons a caller says it. ``rules/facts``'
    gates ask 「can the shelf judge this part?」, and a gate is exactly where a
    part must not vanish — a part the model read one pin of is a part the shelf
    is being *asked about*, not a part that stopped being an IC (and the module's
    own anchors build one-pin components on purpose). ``rules/sensebias`` asks
    whether a pin name is an op-amp input, and 127b's floor was measured for the
    other question entirely. A rule that asks 「does this part need something?」
    (a bypass capacitor — :class:`~boardwise.rules.connectivity.DecouplingPerIC`)
    keeps the default, and that is where the floor was 127b's.
    """
    read = (
        declarations_of(component) if component is not None else PartDeclarations()
    ).merged(facts)
    answer = _read_part_kind(read, component, library)
    return _refuse_a_two_pin_ic(answer, read) if pin_floor else answer


def _read_part_kind(
    read: PartDeclarations, component: object | None, library: object | None
) -> PartKind:
    """The three declaration sources, in order (see the module docstring)."""
    declaration = read.shelf_category
    if not declaration and library is not None and component is not None:
        declaration = _shelf_declaration(_resolve_entry(library, component))
    if declaration:
        kind = kind_of_category(declaration)
        if kind == KIND_IC:
            return PartKind(
                kind=kind,
                basis=BASIS_SHELF,
                reason=f"shelf category {declaration!r} is an IC class",
            )
        if kind != KIND_UNKNOWN:
            return PartKind(
                kind=kind,
                basis=BASIS_SHELF,
                reason=(
                    f"shelf category {declaration!r} is not an IC class "
                    f"(a {_label(kind)})"
                ),
            )
        # A category this reader does not know says "not nothing": it is a
        # declaration, and the honest answer is 「the shelf wrote a word this
        # build has no kind for」 rather than a fallback to the prefix.
        return PartKind(
            kind=KIND_UNKNOWN,
            basis=BASIS_SHELF,
            reason=(
                f"shelf category {declaration!r} is not one of the kinds this "
                "reader names"
            ),
        )

    for source, text in (
        ("its 立创 metadata", read.metadata),
        ("the part's own name or footprint", read.text),
    ):
        kind, label, hit = _kind_of_words(text)
        if kind != KIND_UNKNOWN:
            return PartKind(
                kind=kind,
                basis=BASIS_METADATA,
                reason=f"{source} says {label} ({hit!r})",
            )

    return _from_designator(read)


def _refuse_a_two_pin_ic(read: PartKind, declarations: PartDeclarations) -> PartKind:
    """127b's pin floor, as a necessary condition on the **IC** answer.

    It fires *after* the sources and only when the caller supplied a pin count,
    which is the one place this reader departs from 127b's spelling rather than
    its judgement: 127b asked the floor first because its only question was
    「is this an IC?」, and asking it first here would answer 「unknown」 about a
    two-pin **capacitor** — emptying the decoupling rule's capacitor set and
    making every IC on every board complain. What the floor decides is what it
    always decided: no part with fewer than three pins is an IC, whichever
    source said otherwise.
    """
    pins = declarations.pins
    if read.kind != KIND_IC or pins is None or pins >= MIN_IC_PINS:
        return read
    return PartKind(
        kind=KIND_UNKNOWN,
        basis=BASIS_PIN_FLOOR,
        reason=(
            f"{pins} pin(s) — below the {MIN_IC_PINS}-pin floor, so the "
            f"designator {declarations.designator!r} cannot make it an IC"
        ),
    )


def _resolve_entry(library: object, component: object) -> object | None:
    """The shelf entry for a component, through the identity chain (186 §B)."""
    from .parts import resolve_component_facts

    try:
        entry, _matched = resolve_component_facts(library, component)
    except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
        return None
    return entry


def _from_designator(read: PartDeclarations) -> PartKind:
    """The last step: what the designator's own family says."""
    designator = read.designator
    prefix = _prefix_of(designator)
    category = ""
    if prefix:
        from .parts import designator_category

        category = designator_category(designator)
    kind = kind_of_category(category) if category else KIND_UNKNOWN

    if kind == KIND_IC:
        return PartKind(
            kind=KIND_IC,
            basis=BASIS_PREFIX,
            reason=(
                "no device fact classifies it either way, so the designator "
                f"{designator!r} is the fallback ({category!r})"
            ),
        )

    if kind != KIND_UNKNOWN:
        return PartKind(
            kind=kind,
            basis=BASIS_PREFIX,
            reason=(
                f"the designator prefix {prefix!r} names a {_label(kind)}, which "
                "is not an IC"
            ),
        )

    if prefix and prefix in NON_IC_DESIGNATOR_PREFIXES:
        return PartKind(
            kind=KIND_UNKNOWN,
            basis=BASIS_PREFIX,
            reason=f"designator prefix {prefix!r} never names an IC",
        )

    return PartKind(
        kind=KIND_UNKNOWN,
        basis=BASIS_NONE,
        reason=(
            "no device fact names it an IC and its designator "
            f"{designator!r} does not either"
        ),
    )


def _label(kind: str) -> str:
    return _KIND_LABEL.get(kind, kind)


__all__ = [
    "BASIS_METADATA",
    "BASIS_NONE",
    "BASIS_PIN_FLOOR",
    "BASIS_PREFIX",
    "BASIS_SHELF",
    "CAPACITOR_WORDS",
    "CATEGORY_KINDS",
    "CONNECTOR_WORDS",
    "CRYSTAL_WORDS",
    "DECLARATION_WORDS",
    "DIODE_WORDS",
    "INDUCTOR_WORDS",
    "KIND_BUZZER",
    "KIND_CAPACITOR",
    "KIND_CONNECTOR",
    "KIND_CRYSTAL",
    "KIND_DIODE",
    "KIND_FUSE",
    "KIND_IC",
    "KIND_INDUCTOR",
    "KIND_LED",
    "KIND_RELAY",
    "KIND_RESISTOR",
    "KIND_SWITCH",
    "KIND_TESTPOINT",
    "KIND_THERMISTOR",
    "KIND_TRANSFORMER",
    "KIND_TRANSISTOR",
    "KIND_UNKNOWN",
    "METADATA_TYPE_KEYS",
    "MIN_IC_PINS",
    "NON_IC_DESIGNATOR_PREFIXES",
    "PartDeclarations",
    "PartKind",
    "RESISTOR_WORDS",
    "THERMISTOR_WORDS",
    "TRANSFORMER_WORDS",
    "TRANSISTOR_WORDS",
    "classify_part",
    "declarations_of",
    "kind_of_category",
]

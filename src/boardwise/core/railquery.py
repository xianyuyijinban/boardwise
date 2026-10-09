"""Which rails still owe the engineer a voltage — the review's 先问再判 list (issue #65).

``pcb-voltage-spacing`` and ``rules/railratings`` both answer the same way when a
rail's voltage nobody has stated: an UNKNOWN row that names the address it may be
written at (``requirements.rails[net=…].voltage``). That is a correct verdict and
a bad work order, because it leaves the *decision* with the reviewer on every
single run: the same net is asked about again on the next pass, and on the one
after that. 岳's ruling (2026-10-07) turns the address into a **once**:
enumerate the nets whose voltage only the engineer knows, ask them one at a
time, and write each answer into the DesignIntent contract with
``provenance: user_stated`` so the next run reuses it and says nothing.

This module is that enumeration, and nothing else — it does not ask, does not
write and does not judge a board. It answers one question per net: *is this net
a power net whose voltage no source has priced?* The caller prints the list and
stops; the answer comes back through
:func:`boardwise.cli._cmd_intent_set_rail`, which writes it through
:mod:`boardwise.core.designintent`.

**The vocabulary, and why the test is two clauses.** A net has to be *named like
a supply* **or** *carry a supply pin* to be on the list at all — the union of the
two, so neither a spelled-out rail (``VCC``, ``TVDD``, ``VCCI``) nor an
auto-named one (``NET11`` carrying an LDO's ``VDD``) is missed:

* :data:`_RAIL_NAME` — the *name* family: a ``V``-rooted rail spelling
  (``VCC``/``VCCA``/``VDD``/``VDDA``/``VDDIO``/``DVDD``/``VDD_1``/``IOVDD``/
  ``TVDD``/``VBAT``/``VBUS``/``VIN``/``VM``/``VS``/``VEE``/``VREF``/``VREF+``/
  ``V+`` and the digit/letter suffixes designers glue on). It is a prefix
  match, guarded so a prefix cannot be rescued by a blocklist-free suffix:
  ``VCC`` matches, ``VCCA`` matches, ``VCCIO`` matches, and a name that merely
  *contains* a ``V`` somewhere (``RECV``, ``DRV_EN``) does not.
* :func:`boardwise.core.pinrole.pin_role` — a pin on the net whose name says
  ``IN`` or ``OUT`` (:data:`SUPPLY_ROLES`) **and** is spelled as one of
  :data:`_RAIL_NAME`'s rails. Both clauses, because they answer different
  questions: 131a says what the pin's *job* is (``VDD``/``VBAT``/``VCC``/``VM``/
  ``VIN`` read as a supply input, ``VOUT`` as a supply output, and ``EN``/``SW``/
  ``FB``/``BST``/``GND`` do not), and the rail vocabulary says whether that job is
  a **supply's**. A bare direction word is not a rail name: ``OUT`` is how a part
  labels a port — the measured counterexamples are a voltage transformer writing
  ``IN``/``IN``/``OUT``/``OUT`` on its four pins and a current transducer writing
  ``OUT`` on its output (``毕设滤波采样``'s ``L2`` and ``U6.12``), i.e. five nets
  that the loose reading would ask an engineer to price and none of which is a rail.
  ``VSSA``-style returns are excluded here for free, and the name family catches
  what the pin test cannot (a net that only a connector's ``VBUS`` sits on is
  priced by neither the name nor a component pin of a catalogued part).

  **What the second clause costs, stated plainly**: a regulator whose output pin
  is literally named ``OUT``, on a net that is not rail-named, is not enumerated
  (measured: ``FPC触屏游戏机``'s SOT-23-6 boost writes ``OUT`` on ``NET1``). The
  cost is bounded — nothing is silently accepted as fine, the rules that wanted
  that voltage still print their own UNKNOWN row naming
  ``requirements.rails[net=…].voltage``, which is the pre-#65 behaviour this
  enumeration improves on. The audit misses one question; it does not lose a
  verdict.

**A name that states its voltage is never on the list** — ``+5V``/``12V``/``3V3``
by the whole-name whitelist (:func:`boardwise.core.power_domains.
voltage_from_net_name`) and ``A5V``/``D5V``/``15V+``/``VDD_3V3`` by
:data:`_NAME_STATES_VOLTS`, which reads a voltage **anywhere** in the name. The
first is the vocabulary the rules themselves price; the second exists because
``A5V`` does state 5 V to every human who reads it, and asking the engineer what
``A5V`` is would spend the one question this command exists to spend on a fact
the drawing already carries in its own lettering.

**A net that states an arithmetic relation to another rail is settled too.**
``VCC/2`` is a divider tap, and the formula is the answer — asking a voltage for
it would spend the one question this command exists to spend on something the
name already said in symbols (:data:`_NAME_IS_DERIVED`).

**Ground is settled, not asked.** :func:`boardwise.core.model.is_ground_net`
covers ``GND``/``AGND``/``PGND``/``VSS``/…: a ground net's potential is the
board's 0 V reference by definition, ``pcb-voltage-spacing`` already prices it as
``GROUND_VOLTS``, and there is no answer an engineer could give that the board
does not already declare. Those rows come back in :attr:`RailAudit.settled`
with the reason written down, not in the ask list — a filtered net that says
nothing is how a reader ends up re-deriving the filter by hand.

**A net the architecture already priced is settled too**, and this is the half
that makes the list worth running: ``VCC`` on a board whose regulator declares
3.3 V is not an open question even though the contract is silent about it. The
enumeration is read through the **public**
:func:`~boardwise.core.architecture.generate_architecture` — the same call
``cli.checkup`` makes — so "what the drawing already supports" has one
implementation, and this module never re-derives a rail or a voltage.

One rail, one answer. :func:`set_rail_voltage` is the writer: it merges one
``voltage`` — and the ``targetVoltage`` that is the same answer in 092's
vocabulary, so no reader is left asking — into one ``rails[net=…]`` entry and
leaves every other key, every other entry and the entry's position alone,
because a contract that came back different from the one an engineer just
answered for is the 052 §2.2 accident one level down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .circuitspec import PROVENANCE_USER_STATED
from .designintent import (
    SECTION_RAILS,
    DesignIntent,
    DesignIntentError,
    IntentRail,
    write_path,
)
from .model import BoardModel, DesignModel, is_ground_net
from .parts import PartLibrary
from .pinrole import pin_role
from .power_domains import voltage_from_net_name
from .values import parse_voltage_volts

__all__ = [
    "RAIL_QUERY",
    "RAIL_VOLTAGE_SLOTS",
    "RailAudit",
    "RailQuery",
    "SUPPLY_ROLES",
    "audit_rails",
    "is_supply_name",
    "name_states_volts",
    "set_rail_voltage",
]

#: The token the contract and the SOP name, so the reviewer's question and the
#: report's row cannot drift apart. One string, read by the CLI's own output and
#: by `docs/review-sop.md` §3.1b.
RAIL_QUERY = "intent-missing"

#: The two contract slots a rail's voltage is stated in, in reading order.
#:
#: They are two readings of **one** answer, not two questions: ``voltage`` is the
#: value the rail *is* (the settled slot — this module's audit and
#: ``rules.pcb.ipc.declared_voltages`` read it first) and ``targetVoltage`` is the
#: design *target* (092 A2b's slot, the one ``pwr-cap-voltage-rating`` /
#: ``path-ldo-dissipation`` were written against). Under
#: ``provenance: user_stated`` one answer is both, so :func:`set_rail_voltage`
#: writes both and every reader accepts either — answering through one slot used
#: to leave the other family reporting ``intent-missing`` for a rail an engineer
#: had already priced (064 and 139 hit the same seam, evidence/064).
RAIL_VOLTAGE_SLOTS: tuple[str, ...] = ("voltage", "targetVoltage")

#: The pin roles that make a net a **power** net. ``IN`` is a supply input
#: (``VDD``/``VCC``/``VIN``/``VM``), ``OUT`` is a supply output (``VOUT``). The
#: other seven of 131a's nine are deliberately not here: a ``SW``/``FB``/``BST``
#: net is a switching node the rail rules have their own reading for, an ``EN``
#: net is a control signal, and a ``GND`` role is a return — a net is not a rail
#: because something on it is wired to a ground pin.
#:
#: A role from this set is **half** the pin test; the other half is
#: :func:`is_supply_name` on the pin's own name (see :func:`_supply_members`).
SUPPLY_ROLES: frozenset[str] = frozenset({"IN", "OUT"})

#: The **name** family of a supply rail, matched case-insensitively as a prefix.
#:
#: A prefix (not a whole name) because the trade appends a qualifier to the same
#: stem — ``VCCA``, ``VCCIO``, ``VDDA``, ``VDDB``, ``VCCI``, ``VDDIO``,
#: ``DVDD``, ``IOVDD``, ``TVDD``, ``VDD_1`` — and a whole-name table would need
#: every suffix anyone has ever typed. Guarded on the left so only a name
#: *starting* with one of these stems counts: ``RECV``/``DRV_EN``/``PVDD``'s
#: sibling ``DVDD_EN`` is a rail by this table (a ``DVDD`` stem), but
#: ``ADVCC`` is not a rail this build claims to recognise, and
#: :func:`is_supply_name` says so rather than guessing at the tail.
_RAIL_NAME = re.compile(
    r"^(?:"
    r"VCC|VSS|VDD|DVDD|AVDD|IOVDD|TVDD|LVDD"     # the VDD family and its prefixes
    r"|VBAT|VBUS|VEE"                            # battery / bus / negative supply
    r"|VIN|VOUT|VM|VS"                           # regulator-side rail names
    r"|VREF|VREFP|VREFN"                         # references: not ground, not 0 V
    r"|V\+|VP|VN"                               # the polarity-only spellings
    r")",
    re.IGNORECASE,
)

#: A voltage written **anywhere** in a net name: ``A5V``/``D5V``/``15V+``/
#: ``VDD_3V3``/``3V3_SENSOR``. Whitelisted-shaped (a number, an optional sign, a
#: ``V``) and never applied to a name the whole-name reader already priced, so
#: the two readers cannot disagree about ``+5V`` — they answer the same way.
#:
#: Two numbered shapes, and the ``V``-as-decimal-point one comes first: the trade
#: writes 3.3 V as ``3V3``, so ``VDD_3V3`` must come back as ``3V3`` rather than
#: the ``3V`` a plain ``\d+V`` leaves behind — the matched text is quoted to the
#: engineer as *where* the reading came from, and a truncated quote is a wrong
#: one. Only then the plain ``5V``/``3.3V`` shape.
_NAME_STATES_VOLTS = re.compile(r"[+-]?(?:\d+V\d+|\d+(?:\.\d+)?\s*V)", re.IGNORECASE)

#: A name that states an **arithmetic** relation to another rail: ``VCC/2`` is
#: the divider tap of ``VCC``, not a rail an engineer has to price. It is settled
#: rather than asked, and the reason says why — "half of VCC" is a formula, and
#: asking a voltage for it would spend the one question on something the name
#: already answered in symbols. Only ``/`` and ``*`` count: ``VCC-1`` and
#: ``VCC_1`` are two rails a designer chose to call similar, and a dash is too
#: ordinary a character in a net name to read as arithmetic.
_NAME_IS_DERIVED = re.compile(r"^.+[/][0-9.]+$|^.+[*][0-9.]+$")


def is_supply_name(net: str | None) -> bool:
    """Does this **name** belong to the supply-rail vocabulary?

    ``VCC``/``VCCA``/``VDDA``/``TVDD``/``VBAT``/``VREF+``/``VM`` → True;
    ``CAN_RX``/``U+``/``NET11``/``RECV``/``DRV_EN`` → False. A name is one of the
    two halves of :func:`audit_rails`' test, never the whole of it: an
    auto-named ``NET11`` that carries an LDO's output pin is a rail this audit
    lists, and it does so on the pin half.
    """
    return bool(_RAIL_NAME.match(str(net or "").strip()))


def name_states_volts(net: str | None) -> str:
    """The voltage this net's **own name** states, or ``""``.

    ``+5V``/``3V3`` come from the whole-name whitelist the rules read
    (:func:`boardwise.core.power_domains.voltage_from_net_name`) and are
    returned in their own spelling; ``A5V``/``D5V``/``15V+`` have no whole-name
    form, and the embedded read returns the matched text so the caller can quote
    where the number came from. A name that states nothing returns ``""`` — never
    ``0``, never a guess.
    """
    text = str(net or "").strip()
    if not text:
        return ""
    hit = voltage_from_net_name(text)
    if hit is not None:
        return text
    found = _NAME_STATES_VOLTS.search(text)
    return found.group(0) if found is not None else ""


@dataclass(frozen=True)
class RailQuery:
    """One net's answer to "does this rail still owe the engineer a voltage?".

    ``settled`` is the whole verdict: a row with ``settled`` empty is on the ask
    list, and a row with one is not. The two reasons a row is settled are
    deliberately distinct words — the **contract** already carries an engineer's
    answer (:attr:`stated_voltage`, ``provenance`` beside it) versus **the
    drawing** already prices it (the name, the architecture enumeration) — because
    only the first is something ``intent set-rail`` would change, and a reviewer
    reading the list needs to know which of the two they are looking at.
    """

    net: str
    board: str = ""
    members: tuple[str, ...] = ()
    why: str = ""
    stated_voltage: str = ""
    provenance: str = ""
    settled_by: str = ""
    write: str = ""

    @property
    def settled(self) -> bool:
        """Is this rail's voltage already known to somebody? Then do not ask."""
        return bool(self.settled_by)

    def to_jsonable(self) -> dict:
        body: dict = {
            "net": self.net,
            "board": self.board,
            "why": self.why,
            "members": list(self.members),
            "write": self.write,
            "settled": self.settled,
        }
        if self.stated_voltage:
            body["statedVoltage"] = self.stated_voltage
            body["provenance"] = self.provenance
        if self.settled_by:
            body["settledBy"] = self.settled_by
        return body


@dataclass
class RailAudit:
    """``(ask, settled)`` — the two halves of one run's enumeration.

    ``ask`` is the work order: every power net whose voltage no source prices,
    sorted, each with the pin evidence that put it on the list and the exact
    contract key the answer goes to. ``settled`` is everything that looked like a
    power net and already has a number — kept, with the reason, so a reviewer who
    remembers a net being asked about can see **where** the answer came from
    instead of asking again (the ruling's 「不再重复问」, made checkable).
    """

    ask: list[RailQuery] = field(default_factory=list)
    settled: list[RailQuery] = field(default_factory=list)

    @property
    def ask_count(self) -> int:
        return len(self.ask)

    @property
    def settled_count(self) -> int:
        return len(self.settled)

    def to_jsonable(self) -> dict:
        return {
            "token": RAIL_QUERY,
            "ask": [row.to_jsonable() for row in self.ask],
            "settled": [row.to_jsonable() for row in self.settled],
            "totals": {
                "ask": len(self.ask),
                "settled": len(self.settled),
            },
        }


def _board_title(model: object) -> str:
    board = getattr(model, "board", None)
    return str(getattr(board, "title", "") or "")


def _supply_members(model: object, net: str, limit: int = 6) -> list[str]:
    """``U1.16(VDD)``-style evidence for the supply pins sitting on ``net``.

    Read through the model's own reverse index (net → ``(designator, pin)``) and
    the component's pins, so the evidence names the pin whose *name* declared the
    role — that is the whole claim being made, and quoting ``U1.16(VDD)`` lets a
    reader check it in one glance. Two tests decide, and both have to pass:
    131a's :func:`~boardwise.core.pinrole.pin_role` says the pin's job is a
    supply direction (:data:`SUPPLY_ROLES`), and :func:`is_supply_name` says the
    name it declares that job with is one of the rail spellings. A bare ``OUT``
    or ``IN`` fails the second and is a port label, not evidence — the measured
    counterexamples are in the module docstring. Capped at ``limit`` because a
    ``GND``-like rail on a big board has hundreds of members and the first few
    are as convincing as all of them; the count of hits is reported separately.
    """
    nets = getattr(model, "nets", {})
    net_record = nets.get(net) if hasattr(nets, "get") else None
    pins = list(getattr(net_record, "pins", []) or [])
    components = getattr(model, "components", {})
    out: list[str] = []
    for designator, number in pins:
        component = components.get(designator)
        if component is None:
            continue
        for pin in getattr(component, "pins", []) or []:
            if pin.number != number or not pin.name:
                continue
            if pin_role(pin.name) in SUPPLY_ROLES and is_supply_name(pin.name):
                out.append(f"{designator}.{number}({pin.name})")
            break
    return out[:limit]


def _architecture_prices(
    model: object, library: PartLibrary | None
) -> dict[str, tuple[float, str]]:
    """``net -> (volts, where)`` for the rails the drawing itself supports.

    Read through the public :func:`~boardwise.core.architecture.
    generate_architecture`, so the answer is literally the one ``checkup``'s
    report prints for the same board. **A failure contributes nothing** rather
    than raising: this enumeration is a work order, and a work order that
    crashes on a board the review itself walked would be a worse defect than the
    extra question it failed to suppress.
    """
    try:
        from .architecture import generate_architecture

        enumeration = generate_architecture(model, library=library)
    except Exception:  # noqa: BLE001 — a narrower reading, never a crash
        return {}
    out: dict[str, tuple[float, str]] = {}
    for rail in (enumeration.section.get("chains") or {}).get("rails") or []:
        net = str(rail.get("net") or "").strip()
        volts = rail.get("voltage")
        if not net or not isinstance(volts, (int, float)) or isinstance(volts, bool):
            continue
        out[net] = (
            float(volts),
            f"architecture.chains.rails[net={net}].voltage = {volts:g} V"
            + (f" ({rail.get('voltageSource')})" if rail.get("voltageSource") else ""),
        )
    return out


def audit_rails(
    model: DesignModel | BoardModel,
    contract: DesignIntent | None = None,
    *,
    library: PartLibrary | None = None,
) -> RailAudit:
    """Every power net whose voltage nobody has stated, and why the rest are not.

    Walked **per board** by the caller (``ProjectModel.boards``), because one
    project is not one netlist and ``VCC`` on Board1 is not ``VCC`` on Board2.
    ``contract`` is the DesignIntent the run reads (``checkup --intent`` or the
    user-level default) and may be ``None`` — no contract is the normal state of
    a first review, and it makes every priced-by-nothing rail a question rather
    than an error.

    The order of the three settled-reasons is the order of authority: the
    **contract** first (an engineer said it, and nothing overrides that), then
    **the net's own name**, then **the architecture enumeration** (a shelf
    regulator's declared or MPN-decoded output). The first one that has a number
    is the one reported, and only that one — a rail the contract prices at 5 V
    while the enumeration reads 3.3 V is a conflict for
    ``arch-rail-voltage-clash`` to adjudicate, and this enumeration's job is to
    notice that the question is answered, not to pick a side.
    """
    audit = RailAudit()
    priced = _architecture_prices(model, library)
    for net in sorted(getattr(model, "nets", {}) or {}):
        name = str(net or "").strip()
        if not name:
            continue
        members = _supply_members(model, name)
        by_name = is_supply_name(name)
        ground = is_ground_net(name)
        if not by_name and not members and not ground:
            continue  # not a power net by any test: the rule has nothing to say
        if by_name:
            why = f"网名是电源轨写法（{name!r}）"
        elif members:
            why = "网上挂着电源脚（" + "、".join(members) + "）"
        else:
            # A ground net whose own name is not one of the rail spellings and
            # which carries no supply pin: it is here on `is_ground_net` alone,
            # so the row has to say that instead of borrowing either of the two
            # clauses it did not pass.
            why = f"地网（{name!r}）——0 V 是这块板的定义，不是一条要问价的电源轨"
        if by_name and members:
            why += f"；电源脚：{'、'.join(members)}"
        stated = _contract_voltage(contract, name)
        own = name_states_volts(name)
        drawn = priced.get(name)
        settled_by = ""
        stated_voltage = ""
        provenance = ""
        if stated:
            stated_voltage, provenance = stated
            settled_by = (
                f"合同里已经写了 {write_path(SECTION_RAILS, name, 'voltage')} = "
                f"{stated_voltage!r}（{provenance}）——不再问"
            )
        elif own:
            settled_by = f"网名自带电压（{own!r}）——图上已经写着这个数"
        elif ground:
            settled_by = (
                f"地网：{name!r} 按定义是这块板的 0 V 参考，几何规则已经按它定价"
            )
        elif _NAME_IS_DERIVED.match(name):
            settled_by = (
                f"派生轨：{name!r} 是别的轨的分压/倍数关系（图上写着的算式），"
                "不是一条要单独定价的电源轨"
            )
        elif drawn is not None:
            settled_by = f"图纸已经定出价：{drawn[1]}"
        row = RailQuery(
            net=name,
            board=_board_title(model),
            members=tuple(members),
            why=why,
            stated_voltage=stated_voltage,
            provenance=provenance,
            settled_by=settled_by,
            write=write_path(SECTION_RAILS, name, "voltage"),
        )
        (audit.settled if row.settled else audit.ask).append(row)
    return audit


def _contract_voltage(
    contract: DesignIntent | None, net: str
) -> tuple[str, str] | None:
    """``(value, provenance)`` the contract states for ``net``, or ``None``.

    ``voltage`` before ``targetVoltage`` — the same precedence
    :func:`boardwise.rules.pcb.ipc.declared_voltages` uses, so a rail the rules
    would price is a rail this audit does not ask about. An entry that exists but
    answers neither slot returns ``None`` (the net is still an open question, and
    ``intent set-rail`` will fill the same entry), and an entry marked ``stale``
    still counts: a rail the drawing moved out from under keeps the answer an
    engineer gave, and re-asking it is exactly the repetition the ruling closed.
    """
    if contract is None:
        return None
    entry = contract.entry(SECTION_RAILS, net)
    if entry is None:
        return None
    for slot in RAIL_VOLTAGE_SLOTS:
        value = str(getattr(entry, "slots", {}).get(slot, "") or "").strip()
        if value:
            return value, str(getattr(entry, "provenance", "") or "")
    return None


def set_rail_voltage(document: DesignIntent, net: str, voltage: str) -> tuple[DesignIntent, str]:
    """``(updated document, what changed)`` — one rail's voltage, one write.

    The write is deliberately small, because the contract is the engineer's
    document and this command is a clerk: it sets ``rails[net=…].voltage`` **and**
    ``rails[net=…].targetVoltage`` to the same value, the entry's ``provenance``
    to :data:`~boardwise.core.designintent.PROVENANCE_USER_STATED`, and **touches
    nothing else** — not the entry's ``role``, not its other slots, not another
    entry, not the order. An entry that does not exist is created (at the front,
    the way :func:`~boardwise.core.designintent.merge` inserts, so no existing
    line moves) — with the same ``provenance``, because a brand-new entry that
    came back a *draft* would be this command refusing to record what the engineer
    just said. An entry that does keeps its position and its bytes.

    **Why one answer goes into two slots** (139 收口; evidence/064): ``voltage``
    and ``targetVoltage`` are two *semantic* readings of the same engineer's
    answer — ``voltage`` is the value the rail **is** (the settled slot:
    ``pcb-voltage-spacing``, :func:`_contract_voltage` and the PCB writer all read
    it first) while ``targetVoltage`` is the design **goal** (092 A2b's slot, the
    one ``pwr-cap-voltage-rating`` / ``path-ldo-dissipation`` were written
    against). Under ``user_stated`` the two are the same statement, so writing
    only one of them left the other family reporting ``intent-missing`` for a rail
    the engineer had just priced — 064's ``sel-ldo-fixed-output`` and 139's own
    audit both read the contract that way and both concluded "nobody answered".
    Writing both, same value, is what makes *any* reader price the rail,
    including the 092-era readers that know only ``targetVoltage`` (see
    :data:`RAIL_VOLTAGE_SLOTS`).

    A value this build cannot read as a voltage is **refused** by name rather
    than stored: the contract's values are free text, but these slots are read by
    arithmetic (:func:`boardwise.core.values.parse_voltage_volts` is what
    ``pcb-voltage-spacing`` and ``pwr-cap-voltage-rating`` price them with), and
    writing a string no reader can turn into volts would leave the rail asking
    the same question forever — the defect this whole module exists to close.
    The previous value is returned so the caller can print it, and
    ``stale``/``provenance`` of an untouched entry are left as they were.
    """
    name = str(net or "").strip()
    if not name:
        raise DesignIntentError("the net name is empty — name the rail to price")
    text = str(voltage or "").strip()
    volts = parse_voltage_volts(text)
    if volts is None:
        raise DesignIntentError(
            f"{text!r} is not a voltage this build can read (a number, an optional "
            f"sign, and a V: '3.3V', '3V3', '5V', '+5V', '-12V') — the rail's "
            "voltage is priced by arithmetic, so a value no reader can turn into "
            "volts would leave this question open forever"
        )
    updated = document.copy()
    entry = updated.entry(SECTION_RAILS, name)
    if entry is None:
        updated.set_entry(
            SECTION_RAILS,
            IntentRail(
                net=name,
                slots={slot: text for slot in RAIL_VOLTAGE_SLOTS},
                provenance=PROVENANCE_USER_STATED,
            ),
        )
        return updated, f"new entry, voltage = {text!r}, targetVoltage = {text!r}"
    # What each slot held before the write: a correction has to be visible
    # whichever of the two carried the old answer, and the sentence the engineer
    # reads names both keys either way.
    before = {
        slot: str(entry.slots.get(slot, "") or "") for slot in RAIL_VOLTAGE_SLOTS
    }
    for slot in RAIL_VOLTAGE_SLOTS:
        entry.slots[slot] = text
    entry.provenance = PROVENANCE_USER_STATED
    if any(value and value != text for value in before.values()):
        return updated, (
            ", ".join(
                f"{slot} {before[slot] or '(empty)'!r} -> {text!r}"
                for slot in RAIL_VOLTAGE_SLOTS
            )
            + " (was stated; corrected)"
        )
    if any(before.values()):
        return updated, (
            f"voltage = {text!r}, targetVoltage = {text!r} restated (unchanged)"
        )
    return updated, f"voltage = {text!r}, targetVoltage = {text!r} (was empty)"

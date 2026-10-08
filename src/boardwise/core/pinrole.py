"""What a pin's **name** says its job is, and nothing more (task 131a).

:func:`pin_role` turns one pin name — the ``Pin Name`` a ``.epro2`` SYMBOL
document declares, which :mod:`boardwise.parsers.epro2_model` now joins onto the
PCB-side model — into a coarse electrical role, or ``None`` when the name does
not say. It is the ground the power rules (131b/131c) stand on: a rule that
wants "this regulator's output pin" asks for ``pin_role(...) == "OUT"`` and
never pattern-matches ``VOUT`` itself.

It is **not** a second version of
:data:`boardwise.core.symbolprofile.ROLE_BY_PIN_NAME`. That table belongs to the
053/060 drawing grammar, names roles in its own vocabulary (``VIN``/``VOUT``),
and changing it would change what the compiler draws. This module is read-only
over a name string and is deliberately separate.

Why ``None`` is the common answer
---------------------------------

A wrong role is worse than an absent one: a rule that acts on a wrong role
reports a finding against a pin that is not the one it means, and the finding
reads as a defect in the design. So the table below only holds names whose job
is the **same on every part that carries the name**, and everything else returns
``None`` — including names that are perfectly clear to a human and simply are
not one of the nine roles here.

Vocabulary, and where each entry comes from
-------------------------------------------

Two provenances, both stated per group because they carry different weight:

* **measured** — the name occurs on a fixture in ``tests/fixtures`` *and* its
  net confirms the reading. The nets quoted are the evidence; they are what make
  an entry a measurement rather than a recollection.
* **standard** — the name is the industry-wide spelling for that job but is not
  exercised by a fixture. Kept because the part it names is common; noted so a
  reader knows which entries are load-bearing on this corpus.

Roles and their precedence
--------------------------

Checked in this order, and the order is the contract:

1. :data:`_OSC_SUBSTRING` — a name carrying ``OSC`` names an oscillator and
   is not a supply pin (131d). Checked first because the failure it closes is
   the token scan's, and only the token scan produces it.
2. :data:`_NOT_A_ROLE` — names that are affirmatively *not* one of the nine
   roles, matched before anything else so a blocklisted name can never be
   rescued by token splitting.
3. :data:`_WHOLE_NAME` — the whole normalised name in the table.
4. token scan — a compound name (``EN/UVLO``, ``GND/ADJ``, ``VEE/GND``,
   ``OUT A``) is split on :data:`_SEPARATORS` and the **highest-precedence
   resolving token** wins. Precedence is :data:`ROLE_PRECEDENCE`, which is why
   ``GND/ADJ`` reads ``GND`` (the ``ADJ`` half is not a role) and ``EN/UVLO``
   reads ``EN`` (the ``UVLO`` half is not a role either — it is what the enable
   pin *does*, not a second pin).

``GND`` outranks ``OUT`` deliberately: ``VEE/GND`` is a return pin that happens
to be written with a supply name beside it, and reading it as an output would
put a decoupling rule on a ground pad.

**The oscillator family is the reason a blocklisted *token* has to void a
compound name (131d).** That behaviour already existed for the gate-driver
channel halves (``INA/OUT`` reads nothing); an STM32 oscillator pin reached it
the same way and is why it is now load-bearing. ``PF0-OSC_IN`` splits on the
underscore into ``PF0-OSC`` + ``IN``, the ``IN`` half is a table hit, and the
pin resolved as a **supply input** — the exact failure this module exists to
prevent, reached through a name that looks like one of the nine. The four
misjudgements are measured on the corpus: ``PH0-OSC_IN`` / ``PH1-OSC_OUT`` on
毕设FOC 1.0.0 and 1.1.0, ``PF0-OSC_IN`` / ``PF1-OSC_OUT`` on ROBOT ctrl FOC
and 药箱, ``PC14-OSC32_IN`` / ``PC15-OSC32_OUT`` on every STM32 in the
fixtures, ``PD0-OSC_IN`` / ``PD1-OSC_OUT`` on 超声波.
"""

from __future__ import annotations

import re

__all__ = [
    "PIN_ROLES",
    "ROLE_PRECEDENCE",
    "pin_role",
]


#: The roles this classifier can return. Anything outside this set is a bug in a
#: caller, not a name this module declined to classify.
PIN_ROLES: frozenset[str] = frozenset(
    {"IN", "OUT", "SW", "FB", "EN", "BST", "EP", "GND"}
)

#: Which role wins when a compound name resolves to more than one. Only the
#: pairs that actually occur are ordered against each other; ``GND`` before
#: ``OUT`` is the load-bearing one (``VEE/GND``, measured on 毕设FOC's U14/15/16
#: — pin 4 on net ``AGND``).
ROLE_PRECEDENCE: tuple[str, ...] = ("GND", "EP", "EN", "BST", "SW", "FB", "OUT", "IN")


#: Names affirmatively **not** one of the nine roles, matched against the whole
#: normalised name before token splitting.
#:
#: * measured as explicitly having no supply meaning: ``NC`` (25 occurrences,
#:   every one on ``net=None``), ``PGOOD`` (3, all unconnected on the 毕设FOC and
#:   高速板 LM5164), ``RON`` (3, on a resistor divider ``$1N66669`` / ``NET28`` /
#:   ``NET23`` — a programming pin, not a rail), ``RESV`` (3, all unconnected).
#: * gate-driver **channel** pins: ``INA+`` / ``INA-`` / ``INB+`` / ``INB-`` /
#:   ``INA`` / ``INB`` / ``OUTA`` / ``OUTB`` / ``IN A+`` / ``IN A-`` / ``IN B+``
#:   / ``IN B-`` / ``OUT A`` / ``OUT B`` (measured 8+ each across U14/U15/U16 of
#:   毕设FOC and U2/U3 of 级联多电平, landing on nets ``IA``/``IC``/``NET5``…). They
#:   read as IN/OUT but are one channel's high/low pair, so calling them the
#:   part's supply ``IN`` would point a decoupling rule at a gate. This is the
#:   reason ``IN A+`` is listed here explicitly *and* ``OUT A`` is not rescued by
#:   the token scan: blocklist first, always.
#: * bare polarities and one-letter names: ``+``/``-``/``A``/``K``/``C``/``G``/
#:   ``D``/``S``/``R``/``15V+``/``15V-``. On an LED, a diode or a bridge these
#:   are polarity, not a rail direction; the same letter is an address bit on
#:   anything else.
#:
#: The **oscillator family is deliberately not here** (131d). ``PH0-OSC_IN`` /
#: ``PF0-OSC_IN`` / ``PC14-OSC32_IN`` used to resolve to ``IN`` / ``OUT`` — the
#: token scan splits ``PF0-OSC_IN`` on the underscore into ``PF0-OSC`` + ``IN``
#: and the ``IN`` half is a table hit — but ``-`` is *not* in
#: :data:`_SEPARATORS`, so the token is the whole ``PF0-OSC`` and enumerating
#: it here would mean one entry per STM32 port pin. :data:`_OSC_SUBSTRING`
#: short-circuits the family instead; see the module docstring.
_NOT_A_ROLE: frozenset[str] = frozenset(
    {
        "NC", "NC/", "PGOOD", "RON", "RESV",
        "INA", "INB", "INA+", "INA-", "INB+", "INB-",
        "OUTA", "OUTB",
        "IN A", "IN B", "OUT A", "OUT B",
        "IN A+", "IN A-", "IN B+", "IN B-",
        "+", "-", "A", "K", "C", "G", "D", "S", "R",
        "15V+", "15V-",
    }
)


#: Any pin name carrying this substring names an **oscillator** and is not one
#: of the nine roles (131d).
#:
#: **Why a substring and not a table entry.** The measured spellings are
#: ``PH0-OSC_IN`` / ``PH1-OSC_OUT`` (毕设FOC 1.0.0 and 1.1.0, 高速板),
#: ``PF0-OSC_IN`` / ``PF1-OSC_OUT`` (ROBOT ctrl FOC, 药箱),
#: ``PC14-OSC32_IN`` / ``PC15-OSC32_OUT`` (every STM32 on the corpus),
#: ``PD0-OSC_IN`` / ``PD1-OSC_OUT`` (超声波) and the crystal's own ``OSC1`` /
#: ``OSC2`` — and behind each port-pin name stands every other pin of the same
#: family that no fixture happens to place. :data:`_SEPARATORS` splits ``_`` but
#: **not** ``-``, so the token the table would have to enumerate is the whole
#: ``PF0-OSC``: one entry per port pin, on a part whose pin names are its own
#: naming, not a fixed vocabulary. A substring is the shape the family has.
#:
#: **What it costs, stated plainly.** ``OSC`` is a substring, so a name that
#: merely *contains* it is refused — a hypothetical ``OSC_EN`` (an oscillator
#: enable) or ``RCC_OSC_IN`` (CubeMX's own spelling for the same pin,
#: :func:`boardwise.core.pintable.port_pin_of` records that disagreement) is
#: refused too. That is the safe direction: this module's contract is that a
#: wrong role is worse than an absent one, and every pin an oscillator
#: sub-circuit has is a pin whose supply role a supply rule must not act on.
#: An oscillator enable is an ``EN``-class pin, and refusing it here costs a
#: caller the ability to learn it is an enable — which no rule in the tree
#: currently asks an MCU about.
#:
#: Checked **before** :data:`_NOT_A_ROLE` and the whole-name table, because the
#: failure it closes is the token scan's and only the token scan produces it.
_OSC_SUBSTRING = "OSC"


#: The whole normalised name -> role.
#:
#: Each entry is annotated with how it is known. The nets in the comments are
#: the measured ones; where a name is marked *standard* no fixture exercises it
#: and the entry rests on the common spelling.
_WHOLE_NAME: dict[str, str] = {
    # --- return / ground. measured: GND 69x, VSS 27x, AGND/DGND/PGND, 0V on
    # 级联多电平 U1.4 = QAHS (the low-side source), VEE/GND on AGND.
    "GND": "GND", "AGND": "GND", "DGND": "GND", "GNDA": "GND", "GNDS": "GND",
    "PGND": "GND", "VSS": "GND", "VSSA": "GND", "VSSB": "GND", "VSSC": "GND",
    "VEE": "GND", "0V": "GND", "VSS_1": "GND", "VSS_2": "GND", "VSS_3": "GND",
    "VSS1": "GND", "VSS2": "GND", "VSS3": "GND",
    # V- measured on 毕设滤波采样 U1.4 / U7.4 / U8.4, all on net ``AGND`` — the
    # negative supply of a dual-rail part is a return, so it belongs here rather
    # than in the ``_NOT_A_ROLE`` polarity list that carries bare ``+`` / ``-``.
    "V-": "GND",

    # --- exposed pad. measured: EP 8x, always on the ground net of its part
    # (毕设FOC U11.9 = PGND, i.e. the SO-8-EP's thermal pad tied to PGND).
    "EP": "EP", "EPAD": "EP", "PAD": "EP", "THERMAL_PAD": "EP",

    # --- enable. measured: EN 16x, `EN/UVLO` 3x (split, see below),
    # ENABLE 3x. CE is *standard* — no fixture places it.
    "EN": "EN", "ENABLE": "EN", "CE": "EN", "NR": "EN",

    # --- bootstrap. measured: BST 3x, on the net between the inductor and the
    # internal high-side supply (毕设FOC U11.7 = $1N66671).
    "BST": "BST", "BOOT": "BST", "BOOST": "BST",

    # --- switching node. measured: SW 4x (毕设FOC U11.8 = $1N66672).
    # LX is *standard* (the other common spelling of the inductor node).
    "SW": "SW", "VSW": "SW", "LX": "SW",

    # --- feedback. measured: FB 5x (毕设FOC U11.5 = $1N66466, the divider tap).
    "FB": "FB", "VFB": "FB", "VDIV": "FB",

    # --- supply output. measured: VOUT 13x (DCDC U10.5 = VCC, FPC U5.5 = VCC),
    # VOUTA, `Output` 2x (ROBOT U8.2/.4, both on VCC). VREG/REGOUT are *standard*
    # but deliberately absent from OUT: REGOUT is measured once on a battery
    # charger's status pin, and a regulator-output reading there would be wrong.
    "VOUT": "OUT", "VOUTA": "OUT", "VOUT1": "OUT", "VO": "OUT",
    "OUT": "OUT", "OUTPUT": "OUT",

    # --- supply input. measured: VIN 21x (U5.1/U6.1 on +5V, U11.2 on +24V),
    # VCC 27x, VDD 32x, VDDA 9x (U1.21 on VCCA), VBUS 17x, VBAT 8x (U1.6 on
    # VCC), VM 3x (U10.2 / DRV1.4 on the motor rail), VCCI, DVDD 3x (U10.29),
    # `Input` (ROBOT U8.3 on +12V). V+ is *standard* — the one fixture using it
    # (毕设滤波采样) puts U1.8 on A5V, which agrees.
    "VIN": "IN", "VCC": "IN", "VDD": "IN", "VDDA": "IN", "VDDB": "IN",
    "VDDIO": "IN", "DVDD": "IN", "IOVDD": "IN", "VCCI": "IN", "VCC2": "IN",
    "VBUS": "IN", "VBAT": "IN", "BAT": "IN", "VM": "IN", "VIN1": "IN",
    "VDD_1": "IN", "VDD_2": "IN", "VDD_3": "IN", "VDD1": "IN", "VDD2": "IN",
    "VDD3": "IN", "IN": "IN", "INPUT": "IN", "V+": "IN",
}


#: Characters a compound pin name is split on. ``/`` is the measured case
#: (``EN/UVLO``, ``VEE/GND``, ``GND/ADJ``); space and comma join the same way
#: (``OUT A``); ``_`` covers the ``VSS_1`` / ``VDD_1`` families.
_SEPARATORS = re.compile(r"[/,_ ]+")


def _normalise(name: str) -> str:
    """Uppercase, strip, and squeeze runs of whitespace."""
    return re.sub(r"\s+", " ", (name or "").strip()).upper()


def pin_role(pin_name: str | None) -> str | None:
    """The electrical role this pin name declares, or ``None``.

    ``pin_role("FB") == "FB"``, ``pin_role("EN/UVLO") == "EN"`` (the compound
    name is split and the one role in it wins), ``pin_role("NC") is None`` and
    ``pin_role("") is None``.

    ``None`` means *this name does not declare one of the nine roles* — not
    that the pin has no function. ``RON`` and ``PGOOD`` are the clearest cases:
    both are real, meaningful pins that carry no supply role, and a caller that
    treats ``None`` as "unknown function" rather than "not a supply pin" is the
    only correct way to read it. ``PF0-OSC_IN`` is the case 131d added: it is a
    real pin with a real job (a crystal oscillator input) and no supply role
    at all, and before this batch it answered ``"IN"``.
    """
    text = _normalise(pin_name or "")
    if not text:
        return None
    # 131d, before everything: a name carrying OSC names an oscillator. This
    # has to precede the whole-name table and the blocklist because the fault
    # it closes is the token scan's — `PF0-OSC_IN` splits into `PF0-OSC` and
    # `IN`, and the `IN` half is a table hit.
    if _OSC_SUBSTRING in text:
        return None
    if text in _NOT_A_ROLE:
        return None
    whole = _WHOLE_NAME.get(text)
    if whole is not None:
        return whole
    # A compound name: every part is a candidate, the most specific role wins.
    tokens = [part for part in _SEPARATORS.split(text) if part]
    if len(tokens) < 2:
        return None
    # A blocklisted token voids the whole compound name, not just itself: a
    # channel half (`INA`, `OUTA`) written beside a direction word is still a
    # channel pin, so `INA/OUT` yields no role rather than the `OUT` it
    # superficially contains.
    if any(token in _NOT_A_ROLE for token in tokens):
        return None
    found = {_WHOLE_NAME[token] for token in tokens if token in _WHOLE_NAME}
    for role in ROLE_PRECEDENCE:
        if role in found:
            return role
    return None
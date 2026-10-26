"""The two net-name vocabularies the reviewer and the drawing chain share (540B1).

Both are **pure name tests**: a net has no shelf category and no pin role that
says 「this is the power ground」 or 「nobody named this wire」, so the answer is
spelled by the net's own name and by nothing else. They lived in the two rule
modules that first needed them — :mod:`boardwise.rules.pcb.focground` and
:mod:`boardwise.rules.facts` — and the drawing chain read them through those
rule modules (053/173/C). 540B1 moved the *implementation* down here, into the
shared bottom of the package, and both rule modules re-export these very
objects, so there is exactly one copy of each word list and each regex.

Nothing here imports anything but :mod:`re`: this module is a vocabulary, not a
consumer. The rules and the engines both import *it*, and the arrows therefore
never point from ``core`` up into ``rules``.

**Ground domains — :func:`domain_of` and the two prefix tuples.** The test is a
``strip().upper()`` plus a prefix match, in one order: the **power** family is
consulted first, then the **logic / analog** family, and anything else answers
``""``. That empty string means 「not ground-class *for this word list*」, which
is not the same as 「not ground」 — ``SEC_GND`` / ``ISO_VSS`` are ground words a
caller may know (``core.model.is_ground_net`` does), but neither tuple carries
them, and callers say so rather than quietly filing them under the logic side.

``GROUND_DOMAIN_POWER_PREFIXES`` widens ``core.model``'s narrow ``POWER_GROUND``
reading (``PGND`` only) to the ``P``-prefix family, ``EARTH`` included. It is a
name test and it is the fragile step 133c's module docstring declares: a board
that spells its power ground ``EARTH`` lands in the power domain *by this
declaration* and is judged like any other power ground (D2, 171).

``GROUND_DOMAIN_LOGIC_PREFIXES`` is the corpus's own ground vocabulary minus the
power family — the six words below. Listed rather than derived, and that is the
point: the two tuples are this vocabulary's own **declaration** of which side
each family lands on. They are not the same set in either direction: ``P_GND``
and ``POWER_GND`` are power-side words only this list carries, and a name
``is_ground_net`` knows but neither list holds is placed on **neither** side.

**Auto nets — :func:`is_auto_net` and :data:`AUTO_NET_RE`.** The editor stores
the net of a wire nobody named in two spellings, measured 2026-09-24:

* ``NET1``, ``NET2``, … — how an island with nothing to name it gets stored, and
  how the *export* spells the net of a pin that reaches nothing;
* ``$57N2`` — the editor's **internal id**, which is what its own netlist
  (``sch.netlist``) reports for a wire nobody named. Measured on the same board:
  the very same unnamed wire read ``NET3`` through the export and ``$57N2``
  through ``sch.netlist``, which is what made a plan built on the export answer
  ``stale_before`` for a board that had not moved.

Both carry **no intent** — that is the whole test — so the judgements that ask
「did a person name this?」 must not be fooled by which spelling they are handed.
"""

from __future__ import annotations

import re

__all__ = [
    "AUTO_NET_RE",
    "GROUND_DOMAIN_LOGIC_PREFIXES",
    "GROUND_DOMAIN_POWER_PREFIXES",
    "domain_of",
    "is_auto_net",
]


#: The net-name prefixes that put a ground-class net in the **power** domain.
#:
#: **This is a name test and it is the fragile step the rule module declares.**
#: Measured on the corpus: PCB1 and PCB2 each carry exactly one power-domain
#: ground (``PGND``), while PCB3 and PCB4 carry **none** — so 133c's R1/R1b are
#: structurally silent on those two boards and say so with one INFO row rather
#: than filing a finding about a missing domain.
#: ``POWER_GROUND_PREFIXES`` in :mod:`boardwise.core.model` is deliberately
#: narrower (``PGND`` only) and this list widens it to the ``P``-prefix family,
#: which is where a naming convention puts a power ground — ``P_GND`` /
#: ``POWER_GND`` / ``EARTH`` included, so a board that spells its power ground
#: ``EARTH`` lands in the power domain **by this declaration** and is judged
#: like any other power ground (until D2 fixed the outer sieve it dropped such
#: a name before this list was consulted — see
#: :func:`boardwise.rules.pcb.focground.split_ground_domains`). A ground-class
#: name this list does **not** carry (``SEC_GND``, ``ISO_VSS``) is **UNKNOWN**,
#: not 「logic ground」, and lands in ``GroundDomainSplit.unclassified`` so the
#: R1b row can name it.
GROUND_DOMAIN_POWER_PREFIXES: tuple[str, ...] = ("PGND", "P_GND", "POWER_GND", "EARTH")

#: The net-name prefixes that put a ground-class net in the **logic / analog**
#: domain: the corpus's own ground vocabulary minus the power family. That
#: vocabulary is :data:`boardwise.core.model.GROUND_NET_PREFIXES` — ``GND`` /
#: ``AGND`` / ``DGND`` / ``PGND`` / ``EGND`` / ``SGND`` / ``VSS``, plus ``EARTH``
#: as of 171 — and removing :data:`GROUND_DOMAIN_POWER_PREFIXES` leaves the six
#: words below.
#:
#: Listed rather than derived, and that is the point: the two lists are this
#: vocabulary's own **declaration** of which side each family lands on, and 171
#: grew the shared vocabulary instead of this module. The two are not the same
#: set in either direction — ``P_GND`` / ``POWER_GND`` are power-side words only
#: this module carries, and a name ``is_ground_net`` knows but neither list holds
#: (``SEC_GND``, ``ISO_VSS``) is placed on **neither** side, by name, in
#: ``GroundDomainSplit.unclassified``.
GROUND_DOMAIN_LOGIC_PREFIXES: tuple[str, ...] = (
    "GND",
    "AGND",
    "DGND",
    "EGND",
    "SGND",
    "VSS",
)

#: What the editor calls a net nobody named: ``NET<digits>`` (the export's
#: spelling) or ``$<anything non-blank>`` (the editor's internal id). The input
#: is stripped before the match; the pattern is case-insensitive because the
#: export's casing varies (``net7``). Anchored at both ends, and ``\S+`` is
#: deliberately greedy: it is an **id**, not a name, so whitespace never appears
#: inside one — ``$57 N2`` is not an auto net and is left alone.
AUTO_NET_RE = re.compile(r"^(NET\d+|\$\S+)$", re.IGNORECASE)


def _upper(text: object) -> str:
    return str(text or "").strip().upper()


def domain_of(net: str) -> str:
    """Which ground domain this net name puts it in: ``power`` / ``logic`` / ``""``.

    ``""`` means the name is not ground-class **for this vocabulary's word
    list** — which is not the same as 「not ground」, and the callers say so
    rather than quietly filing it under the logic side.
    """
    upper = _upper(net)
    if not upper:
        return ""
    if any(upper.startswith(p) for p in GROUND_DOMAIN_POWER_PREFIXES):
        return "power"
    if any(upper.startswith(p) for p in GROUND_DOMAIN_LOGIC_PREFIXES):
        return "logic"
    return ""


def is_auto_net(name: str | None) -> bool:
    """Is this an editor-generated net name? (the ones that mean nothing)"""
    return bool(name) and bool(AUTO_NET_RE.match(str(name).strip()))

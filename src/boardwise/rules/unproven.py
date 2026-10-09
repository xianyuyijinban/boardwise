"""The per-page tier's unproven nets, and the refusal a net-shaped rule owes them.

Issue #19. The `per-page` tier reads one page at a time and merges the pages by
net **name** (:func:`boardwise.cli._merge_schematic_models`), because a
single-page export carries no ``SCH``/``BOARD`` document that would say which
board the page belongs to. The merge states that gap in the model
(:attr:`boardwise.core.model.DesignModel.unproven_nets`) and the tier says it in
the report — but a *rule* that looks a net up to find the parts cooperating on
it was not told, and that is the silent defect the issue measured.

The measurement: board 1's ``U1`` is missing its 1 uF on ``VCC`` and on ``+5V``;
board 2 has an unrelated ``C9`` (1 uF) on its own ``VCC``. Reviewed per board,
that is two ``decap-required-caps`` WARNs. Reviewed through the per-page merge,
``C9`` lands in board 1's ``VCC`` — and one of the two WARNs **disappears**,
because the rule found a capacitor that is not on this board at all.

**Agreement by name is not a verified connection.** That sentence is the merge's
own wording for the gap, and it is this refusal's reason: two pages that both
draw a net called ``VCC`` may be two sheets of one board (a real connection) or
two boards that happen to use the same name (no connection at all), and this
tier cannot tell which. So a rule may not conclude either way about the parts it
finds — and that is **both** directions, which is why the refusal is UNKNOWN and
not a withheld pass:

* "a capacitor is on ``VCC``, so the requirement is met" is not established —
  the capacitor may be on the other board (the false pass above);
* "nothing is on ``VCC``, so the requirement is unmet" is not established
  either — the capacitor may be on the page next door, which on a one-board
  project is a legal cross-sheet connection (the false violation).

A rule that refuses here reports UNKNOWN, names the net and the pages it was
seen on, and says which sentence it is obeying.

**Why the same welding is not a defect one tier up.** On a board, two pages that
each carry a label named ``VCC`` *are* one net — that is what a net label means,
and it is why the project-file tier's name-keyed netlist is the reference reading
rather than a guess. The gap is not the welding; it is that the per-page tier
cannot say the pages are one board. So the refusal is scoped to the names the
merge had to weld *blind* (``DesignModel.unproven_nets``), and a model that came
out of one export — every project-file, netlist and ``--file`` reading — carries
no unproven names at all and behaves exactly as it did before issue #19.

**A second gap reaches the same channel (107).** The merge's is about *pages*;
there is another about *placements*. The parser keeps only the first placement of
a repeated designator (049's one-designator-one-component contract, which the
copper layer agrees with), so a part that is drawn on the sheet and really does
connect to a net is simply not a member of it — and the DCDC board is the worked
example: the dropped copies of ``100NF`` sit on ``VCC``, where the board needs a
decoupling capacitor. "No capacitor there" was a confident WARN, and it was not
one: the placement that would satisfy the requirement may be one the model threw
away. So the parser files each such net in the same ``unproven_nets`` channel,
carrying its own reason (:attr:`DesignModel.unproven_reasons`), and the refusal
below says that one instead of the merge's. Both directions are withheld for the
same reason: a truncated member list establishes neither presence nor absence.
The verdicts that change are the ones on **nets**, which is the same population
:data:`NET_MEMBERSHIP_RULES` names; a board with no repeated designator carries
no such name and is untouched byte for byte.

**Which rules these are** is a *list*, not a search: :data:`NET_MEMBERSHIP_RULES`
holds the ids of every rule whose conclusion depends on which other parts sit on
a net. It is what the report's tier note counts ("N rules refuse"), and
``tests/test_checkup_cli.py`` guards it in **both** directions, which 076 made
mechanical rather than claimed:

* an id that is not a built-in rule, or a duplicate, fails
  ``test_every_rule_the_tier_refuses_on_is_a_builtin_rule``;
* and ``test_no_listed_rule_concludes_on_a_board_whose_every_net_is_welded``
  gives **every** listed id a board of its own (``_registry_case``, which raises
  on an id it has no recipe for) with every net unproven, and asserts the rule
  concludes nothing *and* refuses at least one row — so "a listed rule that
  stops refusing" is a failing test rather than a sentence here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..core.model import (
    TRUNCATED_BY_CROSS_PAGE_DESIGNATOR,
    TRUNCATED_BY_DESIGNATOR,
    WELDED_BY_NAME,
    DesignModel,
)
from .base import Outcome

#: The sentence the merge itself uses for the gap, quoted by every refusal so a
#: reader can match a rule's UNKNOWN against the tier's own note.
UNPROVEN_BY_NAME = "agreement by name is not a verified connection"

#: The rule ids whose conclusion depends on which **other parts** sit on a net —
#: the rules the per-page merge can mislead, and the ones the tier note counts.
#:
#: Grouped by what they look up, which is also the shape of the refusal each one
#: makes:
#:
#: * the cooperating part on the net — ``decap-required-caps`` (a capacitor),
#:   ``conn-usb-cc-pulldown`` (a resistor), ``param-divider-output`` (a load),
#:   ``param-led-current`` (the LED's series resistance), ``param-rc-cutoff``
#:   (the resistor's partner capacitor), ``pwr-cap-voltage-rating`` (the
#:   capacitors on a declared rail — 092 A2b), ``arch-opendrain-pullup`` (the
#:   pull-up resistor an open-drain output needs — 093 A3a);
#: * the pin's **company** — ``conn-nc-and-must-connect`` ("alone on this net" and
#:   "shares it with another pin" are the same reading, one netlist over), and
#:   ``arch-nrst-closure``, whose whole judgement is "is this reset pin alone on
#:   its net" (093 A3a: a count of 1 is the F3 shape, more than 1 is the closure);
#: * the net's **voltage**, which the domain inference takes from an LDO's output
#:   pin wherever it is — ``pwr-supply-on-known-domain``, ``pwr-domain-vs-range``,
#:   ``path-ldo-dropout``, ``path-ldo-dissipation`` (092 A2b: the headroom it
#:   squares against the declared current is a difference of two inferred rails,
#:   exactly like ``path-ldo-dropout``'s), and ``arch-rail-voltage-clash`` (093
#:   A3a: one side of the clash *is* that inference, and a rail priced through an
#:   LDO on the page next door is not this board's rail);
#: * both of those at once — ``arch-sense-bias-closure`` (094 A3b) reads *which
#:   resistors* sit on the sense net and *where their far ends go* (a divider
#:   mid-net or a power-class rail, whose voltage it prices), so a name the merge
#:   welded blind can neither supply the parts nor the rail the arithmetic needs.
#:
#: 064 added the two selection rules, both of which read *one part's* spec against
#: *the rail that part is used on* — ``sel-tvs-standoff-rail`` (the stand-off
#: voltage vs the bus it protects) and ``sel-ldo-fixed-output`` (the output step
#: vs the rail behind its output pin). They are here for the second bullet's
#: reason rather than the third's: the part itself is the subject, so nothing
#: about *which other parts are on the net* decides their verdicts — but the
#: **rail's voltage** they read is the domain inference's, and a rail welded by
#: name may belong to another page's board entirely, which would make them
#: compare one board's TVS against another board's bus.
#:
#: The two parameter rules joined the list in 076, and their absence before that
#: was a **misreading of their own code**: they print one part's values, but both
#: *find their partner* by sharing a net with it — ``param-rc-cutoff`` pairs a
#: resistor with a capacitor that shares a non-ground net and is grounded,
#: ``param-led-current`` adopts every resistance sharing a net with the LED and
#: reads the window's voltage off that resistor's far net. A welded name hands
#: each of them the other board's part, so both are net-shaped rules in the sense
#: this list means. What each one reads, exactly:
#:
#: * ``param-led-current`` — the nets the LED and a candidate resistor share
#:   (ground included when that is where they meet: the rule reads that net's
#:   pins like any other), plus the net whose voltage the window is judged in;
#: * ``param-rc-cutoff`` — the non-ground net the pair shares (that filter is the
#:   rule's own, not this list's). The resistor's far net is never read, and the
#:   capacitor's ground side is read **by name** (:func:`is_ground_net`), never by
#:   membership — which also matters practically: a ground name is on every page
#:   of a multi-sheet board, so refusing on it would refuse every RC pair there.
#:
#: The rules that are **not** here, and why: ``conn-duplicate-designators`` reads
#: names, ``conn-library-pin-consistency`` reads one part's pins against the
#: library symbol, and ``param-value-mpn-match`` reads one part's own board value
#: against its own MPN. None of them asks "what else is on this net", so a welded
#: netlist cannot move their verdicts.
#:
#: The two L1 heuristics that *do* ask (`xtal-load-caps`, `shunt-sense-link`) are
#: missing on purpose, and it is a declared gap rather than an oversight: both are
#: legacy ``Rule``s with no four-state protocol, so they cannot say UNKNOWN at
#: all, and converting them is a change to their own contract (their review-eval
#: column moves out of "legacy") that issue #19 does not ask for. What they can
#: do — go quiet on a welded net — they already do, and their messages carry
#: their own "heuristic limits" caveat.
NET_MEMBERSHIP_RULES: tuple[str, ...] = (
    "conn-nc-and-must-connect",
    "conn-usb-cc-pulldown",
    "decap-required-caps",
    "param-divider-output",
    "param-led-current",
    "param-rc-cutoff",
    "path-ldo-dropout",
    "path-ldo-dissipation",
    "pwr-cap-voltage-rating",
    "pwr-domain-vs-range",
    "pwr-supply-on-known-domain",
    "arch-nrst-closure",
    "arch-opendrain-pullup",
    "arch-rail-voltage-clash",
    "arch-sense-bias-closure",
    "sel-tvs-standoff-rail",
    "sel-ldo-fixed-output",
)


class RefusedNet(tuple):
    """One ``(net, pages)`` refusal, carrying **why** this reading cannot prove it.

    A two-element tuple on purpose — every caller here unpacks ``for net, pages
    in found``, and a third element would be a silent change to thirty call
    sites. The reason rides along as an attribute instead, and the builders below
    read it: :data:`boardwise.core.model.WELDED_BY_NAME` (the issue #19 merge)
    and 107's two truncation codes want different sentences, because the gaps
    are different facts.
    """

    def __new__(
        cls, net: str, pages: tuple[str, ...], reason: str, detail: str
    ) -> "RefusedNet":
        self = super().__new__(cls, (net, pages))
        self.reason = reason
        self.detail = detail
        return self

    @property
    def truncated(self) -> bool:
        """Was a placement left out of this net, rather than a page welded in?"""
        return self.reason in (
            TRUNCATED_BY_DESIGNATOR,
            TRUNCATED_BY_CROSS_PAGE_DESIGNATOR,
        )


def unproven_nets(
    model: DesignModel, names: Iterable[str | None]
) -> list[RefusedNet]:
    """Every ``(net, pages)`` among ``names`` this model calls unproven.

    Empty means "all these nets are proven here" — the caller's normal path.
    ``pages`` may be ``()`` ("more than one page, ids unavailable in this
    reading"), which is a real answer and never a "no pages" one.

    The third thing it carries is the **reason**, read from
    ``model.unproven_reasons`` and defaulting to ``WELDED_BY_NAME``: a name
    listed as unproven without one says exactly what issue #19 said, and a name
    whose membership a dropped placement truncated (107) says that instead.
    """
    found: list[RefusedNet] = []
    for name in names:
        if name is None or not name:
            continue
        pages = model.unproven_pages(name)
        if pages is not None:
            reason, detail = model.unproven_reason(name)
            found.append(RefusedNet(name, tuple(pages), reason, detail))
    return found


def _where(pages: Sequence[str]) -> str:
    """How a refusal names the pages a net was seen on (ids may be unknown)."""
    if not pages:
        return "more than one page of this reading (page ids unavailable)"
    return (
        f"{len(pages)} pages of this reading "
        f"({', '.join(page[:8] for page in pages)})"
    )


def _truncated(found: Sequence[RefusedNet]) -> bool:
    """Is this refusal about a dropped placement rather than a welded page?"""
    return any(entry.truncated for entry in found)


def _net_clause(found: Sequence[RefusedNet]) -> str:
    """``net 'VCC' was seen on 2 pages …`` — one net, or the several that refused."""
    if _truncated(found):
        return _truncated_clause(found)
    if len(found) == 1:
        net, pages = found[0]
        return f"net {net!r} was seen on {_where(pages)}"
    return (
        "nets "
        + " and ".join(f"{net!r} ({_where(pages)})" for net, pages in found)
        + " were each seen on more than one page"
    )


#: How a refusal names 107's gap in the words the model used to file it. The
#: codes are the model's; this is their sentence, and the two are kept apart
#: because "two pages may be two boards" and "a placement is missing from this
#: netlist" are not the same claim about the drawing.
TRUNCATION_PHRASES = {
    TRUNCATED_BY_DESIGNATOR: (
        "a netlist in which no placement was left out — this net's membership "
        "may be truncated by a duplicate designator: "
    ),
    TRUNCATED_BY_CROSS_PAGE_DESIGNATOR: (
        "a netlist in which no placement was left out — this net's membership "
        "may be truncated by a duplicate designator drawn across pages: "
    ),
}


def _truncated_clause(found: Sequence[RefusedNet]) -> str:
    """``net 'VCC' may have members missing from it (…)`` — 107's version."""
    entries = [entry for entry in found if entry.truncated]
    if len(entries) == 1:
        entry = entries[0]
        return (
            f"net {entry[0]!r} may have members missing from it "
            f"({entry.detail})"
        )
    return (
        "nets "
        + " and ".join(
            f"{entry[0]!r} may have members missing from it ({entry.detail})"
            for entry in entries
        )
        + " may each be missing members"
    )


def unproven_message(
    subject: str,
    found: Sequence[RefusedNet],
    *,
    what: str,
) -> str:
    """The refusal sentence, without a rule id — for callers that are not an Outcome row.

    :func:`boardwise.rules.facts.pin_ruling` is one: it judges a pin for both the
    rule and the repair, and returns its own :class:`PinRuling`, so it needs the
    same words without owning a row. One builder, so the rule's UNKNOWN and the
    four-state row say the same thing.
    """
    if _truncated(found):
        # 107: the withheld conclusion is the same one — is that part on that
        # net? — and so is the both-directions rule, but the reason a reader is
        # given is the one that applies: the netlist this rule read is missing
        # the placement, so neither "it is there" nor "it is not" is established.
        return (
            f"{subject}: {_net_clause(found)}, so {what} cannot be established — "
            "a placement the model did not keep may be the part this judgement "
            "needs"
        )
    return (
        f"{subject}: {_net_clause(found)}, so {what} cannot be established — "
        "whether those pages are one board is not in this reading"
    )


def unproven_missing_fact(found: Sequence[RefusedNet]) -> str:
    """The fact the refusal is missing — the reading's own sentence, quoted."""
    if _truncated(found):
        entries = [entry for entry in found if entry.truncated]
        phrase = TRUNCATION_PHRASES.get(entries[0].reason)
        if phrase is None:
            phrase = "a netlist in which no placement was left out — "
        return phrase + "; ".join(entry.detail for entry in entries)
    return (
        f"a verified connection for {_net_clause(found)} — this tier cannot "
        f"attribute a page to a board: {UNPROVEN_BY_NAME}"
    )


#: Every sentence :func:`unproven_missing_fact` can produce — the one home for
#: the family, so a third refusal phrasing cannot be added without this noticing.
#:
#: Issue #66 was this list going stale: ``refused_conclusions`` (``engines/review``)
#: matched :data:`UNPROVEN_BY_NAME` alone, so 107's **two** truncation sentences —
#: which name a different gap (a duplicate designator may have left a placement
#: out of the netlist) and therefore do not contain that substring — counted as
#: zero. On the real ``DCDC-12V9V转5V3V3`` fixture all five unproven nets are
#: truncated, two rules really withheld, and the coverage gate reported
#: ``rulesRefused: 0`` — which is the one number that keeps a verdict from
#: claiming ``complete``. One rule, one missing_fact shape, one predicate; a
#: caller that asks "did this reading withhold a conclusion?" asks it here.
REFUSAL_SENTENCES: tuple[str, ...] = (
    UNPROVEN_BY_NAME,
    *TRUNCATION_PHRASES.values(),
)


def is_unproven_refusal(missing_fact: str | None) -> bool:
    """Whether this ``missing_fact`` is the unproven reading refusing to conclude.

    The check is by :data:`REFUSAL_SENTENCES` rather than by a name or a rule
    id, because what the coverage gate needs is "this UNKNOWN exists **because**
    a net could not be verified", and the reader's own sentence is the only thing
    that says so. Matching on one of them (issue #66) silently drops the other
    shapes and makes ``rulesRefused`` read 0 on a board that really withheld.
    """
    text = missing_fact or ""
    return any(sentence in text for sentence in REFUSAL_SENTENCES)


def unproven_outcome(
    rule_id: str,
    subject: str,
    found: Sequence[RefusedNet],
    *,
    what: str,
    evidence: Sequence[str] = (),
) -> Outcome:
    """One rule's UNKNOWN about a subject whose net (or nets) is unproven.

    ``found`` is what :func:`unproven_nets` returned for the nets this judgement
    depends on, so the row names exactly the names that refused. ``what`` is the
    conclusion being withheld, phrased as the thing the net cannot establish
    ("whether a grounded capacitor sits on it"). The ``missing_fact`` is the
    reading's own sentence, so the four-state protocol and the tier note read the
    same way — and so this UNKNOWN is never mistaken for a rule that decided the
    net is clean.
    """
    return Outcome(
        rule_id=rule_id,
        state="UNKNOWN",
        subject=subject,
        message=unproven_message(subject, found, what=what),
        evidence=list(evidence),
        missing_fact=unproven_missing_fact(found),
    )

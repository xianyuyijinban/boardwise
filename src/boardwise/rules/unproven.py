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

**Which rules these are** is a *list*, not a search: :data:`NET_MEMBERSHIP_RULES`
holds the ids of every rule whose conclusion depends on which other parts sit on
a net. It is what the report's tier note counts ("N rules refuse"), and
``tests/test_checkup_cli.py`` guards it against drift in both directions — an id
in the list that is not a built-in rule, and a listed rule that stops refusing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..core.model import DesignModel
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
#:   ``conn-usb-cc-pulldown`` (a resistor), ``param-divider-output`` (a load);
#: * the pin's **company** — ``conn-nc-and-must-connect`` ("alone on this net" and
#:   "shares it with another pin" are the same reading, one netlist over);
#: * the net's **voltage**, which the domain inference takes from an LDO's output
#:   pin wherever it is — ``pwr-supply-on-known-domain``, ``pwr-domain-vs-range``,
#:   ``path-ldo-dropout``.
#:
#: The rules that are **not** here, and why: ``conn-duplicate-designators`` reads
#: names, ``conn-library-pin-consistency`` reads one part's pins against the
#: library symbol, and ``param-led-current`` / ``param-rc-cutoff`` /
#: ``param-value-mpn-match`` read one part's own values. None of them asks "what
#: else is on this net", so a welded netlist cannot move their verdicts.
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
    "path-ldo-dropout",
    "pwr-domain-vs-range",
    "pwr-supply-on-known-domain",
)


def unproven_nets(
    model: DesignModel, names: Iterable[str | None]
) -> list[tuple[str, tuple[str, ...]]]:
    """Every ``(net, pages)`` among ``names`` this model calls unproven.

    Empty means "all these nets are proven here" — the caller's normal path.
    ``pages`` may be ``()`` ("more than one page, ids unavailable in this
    reading"), which is a real answer and never a "no pages" one.
    """
    found: list[tuple[str, tuple[str, ...]]] = []
    for name in names:
        if name is None or not name:
            continue
        pages = model.unproven_pages(name)
        if pages is not None:
            found.append((name, tuple(pages)))
    return found


def _where(pages: Sequence[str]) -> str:
    """How a refusal names the pages a net was seen on (ids may be unknown)."""
    if not pages:
        return "more than one page of this reading (page ids unavailable)"
    return (
        f"{len(pages)} pages of this reading "
        f"({', '.join(page[:8] for page in pages)})"
    )


def _net_clause(found: Sequence[tuple[str, tuple[str, ...]]]) -> str:
    """``net 'VCC' was seen on 2 pages …`` — one net, or the several that refused."""
    if len(found) == 1:
        net, pages = found[0]
        return f"net {net!r} was seen on {_where(pages)}"
    return (
        "nets "
        + " and ".join(f"{net!r} ({_where(pages)})" for net, pages in found)
        + " were each seen on more than one page"
    )


def unproven_message(
    subject: str,
    found: Sequence[tuple[str, tuple[str, ...]]],
    *,
    what: str,
) -> str:
    """The refusal sentence, without a rule id — for callers that are not an Outcome row.

    :func:`boardwise.rules.facts.pin_ruling` is one: it judges a pin for both the
    rule and the repair, and returns its own :class:`PinRuling`, so it needs the
    same words without owning a row. One builder, so the rule's UNKNOWN and the
    four-state row say the same thing.
    """
    return (
        f"{subject}: {_net_clause(found)}, so {what} cannot be established — "
        "whether those pages are one board is not in this reading"
    )


def unproven_missing_fact(found: Sequence[tuple[str, tuple[str, ...]]]) -> str:
    """The fact the refusal is missing — the merge's own sentence, quoted."""
    return (
        f"a verified connection for {_net_clause(found)} — this tier cannot "
        f"attribute a page to a board: {UNPROVEN_BY_NAME}"
    )


def unproven_outcome(
    rule_id: str,
    subject: str,
    found: Sequence[tuple[str, tuple[str, ...]]],
    *,
    what: str,
    evidence: Sequence[str] = (),
) -> Outcome:
    """One rule's UNKNOWN about a subject whose net (or nets) is unproven.

    ``found`` is what :func:`unproven_nets` returned for the nets this judgement
    depends on, so the row names exactly the names that refused. ``what`` is the
    conclusion being withheld, phrased as the thing the net cannot establish
    ("whether a grounded capacitor sits on it"). The ``missing_fact`` is the
    merge's own sentence, so the four-state protocol and the tier note read the
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

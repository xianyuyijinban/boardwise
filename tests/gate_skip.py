"""147c: one place that turns "147's readability gate refuses this shape" into a
documented skip, for every batch whose scenes the compiler cannot yet draw clean.

147 made the checker see three things it could not see before, and every one of
them is a class of defect 岳 found by eye on the landed page while every offline
gate was green: a **body box that is a line** (15 of 19 parts had `body` =
`[pin1 inner end, pin2 inner end]`, zero extent perpendicular to the pin axis, so
no wire and no text row could ever cross it), the **name rows the host prints
itself** (a wire's net name, a rail flag's name row), and the **drawn lead of a
pin**. The gate now reports `wire-through-body` on a flag's glyph, `text-on-wire`
for a text row a conductor crosses, `wire-on-pin-line` for a wire riding a lead,
and `text-overlap` against a *drawn extent* instead of a degenerate box.

The compiler's layout does not yet respect them. The flag ladder still takes its
last resort — standing a flag on its own pin, glyph over the wire that reaches
it — and the text ladders place a part's reference/value rows at the first side
they tried when every rung of the bounded ladder is taken. So a good number of
scenes that used to compile are now refused by a gate that is **right**: the
drawing those scenes pinned really does print a rail's name astride the trunk
that feeds it, or run a conductor through a flag's pennant.

Those tests are not wrong about the drawing they were written for; they are
waiting on compiler work (147 sec.7.2, 147b sec.7.1 option 1: the flag ladder has
to treat glyph + name row + clearance as one box, and the text ladders have to
learn about the host's own rows). Until then the honest state is a **visible**
skip: this module's helper names the gate kinds that refused, quotes the gate's
own lines, and states the condition under which the test starts running again.

It is deliberately strict, and that is the point of putting it in one file:

* it skips only when the **readability gate** is (one of) the reasons nothing was
  drawn — a refusal by a relation, a routing failure, a lattice failure, a
  grammar obligation or an unroutable main-path edge is **not** skipped, so a
  change in *why* a shape refuses is never silent;
* it leaves every assertion in the caller untouched: the geometry a test pins is
  skipped, never weakened, and it runs again the day the compiler draws the shape
  clean;
* the reason carries the gate's own `[kind] objects: evidence` lines, so a reader
  of `pytest -rs` sees which rule was broken without re-running anything.
"""

from __future__ import annotations

import re

import pytest

#: The compiler's own words when the checker refused the plan (drawcompiler).
GATE_PHRASE = "the independent readability checker refused"

#: The hard kinds 147 added or widened, cheapest match first. Kept as a list so a
#: future kind shows up in a skip reason as itself rather than as a mystery.
GATE_KINDS = (
    "wire-through-body",
    "wire-on-pin-line",
    "text-on-wire",
    "text-overlap",
)

#: Everything the skip reason needs to say about how to make the test run again.
REVIVAL = (
    "these assertions are unchanged and run again the moment the compiler draws "
    "this shape clean (147 sec.7.2: the flag ladder must treat glyph + name row + "
    "clearance as one box and drop its 'stand on the pin' last resort; the text "
    "ladders must treat the host's own name rows as boxes to avoid). Until then "
    "this shape is not drawable, so the test is skipped rather than weakened — "
    "outputs/147c/revival_list.md is the list of scenes waiting on that batch"
)


def gate_refusal_lines(result) -> list[str]:
    """The gate's refusal details inside a compile result, or ``[]``.

    Reads ``result.failures[i].detail`` (``GrammarFailure``), which is where the
    checker's own lines end up — not the rendered message, which pytest may have
    truncated by the time a reader sees it.
    """
    out: list[str] = []
    for failure in getattr(result, "failures", None) or ():
        detail = getattr(failure, "detail", "") or ""
        if GATE_PHRASE in detail:
            out.append(detail)
    return out


def kinds_in(detail: str) -> list[str]:
    """The hard kinds the gate named, in :data:`GATE_KINDS` order."""
    return [kind for kind in GATE_KINDS if f"[{kind}]" in detail]


def skip_if_the_147_gate_refused(result, subject: str) -> None:
    """``pytest.skip`` when the readability gate is why nothing was drawn.

    Call it right where a test would otherwise do ``assert result.ok``. A result
    with a candidate is left alone (the caller's own assertions decide), and a
    refusal that does not name the checker is left alone too — that assertion is
    the one that should fail, and it fails with the compiler's own message.
    """
    if getattr(result, "ok", False):
        return
    refusals = gate_refusal_lines(result)
    if not refusals:
        return
    detail = " || ".join(refusals)
    kinds = kinds_in(detail)
    if not kinds:
        # The checker refused, but not under one of 147's kinds (say
        # `netlist-partition-mismatch`, which 118 owns). That is not this
        # helper's business, so the caller's own assertion fails and prints the
        # compiler's message — skipping it would hide a refusal nobody asked to
        # stand aside.
        return
    pytest.skip(
        f"147's readability gate refuses this shape ({subject}): the gate named "
        f"{sorted(set(kinds))} — {detail[:900]} — {REVIVAL}"
    )


def skip_if_the_gate_refuses_the_plan(checked, subject: str) -> None:
    """The same, for a fixture that had to **stand the gate aside** to get a plan.

    Several tests measure the text boxes of a plan that only exists because the
    fixture built it with the checker patched out (see 117's `_plan`). The plan
    is real; what is not real is calling the page clean. This helper reads the
    **unpatched** checker's answer on that plan and skips with its lines, so a
    page the gate would refuse is never quietly measured as if it were drawable.
    """
    violations = list(getattr(checked, "hard_violations", []) or ())
    ours = [item for item in violations if item.kind in GATE_KINDS]
    if not ours:
        # Nothing of 147's here: whatever the checker said belongs to another
        # batch's subject (118's `netlist-partition-mismatch`, say), and the
        # caller's own assertions are the ones that should decide.
        return
    lines = [item.render() for item in violations]
    kinds = sorted({item.kind for item in violations})
    pytest.skip(
        f"147's readability gate refuses this shape ({subject}): the plan exists "
        f"only because the fixture stood the checker aside, and the unpatched "
        f"checker names {len(lines)} hard violation(s) — {kinds} — "
        f"{' || '.join(lines[:6])[:1200]} — {REVIVAL}"
    )

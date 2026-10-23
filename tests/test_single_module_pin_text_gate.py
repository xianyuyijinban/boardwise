"""The single-module path's one tolerance clause, pinned as a pure function.

The merged tree's full suite measured eight reds on the outputs/-gated landing
pages (145a/175/178) — every one of them the same sentence: a `pin-text-press`
between a part's own value row and that same part's pin name, the symbol's own
artwork no placement lever can separate. The island page had a delivery policy
for exactly this kind (530F); the single-module path refused it outright,
because its policy docstring reasoned "this path has the escape ladder" — and
the ladder moves wire name rows, not a symbol's own artwork.

The fix is `drawcompiler.single_module_gate_violations`: the island policy's
pin-text-press clause, same cap, on this path. These tests pin the clause's
three edges — tolerate the measured class, refuse a class over its cap, refuse
a pair with no host-printed row — so the clause cannot quietly widen into a
general tolerance (which is what the policy's scoping paragraph exists to
prevent), nor quietly narrow back into a structural refusal.
"""

from __future__ import annotations

from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability as rb


def _pin_press(index: int) -> rb.HardViolation:
    """One same-part pin-text-press, shaped the way the checker builds them."""
    return rb.HardViolation(
        rb.KIND_PIN_TEXT_PRESSED,
        (f"texts[{index}]", f"parts[T1].pinName[{index}]"),
        "synthetic",
    )


def test_the_measured_class_is_tolerated():
    """Three same-part presses — the flyback landing page's own count — pass."""
    refusing, tolerated = dc.single_module_gate_violations(
        [_pin_press(i) for i in range(3)]
    )
    assert refusing == []
    assert len(tolerated) == 3


def test_a_class_over_its_cap_takes_every_line_with_it():
    """The cap bounds the class; it does not ration it (the island rule's own)."""
    over = [_pin_press(i) for i in range(4)]
    refusing, tolerated = dc.single_module_gate_violations(over)
    assert refusing == over
    assert tolerated == []


def test_a_pair_with_no_host_printed_row_refuses():
    """Clause 2 on this path is the island policy's own question.

    By the checker's construction a pin-text-press pair always carries a pin
    row (host-printed), so this case cannot arise from a real page — which is
    exactly why it is pinned: if the kind's construction ever changes, the
    clause keeps refusing what it cannot account for instead of inheriting a
    wider tolerance by accident.
    """
    synthetic = rb.HardViolation(
        rb.KIND_PIN_TEXT_PRESSED, ("texts[1]", "texts[2]"), "synthetic"
    )
    refusing, tolerated = dc.single_module_gate_violations([synthetic])
    assert refusing == [synthetic]
    assert tolerated == []


def test_every_other_kind_stays_hard_on_this_path():
    """The escape ladder answers text-on-wire and text-overlap here — the
    island policy's widening stops at the one kind no lever can answer."""
    foreign = rb.HardViolation(
        rb.KIND_TEXT_OVERLAP, ("texts[33]", "labels[4]"), "synthetic"
    )
    refusing, tolerated = dc.single_module_gate_violations([foreign, _pin_press(0)])
    assert refusing == [foreign]
    assert len(tolerated) == 1


def test_the_cap_is_the_island_policy_s_own():
    """One number, one place: the clause reads the island policy's entry rather
    than restating it, so the two paths cannot drift apart."""
    cap = dict(dc.ISLAND_GATE_TOLERATED_LIMITS)[rb.KIND_PIN_TEXT_PRESSED]
    refusing, _tolerated = dc.single_module_gate_violations(
        [_pin_press(i) for i in range(cap)]
    )
    assert refusing == []
    over, _tolerated2 = dc.single_module_gate_violations(
        [_pin_press(i) for i in range(cap + 1)]
    )
    assert len(over) == cap + 1

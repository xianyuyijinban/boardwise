"""Issue #46: the two membership-rename implementations must behave identically.

``core.compare.reconcile_names`` (calibration path) used to *merge* two clusters
when a rename landed on a name the candidate already carried, and
``engines.draw._reconcile_derived_names`` (draw path) *dropped* that net on the
floor. Both answers were silent, and they disagreed. The rule both now follow is
the same one sentence: a rename whose target name is already taken is abandoned
and recorded, and nothing is merged, nothing is overwritten.

086 made that one implementation instead of two: the decision now lives in
``core.compare.plan_membership_renames`` and both entry points are thin shells
over it, so the "same words in ``skipped``" below is a structural fact rather
than a coincidence held in place by a test. The *policies* still differ, on
purpose and as named parameters — ``respect_golden_names`` is ``True`` for draw
and ``False`` for calibration — so this file pins both: the shared decision
(§3) and the divergence it deliberately does not erase (§4).
"""

from __future__ import annotations

from boardwise.core.compare import plan_membership_renames, reconcile_names
from boardwise.core.model import DesignModel, Net
from boardwise.engines.draw import _reconcile_derived_names


def _model(*nets: tuple[str, list[tuple[str, str]]]) -> DesignModel:
    return DesignModel(
        nets={name: Net(name=name, pins=list(pins)) for name, pins in nets}
    )


def _nets_dict(*nets: tuple[str, list[tuple[str, str]]]) -> dict[str, Net]:
    """Just the ``.nets`` mapping — what ``plan_membership_renames`` takes."""
    return {name: Net(name=name, pins=list(pins)) for name, pins in nets}


def _nets(model: DesignModel) -> dict[str, set[tuple[str, str]]]:
    return {name: set(net.pins) for name, net in model.nets.items()}


def _both(golden: DesignModel, candidate: DesignModel):
    """Run one input through both entries and pin them to the same answers."""
    calibration_records: list[str] = []
    reconciled = reconcile_names(candidate, golden, skipped=calibration_records)
    drawn = _model(*[(n, list(net.pins)) for n, net in candidate.nets.items()])
    draw_records: list[str] = []
    renamed = _reconcile_derived_names(golden, drawn, skipped=draw_records)
    assert calibration_records == draw_records, (calibration_records, draw_records)
    assert _nets(reconciled) == _nets(drawn), (_nets(reconciled), _nets(drawn))
    return reconciled, drawn, renamed, calibration_records


def _occupancy_collision() -> tuple[DesignModel, DesignModel]:
    """A rename wants a name the candidate is already using for another cluster.

    Golden ``NET1`` is ``U1.1+U1.2``; the editor drew exactly that cluster and
    called it ``$1N5``, so the rename is right — but the candidate *also* has a
    net called ``NET1`` (``U3.1``, a cluster the golden source never named).
    Before #46 this merged (compare) or deleted (draw) one of the two.
    """
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]), ("NET9", [("U2", "1")]))
    candidate = _model(
        ("$1N5", [("U1", "1"), ("U1", "2")]),
        ("NET1", [("U3", "1")]),
    )
    return golden, candidate


def test_a_rename_onto_an_occupied_name_is_abandoned_by_both():
    golden, candidate = _occupancy_collision()
    reconciled, _drawn, renamed, records = _both(golden, candidate)

    assert renamed == 0
    assert records, records
    assert all("$1N5" in line and "NET1" in line for line in records), records
    # Neither net grew a member it never had, and neither went missing.
    assert _nets(reconciled) == {
        "$1N5": {("U1", "1"), ("U1", "2")},
        "NET1": {("U3", "1")},
    }


def test_the_draw_path_no_longer_drops_the_net_under_the_target_name():
    """The half of #46 that was data loss: `candidate.nets[new] = net` ate the net that was already there."""
    golden, candidate = _occupancy_collision()

    assert _reconcile_derived_names(golden, candidate) == 0
    assert _nets(candidate) == {
        "$1N5": {("U1", "1"), ("U1", "2")},
        "NET1": {("U3", "1")},
    }


def test_two_candidates_for_one_golden_name_are_skipped_identically():
    """The other collision: the first rename takes the name, the second gives up."""
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]))
    candidate = _model(
        ("$1N5", [("U1", "1"), ("U1", "2")]),
        ("$1N9", [("U1", "1"), ("U1", "2")]),
    )
    reconciled, _drawn, renamed, records = _both(golden, candidate)

    assert renamed == 1
    assert records == [
        "rename '$1N9' -> 'NET1' skipped: '$1N5' was already renamed to 'NET1'"
    ]
    assert _nets(reconciled) == {
        "NET1": {("U1", "1"), ("U1", "2")},
        "$1N9": {("U1", "1"), ("U1", "2")},
    }


def test_an_uncontested_rename_is_unchanged():
    """The ordinary case must keep working, and keep its silence."""
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]))
    candidate = _model(("$1N5", [("U1", "1"), ("U1", "2")]))

    reconciled, _drawn, renamed, records = _both(golden, candidate)

    assert renamed == 1
    assert records == []
    assert _nets(reconciled) == {"NET1": {("U1", "1"), ("U1", "2")}}


def test_a_cluster_the_golden_never_named_is_left_alone_by_both():
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]))
    candidate = _model(
        ("NET1", [("U1", "1"), ("U1", "2")]),
        ("$1N9", [("U9", "3"), ("U9", "4")]),
    )
    reconciled, _drawn, renamed, records = _both(golden, candidate)

    assert renamed == 0
    assert records == []
    assert _nets(reconciled) == {
        "NET1": {("U1", "1"), ("U1", "2")},
        "$1N9": {("U9", "3"), ("U9", "4")},
    }


def test_compare_permutes_a_cycle_of_renames():
    """A candidate net whose name is *also* a golden name is not necessarily on
    that golden net: the CH340 geometry fixture has four of them, cycled
    (candidate NET5 is golden NET3's cluster, NET3 is NET6's, NET6 is NET2's,
    NET2 is NET5's). No name is free, and every rename still has to happen —
    which is why the collision rule above only refuses a target whose occupant
    is *staying*. `_reconcile_derived_names` leaves these four alone (it treats
    a golden name as the right one already). Since 086 that is the named
    ``respect_golden_names`` parameter rather than a forked implementation:
    one decision, two policies, and this one is pinned on the compare side
    only.
    """
    golden = _model(
        ("NET2", [("U1", "8"), ("C25", "2")]),
        ("NET3", [("U1", "7"), ("C3", "1")]),
        ("NET5", [("R24", "1"), ("USB1", "10")]),
        ("NET6", [("R27", "1"), ("USB1", "4")]),
    )
    candidate = _model(
        ("NET2", [("R24", "1"), ("USB1", "10")]),
        ("NET3", [("R27", "1"), ("USB1", "4")]),
        ("NET5", [("U1", "7"), ("C3", "1")]),
        ("NET6", [("U1", "8"), ("C25", "2")]),
    )
    records: list[str] = []
    reconciled = reconcile_names(candidate, golden, skipped=records)

    assert records == []
    assert _nets(reconciled) == {
        "NET2": {("U1", "8"), ("C25", "2")},
        "NET3": {("U1", "7"), ("C3", "1")},
        "NET5": {("R24", "1"), ("USB1", "10")},
        "NET6": {("R27", "1"), ("USB1", "4")},
    }, _nets(reconciled)


def test_skipped_is_optional_for_every_existing_caller():
    """Keyword-only and defaulted: `reconcile_names(c, g)` / `_reconcile_derived_names(g, c)` still work."""
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]))
    candidate = _model(("$1N5", [("U1", "1"), ("U1", "2")]))

    assert _nets(reconcile_names(candidate, golden)) == {
        "NET1": {("U1", "1"), ("U1", "2")}
    }
    assert _reconcile_derived_names(golden, candidate) == 1


# --------------------------------------------------------------------------
# 3. `plan_membership_renames`：那个唯一的决策落点
# --------------------------------------------------------------------------


def test_the_plan_renames_on_membership_alone():
    """The whole contract in one line: identical member set, golden name."""
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]), ("NET9", [("U2", "1")]))
    candidate = _nets_dict(
        ("$1N5", [("U1", "1"), ("U1", "2")]), ("$1N9", [("U9", "3")]),
    )

    assert plan_membership_renames(golden.nets, candidate) == {"$1N5": "NET1"}


def test_the_plan_translates_addressing_before_comparing_members():
    """`translate` is the draw path's pin_maps, in one hop.

    A drifted part's placed pins carry pad-name numbers, so the same two-member
    cluster reads different on each side until the addressing is put back.
    """
    golden = _nets_dict(("NET6", [("U1", "1"), ("U2", "2")]))
    placed = _nets_dict(
        ("$16N3", [("U1", "A5"), ("U2", "B7")]),
        ("NET9", [("U9", "1")]),
    )
    translate = {("U1", "A5"): ("U1", "1"), ("U2", "B7"): ("U2", "2")}

    assert plan_membership_renames(golden, placed, translate=translate) == {
        "$16N3": "NET6"
    }
    # Without it the same pair is a different set of pins, so nothing renames —
    # the rename silently not firing is exactly the 2026-09-15 NET6/$16N3 bug.
    assert plan_membership_renames(golden, placed) == {}


def test_respect_golden_names_is_the_named_divergence_and_both_states_are_pinned():
    """One decision, two policies — the knob is a parameter, not a fork.

    A candidate net that is *also* a golden name but sits on a *different*
    golden cluster is the CH340 cycle. Draw treats the name as already right
    (the drawn board carries our names explicitly) and leaves it; calibration
    asks "same connectivity?" and permutes it. Both answers are correct for
    their caller, so the flag is what separates them.
    """
    golden = _model(("NET2", [("U1", "1")]), ("NET3", [("U1", "2")]))
    swapped = _nets_dict(
        ("NET2", [("U1", "2")]),   # golden NET2's name, on NET3's cluster
        ("NET3", [("U1", "1")]),   # and the other way round
    )

    assert plan_membership_renames(golden.nets, swapped, respect_golden_names=True) == {}
    assert plan_membership_renames(golden.nets, swapped, respect_golden_names=False) == {
        "NET2": "NET3", "NET3": "NET2",
    }
    # The default is the calibration policy, so a caller that says nothing
    # about it gets the "compare by membership" reading.
    assert plan_membership_renames(golden.nets, swapped) == {
        "NET2": "NET3", "NET3": "NET2",
    }


def test_the_plan_refuses_two_candidates_claiming_one_name():
    """Collision shape 1: the first rename takes the golden name, the second loses."""
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]))
    candidate = _nets_dict(
        ("$1N5", [("U1", "1"), ("U1", "2")]),
        ("$1N9", [("U1", "1"), ("U1", "2")]),
    )
    records: list[str] = []

    assert plan_membership_renames(golden.nets, candidate, skipped=records) == {
        "$1N5": "NET1"
    }
    assert records == [
        "rename '$1N9' -> 'NET1' skipped: '$1N5' was already renamed to 'NET1'"
    ]


def test_the_plan_refuses_a_rename_onto_a_name_the_candidate_keeps():
    """Collision shape 2: the target is occupied by a net that is *staying*."""
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]), ("NET9", [("U2", "1")]))
    candidate = _nets_dict(
        ("$1N5", [("U1", "1"), ("U1", "2")]),
        ("NET1", [("U3", "1")]),
    )
    records: list[str] = []

    assert plan_membership_renames(golden.nets, candidate, skipped=records) == {}
    assert records == [
        "rename '$1N5' -> 'NET1' skipped: the candidate already carries a net "
        "called 'NET1'"
    ]


def test_the_plan_permutes_a_cycle_rather_than_refusing_it():
    """A net that is being renamed *away* does not block the one taking its name."""
    golden = _nets_dict(("A", [("U1", "1")]), ("B", [("U1", "2")]))
    candidate = _nets_dict(("A", [("U1", "2")]), ("B", [("U1", "1")]))
    records: list[str] = []

    assert plan_membership_renames(golden, candidate, skipped=records) == {
        "A": "B", "B": "A",
    }
    assert records == []


def test_skipped_is_optional_on_the_plan_too():
    golden = _model(("NET1", [("U1", "1"), ("U1", "2")]))
    candidate = _nets_dict(
        ("$1N5", [("U1", "1"), ("U1", "2")]),
        ("$1N9", [("U1", "1"), ("U1", "2")]),
    )

    assert plan_membership_renames(golden.nets, candidate) == {"$1N5": "NET1"}


# --------------------------------------------------------------------------
# 4. 一处决策：两个壳的 `skipped` 逐字同源
# --------------------------------------------------------------------------


def test_both_shells_get_word_for_word_the_same_skipped_messages():
    """The convergence itself, asserted rather than assumed.

    One input, the two entry points, a fresh model each — the two ``skipped``
    lists must be equal line for line, because the wording now has exactly one
    home in ``plan_membership_renames``. The input trips **both** collision
    shapes so the lists are long enough to be a real witness: ``$1N9`` loses to
    ``$1N5`` for ``NET1``, and ``$1N3`` is refused because the candidate keeps a
    net called ``NET4``.
    """
    golden = _model(
        ("NET1", [("U1", "1"), ("U1", "2")]),
        ("NET4", [("U2", "1"), ("U2", "2")]),
    )
    shape = (
        ("$1N5", [("U1", "1"), ("U1", "2")]),
        ("$1N9", [("U1", "1"), ("U1", "2")]),
        ("$1N3", [("U2", "1"), ("U2", "2")]),
        ("NET4", [("U9", "1")]),
    )
    calibration_records: list[str] = []
    draw_records: list[str] = []

    reconciled = reconcile_names(_model(*shape), golden, skipped=calibration_records)
    renamed = _reconcile_derived_names(golden, _model(*shape), skipped=draw_records)

    assert len(calibration_records) == 2, calibration_records
    assert draw_records == calibration_records, (draw_records, calibration_records)
    assert calibration_records == [
        "rename '$1N9' -> 'NET1' skipped: '$1N5' was already renamed to 'NET1'",
        "rename '$1N3' -> 'NET4' skipped: the candidate already carries a net "
        "called 'NET4'",
    ], calibration_records
    # One rename survives on both sides; only the application differs.
    assert renamed == 1
    assert _nets(reconciled)["NET1"] == {("U1", "1"), ("U1", "2")}


def test_the_two_shells_agree_on_the_plan_they_were_given():
    """The shells are thin: same nets in, same plan out, only the policy differs."""
    golden = _model(
        ("NET2", [("U1", "1")]), ("NET3", [("U1", "2")]), ("NET7", [("U2", "1")]),
    )
    candidate = _model(
        ("NET2", [("U1", "2")]), ("NET3", [("U1", "1")]), ("$1N9", [("U2", "1")]),
    )

    calibration = plan_membership_renames(
        golden.nets, candidate.nets, respect_golden_names=False,
    )
    draw = plan_membership_renames(
        golden.nets, candidate.nets, respect_golden_names=True,
    )
    # draw skips the two names that already exist on the golden side; calibration
    # permutes them and still renames the genuinely unnamed cluster.
    assert draw == {"$1N9": "NET7"}
    assert calibration == {"NET2": "NET3", "NET3": "NET2", "$1N9": "NET7"}
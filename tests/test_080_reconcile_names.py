"""Issue #46: the two membership-rename implementations must behave identically.

``core.compare.reconcile_names`` (calibration path) used to *merge* two clusters
when a rename landed on a name the candidate already carried, and
``engines.draw._reconcile_derived_names`` (draw path) *dropped* that net on the
floor. Both answers were silent, and they disagreed. The rule both now follow is
the same one sentence: a rename whose target name is already taken is abandoned
and recorded, and nothing is merged, nothing is overwritten.

Merging the two implementations into one is a later batch; until then these tests
hold the two honest — same input, same nets out, same words in ``skipped``.
"""

from __future__ import annotations

from boardwise.core.compare import reconcile_names
from boardwise.core.model import DesignModel, Net
from boardwise.engines.draw import _reconcile_derived_names


def _model(*nets: tuple[str, list[tuple[str, str]]]) -> DesignModel:
    return DesignModel(
        nets={name: Net(name=name, pins=list(pins)) for name, pins in nets}
    )


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
    a golden name as the right one already); that divergence is 006's and waits
    for the merge batch, so this one is pinned on the compare side only.
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
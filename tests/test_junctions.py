"""T-junction splitting: every touching run must END at the shared point.

Measured 2026-09-15 on the golden board's U1.16/VCC net, then with five probes
on a live page: `sch_PrimitiveWire.create` **merges polylines that share an
endpoint into one primitive** and repeats the junction point. Handing over a
run whose *endpoint* lands on another run's interior let the merged polyline
put a pin tip in its middle — and the netlist then reported that pin
unconnected. The same geometry re-sent as segments that all end at the junction
connected it (verified on the page: U1.16 joined VCC).
"""

from __future__ import annotations

from boardwise.engines.generate import WireStep
from boardwise.engines.replay import split_at_junctions


def test_a_branch_landing_mid_run_splits_the_run():
    # the U1.16 shape: pin -> T -> on, plus a stub ending on T
    wires = [
        WireStep(net="VCC", points=[(280.0, 716.0), (290.0, 716.0), (294.0, 716.0)]),
        WireStep(net="VCC", points=[(290.0, 724.0), (290.0, 716.0)]),
    ]
    split, count = split_at_junctions(wires)

    assert count == 1, "the run carrying the junction is the one that splits"
    assert len(split) == 3
    # the segment touching the pin now ends at the junction, so the pin is an
    # endpoint of its own piece rather than a vertex of a longer polyline
    assert split[0].points == [(280.0, 716.0), (290.0, 716.0)]
    assert split[1].points == [(290.0, 716.0), (294.0, 716.0)]
    assert split[2].points == [(290.0, 724.0), (290.0, 716.0)]
    for wire in split:
        assert len(wire.points) >= 2, "no degenerate pieces"


def test_an_endpoint_inside_a_segment_becomes_a_vertex_first():
    # nothing shares a *vertex*, but the stub ends in the middle of the run
    wires = [
        WireStep(net="", points=[(0.0, 0.0), (20.0, 0.0)]),
        WireStep(net="", points=[(10.0, 0.0), (10.0, 10.0)]),
    ]
    split, count = split_at_junctions(wires)

    assert count == 1, "the run is split at the inserted vertex"
    assert [w.points for w in split] == [
        [(0.0, 0.0), (10.0, 0.0)],
        [(10.0, 0.0), (20.0, 0.0)],
        [(10.0, 0.0), (10.0, 10.0)],
    ]


def test_wires_that_do_not_touch_are_left_alone():
    wires = [
        WireStep(net="A", points=[(0.0, 0.0), (10.0, 0.0)]),
        WireStep(net="B", points=[(0.0, 50.0), (10.0, 50.0)]),
    ]
    split, count = split_at_junctions(wires)

    assert count == 0
    assert [w.points for w in split] == [w.points for w in wires]


def test_a_shared_endpoint_is_already_a_junction_and_is_not_split():
    # two runs meeting end-to-end need no split: both already end there
    wires = [
        WireStep(net="", points=[(0.0, 0.0), (10.0, 0.0)]),
        WireStep(net="", points=[(10.0, 0.0), (10.0, 10.0)]),
    ]
    split, count = split_at_junctions(wires)

    assert count == 0
    assert len(split) == 2

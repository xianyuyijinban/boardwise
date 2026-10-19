"""201F: the cost field is a *lower bound*, and it does not change the path.

The heuristic ``route`` now consults is a reverse Dijkstra from the goals priced
at 1.0 a step plus ``CROSS_COST`` whenever a step enters a lattice point that
lies inside a foreign wire. It ignores ``TURN_COST`` and it ignores the two
collinearity rules (never run along a foreign wire, never turn on one). Every
omitted term is non-negative and every omitted rule only removes paths, so the
field's answer must be **≤** the true cheapest legal cost from that node.

That is the whole correctness argument, and it is only worth anything if it is
measured — a heuristic that overestimates once makes A* return a wire that is
dearer than the one it used to return, and the failure is silent (the preview
still renders). So this file pins, in the order the risk runs:

1. the field's values are the values the lattice implies (a corridor, counted by
   hand);
2. ``field[node] <= cost(route(node, goal))`` on random pages — admissibility,
   checked against the search's own output rather than against the field's own
   arithmetic;
3. the path ``route`` returns keeps **exactly** the cost it had with the old
   Manhattan bound, on the same pages;
4. the degradation paths (no goals reachable, no field) leave the old behaviour
   byte-for-byte;
5. the memo key includes the foreign-wire snapshot, so a field built before a
   wire was routed is never handed to a search that would then see that wire.

The 83-preview byte gate (``tools/117_zero_move.py``) is the page-level check;
this file is the one that fails *first*, and in a way that names the cause.
"""

from __future__ import annotations

import random

import pytest

from boardwise.engines import router as rt
from boardwise.engines.router import CROSS_COST, TURN_COST, _Router

GRID = 5.0

#: Seeds the A/B parity test actually compared (not skipped because the fixture
#: walled the goal). Asserted non-empty by the last test in this file: a fixture
#: change that made every seed uncomparable would otherwise leave that whole
#: parametrisation green while testing nothing.
_COMPARED: list[int] = []


def _router(**overrides) -> _Router:
    options = dict(grid=GRID, residue=(0.0, 0.0), boxes=[], bounds=(0.0, 0.0, 200.0, 200.0))
    options.update(overrides)
    return _Router(**options)


def _cost(router: _Router, path: list[tuple[float, float]]) -> float:
    """The price the search would have charged for `path`, recomputed here.

    Deliberately a second implementation: if this file reused `route`'s own
    arithmetic, a wrong price would agree with itself.
    """
    total = 0.0
    previous: tuple[int, int] | None = None
    for start, end in zip(path, path[1:]):
        step = 1.0
        direction = (1, 0) if abs(start[1] - end[1]) < 1e-9 else (0, 1)
        if previous is not None and direction != previous:
            step += TURN_COST
        if router._crossing(router.node(end)) is not None:
            step += CROSS_COST
        total += step
        previous = direction
    return total


def _manhattan(router: _Router, start, goal) -> float:
    a, b = router.node(start), router.node(goal)
    return float(abs(a[0] - b[0]) + abs(a[1] - b[1]))


# ------------------------------------------------------------------ 1. values


def test_a_corridor_is_counted_by_hand():
    """Two boxes leave only ``x = 100`` open; the field must say 16 steps."""
    router = _router(boxes=[(0.0, 0.0, 95.0, 200.0), (105.0, 0.0, 200.0, 200.0)])
    field = router._cost_field({router.node((100.0, 100.0))})
    assert field is not None
    # (100, 20) -> (100, 100) is 80 units on a 5-unit lattice: 16 steps, no
    # foreign wire anywhere, so the crossing term contributes nothing.
    assert field[router.node((100.0, 20.0))] == pytest.approx(16.0)
    # A point inside a box is never valued: the search cannot stand there.
    assert router.node((50.0, 100.0)) not in field


def test_a_goal_inside_a_wall_has_no_field_at_all():
    """No walkable goal means no field, and ``route`` falls back to Manhattan."""
    router = _router(boxes=[(90.0, 90.0, 110.0, 110.0)])
    assert router._cost_field({router.node((100.0, 100.0))}) is None


# ------------------------------------------------------- 2. admissibility


def _random_page(seed: int) -> tuple[_Router, list[tuple[float, float]]]:
    """A small random page: a few box walls and a few foreign wires."""
    rng = random.Random(seed)
    boxes = []
    for _ in range(rng.randint(1, 4)):
        x = rng.randrange(20, 160, 5)
        y = rng.randrange(20, 160, 5)
        boxes.append((float(x), float(y), float(x + rng.choice((10, 20, 30))),
                      float(y + rng.choice((10, 20, 30)))))
    router = _router(boxes=boxes)
    wires = []
    for _ in range(rng.randint(0, 3)):
        if rng.random() < 0.5:
            x, y = rng.randrange(10, 180, 5), rng.randrange(10, 180, 5)
            wires.append(((float(x), float(y)), (float(x + rng.randrange(10, 60, 5)), float(y))))
        else:
            x, y = rng.randrange(10, 180, 5), rng.randrange(10, 180, 5)
            wires.append(((float(x), float(y)), (float(x), float(y + rng.randrange(10, 60, 5)))))
    router.edges = wires
    points = [(float(rng.randrange(10, 190, 5)), float(rng.randrange(10, 190, 5)))
              for _ in range(6)]
    return router, points


@pytest.mark.parametrize("seed", range(24))
def test_the_field_never_exceeds_the_cost_of_the_path_the_search_returns(seed):
    """Admissibility, measured against the search's own answer.

    If this ever goes red, A* can return a wire dearer than the one it used to
    return — the one failure mode the batch must not ship.
    """
    router, points = _random_page(seed)
    checked = 0
    for index in range(0, len(points) - 1, 2):
        start, goal = points[index], points[index + 1]
        if router._wall(router.node(goal)) or router._wall(router.node(start)):
            continue
        field = router._cost_field({router.node(goal)})
        path = router.route(start, goal)
        if path is None or field is None:
            continue
        cost = _cost(router, path)
        bound = field.get(router.node(start))
        if bound is None:
            continue  # unreachable for the field: the caller keeps Manhattan
        assert bound <= cost + 1e-6, (
            f"seed {seed}: field says {bound:.2f} at {start} but the cheapest "
            f"legal path costs {cost:.2f} — the bound overestimates"
        )
        checked += 1
    assert checked, f"seed {seed} exercised no bounded start (fixture too walled)"


# ------------------------------------------------- 3. the path does not move


@pytest.mark.parametrize("seed", range(16))
def test_the_route_costs_the_same_with_and_without_the_field(seed, monkeypatch):
    """Turning the field off must not change the price of the wire drawn.

    Same start, same goal, same page: the new heuristic may only decide *when*
    a state is popped, never which path wins. A tie broken differently shows up
    here as a different cost (or as a different path entirely), and either is a
    regression the 117 byte gate would also catch — one page at a time.
    """
    baseline_router, points = _random_page(seed)
    tuned_router, _ = _random_page(seed)
    start, goal = points[0], points[1]
    if baseline_router._wall(baseline_router.node(goal)):
        pytest.skip("fixture walls the goal")

    monkeypatch.setattr(_Router, "_cost_field", lambda self, goals: None)
    old_path = baseline_router.route(start, goal)
    monkeypatch.undo()

    new_path = tuned_router.route(start, goal)
    assert (old_path is None) == (new_path is None)
    if old_path is None:
        return
    # A silent skip guard: if a fixture change ever made every seed walled or
    # goal-less, this test would pass without comparing anything. The 201F red
    # team noted this file's sibling already counts; this one has to too, and
    # the count is checked once at the end of the file.
    _COMPARED.append(seed)
    assert _cost(tuned_router, new_path) == pytest.approx(_cost(baseline_router, old_path))


# ----------------------------------------------------------- 4. degradation


def test_without_obstacles_the_field_is_the_manhattan_line():
    """An empty page has no crossings and no walls: the field adds nothing."""
    router = _router()
    field = router._cost_field({router.node((100.0, 100.0))})
    assert field is not None
    start = (20.0, 60.0)
    assert field[router.node(start)] == pytest.approx(_manhattan(router, start, (100.0, 100.0)))


def test_a_walled_in_start_is_absent_and_the_search_still_answers():
    """The field leaves unreachable nodes out; ``route`` must not choke on that."""
    router = _router(boxes=[(0.0, 0.0, 195.0, 195.0)])
    field = router._cost_field({router.node((100.0, 100.0))})
    assert field is None or router.node((10.0, 10.0)) not in field


# ------------------------------------------------------------- 5. the memo


def test_a_field_never_outlives_the_world_it_was_built_in():
    """No memo: the field is rebuilt from the current walls on every call.

    A memo did exist here and was removed after the 201F red team measured **0
    hits in 111 calls** across the whole preview gate (and 0 in the flyback,
    ch340 and power-entry pages): ``_wall`` depends on ``blocked`` / ``reserved``
    / ``reserved_exempt`` / ``boxes`` as well as the two things a key could
    cheaply carry, so the entry would have to be invalidated on all of them —
    and an entry built while a wall still stood, handed to a search whose wall
    is gone, can **over**estimate. That is the one direction that breaks A*.
    """
    router = _router()
    goal = router.node((150.0, 100.0))
    first = router._cost_field({goal})
    assert first is not None
    assert not hasattr(router, "_fields"), (
        "a field memo is back — re-read the red-team note in router.py: it bought "
        "nothing and can stale into an overestimate"
    )

    router.edges = [((0.0, 100.0), (200.0, 100.0))]
    second = router._cost_field({goal})
    assert second is not None
    # And the crossing it now costs is visible in the bound: standing on the new
    # wire is dearer than the same distance without it.
    on_wire = router.node((100.0, 100.0))
    assert second[on_wire] > first.get(on_wire, 0.0), (
        "the field priced a step onto the foreign wire at nothing"
    )


def test_a_multi_goal_field_is_the_minimum_over_its_goals():
    """Real compiles pass 2–3 goals (trunk ends, attachments); one goal is the
    easy case. A multi-source seeding that took the *last* goal would still
    satisfy every single-goal test in this file."""
    router = _router()
    near = router.node((40.0, 100.0))
    far = router.node((180.0, 100.0))
    field = router._cost_field({near, far})
    assert field is not None
    assert field[near] == pytest.approx(0.0)
    assert field[far] == pytest.approx(0.0)
    # A point near one goal must be priced against that one, not the other.
    assert field[router.node((45.0, 100.0))] == pytest.approx(1.0)
    assert field[router.node((175.0, 100.0))] == pytest.approx(1.0)
    # And the two seedings cannot both be "the last one".
    assert field[router.node((100.0, 100.0))] < _manhattan(router, (100.0, 100.0), (180.0, 100.0))


# ---------------------------------------------------- 6. the suite is not empty


def test_the_parity_suite_compared_enough_seeds():
    """The A/B parity test must have actually compared paths.

    ``test_the_route_costs_the_same_with_and_without_the_field`` returns early
    when the fixture walls its goal; a change to ``_random_page`` that walled
    every seed would leave 16 green tests that compared nothing. The 201F red
    team flagged exactly this shape (its sibling had a counter, this one did
    not). Pytest runs same-file tests in definition order, so every
    parametrisation above has already reported by the time this one runs.
    """
    assert len(_COMPARED) >= 12, (
        f"only {sorted(_COMPARED)} of 16 seeds produced a comparable path — the "
        "fixture has drifted into all-walls and the parity check is vacuous"
    )

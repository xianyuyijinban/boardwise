"""143a: the compiler/spec holes 143 dug up in `drawcompiler.py` and
`core/presentationspec.py`.

One test per finding, each asserting the *behaviour the contract promises*
rather than a particular arrangement:

* 洞1 — a lock's `rotation` is applied to the pose the part is drawn in, not only
  checked (`_locked_pose`), and a lock the drawing cannot keep is reported as
  `presentation-poor` naming the lock instead of "a compiler-side geometry
  problem";
* 洞2 — a non-finite lock coordinate is refused at the document boundary with
  `PresentationSpecError` (the CLI's exit 5), never as a `round(NaN)` traceback;
* 洞3 — a hard readability violation is归口 by its own `kind`: a pin the symbol
  does not carry is `facts-missing`, a broken lock is `presentation-poor`;
* 洞4 — the lattice refusal names the symbols and never blames locks the
  measurement cannot see;
* 洞5 — a rotation the symbol declares **mirrored only** is not refused as
  "the symbol does not allow it";
* F1 — a flag the library lacks becomes a wire, never a net with zero
  conductors, and the degradation is marked for the change plan;
* F4 — `horizontal-tap`/`vertical-tap` are measured, and an unknown kind is not
  silently satisfied.
"""

from __future__ import annotations

import math

import pytest

import test_053b_drawcompiler as T
from boardwise.core.presentationspec import PresentationSpec, PresentationSpecError
from boardwise.core.symbolprofile import SymbolPin, SymbolPose, SymbolProfile
from boardwise.engines import drawcompiler as dc

LOCK = dc.LOCK_PREFIX


def _lock(part_id: str, *, rotation: float = 0.0, x: float = 0.0, y: float = 0.0):
    return {"partId": part_id, "x": x, "y": y, "rotation": rotation}


def _failures(result: dc.CompileResult) -> str:
    return "\n".join(
        f"[{item.category}] {item.subject}: {item.detail}\n   {item.action}"
        for item in result.failures
    )


# ---------------------------------------------------------------- 洞 1


def test_143a_h1_a_lock_the_drawing_cannot_keep_is_reported_as_the_lock_conflict():
    """053 sec.5 scenario 12: "报告冲突+可选动作，不静默忽略锁定".

    R0402 declares rotation 90, so `_lock_pose_failures` is silent — but a
    vertical chain cannot be drawn with a horizontal resistor, so the pose the
    lock asks for breaks `same-column(R1, R2)`. Before the fix the compiler drew
    `accepted[0]` (rotation 0), refused that drawing for violating the lock, and
    reported the input as "a compiler-side geometry problem, not a spec
    problem" — while the lock was the whole reason. The pose is now taken from
    the lock and the *relation* is what names the conflict.
    """
    circuit = T.divider_circuit()
    presentation = T.divider_presentation(
        userLocks=[_lock("R1", rotation=90.0, y=500.0)]
    )
    result = dc.compile(circuit, presentation, T.library())

    assert result.candidates == []
    assert result.categories() == ["presentation-poor"], _failures(result)
    failure = result.failures[0]
    assert failure.subject == "R1"
    assert f"{LOCK}[R1]" in failure.detail
    assert "the relation" in failure.detail
    # The two sentences the defect was: the compiler's own action denied that any
    # spec input was involved, and the plan's JSON called the whole input
    # `layout-unsat`.
    assert "compiler-side geometry problem" not in failure.action
    assert "layout-unsat" not in result.categories()


def test_143a_h1_the_pose_chooser_reads_the_lock_not_the_ladder_index():
    """`_locked_pose`: the lock's rotation picks the pose, whatever its index.

    The old line was `accepted[min(variant.pose_index, len-1)]` — a single global
    index with the lock's rotation validated and then never read, so a rotation
    sitting past index 1 of the accepted set could not be drawn at any rung (the
    real flyback's `C6`, whose 90 is index 2 of `['0', '0+m', '90', '90+m']`).
    """
    ctx = _context(
        T.divider_circuit(),
        T.divider_presentation(userLocks=[_lock("R1", rotation=180.0)]),
        T.library(),
    )
    accepted = [SymbolPose(0, False), SymbolPose(90, False), SymbolPose(180, False)]

    chosen = dc._locked_pose(ctx, "R1", accepted)
    assert chosen == SymbolPose(180, False)

    # A rotation the accepted set does not carry at all is still obeyed: the
    # symbol's own declared pose of that rotation is used, and the relation it
    # then breaks is what gets reported (the test above).
    only_zero = [SymbolPose(0, False)]
    assert dc._locked_pose(ctx, "R1", only_zero) == SymbolPose(180, False)

    # A lock names a rotation and not a mirror: the unmirrored pose is preferred,
    # and the mirrored one of that rotation is accepted when it is the only one.
    mirrored_ctx = _context(
        T.divider_circuit(),
        T.divider_presentation(userLocks=[_lock("R1", rotation=90.0)]),
        T.library(),
    )
    assert dc._locked_pose(
        mirrored_ctx, "R1", [SymbolPose(90, True), SymbolPose(90, False)]
    ) == SymbolPose(90, False)
    assert dc._locked_pose(
        mirrored_ctx, "R1", [SymbolPose(90, True)]
    ) == SymbolPose(90, True)

    # No lock, no opinion: the ladder keeps choosing.
    plain = _context(
        T.divider_circuit(), T.divider_presentation(), T.library()
    )
    assert dc._locked_pose(plain, "R1", accepted) is None


def _context(circuit, presentation, book) -> dc._Context:
    """The compiler's own stage-2 context, for the placement-level tests."""
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book, dc.CompileBudget())
    assert prepared.failures == [], [item.detail for item in prepared.failures]
    assert prepared.context is not None
    return prepared.context


# ---------------------------------------------------------------- 洞 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_143a_h2_a_non_finite_lock_coordinate_is_refused_at_the_document(value):
    """`json.loads` reads `NaN`/`Infinity` and `json.dumps` writes them back.

    Such a value reached `_place`'s displacement arithmetic and the final lattice
    snap raised `round(NaN)` out of the compiler — a traceback and exit 1 where
    the contract is "Input problems never raise" and the CLI's exit 5.
    """
    payload = {
        "grammarRef": "voltage-divider",
        "userLocks": [{"partId": "R1", "x": value, "y": 0.0, "rotation": 0}],
    }
    with pytest.raises(PresentationSpecError) as caught:
        PresentationSpec.from_dict(payload)
    message = str(caught.value)
    assert "userLocks[0].x" in message
    assert "not a place" in message


def test_143a_h2_a_finite_lock_coordinate_is_still_accepted():
    payload = {
        "grammarRef": "voltage-divider",
        "userLocks": [{"partId": "R1", "x": 2.5, "y": -10.0, "rotation": 90}],
    }
    spec = PresentationSpec.from_dict(payload)
    assert spec.user_locks[0].x == 2.5


# ---------------------------------------------------------------- 洞 3


def test_143a_h3_a_pin_the_symbol_does_not_carry_is_facts_missing():
    """The gate's refusal is归口 by the violation's own kind.

    `circuitSpec.nets[VIN]` names `R1.3` and `R0402` has no pin 3: the checker's
    line says so, and the compiler's action used to say "not a spec problem —
    change the region, the ladder or the symbol set", which cannot change the
    answer. The category is now `facts-missing` and the action names the repair.
    """
    circuit = T.circuit(
        [T.part("R1", "R0402", "10k"), T.part("R2", "R0402", "10k")],
        [
            T.net("VIN", "power", ["R1.3"]),
            T.net("TAP", "signal", ["R1.2", "R2.1"]),
            T.net("GND", "gnd", ["R2.2"]),
        ],
    )
    result = dc.compile(circuit, T.divider_presentation(), T.library())

    assert result.candidates == []
    assert result.categories() == ["facts-missing"], _failures(result)
    failure = result.failures[0]
    assert "R1.3" in failure.subject
    assert "compiler-side geometry problem" not in failure.action
    assert "CircuitSpec" in failure.action


# ---------------------------------------------------------------- 洞 4


def test_143a_h4_the_lattice_refusal_names_the_symbols_not_a_missing_lock():
    """The measured points are the symbols' own tips; no lock enters.

    `_lattice_residue` is handed each part's pin tips with the origin at (0, 0)
    and runs before any lock is applied, so "the locked positions put tips on
    different residues" blamed an object the measurement never read — 143's
    witness has `userLocks: []`. Both sentences now state what was measured.
    """
    book = T.library()
    book["R-ODD"] = SymbolProfile(
        symbol_ref="R-ODD", title="pins off the 5-unit lattice",
        body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 47.0), name="1", direction="up"),
            SymbolPin(number="2", tip=(0.0, -47.0), name="2", direction="down"),
        ],
    )
    presentation = T.divider_presentation()
    assert presentation.user_locks == []
    result = dc.compile(
        T.divider_circuit(symbols=("R0402", "R-ODD")), presentation, book
    )

    assert result.categories() == ["layout-unsat"], _failures(result)
    failure = result.failures[0]
    assert failure.subject == "lattice"
    # the two sentences that blamed locks this measurement cannot see
    assert "locked positions" not in failure.detail
    assert "move the locks" not in failure.action
    assert "pin pitches" in failure.detail


# ---------------------------------------------------------------- 洞 5


def test_143a_h5_a_rotation_only_declared_mirrored_is_not_refused():
    """A lock names a rotation; the mirroring is the compiler's to choose.

    The old check was `profile.allows(lock.rotation, False)` and the message
    printed the symbol's pose list — which contained the very pose it had called
    impossible ("locks the part at rotation 90°, which 'R0402' does not allow
    (its poses are 0, 90+mirror)").
    """
    book = T.library()
    book["R0402"] = SymbolProfile(
        symbol_ref="R0402", title="0 unmirrored, 90 mirrored only",
        body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up"),
            SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down"),
        ],
        poses=[SymbolPose(0, False), SymbolPose(90, True)],
    )
    presentation = T.divider_presentation(userLocks=[_lock("R1", rotation=90.0)])
    result = dc.compile(T.divider_circuit(), presentation, book)

    assert "does not allow" not in _failures(result), _failures(result)
    prepared = dc._prepare(
        T.divider_circuit(),
        presentation,
        dc.bind_grammar(
            T.divider_circuit(), presentation, book
        ),
        book,
        dc.CompileBudget(),
    )
    assert prepared.failures == [], [item.detail for item in prepared.failures]


def test_143a_h5_a_rotation_the_symbol_never_declares_is_still_refused():
    book = T.library()
    book["R0402"] = SymbolProfile(
        symbol_ref="R0402", title="a single declared pose",
        body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up"),
            SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down"),
        ],
        poses=[SymbolPose(0, False)],
    )
    result = dc.compile(
        T.divider_circuit(),
        T.divider_presentation(userLocks=[_lock("R1", rotation=90.0)]),
        book,
    )
    assert result.categories() == ["presentation-poor"], _failures(result)
    assert "does not allow" in result.failures[0].detail
    assert "in either mirroring" in result.failures[0].detail


# ---------------------------------------------------------------- F1


def test_143a_f1_a_flag_the_library_lacks_is_wired_never_left_without_a_conductor():
    """`CompileBudget.gnd_flag`'s "written as a net label instead" was a fiction.

    A label is a conductor to `readability.derive_netlist` and to nothing else:
    029 measured `sch.place_netlabel` unusable, and `draw apply` writes wires and
    flags. The fallback is a wire, and every multi-pin net the plan places has a
    conductor.
    """
    book = T.library()
    del book["PWR-GND"]
    result = dc.compile(T.ldo_circuit(), T.ldo_presentation(), book)

    assert result.ok, _failures(result)
    plan = result.best()
    gnd = [segment for segment in plan.segments if segment.net == "GND"]
    assert gnd, "the three-pin GND net was drawn with no conductor at all"

    pins_per_net = {
        net.id: len([m for m in net.members if m in {p.part_id for p in plan.parts}])
        for net in T.ldo_circuit().nets
    }
    for net_id, count in pins_per_net.items():
        if count < 2:
            continue
        conductors = [s for s in plan.segments if s.net == net_id] + [
            s for s in plan.power_symbols if s.net == net_id
        ]
        assert conductors, f"net {net_id} has {count} pins and no conductor"


def test_143a_f1_the_downgrade_is_marked_for_the_change_plan():
    """The reader authorising the plan is told they are not getting a flag."""
    book = T.library()
    del book["PWR-GND"]
    plan = dc.compile(T.ldo_circuit(), T.ldo_presentation(), book).best()
    marked = [
        note for note in plan.notes
        if note.startswith(dc.DOWNGRADE_NOTE_PREFIX)
    ]
    assert marked, plan.notes
    assert "PWR-GND" in marked[0]


# ---------------------------------------------------------------- F4


def test_143a_f4_the_two_tap_kinds_are_measured():
    """`_relation_holds` used to return True for both of them, and for anything.

    The points are the two arms' pins on the shared net — the junction the stub
    leaves from — so the tap's own axis is checkable: a horizontally-leaving stub
    has its junction on a vertical line.
    """
    common = dict(grid=dc.GRID, near_limit=dc.NEAR_LIMIT,
                  lateral=(1.0, 0.0), progress=(0.0, -1.0))
    vertical_pair = ((0.0, 0.0), (0.0, 40.0))
    horizontal_pair = ((0.0, 0.0), (40.0, 0.0))

    assert dc._relation_holds(dc.HORIZONTAL_TAP, vertical_pair, **common)
    assert not dc._relation_holds(dc.HORIZONTAL_TAP, horizontal_pair, **common)
    assert dc._relation_holds(dc.VERTICAL_TAP, horizontal_pair, **common)
    assert not dc._relation_holds(dc.VERTICAL_TAP, vertical_pair, **common)


def test_143a_f4_an_unknown_kind_is_not_silently_satisfied():
    common = dict(grid=dc.GRID, near_limit=dc.NEAR_LIMIT,
                  lateral=(1.0, 0.0), progress=(0.0, -1.0))
    assert not dc._relation_holds("not-a-kind-at-all", ((0.0, 0.0), (5.0, 5.0)), **common)


def test_143a_f4_every_published_kind_is_answered():
    """The ruler covers `CONSTRAINT_KINDS`; nothing is left to the old tail."""
    from boardwise.engines.grammar.base import CONSTRAINT_KINDS

    points = ((0.0, 0.0), (0.0, 40.0))
    common = dict(grid=dc.GRID, near_limit=dc.NEAR_LIMIT,
                  lateral=(1.0, 0.0), progress=(0.0, -1.0))
    for kind in CONSTRAINT_KINDS:
        assert dc._relation_holds(kind, points, **common) in (True, False)
    assert math.isfinite(dc.GRID)

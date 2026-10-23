"""515A: the eight draw-engine holes the pre-release audit swarm dug up.

One file, eight subjects, each with the probe that reproduced it (seam 1 in
``.tmp_hole515_s1/``, seam 2 in ``.tmp_hole515_2/``) turned into a regression
pin. The probes are audit artefacts; these tests are the pins that keep the
fixes from rotting:

* **高危 1** — `_ground_domains` counted domains on the **module-local**
  circuit, so a multi-module page drew PGND and SEC_GND with the shared
  ``PWR-GND`` glyph (绝不并地, violated). The page compiler now hands the
  page-wide domain set to every module compile.
* **高危 2** — the topology round priced relations as soft costs and shipped
  its answer with misses; `compile` said ok with a broken grammar relation in
  the evidence. The same gate the ladder runs now runs on the search's answer.
* **高危 3** — the topology search never read a lock's coordinates, so any
  locked part was seeded and snapped somewhere else and refused downstream
  (``user-lock-violated``). The lock's origin travels into the request and is
  pinned exactly.
* **中危 4** — the wire-not-routable label fallback rebound a local variable,
  so the rail-flag pass still read the old wire expression and wrote
  "pads are joined by the rail" about a rail nobody drew. Written back.
* **中危 5** — `relation_miss` (``<=``) and `relation_holds` (``<``)
  disagreed at the boundary of the four strict order kinds and for
  coincident `adjacent` points. One ruler, parametrized at the boundary.
* **中危 6** — `_flag_seats`' ground branch used a second, divergent seat
  reading (first chain member) instead of `_flag_seat_pins`' ladder, and the
  reserved box did not include the pin itself.
* **中危 7** — the annealing stop rule only counted stalls on the
  evaluate/accept path, so an all-locked input spun the full iteration budget
  doing nothing.
* **中危 8** — `geometry-outside-module-frames` only asked "in **some**
  frame"; a module's own flag drawn into a neighbour's frame passed. Single-
  owner nets are now measured against their own module's frame.

Fixtures are read-only; nothing here talks to a bridge or an editor.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec, UserLock
from boardwise.core.symbolprofile import SymbolPin, SymbolPose, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import pagecompiler as pc
from boardwise.engines import placement as pl
from boardwise.engines import readability
from boardwise.engines.grammar.base import RelativeConstraint

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import test_053b_drawcompiler as b053  # noqa: E402
import test_056_pagecompiler as p056  # noqa: E402
import test_201a_flags as t201a  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"


def _library_from(path: pathlib.Path) -> dict[str, SymbolProfile]:
    payload = path.read_text(encoding="utf-8")
    import json

    book: dict[str, SymbolProfile] = {}
    for entry in json.loads(payload)["profiles"]:
        body = entry.get("body")
        book[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"], title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                SymbolPin(
                    number=str(pin["number"]), name=str(pin.get("name", "")),
                    tip=(float(pin["tip"][0]), float(pin["tip"][1])),
                    direction=str(pin.get("direction", "")),
                )
                for pin in entry["pins"]
            ],
        )
    return book


# ----------------------------------------------------------------- 高危 1


def _two_module_ground_page() -> tuple:
    """The probe's page: module a (PGND) and module b (SEC_GND), one LDO each."""
    lib = b053.library()
    for name in ("PWR-PGND", "PWR-SEC_GND", "PWR-GND"):
        lib[name] = b053.flag(name)

    def module_parts(tag, unit, c1, c2, ground):
        parts = [b053.part(unit, "AMS1117-3.3", "x"),
                 b053.part(c1, "C0805", "10u"), b053.part(c2, "C0402", "22u")]
        nets = [b053.net(f"VIN_{tag}", "power", [unit + ".3", c1 + ".1"]),
                b053.net(f"OUT_{tag}", "power", [unit + ".2", c2 + ".1"]),
                b053.net(ground, "gnd", [unit + ".1", c1 + ".2", c2 + ".2"])]
        return parts, nets

    parts, nets, modules = [], [], []
    for tag, (unit, c1, c2, gnd) in {
        "a": ("U1", "C1", "C2", "PGND"),
        "b": ("U2", "C3", "C4", "SEC_GND"),
    }.items():
        p, n = module_parts(tag, unit, c1, c2, gnd)
        parts += p
        nets += n
        modules.append(
            {"id": tag, "parts": [unit, c1, c2], "role": tag, "grammarRef": "ldo"}
        )
    circuit = b053.circuit(parts, nets)
    presentation = b053.presentation(
        "ldo", modules=modules,
        portRoles={"VIN_a": "input", "VIN_b": "input"},
    )
    return circuit, presentation, lib


def test_two_module_page_draws_two_distinct_ground_glyphs():
    """高危 1 (probe_page_domains): PGND 与 SEC_GND 不得并成同一个 PWR-GND。

    Each module compiled alone sees one ground net, so the old module-local
    domain count was always 1 and every ground took the shared glyph. The
    page-level domain set makes the per-domain refs reachable.
    """
    circuit, presentation, lib = _two_module_ground_page()
    result = pc.compile_page(
        circuit, presentation, lib,
        pc.PageCompileBudget(page_box=(0.0, 0.0, 1169.0, 826.0)),
    )
    assert result.pages, result.render_failures()
    refs = {s.net: s.symbol_ref for s in result.pages[0].plan.power_symbols}
    assert refs["PGND"] == "PWR-PGND", refs
    assert refs["SEC_GND"] == "PWR-SEC_GND", refs


def test_standalone_module_compile_still_counts_its_own_domains():
    """The keyword-only page set is opt-in: a standalone compile derives its own."""
    circuit, presentation, lib = _two_module_ground_page()
    result = dc.compile(circuit, presentation, lib, dc.CompileBudget())
    assert result.ok, result.render_failures()
    # one module's worth of nets? No: this is the *whole* two-module circuit,
    # and it compiles with both domains spelled — the old reading, unchanged.
    refs = {s.net: s.symbol_ref for s in result.candidates[0].power_symbols}
    assert refs["PGND"] == "PWR-PGND" and refs["SEC_GND"] == "PWR-SEC_GND", refs


# ----------------------------------------------------------------- 高危 2


def _flyback_specs():
    circuit = _load_circuit()
    presentation = _load_presentation()
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    return circuit, presentation, book


def _load_circuit():
    from boardwise.core.circuitspec import CircuitSpec

    return CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")


def _load_presentation():
    from boardwise.core.presentationspec import PresentationSpec

    return PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")


def _bind_with_extra_constraint(circuit, presentation, book, extra):
    original = dc.bind_grammar

    def patched(*args, **kwargs):
        result = original(*args, **kwargs)
        if result.ok:
            result = dataclasses.replace(
                result, constraints=result.constraints + extra
            )
        return result

    return original, patched


def test_topology_round_refuses_a_broken_relation():
    """高危 2 (pb3/pb4): 拓扑轮的答案必须过与阶梯同一把关系闸。

    One contradictory constraint beside the grammar's own makes the search's
    best answer miss it; `_topology_placement` itself must refuse the round
    with that gate (naming the pair), instead of handing a placement whose
    evidence carries the miss while `compile` says ok.
    """
    circuit, presentation, book = _flyback_specs()
    budget = dc.CompileBudget(max_candidates=64)
    original, patched = _bind_with_extra_constraint(
        circuit, presentation, book,
        (RelativeConstraint(
            kind="left-of", subject="D3", object="T1",
            reason="515A probe: contradicts the grammar's own right-of(D3, T1)",
        ),),
    )
    dc.bind_grammar = patched
    try:
        binding = patched(circuit, presentation, book)
        prepared = dc._prepare(circuit, presentation, binding, book, budget)
        assert prepared.context is not None
        answer = dc._topology_placement(prepared.context)
    finally:
        dc.bind_grammar = original
    assert isinstance(answer, dc.GrammarFailure), type(answer).__name__
    assert answer.category == "presentation-poor", answer.category
    assert "relation" in answer.detail and "measured" in answer.detail, (
        answer.detail[:300]
    )


def test_topology_round_still_draws_the_untouched_flyback():
    """The gate is not a new refusal for its own sake: the plain flyback still
    reaches the search when the ladder cannot draw it, and its answer passes."""
    circuit, presentation, book = _flyback_specs()
    budget = dc.CompileBudget(max_candidates=64)
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book, budget)
    assert prepared.context is not None
    answer = dc._topology_placement(prepared.context)
    assert not isinstance(answer, dc.GrammarFailure)
    assert dc._relation_failures(prepared.context, answer) == []


# ----------------------------------------------------------------- 高危 3


def test_lock_coordinates_are_pinned_in_the_topology_answer():
    """高危 3 (pc_locks/pc2): 锁定件的坐标是硬锚，搜索不许挪。

    The lock travels into the request (`locked_origin`), so a lock on the
    topology answer's own seat reproduces that answer exactly — the search did
    not merely pass near the point, it was pinned to it.
    """
    circuit, presentation, book = _flyback_specs()
    budget = dc.CompileBudget(max_candidates=64)
    binding = dc.bind_grammar(circuit, presentation, book)
    ctx = dc._prepare(circuit, presentation, binding, book, budget).context
    free = dc._topology_placement(ctx)
    seat = free.origins["C6"]
    rotation = float(free.poses["C6"].rotation)
    assert dc._topology_request(ctx) is not None
    request = dc._topology_request(ctx)
    part = next(p for p in request.parts if p.part_id == "C6")
    presentation.user_locks.append(
        UserLock("C6", x=seat[0], y=seat[1], rotation=rotation)
    )
    pinned_request = dc._topology_request(ctx)
    pinned_part = next(p for p in pinned_request.parts if p.part_id == "C6")
    assert pinned_part.locked_origin == seat
    assert pinned_part.locked is not None
    pinned = pl.place(pinned_request)
    assert pinned.origins["C6"] == seat, (pinned.origins["C6"], seat)
    assert float(pinned.poses["C6"].rotation) == rotation


def test_lock_off_the_natural_seat_is_reported_not_bent():
    """A lock the grammar cannot honour is refused naming the lock (053 sec.5
    scenario 12), never silently snapped back onto the search's own answer.

    The pc2 probe's scenario: a lock 75 units off the seat the search picks
    breaks a pin-level relation; the refusal names `userLocks[C115]` and the
    measured pair instead of bending either the lock or the grammar.
    """
    circuit = CircuitSpec.load(SPECS / "power_entry_xt30.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "power_entry_xt30.presentation.json"
    )
    book = _library_from(SPECS / "power_entry_xt30.library.json")
    budget = dc.CompileBudget(max_candidates=64)
    binding = dc.bind_grammar(circuit, presentation, book)
    ctx = dc._prepare(circuit, presentation, binding, book, budget).context
    seat = dc._topology_placement(ctx).origins["C115"]
    presentation.user_locks.append(
        UserLock("C115", x=seat[0] + 75.0, y=seat[1] + 75.0, rotation=0.0)
    )
    compiled = dc.compile(circuit, presentation, book, budget)
    assert not compiled.ok
    detail = " ".join(item.detail for item in compiled.failures)
    assert "userLocks[C115]" in detail, detail[:300]
    assert "measured" in detail, detail[:300]

# ----------------------------------------------------------------- 中危 4


def test_label_fallback_is_written_back_and_the_note_holds():
    """中危 4 (probe_gnd_label_forced): 降级要写回 expressions，
    且「joined by the rail」只许在有轨道时说。

    **535 重钉（2026-10-23，实测驱动）**：这一条量的**机制**（写回 + 记账 + 不许
    声称一根没人画的轨道）一个字没动，变的是被写回去的那个**表达式**——第二层
    修复让 `GND` 走 `_label_fallback` 的**旗标**分支（530A：地只能是旗标，不许
    网络标签）。

    * **旧读数**（515A 写下这条时）：地降级成**网络标签**，plan 里没有 GND 导线、
      **没有 GND 符号**、三个 label；
    * **新读数**（第二层修复之后，同一份夹具同一份强制失败）：地降级成**旗标**，
      plan 里是**三面** `PWR-GND`（三颗引脚 `C1.2`/`U1.11`/`U1.4` 各一面），
      每面由**恰好一根**引线接到自己的引脚，label **零**个。

    谁是诚实的那一半，看 530A 的原文就够了：「GND 还有各类电源标识，不准给我摆
    网络标签，必须是旗标！」旧的三个 label 正是岳禁掉的画法；新的三面旗标是黄金
    板上的常态，而且**电气结论不变**——旗标在网表里就是这条网的导体，`GND` 仍读
    一个结点（下面照旧量）。写回仍然必须发生：不写回，后面的轨道旗标 pass 还在读
    那根没人画的长线，就会写出「pads are joined by the rail」。
    """
    circuit = t201a.opamp_circuit()
    presentation = t201a.opamp_presentation()
    library = t201a.book()
    real = dc._connect_net

    def failing(ctx, router, expression, blocked, existing=()):
        if expression.net == "GND":
            return None
        return real(ctx, router, expression, blocked, existing)

    dc._connect_net = failing
    try:
        result = dc.compile(circuit, presentation, library, dc.CompileBudget())
    finally:
        dc._connect_net = real
    assert result.candidates
    plan = result.candidates[0]
    flags = [s for s in plan.power_symbols if s.net == "GND"]
    assert len(flags) == 3, (
        "one flag per pin of the ground the router could not join (530A): "
        f"{[(s.symbol_ref, s.x, s.y) for s in plan.power_symbols]}"
    )
    assert {s.symbol_ref for s in flags} == {"PWR-GND"}, flags
    assert [l for l in plan.labels if l.net == "GND"] == [], (
        "a ground is named by a flag, never by a net label (530A)"
    )
    # Each of the three flags is reached by exactly one conductor: its own lead.
    anchors = [(s.x, s.y) for s in flags]

    def _reaches_a_flag(segment) -> bool:
        return any(
            any(abs(x - ax) <= 1e-6 and abs(y - ay) <= 1e-6 for x, y in segment.points)
            for ax, ay in anchors
        )

    leads = [s for s in plan.segments if s.net == "GND" and _reaches_a_flag(s)]
    assert len(leads) == len(flags) == 3, (
        "three flags, three leads — the ground drawn as three named pins: "
        f"{[s.points for s in plan.segments if s.net == 'GND']}"
    )
    for note in result.notes:
        assert "joined by the rail" not in note, note
    # The write-back is this test's subject: the downgrade is on the plan, it says
    # **flag**, and it never claims a rail nobody drew.
    downgrades = [n for n in plan.notes if n.startswith(dc.DOWNGRADE_NOTE_PREFIX)]
    assert len(downgrades) == 1, plan.notes
    assert "**flag** at each of its pins" in downgrades[0], downgrades[0]
    assert "joined by the rail" not in downgrades[0]
    # 520E's account is kept beside it: one record, one net, and it says the same.
    assert [f.net for f in result.label_fallbacks] == ["GND"], result.label_fallbacks
    assert "**flag**" in result.label_fallbacks[0].gave_up
    # The flags are conductors in the offline model: the net still reads one node.
    derived = readability.derive_netlist(plan, library)
    groups = {derived.group_of(m) for m in circuit.net("GND").members}
    assert len(groups) == 1, "the flags name every pin, so the net is still one node"


# ----------------------------------------------------------------- 中危 5


_BOUNDARY_KW = dict(grid=5.0, near_limit=300.0, lateral=(1.0, 0.0),
                    progress=(0.0, -1.0))


@pytest.mark.parametrize("kind,points", [
    ("left-of", ((0.0, 0.0), (2.5, 0.0))),
    ("right-of", ((2.5, 0.0), (0.0, 0.0))),
    ("above", ((0.0, 0.0), (0.0, -2.5))),
    ("below", ((0.0, 0.0), (0.0, 2.5))),
])
def test_strict_order_kinds_agree_at_the_exactly_slack_boundary(kind, points):
    """中危 5 (pa_boundary): 恰好 grid/2 的距离是 holds 为真的边界点。"""
    assert pl.relation_holds(kind, points, **_BOUNDARY_KW)
    assert pl.relation_miss(kind, points, **_BOUNDARY_KW) == 0.0


def test_adjacent_coincident_pair_holds_neither_way():
    """`adjacent` on a coincident pair: holds False, miss > 0 — the two
    functions cannot disagree at that boundary either."""
    points = ((0.0, 0.0), (0.0, 0.0))
    assert not pl.relation_holds("adjacent", points, **_BOUNDARY_KW)
    assert pl.relation_miss("adjacent", points, **_BOUNDARY_KW) > 0.0


# ----------------------------------------------------------------- 中危 6


def test_ground_flag_seat_follows_the_flag_pass_ladder():
    """中危 6: `_flag_seats` 的地网分支与 `_flag_seat_pins` 是同一把尺。

    The opamp GND's members are C1.2, U1.11, U1.4 and the chain part is U1:
    the old "first chain member" reading reserved the room at U1.11, while the
    flag pass walks far-end-first (088b: 背向入口那端) and would stand the
    symbol elsewhere. The reservation must name the head of the **same**
    ladder the flag pass walks.
    """
    circuit = t201a.opamp_circuit()
    presentation = t201a.opamp_presentation()
    library = t201a.book()
    budget = dc.CompileBudget()
    binding = dc.bind_grammar(circuit, presentation, library)
    ctx = dc._prepare(circuit, presentation, binding, library, budget).context
    assert ctx is not None
    reservation = next(s for s in dc._flag_seats(ctx) if s.net_id == "GND")
    # The ladder the flag pass walks, read directly: far end first, then pads
    # by member id. Its head is what the reservation must name.
    ladder = dc._flag_seat_pins(
        ctx,
        dc._Expression(
            net="GND", style="flag",
            points=tuple(
                (member, (0.0, 0.0))
                for member in sorted(circuit.net("GND").members)
            ),
            reason="the seat ladder needs only the member ids",
        ),
        "gnd",
    )
    assert ladder, "the flag pass must have a seat ladder at all"
    head = ladder[0][0]
    assert (reservation.part_id, reservation.token) == (
        head.partition(".")[0], head.partition(".")[2],
    ), (reservation.part_id, reservation.token, head)
    # And it is not the old "first chain member" answer unless the ladder
    # really lands there: for the opamp the two readings differ.
    chain_first = next(
        member for member in sorted(circuit.net("GND").members)
        if ctx.slots.get(member.partition(".")[0]) is not None
        and ctx.slots[member.partition(".")[0]].kind == "chain"
    )
    assert head != chain_first, (
        "this fixture was chosen because the two ladders disagree: "
        "if they agree, the pin is not testing the fix"
    )


def test_flag_reservation_box_covers_its_own_pin():
    """The box is stated relative to the pin, and the pin itself is inside it:
    a zero-sized glyph still reserves the point its corridor grows from."""
    profile = SymbolProfile(
        symbol_ref="PWR-X", title="degenerate flag", body=None, pins=[],
    )
    box = dc._flag_box(profile, 0.0, (10.0, -20.0), "NET", margin=0.0)
    assert box[0] <= 10.0 <= box[2] and box[1] <= -20.0 <= box[3]


# ----------------------------------------------------------------- 中危 7


def _two_locked_parts() -> pl.PlacementInput:
    def symbol(ref):
        return SymbolProfile(
            symbol_ref=ref, title=ref, body=(-10.0, -10.0, 10.0, 10.0),
            pins=[SymbolPin(number="1", name="P", tip=(0.0, 0.0),
                            direction="right")],
        )

    return pl.PlacementInput(
        parts=(
            pl.PlacementPart(
                "A", symbol("A"), (SymbolPose(0, False),),
                locked=SymbolPose(0, False), locked_origin=(10.0, 0.0),
            ),
            pl.PlacementPart(
                "B", symbol("B"), (SymbolPose(0, False),),
                locked=SymbolPose(0, False), locked_origin=(70.0, 0.0),
            ),
        ),
        iterations=6000, restarts=1,
    )


def test_all_locked_input_stops_at_the_stall_bound():
    """中危 7 (pd_extremes): 全锁输入即刻返回种子，不再 6000 次空转。

    The task book offered two repairs — count stalls on the continue paths, or
    short-circuit an all-pinned input to its seed. The short-circuit is the one
    taken: counting continue-path stalls changes how often the rng is drawn on
    *every* input, which reshuffled the flyback's search trajectory and pushed
    its page compile from 7s to 26s (measured — the 116 perf guard went red).
    The short-circuit touches only inputs with nothing to move.
    """
    result = pl.place(_two_locked_parts())
    assert result.accepted == 0
    assert result.iterations == 0, result.iterations


def test_locked_origins_survive_the_seed_and_the_moves():
    """The pinned origin is exact after `place` — seed and moves alike. And
    `_snap` no longer rounds a lock onto the lattice."""
    request = _two_locked_parts()
    result = pl.place(request)
    assert result.origins["A"] == (10.0, 0.0)
    assert result.origins["B"] == (70.0, 0.0)
    assert request.locked_origins() == {"A": (10.0, 0.0), "B": (70.0, 0.0)}


# ----------------------------------------------------------------- 中危 8


def test_single_owner_flag_in_a_foreign_frame_is_reported():
    """中危 8 (probe_page_crossmodule): 只属于一个模块的旗标被画进邻居的框，
    页级闸要点名。

    The probe moved sense's GND — a *shared* net, which legitimately anchors in
    either frame — and passed both before and after; the gap it pointed at
    bites on a single-owner net, so this moves `pwr`'s own 3V3 flag into
    sense's frame and expects the violation to name both sides.
    """
    scene = p056.scenes()[1]
    result = pc.compile_page(
        scene.circuit, scene.presentation, p056.library(), scene.budget
    )
    assert result.pages
    import copy

    page = copy.deepcopy(result.pages[0])
    frames = {m.id: m.frame for m in page.modules}
    moved = False
    for symbol in page.plan.power_symbols:
        if symbol.net == "3V3":
            symbol.x = frames["sense"][0] + 40.0
            symbol.y = frames["sense"][1] + 40.0
            moved = True
            break
    assert moved
    checked = readability.check_page(
        page, scene.circuit, scene.presentation, p056.library(),
        keepouts=(), module_gap=pc.MODULE_GAP,
    )
    kinds = [v.kind for v in checked.hard_violations]
    assert readability.KIND_GEOMETRY_OUTSIDE_FRAMES in kinds, kinds
    evidence = " ".join(
        v.evidence for v in checked.hard_violations
        if v.kind == readability.KIND_GEOMETRY_OUTSIDE_FRAMES
    )
    assert "3V3" in evidence and "sense" in evidence and "pwr" in evidence


def test_shared_net_flag_still_anchors_in_either_frame():
    """A shared net's anchor may sit in either of its own modules' frames: the
    hole-8 reading must not turn the legitimate half into a violation."""
    scene = p056.scenes()[1]
    result = pc.compile_page(
        scene.circuit, scene.presentation, p056.library(), scene.budget
    )
    page = result.pages[0]
    checked = readability.check_page(
        page, scene.circuit, scene.presentation, p056.library(),
        keepouts=(), module_gap=pc.MODULE_GAP,
    )
    assert checked.hard_violations == [], [
        v.render() for v in checked.hard_violations
    ]

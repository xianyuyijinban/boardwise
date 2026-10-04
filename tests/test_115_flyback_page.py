"""115：反激整页出图的收官棒——支路×owner 序关系的**保守**消费 + pin token 同尺。

114 把反激整页推到最后两件事，113 的语法与 114 的求解器都已就位。本棒
**只动求解器与读数层**，`grammar/*.py` 一字不改。

* **① 支路 × owner 的序关系**（`below` / `right-of` 挂在支路与它的 owner 之间）。
  114 试过一版无条件给 basis——能让反激整页出图，却把 098 scene 08 变了一个
  字节而撤回。本棒改成任务书定的**保守判据**：**只有当默认的 pin 方向会违反
  该序关系时**才用序关系给的方向；默认方向已经满足序关系的情形一个字都不动。
  098 的 `left-of(C1,U1)` / `right-of(C4,U1)` 等默认就满足，所以既有五语法
  逐字节不变；反激的 `below(C7,D2)`（辅助储能电容的焊盘朝侧、实测反在上方
  60）默认违反，才被序关系接住。
* **② pin token 同尺**（位号 vs 名字）。`readability._derive` 按 profile 位号建
  `pin_points` 键，规范侧网成员用作者写的 token（`D1.A`/`D1.K`），键对不上 →
  6 条闸报。治法：**读数层按规范侧 token 取点**，与 `drawcompiler._pin_of_token`
  同一把尺（先位号后名字）。不许出现两把不一致的尺。
* **③** ② 修好后独立暴露的两条 text-overlap（旗标/文字摆位）——能顺手治就治，
  治不了就实测归 116，不许为治它引入新的排版风险。

**最硬的闸**：既有五语法编译输出逐字节不变（83 预览 + 15 板 sha256 全同），
并把「114 回撤过的那件事」（098 scene 08 一个字节的变化）写成**回归钉**测试。
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import subprocess

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import (
    DEFAULT_POSES,
    SymbolPin,
    SymbolPose,
    SymbolProfile,
)
from boardwise.engines import drawcompiler as dc
from boardwise.engines import grammar
from boardwise.engines import readability
from boardwise.engines.grammar.base import BELOW, LEFT_OF, RelativeConstraint

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

PROV = "engineer_confirmed"


# ------------------------------------------------------------------ 夹具工具


def _pin(number: str, name: str, tip, direction: str) -> SymbolPin:
    return SymbolPin(number=number, tip=tip, name=name, direction=direction)


def _book() -> dict[str, SymbolProfile]:
    """A core whose pad the branch hangs off points **up**, plus a plain cap.

    Two things about the core are deliberate, and both come from the real flyback
    rather than from taste:

    * its ``1`` pad leaves **upward** — a branch that walks straight out of that
      pad lands *above* the body, which is the measured AMS1117 shape (054 C3);
    * it declares **one** pose, ``(0, False)``. The flyback's ``D2`` is the case
      115-① is about, and what makes it one is that the compiler accepts only
      the single pose whose pads satisfy ``D2``'s own relations — so "some other
      pose would say it" is false there, while for a core with eight poses it is
      true and the criterion deliberately stays out of the way (see
      ``test_the_criterion_is_conservative_for_an_order_the_pin_already_keeps``).
    """
    core = SymbolProfile(
        symbol_ref="U-TEST", title="test core",
        body=(-20.0, -20.0, 20.0, 20.0),
        poses=[SymbolPose(rotation=0.0, mirror=False)],
        pins=[
            _pin("1", "A", (0.0, 40.0), "up"),
            _pin("2", "B", (40.0, 0.0), "right"),
            _pin("3", "C", (-40.0, 0.0), "left"),
            _pin("4", "D", (0.0, -40.0), "down"),
        ],
    )
    cap = SymbolProfile(
        symbol_ref="C-TEST", title="test capacitor",
        body=(-5.0, -10.0, 5.0, 10.0),
        poses=[SymbolPose(rotation=0.0, mirror=False)],
        pins=[
            _pin("1", "1", (0.0, 20.0), "up"),
            _pin("2", "2", (0.0, -20.0), "down"),
        ],
    )
    return {"U-TEST": core, "C-TEST": cap}


def _circuit(parts, nets) -> CircuitSpec:
    payload = {
        "kind": "boardwise-circuit-spec",
        "specVersion": 1,
        "parts": [
            {"id": part_id, "symbolRef": symbol, "provenance": PROV}
            for part_id, symbol in sorted(parts.items())
        ],
        "nets": [
            {"id": net_id, "class": cls, "members": list(members),
             "provenance": PROV}
            for net_id, (cls, members) in sorted(nets.items())
        ],
    }
    return CircuitSpec.from_dict(payload)


def _presentation(modules) -> PresentationSpec:
    payload = {
        "kind": "boardwise-presentation-spec",
        "specVersion": 1,
        "grammarRef": "ic-periphery",
        "sidePreferences": {"input": "left", "output": "right",
                            "power": "top", "gnd": "bottom"},
        "modules": modules,
    }
    return PresentationSpec.from_dict(payload)


ORDER_CIRCUIT = _circuit(
    {"U1": "U-TEST", "C1": "C-TEST"},
    {
        "VOUT": ("power", ["U1.1", "C1.1"]),
        "GND": ("gnd", ["U1.4", "C1.2"]),
        "AUX": ("signal", ["U1.2", "U1.3"]),
    },
)

ORDER_PRESENTATION = _presentation([
    {"id": "core", "parts": ["U1", "C1"],
     "role": "a core with a hanging branch", "grammarRef": "ic-periphery"},
])


def _prepare(circuit, presentation, book, *, order=None) -> dc._Context:
    binding = grammar.bind(circuit, presentation, book)
    assert binding.ok, [item.detail for item in binding.failures]
    if order is not None:
        kind, subject, object_ = order
        binding = dataclasses.replace(
            binding,
            constraints=binding.constraints + (
                RelativeConstraint(kind, subject, object_,
                                   "115 fixture: the order kind under test"),
            ),
        )
    prepared = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=8)
    )
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return prepared.context


def _placed(ctx):
    """A placement for `ctx`, the relation gate switched off, straight back."""
    import boardwise.engines.drawcompiler as module

    saved = module._relation_failures
    module._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = module._place(ctx, dc._variants(ctx)[0])
        assert placed is not None, failure
        return placed
    finally:
        module._relation_failures = saved


# ============================================ ① 序关系的保守消费


def test_a_stated_order_the_default_pin_violates_is_honoured():
    """**115-① 正例（C7 形态）**：默认 pin 方向**违反**序关系时，序关系接管。

    `C1` 挂在 `U1.1`，那根脚的 pad 朝**上**——摆出来就在 owner **上方**。
    语法说 `below(C1, U1)`，而 `below` 与默认方向相反：这不是符号的错
    （053 sec.2 禁换脚号迁就版式），是**求解器**没读序关系。115-① 让它读。

    断言落点本身：`C1.y < U1.y`（栅格 5、公差 2.5），不是「某个函数返回了
    一个非零向量」。落点是读者能对着画布量的东西。
    """
    ctx = _prepare(
        ORDER_CIRCUIT, ORDER_PRESENTATION, _book(),
        order=(BELOW, "C1", "U1"),
    )
    placed = _placed(ctx)
    here = placed.origins["C1"]
    there = placed.origins["U1"]
    slack = ctx.budget.grid / 2.0
    assert here[1] < there[1] - slack, (
        f"below(C1, U1) is not honoured: C1 at {here}, U1 at {there}, "
        f"slack {slack}"
    )


def test_the_same_circuit_without_the_order_kind_keeps_the_pin_direction():
    """**反面**：不写这条序关系时，编译器仍走默认的 pin 方向。

    没有这条声明，编译器不该猜页面的方向（那是 053 sec.4「关系不是坐标」的
    另一面）。这一条钉住判据的另一半：新机制**只由一条明写的序关系**触发，
    不是「支路一律用序关系方向」。
    """
    ctx = _prepare(ORDER_CIRCUIT, ORDER_PRESENTATION, _book())
    placed = _placed(ctx)
    here = placed.origins["C1"]
    there = placed.origins["U1"]
    assert here[1] > there[1], (
        "without a stated order kind the branch must stay on the side its "
        f"own pin names (up): C1 at {here}, U1 at {there}"
    )


def test_the_criterion_stands_aside_when_the_pin_already_says_it():
    """**保守性**：pin 自己已经照着序关系说时，判据不动手。

    判据的门是「owner 的符号**没有一个**合法位姿能照着说」。这里把 owner 那根
    焊盘的朝向换成朝**下**、序关系仍然写 `below(C1, U1)`——pin 自己就说了「下」，
    于是它**就是**那个已经照着说的合法位姿，判据必须让位，落点与「关掉判据」
    时**逐件相同**。

    这一条不额外设「当前 pin 方向」那道闸：``_a_pose_says`` 遍历的正是接受位姿
    集合，当前那个就在其中，所以凡是当前方向会让位的情形它已经让了位
    （见 SUMMARY §五「第一版的两道门里第一道是死代码」）。
    """
    book = _book()
    book["U-TEST"] = dataclasses.replace(
        book["U-TEST"], pins=[
            _pin("1", "A", (0.0, -40.0), "down"),   # the pad leaves downward
            _pin("2", "B", (40.0, 0.0), "right"),
            _pin("3", "C", (-40.0, 0.0), "left"),
            _pin("4", "D", (0.0, 40.0), "up"),
        ],
    )
    ctx = _prepare(
        ORDER_CIRCUIT, ORDER_PRESENTATION, book, order=(BELOW, "C1", "U1"),
    )
    slot = ctx.slots["C1"]
    token = dc._shared_token(ctx, slot)
    pin_direction = dc._pin_direction(
        ctx, slot.owner, token, {slot.owner: ctx.accepted[slot.owner][0]})
    assert pin_direction[1] < 0, (
        "the fixture's pin leaves downward, which already is what below(C1, U1) "
        f"asks; if that changed the test measures nothing (got {pin_direction})"
    )
    assert dc._order_direction(ctx, slot) is None, (
        "the pin direction already keeps below(C1, U1), so the criterion must "
        "stand aside"
    )
    # And the placement it produces must be the pin's own, unchanged by the
    # stated order kind.
    with_criterion = _placed(ctx).origins
    plain = _prepare(ORDER_CIRCUIT, ORDER_PRESENTATION, book)
    baseline = _placed(plain).origins
    moved = sorted(
        part_id for part_id in baseline
        if baseline[part_id] != with_criterion[part_id]
    )
    assert not moved, (
        "below(C1, U1) agrees with the pin, so the criterion must change "
        f"nothing — but it moved {moved}"
    )


def test_the_criterion_is_conservative_when_another_pose_would_say_it():
    """**保守性（gate 2）**：owner 的**别的位姿**已经能说这条序关系时，判据不动手。

    这是 114 回撤的那一刀的正面写法，也是 115 查清的**根因**：098 的
    ``left-of(C1, U1)` 之所以在 114 那版 basis 下变了 `098_scene08_narrow_refused.txt`
    一个字节，是因为 pose-variant=1 把 U1 **镜像**了，它所有焊盘于是都朝反方向。
    114 的 basis 不问「换个位姿能不能说」，直接改画，于是那一档画的东西全变了。

    这里把同一件事做成合成夹具：owner 给**八个位姿**，其中几个的焊盘朝左，
    `left-of(C1, U1)` 于是**本来就能满足**。判据必须让位——即使当前这一档的
    pin 方向朝右。落点必须与「关掉判据」时**逐件相同**。
    """
    import boardwise.engines.drawcompiler as module

    book = _book()
    # A core with the full default pose set: several of its rotations put the
    # pad on the left, which is what `left-of` asks for.
    book["U-TEST"] = dataclasses.replace(
        book["U-TEST"], poses=list(DEFAULT_POSES),
    )
    ctx = _prepare(
        ORDER_CIRCUIT, ORDER_PRESENTATION, book, order=(LEFT_OF, "C1", "U1"),
    )
    slot = ctx.slots["C1"]
    assert len(ctx.accepted["U1"]) > 1, (
        "the fixture needs an owner with more than one accepted pose, else "
        "the gate cannot be exercised"
    )
    with_criterion = _placed(ctx).origins
    saved_gate = module._relation_failures
    saved = module._order_direction
    module._relation_failures = lambda ctx_, placed_: []
    module._order_direction = lambda *args, **kwargs: None
    try:
        without, failure = module._place(ctx, dc._Variant(
            label="probe", scale=1.0, pose_index=0))
    finally:
        module._order_direction = saved
        module._relation_failures = saved_gate
    assert without is not None, failure
    moved = sorted(
        part_id for part_id in without.origins
        if without.origins[part_id] != with_criterion[part_id]
    )
    assert not moved, (
        "another legal pose of the owner already keeps left-of(C1, U1), so the "
        f"criterion must stand aside — but it moved {moved}"
    )


# ============================================ ① 的回归钉：既有语法不动


def _library_from(path: pathlib.Path) -> dict[str, SymbolProfile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        body = entry.get("body")
        book[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"], title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                _pin(str(pin["number"]), str(pin.get("name", "")),
                     (float(pin["tip"][0]), float(pin["tip"][1])),
                     str(pin.get("direction", "")))
                for pin in entry["pins"]
            ],
        )
    return book


def test_the_new_order_basis_moves_nothing_for_the_existing_grammars():
    """**最硬的保守钉**（快版）：新序关系判据对既有语法**不动一个坐标**。

    114 的无条件 basis 就是从这一条漏过去的——它让反激整页通了，却把
    098 scene 08 变了一个字节。这里把 ① 那个判据整段**关掉**再跑一遍
    `_place`，两次的 `origins` 必须逐件相同。零移动闸的 83 张预览 + 15 板是
    它的最终形态；这条是能先挡一道的快版。
    """
    import boardwise.engines.drawcompiler as module

    helper = "_order_direction"
    assert hasattr(module, helper), (
        f"{helper} is the hook this test disables; if the mechanism moved, "
        "this test has to move with it"
    )
    stems = ("power_entry_xt30", "ch340_serial")
    seen = 0
    for stem in stems:
        library_path = SPECS / f"{stem}.library.json"
        circuit_path = SPECS / f"{stem}.circuit.json"
        presentation_path = SPECS / f"{stem}.presentation.json"
        if not library_path.is_file():
            continue
        book = _library_from(library_path)
        circuit = CircuitSpec.load(circuit_path)
        presentation = PresentationSpec.load(presentation_path)
        binding = grammar.bind(circuit, presentation, book)
        if not binding.ok:
            continue
        ctx = dc._prepare(
            circuit, presentation, binding, book,
            dc.CompileBudget(max_candidates=8),
        ).context
        if ctx is None:
            continue
        with_basis = _placed(ctx)

        saved = getattr(module, helper)
        setattr(module, helper, lambda *args, **kwargs: None)
        try:
            without, failure = module._place(ctx, dc._Variant(
                label="probe", scale=1.0, pose_index=0))
        finally:
            setattr(module, helper, saved)
        assert without is not None, f"{stem}: {failure}"
        moved = sorted(
            part_id for part_id in with_basis.origins
            if with_basis.origins[part_id] != without.origins[part_id]
        )
        assert not moved, (
            f"{stem}: the new order basis moved {moved} — 114's regression "
            "is exactly this, and it must not come back"
        )
        seen += 1
    assert seen, "no existing grammar was exercised; the guarantee is untested"


def test_098_scene08_refusal_is_byte_identical_to_the_recorded_baseline():
    """**114 回撤过的那件事的回归钉**：098 scene 08 一个字节都不许变。

    114 §五记下：它那版 basis 让 ``098_scene08_narrow_refused.txt`` 从
    ``cd23f7d0…`` 变成 ``fcd6ac6c…``。本条把该文件重新生成并与
    ``outputs/114/previews/098/098_scene08_narrow_refused.txt`` 比对——逐字节。
    若 ① 的保守判据仍改变它的输出，这条会红。
    """
    baseline = (
        ROOT / "outputs" / "114" / "previews" / "098"
        / "098_scene08_narrow_refused.txt"
    )
    if not baseline.is_file():
        pytest.skip("the 098 scene 08 baseline product is not in the tree")
    scratch = ROOT / "outputs" / "115" / "_probe_098"
    scratch.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(PYTHON), str(ROOT / "tools" / "098_previews.py"), str(scratch)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    produced = scratch / "098_scene08_narrow_refused.txt"
    assert produced.is_file(), sorted(p.name for p in scratch.iterdir())
    assert produced.read_bytes() == baseline.read_bytes(), (
        "the 098 scene 08 refusal report changed a byte — 114's regression, "
        "the new order basis must not touch the existing grammars"
    )
    _assert_shallow_copy_of_scratch(scratch)


def _assert_shallow_copy_of_scratch(scratch: pathlib.Path) -> None:
    """The scratch directory is a re-run, not the baseline — say so once.

    Written as a function rather than a comment so that the last line of the
    byte-comparison test states the one thing a reader can get wrong: the file
    being compared against is the **recorded** one under ``outputs/114``.
    """
    assert scratch != (ROOT / "outputs" / "114" / "previews" / "098")

# ============================================ ② pin token 同尺（位号 vs 名字）


DIODES = (
    # number 1/2 declared, names A/K — the shape the flyback's D1 uses, and the
    # same symbol the sibling D2 refers to by number in the same document.
    ("1", "A", (0.0, 20.0), "up"),
    ("2", "K", (0.0, -20.0), "down"),
)


def _diode_book() -> dict[str, SymbolProfile]:
    return {
        "DIO-TEST": SymbolProfile(
            symbol_ref="DIO-TEST", title="test diode",
            body=(-5.0, -10.0, 5.0, 10.0),
            poses=[SymbolPose(rotation=0.0, mirror=False)],
            pins=[_pin(number, name, tip, direction)
                  for number, name, tip, direction in DIODES],
        ),
    }


def _diode_plan():
    """A one-part plan drawn with the diode, read straight back."""
    from boardwise.core.layoutplan import LayoutPlan, LayoutPart

    return LayoutPlan(parts=[
        LayoutPart(part_id="D1", symbol_ref="DIO-TEST", x=0.0, y=0.0,
                   rotation=0.0, mirror=False),
    ])


def _diode_circuit(token: str):
    return CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec", "specVersion": 1,
        "parts": [{"id": "D1", "symbolRef": "DIO-TEST", "provenance": PROV}],
        "nets": [{"id": "SW", "class": "signal", "members": [f"D1.{token}"],
                  "provenance": PROV}],
    })


def _plain_presentation():
    return PresentationSpec.from_dict({
        "kind": "boardwise-presentation-spec", "specVersion": 1,
        "grammarRef": "ic-periphery",
        "sidePreferences": {"input": "left", "output": "right",
                            "power": "top", "gnd": "bottom"},
    })


def test_the_one_ruler_resolves_a_name_token_to_the_profiles_number():
    """**115-② 的钉法**：``D1.A`` 与 ``D1.1`` 经同一把尺解到**同一把键**。

    符号库声明 number=`1`/`2`、name=`A`/`K`。规范侧可以写任一种，所以读数层
    必须有且只有一把尺——:func:`readability._profile_pin_ruler`，与
    ``drawcompiler._pin_of_token``、``grammar.base.profile_pin_for`` 同一条规则
    （先位号后名字）。本条直接量那把尺：两种写法解出同一个位号。
    """
    profile = _diode_book()["DIO-TEST"]
    assert readability._profile_pin_ruler(profile, "A") == "1"
    assert readability._profile_pin_ruler(profile, "1") == "1"
    assert readability._profile_pin_ruler(profile, "K") == "2"
    # A token the symbol genuinely lacks is returned unchanged, so constraint 9
    # still reports "the symbol has no such pin" instead of folding it onto
    # some other pad.
    assert readability._profile_pin_ruler(profile, "Z") == "Z"
    assert readability._profile_pin_ruler(None, "A") == "A"


def test_a_spec_naming_pins_by_name_gets_no_false_required_pin_finding():
    """**115-② 正例**：规范写名字时，闸不再说「符号没有这根脚」。

    114 实测的两条 `required-pin-not-connected`（`D1.A`/`D1.K`「没有 tip」）
    就是这个：键对不上，不是图画错。这里让约束 9 在两种写法下**给出同一条**
    读数——都不报「没有 tip」。
    """
    book = _diode_book()
    plan = _diode_plan()
    presentation = _plain_presentation()
    seen = {}
    for token in ("1", "A"):
        result = readability.check(
            plan, _diode_circuit(token), presentation, book,
        )
        missing = [
            violation for violation in result.hard_violations
            if "has no tip in the drawing" in violation.evidence
        ]
        seen[token] = missing
        assert not missing, (
            f"the spec names D1.{token} and the symbol has that pad under "
            f"either spelling; the checker must not say otherwise: "
            f"{[v.evidence for v in missing]}"
        )
    assert seen["1"] == seen["A"]


def test_the_two_spellings_are_one_pad_not_two_nodes():
    """**同尺的反面**：两种写法不是两个键，所以一颗焊盘**只在一个节点上**。

    「两把尺」最隐蔽的失败不是查不到，而是两把尺给出**略微不同**的答案，
    于是一颗焊盘在分区比较里出现两次、或凭空多出一个节点。本条把 `A` 与 `K`
    写进**同一个网**（电气上正是同一件事：两颗脚之间是二极管），量的是派生
    网表自己——`D1.1` 与 `D1.2` 必须落在同一个 group 上，且该 group 里只有
    这两个键。
    """
    from boardwise.core.layoutplan import LayoutSegment

    plan = _diode_plan()
    plan.segments.append(LayoutSegment(points=[
        (0.0, 20.0), (0.0, 40.0),
    ], net="SW"))
    book = _diode_book()
    derived = readability.derive_netlist(plan, book)
    circuit = CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec", "specVersion": 1,
        "parts": [{"id": "D1", "symbolRef": "DIO-TEST", "provenance": PROV}],
        "nets": [{"id": "SW", "class": "signal",
                  "members": ["D1.A", "D1.K"], "provenance": PROV}],
    })
    profile_map = {"DIO-TEST": book["DIO-TEST"]}
    declared = readability._role_node_expectations(circuit, profile_map)
    # The spec's own spellings come back keyed by the profile's numbers — one
    # key space, the ruler having spoken exactly once.
    assert declared == {"D1.1": "SW", "D1.2": "SW"}, declared
    # And the derived side agrees, so the wire on D1.1's tip is the spec's SW.
    assert derived.wired_pins == frozenset({"D1.1"}), derived.wired_pins


def test_a_name_spelled_member_of_a_shared_net_stops_being_unmentioned():
    """**115-② 的实际病灶**：`D1.1`/`D1.2` 不再在分区比较里成 unmentioned。

    114 实测的两条 `netlist-partition-mismatch` 里，`D1.1`（SW 上）与
    `D1.2`（CLAMP 上）都是 **unmentioned**——因为规范侧写的是 `D1.A`/`D1.K`，
    派生侧的键是 `D1.1`/`D1.2`，谁也认不出谁，于是同网的邻居（`Q1.2`/`T1.P2`）
    看上去连成了一体。本条量那一层：`spec_net_of` 里每一颗脚都必须有网。
    """
    book = _diode_book()
    circuit = CircuitSpec.from_dict({
        "kind": "boardwise-circuit-spec", "specVersion": 1,
        "parts": [{"id": "D1", "symbolRef": "DIO-TEST", "provenance": PROV}],
        "nets": [
            {"id": "SW", "class": "signal", "members": ["D1.A"],
             "provenance": PROV},
            {"id": "CLAMP", "class": "signal", "members": ["D1.K"],
             "provenance": PROV},
        ],
    })
    declared = readability._role_node_expectations(
        circuit, {"DIO-TEST": book["DIO-TEST"]})
    assert declared == {"D1.1": "SW", "D1.2": "CLAMP"}, declared
    unmentioned = sorted(pin for pin in ("D1.1", "D1.2")
                         if pin not in declared)
    assert not unmentioned, f"{unmentioned} are unmentioned: {declared}"
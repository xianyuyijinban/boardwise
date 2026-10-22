"""201B 阶段一：拓扑感知布局搜索（`engines/placement.py`）验收。

============================ 这批要治的病 ============================

旗舰输入反激 `blocklib/specs/flyback_uc3845.*` 今天 `draw compile` **0 候选**，
24 档变体全部死在同一句 `same-column(Q1, R5)`：现布局是「链+支路+货架」顺序贪心，
位姿只搜 2 档，关系约束只做事后验尸（违反即整候选判死，不修）。

新模块的五条概念（文件头有全文）：方向、成簇、位姿进搜索、关系分软硬、代价可解释。
本文件钉的是**可判据的那几面**，一条测试一句话：

1. **尺子与语法同一把**（§一）：十种关系 kind 的 `relation_holds` 与
   `relation_miss` 必须逐点等价——`miss == 0` 当且仅当 `holds`。两个函数各写一遍
   分支就会各答一次，这正是「两把尺子」的病。
2. **pin 级对齐是做得到的**（§二）：反激那条 `same-column(Q1, R5)` 量的是
   `Q1.3` 与 `R5.1`（同网 SRC）两个**针尖**，不是两个原点——20 单位的针偏移
   让原点对齐永远差 20。测试合成一个最小场景，钉住「原点对齐不够、搜索够得着」。
3. **锁定优先**（§三）：lock 的件位姿照锁、位置可以被关系拉走，但**位姿不许被翻**。
4. **硬约束只有三条**（§四）：出页、压 keep-out、重叠。关系违反**不进**硬约束。
5. **确定性**（§五）：同输入跑两遍，落位逐字相同。
6. **真三件套端到端**（§六）：反激 19 件、30 条关系，全部关系为 0 违反、无硬违反、
   单次搜索 < 30 秒（120/121 的 SEARCH_MARGIN 教训：别让搜索膨胀成分钟级）。
7. **代价可解释**（§七）：每项代价都有名字、值、理由；`to_jsonable` 能印出来。
"""

from __future__ import annotations

import dataclasses
import functools
import json
import math
import pathlib
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.core.symbolprofile import SymbolPin, SymbolPose, SymbolProfile  # noqa: E402
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import placement as pl  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"


def _pin(number: str, name: str, tip: tuple[float, float], direction: str) -> SymbolPin:
    return SymbolPin(number=number, tip=tip, name=name, direction=direction)


def _library_from(path: pathlib.Path) -> dict[str, SymbolProfile]:
    """反激三件套的库 sidecar，读成编译器吃的那本 book。

    与 `test_113_flyback_grammar._library_from` 同一读法（sidecar 就是
    `boardwise-symbol-profile` 那份格式）。
    """
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


# ---------------------------------------------------------------- 合成零件库


def _resistor(ref: str = "R") -> SymbolProfile:
    """横放两脚电阻：pin1 左、pin2 右，针尖 ±20。"""
    return SymbolProfile(
        symbol_ref=ref, body=(-10.5, -4.5, 10.5, 4.5),
        pins=[_pin("1", "1", (-20.0, 0.0), "left"),
              _pin("2", "2", (20.0, 0.0), "right")],
    )


def _nmos() -> SymbolProfile:
    """竖放三脚 NMOS：G 左、D 上、S 下——与 flyback 料号同一个形状。"""
    return SymbolProfile(
        symbol_ref="NMOS", body=(-20.5, -10.5, 14.5, 10.5),
        pins=[_pin("1", "G", (-30.0, 0.0), "left"),
              _pin("2", "D", (0.0, 20.0), "up"),
              _pin("3", "S", (0.0, -20.0), "down")],
    )


ALL_POSES = tuple(
    SymbolPose(rotation=rotation, mirror=mirror)
    for rotation in (0, 90, 180, 270)
    for mirror in (False, True)
)


# ------------------------------------------------------------------- §一 尺子


#: (kind, 两个测量点, 该 kind 是否成立) —— 每种 kind 两条，一真一假。
_KIND_CASES = [
    ("same-column", ((0.0, 0.0), (2.0, 90.0)), True),
    ("same-column", ((0.0, 0.0), (7.0, 90.0)), False),
    ("same-row", ((0.0, 0.0), (90.0, 2.0)), True),
    ("same-row", ((0.0, 0.0), (90.0, 7.0)), False),
    ("horizontal-tap", ((0.0, 0.0), (2.5, -50.0)), True),
    ("horizontal-tap", ((0.0, 0.0), (9.0, -50.0)), False),
    ("vertical-tap", ((0.0, 0.0), (-50.0, 2.5)), True),
    ("vertical-tap", ((0.0, 0.0), (-50.0, 9.0)), False),
    ("above", ((0.0, 0.0), (60.0, -30.0)), True),
    ("above", ((0.0, 0.0), (60.0, 30.0)), False),
    ("below", ((0.0, 0.0), (60.0, 30.0)), True),
    ("below", ((0.0, 0.0), (60.0, -30.0)), False),
    ("left-of", ((0.0, 0.0), (30.0, 60.0)), True),
    ("left-of", ((0.0, 0.0), (-30.0, 60.0)), False),
    ("right-of", ((0.0, 0.0), (-30.0, 60.0)), True),
    ("right-of", ((0.0, 0.0), (30.0, 60.0)), False),
    ("adjacent", ((0.0, 0.0), (0.0, 60.0)), True),
    ("adjacent", ((0.0, 0.0), (10.0, 60.0)), False),
    ("near", ((0.0, 0.0), (200.0, 100.0)), True),
    ("near", ((0.0, 0.0), (400.0, 100.0)), False),
]


@pytest.mark.parametrize("kind,points,expected", _KIND_CASES)
def test_relation_miss_is_zero_exactly_when_the_ruler_holds(kind, points, expected):
    """`relation_miss == 0` 与 `relation_holds` 必须逐点等价。

    两个函数各写一遍十种 kind 的分支，就是两把尺子；这一条把「miss 为 0」钉成
    「holds 为真」的同义句——顺带验 `holds` 自己的答案与手算一致。
    """
    kwargs = dict(grid=5.0, near_limit=300.0, lateral=(1.0, 0.0),
                  progress=(0.0, -1.0))
    assert pl.relation_holds(kind, points, **kwargs) is expected
    miss = pl.relation_miss(kind, points, **kwargs)
    assert (miss == 0.0) is expected
    assert miss >= 0.0


def test_an_unknown_kind_holds_for_neither_function():
    """未知 kind 两边都不许「默认通过」（053 sec.5 场景 12：报告冲突，不静默忽略）。"""
    kwargs = dict(grid=5.0, near_limit=300.0, lateral=(1.0, 0.0),
                  progress=(0.0, -1.0))
    assert pl.relation_holds("diagonal-of", ((0.0, 0.0), (0.0, 0.0)), **kwargs) is False
    assert pl.relation_miss("diagonal-of", ((0.0, 0.0), (0.0, 0.0)), **kwargs) == float("inf")


def test_relation_holds_matches_the_compilers_own_ruler():
    """与 `drawcompiler._relation_holds` 同答案——语法层与布局层不许两把尺子。

    真三件套的 30 条关系逐条对比两个实现，答案必须一字不差。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    ctx = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=8)
    ).context
    assert ctx is not None
    request = _request_from(ctx, circuit, presentation)
    # 一组合成落位：把每个器件按序摆开，再逐条比两个尺子的答案。
    state = pl._seed(request, pl._ranks(request.relations, request.part_ids()))
    pins = pl._pins_of(request, state)
    checked = 0
    for relation in request.relations:
        points = pl.relation_points(request, relation, pins, state.origins)
        assert points is not None
        theirs = dc._relation_holds(
            relation.kind, points, grid=request.grid,
            near_limit=request.near_limit, lateral=request.lateral,
            progress=request.progress,
        )
        ours = pl.relation_holds(
            relation.kind, points, grid=request.grid,
            near_limit=request.near_limit, lateral=request.lateral,
            progress=request.progress,
        )
        assert ours is theirs, relation.label()
        checked += 1
    assert checked == len(request.relations) >= 25


# ------------------------------------------------------- §二 pin 级对齐够得着


def _two_part_request(
    poses_r5: tuple[SymbolPose, ...], relations: tuple[pl.PlacementRelation, ...]
) -> pl.PlacementInput:
    """最小场景：Q1 竖放、R5 横放，两者只有 SRC 一条网相连。

    Q1.3（S）针尖在局部 (0, -20)，R5.1 在局部 (-20, 0)——**原点对齐永远差 20**，
    这正是反激那条 same-column 量到的偏移。
    """
    return pl.PlacementInput(
        parts=(
            pl.PlacementPart("Q1", _nmos(), ALL_POSES),
            pl.PlacementPart("R5", _resistor("R0603"), poses_r5),
        ),
        nets=(
            pl.PlacementNet("SRC", (("Q1", "3"), ("R5", "1"))),
            pl.PlacementNet("PGND", (("R5", "2"),), cls="gnd"),
            pl.PlacementNet("SW", (("Q1", "2"),)),
        ),
        relations=relations,
        progress=(0.0, -1.0), lateral=(1.0, 0.0),
        iterations=6000, restarts=3, seed=201,
    )


def test_a_pin_level_same_column_is_reachable_by_the_search():
    """反激的死因：`same-column(Q1, R5)` 量的是针尖，搜索必须够得着。

    两个端点都自由时，搜索必须落到「Q1.3 与 R5.1 同一列」的落位上；这不是
    「选一档位姿」能解决的题，量的是两个**针尖**——原点差 20。
    """
    request = _two_part_request(
        ALL_POSES,
        (pl.PlacementRelation("same-column", "Q1", "R5", "岳 110 裁决 c"),
         pl.PlacementRelation("near", "R5", "Q1", "岳 110 裁决 d"),
         pl.PlacementRelation("below", "R5", "Q1", "岳 110 裁决 d")),
    )
    result = pl.place(request)
    assert result.hard == [], [item.render() for item in result.hard]
    assert result.relations_held, [item.render() for item in result.soft]
    pins = pl._pins_of(request, pl._State(dict(result.origins), dict(result.poses)))
    assert abs(pins["Q1"]["3"][0] - pins["R5"]["1"][0]) <= request.grid / 2.0
    assert pins["R5"]["1"][1] < pins["Q1"]["3"][1]


def test_the_search_reports_a_relation_it_cannot_keep_instead_of_refusing():
    """关系是**软**的：留不住的档也得出图，并逐条印出名与值（不判死）。

    场景：把 R5 位姿锁成一档、再用一条 `left-of(R5, Q1)` 指到反方向——关系留不住，
    结果里必须有这条命名的代价，而不是「零候选」。
    """
    request = pl.PlacementInput(
        parts=(
            pl.PlacementPart("Q1", _nmos(), ALL_POSES,
                             locked=SymbolPose(rotation=0, mirror=False)),
            pl.PlacementPart("R5", _resistor("R0603"),
                             (SymbolPose(rotation=90, mirror=False),)),
        ),
        nets=(
            pl.PlacementNet("SRC", (("Q1", "3"), ("R5", "1"))),
            pl.PlacementNet("PGND", (("R5", "2"),), cls="gnd"),
            pl.PlacementNet("SW", (("Q1", "2"),)),
        ),
        relations=(
            # same-column 与 left-of 同时要求 R5 在 Q1 的同一列**左右各一边**：
            # 针尖对齐要 R5 在 Q1 正下方，left-of 要它在左边——两者不可同时成立。
            pl.PlacementRelation("same-column", "Q1", "R5", "在开关的列里"),
            pl.PlacementRelation("left-of", "R5", "Q1", "与上一条冲突"),
        ),
        progress=(0.0, -1.0), lateral=(1.0, 0.0),
        iterations=3000, restarts=2, seed=7,
    )
    result = pl.place(request)
    assert result.hard == []
    term = result.term("relation:left-of(R5, Q1)")
    assert term is not None and term.violated
    assert "missed by" in term.detail and "冲突" in term.detail
    assert result.term("relation:same-column(Q1, R5)").value == 0.0


# ------------------------------------------------------------------- §三 锁定


def test_a_locked_part_keeps_its_pose_and_is_never_turned():
    """052 的合法缝：userLocks 的件位姿照锁，代价函数也不许动它。"""
    locked = SymbolPose(rotation=270, mirror=True)
    request = pl.PlacementInput(
        parts=(
            pl.PlacementPart("Q1", _nmos(), ALL_POSES),
            pl.PlacementPart("R5", _resistor("R0603"), ALL_POSES + (locked,),
                             locked=locked),
        ),
        nets=(
            pl.PlacementNet("SRC", (("Q1", "3"), ("R5", "1"))),
            pl.PlacementNet("PGND", (("R5", "2"),), cls="gnd"),
            pl.PlacementNet("SW", (("Q1", "2"),)),
        ),
        relations=(pl.PlacementRelation("same-column", "Q1", "R5", "r"),
                   pl.PlacementRelation("near", "R5", "Q1", "r")),
        progress=(0.0, -1.0), lateral=(1.0, 0.0),
        iterations=4000, restarts=2, seed=11,
    )
    result = pl.place(request)
    assert result.poses["R5"] == locked
    assert result.relations_held


def test_a_lock_outside_the_accepted_set_is_still_obeyed():
    """锁的旋转不在合法集里也照锁（053 sec.5 场景 12：要么照做要么报冲突）。"""
    locked = SymbolPose(rotation=45, mirror=False)
    request = pl.PlacementInput(
        parts=(
            pl.PlacementPart("Q1", _nmos(), ALL_POSES),
            pl.PlacementPart("R5", _resistor("R0603"),
                             (SymbolPose(0, False), SymbolPose(90, False)),
                             locked=locked),
        ),
        nets=(pl.PlacementNet("SRC", (("Q1", "3"), ("R5", "1"))),),
        relations=(pl.PlacementRelation("near", "R5", "Q1", "r"),),
        progress=(0.0, -1.0), lateral=(1.0, 0.0),
        iterations=1000, restarts=1, seed=3,
    )
    result = pl.place(request)
    assert result.poses["R5"] == locked


# --------------------------------------------------------------- §四 硬/软分家


def test_overlap_and_the_page_are_hard_while_a_relation_is_not():
    """硬约束三条：出页、压 keep-out、重叠；关系违反不进硬约束。"""
    request = pl.PlacementInput(
        parts=(
            pl.PlacementPart("Q1", _nmos(), ALL_POSES),
            pl.PlacementPart("R5", _resistor("R0603"), ALL_POSES),
        ),
        nets=(pl.PlacementNet("SRC", (("Q1", "3"), ("R5", "1"))),),
        relations=(pl.PlacementRelation("near", "R5", "Q1", "r"),),
        page_box=(0.0, 0.0, 60.0, 60.0),
        keepouts=((0.0, 0.0, 60.0, 60.0),),
        progress=(0.0, -1.0), lateral=(1.0, 0.0),
        iterations=2000, restarts=1, seed=5,
    )
    result = pl.place(request)
    names = {item.name for item in result.costs}
    assert {"out-of-page", "keepout", "overlap"} <= names
    hard_names = {item.name for item in result.costs if item.hard}
    assert hard_names == {"out-of-page", "keepout", "overlap"}
    # 「没给页」是页那一项的另一个答案，与「出了页」不同名。
    no_page = pl.PlacementInput(
        parts=(pl.PlacementPart("Q1", _nmos(), ALL_POSES),),
        nets=(pl.PlacementNet("SW", (("Q1", "2"),)),),
        iterations=1, restarts=1, seed=5,
    )
    assert pl.place(no_page).term("page").value == 0.0


def test_a_relation_violation_never_becomes_a_hard_violation():
    """关系违反只出现在软项里——那是「扣分修复」，不是「整候选判死」。"""
    request = pl.PlacementInput(
        parts=(
            pl.PlacementPart("Q1", _nmos(), ALL_POSES,
                             locked=SymbolPose(rotation=0, mirror=False)),
            pl.PlacementPart("R5", _resistor("R0603"),
                             (SymbolPose(rotation=90, mirror=False),)),
        ),
        nets=(pl.PlacementNet("SRC", (("Q1", "3"), ("R5", "1"))),),
        relations=(
            pl.PlacementRelation("same-column", "Q1", "R5", "c"),
            pl.PlacementRelation("left-of", "R5", "Q1", "conflicts with c"),
        ),
        progress=(0.0, -1.0), lateral=(1.0, 0.0),
        iterations=1500, restarts=1, seed=9,
    )
    result = pl.place(request)
    assert result.hard == []
    soft_names = {item.name for item in result.soft}
    assert "relation:left-of(R5, Q1)" in soft_names
    assert not any(
        item.hard for item in result.costs if item.name.startswith("relation:")
    )


# ----------------------------------------------------------------- §五 确定性


def test_the_same_input_produces_the_same_drawing_twice():
    """种子固定：同输入跑两遍，落位逐字相同（`place` 的对外承诺）。"""
    request = _two_part_request(
        ALL_POSES,
        (pl.PlacementRelation("same-column", "Q1", "R5", "c"),
         pl.PlacementRelation("near", "R5", "Q1", "n")),
    )
    first = pl.place(request)
    second = pl.place(request)
    assert json.dumps(first.placement(), sort_keys=True) == json.dumps(
        second.placement(), sort_keys=True
    )
    assert first.iterations == second.iterations
    assert first.seed == second.seed


# ------------------------------------------------- §六 真三件套端到端 + 性能


def _request_from(
    ctx, circuit: CircuitSpec, presentation: PresentationSpec
) -> pl.PlacementInput:
    """编译器 stage 2 的上下文 -> 本模块的输入（工具与测试共用这一读法）。"""
    parts = []
    for part_id in sorted(ctx.slots):
        parts.append(pl.PlacementPart(
            part_id=part_id, profile=ctx.profile(part_id),
            poses=tuple(ctx.accepted[part_id]),
            locked=dc._locked_pose(ctx, part_id, ctx.accepted[part_id]),
        ))
    nets = tuple(
        pl.PlacementNet(
            net_id=net.id,
            members=tuple(
                (member.partition(".")[0], member.partition(".")[2])
                for member in net.members
            ),
            cls=net.cls,
        )
        for net in circuit.nets
    )
    relations = tuple(
        pl.PlacementRelation(kind=item.kind, subject=item.subject,
                             object=item.object, reason=item.reason)
        for item in ctx.binding.constraints
    )
    return pl.PlacementInput(
        parts=tuple(parts), nets=nets, relations=relations,
        progress=ctx.progress, lateral=ctx.lateral(),
        page_box=ctx.budget.page_box, keepouts=tuple(ctx.budget.keepouts),
        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
        channel=ctx.budget.channel, lane=ctx.budget.lane,
    )


def _flyback(*, single_module: bool = False) -> tuple[pl.PlacementInput, dc.CompileResult]:
    """The flyback as the document states it — or with `islands` taken off (530F).

    `single_module=True` is `DESIGN` §9.3's fixture swap for 201B: this module
    (`engines/placement.py`) is the **single-module** topology search, and since
    520m made the island path the one a spec with `islands` compiles through
    (`drawcompiler.compile`'s `multi_island`), a test that measures this module
    through the real document no longer measures it at all.  Stripping the
    declaration — not a compiler switch — puts the fixture back on the path the
    assertions are about.
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    if single_module:
        presentation = dataclasses.replace(presentation, islands=None)
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    budget = dc.CompileBudget(max_candidates=64)
    compiled = dc.compile(circuit, presentation, book, budget)
    assert compiled.grammar.ok, [item.detail for item in compiled.grammar.failures]
    ctx = dc._prepare(
        circuit, presentation, compiled.grammar, book, budget
    ).context
    assert ctx is not None
    return _request_from(ctx, circuit, presentation), compiled


@functools.lru_cache(maxsize=1)
def _flyback_placed() -> tuple[pl.PlacementInput, pl.PlacementResult, float]:
    """Run the real search once and share it: the suite pays for it one time."""
    request, _ = _flyback()
    started = time.perf_counter()
    result = pl.place(request)
    return request, result, time.perf_counter() - started


def test_the_flyback_has_no_candidate_today_which_is_why_this_module_exists():
    """先把病情钉住：现编译器对这份输入仍然给 0 候选，但**拦路的换了一层**。

    这条测试是**病历**，不是验收——阶段二把 `_place` 接上之后它会跟着改口径。

    **520A2 重钉**（这份病历的又一次换口径，历史的每一次都写在这里）：

    * 改动前：死因是 **`same-column(Q1, R5)`**——序关系闸。构造阶梯 24 档
      全被它（或同族的关系）拒掉，`_place` 连一个摆放都交不出来。
    * 改动后（520A2，链件可沿**横跨链**的方向 walk）：序关系闸上活下来 2 档
      （`spacing=1 pose-variant=0`、`spacing=1.5 pose-variant=0`），页面往前
      走到**布线**层，死在 `net 'HVDC' … direct-wire obligation`。
    * 再改动后（520E）：布线层也过去了。直连义务连不上时那条网被**降级成名字
      并记账**（岳的裁决：什么时候打标签该由算法反馈决定），2 档于是停在
      **可读性闸**（手搓 loader 下 `13` 条硬违反），`label_fallbacks` 点名
      `HVDC` 与 `SEC_12V`。

    **530F 换夹具（`DESIGN` §9.3）**：这份文档的 `islands[]` 在 520m 之后把
    `compile` 送上了**岛路**，而 201B 的主体 `engines/placement.py` 是
    **单模块**的拓扑搜索——留在岛页上量它，量的是一个这份模块根本没有跑的东西
    （岛路上 `_topology_round` 结构上不点火，`drawcompiler.compile` 的
    `if not multi_island:`）。所以这一条现在把 `islands` **从夹具上剥掉**
    （`_flyback(single_module=True)`），让它回到它声称要量的那条路上。
    **不加编译器开关**：开关等于让产品多一个只为测试存在的分支（§9.3 的原话）。
    剥岛之后本节的历史读数**逐字成立**：0 候选、停在可读性闸、`HVDC`/`SEC_12V`
    被降级点名——201B 的病历一个字不用改。

    所以「0 候选」这个事实没变，变的是**哪一层**把它拒掉。断言按这个新事实写：
    它抓的是「页面又退回关系闸」这种回归，也抓「降级凭空消失」这种回归。
    """
    _, compiled = _flyback(single_module=True)
    assert compiled.ok is False
    assert compiled.candidates == []
    reasons = " ".join(item.detail for item in compiled.failures)
    assert "the independent readability checker refused" in reasons, (
        "the page no longer stops at the relation gate; under 520A2 the refusal "
        "moved one layer forward, to the routing, and under 520E to the "
        "readability gate — if it moved again, say where in this docstring "
        f"rather than leaving the old text: {reasons[:300]}"
    )
    assert [item.net for item in compiled.label_fallbacks] == ["HVDC", "SEC_12V"], (
        "520E's own subject: the nets the router could not join are named and "
        f"recorded, not silently dropped: {[f.net for f in compiled.label_fallbacks]}"
    )
    assert "same-column(Q1, R5)" not in reasons, (
        "the relation the page used to die on is honoured by the placement now; "
        "a refusal that names it again means the chain walk regressed: "
        f"{reasons[:300]}"
    )


def test_the_flyback_is_placed_with_every_relation_kept_and_nothing_hard_broken():
    """反激 19 件 30 条关系：全部关系 0 违反、无重叠、无出页。"""
    request, result, elapsed = _flyback_placed()
    assert len(request.parts) == 19
    assert len(request.relations) >= 30
    assert result.hard == [], [item.render() for item in result.hard]
    misses = [
        item for item in result.costs
        if item.name.startswith("relation:") and item.violated
    ]
    assert misses == [], [item.render() for item in misses]
    assert result.term("relation:same-column(Q1, R5)").value == 0.0
    # 性能：19 件规模单次搜索 < 30 秒（120/121 的 SEARCH_MARGIN 教训）。
    assert elapsed < 30.0, elapsed
    # 每个器件的位姿都必须是它自己合法集里的一档。
    for part in request.parts:
        assert result.poses[part.part_id] in part.poses, part.part_id


def test_every_part_of_the_flyback_is_placed_on_the_lattice():
    """落位全在 5 单位格点上——读图与落图都按这把尺子量。"""
    request, result, _ = _flyback_placed()
    for part_id, (x, y) in sorted(result.origins.items()):
        assert x % request.grid == 0, (part_id, x)
        assert y % request.grid == 0, (part_id, y)


def test_the_repair_move_is_what_makes_the_flyback_drawing_good():
    """修复移动的价值是**量出来的**，不是写在注释里的。

    把 `_repair_delta` 关掉（变异 M2）之后，反激照旧能解出「30 条关系全不违反」
    的图，但图明显更差——实测：走线 2780（有修复 1595）、pin-facing 1091（445）、
    外接框对角 825（478）。可行性来自位姿搜索与平移，**质量**来自修复移动；
    这条把两个读数钉住，注释里那句「修复是质量来源」就不能悄悄失效。
    """
    _, result, _ = _flyback_placed()
    # 阶段二重测（(a) 关系进约束集、旗净空项加入之后）：走线 2170、对角 624.6；
    # 关掉修复移动（变异 M2）实测 3135 / 829.4，而且那份搜索慢得多（6000 迭代
    # 不够收敛到停止条件，单文件用例从 26 s 变 162 s）。界线钉在两者之间：修复
    # 移动的价值是**量出来的**，不是写在注释里的。
    assert result.term("wire-length").value <= 2500.0, (
        result.term("wire-length").render()
    )
    assert result.term("spread").value <= 680.0, result.term("spread").render()


def test_the_transformer_keeps_its_own_pin_split_along_the_chain():
    """T1 的位姿落在它自己的合法集里，且主/副边针尖分居链轴两侧。

    这条是给阶段二留的判据：位姿是搜索变量，但它服务的仍是符号自己的针脚
    几何——T1 的六脚分成左右两列，谁也不能被搜到「主副边混在一起」。
    """
    request, result, _ = _flyback_placed()
    t1 = request.part("T1")
    pose = result.poses["T1"]
    assert pose in t1.poses
    pins = pl._pins_of(request, pl._State(dict(result.origins), dict(result.poses)))
    primary = [pins["T1"][token] for token in ("1", "2", "3")]
    secondary = [pins["T1"][token] for token in ("4", "5", "6")]
    assert (sum(point[0] for point in primary) / 3.0) != (
        sum(point[0] for point in secondary) / 3.0
    ) or (sum(point[1] for point in primary) / 3.0) != (
        sum(point[1] for point in secondary) / 3.0
    )


# ------------------------------------------------------------- §七 代价可解释


def test_every_cost_term_has_a_name_a_value_and_a_reason():
    """052 sec.6：只给原始值和理由，不许只报一个总分。"""
    request, result, _ = _flyback_placed()
    assert result.costs
    for item in result.costs:
        assert item.name
        assert isinstance(item.value, float)
        assert item.detail
        assert isinstance(item.hard, bool)
    payload = result.to_jsonable()
    assert payload["kind"] == pl.PLACEMENT_NAME
    assert len(payload["costs"]) == len(result.costs)
    assert payload["placement"][0]["partId"]
    assert "hardViolations" in payload and "softViolations" in payload


def test_the_weights_are_the_ones_the_module_declares():
    """权重是具名常量，且关系比紧凑度贵——不然搜索会拿拓扑换版面。"""
    assert pl.W_RELATION > pl.W_SPREAD
    assert pl.W_HARD > pl.W_RELATION
    assert pl.W_FACING > 0.0 and pl.W_WIRE > 0.0 and pl.W_SIDE > 0.0


def test_the_energy_function_reads_each_term_through_its_own_weight():
    """`_energy` 逐项加权，没有跨层总分被偷偷加进去。"""
    hard = pl.CostTerm("overlap", 2.0, "重叠", hard=True)
    relation = pl.CostTerm("relation:same-column(Q1, R5)", 3.0, "miss")
    spread = pl.CostTerm("spread", 10.0, "extent")
    assert pl._energy([hard]) == 2.0 * pl.W_HARD
    assert pl._energy([relation]) == 3.0 * pl.W_RELATION
    assert pl._energy([spread]) == 10.0 * pl.W_SPREAD
    assert pl._energy([hard, relation, spread]) == (
        2.0 * pl.W_HARD + 3.0 * pl.W_RELATION + 10.0 * pl.W_SPREAD
    )


# --------------------------------------------------- §八 旗位预留（阶段二）

def _seated_request(reservation: tuple[float, float, float, float]) -> pl.PlacementInput:
    """Two parts 40 units apart, with a flag reservation between them.

    The reservation is stated the way the compiler states it: a box **relative to
    the pin**, covering the lead's run and the glyph + name row the plan will print
    (`drawcompiler._flag_box`). Q1's drain pin is at its own origin, so the box
    lands where the second part is.
    """
    return pl.PlacementInput(
        parts=(
            pl.PlacementPart("Q1", _nmos(), ALL_POSES),
            pl.PlacementPart("R1", _resistor("R0402"), ALL_POSES),
        ),
        nets=(
            pl.PlacementNet("SW", (("Q1", "2"), ("R1", "1"))),
            pl.PlacementNet("VIN", (("Q1", "2"),), cls="power"),
        ),
        flag_seats=(
            pl.FlagReservation(
                part_id="Q1", token="2", net_id="VIN", box=reservation,
            ),
        ),
        progress=(0.0, -1.0), lateral=(1.0, 0.0),
        iterations=4000, restarts=3, seed=201,
    )


def test_a_flag_reservation_is_priced_and_the_search_moves_the_part_out():
    """201B 阶段二：旗位预留项计价，搜索把挡路的件挪开。

    这条钉的是反激最后一个拦路虎的**机制**：编出来的图画到 0 条硬违反之后，
    卡在旗标阶段——`HVDC` 的旗在供电脚 `T1.1` 周围挂不下（`_rail_flag_seat`
    的每一档引线都撞别人）。把那一档"别人"合成到这条最小场景里：预留框正好压在
    第二颗件的位置上。
    """
    reservation = (-20.0, 0.0, 20.0, 55.0)
    request = _seated_request(reservation)
    # 第一次落位时把第二颗件放在预留框里，代价项必须看得见它。
    # The intruder is turned across the reservation: a chip resistor at 0deg has
    # both pins on one vertical line, so its box has no width to intersect with.
    crowded = pl._State(
        origins={"Q1": (0.0, 0.0), "R1": (0.0, 20.0)},
        poses={"Q1": ALL_POSES[0], "R1": SymbolPose(90, False)},
    )
    term = pl._flag_room_term(
        request, pl._pins_of(request, crowded), pl._boxes_of(request, crowded),
    )
    assert term.violated, term.render()
    assert "VIN" in term.detail

    result = pl.place(request)
    reserved = request.flag_seats[0].box_at(result.origins["Q1"])
    pins = pl._pins_of(request, pl._State(dict(result.origins), dict(result.poses)))
    boxes = pl._boxes_of(request, pl._State(dict(result.origins), dict(result.poses)))
    taken = sum(
        pl._boxes_overlap(reserved, box)
        for part_id, box in boxes.items() if part_id != "Q1"
    )
    assert taken == 0.0, (
        f"the search left a part in the flag's room: {reserved} vs {boxes['R1']}"
    )
    assert result.term("flag-room").value == 0.0
    assert pins["Q1"]["2"] is not None


def test_a_request_with_no_flag_seat_reserves_nothing():
    """没声明旗位的请求不评这一项（不是"零违反"，是"不适用"）。"""
    request = pl.PlacementInput(
        parts=(pl.PlacementPart("Q1", _nmos(), ALL_POSES),),
        nets=(pl.PlacementNet("SW", (("Q1", "2"),)),),
        iterations=50, restarts=1, seed=1,
    )
    result = pl.place(request)
    assert result.term("flag-room").value == 0.0
    assert "no flag seat" in result.term("flag-room").detail


# ------------------------------------------ §九 异网 pin 尖间距（pin-clearance）

def _pin_request(**kwargs) -> pl.PlacementInput:
    """两颗两脚电阻，网表可调——钉 pin 尖间距这一项的机制。"""
    base = dict(
        parts=(
            pl.PlacementPart("R1", _resistor("R0603"), ALL_POSES),
            pl.PlacementPart("R2", _resistor("R0603"), ALL_POSES),
        ),
        nets=(
            pl.PlacementNet("A", (("R1", "1"), ("R1", "2"))),
            pl.PlacementNet("B", (("R2", "1"), ("R2", "2"))),
        ),
        progress=(1.0, 0.0), lateral=(0.0, 1.0),
        iterations=20, restarts=1, seed=3,
    )
    base.update(kwargs)
    return pl.PlacementInput(**base)


def test_foreign_pin_tips_closer_than_the_threshold_are_priced():
    """两个**不同网**的针尖挤在同一点：搜索看得见它，并报出是哪两根。

    这是 2026-10-18 实测的那个 bug 的机制：`Q1.3`（SRC）与 `R5.2`（PGND）同在
    (75, 165)。`overlap`/`clearance` 量的是**器件 body**，针尖是 body 边界上的
    一个点，两边都不管——于是这一对在 cost 表里读数是 0，而 router 把外网针尖
    当墙，SRC 的直连义务就此必然被拒。
    """
    request = _pin_request(pin_clearance=True)
    # pin1 在 -20、pin2 在 +20：两颗件原点相距 40 时，R1.2 (20, 0) 与
    # R2.1 (20, 0) 同心 —— 正是要说「不许」的那一种。
    crowded = pl._State(
        origins={"R1": (0.0, 0.0), "R2": (40.0, 0.0)},
        poses={"R1": SymbolPose(0, False), "R2": SymbolPose(0, False)},
    )
    term = pl._pin_clearance_term(request, pl._pins_of(request, crowded))
    assert term.violated, term.render()
    assert "R1.2" in term.detail and "R2.1" in term.detail
    assert "same point" in term.detail
    # 距离 0，所以整整欠一个阈值（grid 5 x PIN_CLEARANCE_GRID 3 = 15）。
    assert term.value == request.grid * pl.PIN_CLEARANCE_GRID


def test_a_foreign_pair_inside_the_threshold_is_priced_by_the_gap():
    """没重合但太近也计——按**欠多少**计，不是二元判定。

    反激落地态的 `Q1.3`/`R5.2` 就是这种：不同点，相距 15，照样是 router
    过不去的那一类。所以这一项必须量距离，不能只在距离为 0 时报警。
    """
    request = _pin_request(pin_clearance=True)
    # 相距 45：R1.2 (25, 0) 与 R2.1 (25, 0) 差 5，阈值 15，欠 10。
    close = pl._State(
        origins={"R1": (0.0, 0.0), "R2": (45.0, 0.0)},
        poses={"R1": SymbolPose(0, False), "R2": SymbolPose(0, False)},
    )
    term = pl._pin_clearance_term(request, pl._pins_of(request, close))
    assert term.value == request.grid * pl.PIN_CLEARANCE_GRID - 5.0, term.render()
    assert "by 5 units" in term.detail


def test_pin_tips_of_one_net_may_share_a_point():
    """同一个网的针尖重合不是短路：两脚件共网是合法电路，不该被推着走。"""
    request = _pin_request(
        nets=(pl.PlacementNet("A", (("R1", "1"), ("R1", "2"),
                                    ("R2", "1"), ("R2", "2"))),),
        pin_clearance=True,
    )
    crowded = pl._State(
        origins={"R1": (0.0, 0.0), "R2": (45.0, 0.0)},
        poses={"R1": SymbolPose(0, False), "R2": SymbolPose(0, False)},
    )
    term = pl._pin_clearance_term(request, pl._pins_of(request, crowded))
    assert term.value == 0.0, term.render()


def test_a_request_that_does_not_ask_has_no_pin_clearance_term():
    """没声明的请求不评这一项（不是「零违反」，是「不适用」）——ladder 逐字等价。"""
    request = _pin_request()
    assert request.pin_clearance is False
    result = pl.place(request)
    assert result.term("pin-clearance") is None


def test_the_energy_prices_the_shortfall_through_its_own_weight():
    """这一项**进了 `_energy`**，而且按 `W_PIN_CLEARANCE` 计价。

    只写 term 函数而忘了加权，cost 表会照旧报数、搜索却不挪——这一条钉的是
    加权本身：同一个 term 值走 `_energy`，乘出来的必须是 `值 × W_PIN_CLEARANCE`
    （`test_the_energy_function_reads_each_term_through_its_own_weight` 已经是这个
    形状，这里只补上本项那一条分支）。
    """
    term = pl.CostTerm("pin-clearance", 15.0, "two foreign tips on one point")
    assert pl._energy([term]) == 15.0 * pl.W_PIN_CLEARANCE
    # 量级：它必须**压过**关系项（短路的代价高于任何美观项），又远低于硬项
    # 的每单位价（硬项是"这不叫一张图"，不是"这图难看"）。
    assert pl.W_PIN_CLEARANCE > pl.W_RELATION
    assert pl.W_PIN_CLEARANCE < pl.W_HARD


def test_the_flybacks_placement_keeps_every_foreign_tip_apart():
    """反激拓扑答案：异网针尖两两满足阈值——本批要修的那个 bug 的行为面。

    这一条用**真三件套**的拓扑请求（`dc._topology_request` 是唯一传
    `pin_clearance=True` 的地方），量的是 2026-10-18 那对 `Q1.3`(SRC) /
    `R5.2`(PGND) 那类重合还在不在。
    """
    request, _ = _flyback()
    request = dc._topology_request(
        dc._prepare(
            CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
            PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
            _flyback()[1].grammar,
            _library_from(SPECS / "flyback_uc3845.library.json"),
            dc.CompileBudget(max_candidates=64),
        ).context
    )
    assert request.pin_clearance is True, "the topology round is what asks for this term"
    result = pl.place(request)
    pins = pl._pins_of(request, pl._State(dict(result.origins), dict(result.poses)))
    net_of: dict[tuple[str, str], str] = {}
    for net in request.nets:
        for owner, pin in net.members:
            net_of.setdefault((owner, pin), net.net_id)
    tips = [
        (owner, pin, point, net_of.get((owner, pin), ""))
        for owner in sorted(pins) for pin in sorted(pins[owner])
        for point in (pins[owner][pin],)
    ]
    threshold = request.grid * pl.PIN_CLEARANCE_GRID
    for index, (a_owner, a_pin, a_point, a_net) in enumerate(tips):
        for b_owner, b_pin, b_point, b_net in tips[index + 1:]:
            if a_owner == b_owner or (a_net and a_net == b_net):
                continue
            gap = math.hypot(a_point[0] - b_point[0], a_point[1] - b_point[1])
            assert gap >= threshold, (
                f"{a_owner}.{a_pin} ({a_net}) and {b_owner}.{b_pin} ({b_net}) "
                f"are {gap:g} apart, threshold {threshold:g}"
            )
    assert result.term("pin-clearance").value == 0.0, result.term("pin-clearance").render()

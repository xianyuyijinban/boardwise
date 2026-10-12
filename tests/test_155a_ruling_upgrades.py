"""Task 155a: 岳 2026-10-11 裁的两条落地——0R 单点**按域对**计，三个阈值升级 WARN.

两处裁定，一处一批：

* **① ``pcb-foc-ground-tie`` 的单点口径改成「每对地域各一颗」**（推翻 2026-10-08
  的「全板恰好一颗」）。判定单位从**板**变成**域对**：``PGND``↔``GND`` 一颗、
  ``PGND``↔``AGND`` 一颗 = 1.0.0 / 1.1.0 两板**双双合规**；一对多颗/非零/铜直连
  只报那一对；一对什么都没有也只报那一对（「要么不连，要么单点」）。
* **② 三个阈值 INFO→WARN**（岳裁：以内 INFO、以外 WARN，数字维持既有建议值）：
  R16 去耦电容距电源脚 200 mil（``rules/pcb/foc.py``）、器件间距 20 mil
  （``pcb-component-spacing``，126——该条**本来就已经是 WARN**，岳只是复议了它）、
  晶振净空外扩 9.84 mil（131f 的 crystal keepout）。**环路口径（poly/bbox）岳没裁，
  维持测量行不动**——本文件把「不动」也钉住。

本文件是**批次的验收锚点**：主锚是真实夹具（毕设FOC 1.0.0 / 1.1.0、ROBOT、药箱、
llc）上的实测读数，合成板只用来钉**边界**（200.0 vs 200.1 mil、19.9 vs 20.0 mil、
同一颗电容的内外两侧）。全部离线，不碰 bridge。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from boardwise.core.geometry import (
    BoardGeometry,
    BoardOutline,
    ComponentPlacement,
    LayerInfo,
    NetGeometry,
    PadGeometry,
    Point,
    StackupEntry,
    TrackSegment,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines.pcbreview import run_pcb_review
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.crystalkeepout import (
    CRYSTAL_KEEPOUT_RULING,
    CRYSTAL_REGION_MARGIN_MIL,
    McuCrystalKeepout,
)
from boardwise.rules.pcb.distance import (
    COMPONENT_SPACING_MIL,
    DECAP_DISTANCE_MIL,
    ComponentSpacing,
)
from boardwise.rules.pcb.foc import FocDecapProximity, TI_DECAP_REFERENCE_MIL
from boardwise.rules.pcb.focground import (
    TIE_PER_PAIR_RULING,
    FocGroundTie,
    bridging_parts_of,
    zero_ohm_resistors_of,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"

R1B = "pcb-foc-ground-tie"
R16 = "pcb-foc-decap-proximity"
KEEP = "pcb-mcu-crystal-keepout"
LOOP = "pcb-foc-power-loop-area"

EMPTY_SHELF = PartLibrary()

_PROJECTS: dict[Path, object] = {}


def _findings(path: Path) -> list:
    """Every finding of a run wired the way production wires it (a project model)."""
    from boardwise.parsers.schematic import build_project_model

    model = _PROJECTS.get(path)
    if model is None:
        model = _PROJECTS[path] = build_project_model(path)
    findings, _section = run_pcb_review(path, model=model)
    return findings


def _rows(path: Path, rule_id: str) -> list:
    return [f for f in _findings(path) if f.rule_id == rule_id]


def _evidence(row) -> str:
    return "\n".join(row.evidence)


# ---------------------------------------------------------------------------
# 一、① 0R 单点 = 每对域一颗（岳 2026-10-11 裁）
# ---------------------------------------------------------------------------


def test_the_two_corrected_boards_are_compliant_on_every_pair():
    """**验收锚点**：1.0.0 与 1.1.0 修正后 = 每对各一颗 0R = 全对合规。

    实测（``run_pcb_review`` 走生产入口，带项目模型）：

    * 毕设FOC 1.0.0 PCB1 — ``R48``（``0R``，``GND``↔``PGND``）与 ``R49``（``0R``，
      ``AGND``↔``PGND``）：**两对、各一颗、两行合规**；另有 ``R31``（``0R``，
      ``+24V``↔``$1N74269``）作为 jumper 单独一行。
    * 毕设FOC 1.1.0 PCB1 — ``R25``（``GND``↔``PGND``）与 ``R11``（``AGND``↔
      ``PGND``）：同样两行合规 + ``R3`` jumper。

    旧口径（2026-10-08「全板恰好一颗」）下这两块板都被报成「not a single point」
    —— 两板各有 2 颗 0R，唯一的差别是**计数单位**。
    """
    for path, ties in ((FOC_100, {"R48", "R49"}), (FOC_110, {"R11", "R25"})):
        rows = [r for r in _rows(path, R1B) if r.board == "PCB1"]
        compliant = [r for r in rows if "每对域恰好一颗 0R — 合规" in r.message]
        assert len(compliant) == 2, (path.name, [r.message[:70] for r in rows])
        assert {r.target.component_ref for r in compliant} == ties, path.name
        assert all(r.severity == "INFO" for r in rows), path.name
        assert not [r for r in rows if "not a single point" in r.message], path.name
        assert not [r for r in rows if "not connected at all" in r.message], path.name
        for row in compliant:
            assert "岳 2026-10-11 裁" in row.message
            blob = _evidence(row)
            assert TIE_PER_PAIR_RULING in blob
            assert "推翻 2026-10-08" in blob

    # PCB2 / PCB3 take the structural branches (no power domain / no logic), and
    # 155a did not move those rows.
    assert len([r for r in _rows(FOC_100, R1B) if r.board == "PCB2"]) == 1
    assert len([r for r in _rows(FOC_110, R1B) if r.board == "PCB2"]) == 1
    assert len([r for r in _rows(FOC_110, R1B) if r.board == "PCB3"]) == 1


def test_the_verdict_of_one_pair_is_independent_of_the_other():
    """**每对域判定彼此独立**：一对合规 + 一对不合规，同一块板各报各的.

    合成板：``PGND`` 对 ``GND`` 是**两颗 0R**（多颗，报账），对 ``AGND`` 是
    **一颗 0R**（合规）。板级计数永远只能给出一个答案；按域对判定则必须同时给出
    「这一对合规」和「那一对不合规」，且互不牵连。
    """
    board, model = _tie_board(
        {
            "PGND": [("R1", "1"), ("R2", "1"), ("R3", "1")],
            "GND": [("R1", "2"), ("R2", "2")],
            "AGND": [("R3", "2")],
        }
    )
    rows = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), EMPTY_SHELF
    )
    compliant = [r for r in rows if "每对域恰好一颗 0R — 合规" in r.message]
    accounts = [r for r in rows if "not a single point" in r.message]
    assert len(compliant) == 1, [r.message[:70] for r in rows]
    assert len(accounts) == 1, [r.message[:70] for r in rows]
    assert "'AGND'" in compliant[0].message and "R3" in compliant[0].message
    assert "'GND'" in accounts[0].message
    assert "2 0 Ω resistor(s)" in accounts[0].message
    assert "R1" in accounts[0].message and "R2" in accounts[0].message
    assert "岳 2026-10-11 裁：**每对域恰好一颗 0R 即合规**；这一对不是。" in (
        accounts[0].message
    ), "the account row says which pair it is about"
    assert compliant[0].target.net_refs == ["PGND", "AGND"] or set(
        compliant[0].target.net_refs
    ) == {"PGND", "AGND"}
    assert set(accounts[0].target.net_refs) == {"PGND", "GND"}
    for row in rows:
        assert row.severity == "INFO"
        assert TIE_PER_PAIR_RULING in _evidence(row)


def test_a_logic_to_logic_bridge_is_not_a_domain_pair_at_all():
    """``GND``↔``AGND`` 是**域内**的连接，不是域对：它进 jumper 行、不进任何一对.

    域对是 R1 自己的枚举——功率侧网 × 逻辑侧网——而 :func:`domain_of` 的两分是
    构造性的，所以 ``GND``↔``AGND``（1.0.0 上 ``U1`` 在逻辑域内把它们连起来）
    根本不是一个域对。一颗 0R 跨这两条网时，它不参与任何一对的计数。
    """
    board, model = _tie_board(
        {
            "PGND": [("R1", "1")],
            "GND": [("R1", "2"), ("R9", "1")],
            "AGND": [("R9", "2")],
        }
    )
    assert {
        p.designator for p in bridging_parts_of(model, EMPTY_SHELF)
    } == {"R1"}, "只有跨功率/逻辑侧的那颗才算桥"
    assert [p.designator for p in zero_ohm_resistors_of(model, EMPTY_SHELF)] == ["R1"]

    rows = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), EMPTY_SHELF
    )
    jumper = [r for r in rows if "not a ground-domain tie" in r.message]
    assert len(jumper) == 1 and jumper[0].target.component_ref == "R9", [
        r.message[:70] for r in rows
    ]
    assert "'GND'" in jumper[0].message and "'AGND'" in jumper[0].message
    assert not [r for r in rows if "not a single point" in r.message], (
        "R9 must not be counted against the PGND↔GND pair either"
    )
    assert len([r for r in rows if "每对域恰好一颗 0R — 合规" in r.message]) == 1


def test_a_pair_joined_by_nothing_reports_itself_and_only_itself():
    """「不连」也是**按域对**报：两对都不连 → 两行，各点各的名字."""
    board, model = _tie_board(
        {
            "PGND": [("C1", "1")],
            "GND": [("U1", "1")],
            "AGND": [("U1", "2")],
        }
    )
    rows = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), EMPTY_SHELF
    )
    lonely = [r for r in rows if "this pair is not connected at all" in r.message]
    assert len(lonely) == 2, [r.message[:70] for r in rows]
    assert {tuple(sorted(r.target.net_refs)) for r in lonely} == {
        ("GND", "PGND"),
        ("AGND", "PGND"),
    }
    for row in lonely:
        assert row.severity == "INFO"
        assert "「要么不连，要么单点」" in row.message
        assert "the other pairs of this board are judged on their own rows" in (
            _evidence(row)
        )


def test_a_pair_whose_only_bridge_is_unreadable_makes_no_pair_claim():
    """UNKNOWN 桥不冒充任何结论：既不是「合规」也不是「不连」.

    合成板上一颗跨域的电阻没写值（``Value`` 空）——它确实把两条网连在一起
    （这是图纸连通性的事实），但它是不是 0R 没人说。按域对判定下这一对的状态
    同样是 UNKNOWN：只出**这一件**的 UNKNOWN 行，不出对级判定。
    """
    board, model = _tie_board({"PGND": [("R7", "1")], "GND": [("R7", "2")]})
    rows = FocGroundTie().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), EMPTY_SHELF
    )
    assert len(rows) == 1, [r.message[:70] for r in rows]
    assert "no readable resistance" in rows[0].message
    assert rows[0].target.component_ref == "R7"
    assert not [r for r in rows if "not connected" in r.message]
    assert not [r for r in rows if "合规" in r.message]


# ---------------------------------------------------------------------------
# 二、② 阈值升级：R16 200 mil（以内 INFO、以外 WARN）
# ---------------------------------------------------------------------------


def test_r16_boundary_is_exactly_the_ruled_two_hundred_mil():
    """边界钉在 **200.0 mil**：等于阈值算「以内」（INFO），200.1 才算超（WARN）.

    岳裁「以内 INFO、以外 WARN」，数字维持 TI §5.3.1 的 0.2 in = 200 mil。合成板
    把同一颗电容摆在 200.0 与 200.1 mil（焊盘 40 宽，中心距 = 间隙 + 40）。
    """
    assert TI_DECAP_REFERENCE_MIL == 200.0

    board, model, shelf = _decap_board(cap_center_x=240.0)  # 240 - 40 = 200.0 mil
    rows = FocDecapProximity().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), shelf
    )
    assert len(rows) == 1, [r.message[:80] for r in rows]
    assert rows[0].target.measurement["value"] == 200.0
    assert rows[0].severity == "INFO", "等于阈值不算超（以内 INFO）"
    assert "以内 INFO" in rows[0].message

    board, model, shelf = _decap_board(cap_center_x=240.1)  # 200.1 mil
    rows = FocDecapProximity().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), shelf
    )
    assert rows[0].target.measurement["value"] == 200.1
    assert rows[0].severity == "WARN"
    assert "以外 WARN" in rows[0].message
    assert "超过" in rows[0].message
    assert "TI SLVA959B §5.3.1 的 0.2 in 建议值" in rows[0].message, (
        "WARN 行同时带实测值与阈值出处"
    )


def test_r16_real_boards_split_by_the_line_and_robot_is_the_outside():
    """真实读数：1.0.0 / 1.1.0 全在以内（INFO），ROBOT 三行超标（WARN）.

    实测 1.0.0 PCB1 ``U10``：83.0 / 170.9 / 92.1 mil；1.1.0 PCB1 ``U2``：
    157.8 / 187.4 / 112.9 mil；ROBOT PCB1 ``DRV1``：``C10``@pin11 596.4、
    ``C10``@pin4 767.3、``C6``@pin4 304.1（超），``C6``@pin11 149.9、
    ``C9``@pin11 44.0、``C9``@pin4 162.3（以内）。
    """
    for path, gaps in (
        (FOC_100, [83.0, 170.9, 92.1]),
        (FOC_110, [157.8, 187.4, 112.9]),
    ):
        rows = _rows(path, R16)
        assert sorted(r.target.measurement["value"] for r in rows) == sorted(gaps)
        assert all(r.severity == "INFO" for r in rows), path.name

    robot = _rows(ROBOT, R16)
    assert sorted(
        r.target.measurement["value"] for r in robot if r.severity == "WARN"
    ) == [304.1, 596.4, 767.3]
    assert sorted(
        r.target.measurement["value"] for r in robot if r.severity == "INFO"
    ) == [44.0, 149.9, 162.3]


def test_only_the_ruled_foc_figure_is_compared_and_the_loop_stays_a_measurement():
    """R20（环路口径）**维持测量行不动**：岳没裁，一行都不许升级.

    同时钉住整个 foc 模块里被比较的常量只有 R16 那一个——用 AST 读比较式，不靠
    文本正则（证据串里就有「>= {TI_GATE_WIDTH_REFERENCE_MIL} mil」这句话，文本
    搜索分不清引文与判定）。
    """
    from boardwise.rules.pcb import foc

    source = inspect.getsource(foc)
    compared: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare):
            for side in (node.left, *node.comparators):
                for sub in ast.walk(side):
                    if isinstance(sub, ast.Name):
                        compared.add(sub.id)
    assert "TI_DECAP_REFERENCE_MIL" in compared
    assert "TI_GATE_WIDTH_REFERENCE_MIL" not in compared

    seen_loop_rows = 0
    for path in (FOC_100, FOC_110, LLC):
        for row in _rows(path, LOOP):
            seen_loop_rows += 1
            assert row.severity == "INFO", (path.name, row.message[:80])
            assert "口径" in row.message, "both 口径 are still reported side by side"
    assert seen_loop_rows, "R20 fires on the boards that place a bulk cap + FET pair"
    assert "岳" in foc.FocPowerLoopArea.source


# ---------------------------------------------------------------------------
# 三、② 阈值升级：器件间距 20 mil（126 的 ``pcb-component-spacing``）
# ---------------------------------------------------------------------------


def test_component_spacing_is_graded_at_twenty_mil_and_the_number_is_kept():
    """19.9 mil → WARN；20.0 mil → 无行.

    这条阈值在 155a 之前就已是 WARN，岳 2026-10-11 只是复议了它——所以本测试钉的
    是「数字没动、方向没变」，与 R16/净空两条**新升级**的区别写在这里。
    """
    assert COMPONENT_SPACING_MIL == 20.0

    board = _spacing_board(gap=19.9)
    rows = ComponentSpacing().check(PcbReviewContext(board=board))
    assert len(rows) == 1
    assert rows[0].severity == "WARN"
    assert rows[0].target.measurement == {
        "kind": "distance", "value": 19.9, "unit": "mil",
    }
    assert "under the 20 mil house rule" in rows[0].message

    board = _spacing_board(gap=20.0)
    assert ComponentSpacing().check(PcbReviewContext(board=board)) == []


def test_the_two_distance_constants_carry_the_2026_10_11_ruling():
    """出处标记：岳裁写进三个常量所在处的注释（常量集中处都要标）.

    ``inspect.getdoc`` does not help here — these are **floats**, so it would
    return ``float``'s own docstring. The check is on the module source: 岳's
    ruling must appear just above each constant's assignment.
    """
    from boardwise.rules.pcb import distance

    lines = inspect.getsource(distance).splitlines()
    for name in ("DECAP_DISTANCE_MIL", "COMPONENT_SPACING_MIL"):
        index = next(
            i for i, line in enumerate(lines) if line.startswith(f"{name} = ")
        )
        window = "\n".join(lines[max(0, index - 30):index])
        assert "岳" in window and "2026-10-11" in window, name
    assert DECAP_DISTANCE_MIL == 200.0
    assert COMPONENT_SPACING_MIL == 20.0

    crystal = inspect.getsource(
        __import__(
            "boardwise.rules.pcb.crystalkeepout", fromlist=["x"]
        )
    )
    assert "岳 2026-10-11 裁" in crystal
    keepout_lines = crystal.splitlines()
    index = next(
        i for i, line in enumerate(keepout_lines)
        if line.startswith("CRYSTAL_REGION_MARGIN_MIL = ")
    )
    assert "2026-10-11" in "\n".join(keepout_lines[max(0, index - 25):index])


# ---------------------------------------------------------------------------
# 四、② 阈值升级：晶振净空 9.84 mil 外扩（131f 的 crystal keepout）
# ---------------------------------------------------------------------------


def test_keepout_warns_on_foreign_net_copper_and_names_it():
    """**验收锚点**：1.0.0 底层的 ``AGND`` 铺铜、1.1.0 底层的 ``IA+``/``IB+`` 走线.

    实测（区域内、非晶振自身网；晶振自身网 = 其焊盘所在网 ``OSC-IN`` /
    ``OSC-OUT`` / ``GND``）：

    * 1.0.0 PCB1 ``X1`` @ Bottom Layer — ``pour ["POURED","e3b26ff04e3d6300"] @
      AGND`` → **WARN**（131f 起就量到的那块板）；
    * 1.1.0 PCB1 ``X1`` @ Bottom Layer — ``track 2bbdb921d0bf3fc9 @ IA+`` 与
      ``track dfbd69b2b06ce1d5 @ IB+``（相电流采样对走在晶振底下）→ **WARN**；
    * 其余层（晶振自身焊盘/走线、``GND`` 缝合过孔、空层）→ **INFO**。
    """
    assert CRYSTAL_REGION_MARGIN_MIL == 9.84
    assert "别网铜" in CRYSTAL_KEEPOUT_RULING and "9.84 mil" in CRYSTAL_KEEPOUT_RULING

    foc100 = _rows(FOC_100, KEEP)
    warn = [r for r in foc100 if r.severity == "WARN"]
    assert len(warn) == 1 and "Bottom Layer" in warn[0].message
    assert "AGND" in warn[0].message and "别网铜" in warn[0].message
    assert "以外 WARN" in warn[0].message
    assert [r.severity for r in foc100 if r is not warn[0]] == ["INFO", "INFO", "INFO"]

    foc110 = _rows(FOC_110, KEEP)
    warn = [r for r in foc110 if r.severity == "WARN"]
    assert len(warn) == 1 and "Bottom Layer" in warn[0].message
    assert "IA+" in warn[0].message and "IB+" in warn[0].message
    assert "别网铜" in warn[0].message

    # ROBOT (only its own-net copper) and 药箱 (its own GND pour) stay INFO.
    for path in (ROBOT, PILLBOX):
        assert all(r.severity == "INFO" for r in _rows(path, KEEP)), path.name
    assert _rows(LLC, KEEP) == []


def test_keepout_grades_the_net_not_the_presence_of_copper():
    """「以内/以外」的量是**网**，不是「区域里有没有铜」.

    真实读数就是这条读数的最好证明：1.0.0 ``X1`` 的 **Top Layer 行有 18 件铜**
    （4 个自身焊盘 + 14 条自身网走线）而仍是 **INFO**；**Bottom Layer 行只有 4 件**
    却因为其中一件是 ``AGND`` 铺铜而 **WARN**。若按「有铜就 WARN」读，晶振自己的
    引出线会被指控——那是每个晶振都中招的假阳性。

    合成板把变量隔离到只剩一条：区域内放一条自身网走线（``OSC-IN``）与一条别网
    走线（``OTHERNET``）时升级、只放自身网那条时不升级。
    """
    top = next(r for r in _rows(FOC_100, KEEP) if "Top Layer" in r.message)
    bottom = next(r for r in _rows(FOC_100, KEEP) if "Bottom Layer" in r.message)
    assert "carries **18** copper element(s)" in top.message
    assert "carries **4** copper element(s)" in bottom.message
    assert (top.severity, bottom.severity) == ("INFO", "WARN"), (
        "more copper on Top (all of it the crystal's own) yet Top is the quiet one "
        "— the grading is by net, not by element count"
    )
    assert "GND" in top.message, "the Top row's copper is on the crystal's own nets"

    board, model, shelf = _keepout_board(foreign=True)
    rows = McuCrystalKeepout().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), shelf
    )
    assert len(rows) == 2, [r.message[:80] for r in rows]  # one row per copper layer
    carrier = next(r for r in rows if "OTHERNET" in r.message)
    assert carrier.severity == "WARN", [r.message[:90] for r in rows]
    assert "OSC-IN" not in carrier.message.split("**WARN**")[-1], (
        "the crystal's own trace must not be listed as foreign"
    )

    board, model, shelf = _keepout_board(foreign=False)
    rows = McuCrystalKeepout().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), shelf
    )
    assert len(rows) == 2, [r.message[:80] for r in rows]
    assert all(r.severity == "INFO" for r in rows)
    carrier = next(r for r in rows if "OSC-IN" in r.message)
    assert "区内没有别网铜" in carrier.message
    assert "以内 INFO" in carrier.message
    assert "岳 2026-10-11 裁" in _evidence(carrier)


# ---------------------------------------------------------------------------
# helpers — synthetic boards (only for the boundaries no fixture reaches)
# ---------------------------------------------------------------------------


def _stackup() -> list[StackupEntry]:
    return [
        StackupEntry(layer_id=1, z_index=1000, material="copper", thickness=1.378),
        StackupEntry(layer_id=362, z_index=1001, material="FR4", thickness=12.0),
        StackupEntry(layer_id=2, z_index=9000, material="copper", thickness=1.378),
    ]


def _two_layer() -> dict[int, LayerInfo]:
    return {
        1: LayerInfo(layer_id=1, name="L1", layer_type="TOP"),
        2: LayerInfo(layer_id=2, name="L2", layer_type="BOTTOM"),
    }


def _model_with(parts: dict[str, tuple[str, list[tuple[str, str, str]]]]):
    """``{designator: (value, [(pin, name, net)])}`` → a netlist view.

    ``Net.pins`` is built as ``(designator, pin number)`` pairs accumulated over
    **every** component on the net — that is the shape
    :func:`boardwise.rules.decap.cap_candidates_on` and 131d's oscillator walk
    read, and a net that only carries the last component that mentioned it would
    silently answer 「nobody is on this net」 to both.
    """
    nets: dict[str, list[tuple[str, str]]] = {}
    components: dict[str, Component] = {}
    for designator, (value, pins) in sorted(parts.items()):
        pin_objects = []
        for number, name, net_name in pins:
            pin_objects.append(Pin(number=number, name=name, net=net_name))
            nets.setdefault(net_name, []).append((designator, number))
        components[designator] = Component(
            uid=designator,
            designator=designator,
            value=value,
            mpn=designator,
            pins=pin_objects,
        )
    return DesignModel(
        components=components,
        nets={name: Net(name=name, pins=entries) for name, entries in nets.items()},
    )


def _shelf(**categories: str) -> PartLibrary:
    """A shelf whose entries are keyed/MPN'd exactly like the synthetic parts."""
    return PartLibrary(
        parts=[
            PartEntry(key=designator, mpn=designator, category=category)
            for designator, category in sorted(categories.items())
        ]
    )


#: Designators whose value is deliberately **not stated** (UNKNOWN, not zero).
_UNVALUED = {"R7", "U1", "C1", "C9"}


def _tie_board(nets: dict[str, list[tuple[str, str]]]):
    """A two-layer board whose pads follow ``{net: [(designator, pin)]}``.

    Every part is a **0 Ω resistor** unless it appears in ``_UNVALUED``; the pins
    land on the nets the caller states, so the structural pool sees exactly the
    topology the test describes. Pads are laid out on separate rows and every net
    gets one short track in a band of its own, so no two nets' copper can touch by
    accident — which would silently answer the copper-contact question these tests
    are not asking.
    """
    pads: list[PadGeometry] = []
    tracks: list[TrackSegment] = []
    per_net: dict[str, tuple[list[PadGeometry], list[TrackSegment]]] = {
        net: ([], []) for net in nets
    }
    index = 0
    for net, entries in nets.items():
        net_pads, net_tracks = per_net[net]
        for designator, pin in entries:
            index += 1
            pad = PadGeometry(
                id=f"{designator}-{pin}",
                component=designator,
                pin_number=pin,
                net=net,
                layer_id=1,
                effective_layer_ids=[1],
                x=200.0 * index,
                y=100000.0 + 400.0 * index,
                width=60.0,
                height=60.0,
                shape="rect",
            )
            pads.append(pad)
            net_pads.append(pad)
        band = 500.0 * list(nets).index(net)
        index += 1
        track = TrackSegment(
            id=f"T{index}",
            net=net,
            layer_id=1,
            start=Point(0.0, band),
            end=Point(2000.0, band),
            width=10.0,
        )
        tracks.append(track)
        net_tracks.append(track)

    designators = sorted({d for entries in nets.values() for d, _p in entries})
    board = BoardGeometry(
        name="TIE_SYNTH",
        layers=_two_layer(),
        stackup=_stackup(),
        components=[
            ComponentPlacement(
                id=des, designator=des, x=200.0 * i, y=100000.0, angle=0.0, layer_id=1
            )
            for i, des in enumerate(designators, start=1)
        ],
        pads=pads,
        tracks=tracks,
        vias=[],
        pours=[],
        outline=None,
        nets={
            net: NetGeometry(name=net, pads=net_pads, tracks=net_tracks)
            for net, (net_pads, net_tracks) in per_net.items()
        },
    )
    model = _model_with(
        {
            des: (
                "" if des in _UNVALUED else "0R",
                [
                    (pin, pin, net)
                    for net, entries in nets.items()
                    for d, pin in entries
                    if d == des
                ],
            )
            for des in designators
        }
    )
    return board, model


def _decap_board(cap_center_x: float):
    """A motor driver with one supply pin and one bypass capacitor at a chosen gap.

    Pads are 40 mil wide, so a capacitor centred at ``cap_center_x`` against the
    driver's pad at 0 has an edge-to-edge gap of ``cap_center_x - 40`` mil. The
    driver is a motor driver through the **shelf category** — the only door this
    rule opens — so the shelf travels with the board.
    """
    pads = [
        PadGeometry(
            id="U1-1", component="U1", pin_number="1", net="VM", layer_id=1,
            effective_layer_ids=[1], x=0.0, y=0.0, width=40.0, height=40.0,
            shape="rect",
        ),
        PadGeometry(
            id="C1-1", component="C1", pin_number="1", net="VM", layer_id=1,
            effective_layer_ids=[1], x=cap_center_x, y=0.0, width=40.0,
            height=40.0, shape="rect",
        ),
        PadGeometry(
            id="C1-2", component="C1", pin_number="2", net="GND", layer_id=1,
            effective_layer_ids=[1], x=cap_center_x, y=200.0, width=40.0,
            height=40.0, shape="rect",
        ),
    ]
    board = BoardGeometry(
        name="DECAP_SYNTH",
        layers=_two_layer(),
        stackup=_stackup(),
        components=[
            ComponentPlacement(id="U1", designator="U1", x=0.0, y=0.0, layer_id=1),
            ComponentPlacement(
                id="C1", designator="C1", x=cap_center_x, y=0.0, layer_id=1
            ),
        ],
        pads=pads,
        tracks=[],
        vias=[],
        pours=[],
        outline=None,
        nets={
            "VM": NetGeometry(name="VM", pads=[pads[0], pads[1]], tracks=[]),
            "GND": NetGeometry(name="GND", pads=[pads[2]], tracks=[]),
        },
    )
    model = _model_with(
        {
            "U1": ("", [("1", "VM", "VM")]),
            "C1": ("100nF", [("1", "1", "VM"), ("2", "2", "GND")]),
        }
    )
    return board, model, _shelf(U1="ic.motor-driver")


def _spacing_board(gap: float) -> BoardGeometry:
    """Two 40-mil pads whose edge-to-edge gap is exactly ``gap`` mil."""
    offset = 40.0 + gap
    pads = [
        PadGeometry(
            id="R1.1", component="R1", pin_number="1", net="N1", layer_id=1,
            effective_layer_ids=[1], x=0.0, y=0.0, width=40.0, height=40.0,
            shape="rect",
        ),
        PadGeometry(
            id="R2.1", component="R2", pin_number="1", net="N2", layer_id=1,
            effective_layer_ids=[1], x=offset, y=0.0, width=40.0, height=40.0,
            shape="rect",
        ),
    ]
    return BoardGeometry(
        name="SPACING_SYNTH",
        layers={1: LayerInfo(layer_id=1, name="L1", layer_type="TOP")},
        stackup=_stackup(),
        components=[
            ComponentPlacement(id="R1", designator="R1", x=0.0, y=0.0, layer_id=1),
            ComponentPlacement(
                id="R2", designator="R2", x=offset, y=0.0, layer_id=1
            ),
        ],
        pads=pads,
        tracks=[],
        vias=[],
        pours=[],
        outline=BoardOutline(
            points=[
                Point(-500.0, -500.0), Point(5000.0, -500.0),
                Point(5000.0, 500.0), Point(-500.0, 500.0),
            ]
        ),
        nets={
            "N1": NetGeometry(name="N1", pads=[pads[0]], tracks=[]),
            "N2": NetGeometry(name="N2", pads=[pads[1]], tracks=[]),
        },
    )


def _keepout_board(*, foreign: bool):
    """A crystal whose region carries its **own** trace, plus optionally a foreign one.

    The MCU is ``U1`` (shelf ``ic.mcu``, pins named ``OSC_IN`` / ``OSC_OUT``) and
    the crystal is ``X1`` (value ``16MHz``) — both found by 131d's own sieves, so
    the synthetic board reaches the rule the way a real one does. A trace on
    ``OSC-IN`` inside the region is 「以内」; a trace on ``OTHERNET`` is 「以外」.
    """
    pads = [
        PadGeometry(
            id="X1.1", component="X1", pin_number="1", net="OSC-IN", layer_id=1,
            effective_layer_ids=[1], x=0.0, y=0.0, width=30.0, height=30.0,
            shape="rect",
        ),
        PadGeometry(
            id="X1.2", component="X1", pin_number="2", net="OSC-OUT", layer_id=1,
            effective_layer_ids=[1], x=100.0, y=0.0, width=30.0, height=30.0,
            shape="rect",
        ),
    ]
    tracks = [
        TrackSegment(
            id="OWN_TRACK", net="OSC-IN", layer_id=1,
            start=Point(-20.0, 0.0), end=Point(-55.0, 0.0), width=8.0,
        ),
    ]
    nets = {
        "OSC-IN": NetGeometry(name="OSC-IN", pads=[pads[0]], tracks=[tracks[0]]),
        "OSC-OUT": NetGeometry(name="OSC-OUT", pads=[pads[1]], tracks=[]),
    }
    if foreign:
        tracks.append(
            TrackSegment(
                id="FOREIGN_TRACK", net="OTHERNET", layer_id=1,
                start=Point(0.0, 10.0), end=Point(110.0, 10.0), width=8.0,
            )
        )
        nets["OTHERNET"] = NetGeometry(name="OTHERNET", pads=[], tracks=[tracks[1]])
    board = BoardGeometry(
        name="KEEPOUT_SYNTH",
        layers=_two_layer(),
        stackup=_stackup(),
        components=[
            ComponentPlacement(id="X1", designator="X1", x=0.0, y=0.0, layer_id=1)
        ],
        pads=pads,
        tracks=tracks,
        vias=[],
        pours=[],
        outline=None,
        nets=nets,
    )
    model = _model_with(
        {
            "U1": (
                "",
                [("1", "OSC_IN", "OSC-IN"), ("2", "OSC_OUT", "OSC-OUT")],
            ),
            "X1": ("16MHz", [("1", "1", "OSC-IN"), ("2", "2", "OSC-OUT")]),
        }
    )
    return board, model, _shelf(U1="ic.mcu")

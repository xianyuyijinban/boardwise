"""任务 172：丝印字宽改走宿主实测 bbox——实测优先、估算降级、两态可区分。

岳 2026-10-11 裁：「丝印字宽改走宿主渲染 bbox（参考 easyeda-agent）：**实测不
估算、测不到就诚实降级**」，估宽档退役为**降级路径**而不是判定基准。

本批落地的东西分三层，测试也按层钉：

* **规则层**（``rules/pcb/silk.py``）——:class:`SilkDesignator` 收一个
  ``measured`` 映射（键 ``(板名, 位号文字)``），给了就用读数、不给就用那条
  字宽比带。两态在 evidence 里**逐条**带字样：「实测（宿主 primitive bbox）」
  与「估算值（字宽比带，非读数）」——报告里不允许出现一个看起来像读数的估算数；
* **接线层**（``cli.py``）——在线 ``project-file`` 档上试一次宿主实测
  （``doc.list`` → 在线档里取位号 ATTR 记录 id → bbox 动作
  ``pcb.geometry --bboxIds``，174 之前这里写的是 ``sch.geometry``——见
  ``cli.SILK_BBOX_ACTION`` 的注），成了就把内置规则表的丝印一条换成带实测盒的
  实例；不成就返回空表 + 一条 ``notes``。**降级永远明说**；
* **真机层**——test 工程窗口不在就 skip（不硬依赖）。2026-10-12 实测：这块板
  （``test``/``PCB1``）是空板，没有可测的位号，所以真机端到端演示缺席，原因见
  ``outputs/172/evidence.md``。

本文件全部离线可测：假宿主（一个 ``async call``）＋假实测盒；只有最后一个
真机探针会连桥，且窗口不在就 skip。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise import cli as cli_module
from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    PadGeometry,
    SilkText,
)
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES
from boardwise.parsers.epru import load_epro2_source
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.silk import (
    ESTIMATED_WIDTH,
    MEASURED_WIDTH,
    WIDTH_SOURCE_LABEL,
    SilkDesignator,
    measured_corners,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"

#: 岳 2026-10-12 给的 test 工程（任务书点名）。真机探针只碰这一个。
#: 按**工程名**路由（`--project`），不硬编码窗口 instance id：任何一次
#: 热更/reload 后 instance id 都会变（2026-10-12 实测 0.4.29→0.4.30 后
#: inst-110614866-3i116ex4 已不存在），硬编码只会让探针假 skip。test 工程
#: 只有一个窗口开着，按名路由无歧义。
TEST_PROJECT = "test"


# ---------------------------------------------------------------------------
# helpers — 合成板与假实测（全部离线）
# ---------------------------------------------------------------------------


def _silk_text(
    component: str,
    text: str,
    x: float,
    y: float,
    *,
    angle: float = 0.0,
    layer_kind: str = "TOP_SILK",
    layer_id: int = 3,
    font_size: float = 45.0,
    visible: bool = True,
) -> SilkText:
    return SilkText(
        component=component,
        component_id=f"c-{component}",
        text=text,
        source="designator",
        x=x,
        y=y,
        local_x=x,
        local_y=y,
        angle=angle,
        stored_angle=angle,
        layer_id=layer_id,
        layer_kind=layer_kind,
        font_size=font_size,
        stroke_width=6.0,
        origin="LEFT_BOTTOM",
        visible=visible,
    )


def _pad(component: str, pin: str, *, at: tuple[float, float],
         width: float = 40.0, height: float = 40.0) -> PadGeometry:
    return PadGeometry(
        id=f"{component}.{pin}", component=component, component_id=f"c-{component}",
        pin_number=pin, net="", layer_id=1, effective_layer_ids=[1],
        x=at[0], y=at[1], local_x=at[0], local_y=at[1],
        width=width, height=height, shape="RECT", angle=0.0,
    )


def _board(texts, pads=None, *, name="PCB1") -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name=name,
        components=[
            ComponentPlacement(id=f"c-{t.component}", designator=t.component, layer_id=1)
            for t in texts
        ],
        pads=list(pads or []),
        silk_shapes=[],
        silk_texts=list(texts),
    )


def _ctx(board, title=None) -> PcbReviewContext:
    return PcbReviewContext(board=board, board_title=title or board.name or "PCB1")


def _silk_findings(rule, board, title=None):
    return [f for f in rule.check(_ctx(board, title)) if f.rule_id == rule.id]


#: 一条 2.4 mil 宽的假实测盒，横跨 ``(-20, -10) – (-18.4, -8)``……不，是一条
#: **4×4 mil** 的读数：这样「估算法三档都不相交、实测盒相交」和反向两种状态都能
#: 用同一批数字摆出来，不用为每个态重算几何。
def _box(min_x, min_y, max_x, max_y):
    return (min_x, min_y, max_x, max_y)


# ---------------------------------------------------------------------------
# 1. 两态：实测读数取代整条估算带
# ---------------------------------------------------------------------------


def test_a_measured_box_decides_the_overlap_on_its_own():
    """实测盒相交就报 WARN，且 message/evidence 说的是「实测」不是「估算」。

    这条位号摆在**只有最宽档才压上**的位置（锚点 ``x=-100``，宽 2 字符 × fontSize 45：
    0.4 档到 ``x=-64``、0.6 档到 ``x=-46``，都够不到 ``x=-40`` 的焊盘边；0.8 档到
    ``x=-28``，压进 12 mil），所以估算法只出测量行、一条 WARN 都没有；给一个盖住
    焊盘的实测盒则立刻 WARN。
    """
    board = _board(
        [_silk_text("R1", "R1", -100.0, 0.0)],
        [_pad("R1", "1", at=(-20.0, 0.0))],
    )
    estimated = _silk_findings(SilkDesignator(), board)
    assert [f for f in estimated if f.severity == "WARN"] == []
    assert "宽字形模型下" in " ".join(f.message for f in estimated)

    measured = _silk_findings(
        SilkDesignator(measured={("PCB1", "R1"): _box(-100.0, 0.0, -30.0, 45.0)}),
        board,
    )
    warns = [f for f in measured if f.severity == "WARN"]
    assert len(warns) == 1
    assert warns[0].message.startswith("PCB1 R1 的位号丝印压在焊盘上")
    assert "宿主实测的文字盒就直接相交" in warns[0].message
    assert "最窄字宽档" not in warns[0].message
    assert any(
        line.startswith("R1 pin 1: 叠加深度（") and "实测 → " in line
        for line in warns[0].evidence
    )
    assert any(WIDTH_SOURCE_LABEL[MEASURED_WIDTH] in line for line in warns[0].evidence)
    # 那条「只有宽字形模型才压上」的估算汇总行必须消失——读数面前那条带没有信息量
    assert [f for f in measured if "宽字形模型下" in f.message] == []


def test_the_estimated_state_marks_itself_as_an_estimate_everywhere():
    """估算那一态**每条带数字的 evidence 都要出现「估算值」**。

    这是本批的要害：报告里不许出现一个看起来像读数、其实是模型描出来的数。
    """
    board = _board(
        [_silk_text("C1", "C1", -70.0, 0.0), _silk_text("R9", "R9", -20.0, 0.0)],
        [_pad("R1", "1", at=(0.0, 0.0))],
    )
    findings = _silk_findings(SilkDesignator(), board)
    assert findings
    for finding in findings:
        for line in finding.evidence:
            # 只说**宽度**那种数字：位号记录行里的 fontSize 是文件读数，
            # 阻焊开窗那行是规则读数——它们不是估出来的宽度。
            if "字宽比" in line or "宽度" in line:
                assert "估算值" in line, line

    warn = [f for f in findings if f.severity == "WARN"][0]  # R9 压上了
    assert any(WIDTH_SOURCE_LABEL[ESTIMATED_WIDTH] in line for line in warn.evidence)
    assert WIDTH_SOURCE_LABEL[MEASURED_WIDTH] not in "\n".join(warn.evidence)


def test_the_summary_counts_measured_against_estimated():
    """小结行把两态的盘账报出来：几个实测、几个估算。"""
    board = _board(
        [_silk_text("C1", "C1", 0.0, 0.0), _silk_text("C2", "C2", 200.0, 0.0)],
        [_pad("R1", "1", at=(-100.0, 0.0))],
    )
    none = [f for f in _silk_findings(SilkDesignator(), board) if f.message.startswith("PCB1 丝印读数")]
    assert len(none) == 1
    assert "文字宽度：" in none[0].message
    assert f"{WIDTH_SOURCE_LABEL[MEASURED_WIDTH]} 0 个" in none[0].message
    assert f"{WIDTH_SOURCE_LABEL[ESTIMATED_WIDTH]} 2 个" in none[0].message
    assert any("降级是明说的" in line for line in none[0].evidence)

    one = [
        f for f in _silk_findings(
            SilkDesignator(measured={("PCB1", "C1"): _box(0.0, 0.0, 90.0, 45.0)}), board
        )
        if f.message.startswith("PCB1 丝印读数")
    ]
    assert f"{WIDTH_SOURCE_LABEL[MEASURED_WIDTH]} 1 个" in one[0].message
    assert f"{WIDTH_SOURCE_LABEL[ESTIMATED_WIDTH]} 1 个" in one[0].message


def test_the_summary_says_no_object_when_the_board_has_no_designator():
    """空板（2026-10-12 真机 `test`/`PCB1` 就是这一态）：两个 0 是「没有对象」，
    不是「测了没测到」——这句话必须能分清，否则降级句会误导读者。"""
    board = _board([], [])
    findings = _silk_findings(
        SilkDesignator(measured={("PCB1", "C1"): _box(0.0, 0.0, 10.0, 10.0)}), board
    )
    summary = [f for f in findings if f.message.startswith("PCB1 丝印读数")]
    assert len(summary) == 1
    assert f"{WIDTH_SOURCE_LABEL[MEASURED_WIDTH]} 0 个" in summary[0].message
    assert any("没有可读的位号丝印" in line for line in summary[0].evidence)


def test_a_measurement_keyed_to_another_board_is_never_applied():
    """实测盒按 ``(板名, 位号)`` 分键：A 板的读数不许贴到 B 板的几何上。

    同一个工程里 ``C1`` 在每块板上各有一份，按位号文字单键就会串板——这条钉的是
    那个键的形状。
    """
    board = _board(
        [_silk_text("C1", "C1", -70.0, 0.0)],
        [_pad("R1", "1", at=(0.0, 0.0))],
        name="PCB2",
    )
    findings = _silk_findings(
        SilkDesignator(measured={("PCB1", "C1"): _box(-70.0, 0.0, 10.0, 45.0)}),
        board,
    )
    assert [f for f in findings if f.severity == "WARN"] == []
    assert "宽字形模型下" in " ".join(f.message for f in findings)


def test_the_covered_check_uses_the_measured_box_too():
    """「被本体压住」也吃宽度，所以同样实测优先——而且两条路给的结论相反。

    本体轮廓是个 ``x ∈ [-40, 40], y ∈ [-20, 20]`` 的方框；位号锚在
    ``(-30, -30)``、字号 45，估算法最宽档得到 ``x ∈ [-30, 105]、y ∈ [-30, 15]``，
    四角不都在框里（只有左下那一角不进去？不——它其实 2/4 角在内），所以估算法
    只出「部分」测量行；一个整条落进框内的实测盒则报「完全压住」的 WARN。
    """
    from boardwise.core.geometry import SilkShape
    from boardwise.core.geometry import Point

    board = _board([_silk_text("C3", "C3", -30.0, -30.0)], [])
    board.silk_shapes = [
        SilkShape(
            id="U8-body", component="U8", component_id="c-U8", kind="poly",
            layer_id=48, layer_kind="COMPONENT_SHAPE",
            points=[Point(-40.0, -20.0), Point(40.0, -20.0),
                    Point(40.0, 20.0), Point(-40.0, 20.0)],
            local_points=[Point(-40.0, -20.0), Point(40.0, -20.0),
                          Point(40.0, 20.0), Point(-40.0, 20.0)],
        )
    ]
    board.components.append(ComponentPlacement(id="c-U8", designator="U8", layer_id=1))

    estimated = _silk_findings(SilkDesignator(), board)
    assert [f for f in estimated if "完全压住" in f.message] == []
    partial = [f for f in estimated if "部分" in f.message]
    assert partial and "（宽度估算值）" in partial[0].evidence[0]

    measured = _silk_findings(
        SilkDesignator(measured={("PCB1", "C3"): _box(-35.0, -15.0, -5.0, 5.0)}),
        board,
    )
    covered = [f for f in measured if "完全压住" in f.message]
    assert len(covered) == 1
    assert any(WIDTH_SOURCE_LABEL[MEASURED_WIDTH] in line for line in covered[0].evidence)
    assert [f for f in measured if "部分" in f.message] == []


def test_an_oblique_measured_box_says_it_is_the_axis_aligned_superset():
    """斜置位号的实测盒是宿主给的**轴对齐**外接矩形——报告要说出来。"""
    board = _board(
        [_silk_text("SCREW1", "SCREW1", 0.0, 0.0, angle=34.0)],
        [_pad("R1", "1", at=(10.0, 10.0))],
    )
    findings = _silk_findings(
        SilkDesignator(measured={("PCB1", "SCREW1"): _box(0.0, 0.0, 40.0, 40.0)}),
        board,
    )
    warn = [f for f in findings if f.severity == "WARN"][0]
    note = "\n".join(warn.evidence)
    assert "轴对齐" in note and "外接矩形" in note and "34" in note

    # 正置位号不该带那句废话：0°/90° 上位矩形就是文字盒
    upright = _board(
        [_silk_text("R1", "R1", 0.0, 0.0, angle=90.0)],
        [_pad("R2", "1", at=(10.0, 10.0))],
    )
    findings = _silk_findings(
        SilkDesignator(measured={("PCB1", "R1"): _box(0.0, 0.0, 40.0, 40.0)}),
        upright,
    )
    warn = [f for f in findings if f.severity == "WARN"][0]
    assert "外接矩形" not in "\n".join(warn.evidence)


def test_measured_corners_takes_both_shapes_and_refuses_junk():
    """``measured_corners`` 收宿主原样的四元组，也收四个点；形状不对就炸。

    「读不懂的实测盒」必须当场失败，绝不能悄悄退化成估算——那正是本批要消灭的混同。
    """
    four = measured_corners((1.0, 2.0, 5.0, 8.0))
    assert [(p.x, p.y) for p in four] == [(1.0, 2.0), (5.0, 2.0), (5.0, 8.0), (1.0, 8.0)]
    points = measured_corners([(1, 2), (5, 2), (5, 8), (1, 8)])
    assert [(p.x, p.y) for p in points] == [(1.0, 2.0), (5.0, 2.0), (5.0, 8.0), (1.0, 8.0)]
    with pytest.raises(ValueError):
        measured_corners([(1, 2), (5, 2), (5, 8)])
    with pytest.raises((ValueError, TypeError)):
        measured_corners("not a box")


# ---------------------------------------------------------------------------
# 2. 接线层：宿主的答案怎么和在线档 join 起来
# ---------------------------------------------------------------------------


def _fake_host(answers: dict, seen: list):
    """一个记流水账的假宿主：``answers[(action, params 排序后的 json)]``。"""

    async def call(action, params):
        seen.append((action, params))
        key = (action, json.dumps(params, sort_keys=True))
        if key in answers:
            value = answers[key]
            if isinstance(value, Exception):
                raise value
            return value
        raise AssertionError(f"the test host was not given an answer for {key}")

    return call


def _focused_pcb_of(archive: Path):
    """在线档里第一块 PCB 文档与它的一条位号 ATTR 记录（真档、真 id）。"""
    source = load_epro2_source(archive)
    document = source.documents_of_type("PCB")[0]
    attr = next(
        record for record in document.records
        if record.type == "ATTR" and (record.body or {}).get("key") == "Designator"
    )
    return document, attr


def _doc_list_payload(uuid: str, name: str, *, doc_type: str = "pcb") -> dict:
    """``doc.list`` 的答案形状（2026-10-12 真机实测）：``pcbs`` 是**计数**，
    PCB 清单在 ``documents[]`` 里、每项带 ``name``。"""
    return {
        "active": {"uuid": uuid, "type": doc_type},
        "documents": [
            {"uuid": "sch-1", "name": "schematic1", "type": "schematic"},
            {"uuid": uuid, "name": name, "type": doc_type},
        ],
        "pcbs": 1 if doc_type == "pcb" else 0,
    }


def test_the_host_answer_is_joined_to_the_archive_records_by_primitive_id():
    """实测通道：``doc.list`` → 档里的 ATTR id → ``pcb.geometry --bboxIds``（174）。"""
    document, attr = _focused_pcb_of(FOC_100)
    designator = str(attr.body["value"])
    seen: list = []
    host = _fake_host(
        {
            ("doc.list", "{}"): _doc_list_payload(document.uuid, "PCB1"),
            (cli_module.SILK_BBOX_ACTION, json.dumps({"bboxIds": sorted(
                {str(r.id): 1 for r in document.records
                 if r.type == "ATTR" and (r.body or {}).get("key") == "Designator"
                 and r.id}
            )}, sort_keys=True)): {
                "bboxes": {str(attr.id): {"minX": 10.0, "minY": 20.0, "maxX": 40.0, "maxY": 60.0}},
            },
        },
        seen,
    )
    notes: list[str] = []
    measured = asyncio.run(cli_module._measure_silk_boxes(host, FOC_100, notes))
    assert measured == {("PCB1", designator): (10.0, 20.0, 40.0, 60.0)}
    assert [action for action, _params in seen] == ["doc.list", cli_module.SILK_BBOX_ACTION]
    assert any("宿主实测" in note and "1 条位号文字盒" in note for note in notes)


def test_a_host_that_gives_no_box_degrades_and_says_so():
    """宿主给不出盒子 → 空表 + 一条点名「估算值」的 notes；绝不出半张表。"""
    document, _attr = _focused_pcb_of(FOC_100)
    host = _fake_host(
        {("doc.list", "{}"): _doc_list_payload(document.uuid, "PCB1")},
        [],
    )

    async def call(action, params):
        if action == "doc.list":
            return await host(action, params)
        return {"bboxes": {}}  # 宿主答了，但没给盒子

    notes: list[str] = []
    assert asyncio.run(cli_module._measure_silk_boxes(call, FOC_100, notes)) == {}
    assert any("丝印字宽降级" in note and "估算值" in note for note in notes)


def test_a_board_with_no_designator_record_in_the_archive_degrades_honestly():
    """档里找不到这块 PCB（或它没有位号记录）→ 一条说清的降级，而不是含糊的「没测到」。

    这条走的是 2026-10-12 真机跑出来的那个分支：宿主答得上、档也在，但没有可测的
    位号（``test``/``PCB1`` 是空板）——notes 必须点名是哪一块、为什么。
    """
    from boardwise.parsers.epru import load_epro2_source

    no_pcb = FIXTURES / "ProPrj_CH340G_2026-09-13.epro2"
    assert not load_epro2_source(no_pcb).documents_of_type("PCB")

    async def call(action, params):
        if action == "doc.list":
            return {
                "active": {"uuid": "5dc38976c1fa45ce", "type": "pcb"},
                "documents": [{"uuid": "5dc38976c1fa45ce", "name": "PCB1", "type": "pcb"}],
                "pcbs": 1,
            }
        raise AssertionError("the archive has no such PCB, so no bbox call may follow")

    notes: list[str] = []
    assert asyncio.run(cli_module._measure_silk_boxes(call, no_pcb, notes)) == {}
    assert any("丝印字宽降级" in note and "PCB1" in note and "估算值" in note for note in notes)


def test_a_focus_that_is_not_a_pcb_stays_silent():
    """焦点不是 PCB：不打搅、也不加「降级」噪声——本来就没有实测可言。"""
    seen: list = []
    host = _fake_host(
        {("doc.list", "{}"): _doc_list_payload("sch-1", "schematic1", doc_type="schematic")},
        seen,
    )
    notes: list[str] = []
    assert asyncio.run(cli_module._measure_silk_boxes(host, FOC_100, notes)) == {}
    assert notes == []
    assert [action for action, _ in seen] == ["doc.list"]


def test_a_broken_bridge_read_degrades_instead_of_raising():
    """桥读炸了只许降级：报告仍要写出来。"""

    async def call(_action, _params):
        raise RuntimeError("daemon went away")

    notes: list[str] = []
    assert asyncio.run(cli_module._measure_silk_boxes(call, FOC_100, notes)) == {}
    assert any("丝印字宽降级" in note for note in notes)


def test_the_rule_override_replaces_the_silk_rule_and_nothing_else():
    """接线只换丝印那一条：其余规则必须还是**同一个对象**（166 的同一条管线）。"""
    measured = {("PCB1", "C1"): (0.0, 0.0, 10.0, 10.0)}
    rules = cli_module._pcb_rules_with_measured_silk(measured)
    assert [rule.id for rule in rules] == [rule.id for rule in BUILTIN_PCB_RULES]
    for before, after in zip(BUILTIN_PCB_RULES, rules):
        if before.id == "pcb-silk-designator":
            assert isinstance(after, SilkDesignator)
            assert after is not before
            assert after.measured == measured
        else:
            assert after is before


def test_the_offline_file_path_still_says_estimate_for_every_width():
    """离线 ``--file`` 没有宿主可问：整份报告的宽度都必须是「估算值」。"""
    from boardwise.engines.pcbreview import run_pcb_review

    findings, section = run_pcb_review(FOC_100)
    assert section is not None
    silk = [f for f in findings if f.rule_id == "pcb-silk-designator"]
    assert silk
    summaries = [f for f in silk if f.message.startswith("PCB1 丝印读数")]
    assert summaries
    assert f"{WIDTH_SOURCE_LABEL[MEASURED_WIDTH]} 0 个" in summaries[0].message


# ---------------------------------------------------------------------------
# 3. 真机探针 —— 窗口不在就 skip，不硬依赖
# ---------------------------------------------------------------------------


def _bridge_call(action: str, params: dict, *, timeout: int = 60):
    """真机只读调用（子进程走 CLI，和人在终端敲的是同一条路）。"""
    env = dict(os.environ)
    env.pop("BOARDWISE_NO_AUTO_DAEMON", None)
    proc = subprocess.run(
        [
            sys.executable, "-m", "boardwise.cli", "bridge", "call",
            "--action", action, "--project", TEST_PROJECT,
            "--params", json.dumps(params),
        ],
        cwd=REPO, capture_output=True, timeout=timeout, env=env,
        # UTF-8 explicitly, for the same reason test_174's copy of this helper
        # documents: the CLI prints its payload with `ensure_ascii=False`, so a
        # host message in Chinese is UTF-8 on the pipe while this process's
        # locale is GBK — decoding by locale loses the whole frame to a
        # reader-thread exception and turns a good read into `stdout is None`.
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        return None, (proc.stdout + proc.stderr).strip()
    return json.loads(proc.stdout), ""


def test_live_the_test_board_has_no_measurable_designator():
    """真机（窗口不在就 skip）：``test``/``PCB1`` 上没有可测的位号。

    2026-10-12 实测：这块板是**空板**（0 COMPONENT、0 ATTR、Gerber 的丝印层零
    图元），所以「在线且工程开着 → 走实测」这一条今天在这台机器上**没有可演示的
    对象**。探针钉两件事，都是事实而不是期望：桥答得上、这块板上量不到位号。
    """
    listing, why = _bridge_call("doc.list", {})
    if listing is None:
        pytest.skip(f"test 工程窗口不在线（`bridge call doc.list` 失败：{why[:200]}）")
    # `doc.list` 的 `pcbs` 是**计数**，PCB 清单在 `documents[]` 里（type=="pcb"）
    pcbs = [d for d in (listing.get("documents") or []) if d.get("type") == "pcb"]
    if not pcbs:
        pytest.skip("test 窗口在线，但活动工程里没有 PCB 文档")

    pcb_uuid = str(pcbs[0]["uuid"])
    # 179 起 `uuid` 是真的：宿主 `getDocumentSource()` 不吃参数（实测 arity 0），
    # 所以这个动作只能读**活动文档**，点名别的文档回 `DOC_NOT_ACTIVE`。这条测试
    # 想读的是 PCB，就得它在前台——不在前台时明确 skip，别让「读到了别的文档」
    # 冒充「读到了 PCB」。
    active = listing.get("active") or {}
    if active.get("uuid") != pcb_uuid:
        pytest.skip(
            f"活动文档是 {active.get('uuid')}，不是 {pcbs[0].get('name')}({pcb_uuid})"
            "——sys.get_document_source 只读活动文档，先把这块板 doc.open 到前台"
        )
    source_payload, why = _bridge_call("sys.get_document_source", {"uuid": pcb_uuid})
    if source_payload is None:
        pytest.skip(f"读不到 {pcbs[0].get('name')} 的文档源（{why[:200]}）")
    text = str(source_payload.get("data") or "")
    assert '"type":"DOCHEAD"' in text or '"docType":"PCB"' in text, text[:200]
    # 量不到位号的原因，就是板上一片元件都没有——两个读数说的是同一件事
    assert '"type":"COMPONENT"' not in text
    assert '"type":"ATTR"' not in text

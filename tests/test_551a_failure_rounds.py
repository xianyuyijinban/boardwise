"""551A：零候选报告的分轮失败——拓扑轮的拒因不许被阶梯的第一条遮住。

============================ 病 ============================

`_no_candidate_failures` 只把 ``result.rejected`` 里**第一个**带 failure 的变体
端上 ``failures``。反激（去锁 presentation）实测：阶梯的 14 个变体全被
`same-column(Q1, R5)` 拒，随后拓扑搜索被 `net 'SEC_12V' … rail drawn as a wire`
拒——报告只有 `same-column`，拓扑轮那条**完全不可见**。岳点过这是「一个结论
多个出口」的同族毛病，这次被遮住的是**失败原因**。

============================ 治 ============================

``failures`` 是**摘要**（第一条拒因，所有既有消费方的读法）——一个字不改。
旁边加 ``failure_rounds``：每个搜索轮（base / widened / topology）自己的**第一条**
拒因，按编译器到达各轮的顺序排。``summarize_failure_rounds()`` 把它渲染成
``{round, category, detail}`` 字典列表给报告读；手工构造的 result（没有
rounds）回退到摘要 failures 本身，每个记 ``round="first"``——旧形状可复现。

本文件钉四件事：

1. **形状**（纯数据层）：round 词表、非法 round 拒收、``_variant_round`` 的标签
   判读、``summarize_failure_rounds`` 的两条路径；
2. **装配**（单测 `_failure_rounds` 对一个真实 rejected 列表）：每轮一条、按
   轮序、乱序的 rejected 也不影响轮序；
3. **端到端**（真数据，反激整页）：``failures`` 仍只有旧的那一条（向后兼容钉），
   ``failure_rounds`` 三轮齐、每轮点名自己那条——**拓扑轮的 rail 拒因在列表里**；
4. **CLI 合同**：``draw compile --json-path`` 的载荷带 ``failureRounds``，
   摘要 ``failures`` 键的形状不变。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawcompiler as dc
from boardwise.engines.grammar.base import GrammarFailure

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


# ---------------------------------------------------------------- 1 形状层


def _failure(detail: str, category: str = dc.FAILURE_LAYOUT_UNSAT) -> GrammarFailure:
    return GrammarFailure(category=category, detail=detail)


def test_failure_round_names_are_the_three_search_rounds():
    """551A 的轮词表只有编译器真的会跑的三轮，再没有一个能被手拼进来。"""
    assert dc.FAILURE_ROUNDS == ("base", "widened", "topology")
    for name in dc.FAILURE_ROUNDS:
        dc.FailureRound(round=name, failure=_failure("x"))
    with pytest.raises(dc.CompileError):
        dc.FailureRound(round="bogus", failure=_failure("x"))


def test_variant_round_reads_the_labels_the_compiler_writes():
    """标签判读：201B 的 topology-search、119 的 (widened)、053 的裸阶梯。

    一个不认识任何轮的标签落在 base——和每条阶梯档位同一个缺省，而不是被猜。
    """
    assert dc._variant_round("topology-search") == "topology"
    assert dc._variant_round("spacing=1 pose-variant=2 (widened)") == "widened"
    assert dc._variant_round("spacing=2.2 pose-variant=1") == "base"
    assert dc._variant_round("hand-built") == "base"


def test_summarize_failure_rounds_falls_back_to_the_summary_failures():
    """手工构造的 result（无 rounds）回退到 failures 本身——旧形状可复现。"""
    first = _failure("the first refusal", dc.FAILURE_PRESENTATION_POOR)
    result = dc.CompileResult(failures=[first, _failure("the second")])
    assert result.summarize_failure_rounds() == [
        {"round": "first", "category": first.category, "detail": first.detail},
        {"round": "first", "category": dc.FAILURE_LAYOUT_UNSAT,
         "detail": "the second"},
    ]


def test_summarize_failure_rounds_renders_the_rounds_when_present():
    """rounds 在场时是报告要的 {round, category, detail}，不是别的。"""
    result = dc.CompileResult(failure_rounds=[
        dc.FailureRound(round="base", failure=_failure("ladder reason")),
        dc.FailureRound(round="topology", failure=_failure("search reason")),
    ])
    assert result.summarize_failure_rounds() == [
        {"round": "base", "category": dc.FAILURE_LAYOUT_UNSAT,
         "detail": "ladder reason"},
        {"round": "topology", "category": dc.FAILURE_LAYOUT_UNSAT,
         "detail": "search reason"},
    ]


# ---------------------------------------------------------------- 2 装配层


def test_failure_rounds_take_the_first_refusal_of_each_round_in_round_order():
    """每个轮取它**第一条**拒因；rejected 乱序不改变轮序。

    rejected 是一条扁平的追加日志（阶梯档位 → 加宽档位 → 拓扑，按发生顺序），
    所以同一轮的第二条拒因被跳过，三轮的顺序由 FAILURE_ROUNDS 定而不是由
    rejected 的出现顺序定。
    """
    rejected = [
        # widened first in the list — the round order must not follow it
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=2 (widened)",
            reason="widened reason", failure=_failure("widened reason"),
        ),
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=3 (widened)",
            reason="second widened", failure=_failure("second widened"),
        ),
        dc.RejectedCandidate(
            variant="topology-search",
            reason="search reason", failure=_failure("search reason"),
        ),
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=0",
            reason="ladder reason", failure=_failure("ladder reason"),
        ),
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=1",
            reason="second ladder", failure=_failure("second ladder"),
        ),
        # a variant with no failure of its own (same-geometry rejections) is
        # not a round's answer and names no round
        dc.RejectedCandidate(
            variant="spacing=1.5 pose-variant=0",
            reason="the same geometry as an earlier variant",
        ),
    ]
    result = dc.CompileResult(rejected=rejected)
    rounds = dc._failure_rounds(result)
    assert [(item.round, item.failure.detail) for item in rounds] == [
        ("base", "ladder reason"),
        ("widened", "widened reason"),
        ("topology", "search reason"),
    ]


def test_a_round_with_no_recorded_refusal_is_absent_not_invented():
    """没有 failure 的轮不出场——列表里每一条都是读者还没被给过的原因。"""
    result = dc.CompileResult(rejected=[
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=0", reason="x",
            failure=_failure("ladder reason"),
        ),
        dc.RejectedCandidate(
            variant="topology-search", reason="y",
        ),
    ])
    rounds = dc._failure_rounds(result)
    assert [item.round for item in rounds] == ["base"]


# ---------------------------------------------------------------- 3 端到端


def _flyback_library() -> dict:
    import test_113_flyback_grammar as t113
    return t113._library_from(SPECS / "flyback_uc3845.library.json")


def test_the_topology_refusal_is_visible_beside_the_ladder_refusal():
    """**551A 的正题**：阶梯被 A 拒、拓扑被 B 拒——两条原因都在列表里。

    反激整页（去锁 presentation，120 后的形态）实测拒因链：阶梯 6 档全被
    `same-column(Q1, R5)` 拒 → 加宽轮被 `right-of(D3, T1)` 拒 → 拓扑轮被
    `net 'SEC_12V' … rail drawn as a wire` 拒。旧报告只显示第一条；现在
    ``failure_rounds`` 三轮齐，且拓扑轮那条**逐字可见**。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    result = dc.compile(
        circuit, presentation, _flyback_library(),
        dc.CompileBudget(max_candidates=64),
    )
    assert not result.ok and not result.candidates

    # 向后兼容钉：摘要 failures 还是旧的那一条、还是 same-column 那句话。
    assert len(result.failures) == 1
    assert "same-column(Q1, R5)" in result.failures[0].detail

    # 新的：三轮各一条，拓扑轮的拒因不再是被遮住的那个。
    by_round = {item.round: item.failure for item in result.failure_rounds}
    assert set(by_round) == {"base", "widened", "topology"}
    assert "same-column(Q1, R5)" in by_round["base"].detail
    assert "right-of(D3, T1)" in by_round["widened"].detail
    assert "'SEC_12V'" in by_round["topology"].detail, (
        "the topology round's own refusal must be visible beside the ladder's: "
        f"got {[item.round for item in result.failure_rounds]}"
    )

    # summarize 是报告的读法：round 名逐条在场。
    summary = result.summarize_failure_rounds()
    assert [item["round"] for item in summary] == [
        "base", "widened", "topology",
    ]
    assert "same-column(Q1, R5)" in summary[0]["detail"]
    assert "right-of(D3, T1)" in summary[1]["detail"]
    assert "'SEC_12V'" in summary[2]["detail"]


def test_a_hand_built_result_json_round_trips_are_report_ready():
    """``--json-path`` 载荷经 json.dumps 的那一手是纯数据，不炸。"""
    result = dc.CompileResult(failure_rounds=[
        dc.FailureRound(round="base", failure=_failure("d1")),
    ])
    payload = {"failureRounds": result.summarize_failure_rounds()}
    assert json.loads(json.dumps(payload))["failureRounds"] == [
        {"round": "base", "category": dc.FAILURE_LAYOUT_UNSAT, "detail": "d1"},
    ]


# ---------------------------------------------------------------- 4 CLI 合同


def test_draw_compile_json_payload_carries_failure_rounds(tmp_path):
    """``draw compile --json-path``：``failureRounds`` 在场，``failures`` 原样。

    窄页上的分压器（053 场景 10 的形状）在 CLI 里离线拒绝：`layout-unsat`、
    变体逐条建齐。钉的是载荷键的**形状**：新键是 list[{round,category,detail}]、
    旧键的字段集 (category, detail, action) 一个不少。
    """
    from boardwise import cli

    fixtures = pathlib.Path(__file__).resolve().parent / "fixtures" / "drawapply"
    report = tmp_path / "compile.json"
    code = cli.main([
        "draw", "compile",
        "--circuit", str(fixtures / "divider.circuit.json"),
        "--presentation", str(fixtures / "divider.presentation.json"),
        "--profiles", str(fixtures / "library.json"),
        "--page-box", "0,0,240,300",
        "--out", str(tmp_path / "out"),
        "--json", str(report),
    ])
    assert code == 5, "the narrow page refuses; the payload is the refusal's"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert isinstance(payload["failureRounds"], list)
    assert payload["failureRounds"], (
        "a refusal with no round rows would leave the second exit invisible "
        "again — this is the key the report reads"
    )
    for item in payload["failureRounds"]:
        assert set(item) == {"round", "category", "detail"}
        assert item["round"] in (*dc.FAILURE_ROUNDS, "first")
    for item in payload["failures"]:
        assert {"category", "detail", "action"} <= set(item)

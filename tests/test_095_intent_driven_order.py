"""095 A4：power-entry 语法消费 intent —— 支路顺序的三来源（角色与顺序同源）。

A 主线第四批。088b 让「TVS 贴入口」可声明（`branchOrder`），A2/A3 让 intent 成为审查的
事实源；本批让**绘制侧**直接消费合同：同一个事实说一次，审查与绘制共用，出处一路进
evidence（`docs/design-intent-channel.md` §三 A4 行）。

一句话一条规矩（任务书 §一，逐条对应下面的测试组）：

1. **三来源，按优先级**：`PresentationSpec.modules[].branchOrder`（图纸自己声明的最大）
   > intent（`decisions[subject=<支路>]` 的 prose、或 `blocks[].kind` 说这条是泄放类）
   > 位号序。前者与中层**都说话且不一致 → 拒绝**，把两个来源的原文并列，谁错人裁；
2. **intent 读什么**：泄放类（`tvs` / `clamp`·`钳位` / `泄放`）的支路排最靠入口，其余按
   位号序跟后；不做「泄放类之间谁更靠前」的判断——那一段是语法自己的位号 tie-break，
   拿它拒绝就是假警报（R2 的成本与误删同价）。claim 是**集合**不是排列，所以冲突判据是
   「有没有哪条非泄放支路站在所有泄放支路前面」；
3. **证据**：claim 的**原文 + 出处（`decisions[subject='D1']` / `blocks[id=…].kind`）+
   provenance + 合同路径**都进绑定 evidence；`ai_asserted` 照走但标注草稿，且绑定自己的
   provenance 行随之走弱（052 §4：草稿可以被画出来，但不许被读成工程师的要求）；
4. **缝**：`dc.compile(..., intent=None)` 可选、默认 None；CLI `draw compile/plan --intent
   PATH` 按 094 的 `_intent_source_for_apply` 同款路径解析（显式路径；默认落点要
   projectUuid，而编译发生在读工程之前，这一点在报告里留档）；
5. **零移动**：无合同（或合同对本模块的支路什么都没说）时，绑定/约束/义务/几何逐字节
   与 088/088b 一致。三层证据：本文件把**整份 `GrammarResult` 的 sha256 与 HEAD 树逐字钉死**
   （`HEAD_RESULT_SHA256`——顺序也在里面，实测它抓到过一次绑定顺序被换）、`evidence/095/`
   的 088/088b 预览哈希零移动、两张图的 geometry sha256 在 HEAD 树与工作树上逐字相同。

夹具复用 088（`test_088_power_entry`）与 088b（`test_088b_followups`）：两条轨、三颗支路、
连接器形状各只有一处定义，多一份就是第二个画法定义。合同一律**内存构造**
（`DesignIntent.from_dict` + `IntentSource`），本批不新增夹具文件。
"""

from __future__ import annotations

import json

import pytest

import test_088_power_entry as base088
import test_088b_followups as b088b

from boardwise import cli
from boardwise.core import designintent as di
from boardwise.core.circuitspec import CircuitSpec
from boardwise.engines import drawcompiler as dc
from boardwise.engines.grammar import grammar_for
from boardwise.engines.grammar import power_entry
from boardwise.engines.grammar.base import (
    ADJACENT,
    FAILURE_CIRCUIT_INVALID,
    GrammarError,
)

BRANCHES = b088b.SAMPLE_BRANCHES
CONTRACT_PATH = "C:/tmp/inlet.intent.json"

#: 岳样板那句事实：D1 是 TVS，贴入口（088b 的 R12；本批的「真实证人」是 ctrl FOC
#: 合同形状 `decisions[R4]` 的类比——把 subject 换成入口模块里的那颗支路）。
TVS_DECISION = {
    "subject": "D1",
    "decision": "入口 TVS 贴连接器，泄放浪涌尖峰",
    "rationale": "尖峰要在它到达后级支路之前泄掉",
    "provenance": "user_stated",
}


# ------------------------------------------------------------------ 夹具与工具


def contract(*decisions, blocks=(), path=CONTRACT_PATH):
    """一份内存合同：只写本批读的两段，其余缺省（合同 schema 的缺省即空）。"""
    return di.IntentSource(
        document=di.DesignIntent.from_dict({
            "intentVersion": di.INTENT_VERSION,
            "blocks": list(blocks),
            "decisions": list(decisions),
        }),
        path=path,
    )


def tvs(**overrides):
    body = dict(TVS_DECISION)
    body.update(overrides)
    return body


TVS = contract(tvs())


def bind(circuit_spec, presentation_spec, intent=None):
    """The grammar bound with the contract in hand (the two-arg form is 088b's)."""
    return grammar_for("power-entry").bind(
        circuit_spec, presentation_spec, intent=intent
    )


def compile_with(circuit_spec, presentation_spec, intent=None, budget=None):
    return dc.compile(
        circuit_spec,
        presentation_spec,
        base088.library(),
        budget if budget is not None else dc.CompileBudget(),
        intent=intent,
    )


def best(circuit_spec, presentation_spec, intent=None):
    result = compile_with(circuit_spec, presentation_spec, intent=intent)
    assert result.ok, result.render_failures()
    return result.best()


def undeclared(side="right"):
    return b088b.undeclared(side=side)


def declared(order=("D1", "C115", "C116"), **overrides):
    return b088b.declared(order=order, **overrides)


def shunt_evidence(result, part_id):
    return next(
        item.evidence
        for item in result.bindings
        if item.role == "shunt" and item.part_id == part_id
    )


def adjacent_reason(result, subject):
    return next(
        item.reason
        for item in result.constraints
        if item.kind == ADJACENT and item.subject == subject
    )


# ======================================================== 1. 顺序的三来源（§一.1/2）


def test_without_a_contract_nothing_moves_for_either_presentation():
    """硬约束：`intent=None` 与不传参**逐字节同一个结果**（088b 的图一动不动）。

    比的是整份 `GrammarResult` 的规范 JSON：绑定 evidence 里的每个字、约束的每条
    reason、义务的每条 reason 都在里面，所以这条断言比逐个字符串更严。
    """
    for presentation_spec in (declared(), undeclared()):
        circuit_spec = base088.inlet_circuit()
        without = base088.bind(circuit_spec, presentation_spec)
        explicitly = bind(circuit_spec, presentation_spec, None)

        assert without.to_jsonable() == explicitly.to_jsonable()
        assert json.dumps(without.to_jsonable(), sort_keys=True) == json.dumps(
            explicitly.to_jsonable(), sort_keys=True
        )


#: 无合同（`intent=None`）时整份 `GrammarResult` 规范 JSON 的 sha256 —— 在 **HEAD 树**上量到
#: （`.tmp_095_head/`，`git archive HEAD src tests tools`；机具见 `evidence/095/zero_motion.sh`）。
#:
#: 为什么钉哈希而不只钉字符串：**绑定与约束的顺序**也是这份结果的一部分。本批实测踩过一次
#: ——`_result` 里把「读哪一份序列」写错（位号集合而不是最终顺序）时，declared / partial
#: 两个场景的绑定顺序与三条 same-row/right-of/near 的顺序都会变，而 088b 的既有断言
#: （只查链的两端与成员）看不出来。哈希是"无合同 = HEAD"的最严写法：顺序、每条 evidence
#: 的每个字、每条 reason 都在里面。
HEAD_RESULT_SHA256 = {
    "declared": "375bbe6a983d0875e9ef2fa709549bc964c2bf6d8f3606f3465831ed0c0dcc4c",
    "undeclared": "91f6461263901c9db3336f3ae98f9f9429e4e796275a944fb3acd7b3f3105688",
    "partial": "e0c581ba6b9ed279e926bd61e2f89d8b26112cac661031ada581c2b69561b07e",
    "four": "a4b03c45fe5e07bc6cb6c8b8a5d230c1396b9c500486336c11c3941e794341df",
    "left": "f98ee5abd98c68ad20b0f36329155bdd02391d5566afbf5c1677d1fe55e08a39",
    "declared_no_order": "91f6461263901c9db3336f3ae98f9f9429e4e796275a944fb3acd7b3f3105688",
    "order_names_inlet": "c85bcd93adb6ee8d7e022f38e1f5d3c2daaed449c3b222121da8cbd9ea1c1540",
}

FOUR = ("D1", "C115", "C116", "C117")


def head_scenes() -> dict:
    """The 088b scenes this batch must not move, as `{name: (circuit, presentation)}`."""
    circuit_spec = base088.inlet_circuit()
    return {
        "declared": (circuit_spec, b088b.declared()),
        "undeclared": (circuit_spec, b088b.undeclared()),
        "partial": (circuit_spec, b088b.declared(order=("C116",))),
        "four": (
            base088.inlet_circuit(shunts=FOUR),
            b088b.declared(order=FOUR, branches=FOUR),
        ),
        "left": (circuit_spec, b088b.declared(side="left")),
        "declared_no_order": (circuit_spec, b088b.declared(order=None)),
        "order_names_inlet": (circuit_spec, b088b.declared(order=("CN1", "D1"))),
    }


def test_without_a_contract_the_whole_binding_is_still_heads_binding():
    """七个 088b 场景的整份 `GrammarResult`（含顺序）与 HEAD 树逐字节相同。

    比 `test_without_a_contract_nothing_moves_for_either_presentation` 更严的一层：
    那条比的是本批自己的两种写法彼此相等（**同错不算错**），这条比的是**HEAD 的字节**。
    偏离 = 无合同行为移动了（硬约束），例如绑定/约束的顺序被换过。
    """
    import hashlib

    for name, (circuit_spec, presentation_spec) in head_scenes().items():
        result = bind(circuit_spec, presentation_spec, None)
        digest = hashlib.sha256(
            json.dumps(result.to_jsonable(), sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert digest == HEAD_RESULT_SHA256[name], name


def test_the_contract_orders_the_branches_when_nothing_is_declared():
    """缺省声明 + 合同说 D1 是泄放类 → D1 排最靠入口，其余按位号序跟后。

    三条一起钉：约束链是 `adjacent(D1,C115), adjacent(C115,C116)`；图上离入口的顺序
    就是 D1 → C115 → C116；可读性检查器零硬违规（顺序不是画得丑的借口）。
    """
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()
    result = bind(circuit_spec, presentation_spec, TVS)
    plan = best(circuit_spec, presentation_spec, TVS)

    assert result.ok, result.failures
    assert b088b.relation_pairs(result)[-2:] == [
        (ADJACENT, "D1", "C115"),
        (ADJACENT, "C115", "C116"),
    ]
    assert b088b.from_the_inlet(plan, BRANCHES, side="right") == list(BRANCHES)
    base088.clean(plan, circuit_spec, presentation_spec)


def test_the_declaration_outranks_the_contracts_designator_tie_break():
    """图纸自己的声明最大：声明把**非泄放类**排在泄放类之后、但内部顺序不同于位号序时，
    画的是声明，不是合同推出来的位号序（C116 在 C115 前面）。"""
    circuit_spec = base088.inlet_circuit()
    presentation_spec = declared(order=("D1", "C116", "C115"))
    plan = best(circuit_spec, presentation_spec, TVS)

    assert b088b.from_the_inlet(plan, BRANCHES, side="right") == [
        "D1", "C116", "C115"
    ]
    result = bind(circuit_spec, presentation_spec, TVS)
    assert b088b.relation_pairs(result)[-2:] == [
        (ADJACENT, "D1", "C116"),
        (ADJACENT, "C116", "C115"),
    ]


def test_a_contract_that_says_nothing_about_these_branches_leaves_088b_alone():
    """合同存在、但说的是**别的件**（连接器、或不存在的位号）→ 与无合同逐字节相同。

    这是「事实说一次」的另一半：合同没说的，语法不许自己替它说。本轮钉的是
    **作用域**那一半（subject 不是本模块支路）；**token** 那一半（subject 是支路、
    但没说泄放类）由下面 `test_a_decision_that_names_no_clamping_family_is_not_an_order`
    钉——变异 M4 实测：两条合起来才拦得住「无条件把任何条目当 claim」。
    """
    circuit_spec = base088.inlet_circuit()
    presentation_spec = declared()
    unrelated = contract(
        tvs(subject="CN1", decision="连接器，不是泄放件"),
        {"subject": "C9", "decision": "TVS 泄放", "provenance": "user_stated"},
        blocks=[{"id": "b1", "kind": "TVS", "parts": ["C9"]}],
    )

    assert json.dumps(
        bind(circuit_spec, presentation_spec, unrelated).to_jsonable(), sort_keys=True
    ) == json.dumps(
        base088.bind(circuit_spec, presentation_spec).to_jsonable(), sort_keys=True
    )
    assert b088b.from_the_inlet(
        best(circuit_spec, presentation_spec, unrelated), BRANCHES, side="right"
    ) == ["D1", "C115", "C116"]


def test_a_decision_that_names_no_clamping_family_is_not_an_order():
    """合同里有**本模块支路**的条目，但没说它是泄放类 → 不是顺序声明（位号序照旧）。

    这是 token 表的边界，而且它有真代价：`浪涌`/`surge` 也出现在「大电容提供浪涌
    电流」这种句子里——把它算成泄放件，会把一颗体电容搬到入口。所以只有写明
    `tvs` / `clamp`·`钳位` / `泄放` 才算 claim。**变异 M4**（`_names_clamp` 无条件
    返回 True）在这条上红两处：evidence 里多出 intent 那句话，且图从位号序变成
    C116 贴入口。
    """
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()
    energy = contract({
        "subject": "C116",
        "decision": "330uF 输入储能",
        "rationale": "为后级提供浪涌电流与能量缓冲",
        "provenance": "user_stated",
    })
    result = bind(circuit_spec, presentation_spec, energy)

    assert result.ok, result.failures
    assert "the design intent states" not in shunt_evidence(result, "C116")
    assert b088b.from_the_inlet(
        best(circuit_spec, presentation_spec, energy), BRANCHES, side="right"
    ) == ["C115", "C116", "D1"]


def test_the_claim_is_a_set_so_the_order_among_the_clamping_branches_is_not_a_conflict():
    """两条泄放类支路都声明了：只要它们都在非泄放支路前面，声明的图照画不改。

    合同没有说「D1 比 C116 更靠入口」，所以声明把 D1 放前面（而合同的位号 tie-break
    会给 C116 在前）不是冲突——拿这个拒绝就是假警报（R2）。
    """
    circuit_spec, presentation_spec = base088.inlet_circuit(), declared(
        order=("D1", "C116", "C115")
    )
    both = contract(
        tvs(subject="D1"),
        tvs(subject="C116", decision="入口第二颗 TVS，泄放"),
    )
    result = bind(circuit_spec, presentation_spec, both)

    assert result.ok, result.failures
    assert b088b.from_the_inlet(
        best(circuit_spec, presentation_spec, both), BRANCHES, side="right"
    ) == ["D1", "C116", "C115"]
    note = shunt_evidence(result, "C115")
    assert "satisfies the claim" in note
    assert "the two sources agree" not in note


# ==================================================== 2. 证据与出处（§一.2 后半）


def test_the_evidence_names_the_entry_the_claim_and_the_contract():
    """claim 进 evidence 的三件事：**哪条**说的、**原话**是什么、**谁**说的（provenance）。

    合同路径一起进，所以读证据的人不必先知道合同在哪。绑定自己的 provenance 行是
    这一条支路的最弱事实：D1 因为合同放了它，随 claim 落到 `user_stated`；C115 没有
    被合同摆位，仍是电路自己的 `verified_recipe`（不许被邻座拖弱）。
    """
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()
    result = bind(circuit_spec, presentation_spec, TVS)

    d1 = shunt_evidence(result, "D1")
    assert "the design intent states" in d1
    assert "decisions[subject='D1']" in d1
    assert TVS_DECISION["decision"] in d1
    assert "(provenance=user_stated)" in d1
    assert f"the contract {CONTRACT_PATH}" in d1
    assert d1.endswith("provenance=user_stated")
    assert shunt_evidence(result, "C115").endswith("provenance=verified_recipe")


def test_a_draft_claim_is_carried_out_and_marked_a_draft():
    """052 §4：`ai_asserted` 的 claim 照走，但绑定自己变成可见的草稿。"""
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()
    draft = contract(tvs(provenance="ai_asserted"))
    result = bind(circuit_spec, presentation_spec, draft)

    assert result.ok, result.failures
    evidence = shunt_evidence(result, "D1")
    assert "provenance=ai_asserted" in evidence
    assert "draft (ai_asserted)" in evidence
    assert "carried out here because the document declares no order" in evidence
    # 照走：D1 仍然贴着入口（草稿不是不执行，是标注）。
    assert b088b.from_the_inlet(
        best(circuit_spec, presentation_spec, draft), BRANCHES, side="right"
    ) == list(BRANCHES)


def test_a_block_kind_states_the_same_claim_as_a_decision():
    """同一条事实也可以写成 `blocks[]`（`kind` 说角色、`parts` 说是哪颗）。"""
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()
    from_block = contract(blocks=[{
        "id": "clamp", "kind": "TVS 泄放", "parts": ["D1"],
        "provenance": "user_stated",
    }])
    result = bind(circuit_spec, presentation_spec, from_block)

    assert result.ok, result.failures
    assert "blocks[id='clamp'].kind" in shunt_evidence(result, "D1")
    assert b088b.from_the_inlet(
        best(circuit_spec, presentation_spec, from_block), BRANCHES, side="right"
    ) == list(BRANCHES) == b088b.from_the_inlet(
        best(circuit_spec, presentation_spec, TVS), BRANCHES, side="right"
    )


def test_the_chain_reason_says_which_source_the_order_came_from():
    """`adjacent` 链的 reason 开头那一句随来源变：声明 / 合同 / 两者一致。

    顺序落在图上，但「谁说的」只在 reason 里——两条来源发的是同一个 kind、同一套
    检查，所以这一句是读者唯一能分辨的地方。
    """
    circuit_spec = base088.inlet_circuit()
    declared_only = adjacent_reason(
        base088.bind(circuit_spec, declared()), "D1"
    )
    contracted = adjacent_reason(
        bind(circuit_spec, undeclared(), TVS), "D1"
    )
    both = adjacent_reason(
        bind(circuit_spec, declared(), TVS), "D1"
    )

    assert declared_only.startswith(
        "088b sec.2: the document states this module's branch order (branchOrder),"
    )
    assert contracted.startswith(
        "088b sec.2: the design intent states this module's branch order "
        "(the contract's own decisions, not branchOrder),"
    )
    assert "design intent states the same one" in both
    # 其余逐字相同：链说的是同一件事，只有出处不同。
    tail = "and D1 is the branch next to the inlet CN1 before C115 —"
    assert tail in declared_only and tail in contracted and tail in both


# ============================================================ 3. 冲突（§一.3）


def test_a_declaration_that_denies_the_contract_is_refused_with_both_originals():
    """声明与合同都说话且不一致 → `circuit-invalid`，两个来源的原文并列，谁错人裁。

    断言的是「人能不能只读这条拒绝就判」：声明的**列表原文**、合同的**条目原文**
    （含 provenance 与文件）、以及两边各自推出什么，全在 detail 里；action 给出两种
    修法（改声明 / 改合同），并列名要去改的那个 subject。
    """
    circuit_spec = base088.inlet_circuit()
    presentation_spec = declared(order=("C116", "D1", "C115"))
    result = bind(circuit_spec, presentation_spec, TVS)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "D1"
    assert "modules[inlet].branchOrder states [C116, D1, C115]" in failure.detail
    assert "decisions[subject='D1']" in failure.detail
    assert TVS_DECISION["decision"] in failure.detail
    assert "(provenance=user_stated)" in failure.detail
    assert f"the contract {CONTRACT_PATH}" in failure.detail
    assert "C116 stands before D1" in failure.detail
    assert "a person says which" in failure.detail
    assert "modules[inlet].branchOrder as [D1, C115, C116]" in failure.action
    assert "change decisions[subject='D1']" in failure.action
    # 拒绝是拒绝：没有候选、也没有图（编译器的四分类里它落在 circuit-invalid）。
    compiled = compile_with(circuit_spec, presentation_spec, TVS)
    assert compiled.ok is False and compiled.categories() == [FAILURE_CIRCUIT_INVALID]


def test_a_declaration_that_agrees_with_the_contract_is_carried_out_as_declared():
    """两个来源说同一件事不是冲突：声明照画，一致写进 evidence。"""
    circuit_spec = base088.inlet_circuit()
    presentation_spec = declared(order=("D1", "C115", "C116"))
    result = bind(circuit_spec, presentation_spec, TVS)

    assert result.ok, result.failures
    assert b088b.relation_pairs(result)[-2:] == [
        (ADJACENT, "D1", "C115"),
        (ADJACENT, "C115", "C116"),
    ]
    evidence = shunt_evidence(result, "C115")
    assert "modules[inlet].branchOrder states the same order" in evidence
    assert "the two sources agree" in evidence
    # 声明说的是 D1/C115/C116；合同只多说了「D1 最靠入口」，图上仍是声明那一版。
    assert b088b.from_the_inlet(
        best(circuit_spec, presentation_spec, TVS), BRANCHES, side="right"
    ) == list(BRANCHES)


def test_the_contract_is_read_before_the_declaration_can_be_refused_for_its_own_sake():
    """声明本身站不住（点了入口）时，报的是 088b 那条拒绝——合同不改变这个判断。"""
    circuit_spec = base088.inlet_circuit()
    presentation_spec = declared(order=("CN1", "D1"))
    result = bind(circuit_spec, presentation_spec, TVS)

    assert result.ok is False
    (failure,) = result.failures
    assert failure.subject == "CN1"
    assert "it is the inlet of this module" in failure.detail
    assert "branchOrder" in failure.detail


# ============================================ 4. 检查器与缝（§一.4 + 053 §2）


def test_the_independent_checker_reads_the_same_contract_as_the_compiler():
    """检查器（`check_grammar`）读的合同必须与出约束的那一次相同（095 A4）。

    **实测先说清楚**：`adjacent` 在成品图上的判据是「横向对齐、纵向错开」
    （`drawcompiler._relation_holds`），**与谁更靠入口无关**——这正是 088b 选它的
    理由（两种朝向下同一句话都成立）。所以「顺序画反了」是**编译器的 rank 走查**
    拦下来的（§1 的三条测试钉的就是它），检查器拦不住，本测试也不假装它拦得住。

    可分辨的地方是**检查器用的是哪一份绑定**：图按「声明说 C116 先」画出来（不带
    合同编译），拿带合同的检查器读同一张图，它先撞上「语法拒绝这份文档」（合同与
    声明不一致）——说明它确实把合同交给了语法；不带合同读同一张图 → 零 finding
    （缺省声明不发链，也不发这个拒绝）。两种读法给得出不同的答案，就是「读到没
    读到」的证据。
    """
    circuit_spec = base088.inlet_circuit()
    presentation_spec = declared(order=("C116", "D1", "C115"))
    plan = best(circuit_spec, presentation_spec)

    with_contract = dc.check_grammar(
        plan, circuit_spec, presentation_spec, base088.library(), intent=TVS
    )
    without = dc.check_grammar(
        plan, circuit_spec, presentation_spec, base088.library()
    )

    assert [item.kind for item in with_contract] == [dc.KIND_BINDING_UNPLACED]
    assert "the grammar refuses this circuit" in with_contract[0].detail
    assert without == []


def test_the_weakest_provenance_table_knows_the_contracts_engineer_token():
    """095 撞上的洞：语法的 provenance 表原本不认 `user_stated`（合同通道的工程师档
    拼法，090 A1），于是「电路 verified_recipe + 合同 user_stated」在
    `weakest_provenance` 里抛 `KeyError`——合同是第一个能把这个词送进语法的文档。"""
    from boardwise.engines.grammar import base as grammar_base

    assert grammar_base.weakest_provenance(
        "verified_recipe", "user_stated"
    ) == "user_stated", "the engineer's own word ranks above a recipe"
    assert grammar_base.weakest_provenance(
        "user_stated", "ai_asserted"
    ) == "ai_asserted"
    assert grammar_base.weakest_provenance(
        "user_stated", ""
    ) == grammar_base.PROVENANCE_UNSTATED, "an unstated fact is the weakest"


def test_the_compiler_refuses_a_contract_it_cannot_read():
    """合同的类型在缝上就查：一个读不了的合同不等于没有合同。"""
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()

    with pytest.raises(dc.CompileError) as caught:
        compile_with(circuit_spec, presentation_spec, intent={"decisions": []})
    assert "IntentSource or a DesignIntent" in str(caught.value)

    with pytest.raises(GrammarError) as caught:
        bind(circuit_spec, presentation_spec, {"decisions": []})
    assert "IntentSource or a DesignIntent" in str(caught.value)


def test_the_grammars_that_read_no_contract_still_accept_one():
    """四个语法同一个 `bind` 签名：不读合同的那三个照收不误（否则一个 dispatcher
    调用就得先问名字），而且**收与不收结果一样**——它们没读它。"""
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()
    for name in ("ldo", "rc-lowpass", "voltage-divider"):
        target = grammar_for(name)
        with_contract = target.bind(circuit_spec, presentation_spec, intent=TVS)
        without = target.bind(circuit_spec, presentation_spec)

        assert with_contract.to_jsonable() == without.to_jsonable(), name


# ============================================================ 5. CLI 的缝（§一.4）


def write_inputs(tmp_path, circuit_spec, presentation_spec):
    circuit = tmp_path / "inlet.circuit.json"
    presentation = tmp_path / "inlet.presentation.json"
    profiles = tmp_path / "library.json"
    circuit.write_text(
        json.dumps(circuit_spec.to_jsonable(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    presentation.write_text(
        json.dumps(presentation_spec.to_jsonable(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    profiles.write_text(
        json.dumps(
            {"profiles": [item.to_jsonable() for item in base088.library().values()]},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return circuit, presentation, profiles


def write_contract(tmp_path) -> "object":
    path = tmp_path / "inlet.intent.json"
    di.DesignIntent.from_dict({
        "intentVersion": di.INTENT_VERSION,
        "decisions": [dict(TVS_DECISION)],
    }).dump(path)
    return path


def test_draw_compile_reads_the_contract_named_by_the_flag(tmp_path, capsys):
    """`draw compile --intent PATH` 真的把合同送进了编译：画出来的几何就是带合同的
    那一版（与进程内编译的 geometry sha256 逐字相同），而不是位号序那一版。"""
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()
    circuit, presentation, profiles = write_inputs(
        tmp_path, circuit_spec, presentation_spec
    )
    path = write_contract(tmp_path)
    report = tmp_path / "compile.json"

    code = cli.main([
        "draw", "compile",
        "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(profiles), "--intent", str(path),
        "--out", str(tmp_path / "out"), "--json", str(report),
    ])
    printed = capsys.readouterr()
    assert code == 0, printed.out + printed.err
    payload = json.loads(report.read_text(encoding="utf-8"))
    with_contract = best(circuit_spec, presentation_spec, TVS).geometry_sha256()
    without = best(circuit_spec, presentation_spec).geometry_sha256()

    assert with_contract != without, "the two readings must differ, or this proves nothing"
    assert payload["candidates"][0]["geometrySha256"] == with_contract
    assert not any("设计意图合同" in note for note in payload["notes"]), payload["notes"]


def test_draw_compile_says_so_when_the_named_contract_cannot_be_read(tmp_path, capsys):
    """094 的读法：点了名却读不了的合同 → 一条 note + 按原样跑（不是崩溃、不是猜测）。

    图因此回到位号序那一版，与无合同编译逐字相同——「没读到」不会悄悄变成「读到了
    一个空合同」。
    """
    circuit_spec, presentation_spec = base088.inlet_circuit(), undeclared()
    circuit, presentation, profiles = write_inputs(
        tmp_path, circuit_spec, presentation_spec
    )
    report = tmp_path / "compile.json"

    code = cli.main([
        "draw", "compile",
        "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(profiles),
        "--intent", str(tmp_path / "not-there.json"),
        "--out", str(tmp_path / "out"), "--json", str(report),
    ])
    printed = capsys.readouterr()
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert code == 0, printed.out + printed.err
    assert "存在" in printed.out, printed.out
    assert "not-there.json" in printed.out
    assert payload["notes"], "the note reaches the machine-readable run too"
    assert (
        payload["candidates"][0]["geometrySha256"]
        == best(circuit_spec, presentation_spec).geometry_sha256()
    )


def test_the_page_path_says_it_does_not_read_the_contract_yet():
    """057 的页级路径本批不消费合同：给了 `--intent` 要说出来，不许静默忽略。"""
    class _Args:
        intent = "C:/tmp/inlet.intent.json"

    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        cli._warn_page_intent(_Args(), "draw compile")
    assert "not read on the page path" in buffer.getvalue()

    silent = io.StringIO()
    with contextlib.redirect_stderr(silent):
        cli._warn_page_intent(type("A", (), {"intent": ""})(), "draw compile")
    assert silent.getvalue() == ""


# ==================================================== 6. 零移动的回归钉（§二）


def test_the_contract_less_scenes_keep_their_measured_geometry():
    """无合同的两张图（088b 声明版 + 088 缺省版）的几何哈希是本批实测的常量。

    这是 `evidence/095/` 里 088/088b 预览哈希零移动的**测试内**同一个事实：预览哈希
    覆盖 14 + 18 张产物，这里钉住两次编译的落点。任何一处漂移都会先在这里红。
    """
    circuit_spec = base088.inlet_circuit()
    declared_sha = best(circuit_spec, declared()).geometry_sha256()
    undeclared_sha = best(circuit_spec, undeclared()).geometry_sha256()

    assert declared_sha == DECLARED_GEOMETRY_SHA
    assert undeclared_sha == UNDECLARED_GEOMETRY_SHA
    assert declared_sha != undeclared_sha


#: 088b 的声明版与 088 的缺省版（`intent=None`）实测几何哈希——改动后用同一段代码在
#: **HEAD 树**（`git archive HEAD` 解到 `.tmp_095_head/`）与工作树上各跑一遍，两值逐字
#: 相同（`evidence/095/zero_motion.txt` 是那一次的机具与输出）。
DECLARED_GEOMETRY_SHA = "f0f8c26fb41ade21376d20230ae53d7244ecd4274d746232c1367c3196323681"
UNDECLARED_GEOMETRY_SHA = "c0f9a64e1b0715d6a68baf30424ff0f542eb716543d933901c5a9ca0cba9866f"


def test_the_module_carries_no_scenario_specific_constant_after_095():
    """053 §6 的红线在本批新增的代码里照旧成立（088 那条查全文，这里复查一次：
    本批新增的 token 表里没有位号、值、封装名）。"""
    import ast
    import pathlib

    source = pathlib.Path(power_entry.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant
            ):
                docstrings.add(id(body[0].value))
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    comments = [line for line in source.splitlines() if line.strip().startswith("#")]
    for token in ("D1", "C115", "C116", "SMCJ", "330uF", "R0402"):
        assert not any(token in value for value in literals), token
        assert not any(token in line for line in comments), token


def test_the_contract_carrier_is_the_one_094_put_in_core():
    """合同的载体是 `core.designintent.IntentSource`（094 的规则走查用的是同一个），
    grammar 只从 core 读、自己不碰盘（006c 层表）。"""
    assert isinstance(TVS, di.IntentSource)
    assert di.IntentSource(document=di.DesignIntent(), path="").document.entry(
        di.SECTION_DECISIONS, "D1"
    ) is None
    assert isinstance(base088.inlet_circuit(), CircuitSpec)

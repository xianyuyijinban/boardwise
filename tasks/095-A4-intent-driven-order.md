# 095 — A4：power-entry 语法消费 intent（角色与顺序同源）

A 主线第四批（A1 `b21089a` / A2 `ab6aa10`/`aceda21` / A3 `310b93b`/`80653cd`）。
**先读** `docs/design-intent-channel.md` §三 A4 行、`src/boardwise/engines/grammar/power_entry.py`
（088b 的 branchOrder 消费）、`src/boardwise/cli.py` 的 `_intent_source_for_apply`（094 的合同解析缝）。

## 〇、动机（意图→图纸同源）

088b 让「TVS 贴入口」可声明（`branchOrder`），A2/A3 让 intent 成为审查的事实源。
今天同一个事实（「D1 是 TVS、贴入口」）要在**每份** PresentationSpec 里重新声明一遍——
而 intent 的 `decisions[]` / `blocks[]` 已经说过一次。本批让 power-entry 语法**直接消费
intent**：事实说一次，审查与绘制共用；出处（provenance）一路进 evidence。

## 一、消费规则（写进 grammar docstring）

1. `PresentationSpec.modules[].branchOrder` **仍是第一优先级**（图纸自己的声明最大）；
2. branchOrder 缺省时，语法按顺序从 intent 推：
   - `decisions[subject=<shunt>]` 的 prose/`kind` 明示角色（TVS/泄放）→ 泄放类排最靠入口，
     其余按位号序跟后；证据行带 intent 出处与 provenance（`ai_asserted` 照走但标注草稿）；
   - 推不出（无合同/无相关决策）→ **088b 现状逐字节**（位号序，零移动）；
3. **冲突**：branchOrder 与 intent 推出的顺序**不一致** → 语法拒绝（`circuit-invalid` 同族），
   消息把两个来源的原文都列出（谁错人裁——A3a R1 的纪律在绘制侧的同款）；
4. intent 进语法的缝：`dc.compile(circuit, presentation, library, intent=None)` 加**可选**
   参数（默认 None=零移动）；CLI 侧 `draw compile/plan` 按 094 的 `_intent_source_for_apply`
   同款路径解析（默认落点；`--intent` flag 若顺手就加，不加留记录）。层表：engines 读 core
   合规（A2a 层表），grammar 不碰盘。

## 二、测试与验收

- 夹具：branchOrder 有/无 × intent 有/无/冲突五态；provenance 两档（user_stated/ai_asserted）
  的 evidence 措辞；**无 intent 逐字节零移动**（088/088b 场景哈希全不动——硬约束）。
- 真实证人：ctrl FOC 合同形状（`decisions[R4]`）类比的合成 inlet（decisions 说 D1 是 TVS）
  → 不声明 branchOrder 也排出 D1 贴入口；同时声明相反的 branchOrder → 拒绝并列双源。
- 全量 pytest 绿（基线 **3120**），新测试进 `tests/test_095_intent_driven_order.py`；
  既有断言一字不改；088/088b 预览哈希零移动（申报制证据）。
- 变异 ≥2 组（intent 兜底支路 + 冲突拒绝支路），cp+sha256 还原。
- 文档：`docs/design-intent-channel.md` §三 A4 行转「已落地（095，power-entry 首吃）」；
  schematic-conventions.md R12 补「顺序三来源：branchOrder > intent > 位号序」。
- **删除一律进回收站（红线#4，零删除才许交卷）**；纯离线、不动 git、不写 PROGRESS。
- 交卷：改动清单/五态样例/哈希零移动证据/变异记录/全量结果行/遗留项（A4 未完：模块清单
  与 flow 从 blocks 推出的提案器——归后续批的说明）。

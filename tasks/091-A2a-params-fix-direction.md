# 091 — A2a：params 冲突的「改值 or 改料号」双向修复建议

A 主线第二批（A1 已落账 `b21089a`）。**先读** `docs/design-intent-channel.md` §一.1 与 §三 A2 行、
`tasks/090-A1-design-intent.md` 交卷口径（intent 只报告不抬 verdict 的现状）。

## 背景与动机（052 评审点 1，实案）

params 规则发现「MPN 与 Value 冲突」时，今天的建议一律偏向「把 Value 改成料号对应的值」
（`src/boardwise/rules/params.py:359` 一带）。实案反例：一块板上 **17 颗器件是 MPN 字段写错、
设计值正确**——照现建议修会把电路改错。**发现矛盾 ≠ 知道该怎么修**；修复方向要看设计意图。

A1 之后意图有了住处：intent 的 `decisions[]` 以位号为 `subject`（ctrl FOC 已发一船：
`{"subject":"R4","decision":"0.1Ω 直采…","provenance":"user_stated"}`）。本批让 params 规则
**消费**它：方向由 intent 决定，intent 没说的就双向列出并点名去哪补。

## 一、合同侧（小增量）

- `decisions[]` 条目新增**可选** `value` 字段（如 `"0.1Ω"`）——决策正文是散文、机读值要结构化
  才能和 MPN 对拍。封闭 schema 加键纪律照旧（可选、缺省不写出、intentVersion 不升）。
- `blocklib/intents/robot-ctrl-foc.intent.json` 的 R4 决策补上 `value: "0.1Ω"`（与正文一致）。

## 二、规则侧（params.py）

先盘清「建议改 Value」的 findings 到底有几条产出路径（grep params.py 的 action/recommend
文案），全部过同一个 helper（单点防口径漂移，参照 #55 的 `_grade_new_findings` 手法）：

1. intent 有该位号的 `decisions[].value` → 建议**改 MPN/重选件**（方向=设计值是对的），
   文案带出 intent 出处与 provenance（`user_stated` 与 `ai_asserted` 语气分级：
   前者「按设计决策应改料号」，后者「AI 草稿认为应改料号，请确认」）。
2. intent 无该位号决策 → **双向列出**（改值 or 改料号），并附 `intent-missing` 同族提示：
   写到哪个文件哪个键（`decisions[].value`）。
3. severity/verdict/退出码**一律不变**（方向是建议不是判决——A3 之前意图不进评级）。
4. 层规则：rules 侧 import `core.designintent` 是否合规，先查 `tests/test_layer_rules.py`
   的层表再动手；`run_review(model)` 的 intent 注入缝（参数怎么进规则）按层表允许的最小路径，
   选错了主代理复验会打回。

## 三、测试与验收

- 夹具：构造 MPN=100Ω / Value=0.1Ω 的冲突件 + 三态 intent（有 `user_stated` 决策 /
  有 `ai_asserted` 决策 / 无决策）→ 三种文案方向各自钉死。
- 真实案例证人：ctrl FOC 导出 + shipped intent → R4 那条冲突（若该板有）或等价形状的
  finding，建议方向 = 改料号、出处 = `user_stated`。
- 无 intent 文件时全规则行为**逐字节不变**（无合同=现状，钉一条回归）。
- 全量 pytest 绿（基线 **3007**），新测试进 `tests/test_091_intent_direction.py`；
  既有断言一字不改（若某条旧断言钉的就是「建议改 Value」的旧文案，列为「052 裁决改写」
  逐条报备）。
- 变异 ≥2 组（方向 helper 的两条支路各一组），cp+sha256 还原，禁 sed/禁 git apply。
- 文档：`docs/design-intent-channel.md` §三 A2a 行转「已落地」；SKILL.md 若引用了旧建议
  口径就同步。
- **删除一律进回收站（红线#4）**，禁 rm/rm -f/unlink，PowerShell `SendToRecycleBin` 通道。
- 纯离线、不动 git、不写 PROGRESS；交卷=改动清单/产出路径盘清结论/三态文案样例/变异记录/
  全量结果行/遗留项。

# 094 — A3b：采样链偏置闭合（F1 变规则）+ 合同接进 apply 走查

A 主线第三批下半（A3a `310b93b` 已立分级框架）。**先读** `docs/design-intent-channel.md` §三、
`tasks/093-A3a-arch-closure.md` 交卷 §8.1（F1 输入素材与两种形状）与 §8.3（apply 接线遗留）、
`src/boardwise/rules/archclosure.py` 的框架（`intent_grade()`/`INTENT_GRADES`）。

## 〇、实案锚（这条规则存在的全部理由）

FOC 偏置案（ctrl FOC `review-findings.md` F1）：双向电流采样（0.1Ω 直采进单电源 ADC）
需要把节点抬到 VCC/2；工程师「补了偏置」= R10/R16 各 1k 分压（内阻 500Ω）经 R17/R18
各 10k 送到 0.1Ω 节点 → `1.65V × 0.1/(500+10000+0.1) ≈ 15.7µV`，想要 1.65V 差 5 个数量级。
**偏置源阻抗必须 ≪ 采样电阻**，电阻分压+串阻物理上做不到。本批让它成为规则。

**两种形状都要处理**（A3a §8.1 实测）：导出夹具 =「完全无偏置」（`U+` 3 成员、无 VCC/2 网）；
真机现状 =「有偏置但源阻抗不闭合」。同一规则的两个档。

## 一、`arch-sense-bias-closure`（新规则，进 `INTENT_RULES`；archclosure.py 同模块）

判定顺序（每档都给出处与算术）：

1. **主题**：intent `signals[net].kind == "current-sense"` 且 `polarity == "bidirectional"`
   （或显式 `requires: ["bias-reference"]`）。无 intent → 零移动（框架既定）。
2. **豁免通道（合同侧小增量，本批带上）**：`signals[]` 条目加**可选** `closure: "waived"`
   ——工程师明示放弃闭合（实案：ctrl FOC 的 R4 决策「0.1Ω 直采不加放大器，接受正半轴
   ~7.8bit」）。`user_stated` 豁免 → **INFO**（引 rationale 原文）；`ai_asserted` 豁免 →
   **WARN**（草稿自己豁免自己不算数，052 §4）。shipped 的 `robot-ctrl-foc.intent.json`
   给 `U+`/`W+` 补 `closure: "waived"`（与 R4 决策一致，user_stated）。
3. **无豁免且无偏置网络**（导出档形状：信号网没有任何通往「分压样」中间网的电阻路径）
   → 按 `intent_grade()` 分级（`user_stated` 声明被违反 = **ERROR**）。
4. **有偏置网络 → 阻抗算术（本批的硬货）**：拓扑 = 信号网 S 经串阻 Rs 到偏置网 B，
   B 有 R_up 到 power-class 网、R_dn 到 gnd → `R_th = (R_up‖R_dn) + Rs`；
   偏置失误电压 `V_err = V_bias × R_sense/(R_th + R_sense)`（F1 原式）。
   - `R_th ≥ R_sense` → 形同虚设：按框架分级（ERROR/WARN），消息带全式数字
     （实案：10500 vs 0.1，V_err 15.7µV vs 想要 1.65V）；
   - `R_sense/10 < R_th < R_sense` → **WARN**（比值存疑，数字进消息）；
   - `R_th ≤ R_sense/10` → **INFO** 测量行（闭合成立，报 R_th 与 V_err）。
   - 「1/10」是本规则**自声明的判据**不是标准——写进 docstring（不发明标准纪律的
     例外处：数字随行，判据公开）。拓扑对不上（找不到 Rs/B 但信号网确实有外来电阻）
     → UNKNOWN + 点名去哪补，不猜。
5. 运放闭合形态（bias-reference 由运放输出直接馈入）检测：信号网直连运放输出脚
   （shelf 认 op-amp）→ INFO 闭合（输出阻抗 ~Ω 级，免检算术）。

## 二、合同接进 apply 走查（A3a 遗留③，小但关键）

`_baseline_findings`（`cli.py:13016` 一带）与 3 处 apply 路径的 `run_review(model)` 调用
全部带 `intent=`（合同解析按 A2b 的既有路径取）。接完后：**自洽 ERROR 在真机落图/编辑时
真的拦保存**（#55 分级下 force 不豁免）——A3a 只钉了机制，本批钉真联动。无合同逐字节
不变（既有口径）。CLI 次序与 notes 变化若有既有断言碰撞，逐条报备。

## 三、测试与验收

- 夹具三形状：无偏置（导出档形状）/ 弱偏置（VCC/2+10k 合成模型，算术逐数对照 F1）/
  运放闭合 + 豁免两态（user_stated/ai_asserted）。
- 真实案例证人：ctrl FOC 导出 + shipped 合同（补 waived 后）→ `U+`/`W+` 报 INFO 豁免行
  （引 R4 rationale）；**撤掉** waived 的变体合同 → ERROR 无偏置行（user_stated 被违反）。
- 联动：带合同的 apply 走查遇自洽 ERROR → exit 2 不保存（force 仍拦）；遇 WARN → force
  才放行并留痕（#55 既定）。
- 全量 pytest 绿（基线 **3087**），新测试进 `tests/test_094_sense_bias.py`；
  既有断言一字不改（apply 接线碰撞逐条报备）。
- 变异 ≥2 组（阻抗算术一档 + 豁免通道一档），cp+sha256 还原。
- 文档：`docs/design-intent-channel.md` §三 A3 行转「已落地」；规则判据（1/10）与拓扑
  定义进模块 docstring；SKILL.md 同步「合同进 apply 走查」。
- **删除一律进回收站（红线#4，再强调：临时产物也走 PowerShell 通道，没有例外）**；
  纯离线、不动 git、不写 PROGRESS。
- 交卷：改动清单/五档文案样例/F1 算术逐数复算对照/豁免后 ctrl FOC 实录/apply 联动实录/
  变异记录/全量结果行/遗留项。

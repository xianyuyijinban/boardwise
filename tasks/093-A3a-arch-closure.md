# 093 — A3a：架构自洽分级框架 + 三条闭合规则（异压 / 开漏上拉 / NRST）

A 主线第三批上半（A1 `b21089a` / A2a `ab6aa10` / A2b `aceda21`）。
**先读** `docs/design-intent-channel.md` §一.2/§三 A3、`tasks/092-A2b-rail-ratings.md` 交卷遗留③。

## 〇、本批的口径核心（自洽分级框架，写进规则模块 docstring）

A3 起 intent **可以**进评级，但 052 §4 的红线不落笔不成文：

| 情况 | 级别 |
|---|---|
| 违反 **`user_stated`** intent（工程师自己声明的架构被图纸违反） | **ERROR** |
| 违反 **`ai_asserted`** intent（AI 草稿与图纸不一致） | **WARN**（草稿不一致，请确认） |
| 无 intent | **不查，零移动**（无合同行为逐字节不变，A2 口径延续） |
| 不依赖 intent 的**结构性**闭合（本批的开漏上拉、NRST） | 直接 **WARN**（有出处、点名、给修法） |

联动（已有机制，不改代码）：自洽 ERROR 在 `edit/draw apply` 的 findings 闸下会被 #55 的
分级**必拦**——这是正确行为，钉一条测试见证；checkup 的 verdict/退出码/schema `/6` 不动。

## 一、三条规则（新模块，进 `BUILTIN_RULES` + `INTENT_RULES` 中需要合同的两条）

### R1 `arch-rail-voltage-clash`（A2b 遗留③，依赖 intent）

合同与图纸对**同一轨**给出不同电压：`requirements.rails[net=…].targetVoltage`（解析量）
vs `core.power_domains.infer_net_domains` 的图上判定。异压 → 按框架分级（user_stated 合同
被违反=ERROR、ai_asserted=WARN）；**两个来源的原始字段与值都进消息**（谁错人裁，工具
只说「两处说得不一样」）。图上判不出 → 不查。

### R2 `arch-opendrain-pullup`（F2 nFAULT 案，结构性、不依赖 intent）

- **数据侧（本批带上）**：blocklib shelf 的 DRV8313PWPR 条目补 `category` + facts——
  nFAULT(pin18) 标 `open_drain: true` / `pull_required: true`（手册 p.3 原文：open-drain
  output requires an external pullup）；VM(pin4/11) 的 required_caps 各 0.1µF（同页，
  给 decap 既有机制喂料）。这是 issue #56 数据侧的落地；**工具侧（IC_PATTERN 放宽）不在本批**。
- 规则：shelf facts 标了 `pull_required` 的脚 → 所在网成员里有电阻跨到 power-class 网
  = 闭合（INFO 测量行）；没有 → **WARN**：点名脚、网、手册出处、修法（加 10k 上拉）。
  intent `decisions[]` 声明了「该脚用 MCU 内部上拉」且 provenance `user_stated` → 也判闭合
  （INFO 行注明依据=设计决策）——F2 案里「固件开内部上拉」的合法出路。

### R3 `arch-nrst-closure`（F3 案，结构性）

shelf 认出 MCU（category=mcu 或既有识别路径）→ 其 NRST/RESET 脚所在网：成员数 == 1
（裸奔：无电容/无按键/无测试点/无编程器）→ **WARN**：点名脚与网、后果（随机复位风险、
无 connect-under-reset 通道）、修法（100nF 到地 / SWD 座引 NRST）。有成员但全是
「看不见的连接」（网络标签到另一页的单成员网）→ 同上（F3 实案就是这个形状）。

## 二、测试与验收

- 夹具：R1 异压两态（user_stated/ai_asserted）+ 无合同零移动；R2 上拉有/无/决策闭合
  三态（shelf 注入带 `pull_required` 的假件）；R3 裸奔/有电容/跨页标签三态。
- 真实案例证人：ctrl FOC 导出 + shipped 合同 → R2 应报 nFAULT（DRV1.18）无上拉
  （板上确实没有——F2 实案由规则复现）；R3 应报 U1.7 NRST 裸奔（F3 实案由规则复现）；
  R1 该板合同与图同压 → 不报（阴性对照）。
- **联动见证**：构造带 R1 ERROR 的板走 `edit apply` 的 findings 闸 → ERROR 必拦（#55
  分级下 exit 2）；WARN 不拦但进报告。
- 全量 pytest 绿（基线 **3055**），新测试进 `tests/test_093_arch_closure.py`；
  既有断言一字不改（冲突停下报主代理）。
- 变异 ≥2 组（R2 的 WARN 支路 + 分级框架的 user_stated→ERROR 支路），cp+sha256 还原。
- 文档：`docs/design-intent-channel.md` §三 A3a 行；分级框架表进模块 docstring 与该文档
  §三；SKILL.md 同步「intent 进评级」的口径变化（这是 A1 以来第一次）。
- **删除一律进回收站（红线#4）**；纯离线、不动 git、不写 PROGRESS。
- 交卷：改动清单/框架分级样例三态/ctrl FOC 实录（R2 R3 复现案、R1 阴性）/联动见证/
  变异记录/全量结果行/遗留项（A3b 的输入素材清单）。

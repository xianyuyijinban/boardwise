# 092 — A2b：checkup 接线合同进走查 + rail 声明驱动「额定与降额」

A 主线第二批的下半（A2a 已落账 `ab6aa10`）。**先读** `docs/design-intent-channel.md` §三、
`tasks/091-A2a-params-fix-direction.md` 交卷遗留项 1（时序接线）、A1 的 `arch --intent` 口径。

## 一、checkup 接线：合同真正走进规则走查（A2a 遗留）

- 现状：`_cmd_checkup` 里 `run_review` 发生在 shelf/架构枚举/合同加载**之前**，所以
  `checkup --intent` 只驱动报告 intent 节，规则走查吃不到合同。
- 改法：把「shelf 加载 → 架构枚举 → 合同解析（默认位 `~/.boardwise/design-intent/<uuid>.json`
  或 `--intent`）」整体提到 `run_review(model, intent=…)` 之前；`IntentSource.load` 读盘
  只在 cli/checkup 层（rules 不碰盘，A2a 层表结论不破）。
- **notes 顺序会变**：先盘 `tests/` 里钉 checkup notes/报告顺序的断言，碰了就逐条列为
  「A2b 接线改写」报备；退出码/verdict/schema `/6` 一律不动。
- 无合同（默认位无文件、未给 `--intent`）行为**逐字节不变**（A2a 的零移动口径延续）。

## 二、rail 声明驱动「额定与降额」（新规则模块）

新规则文件（命名按仓库惯例，如 `rules/railratings.py`），进 `BUILTIN_RULES` +
`INTENT_RULES` 表（A2a 留的接入点）。**两条检查，同一纪律：测量永远报（INFO），
只有拿得准的越限才 WARN，读不到就 UNKNOWN 并点名去哪补**——不发明降额标准。

- **R1 电容耐压 vs 轨压**：intent 的 `rails[].targetVoltage`（解析成量）× 板上电容的
  额定电压（shelf facts / 值字段 / MPN 解码，按既有取值顺序）。三态：
  rating ≥ rail → INFO 测量行（报比值）；rating < rail → **WARN**（这是确定的越限，
  不是降额口味）；rating 读不出 → UNKNOWN + `needs_datasheet` 同族点名
  「C? 的耐压（所在轨 +24V=24V）」。ctrl FOC 的 C4/C5/C6/C9 就是 UNKNOWN 实案。
- **R2 LDO 耗散估算**：shelf facts 已认 LDO（AMS1117 族）；intent 给输入轨/输出轨
  `targetVoltage` 与输出轨 `continuousCurrent` → `P=(Vin−Vout)×I`。限值从 shelf facts 读
  （facts 没声明 maxDissipation 就**只**报 INFO 测量行，不编封装限值）；超限 → WARN；
  电流没声明 → `intent-missing` 点名 `requirements.rails[net=…].continuousCurrent`。
  实案锚：12V→3.3V 的 AMS1117（压差 8.7V）。
- 两条都过 A2a 的 `_rules_for` 缝（新实例带 intent，不碰共享实例）。

## 三、测试与验收

- 夹具三态各钉：耐压足/不足/读不出；耗散可算/超限（shelf 注 limit）/电流未声明。
- 真实案例证人：ctrl FOC 导出 + shipped 合同跑 checkup——报告里 R1/R2 的 INFO/UNKNOWN
  行要指得对（C 系电容 UNKNOWN 名单、AMS1117 的 INFO 行带 8.7V 与 intent-missing 电流槽）。
- 全量 pytest 绿（基线 **3028**），新测试进 `tests/test_092_rail_ratings.py`；
  既有断言一字不改（时序接线碰的逐条报备，预期是 notes 顺序类）。
- 变异 ≥2 组（R1 的 WARN 支路 + 接线时序各至少一组），cp+sha256 还原，禁 sed/禁 git apply。
- 文档：`docs/design-intent-channel.md` §三 A2b 转「已落地」；新规则的「不发明降额标准」
  纪律写进模块 docstring；SKILL.md 若引用旧口径就同步。
- **删除一律进回收站（红线#4）**；纯离线、不动 git、不写 PROGRESS。
- 交卷：改动清单/时序重排的断言影响清单/R1R2 三态样例/ctrl FOC 实录/变异记录/全量结果行/遗留项。

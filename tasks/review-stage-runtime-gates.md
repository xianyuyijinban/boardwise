# 审查分阶段交付的运行时闸 — 规划（本批未实施）

> 状态：**规划/本批未实施**。这份文件只写「缺口是什么、验收怎么打」，
> 仓库里**没有任何一行**代码在做下面的事。SOP 的 [`docs/review-sop.md`](../docs/review-sop.md)
> §3.0a 已把 AI 侧纪律写死，但纪律不是闸：同一基准重复 checkup 照样跑，
> 第三次 DRC 照样跑，私有动作照样能调。本文列的四件是把纪律变成机器行为的候选，
> **全部未落地**，不得在报告或交付里写成「已实施/已拦住」。

## 背景（现状，可核对）

SOP §3.0a 定下的四条纪律——首轮检查点先交付、每批 ≤3 finding/约 15 分钟/约 30 分钟
必交付、同基准无新证据不重算、中止后只读出 `partial`——目前**只有文档约束**。
机器侧实际存在的东西很窄：

- `review-read` 的四节投影对同一份 `report.json` 输出稳定（不产生新结论）；
- `review finalize` 在披露一致时校验 `partial` 交付、签 CLI 收据（内存 re-gate，不采集）；
- [`tests/test_review_stage_delivery.py`](../tests/test_review_stage_delivery.py) 的匿名
  after-first-checkup 钉证明：中止后上面两条不必再调 `checkup` / 采集。

这些**都不拦截另起一次 checkup**，也不构成全局去重。下面 R1–R4 是缺口清单。

## R1 — 版本化 RunManifest 与语义 diff

**缺口**：现在没有一份「这次 run 冻了什么」的机器可读记录，所以「同基准」只能靠人记。

**候选形态**：`checkup`（以及任何开启一次审查的入口）落一份 `run.json`：
`{schema, runId, inputs:[{path, bytes, sha256}], engine:{boardwise, ruleset, rulesetHash},
intent:{path,sha256}, pages:[uuid…], channels:{liveSchematic, archivePcb, livePcb, schematicImage,
pcbImage, datasheets}, modelCounts:{components, nets, datasheetsMissing}}`。
两份 manifest 的**语义 diff** 输出 `{addedFindings, removedFindings, coverageChanged,
inputsChanged}`，而不是「报告文件不同」。

**验收（匿名合成）**：两份合成 manifest，输入哈希相同/引擎相同/intent 相同 → diff 报
`sameBaseline: true`、无 finding 增删；只换一个输入哈希 → `inputsChanged` 恰好一项；
同时换归档与活动页 → 标 `multi-variable-change`、**拒绝单因子归因**（语义差异清单
照出，只是不许把它归给某一个变量），findings 仍不混。

**边界**：`shared/CLI` 改动走 [`tasks/shared-platform.md`](shared-platform.md) 的集成锁；
不碰规则引擎、不碰 parser 输出形态。

## R2 — CLI 重计算 guard（新证据理由、DRC 次数）

**缺口**：`checkup` / `run_pcb_review` / DRC 复核没有次数感，`reject-use-existing` 与
`reject-needs-new-evidence` 只写在策略表里。

**候选形态**：一个显式的 guard 层。可以先做 opt-in 的 `--strict` 路径做兼容验证，
但**只有实际启用的拒绝路径通过验收后才算硬约束**；只打印警告永远不算。

- 同输入哈希 + 同引擎 + 同 intent + 无新证据 → `reject-use-existing`，打印「复读
  `review-read` 即可」；
- 同一基准第 3 次 DRC 复核 → `reject-needs-new-evidence`，要求 `--new-evidence <理由>`
  且理由可核对（新导出哈希 / 新页面 / 新手册事实）；
- 计数落在 R1 的 manifest 里，**不进报告 schema**，避免把调度状态混进板级结论。

**验收（匿名合成）**：合成目录 + 假 manifest，连跑两次 → 第二次 `reject-use-existing`、
**不写任何新报告**，并用假引擎证明**第二次没有调用引擎**（调用计数为 0）；第三次
DRC → `reject-needs-new-evidence`；带新证据理由 → 放行且恰好调用一次；拒绝的退出码
与「坏输入 2 / 有 ERROR 1」不冲突。

**边界**：先 opt-in 不等于「可选功能就算完成」——警告永远不算硬约束，只有启用后的
拒绝路径（且验收证明没调引擎）才算；默认行为若要改，必须先走集成锁与真机验收。

## R3 — harness checkpoint / 批次预算 pre-execute 硬闸

**缺口**：「一次 checkup 后先交付首轮检查点」与「约 15/30 分钟」现在靠 AI 自觉；
没有 pre-execute 拦截。

**候选形态**：在 harness 侧（DSH 客户端插件或 skill 加载后的第一步）加一个
pre-execute 检查：没有 `initial/partial` 检查点就发起的第二批深挖被拒绝执行，并要求
「先交付检查点」；批次预算报**已用步数/已用墙钟**，到线时**允许当前只读命令收尾**，
但**拒绝下一项深挖/重计算**直到阶段交付完成；中止时只出只读 `partial`，
**不杀进程冒充交付**。

**验收（匿名合成）**：假 harness 状态机，越过检查点直接进第二批 → 被拒并给出「交付
检查点」的下一步；已交付检查点 → 放行；预算到线 → 当前只读命令可跑完、下一项深挖被拒，直到阶段交付；
中止路径只出 `partial`，不许把杀进程写成「已交付」。

**边界**：DSH 运行进程需**独立加载验证**（重启 + 新闸生效要真跑一次），不能在未重启时
声称已加载；这一项不改变 CLI 行为。

## R4 — 中断 partial 状态机与四分类校验 / 公开接口 allowlist

**缺口**：`partial` 的「已确认/疑似/未验证/未覆盖」四档与 `needs-manual`/`open-item`
没有机器校验；「只用公开接口」没有 allowlist。

**候选形态**：

- `review finalize` 在 `partial` 上校验四档齐全、每档有计数，缺档报 issue（不猜补）；
- 公开接口 allowlist：CLI 公开子命令 + `review-read` 的公开 sections；越界调用（私有 bridge
  动作、手解析内部文件）在**受管入口**上直接**拒绝**并记一条 `tool-gap`；无法识别
  的命令保留为**覆盖缺口**如实披露，不假装已覆盖；
- 中止路径的验收：只读已有产物即可出 `partial`，不新跑 checkup / 采集。

**验收（匿名合成）**：合成 `partial` 报告（四档齐全、缺一档）→ 前者校验通过、后者
点名缺哪一档；中止后走 `review-read` + `review finalize`，断言三个入口未被调用
（沿用匿名 after-first-checkup 钉的写法）。

**边界**：四档是**披露**校验，不是板级结论；不得把「四档齐全」读成通过。

## 非目标

- 不改规则、finding 文案与评价口径；
- 不做 parser / 缓存 / 性能大改；
- 不碰 Rust workspace；
- 不用真实日志或真实工程做验收（全部匿名合成）；
- **不承诺**「固定分钟数完成整板审查」——R3 只用已用量决定何时拒绝下一项深挖并要求阶段交付，
  不承诺固定分钟 SLA。

## 顺序与依赖

R1 是 R2/R4 的数据基础（manifest 里才有 baseline 与次数）；R3 独立于 CLI，可与 R2 并行
但不同批。任何 `shared`/CLI 改动走 [`tasks/shared-platform.md`](shared-platform.md)
集成锁，串行落地；每项落地前先在对应任务书里写清本批边界与匿名验收，落地后把本文
对应小节改成「已实施 + 证据路径」——**在那之前，这四项都只是规划**。

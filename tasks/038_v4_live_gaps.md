# V4 在线证据三缺口根因与修复计划（2026-10-31）

> 岳要求主代理追根因并解决。工作树含 #89、038F、调研等未提交改动，禁止覆盖/整理；
> 不做 git 写、设计写入、编辑器重启或发布。当前工程只读授权继续有效；connector 热更如需，
> 必须另行逐项申请。

## 原则

- 先根因后修复，不能把 failed 简单改 not-applicable 来“变绿”。
- V3/V4 在宿主适配/采集层分叉；报告 schema、conclusion、规则和证据词汇继承。
- 每批一个文件域、一个完成条件；shared/CLI/connector 不夹批，真机串行只读。
- 不把空模型、缺图、unparsable、超时或归档证据写成通过。

## 批次

### O1 schematic 容器 vs page

根因候选：V4 的 schematic 容器不再产生 tab，但 review-evidence 仍对容器 doc.open，
连带 liveSchematic/schematicImage failed。完成条件：只对可寻址 SCH_PAGE 采集；容器身份保留为
元数据/not-applicable，不触发无意义 doc.open；P1/P2 实际 readback/netlist/render 成功，
focusRestore 仍成立，V3 行为不回归。

### O2 PCB render 超时

先实测激活/调用/返回耗时，区分页面未激活、10s 硬超时、宿主持续不返回和 connector 参数差异。
完成条件：在 V4 当前工程 PCB1 上取得真实 PNG 并亲眼复核，或拿到可复现的宿主限制并给出
最窄修复。不得用原理图成功替代 PCB 成功，不得仅把 timeout 藏起来。

### O3 ERC 每页 519 条 unparsable

先抓原始响应结构并对照 connector/parser 期待，区分 V4 schema 改变、主机聚合口径、
字段类型漂移和真实 ERC 条目。完成条件：能解析的逐条正确解析；真正不可解析的保留计数与原因，
total=0/passed 不得冒充零问题。V3 响应兼容，DRC 退出码/conclusion 不被涂改。

## 验收

- 单元/邻域测试、至少两处变异与 cp 恢复 SHA；主代理抽 diff 和独立变异。
- 实际 V4 只读复验：doctor/probe、checkup、review-evidence；liveSchematic/pcbImage 目标状态
  按真实采集，不预设全 ok。记录真实 exit、focusRestore、通道状态与图像证据。
- 若生产修复需要更新运行中的 connector：先完成离线测试，再申请热更；未热更前不得宣称在线已修。
- 最终全量 Python/connector/DSH/Rust/跨语言按批次需要串行，既知 MSYS红不隐瞒。

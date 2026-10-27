# 542 — 原理图绘制 3.0：2026-11-01 可用版与 V4 交接

- 立项：2026-10-27（岳要求 11 月 1 日完成 3.0，之后转立创 V4 与规则）。
- 集成分支：`drawing-line` / `E:\boardwise-wt-draw`；主工作区未提交 201H 副本继续保留。
- 版本口径：这里的「3.0」是第三阶段可用绘制里程碑；对外版本号仍沿 `docs/roadmap.md`
  与 `tasks/SCHEDULE.md`，不擅自把 package 从 0.5.22 跳成 3.0.0。
- 证据：`evidence/542/`、`.tmp_542_*`；常规测试使用各批独立 `.tmp_pt_542_*`。

## 1. 当前基线（已发生，不是规划）

- `4644f99f2a432320a9deb418f6e88958eb2fd3bd` 已完成 201H T1 值可见性并推到
  `origin/drawing-line`；远程哈希一致。主工作区 HEAD 与未提交副本未清理。
- 离线检查已有：Python 8213/97/0、Rust 45/4、connector 536、dsh-plugin 127/1；
  后续节点仍须按自己的改动重跑邻域与全量，不能只引用旧读数。
- T1 的真实 `valueVisible=false`、位号可见、Value、PNG/SVG 视觉和 `saved_unverified`
  已由独立后续读数确认；守护脚本自身的 `readBack=differs` 退出保留，未伪报通过。
- **P4 机器与代理视觉门已关闭（2026-10-27）**：最终页 `/test` P4
  `b0066b440b3eee95` 单次 apply 通过；fresh netlist 19 件/16 网/44 源脚/46 物理脚/0 失配，
  T3.2/T3.5 NC；live 与 captured-pair lint 均 0/0/0；12 个网名最长 run 全水平。
  主代理和独立代理均实际查看宿主 PNG/SVG，独立 verdict=approve；证据 `evidence/542/final-p4.md`。
- **两项人工门也已关闭（2026-10-27）**：岳对 P4 的最终人眼问题选择“通过”；随后真实关闭/
  重开 `/test` 并聚焦 P4，`persistence --baseline` exit 0，明确返回 `saved_verified`
  （39 components / 21 nets / 57 primitives）。基线与重开快照均在 `evidence/542/`。
- **542 P0 提前完成并冻结候选**：C9 标题栏薄余量、13 条软 grammarFindings、工程级同名公司
  等只在 `evidence/542/final-p4.md` 保留披露，不再为本里程碑加功能。CH343 未挤占 P0；
  V4 仍只在 11 月 1 日后按 §7 实施。正式 semver/tag/release/merge 未执行。

## 2. 范围与优先级

### P0 — 11 月 1 日必须有

1. 当前反激候选可复现：`draw compile` `ok=True`，硬 violation 为 0；tolerated 若存在，
   必须逐条解释，不提高容忍额度。
2. 在 `/test` 的**空白**目标页完成 apply；页内已有内容就停止检查，不清理别人的现场。
   对照源 circuit 网表逐脚回验 0 失配，`draw lint` 通过，PNG/SVG 逐岛视觉自审。
3. 关闭 U4、输出岛、文本间距/交叉/密度中阻碍人读的最小缺口；每批只修一个缺口、
   一个文件域，给前后指纹/图像。不得用挪模型盒子、提高 cap 或隐藏 R/C/L/IC/reference
   来假绿。
4. 四条缝独立挖洞并分批修复：编译布局、布线/旗标/连通、宿主 apply/readback、
   SVG/S-01…S-21 视觉。挖洞只交可复现问题，修复另批。
5. 候选冻结前完成全量 pytest、connector、dsh-plugin、Rust、真实 test 页验收和保密/卫生闸；
   提交并 push 每个通过节点。

### P1 — 不挤占 P0

- 534 CH343 UART 全新设计 dogfood（datasheet、spec、三件套、三关与 checkup）。
- 10 月 29 日若它影响反激三关或 RC 冻结，就移到后续小版本，不为了范围牺牲 deadline。
- 201C 复活、通用全自由绘制、PCB 自动布局布线、Rust 大规模翻译、V4 实施均不在本批。

## 3. 倒排执行表

| 日期 | 节点 | 完成条件 |
| --- | --- | --- |
| 10-27 | N0 集成 + N1 基线 | 201H 推送完成；542 任务书；独立视觉挖洞交回；当前反激准确命令/读数/首个 P0 缺口确定 |
| 10-28 | N2 单缺口攻坚 | U4 或输出岛最高优先问题修复；前后 SVG/指纹；邻域测试；独立复审 |
| 10-29 | N3 整页三关 | 空白 test 页 apply、逐脚 0 失配、lint、整页视觉；P1 CH343 仅在不影响 P0 时推进 |
| 10-30 | N4 稳定化 + RC | 四缝挖洞修复收口；全量四线/Rust；apply/readback/save/render 证据；只许 P0 修复 |
| 10-31 | 候选冻结 | 不再加功能；最终全量、真机、保密/卫生、release candidate 说明与剩余披露全部齐备 |
| 11-01 | 交付与切换 | 岳一次看图/试用；记录最终人工裁定；交付 3.0，转 V4 路线，不继续无边界优化 |

## 4. 每批执行卡（硬约束）

1. **一派单一缺口**：任务书写明文件域、基线、相邻测试、完成条件；shared parser/model/
   bridge/core/CLI 另走集成锁，算法与迁移不同批。
2. **挖洞 ≠ 修复**：独立代理只读复现最多 3 条问题；主代理选 1 条后另派修复。
   并行最多两个不重叠文件域；子代理 ≤40 步/30 分钟，结论 ≤2000 字，主代理审关键 diff。
3. **测试节奏**：开发跑聚焦；节点验收跑完整四线/Rust。全量一次只跑一轮，`-n 4
   --dist loadfile`，独立 basetemp；失败后先聚焦，完整复跑最多一次，第三轮必须说明。
4. **真机串行**：先 `bridge status` + `doc.list` 逐字核对 `/test` 或 `/test2` 和页 UUID；
   不碰真实工程，不新增/删除器件来绕过失败，不在超时后盲目重试。
5. **三关不可互相替代**：compile/readability、逐脚连通、PNG/SVG 视觉分别留证据；
   视觉除主代理外必须有独立代理看图，最终人工锚由岳裁定。
6. **提交与推送**：每个节点修复+独立复审+真实测试后，主代理审 staged 清单再 commit/push。
   push 不等于正式发布；正式版本号/tag/release 由岳在候选验收时一次决定。
7. **工作区红线**：不清理 C 盘、不直接删除文件、不碰 `E:\boardwise-wt520` 档案、
   不移除 worktree、不改主工作区未提交副本；临时物按批次落 `.tmp_542_*`。

## 5. 验收矩阵

| 关 | 必须回答 | 证据 |
| --- | --- | --- |
| 编译/可读性 | `ok=True`、hard=0；tolerated 是否逐条可解释 | compile JSON、layout/SVG、前后指纹 |
| 连通 | 源 circuit 每个 part.pin 与宿主网表一致，0 失配 | plan/apply 报告、宿主 netlist/readback |
| lint | 页内压线/重叠/出界/同名导线段无未解释硬项 | `draw lint` JSON |
| 视觉 | 每个岛是什么、怎么接、与网表是否一致；一眼能读信号流向 | 主代理 + 独立代理 PNG/SVG 审查，岳最终裁定 |
| 持久化 | 区分 placed / saved_unverified / saved_verified | save 回执与（若另批授权）重开读数 |
| 回归 | 当前节点四线/Rust及卫生闸真实读数 | 命令、计数、日志路径、commit hash |

## 6. 风险与降级

- **整页视觉仍是最大风险**：机器 ok 早已达到，不能拿旧 metrics 冒充人读通过；优先修
  U4/输出岛和文本间距，而不是扩新器件库。
- **worktree 证据不全**：未入库 outputs/私有夹具的 skip 不冒充已验；发布前在主证据环境
  复跑必要项，但不能复制真实工程容器或公司板进仓库。
- **宿主写回并非总是 identical**：先只读确认实际状态，绝不重试造成双倍写入；保存与
  持久化分级如实披露。
- **远程/凭据故障**：优先用本机已有 `gh` 临时 credential helper，不改全局配置、不打印 token；
  远程故障不得阻塞本地关键路径，但最终节点必须有远程哈希。
- **降级顺序**：CH343 → 非关键性能优化 → 非关键重构；反激三关、独立视觉和回归不降级。

## 7. V4 交接（11 月 1 日后启动）

按 `tasks/038-eprj3-tierA.md` §V4 与 TASKMAP V4 行执行，不在 3.0 关键路径提前实施：

1. 真 V4 `doctor` + 一块板 `checkup`，与既有结果包逐字段对拍；
2. connector-on-V4 API/arity 探针重跑，建立支持矩阵，不凭类型声明写实现；
3. `.eprj3` 真样本验证 yAxisDirection / NC 引脚 id / CANVAS 缺失；
4. V4 菜单的 `.eprj2` 导出引导与本地保存格式核对；
5. 规则与绘制迁移分小批，算法和宿主迁移不同批，先合同对齐再接 adapter。

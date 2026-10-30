# 任务全图（TASKMAP）

> **这份文件回答「这个仓库做过什么、现在在哪、还有什么没做」**，按任务编号索引。
> 它不是流水账——流水账在 `PROGRESS.md`（按时间 append，只用于查历史细节）。
>
> **AI 恢复上下文的最小路径**：
> 1. `docs/roadmap.md` §1-§2（当前在哪、版本骨架）→ 2. 本文件 §0（在途/搁置）→
> 3. 你要做的任务的 `tasks/<批号>*.md`（规格）→ 4. 需要历史细节才 grep `PROGRESS.md`。
>
> **状态口径**（五选一，取该编号最后一次记录）：
> `已落` = 已 commit 并推送 · `工作树` = 已完成未提交 · `搁置` = 明确踢出/hold ·
> `在途` = 子代理正在跑 · `规划` = 任务书写了未开工。
>
> **证据**列原样抄自 PROGRESS 行里的路径/commit；空白 = 该行没写路径。
> 只做聚合，不重述结论；细节打开对应任务书/证据目录。

---

## §0 当前在做（截至 2026-10-30）

- **已完成、未提交**：`540`（0.6.0 前平台准备）——540A/B/C 已验收，并在对抗修复与
  只读真机追加验收后收口；142 模块/0 legacy、24 个 CLI 命令和 DSH 10 工具面保持兼容，
  Rust 合同、差分与最小 workspace 已实际运行。**读数要分层，别混用**：
  - 首轮全量 `evidence/540/final-regression.md`：Python **7876/21/5**、connector **536**、
    DSH **122/1**、Rust **7**、4 case；
  - 对抗后首轮 `evidence/540/final-regression-adversarial.md`：Python
    **8206 passed / 19 skipped / 5 xfailed / 1 failed**（唯一红是 rulebody 源码指纹钉，
    已按 B2 下沉补钉）、connector 536、DSH **127/1**、Rust **45 + 显式 4**、5 case；
  - **最终候选读数以 `evidence/540/candidate-regression.md` 为准**（该文件由后续步骤
    产生，未产生前**不算通过**）；本轮收口摘要 `evidence/540/final-regression-followup.md`。
  - 真机只读：`evidence/540/real-machine-instance-20261025-233933/25-final-report.md`
    与 `outputs/review/540/`——`conclusion=incomplete`（0 器件 0 网络）、`delivery=partial`，
    **不是板级通过**。
- **已验收、已提交**：`537` 审查流程与 `538` 块级独立子岛编译，随 `539` 的
  `0f638de` 一并入库，并含在 0.5.22 历史中。其 2026-10-25 基线复跑为
  Python **7708 passed / 19 skipped / 5 xfailed**，connector **536 passed** + typecheck，
  DSH **113 passed / 1 skipped** + typecheck + build；不把这些旧读数冒充 540 最终全量。
- **已验收、已提交**：`539` 的 F1–F9、对抗审查、只读真机与全量复核，
  commit `0f638deaa5d089194e8addf2d400cb7422d422bf`；其后 0.5.22 的
  `63df468`/`23f030f` 已包含它。真机结论为
  `completion=incomplete / delivery=partial`，不是板子通过，也不是 540 的提交。
- **工作树**：当前含 `540`、`200A/B/C`、`#87④` 等未提交改动，按各自任务书归属，
  不把整棵脏树算进单一批次；旧 `520k–533` 岛系列的状态见下方各行与 `docs/handoff.md`。
- **0.6.0 门槛**：`200A/B/C` 工作树完成、审查线验收通过（证据 `outputs/200/acceptance.md`）；
  整体 Python 全量仍有 MSYS 与绘制线两个域外红项。发布候选必须先报证据，何时发布仍由岳决定。
- **0.6.0 后**：绘制算法与 Rust strangler 双主线并行；共享底座、全量测试与真机串行。
  0.6.x / 0.7.0 的验收边界由 540 同步进 roadmap、SCHEDULE 与 handoff。
- **既有搁置不变**：`201C`、`121b`、`text_overlap` 与 `R4` 阶段二；540 不顺手复活。

---

## 001–099

| 编号 | 主题 | 状态 | 证据/任务书路径 |
|---|---|---|---|
| M0 | 基线统一入口与持久化基线 | 已落 | tag `m0-baseline`；docs/persistence-baseline.md |
| M1 | 原理图审查可用（15规则+度量机具） | 已落 | `5958b1c`；tasks/011-review-rules-m1.md |
| 009d | 持久化基线三态 | 已落 | tasks/009d-persistence-baseline.md |
| 009d2 | 断连诚实（exit 3） | 已落 | tasks/009d2-disconnect-honesty.md |
| 010 | LDO 惯用法 AMS1117 | 已落 | tasks/010-ldo-idiom-ams1117.md |
| 010b | place_wire 锁窗重试（0.4.5） | 已落 | `d409026`；tasks/010b-placewire-retry.md |
| 010c | 坐标约定定案 | 已落 | `ce044a6`；tasks/010c-coordinate-convention.md |
| 011 | M1 审查规则批 | 已落 | `5958b1c`；tasks/011-review-rules-m1.md |
| 011b | facts 库 | 已落 | tasks/011b-facts-library.md |
| 011c | 连接器供电路径规则 | 已落 | tasks/011c-conn-pwr-path-rules.md |
| 011d | decap/param 注入件 | 已落 | tasks/011d-decap-param-injection.md |
| 011e | M1 晋级判据 | 已落 | tasks/011e-m1-graduation.md |
| 012 | 基础体验（内测 0.4.6） | 已落 | `e2bb78c`；tasks/012-basic-experience.md |
| 013 | 真机验证（0.4.10） | 已落 | `1798d7e`；tasks/013-realhost-verification.md |
| 015 | M2 规则批①②（容忍度） | 已落 | `501a2f4`/`5ff0a1d`；tasks/015-review-rules-m2.md |
| 016 | review-to-local-edit（M3 首切片） | 已落 | `15b3da2`；tasks/016-review-to-local-edit.md |
| 017 | 评测集扩充（度量机器/泛化结论） | 已落 | tasks/017-eval-set-expansion.md；outputs/017_* |
| 018 | 朋友内测基础体验 | 已落 | `15b3da2`；tasks/018-beta-basic-experience.md |
| 019 | 空板提示 | 已落 | tasks/019-review-empty-board-hint.md |
| 020 | 上游 issue 加固 | 已落 | `ffbdf77`；tasks/020-upstream-issue-fixes.md |
| 021 | 多工程=多窗口实测 | 已落 | `d70f59b`；tasks/021-multiproject.md |
| 022 | 全新 clone 三 issue | 已落 | `4448c59`；tasks/022-fresh-clone-issues.md |
| 023 | 多窗口路由 | 已落 | `383e524`；tasks/023-multiwindow-routing.md |
| 024 | 3.2.149 bootstrap（0.4.12） | 已落 | `ac465ae`；tasks/024-easyeda-3.2.149-bootstrap.md |
| 024b | About box 读共享运行时（0.4.13） | 已落 | （无独立任务书） |
| 025 | checkup 一条命令（0.4.14–0.4.16） | 已落 | tasks/025-review-flow-v2.md；outputs/025_* |
| 025e | update-connector 假失败修复 | 已落 | outputs/025e_update_connector_false_failed.txt |
| 026 | Worker 闹钟形态定案 | 已落 | tasks/026-worker-watchdog.md；outputs/026_probe.md |
| 026b | Worker 闹钟实现+规格修正 | 已落 | tasks/026b-worker-watchdog-impl.md；outputs/026b_* |
| 026c/026d | 闹钟规格两轮修正 | 已落 | outputs/026c_*；outputs/026d_* |
| 027 | EDITOR_API_FLOOR (3,2,149) | 已落 | tasks/027-editor-api-floor.md |
| 028 | 内测分发三件套（0.4.19） | 已落 | tasks/028-distribution-trio.md |
| 029 | add-component（M3 第2片） | 已落 | tasks/029-edit-add-component.md；outputs/029b_* |
| 030 | update-connector 多窗三档 | 已落 | tasks/030-update-connector-multiwindow.md |
| 031 | export.render PNG 超时→SVG 回退（0.4.20） | 已落 | tasks/031-export-render-png-fallback.md |
| 032 | export.render toast 自清除（0.4.21） | 已落 | tasks/032-export-render-toast-teardown.md |
| 033 | export.render 导出前自激活（0.4.22） | 已落 | tasks/033-export-render-auto-activate.md |
| 034 | activateExportPage 三步补齐（0.4.23） | 已落 | tasks/034-activate-export-page-full.md |
| 035 | patch-pin（M3 第3片） | 已落 | tasks/035-patch-pin.md；outputs/035c_* |
| 036 | insert-subcircuit（M3 第4片） | 已落 | tasks/036-insert-subcircuit.md |
| 036b | 029 位号池盲点修复 | 已落 | tasks/036-insert-subcircuit.md §036b；outputs/036b_* |
| 037 | move-block（M3 第5片收官） | 已落 | tasks/037-move-block.md |
| 038 | eprj3 适配（V4 A 档只读） | 已落 | tasks/038-eprj3-tierA.md |
| 039 | parts 工具链+facts 第一波 | 已落 | tasks/039-parts-toolchain-facts-wave1.md |
| 039b | decap 硬化+REF2033 翻闸 | 已落 | outputs/039b1_* |
| 039批② | 审查流程升级（schema /3） | 已落 | tasks/039b-review-flow-upgrade.md；outputs/039c_* |
| 040 | 解析器页归属修复 | 已落 | tasks/040-parser-page-scope.md |
| 040b | 一板一模型 | 已落 | tasks/040b-per-board-model.md |
| 041 | 跨板网络（DRAFT） | 规划 | tasks/041-cross-board-net-DRAFT.md |
| 042 | 解析器 parentId 双程挂载 | 已落 | `5f7cd58`；tasks/042-parser-attr-parentid.md |
| 043 | MPN 阻值解码偏差 | 已落 | tasks/043-mpn-value-decode.md |
| 044 | arch 骨架生成器 | 已落 | tasks/044-architecture-self-consistency.md |
| 045 | dsh 插件（0.1.0） | 已落 | `f4230e9`/`f01e23d`；tasks/045-dsh-plugin.md |
| 045b | exe 器件库内嵌修复 | 已落 | `634197d`；outputs/045b_blocklib_embed.txt |
| 046 | MPN 译码缺口×4 | 已落 | tasks/046-mpn-decoder-gaps.md |
| 047 | harness 卫生批四修 | 已落 | tasks/047-harness-hygiene-batch.md |
| 048 | 数字指数四位场解码 | 已落 | tasks/048-decoder-numeric-exponent.md |
| 049 | 解析器缺陷批（P2/P3） | 已落 | tasks/049-parser-defect-batch.md |
| 049-P1 | DCDC 并网修复（keep-first） | 已落 | tasks/049-parser-defect-batch.md §P1 |
| 050 | 真构建核对内嵌资源 | 已落 | tasks/050-frozen-build-verification.md |
| 052 | 审查复核与绘制方向建议 | 已落 | tasks/052-schematic-drawing-direction.md（研判；架构被 053 采用，无独立提交） |
| 053 | 画法编译器（阶段 A/B/C 地基） | 已落 | tasks/053-drawing-compiler-ab.md |
| 053B | keepout 真实裁剪等收尾三件 | 已落 | tasks/053-drawing-compiler-ab.md §六 |
| 054 | 画法编译器落图（C1，单模块进编辑器） | 已落 | `aa61768`；tasks/054-draw-stage-c-editor.md |
| 055 | 画图编译器收尾 G1/G2/G3/G6 | 已落 | `50ca8b6`；tasks/055-draw-followups-g1-g6.md |
| 056 | 多模块单页编译（C2a） | 已落 | `0459e74`；tasks/056-draw-stage-c2a-multimodule.md |
| 057 | C2b 编辑器半（离线半，PR #10） | 已落 | `986ecb3`；tasks/057-draw-stage-c2b-editor.md |
| 058 | 手册闸前置（issue #8） | 已落 | `9318506`；tasks/058-review-needs-datasheet.md |
| 059 | 真机验收收口 E1–E7 + 坑36 | 已落 | outputs/059_attr/VERDICT.md |
| defect-μ | 电容解析希腊 μ 崩溃修复 | 已落 | （无编号，PROGRESS.md:158） |
| 060 | 布局质量批（分侧/重复脚/GND 旗） | 已落 | tasks/060-draw-layout-quality.md |
| 061 | install-skill 认 harness（#11） | 已落 | tasks/061-skill-harness-claude.md |
| 062 | install-skill --agent 分发通道 | 已落 | tasks/062-install-skill-agent.md |
| 063 | warning_triage 侧车 + triage 命令（#12） | 已落 | tasks/063-warning-triage-sidecar.md |
| 064 | 旗标罗盘按符号分家 | 已落 | tasks/064-flag-compass-per-symbol.md；outputs/064_railflag/ |
| 065 | 电容挂归属脚物理侧 | 已落 | tasks/065-cap-pin-physical-side.md；outputs/065_capside/ |
| 069 | 岳画法裁决落地（旗/远脚/电源旗） | 已落 | tasks/069-far-sibling-pins-flag-join.md |
| 070 | triage key 撞车修复（#13） | 已落 | tasks/070-triage-key-identity.md |
| 071 | MPN 解码止血批（锚点闸 C） | 已落 | tasks/071-mpn-bleed-stop.md；evidence/071/ |
| 072 | 覆盖闸（#28/#29/#30） | 已落 | tasks/072-coverage-gate.md；evidence/072/ |
| 073 | 边界失败收尾（incomplete 非零退出） | 已落 | tasks/073-boundary-exit-codes.md；evidence/073/ |
| 074 | 旗引线穿越别网硬拒 | 已落 | tasks/074-flag-lead-foreign-crossing.md；evidence/074/ |
| 075 | 退出码一致性 | 已落 | tasks/075-exit-code-consistency.md；evidence/075/ |
| 076 | rc/led 未证实网闸 | 已落 | tasks/076-rc-led-unproven-nets.md；evidence/076/ |
| 077 | 电容中缀记号 | 已落 | tasks/077-capacitance-infix.md；evidence/077/ |
| 078 | MPN 日期码吞锚点 | 已落 | tasks/078-mpn-datecode-anchor.md；evidence/078/ |
| 079 | datasheet 提取器符号/电容口径 | 已落 | tasks/079-datasheet-extractor-signs-caps.md；evidence/079/ |
| 080 | issue 清仓批 0–5 | 已落 | tasks/080-issue-cleanups.md |
| 081 | pintable role≠球名 | 已落 | tasks/081-pintable-role-vs-ball.md；evidence/081/ |
| 082 | 074 遗留两件 | 已落 | tasks/082-074-leftovers.md；evidence/082/ |
| 083 | 值解析统一（values.py 下移 core） | 已落 | tasks/083-value-unification.md；evidence/083/ |
| 084 | doc.open 分类对齐 + pageUuid | 已落 | tasks/084-docopen-pageuuid.md |
| 085 | 覆盖闸补齐丢弃 producer | 已落 | tasks/085-coverage-gate-producer.md |
| 086 | reconcile 收敛 | 已落 | tasks/086-reconcile-convergence.md |
| 087 | 电容中缀无分数族放开 | 已落 | tasks/087-capacitance-nofraction.md；evidence/087/ |
| 088 | power-entry 语法（离线半） | 已落 | tasks/088-power-entry-grammar.md |
| 088b | power-entry 跟进（gnd-outlet/branchOrder） | 已落 | tasks/088b-power-entry-followups.md |
| 089 | power-entry 真机落图 | 已落 | tasks/089-power-entry-landing.md |
| 090 | A1 DesignIntent 合同 | 已落 | tasks/090-A1-design-intent.md |
| 091 | A2a params 冲突方向由 intent 定 | 已落 | tasks/091-A2a-params-fix-direction.md |
| 092 | A2b checkup 接线 + rail 额定核算 | 已落 | tasks/092-A2b-rail-ratings.md |
| 093 | A3a 架构自洽分级框架+三规则 | 已落 | tasks/093-A3a-arch-closure.md |
| 094 | A3b 采样链偏置闭合+合同接进 apply | 已落 | tasks/094-A3b-sense-bias.md |
| 095 | A4 power-entry 消费 intent | 已落 | tasks/095-A4-intent-driven-order.md |
| 096 | 页级两缺陷修复 | 已落 | tasks/096-page-two-defects.md |
| 097 | _annotation_allowance 估算修正 | 已落 | tasks/097-annotation-allowance.md |
| 098 | ic-periphery 语法（离线半） | 已落 | tasks/098-ic-periphery-grammar.md |
| 099 | CH340 真机落成（v0.5.7） | 已落 | tasks/099-ch340-landing.md |
| 099f | stub 阶梯加折线档 | 已落 | tasks/099-ch340-landing.md |

## 100–149

| 编号 | 主题 | 状态 | 证据/任务书路径 |
|---|---|---|---|
| 100 | B1 快速守卫批（#3/#9/#10/#15/#16/#19） | 已落 | tasks/100-b1-quick-guards.md |
| 101 | B2 解析器加固（#4/#5） | 已落 | tasks/101-b2-parser-hardening.md |
| 102 | B3 值解析（#8 容值尺寸码） | 已落 | tasks/102-b3-value-sizecodes.md |
| 103 | B5 规则修正（#14/#17） | 已落 | tasks/103-b5-rule-fixes.md |
| 104 | B4a 核心正确性（#11/#6/#2） | 已落 | tasks/104-b4a-reconcile-roles.md |
| 105 | B4b 位号混网（#1 最重） | 已落 | tasks/105-b4b-designator-membership.md |
| 106 | B6 connector 侧（#12/#13/#18+安全注记） | 已落 | tasks/106-b6-connector-side.md |
| 107 | 重复位号网上结论降级 | 已落 | tasks/107-dup-net-unproven.md |
| 108 | 阻值尺寸码孪生开闸 | 已落 | tasks/108-resistance-sizecodes.md |
| 109 | A4 提案器（intent→PresentationSpec） | 已落 | tasks/109-intent-proposer.md |
| 111 | draw lint 可读性检查器 | 已落 | tasks/111-draw-lint.md |
| 111a | draw lint 增补三规则（L10/L5b/L6） | 已落 | tasks/111a-lint-addendum.md |
| 111b | sys.log_read 日志面板只读（0.4.28） | 已落 | tasks/111b-syslog-action.md |
| 112 | 避障布线 wire_route | 已落 | tasks/112-obstacle-routing.md；outputs/112/ |
| 113 | 反激语法 flyback | 已落 | tasks/113-flyback-grammar.md |
| 114 | 编译器补课（支路串/lane） | 已落 | tasks/114-compiler-islands.md；outputs/114/ |
| 115 | 反激整页出图（序关系保守消费） | 已落 | tasks/115-flyback-page-compile.md |
| 116 | 编译器收官（全部序关系） | 已落 | tasks/116-ordinal-consumption.md |
| 117 | 反激整页翻绿 | 已落 | tasks/117-flyback-gate-green.md；outputs/117/ |
| 118 | 符号库实测化+五脚变压器硬伤 | 已落 | （无独立任务书）；outputs/118/ |
| 119 | 换料收口+位姿阶梯加宽 | 已落 | tasks/119-pose-ladder-widening.md |
| 120 | 第二孤岛落子收口 | 已落 | tasks/120-island-placement.md |
| 121a | spec 订正+语法建模修正 | 已落 | （无独立任务书） |
| 121b | 路径2暂停存档 | 搁置 | tasks/121-hand-plan-next.md |
| 121c | 反激手绘规划落图（离线） | 已落 | （无独立任务书） |
| 121d | 真机段（两硬阻塞如实入账） | 已落 | （无独立任务书） |
| 121e | 修 118/120 红灯 | 已落 | （无独立任务书） |
| 122 | PCB 审查路线图（DRC→模块→器件） | 已落 | tasks/122-pcb-review-roadmap.md |
| 123a | issue #58-61 文档批 | 已落 | （无独立任务书） |
| 123b | self_update 危险档 | 已落 | （无独立任务书） |
| 123c | 阶段 A·DRC 闭环 | 已落 | tasks/123-pcb-drc-stage-a.md |
| 123d | 元审查单位修复（mil/mm） | 已落 | （无独立任务书） |
| 124 | SKILL.md 减重（686→279 行） | 已落 | （无独立任务书） |
| 124b | references 打包 | 已落 | （无独立任务书） |
| 125 | 阶段 B·几何测量库 | 已落 | tasks/125-pcb-measure.md |
| 126 | 阶段 C·模块识别+通用层（母批） | 已落 | tasks/126-pcb-module-review.md |
| 126a | 地基（PcbRule/runner/module_of） | 已落 | tasks/126-pcb-module-review.md |
| 126b | 距离类规则 | 已落 | tasks/126-pcb-module-review.md |
| 126c | IPC 类规则 | 已落 | tasks/126-pcb-module-review.md |
| 126d | verdict schema /7 | 已落 | tasks/126-pcb-module-review.md |
| 127b | 盲审修复五连 | 已落 | tasks/127-blind-review-fixes.md |
| 128 | issue #63 分类器族谱修复 | 已落 | （无独立任务书） |
| 129 | 审计三连修（#67/#66/#68） | 已落 | （无独立任务书） |
| 130 | issue #69 同事上手三条 | 已落 | （无独立任务书） |
| 131a | 阶段 D·引脚名地基+pinrole | 已落 | tasks/131-power-pack.md |
| 131b | 电源包·pcb-regulator-cap-distance | 已落 | tasks/131-power-pack.md |
| 131c | 集成修复+pcb-regulator-fb-placement | 已落 | tasks/131-power-pack.md |
| 131d | MCU 包·OSC 修复+晶振规则 | 已落 | tasks/131-power-pack.md |
| 131e | MCU 包·供电组+复位启动 | 已落 | tasks/131-power-pack.md |
| 131f | MCU 包·POUR+keepout | 已落 | tasks/131-power-pack.md |
| 132 | issue #30⑥ 板级空覆盖闸 | 已落 | （无独立任务书） |
| 133a | 阶段 D·FOC 包三新原语 | 已落 | tasks/133-foc-pack.md |
| 133b | FOC 包·快赢五规则 | 已落 | tasks/133-foc-pack.md |
| 133c | FOC 包·地系统三规则 | 已落 | tasks/133-foc-pack.md |
| 133d | FOC 包·热设计三规则 | 已落 | tasks/133-foc-pack.md |
| 134 | 网络标签策略修复 | 已落 | （无独立任务书） |
| 135 | POURED 结果层破解 | 已落 | （无独立任务书） |
| 136 | validate_full 线-线间距盲区 | 已落 | （无独立任务书） |
| 137 | 布线器避让真修 | 已落 | （无独立任务书） |
| 138 | 审计新四条+#62 | 已落 | （无独立任务书） |
| 139 | issue #65 电源轨枚举/写回 | 已落 | （无独立任务书） |
| 139b | 电压键位统一 | 已落 | （无独立任务书） |
| 140 | issue #64 货架选型规则 | 已落 | （无独立任务书） |
| 141 | 绘制线·通道自适应加宽 | 已落 | evidence/141/ |
| 142 | 修 #75/#74（名单/正则） | 已落 | （无独立任务书） |
| 143 | 绘制线挖洞 swarm（33 洞） | 已落 | tasks/143-drawing-dig-triage.md；outputs/143_dig/ |
| 143a | drawcompiler/presentationspec 修 | 已落 | tasks/143-drawing-dig-triage.md |
| 143b | grammar 修 | 已落 | tasks/143-drawing-dig-triage.md |
| 143c | readability 修 | 已落 | tasks/143-drawing-dig-triage.md |
| 143d | drawapply/cli/changeplan 修 | 已落 | tasks/143-drawing-dig-triage.md |
| 143e | generate/layout 修 | 已落 | tasks/143-drawing-dig-triage.md |
| 143f | subcircuit/symbolprofile 修 | 已落 | tasks/143-drawing-dig-triage.md |
| 144 | 反激落图冲刺（旗标闸拒绝） | 已落 | outputs/144/ |
| 145a | 拆三根能力墙 | 已落 | （无独立任务书） |
| 145c | C13 符号几何修 | 已落 | （无独立任务书） |
| 145d | 修 plan 两缺陷 | 已落 | （无独立任务书） |
| 145e | 终落 P1 | 已落 | （无独立任务书） |
| 146 | 反激可读性抛光 | 已落 | （无独立任务书） |
| 147 | 走线穿体硬闸 | 已落 | （无独立任务书） |
| 147b | 硬闸误伤修复 | 已落 | （无独立任务书） |
| 147c | 复活清单生成 | 已落 | outputs/147c/revival_list.md |
| 148 | 硬闸下重新画出干净图 | 已落 | （无独立任务书） |
| 149 | 对齐岳的 P22 最低标准 | 已落 | （无独立任务书） |

## 150–199

| 编号 | 主题 | 状态 | 证据/任务书路径 |
|---|---|---|---|
| 150 | 修 149 版四处+验闸 | 已落 | （无独立任务书） |
| 155 | 岳裁五条落地 | 已落 | （无独立任务书） |
| 156 | 两案查证（导出丢件/脚号漂移） | 已落 | outputs/156/export_loss_evidence.md |
| 157 | daemon 自动拉起 | 已落 | （无独立任务书） |
| 158 | 原理图对账原则立项 | 已落 | tasks/158-schematic-reconciliation.md |
| 159 | 测试套件性能瘦身 | 已落 | tasks/159-test-perf.md |
| 160 | pytest-xdist 并行 | 已落 | （无独立任务书） |
| 161 | 挖洞审计（~30 洞） | 已落 | tasks/161-hole-triage.md |
| 162a | 测量库正确性（G1/G2） | 已落 | （无独立任务书） |
| 162b | PCB 解析层正确性（H 系列） | 已落 | （无独立任务书） |
| 163a | 布线/生成器闸门（E 系列） | 已落 | （无独立任务书） |
| 163b | 落页/lint/checkup/cli 闸门 | 已落 | （无独立任务书） |
| 164a | FOC 规则原理图对账 | 已落 | （无独立任务书） |
| 164b | 电源/MCU 规则原理图对账 | 已落 | （无独立任务书） |
| 164c | 静默分支与测量口径 | 已落 | （无独立任务书） |
| 165 | update-connector --all confirm | 已落 | （无独立任务书） |
| 166 | 在线 checkup PCB 审查做实 | 已落 | （无独立任务书） |
| 168 | 严重度架构（L8 降 INFO） | 已落 | （无独立任务书） |
| 169 | 测试形状+静默吞规则 | 已落 | （无独立任务书） |
| 170 | 收尾（测试形状对齐） | 已落 | （无独立任务书） |
| 171 | core 两提案（容值尾注/EARTH） | 已落 | （无独立任务书） |
| 172 | 丝印字宽诚实降级 | 已落 | （无独立任务书） |
| 173 | 绘制线积压（A/C/B） | 已落 | （无独立任务书） |
| 174 | pcb.geometry 桥动作（0.4.30） | 已落 | （无独立任务书） |
| 175 | 穿越代价+旗间距 | 已落 | （无独立任务书） |
| 176 | 采样链偏置规则（issue #76） | 已落 | tasks/176-sampling-bias-rule.md |
| 177 | point_in_polygon 收编 | 已落 | tasks/177-point-in-polygon-consolidation.md |
| 178 | 分域地旗入库 | 已落 | tasks/178-library-ground-flags.md |
| 178b | place_power 字形探针 | 已落 | tasks/178b-place-power-probe.md |
| 179 | connector 0.4.31（两坑修复） | 已落 | tasks/179-connector-document-source-rename.md |
| 180 | 地旗按符号放置+173C 收尾 | 已落 | tasks/180-ground-flag-by-symbol.md |
| 182 | 高速规则架子 | 已落 | tasks/182_highspeed_scaffold.md；outputs/182_highspeed_scaffold/ |
| 183 | 描边板框中心线拼合 | 已落 | tasks/183_bug98b_capsule_outline.md；outputs/183_bug98b/ |
| 184 | 值码解码覆盖不足 | 已落 | tasks/184_value_decode_coverage.md；outputs/184_value_decode/ |
| 185 | 结论收口+needsDatasheet 拆名+INSTANCE_STALE | 已落 | `c41f1c1`；tasks/185_conclusion_unified.md |
| 186 | 喂 PDF 链路闭环+hygiene 敏感串闸 | 已落 | `49bad82`；tasks/186_pdf_facts_path.md；outputs/186_pdf_facts/ |
| 187A | 183 系三洞收口 | 已落 | `1b4d3d7`；tasks/187a_outline_holes.md |
| 187B | 发布闸必拦四洞 | 已落 | `dca0373`；tasks/187b_gate_holes.md |
| 187C | daemon 版本自检+parts add --resolve | 已落 | `5932a78`；tasks/187c_daemon_version.md |
| 188A | 值码族补完+细长环披露 | 已落 | `f4bc630`；tasks/188a_value_decode.md |
| 188B | 185/186 低项清扫 | 已落 | `14ec0fe`；tasks/188b_low_items.md |
| 189A1 | 撤 PadGeometry.layer_id | 已落 | `e97c0fb`；tasks/189a1_layer_id.md |
| 189A2 | 原理图视图伪网（镜像引脚落位） | 已落 | `e97c0fb`；tasks/189a2_schematic_nets.md |
| 189A2c | 跨视图检查读数复核（527C）：**旧 7/8/6/2 是错配探针**（没走 154 板链），真读数 34 条/5 板入口，A 0 / B 34 / C 0；`min_pins` 保持 3 | 已落（本批 v0.5.18） | outputs/189a2c/evidence.md；tasks/527_pre060_loose_ends.md §527C |
| 189A2d | 跨视图 note 按**几何**分成「没画线 / 网名不同 / 落位嫌疑」，并点名全部位号（现在只列前 6） | 规划（527C2） | tasks/527_pre060_loose_ends.md §527C |
| 189B | 中危打包（intent/stale/判型） | 已落 | `e97c0fb`；tasks/189b_mid_pack.md |
| 189C | 离线几何渲染 canvas-svg | 已落 | `e9e914c`；tasks/189c_canvas_render.md |
| 189Cf | 底层位号丝印画出视窗 | 已落 | `de2116c`；（无独立任务书） |
| 190 | 判型口径收口+三条小账 | 已落 | `5f88b13`；tasks/190_type_and_basis.md |
| 190f | checkup --file 元数据盲区修复 | 已落 | `5f88b13`；tasks/190_type_and_basis.md §13 |
| 190S | 底层丝印文字延伸方向定标 | 已落 | `5171ed0`；tasks/190s_bottom_silk_direction.md；outputs/190s/ |
| 191A | accept-unknown 真通道 | 已落 | `5171ed0`；tasks/191_mechanisms.md；outputs/191a/ |
| 191B | 用户架/内置架合并+boards 同形 | 已落 | `5171ed0`；tasks/191_mechanisms.md；outputs/191b/ |
| 191C | KiCad 裸 (net N) 序号读取 | 已落 | `5171ed0`；tasks/191_mechanisms.md；outputs/191c/ |
| 191D | 去耦距离按电源轨分档 | 已落 | `5171ed0`；tasks/191d_decap_rail_tiers.md；outputs/191d/ |
| 192A | 挖洞修复·几何/解析/渲染 | 已落 | `5914ee2`；tasks/192_release_holes.md；outputs/192a/ |
| 192B | 挖洞·判型/闸门/合同 | 已落 | `5914ee2`；tasks/192_release_holes.md；outputs/192b/ |
| 192C | 挖洞·货架 CLI/桥 | 已落 | `5914ee2`；tasks/192_release_holes.md；outputs/192c/ |
| 193 | 进程/CPU 硬闸+保密机制补洞 | 已落 | `3434566`；tasks/193_process_and_secrecy.md；outputs/193/ |
| 193D | 文档补齐（190–193 口径） | 已落 | `02d7b9d`；tasks/193_process_and_secrecy.md；outputs/193d/ |

## 200–299

| 编号 | 主题 | 状态 | 证据/任务书路径 |
|---|---|---|---|
| 200A | v0.6.0 122 E 阶段·器件检查收口+报告整合 | 工作树 | tasks/200a_report_integration.md；outputs/200a/report-integration-evidence.md |
| 200B | v0.6.0 高速 A1 跨分割 | 工作树 | tasks/200b_cross_split.md；outputs/200b/evidence.md |
| 200C | v0.6.0 高速 A2 换层地孔+A3 差分对内 | 工作树 | tasks/200c1_ground_via.md、200c2_diffpair.md；outputs/200c1/evidence.md、200c2/evidence.md |
| 201A | 地/电源符号策略重写 | 已落 | `856fb0a`；tasks/201a_flag_strategy.md；outputs/201a/evidence.md |
| 201B | 拓扑感知模块落位+位姿联合搜索 | 已落 | `856fb0a`+`7ce7a5d`；tasks/201b_placement.md；outputs/201b/ |
| 201C | 布线协商三步 | **搁置**（踢出 v0.5.15） | tasks/201c_routing.md；`.tmp_201c_hold/`；outputs/201c/evidence.md §13 |
| 201D | 落位搜索计价「别人的文本行」 | **部分落**（`pin-text` 随 525 落；`text_overlap` 526 试了又撤，见 roadmap §4） | tasks/201d_text_row_cost.md |
| 201E | A* 布线效率 | **已落**（2026-10-19 实测） | outputs/201e/evidence.md；真因：`h` 纯曼哈顿、看不见 `CROSS_COST`，`expanded≈C*²`；23.2 s / 10 次调用（201C 的 68 s / 21 次**不复现**） |
| 201F | A* 可采纳下界（反向 Dijkstra 计价场） | **已完成**（工作树，待发） | outputs/201f/evidence.md；A\* 14.2 s→2.05 s（6.9×）、整页 23.0 s→11.05 s、83 预览逐字节相同；`LED_K`/`COMP` 的 expanded 判据**未达标**（原因见 evidence §4） |
| 201G | 反激整页 0 候选的两个真因（**诊断单**） | 任务书已写，待派 | tasks/201g_flyback_zero_candidate.md；疑点 A＝`same-column(Q1,R5)` 全档不成立、B＝`SEC_12V` 旗标在 `D3.1` 无处可挂 |

## 500+

| 编号 | 主题 | 状态 | 证据/任务书路径 |
|---|---|---|---|
| 515A | v0.5.15 绘制引擎修洞（缝1/缝2） | 规划 | tasks/515a_draw_holes.md |
| 515B | 发版前挖洞修复（S3#1–7 + S4#1–5） | 已落（`337f742`） | outputs/515b/evidence.md |
| 516 | 审查反馈（岳真机实测 A/B/C 级） | 已落（`6ef9ded`） | tasks/516_review_feedback.md |
| 519 | 异网 pin 尖间距：布局把两个网的针尖叠在同一点（修短路，12 对 → 0） | 已落（`1453ac7`） | 本批证据在 PROGRESS |
| 520 | L2a 批量寻址 `parts hunt`：C 号 → detail API → PDF → 提取 → candidate 落架 | 已落（随 v0.5.16/v0.5.17） | docs/parts.md §Bulk addressing |
| 551A | 分轮失败报告（`failures` 不再只保第一条） | 已落（`f56dced`） | outputs/algo_eval/（子代理 393） |
| 551B | L0 榨干归档元数据：被动件参数三路交叉（元数据 / 板上值 / MPN 值码） | 已落（`c51e3e8`） | docs/roadmap.md §7 |
| 551C | L2 datasheet 搜索：子代理并行（≤5 并发 / 每批 3–5 颗）、PDF 不进主上下文、三档可信度 | 第一段已落（520）；**三档可信度已落（522）** | docs/roadmap.md §7 |
| 521 | 提取面：**不做「扩正则」**——AI 读 `.txt` 写 facts，工具当收件闸（六道校验，最硬一条是引文逐字） | 已落（随 v0.5.16/v0.5.17） | tasks/521_ai_facts.md；docs/parts.md §Stage three |
| 522 | `facts_verified` 布尔 → `facts_trust` 三档（`candidate` / `machine_verified` / `verified`）；计算类规则吃机器核验，结论类仍要人工；finding 统一标注「未人工确认」；verdict 不涂绿 | 已落（`05b0302`；follow-up `f2bc7d2` 修层边界+重钉指纹） | tasks/522_facts_trust.md；tests/test_522_facts_trust.py；docs/parts.md §The gate |
| 523 | `category` 的授予路径：`--apply-facts` 只写 facts 不写分类，机器核验的件仍判不了（报告已如实点出两条待办） | 已落（527D，v0.5.18）：`parts classify` + `category_trust`，两道闸都问分类自己的档位 | 522 真板三读数的已知边界；tasks/527_pre060_loose_ends.md §527D |
| 527 | **v0.6.0 之前必须收口的尾巴**（527A `IntentSource` 转发三小节 / 527B connector 页型守卫 `/` 信封文档 / 527C 189A2 分类裁定 / 527D = 523 / 527E 文档收口） | 已落（v0.5.18 内测） | tasks/527_pre060_loose_ends.md |
| 527D2 | `parts classify` 的证据**不落货架**（`machine_verified` 的分类事后无法追溯出处，与 521 口径不一致）；冻结态下内置架条目改不了的提示也没有 | 规划 | tasks/527_pre060_loose_ends.md §527D「已知边界」 |
| 527D3 | **`entry.category` 的直读点**（`rules/pcb/mcureset`/`mcusupply`/`crystal`/`regulator`/`fbplacement`/`foc`/`focground`、`rules/params`/`paramspec`/`decap`/`archclosure`/`railratings`、`core/architecture`/`power_domains`）绕过 `shelf_declaration`，机器档分类仍能驱动结论规则 | **已落**（2026-10-19，工作树待发） | `partkind.declared_category` + `partkind.category_verdict`（ACCEPTED/GATED/ABSENT）+ `facts.category_gate_finding`；17 个读点逐条判档；证据 `outputs/527d3/evidence.md`；指纹 `b05d3384` / `674e07e1` |
| 528 | **0.6.0 门槛重写 + 四条裁决落地**（R4-C `update-connector --no-reload`；191D 数值不动；绘图线做硬门槛；527D2/D3 升为 0.6.0 阻塞项） | 在途 | tasks/528_060_gate.md |
| 529 | 191D 的**分类空白带**（`HF ≤ 1µF` 与 `bulk ≥ 10µF` 之间的 2.2µF/4.7µF 落 unknown → 假 WARN；补档后撤销 191D 的「输入侧无候选才 WARN」收窄） | 规划（非阻塞） | tasks/528_060_gate.md §4 |
| 528A | `bridge update-connector --no-reload`：写记录不 reload，点一次扩展菜单生效（R4 实验④的产物） | 在途 | tasks/528_060_gate.md §1 |
| 530A | **岛页旗标**：`IslandBlock.power_symbols`（加性）+ 跨岛地/电源一律旗标（S-16），旗标进 `bbox`；真机 10 旗标落 `test` 新页，连通 44 脚 0 失配。设计见 `evidence/523/DESIGN.md` | 工作树 | evidence/530a/（报告 + probes + raw + 落图 PNG/SVG） |
| 530B | **岛内布局核心**：主器件居中（S-03）+ 两脚件贴它服务的引脚（S-04）+ 去耦贴供电脚 ≤30（S-05）+ 同规格成排（S-06）；单岛路径几何逐字节不变 | 工作树 | evidence/530b/ |
| 530C | **岛内连线修订**：`_route` 加 `bends` / `true_crossings` 两键与「压外来针尖 / 落在外来导体上」两档过滤（S-09/S-11）；导线网名清空档实测硬违反 8→0 并查出开关 | 工作树 | evidence/530c/ |
| 530D | **命名分量化**（S-14：一条网每个连通分量恰好一个名）+ **落图不印导线网名**（岳裁定 A，`label_wire_indices`）+ 连通回验改**分区核对**；真机 16 条 spec 网 / 44 脚 / 0 失配；闸 8→1（残余是 `LED_K` 标签自己的行压 `R7`） | 工作树 | evidence/530d/ |
| 530E | `draw islands propose`（几何聚类只产出**待写的文档**）与 `draw islands apply`（六道闸 + §5.6 四级保守回退 + 件守恒）；离线两条命令，不碰编辑器 | 工作树 | evidence/530e/ |
| 530F | **多岛总验收**：① 闸降级口径落地——电学类硬拒，被容忍的**主机自印行**每页有上限且**逐条点名**（`ISLAND_GATE_TOLERATED_LIMITS`）；② 5 条老红销账（201b/551a 换夹具、113/119 改账簿、145a 改账簿）后全量 0 红；③ `LayoutIsland.name`（加性）+ `apply` 写入 + 岛页 notes 报名字；④ 真机落图终验：`draw compile` ok=True（1 条被容忍且点名）→ 落 `test` 新页 → 连通 0 失配 / 12 根带名导线=标签 / 10 旗标 / 标题栏零相交 → PNG + plan SVG → 删页存盘 | 工作树 | evidence/530f/（报告 + probes + raw + 落图 PNG/SVG） |
| 530G | **标题栏 keepout 进岛打包**（S-01）：矩形是**图页符号自己的 `TABLE`**（700×180，锚在角上、不随图幅缩放，`core.pageframe`）+ 下方留白 15%；真反激岛页对真矩形零相交；无 page_box 的岛页摘要仍冻结 | 工作树 | evidence/530g/ |
| 533 | **岛页落图强制保护**（补 530G 的缺口：`--page-box` 是可选的，不带就没有 keepout → 530F 偏离 4 与 532 页 A 两次落进标题栏）：① 真机探明页面图幅**读得出来**——`sys.get_document_source` 的记录流里图纸符号自己带 `Width/Height/Blade Width/Title Block Position`（`document.current` 的 `schematicPage` 盒是 `{}`，读不出），接进 `parsers.schematic.sheet_attrs_from_text` → `pageframe.title_block_from_sheet_attrs`；② `draw plan` 绑活页 + 多岛时**自动**读图幅推 page_box+keepouts，读不到又没给 `--page-box` 则 exit 5；③ `draw apply` 核对 plan 自己记的 keep-out（`keep_out_note`）与目标页图幅，没记/对不上/读不到则 exit 5，**绝不静默落进标题栏**；④ 真机回归：新建 test 页自动读图幅 → 落图 → 标题栏矩形内 **0** 图元（同口径 532 页 A 仍 32）→ 连通 0 失配 → 删页存盘 | 工作树 | evidence/533/（报告 + probes + raw + 落图 PNG/SVG） |
| 536 | 岛群→子岛：schema、plan 身份与 hard 校验（不含装配/多群页级） | 已提交 `0f638de`（含在 0.5.22 历史） | tasks/536_archipelago_schema.md；tests/test_536_archipelago_schema.py；tests/test_archipelago_contract.py |
| 537 | 审查流程环境/证据/权限/交付硬闸，含已复现的采样值输入与 Windows 编码缺口 | 已提交 `0f638de`（含在 0.5.22 历史） | tasks/537_review_workflow_gates.md；Python 7650 passed；connector 536 passed；dsh-plugin 113 passed/1 skipped |
| 538 | archipelago 独立子岛编译与局部回滚（不含组装配/页级 pack/整页交付） | 已提交 `0f638de`（含在 0.5.22 历史） | tasks/538_island_compile.md；Python 7708 passed；connector 536 passed；dsh-plugin 113 passed/1 skipped |
| 539 | 537/538 对抗审查、真机只读验收与交付证据修复（F1–F9） | 已提交 `0f638de`（含在 0.5.22 历史） | tasks/539_adversarial_real_acceptance.md；真机 incomplete/partial 如实交付；最终 Python 7731 / connector 536 / DSH 113+1 |
| 540 | 0.6.0 前工作区整理、审查/绘制解耦、Rust 迁移平台准备；不改业务算法、不批量翻译 | 完成、未提交（A/B/C + 对抗修复 + 只读真机追加验收；候选读数待 `candidate-regression.md`） | tasks/540_pre060_platform.md；tasks/540b_review_draw_decoupling.md；tasks/540c_rust_platform.md；evidence/540/final-regression.md；evidence/540/final-regression-adversarial.md；evidence/540/final-regression-followup.md；evidence/540/real-machine-instance-20261025-233933/25-final-report.md；outputs/review/540/ |
| 541 | **审查分阶段交付与可中断流程**：一次 checkup 后先交付 initial/partial 首轮检查点再分批深挖（每批 ≤3 finding）；run 冻结输入、同基准复读、中止只读已有产物出 partial。SOP 小节 + 双 SKILL 路由 + 匿名测试已落地；RunManifest / 重算 guard / harness 硬闸仍为规划 | 已提交、未推送（只 commit 不 push） | docs/review-sop.md §3.0a；tasks/review-stage-runtime-gates.md；tests/test_review_stage_delivery.py；两份 SKILL 的 3.0a 路由 |
| 542 | **原理图绘制 3.0（2026-11-01 可用版）**：drawing-line 集成、反激整页三关、编译/布线/宿主/视觉四缝挖洞修复、RC 冻结与 V4 交接；CH343 仅作不挤占关键路径的 P1 | **P0 完成、候选冻结（2026-10-27 提前）**：P4 三关、岳人眼与重开 `saved_verified` 全过；V4 11-01 后实施，未发正式包 | tasks/542_schematic_3_0_nov01.md；evidence/542/final-p4.md；evidence/201h/live/ |
| V4 | **立创 EDA Pro 4.x 适配**（岳 2026-10-19 裁：**11 月起（0.6.x）做**）。四件事：① 在真 V4 上复跑 `doctor` + 一块板的 `checkup`，逐字段对拍 0.4.26 那次的结果包（当年结论：`.epro2` 归档与 V3 同格式、零适配；之后 0.5.x 六七个版本未在 V4 复测）；② 在线 connector-on-V4 探针重跑（当年 8/8 arity 一致、V4 是纯超集）；③ `.eprj3` 文件夹工程的真样本终验（yAxisDirection / NC 引脚 id / CANVAS 缺失，仍挂着）；④ `.eprj2` 导出引导在 V4 菜单里逐字核（V4 本地保存仍是 `.eprj2` SQLite 壳） | 规划（11 月开） | tasks/038-eprj3-tierA.md §V4.1.60 实测 |

## 字母/别名批号与里程碑（E / R / perf / bug98 / releases）

| 编号 | 主题 | 状态 | 证据/任务书路径 |
|---|---|---|---|
| E1 | 封装一致性对账 | 已落 | （无独立任务书） |
| E2 | 极性/丝印检查 | 已落 | （无独立任务书） |
| E2b | 方向不统一降 INFO | 已落 | （无独立任务书） |
| E3 | 降额物理层 | 已落 | （无独立任务书） |
| E3b | 修 focground 读错视图 | 已落 | （无独立任务书） |
| E4 | 报告整合（E 阶段收口） | 已落 | （无独立任务书） |
| bug98-A | 板框描边拼合 | 已落 | tasks/bug98-A-outline-stitch.md |
| bug98-B | footprint id 回退 | 已落 | tasks/bug98-B-footprint-id-fallback.md |
| bug98-C | 控制台 UTF-8（查证=旧 exe） | 已落 | tasks/bug98-C-console-utf8.md |
| perf-01 | 性能热力图测量 | 已落 | tasks/perf-01-measure.md；outputs/perf/heatmap.md |
| perf-02A | 生产备忘化 | 已落 | tasks/perf-02A-memoization.md |
| perf-02B | 测试侧缓存 | 已落 | tasks/perf-02B-test-cache.md |
| R1 | 桥能力补齐 | 已落（v0.5.12） | tasks/roadmap/R1-bridge-completion.md |
| R2 | PCB 审查加深 | 已落（v0.5.13） | tasks/roadmap/R2-pcb-review-deepening.md |
| R3 | KiCad 第二宿主 | 规划（0.6.0 后） | tasks/roadmap/R3-kicad-harness.md |
| R4 | 真热更 stub | 在途（阶段二待立） | tasks/roadmap/R4-true-hot-update.md；outputs/R4/design-proposal.md |
| R4a | 真热更阶段一收尾+安全设计定稿 | 已落 | `779b953`；tasks/R4a_hot_update_stage1b.md；outputs/R4/evidence.md |
| R5 | SPICE 远景侦察 | 规划（冻结） | tasks/roadmap/R5-simulation-recon.md |
| 路线图任务包 | tasks/roadmap/ 五包+README | 已落 | tasks/roadmap/ |
| 六PR合并 | PR #77–#82 合并+修补波 | 已落 | （无独立任务书） |
| 测试制度与发布闸 | 三闸纪律入文档 | 已落 | docs/testing-doctrine.md |
| dsh-market 上架 | 上架 awesome-dsh-plugin+仓库 topics | 已落 | PR #5981 |
| DSH STORE 适配 | dsh-plugin 0.1.2 lib 入库+repository | 已落 | `344f2e1`/`4489750`/`5475f35`/`c04ae32` |
| release v0.5.0 | 补 4 天拖欠（画法编译器全链） | 已落 | `560dae4` |
| release v0.5.2 | 107/108/109/111/111a/111b | 已落 | `a46acbd` |
| release v0.5.7 | 绘制线封存转 PCB 主线 | 已落 | — |
| release v0.5.8 | E 阶段四件 | 已落 | — |
| release v0.5.9 | 157 daemon 自动拉起 | 已落 | — |
| release v0.5.10 | 审查正确性大修 | 已落 | `d6896fd` |
| release v0.5.11 | 地族隔离+connector 诚实化 | 已落 | — |
| release v0.5.12 | R1 桥能力补齐 | 已落 | — |
| release v0.5.13 | R2 PCB 审查加深 | 已落 | tag `v0.5.13` |
| release v0.5.14 | 挖洞修复+192 批+190S | 已落 | tag `v0.5.14`（`5914ee2`/`f2c53ae`） |
| release v0.5.15 | 515B + 516（201C 踢出） | 已发（tag `v0.5.15`） | tasks/SCHEDULE.md |
| release v0.5.16 | 520 + 521 + 522（审查线资料获取三连）+ 绘图推演简报；内测 | 已发（tag `v0.5.16`，prerelease） | tasks/SCHEDULE.md；PROGRESS |
| 524 | **v0.5.16 挖洞补做**（5 缝只读 swarm，12 条高严重级全修：引文闸子串/pin 未绑引文/两规则绕档位/审计无 dest/offline 假话/shelf 清身份/null 变 verified） | 已落（`8c87070`） | PROGRESS；6 条新回归 |
| release v0.5.17 | v0.5.16 的洞修复；内测 | 已发（tag `v0.5.17`，prerelease）；v0.5.16 notes 已标「请用 0.5.17」 | tasks/SCHEDULE.md |
| 525 | **新布局目标**：CP-SAT 六轮推演收口 + 两处真缺陷修复（`_elbow_route` 拐点漏检 → netlist 并点；布局里缺 pin/文字行净空 → 21 处 pin 尖被邻居 value 行埋葬）。新增 `placement.pin-text` 项（topology 轮开） | 已落（`bbf85a4`） | `tests/test_525_pin_text_row.py`；PROGRESS |
| 526 | **走廊不是瓶颈**：探针筛选零收益（restart 0 本来就 7/7 通且代价最小）；reserved 审计推翻上一条（清空 60 个预留道后 `goal_wall` 逐字不变）；真凶是 `U4.1` 压在 `R8` 值行上沿。**「文字行参与占位」试过又撤回**：`presentation_nolocks` 上 pin-text 1.5→1.0、走廊消失，但 A/B 在整页 presentation 上从「拒 `SEC_12V`」退化成 14 条 `text-overlap`（代价项只看见器件行，readability 还数电源旗/网名/旗名）——**只做一半的约束比不做更差** | 结论已记，代码撤回 | PROGRESS；`experiments/reserved/`（`.tmp_corridor`） |

## 待人工核对（不猜测，按原文保守入表）

1. **`052`**：PROGRESS 自述「working tree changes not committed yet」，后续称架构已被 053 采用——表中记「已落（研判）」并注明无独立提交。
2. **有任务书但 PROGRESS 无记录、状态未知**：`002`、`003`、`004b`、`004c`、`004f`、`008`、`008b`、`009c`、`014`、`066`、`067`、`110`、`110a`、`110b`、`110c`、`110d`（多为早期/调查类，未逐条留痕）。其中 `110/110a-d`（反激规划）与「121 反激规划落图暂停」同源，疑为`搁置`，但 PROGRESS 无明文。
3. **`515A`**：任务书存在（10-17），PROGRESS 只有 515B 记录——按 `规划` 记，等 201C/515A 排期明确后升级。
4. **无任务书可引的编号**（「证据」列留空，非歧义）：`132`、`134`–`142`、`123a/b/d`、`124/124b`、`#55`、`E1`–`E4`。
5. **`defect-μ`**：PROGRESS 里唯一无编号的修复条（希腊 μ KeyError），已按原文标题收录。

> **已核（2026-10-17，主代理跑 `git log`）**：草稿中 182–191 长尾、190S、193、193D、201A/201B、R2、R4a 的「工作树」判定**全部升级为 `已落`**，提交号见上表；
> `515B`（`337f742`）与 `516`（`6ef9ded`）已随 v0.5.15 落账——**全表当前零「工作树」**。

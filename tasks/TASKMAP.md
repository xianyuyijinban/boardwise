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

## §0 当前在做（截至 2026-10-17）

- **主攻**：原理图绘制质量（目标「一个模块画到及格线」）——`201A/201B` 已落，`201C` 踢出待复活，`201D/201E` 规划。
- **在途**：无（`516A` 已交卷、`515B` 已随 v0.5.15 落）。
- **工作树（已完成未提交）**：无。
- **搁置/踢出**：`201C`（150 落地页回归实锤，备份 `.tmp_201c_hold/`）；`121b`（10-06 暂停）。
- **发版**：`v0.5.15` ✅ 已发（2026-10-17，正式版；515B + 516；201C 踢出）。
- **v0.6.0（押后到 10 月底）**：`200A/200B/200C` + `041`；远景 `R5`。

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
| 200A | v0.6.0 122 E 阶段·器件检查收口+报告整合 | 规划 | tasks/200_v060_scope.md |
| 200B | v0.6.0 高速 A1 跨分割 | 规划 | tasks/200_v060_scope.md |
| 200C | v0.6.0 高速 A2 换层地孔+A3 差分对内 | 规划 | tasks/200_v060_scope.md |
| 201A | 地/电源符号策略重写 | 已落 | `856fb0a`；tasks/201a_flag_strategy.md；outputs/201a/evidence.md |
| 201B | 拓扑感知模块落位+位姿联合搜索 | 已落 | `856fb0a`+`7ce7a5d`；tasks/201b_placement.md；outputs/201b/ |
| 201C | 布线协商三步 | **搁置**（踢出 v0.5.15） | tasks/201c_routing.md；`.tmp_201c_hold/`；outputs/201c/evidence.md §13 |
| 201D | 落位搜索计价「别人的文本行」 | 规划 | tasks/201d_text_row_cost.md |
| 201E | A* 布线效率（68s/21 次调用） | 规划 | （任务书未写，见 outputs/201c/evidence.md §7） |

## 500+

| 编号 | 主题 | 状态 | 证据/任务书路径 |
|---|---|---|---|
| 515A | v0.5.15 绘制引擎修洞（缝1/缝2） | 规划 | tasks/515a_draw_holes.md |
| 515B | 发版前挖洞修复（S3#1–7 + S4#1–5） | 已落（`337f742`） | outputs/515b/evidence.md |
| 516 | 审查反馈（岳真机实测 A/B/C 级） | 已落（`6ef9ded`） | tasks/516_review_feedback.md |
| 551A | 分轮失败报告（`failures` 不再只保第一条） | 已落（`f56dced`） | outputs/algo_eval/（子代理 393） |
| 551B | L0 榨干归档元数据：被动件参数三路交叉（元数据 / 板上值 / MPN 值码） | 在途（子代理 396，`.tmp_meta_parse`） | docs/roadmap.md §7 |
| 551C | L2 datasheet 搜索：子代理并行（≤5 并发 / 每批 3–5 颗）、PDF 不进主上下文、三档可信度 | 规划 | docs/roadmap.md §7 |

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
| release v0.5.15 | 515B + 516（201C 踢出） | 在途 | tasks/SCHEDULE.md |

## 待人工核对（不猜测，按原文保守入表）

1. **`052`**：PROGRESS 自述「working tree changes not committed yet」，后续称架构已被 053 采用——表中记「已落（研判）」并注明无独立提交。
2. **有任务书但 PROGRESS 无记录、状态未知**：`002`、`003`、`004b`、`004c`、`004f`、`008`、`008b`、`009c`、`014`、`066`、`067`、`110`、`110a`、`110b`、`110c`、`110d`（多为早期/调查类，未逐条留痕）。其中 `110/110a-d`（反激规划）与「121 反激规划落图暂停」同源，疑为`搁置`，但 PROGRESS 无明文。
3. **`515A`**：任务书存在（10-17），PROGRESS 只有 515B 记录——按 `规划` 记，等 201C/515A 排期明确后升级。
4. **无任务书可引的编号**（「证据」列留空，非歧义）：`132`、`134`–`142`、`123a/b/d`、`124/124b`、`#55`、`E1`–`E4`。
5. **`defect-μ`**：PROGRESS 里唯一无编号的修复条（希腊 μ KeyError），已按原文标题收录。

> **已核（2026-10-17，主代理跑 `git log`）**：草稿中 182–191 长尾、190S、193、193D、201A/201B、R2、R4a 的「工作树」判定**全部升级为 `已落`**，提交号见上表；
> `515B`（`337f742`）与 `516`（`6ef9ded`）已随 v0.5.15 落账——**全表当前零「工作树」**。

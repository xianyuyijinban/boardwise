# 审查闭环 SOP（checkup / 架构走查 / 断连兜底）

> 自 `.kimi-code/skills/boardwise/SKILL.md` §3.1/§3.1b/§3.2 迁入（2026-10-06，SKILL 减重 124）。正文保持迁入时原样；SKILL §3 只留路由图。

### 3.1 审板子＝`boardwise checkup`（首选，一条命令）

```bash
boardwise checkup                                  # 焦点工程，报告写 checkup/
boardwise checkup --project <工程名|uuid> --out <目录>   # 多窗口时指哪打哪
boardwise checkup --file <导出.epro2> --out <目录>       # 断连兜底：纯离线，跳过在线阶段
```

产出（`--out` 目录内）：`report.json`（契约）· `report.md`（人读，同一份内容）·
`architecture.md`（架构骨架，§3.1b 必须逐槽走；**自动生成、每次覆盖，手填无效**）·
`design-intent.md`（**设计意图**，工程师所有：不存在时建全 TODO 模板，存在则生成器一字不改）·
`canvas-<页名>.png`（每张原理图页一张，PCB 页不出图）。

- **退出码**：`0` 无 ERROR / `1` 有 ERROR（主机 ERC fatalError/error、主机 PCB DRC 逐条、
  自有规则 ERROR 任一命中）/ `2` 输入不可用 / `3` 说不清——在线状态不可陈述（daemon 不通、
  没 connector、三级数据路全被拒）**或 `completion.verdict` 是 `incomplete`**（073：审查没看全——
  没读到模型 / 有器件缺手册未审 / 骨架没生成 / 覆盖有缺口）。优先级：坏输入 `2` > 有 ERROR `1`
  > incomplete `3` > `0`；`complete-with-open-items` **仍是 `0`**。`3` 绝不是"板子干净"，
  CI 里也别当通过。
- **报告自己说数据从哪来**（`source.tier`，缺一级就如实降级）：
  `project-file` 整工程归档（满血）→ `per-page` 逐页导出合并（跨页连通性按网名，
  不是追出来的连线）→ `netlist` 仅连通性（无值/无 MPN/无位姿）→ `file` 离线文件。
  **per-page 档里跨页同名的网不是已验证的连接**（issue #19；参数两条规则于 076 补齐）：按网找
  协同器件的 9 条规则（`decap-required-caps` / `conn-nc-and-must-connect` / `conn-usb-cc-pulldown` /
  `param-divider-output` / `param-led-current` / `param-rc-cutoff` / `path-ldo-dropout` /
  `pwr-domain-vs-range` / `pwr-supply-on-known-domain`）对出现在多于一个页的网名
  **一律不下通过/违规结论，只报 UNKNOWN**
  ——同名可能是同一块板的另一张页（真连），也可能是另一块板碰巧同名（假连），这一档分不出来。
  每条规则只对**它自己真正读的那几条网**查（`rules/unproven.py` 的登记表逐条写明：rc 查 R-C 共用的
  非地网，led 查 LED 与串阻共用的网加那条读出电压的轨），地网不查——地网按构造每页都有，查它等于
  把每对 RC 都拒掉。
  报告在 `source.unprovenNets`（网名 + 各自出现在哪些页 + 拒绝的规则名单）与 notes/档位说明里写明；
  `per-page` 档位说明就是那句「agreement by name is not a verified connection」。
  **单页工程与 project-file 档行为一字不变**（单页的网按构造即为已验证）。
  `drc.*.checked=false` + `reason` 一律是"**没查**"，不是"零错误"。
- 只读：`doc.open` 只切焦点、`userInterface` 恒 false（不弹底部面板），每个阶段 `finally`
  把焦点复位。旧版 connector 缺某个动作时报告会记 `note` 并降级，不会瞎报。

**审查四步与 AI 槽位（报告 schema /6：`ai_slots` 加四个一等节就是清单，逐条做完再答用户）**：

⓪ **先问再判（事前动作，阻塞——058 起是第一步，做在①之前）**：动手判定任何器件/管脚之前，
先把**「功能建立不起来的器件与管脚」**列成一张清单，它就是报告里的 `needs_datasheet[]`：
两个触发源，一个清单——

- **触发源①（facts）报告生成时就带着**：规则判不了的器件（= `unreviewed_parts[]` 原样纳入）。
- **触发源②（marked）是你的活**：图上读不懂的管脚、或整颗行为不明的新器件，在**下任何判定之前**
  用 `boardwise need-datasheet --out <checkup目录> --part U7 --pins FB,ICG --reason "为什么解释不了"`
  写进报告（`--pins` 可省 = 整颗器件；按 `(part, pin)` 幂等，重复标记只更新 reason；
  命令会重算 `completion` 并重渲染 `report.md`，纯文件操作、不碰编辑器。**报告里记录的那个
  退出码也一起重算**（075）：标上去 `0 → 3`，标记没了回 `0`——命令**自己的**退出码不是它，
  把标记并进报告成功就是 `0`）。
- 清单非空时**一次性向用户索取**对应手册/资料；**资料到位前不得对依赖它的条目下"通过/不符合"
  结论**，只能写「无法确认（等资料）」。
- **边界（写死）**：**不是**"等齐所有手册才准开工"——**能独立算的先算**（分压、耐压、降额、
  驱动电流照算不误），只把**依赖未知器件功能**的条目挂起；**不**默认自动联网抓手册
  （`parts fetch` 的三通道现状不动，官网通道仍然是你的 WebSearch 活）。
- **消歧：「不许涂绿」与「先问再判」是两件事，分属两个阶段，不许合并成一句。**
  「不许涂绿」是**事后标记**（判不了就如实说判不了——早就有）；「先问再判」是**事前动作**
  （判之前先把未知项列出来、要资料——本步）。事后如实 + 事前索取，两道都得有：
  issue #8 踩的是后者缺席，不是前者。

① **ERC 先行**：主机 ERC/DRC 读数在 `drc` 段——error 已在报告头部错误段，先解决；
warn 逐条进 `warning_triage[]`，**把每条的 `verdict` 填成 有益/有害/无害、`reason` 写理由**——
填法：`boardwise triage --out <checkup目录> --key <key> --verdict … --reason …`
（report.md「警告分诊」表里有 `key` 列；填了立即重算 completion 与报告里记录的退出码
（075——命令自己的退出码是 `0`），重跑 checkup 经侧车并入不丢）。
主机 ERC **没有逐条文本**（只有 host-wide 合计，039 真机 probe 实证，§6 坑 27），
对着计数与画布图判，要看文本得去编辑器底部面板；PCB DRC 叶子和自有规则 WARN 是带文本的。
含警告的模块已排在 `modules` 前头（`source.modulesOrderedBy = "warnings-first"`，
每个模块带 `warningFindings`），分模块**先审含警告的**。

② **分模块 + 手册闸**：手册闸的唯一未知项清单是 `needs_datasheet[]`（⓪ 的两源合一）——
`unreviewed_parts[]` 是它的 **facts 触发子集**，保留原名不动，三通道状态
（`channels.engineer/lcsc/official`）就在那些条目里。遇到不熟的器件**不许跳过、不许涂绿**——
按通道取手册：工程师给的 PDF 放 `.tmp_datasheets/`
（`boardwise parts fetch <mpn> --file <PDF>` 落进去）；立创通道 `parts fetch <mpn>`
自动从库条目链接下载并提取候选事实；官网通道永远是你的活
（`channels.official.suggestedQueries` 给了查询词，WebSearch 找规格书，核**周边配置**：
去耦/上下拉/限流/耐压，顺手确认可用型号）。拿到手册当场核完继续审，**三通道全灭**
才让它留在未审器件里。**该节非空时不得宣称"审查通过"**——结论只能用
`summary.conclusion` 那句（"DRC/连接性已审，N 颗器件缺手册未审；另有 M 项管脚待手册（已标记）"），
`summary.mayClaimPassed` 就是这道闸（**窄义**：只回答"有没有器件缺手册未审"——没别的意思）；
**完整结论/总闸看 `completion.verdict`**（`needsDatasheet > 0` ⇒ `incomplete`，与
`unreviewedParts > 0` 一样让它进不了 `complete`）。

③ **整图布局（审美开关，默认关）**：开关开着报告才有 `layout_review` 节（五轴：
拓扑可辨/流向明确/文字可读/分组合理/网络标识规范），对着 `canvas_images[]` 逐轴打 1–5 分
并写 evidence；**模型没有视觉判断力就写 `skipped`、分数留 null——禁止编分数**
（`layout_review.visionRequired` 说死了）。**首次为用户服务时问一次**"要不要开布局审美评分"，
把选择写进 `boardwise config set review.aesthetics on|off`，不问第二次；
单次想开用 `checkup --aesthetics`（单次覆盖赢配置）。画布图在 `--out` 里，
打开 `report.md` 点链接即可。

最后 `summary_template` —— 按模板**原样留槽**填四段（结论先行 / 错误与归因 / 警告提醒 /
建议动作），把上面的结论写进去，别重述 `report.json` 的全部内容。

**不要重算工具已经算过的东西**：DRC 计数与 PCB 逐条在 `drc` 段、模块划分在 `modules` 段、
规则 findings 在 `findings` 段（`summary` 里的 `ref` 指回它们）。模型只补四件事：
**填警告分诊、查不熟的器件、看画布、写总结**。总结写完把 `report.md`（含图）交用户。

### 3.1b 架构走查（044 起的强制环节，不是可选阅读）

checkup 每次都会在 `--out` 里写**一对文件**，规则从 053 §2.2 起：

- `architecture.md`——**自动生成、每次覆盖，手填无效**（第二行横幅就这么写着）；
- `design-intent.md`——**设计意图，归工程师/AI 提案所有**：不存在时生成器建一份与骨架同构的全 TODO
  模板，存在则**一字不改**。答案写这里才留得住（052 §2.2 实测：填在 `architecture.md` 里的
  `targetVoltage: 3.3V`，重生成后回到 `TODO`）。
- **DesignIntent 合同（090 起的第四份合同，JSON 是源）**——`--intent <path>` 或
  `~/.boardwise/design-intent/<projectUuid>.json`（`BOARDWISE_HOME` 跟着 `config.json` 挪）。
  三段：`requirements`（rails/signals/buses）+ `blocks` + `decisions`，每条带 `provenance`
  （`user_stated` > `verified_recipe` > `ai_asserted`，缺省即草稿）。**有合同时 `design-intent.md`
  是按合同渲染的视图、每次重渲染（手填无效）**；没有合同时仍是上面的 053 §2.2 逐个文件。
  生成/重生成只有一处：`boardwise arch <工程文件> --intent <path>`（已填值逐字节保留，图纸里
  已没有的对象标 `stale` 不删）。`checkup` 只读合同，绝不改写。
  报告 `intent` 节：`totals{slots,filled,missing,requiredMissing}` + `missing[]`（每槽带 `write`
  路径）+ `required[]` 的 `intent-missing` 行（点名槽位 + 文件 + 键）+ `hints[]`（
  `closure-undeclared`：双向电流采样没有 `requires: ["bias-reference"]` 类闭合声明——FOC 偏置案
  的槽位形态，A1 只提问，A3 升级为规则）。**缺槽不抬 verdict、不动退出码**；填缺口的人是
  工程师或模型，工具不代填。**092 A2b 起合同还进规则走查**（不只是报告的一节）：
  `rails[].targetVoltage` 喂 `pwr-cap-voltage-rating`，输出轨的 `continuousCurrent` 喂
  `path-ldo-dissipation`——它们的 finding 与 intent 节是两条独立出口，见 §3.2 的细则。
- **093 A3a 起 intent 进评级**（A1 以来第一次口径变化，`rules/archclosure.py` 的模块
  docstring 是权威表）：

  | 情况 | 级别 |
  |---|---|
  | 违反 `user_stated`（工程师自己声明的架构被图纸违反） | **ERROR**（`apply` 必拦，`--force` 不豁免） |
  | 违反 `verified_recipe` / `ai_asserted`（草稿不一致） | **WARN**（草稿行带「确认前不要照改」，052 §4） |
  | 无合同 | 不查，零移动（读数逐字节不变） |
  | 结构性闭合（开漏上拉、NRST，不依赖合同） | 违反 **WARN** / 闭合 **INFO 测量行** |

  三条规则：`arch-rail-voltage-clash`（合同的 `targetVoltage` vs 图上判定，两个来源的原始值都
  进消息，谁错人裁）、`arch-opendrain-pullup`（货架 `pull_required` 标了 `open_drain` 的脚——
  网成员里有电阻跨到 power-class 轨即闭合；合同 `decisions[]` 里 `user_stated` 的「用 MCU 内部
  上拉」也算，F2 nFAULT 案）、`arch-nrst-closure`（控制器 NRST 脚单成员网 = 裸奔，F3 案）。
  详见 §3.2 的一段。

- **094 A3b 起第四条规则 + 合同进 `apply` 走查**（F1 偏置案落地）：

  - `arch-sense-bias-closure`：合同声明 `signals[].kind = "current-sense"` 且
    `polarity = "bidirectional"`（或该条 `requires` 里点名 bias 类 token）的链，必须真的被
    偏置住。**判定按算术，不按「有没有画东西」**：偏置源内阻 `R_th = (R_up‖R_dn) + Rs`
    与采样电阻 `R_sense`（网上到地那只）比 —— `R_th ≥ R_sense` = 形同虚设（按上表分级，
    `user_stated` ⇒ **ERROR**；实测 F1：`R_th = 10500Ω` vs `R_sense = 0.1Ω`，
    `V_err = 1.65V × 0.1Ω/(10500Ω + 0.1Ω) ≈ 15.7µV`，想要 1.65V，**差 5 个数量级**）；
    `R_sense/10 < R_th < R_sense` ⇒ **WARN**（比值存疑，两个数都进消息）；`R_th ≤ R_sense/10`
    或网里有**运放输出脚**直连 ⇒ **INFO 测量行**（运放输出阻抗 Ω 级，免检分压算术）。
    **「1/10」是本规则自声明的判据，不是标准**——它写在规则 docstring 与
    `BIAS_CLOSURE_RATIO` 里，数字随行；拓扑对不上（网上有外来电阻，但远端网既不是可定价的
    power-class 轨、也不是「一上一下」的分压中点）⇒ **UNKNOWN + 点名去哪补**，不猜。
  - **合同的豁免通道**：`requirements.signals[].closure = "waived"`（可选键，缺省不写出）——
    工程师**明示放弃**这条链的闭合。`user_stated` ⇒ **INFO** 并引 `decisions[]` 的 rationale
    原文（F1 的 R4：「0.1Ω 直采，不加放大器」）；`ai_asserted`/`verified_recipe` ⇒ **WARN**
    （草稿不能自己豁免自己，052 §4）。shipped 合同
    `blocklib/intents/robot-ctrl-foc.intent.json` 的 `U+`/`W+` 已按 R4 决策标 `closure: "waived"`；
    撤掉它，同一条链立刻回到「无偏置网络」的 ERROR。
  - **合同进 apply 走查**（094 起）：`draw apply` / `edit apply`（以及 `draw plan` /
    `edit plan` 记基线那一步）的 findings 走查**带合同**——合同从
    `<BOARDWISE_HOME>/design-intent/<projectUuid>.json` 取（**apply 家族没有 `--intent` flag**），
    两边同一个合同。所以：**这次写造成的**自洽 ERROR 会真的拦保存、`--force` 也不豁免；
    写之前板上本来就有的 ERROR 不算「新增」、不拦这次写（闸比的是**新增**，见 §3.3 的
    `--force` 分工）。

每个槽一个**稳定 ID**：`<projectUuid>/<boardUuid>/<sectionKey>/<slotKey>`（`sectionKey` =
`<节>:<对象>`，节 = power/analog/control/bus/intent）。行内格式：`| 稳定 ID | 槽位 | 值 | 来源 | sig= |`，
来源写 `engineer@2026-09-27` / `ai-proposal@…` / `ai-confirmed@…`；`sig=` 是该槽**关联对象的签名**
（电源树节点集 / 链路器件序列 / 总线成员集），**别手改 sig**——它是"图纸有没有动过"的判据。

`report.json` 的 `architecture` 节是**骨架 ⊕ 意图的合并视图**：`slots[]` 每槽带 `value`/`source`/
`stale`，`totals.{slots,filled,stale,todoSlots}`，`intent.{file,present,filled,stale,orphans}`。
某个槽关联的对象被改画过（签名不符），该槽标 `stale: 图纸已变，此槽待复核`——**不删你的值、不覆盖、
不阻断出报告**；复核完把 `design-intent.md` 里那行的 `sig=` 换成报告给的新值即可。图纸里已无该对象
的行（orphan）同样保留并标 stale，不静默删。**出报告后必须逐槽走一遍**——044 的动机就是 ROBOT 板盲审
漏掉"FOC 采样无偏置"：器件级规则全对，链级意图没人推。
单点跑同一份骨架子加意图文件用 `boardwise arch <工程文件> [--out <path>]`（`design-intent.md`
落在 `--out` 的同目录）。

- **逐槽填 `TODO` 或显式写"不适用"**，一个槽都不许空着走：槽位键是固定英文
  （`quantity`/`range`/`polarity`/`reference`/`gainStage`/`filter`/`sourceImpedance`/
  `endpointConsistency`/`completeness`…），每条链、每张轨各一组。**填不出来不许猜。**
- **设计意图槽位（`targetVoltage`/`continuousCurrent`/`peakCurrent`/`operatingCases`）
  填不了就显式问工程师**：这些数只在他脑中，图自身可以完全自洽（044 §6）。答一次就把答案
  写进 `design-intent.md`（**不是** `architecture.md`），**以后 finding 以它为尺**；需求变了改那里
  （活文档）。AI 提案先写 `ai-proposal@日期`，工程师点头后改 `ai-confirmed@日期`。
- **完整结论看 `completion.verdict`**（053 §2.2）：`scope{rules,boards,pages}` / `errors` /
  `unreviewedParts` / `needsDatasheet` / `warningsPendingTriage` / `architectureSlots{total,filled,stale}` /
  `openTodos` / `sourceVersions{ruleset,rulebody}`，三态 `complete`（errors=0 ∧ 未审=0 ∧ 标记=0 ∧ stale=0 ∧
  待分诊=0 ∧ **架构骨架生成了**）/ `complete-with-open-items`（errors=0 但有开放项）/
  `incomplete`（errors>0 **或** `summary.errors` 列表非空——主机 boolean 答复/整组截断时"错的条目在、
  计数未知"，闸与 `exitCode` 同源（issue #15）——**或** 未审>0 **或** 标记>0 **或** 架构骨架没生成，
  强制环节缺席不给最高置信度（issue #14））。
  `summary.mayClaimPassed` 是**窄义**字段（只回答「有没有器件缺手册未审」），**别拿它当"通过"
  的完整结论**；`verdictWhy` 直接列出是哪些开放项。
- **对每条链做目的论走查**：这条链是干什么的 → 端到端能闭合吗。骨架里
  `- evidence: 邻接 R4→GND` 这类行就是为这一步准备的（成员两端各接什么，工具照抄，判断是你的）。
- **不自洽的槽位写进最终结论，并与规则引擎 finding 分开计数**：`summary` 里的 ERROR/WARN 是
  规则引擎的；架构走查的发现单独成段，写明"架构走查 · 链 `<网名>` · 槽位 `<key>`"，
  别让读者以为是规则报的。
- 网名与端点复用功能（`endpointConsistency`）是同一类走查的机械入口：网名说它是什么功能、
  端点引脚说它是什么功能，两者对不上就是问题（TIM1 案的形态）。跨板链在单板模型里看不到，
  骨架会写明"控制器候选：无"，那种板以别处的控制器为准。

### 3.2 断连兜底与单点命令

没编辑器、只要一份规则体检，或要把发现画回画布/改一处值时，走下面这些单点命令。
**它们不替代 3.1**：3.1 能用就用 3.1。

- **手动导出 + 离线审查**（断连兜底）：编辑器 → 文件 → 导出 → **工程备份**，另存 `.epro2`
  （**导出时取消"加密"**，加密的读不了 → 退出码 2）。然后
  `boardwise review <导出.epro2> --json report.json --md report.md`
  —— 看原理图不用带参数：**047 起文件缺省视图就是 `schematic`**（011 家族规则对着
  schematic 模型写，而 schematic 是设计真相）。要审板级内容（焊盘/走线/过孔）显式
  `--view pcb`：它读 PCB 文档自己那份副本，原理图改了而板子没同步时那份副本是旧的
  （017 的幻影 finding 就是这么来的）。不知道文件在哪：`review --latest [<目录>]` 自动挑最新
  的 `.epro2` 并先打印它选了哪个。退出码 `0`/`1` 同 3.1，`2` = 文件读不了，
  `3` = **读出来是空的**（0 器件 0 网络：归档可能被截断/损坏，或 `--view pcb` 看了一份只有
  原理图的导出——"没读到"不是"干净板"，073 起不再退 `0`）。**`review --live` 同一档**（075）：
  在线拿到了模型但模型是空的（0 器件 0 网）也退 `3`，与 `checkup` 的 `coverage.modelEmpty`
  对齐——它与「根本没拿到模型」是两句话，两句话都不许读成通过。
- **eprj3 文件夹工程（V4，038 A 档只读）**：`boardwise review <工程目录> --json ...`
  —— 目录内含 `<同名>.eprj3` 索引即识别（`sch/**/*.esch2` 逐页粘成一条记录流，原理图模型满血；
  文件夹只有 schematic 这一档，047 起缺省正是它，不必再显式写）。`--view pcb` 对 eprj3
  **诚实报错**"B 档未开"，不给空模型；
  `--latest` 认 eprj3 目录（按索引 mtime 参选）；工程 uuid 从索引 `owner_uuid` 取
  （补了"只有 .epro2 才带工程 uuid"的老缺口）。**一律只读**：写路径走 bridge API，不落盘。
- **器件事实库（039 parts 工具链，纯离线）**：`boardwise parts missing --file <工程>` 列出每颗
  IC 缺哪些事实（UNKNOWN 的来源清单，含 datasheetUrl）；`parts show <mpn>` 看库里已有什么
  （每条事实带出处页码）；`parts add <mpn> --lcsc <C码>` 追加候选条目；`parts fetch <mpn>`
  取手册（`--file <PDF>` 工程师通道 / 库条目立创链接自动下载 / 都没有就打印官网查询词让你去
  WebSearch），候选事实提取是**窄**的（"引脚表+规格行"同文档才 join，Infineon 那类排版一条
  提不出、如实不改库，全文留给你读）。**`facts_verified: false` 的候选事实不驱动任何规则**
  （规则视同无 facts 报 UNKNOWN）——核验的物理形态 = xianyuyijinban审 git diff
  后翻 true。细则见 `docs/parts.md`。
- **把发现画回画布**（要 daemon + 焦点在那张原理图页）：
  `boardwise bridge call --action doc.list` 拿 `pageUuid` → `boardwise review-mark report.json --page <uuid>`。
  终端那张序号表就是图例（marker 只能画形状、不能写字，`marker#N` = 第 N 个红框）；
  `--focus 3` 跳最后一条、`--no-markers` 只看不画。清标记 `review-mark clear`
  **没有 page 守卫**（清的是最前面那块画布，2026-09-21 实测）。留证据图用 `export.render`，
  **不要**用 `bridge screenshot`（3.2.186 返回缓存空帧）。退出码 `0`/`1` 部分成功/`2` 输入坏。
- **从 finding 到局部修改**（可修范围很窄）：
  `boardwise edit plan --file <导出.epro2> --rule param-value-mpn-match --designator U3 --direction value --after <值> -o plan.json`
  → `edit preview plan.json --file ...`（离线复查，永不写）→ `edit apply plan.json --file ... --json apply.json`。
  **规则不再替你选方向也不给值**（052 §2.1：MPN 矛盾有两个修复方向——改 Value 或改 MPN/LCSC，
  048 实证过"MPN 字段写错、设计值对"的真实情形）：不给 `--direction/--after` plan 直接 exit 5 并列出两个候选；
  `--direction mpn` 本 build 未开放（需新 change kind）。方向和值都由你（或工程师的意图）给，工具一个都不猜。
  *（091 A2a：`edit plan` 这条纪律一个字没动；变的是**发现消息**——契约里有该位号的
  `decisions[].value` 时，`param-value-mpn-match` 的 finding 直接说方向 = 改料号/重选件，
  出处与 provenance 一并带出；没有就两个方向都列 + `intent-missing` 点名写进哪个键。
  **092 A2b 起 `checkup --intent`（或默认位
  `~/.boardwise/design-intent/<projectUuid>.json`）真的把合同传进规则走查了**——
  除了上面这条方向消息，另两条 rail 规则也开始读合同：`pwr-cap-voltage-rating`
  报「电容耐压 vs 所在轨轨压」（耐压 ≥ 轨压 = INFO 测量行报比值；耐压 < 轨压 = WARN；
  读不出 = UNKNOWN 并点名 `C? 的耐压（所在轨 +12V=12V）`），`path-ldo-dissipation`
  报「压差 8.7 V + P=(Vin−Vout)×I」（电流没声明 = `intent-missing` 点名
  `requirements.rails[net=…].continuousCurrent`；货架声明 `ldo.max_dissipation_mw` 才判超限）。
  两条都**不发明降额系数**：测量行永远出，判决只看两个数。
  **093 A3a 起 intent 进评级**（A1 以来第一次口径变化）：合同的 provenance 决定严重度——
  违反 `user_stated` = **ERROR**、违反 `verified_recipe`/`ai_asserted` = **WARN**、无合同不查。
  四条架构自洽规则进 `BUILTIN_RULES`：`arch-rail-voltage-clash`（合同的 `rails[].targetVoltage`
  vs 图上自己的判定，**两个来源的原始字段与值都进消息，谁错人裁**）、`arch-opendrain-pullup`
  （货架 `pull_required` 标 `open_drain` 的脚没电阻跨到 power-class 轨 = WARN；合同
  `decisions[]` 里 `user_stated` 的「用 MCU 内部上拉」算闭合——F2 nFAULT 案）、
  `arch-nrst-closure`（控制器 NRST 脚单成员网 = 裸奔 WARN——F3 案）、`arch-sense-bias-closure`
  （**094 A3b**：双向电流采样链的偏置**算术**——`R_th = R_up‖R_dn + Rs` vs `R_sense`，
  `R_th ≥ R_sense` 形同虚设按上表分级、`R_sense/10 < R_th < R_sense` WARN、`≤ R_sense/10`
  或运放输出直连 INFO；合同 `signals[].closure: "waived"` = 工程师明示放弃闭合 ⇒ INFO 引
  `decisions[]` rationale，草稿豁免 WARN；「1/10」是规则自声明判据，写在 docstring 里——F1 案）。
  **apply 闸**：ERROR 必拦，`--force` 只豁免 WARN（#55 裁决 B）；**094 A3b 起 apply 的走查
  也带合同**（基线两侧同一个 `<BOARDWISE_HOME>/design-intent/<projectUuid>.json`），所以
  「这次写造成的」自洽 ERROR 会真的拦保存，写之前就有的 ERROR 不算新增、不拦这次写。）*
  `--file` 路径**只有 `param-value-mpn-match`（单器件值）可修**，别的规则按名字拒绝
  （029 补器件、035 修脚都走 `--report` 路径，见下条）。`apply` 四道保护：
  写前重读页面 → 只写一个键 → 独立 geometry 回读 → save + 复查；重复执行认 `already_applied` 零写入。
  退出码：`0` 已应用 / `2` 效果不在板上 / `3` 页状态不可陈述（**不重试**）/ `4` 前置条件不再成立 /
  `5` plan 不可用。落盘诚实度：无"关闭重开"动作时只报 `saved_unverified`；要 `saved_verified`
  得走 关闭重开工程 → 回读/导出 #2 → 再 `review`（§6 坑 3、坑 4）。
- **修单个引脚连接**（035 `patch-pin`，要 daemon + 一份 checkup `report.json`）：
  `boardwise edit plan --report report.json --rule conn-nc-and-must-connect --designator U3 --pin 4 -o plan.json`
  → `edit preview` / `edit apply` 同上。三形态：**disconnect**（NC 脚，删掉脚上附着的那段线）、
  **connect**（悬空脚画线到既有同名网段 / power-flag / 页面已有 label）、**reconnect**（删错接 + 画新接）。
  **同一 designator 同规则有多条 pin 级 finding 时 `--pin` 必给**——不给则拒绝并列候选脚号，
  `--pin` 无匹配也拒绝；`--pin` 只作用于 `--report` 路径（029 的 decap `--report` 共用同一选择器，
  不限制在 035），配 `--file` 直接拒。connect/reconnect 的目标网必须是**用户命名网**
  （自动网 `NET\d+` / `$\S+` 判不得身份，plan 时拒，exit 5）；附着在脚上的 **netlabel 删不了**
  （本机 `sch_PrimitiveNetLabel` 连读都不存在），拒绝并点名，不替用户想办法。pin 级验收 =
  **活网表（`sch.netlist`）+ 画布（`sch.geometry`）双证**，缺一 exit 3 `verification_disagrees`；
  导出网表只作事故报告附件——**导出新鲜当且仅当本 run 无删除**（§6 坑 24）。
- **插入 RC / 分压子电路**（036 `insert-subcircuit`，要 daemon；**无驱动规则**——AI 自己判断该插什么，
  工具保证插得对）：
  `boardwise edit plan --insert rc-lowpass --pin U3.5 --r 1k --r-lcsc C7250 --c 100n --c-lcsc C14663 -o plan.json`
  → `edit preview` / `edit apply` 同上。T1 `rc-lowpass` 串联插入（断开锚点脚 → 串 R → 负载侧并 C 到 GND，
  含删除）；T2 `divider` 抽头分压（`--net <网名>` + `--r1/--r1-lcsc/--r2/--r2-lcsc`，纯 create）。
  值与 lcsc **全显式无默认**（029 红线：未验证配方不静默落件）；`--insert` 与 `--file`/`--report` 同给直接拒。
  **判据与 029/035 不同**：本片无规则，幂等探测与回读的判据 = **plan 自己的 postconditions**
  （一个函数两用：写前探测、写后回读），双证缺一 exit 3；范围分家照旧（T1 含删除 → 画布身份级 +
  活网表；T2 纯 create → 导出核对）；apply 后全规则 findings 分级拦（#55 裁决 B，2026-10-02）：
  **ERROR 必拦、WARN 要 `--force` 才放行（放行的 WARN 进报告 `findings.forcedWarns` 与 notes，
  不许静默）、INFO 只进报告永不拦**；仍被拦的走 exit 2 并打印新增行。`draw apply` 与
  `edit apply`（insert / move 两条路径）**同一口径**（同一个 `_new_findings_verdict`）。
  **094 A3b 起这条闸还带合同**：基线（plan 记的那次）与写后重读**同一个** DesignIntent
  （从 `<BOARDWISE_HOME>/design-intent/<projectUuid>.json` 取），所以「这次写造成的」自洽
  ERROR（如把双向采样链的偏置改坏 → `arch-sense-bias-closure` ERROR）会真的拦保存、
  `--force` 也不豁免；写之前板上就有的 ERROR 不算新增、不拦这次写。
  落点是**两件一起**的九宫阶梯（模板自带相对偏移 + bbox 干涉检查），位号池取「页面 ∪ 工程导出」
  （§6 坑 25）。
- **局部移动一个功能块**（037 `move-block`，要 daemon；无驱动规则——AI 点名移什么，工具保证连接不变）：
  `boardwise edit plan --move --designators R7,C9 --dx 100 --dy 0 -o plan.json` → `edit preview` / `edit apply` 同上。
  dx/dy 必须是**网格整数倍**（5 的倍数），否则 plan 拒绝。**宿主移器件不拖线**（§6 坑 26）：
  线一律删除 + 正交重画（组内线在两个移动脚之间 `wire_route` 重画，边界线重画到离移动脚最远的原上报点）。
  五种拒绝并点名：边界 label/netflag/总线、组内非器件图元、目标位压既有图元或压组外走线、
  位号找不到/一对多、off-grid。**验收主判据 = 网表恒等**——移动不许改任何连接
  （活网表逐脚岛屿比对，自动网同岛规则），任何一脚变了 exit 2；幂等与 stale 判据 = plan 自己的
  postconditions（036 先例）；`modify_primitive` 报错先回读位姿、**证明没落地**才许重试一次
  （举证重试，写进报告——盲目重试仍禁）。注意：本机造不出"边界带 label"的现场
  （`place_netlabel` 不可用），该拒绝只有离线用例，别在真机上硬试。


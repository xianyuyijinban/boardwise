---
name: boardwise
description: boardwise —— 立创 EDA Pro（EasyEDA Pro）的 AI harness：离线设计审查（review 规则引擎）、把审查发现画回编辑器画布（review-mark）、从一条 finding 生成并执行局部修改（edit plan/preview/apply）、经本机 bridge 读写活着的编辑器（doc.list / readback / geometry / export.render / export.fab）。当用户提到立创 EDA、EasyEDA、原理图审查、网表检查、.epro2 / .eprj2 导出、打板三件套（Gerber/BOM/坐标）、boardwise、bridge、connector，或要求"审查这块板""把问题画到图上""改掉这个器件的值""导出打板文件"时加载。
whenToUse: 用户提到立创 EDA / EasyEDA / 原理图审查 / 网表 / boardwise / bridge / connector / .epro2 / 打板 / Gerber / BOM / 画板 / 器件位号，或要求在编辑器里读当前工程、在画布上打标、改器件值、导出制造文件时
---

# boardwise（立创 EDA Pro 的 AI harness）

> **本文件是该项目的唯一权威 skill。** 用户级目录里那份 `easyeda-agent` skill
> （`~/.claude/skills/easyeda-agent/`，作者 zhoushoujianwork，v1.4.8）属于**另一个项目**：
> 它的 CLI 叫 `easyeda`、门禁叫 `easyeda update --check`、connector 版本号体系也不同。
> 本仓库一律只用 `boardwise` CLI；两处说法冲突时以本文件为准。
> 事实来源：本仓库 `docs/`、`tasks/`、`outputs/`（真机校准宿主：立创 EDA Pro **3.2.186**）。

## 1. 何时加载 · 先做什么

触发：立创 EDA / EasyEDA / 原理图审查 / 网表 / `.epro2` / `.eprj2` / 位号 / 打板 /
Gerber / BOM / boardwise / bridge / connector / 画布打标 / 改器件值。

第一条命令（无编辑器也能跑，确认这份安装能不能干活）：

```bash
boardwise doctor            # 10 项全绿（skip 不算红）= 装好了；退出 0 = 全绿，1 = 有红项
```

- **只做审查（离线）**：不需要编辑器、不需要 daemon。给一个 `.epro2` 就能跑 `review`。
- **要读/写活着的编辑器**：需要 daemon（`boardwise bridge start`，前台窗口）+ 编辑器里的
  connector 扩展（`.eext`）。缺一不可，报错分别是 `daemon not reachable` / `NO_CONNECTOR`。
- 开发态用仓库解释器：`E:\boardwise\.venv\Scripts\python.exe -m boardwise.cli <命令>`。
- **把这份 skill 装到别的 agent 上**：`boardwise install-skill` 写进 Kimi Code / Claude Code 的
  用户级 skill 目录（`--harness {kimi,claude,all}`，默认全装；目标位置已有异版先备份成
  `SKILL.md.bak-<日期>`）；别的 harness 跑 `boardwise install-skill --agent` —— 它**打印一段
  引导指令**，整段粘给你的 AI，放哪儿由它自己按自己的约定定（我们不维护 harness 路径表）。

## 2. 三个进程与两条入口

```
立创 EDA Pro（宿主，唯一有 eda.* API 的进程）
  └── boardwise connector（.eext，唯一有"手"的代码，主动 dial 出去）
        ⇅ ws://127.0.0.1:61190/eda
boardwise daemon（Python，`boardwise bridge start`，路由 + 审计 + 动作白名单）
        ⇅ 同一协议，role="cli"
boardwise CLI（`boardwise bridge call …`，短命进程）
```

- 编辑器是**主动外连**的（扩展不能监听端口），所以 daemon 是服务端。
- 配对是 TOFU：第一次连上就信，之后只认那个 token（`~/.boardwise/connector-token`）。
  换环境/清过配对用 `boardwise bridge revoke`。
- 审计日志 `~/.boardwise/audit/`：每个动作都有记录。工程出了怪事，先看当天的日志。
- **多窗口：用 `--project` 或 `--instance` 指哪打哪（023 起）。** 一个工程一个窗口、各连各的，
  daemon 全部登记；`bridge call --project <工程名或uuid>` 只落到那个窗口，`bridge status` 列出所有
  在线窗口（`windowKey` / 工程 / 页 / 路由次数）。不带 hint 且开了多个窗口时会明确报
  `WINDOW_UNSPECIFIED` 并列候选，指错工程报 `PROJECT_NOT_CONNECTED`，同名多窗口报
  `PROJECT_AMBIGUOUS`——**daemon 不猜**。写动作仍只碰 `test` / `test2`；
  018 的拒绝逻辑与 `CONNECTOR_ALREADY_ACTIVE` 拒绝码已退役（码留在词表里）。
  **编辑器刚重启时**每个窗口的 `context` 可能全是 null（API 还没起来），此时 `--project` 谁也匹配
  不上——用 `bridge call --instance <windowKey>` 按实例 id 直达（两个 hint 同时给时 instance 优先，
  未命中报 `WINDOW_NOT_CONNECTED` 并列在线窗口）；`bridge update-connector --instance <windowKey>`
  可热更指定窗口（`--all` 更新全部在线窗口；多窗又不寻址则**拒绝并列窗口表**，见坑 22）。

## 3. 审查闭环（朋友主用这条）

> **工作流编译在工具里，skill 只说什么时候调它。** 一条命令把数据取回、把主机 DRC 和自有规则跑完、
> 把要模型判断的东西（不熟器件、画布图、总结）摆成槽位；skill 不再描述流程步骤，
> 只描述"看到什么就跑哪条、槽位怎么填"。

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
  **per-page 档里跨页同名的网不是已验证的连接**（issue #19）：按网找协同器件的 7 条规则
  （`decap-required-caps` / `conn-nc-and-must-connect` / `conn-usb-cc-pulldown` /
  `param-divider-output` / `path-ldo-dropout` / `pwr-domain-vs-range` /
  `pwr-supply-on-known-domain`）对出现在多于一个页的网名**一律不下通过/违规结论，只报 UNKNOWN**
  ——同名可能是同一块板的另一张页（真连），也可能是另一块板碰巧同名（假连），这一档分不出来。
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
  活网表；T2 纯 create → 导出核对）；apply 后全规则 findings **只许减不许增**（新增 exit 2 打印新增行）。
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

### 3.3 画法编译器落图（054：`draw compile` / `draw plan` / `draw apply`）

053 阶段 B 的编译器离线算出**画法**（`LayoutPlan`：器件+姿态+折线+旗标+文字 bbox，
`engines/drawcompiler.py`），054 把一张画法落进编辑器的一页。三条命令：

```bash
boardwise draw compile --circuit C.json --presentation P.json --profiles LIB.json \
    --page-box 0,0,1170,825 --out outputs/054_x/previews      # 离线：ranked 表 + 四分类 + SVG
boardwise draw plan    --circuit … --presentation … --profiles … --page-box … \
    --page <uuid> --project test --lcsc R1=C25744 --out plan.json   # 一候选 → ChangePlan
boardwise draw apply   plan.json --project test \
    --circuit … --presentation … --profiles … --layout <cand1.layout.json> \
    --render render.png --json apply.json                     # 真机：守卫 → 落图 → 回读 → 保存 → 出图
```

**落图前必须先有"实测符号库"**（本批最关键的一条工序，C1/C2 都是这么过的）：
编辑器**不提供**库符号几何的读接口（`lib.symbol.get` 明说 no geometry），所以
`--profiles` 的那份库要**先在真机上量**——在临时页上放一颗真器件（`sch.place_component
--params '{"lcsc":"C25744","x":400,"y":300}'`），读 `sch.component_pins`（引脚偏移 + PinLength）
和 `sch.geometry --params '{"bboxIds":[<id>]}'`（实测外框 = body），删掉这颗探针件，
再把量到的数字写成 `SymbolProfile`（`source` 里写清量法与出处）。
实测：C25744（0402 10k）引脚 ±20、body ±10.5×±4.5；C1525（0402 100n）引脚 ±20、body ±10.5×±8.5。
拿**竖排 ±50** 这类没量过的 profile 去落图，引脚回读必然点名不符（C6 现场）。

**apply 的执行序**（`_draw_apply_flow`）：① 页（`--page` 或 `--new-page`；plan 未绑页又没给页 → exit 5）
→ ② 守卫（双 spec 摘要 + 布局摘要 + 库几何表 + 页身份；**显式** `--expect-census` 也在这关）
→ ③ 探针（plan 自己的 postconditions，双证齐全 = `already_applied` exit 0 零写入）
→ ④ 页既不是 plan 成品也不是 plan 基线 → `canvas_changed` exit 4 零写入
→ ⑤ 位号池（页面 ∪ 工程导出）→ ⑥ 放件 → ⑦ **写 Value**（055 起：plan 用 `valueKey` 逐件
声明，无 key/无值**不写不报**；`sch.set_component_attribute` 既有通道零新增）
→ ⑧ **引脚回读**（容差半格，同一把 geometry 读同时做值回读；引脚不符、值写不进/回读不符
**都在拉线前**停住 exit 3）→ ⑨ 走线（`net` 承载网名）→ ⑩ 旗标（`place_power`）→ ⑪ 双证回读
（活网表按**本 plan 自己的引脚**判分区；页面外同名同网只报 `sharedWithOutsidePins`）
→ ⑫ 范围（无删除 → 导出新鲜）+ findings 只减不增
→ ⑬ 保存（`saved_unverified`，要 `saved_verified` 得走 `boardwise persistence` 的关闭重开）
→ ⑭ `export.render` 出图（`already_applied` 也出图：图是证据不是写）
→ ⑮ **旗标朝向核对**（坑 42 的手法、坑 43 的事实）：出图时一并要 `format=svg`，解
`c_partid="netflag"` 组逐颗读"连接点 → 字形往哪边伸"，与 plan 里每颗旗标的 `rotation`
对表；GND 与 PWR-* 两家自然姿态相反，离线预览画的是统一约定盒、看不出这个差
（照抄姿势与判据见 `outputs/064_railflag/`）。

退出码：**0** 落图并被双证确认（或 already_applied 零写入）/ **2** 承诺的效果不在（写被拒、
保存被拒、range/旗标数不对、findings 增长）/ **3** 页状态不可陈述或回读不符（超时、拔 daemon、
引脚/值回读不符、postconditions 不满足——**在拉线前**停）/ **4** 守卫拒绝（摘要 stale、库几何变了、
页不是 plan 的、画布被动过、位号被占、半成品件在页上）/ **5** plan 或输入不可用。

幂等与 stale：`draw apply` 同 plan 再跑 → `already_applied` 零写入（C4）；手工动过画布再跑 →
exit 4 零写入（C5）；库几何不符 → exit 4 零写入（C6，写前那条腿用 `--profiles` 的库文档，
编辑器侧那条腿只能靠放完后的引脚回读，所以它是 exit 3 且件已放）。

**LDO（C3）现场有两条真机事实，照坑 33/34 走**：真机 AMS1117 符号的 VIN/VOUT/GND 全在**同一侧**
（外加一颗重复 VOUT），`ldo` 文法的默认"in 左 out 右"**无合法姿态**——要么按坑 33 用
`sidePreferences`（这是一个**说明**"下面那条输出支路"，不是"输出在下方"），要么换一颗符号；
另有坑 34：本仓库 facts 要求 AMS1117 输出 ≥22µF（053 场景值 055 起已同步为 22µF），拿 100n
输出落图 `decap-required-caps` 会涨 finding、`draw apply` 按 036 规矩**拒绝保存**（图落好了、没落盘）。

**057：一页多模块（页文档）与 `draw discard`——不加命令、不加旗标，同三条命令**：

- **什么算"页"**：PresentationSpec 有 ≥2 个 `modules[]`、或写了 `flow`、或某模块自带 `grammarRef`、
  或有页级锁（`pagecompiler.wants_page`）→ 走页级编译；恰一个模块（054 夹具那种）走原单模块路径，输出一字不变。
  页级 `draw compile` **必须给 `--page-box`**，产物是 `candN.page.json`（`kind=boardwise-page-layout-plan`）+
  带模块虚线框的 `candN.svg`。
- **`draw plan`（页）**：页级编译后把选中候选的 `plan` 字段交给同一个 `module_plan`，产出的仍是
  `draw-module` plan（layoutSha256 = 页文档 `plan` 的几何哈希），旁边写 `<plan>.page.json`。带 `--page`
  时读页面 census，**每个既有图元（件/线/旗标，件用 `bboxIds` 实测外框）转 keepout**，模块组整体平移避开；
  全被占 → `presentation-poor` 点名"existing R5 …"。页文档里的跨模块标签在本机放不了（坑 9），**没有线
  到达的标签点会补一段 10 单位具名短线**（downgrades 里写明），否则两边同名网在工程级网表里合不起来。
- **`draw apply`**：`--layout` 可给页文档；位置参数也可直接给页文档（需 `--circuit/--presentation/--profiles`
  + `--page`/`--new-page`），运行时现建 plan 再走原流程；页文档的"过期守卫" = 它的模块框对页面现状的
  keepout 规则（压到既有图元 → exit 4 零写入）；要"页面任何变动都拒"用 `draw plan --page` 产的 plan
  （census 摘要精确）或 `--expect-census`。**所有落图**新增范围外逐项对比：落图前已在页上的每个图元
  （位号/值/LCSC/网/坐标/姿态/线点）必须原样，改了一件 → exit 2 不保存（`range.outOfScope`）。
  报告 `verification.nets` 逐网列出编辑器网表回读名，跨模块网标 `crossModule`、`oneNet`（G4）。
  findings 只减不增按身份（`rule|severity|位号|脚|命名网`），不按计数。
- **页级锁**：`userLocks[]` 加 `"scope": "page"`（不写 rotation；位姿归模块）→ 该件在每个候选都落在
  页坐标 P（origin = P − 模块内坐标，逐代次不同是对的）；锁点出页 / 两把锁矛盾 / 锁住的框出页、压
  keepout、与另一锁住的框冲突 → `presentation-poor` 点名锁。模块锁（默认 scope）与页锁可同件共存。
- **`draw discard <plan.json|page.json>`**：只删该 plan 自己画的东西。件按**位号 + 坐标 + 值**（无 valueKey
  的旧 plan 用 LCSC）核身份，旗标按网 + 点，线要求**每个点都在 plan 的线上**（被宿主并进别人线的 primitive
  不删，坑 32）；**任何一件不符整批拒删**（exit 4，零删除）。先线、再旗标、后件（每相每次 ≤30 id，分批
  会写进报告）；删后回读：目标全无 + 范围外逐项不变。第二遍 = `nothing_to_discard` exit 0。`--save` 才保存；
  超时/断连先回读、不重试（exit 3）。页文档需 `--circuit/--presentation/--profiles`，按坐标 + 前缀 + 值找件。
- **已知缺口（057 离线实测，`tools/057_scenarios.py`）**：CH340G 核心/晶振/USB 侧**没有文法**（只有
  divider/RC/LDO），页级编译对这三组报 `facts-missing`；金样板上的 RT9013（VIN/GND/EN 同在左侧）在 `ldo`
  文法下 48 种 sidePreferences **全部无合法姿态**——坑 33 的"改输入侧"对它无效。真机 E1–E7 的操作清单见
  `tools/057_live_runbook.md`。
- **074：旗引线不得穿越别网导体**（岳裁「必须改」，命令面一字未增）。069 落下的 pin2 3V3 旗引线
  「横 50 + 竖拐 25」的**竖拐**子线段与 5V0 横轨在 (60,740) 垂直交叉、无 junction 圆点——电气双岛正确，
  但第一眼读成「旗挂在 5V0 轨上」。尺子：候选引线的**每个子线段**与别网导体（`router.edges` +
  已落件引脚）做**严格内部**相交——共享端点、T 型衔接（端点落线 = 有意的 junction）、共线重叠都**不算**；
  只硬化**旗引线/stub 段**（069① 远脚 stub、`_rail_flag` 沿轨段、竖拐 jog），**普通信号布线穿越不硬化**
  （crossings 仍是软指标）。硬拒后按既有梯子升级（距离档 → 逃逸方向 → 三折/两段引线 → 向无轨方向垂挂）；
  梯子穷尽 → `layout-unsat`，报**哪段穿哪条导体 + 交叉点 + 建议动作**，**不许静默产出穿越图、不许假
  junction**（安全阀：`layout-unsat` 是契约内的合法答复，不是 bug）。

## 4. 真机纪律（写操作前逐条对，命中即停）

**R1 身份判定**：动手前，`doc.list` 报的焦点工程名与任务书**逐字一致**，且页特征
（页名/器件数/未布线态/标记）**全项命中**；1 项不命中就停手。
**禁止**用页面内容与夹具/参考电路的相似度判定工程身份——测试工程里全是参考电路拷贝，
内容匹配必然全中，什么也证明不了。

**R2 事故申报纪律**：申报"删错/损坏"前，必须先用 R1 同一套证据（工程名 + uuid + 磁盘结构）
重建现场。证据不足只许报"异常待裁"。**假警报与误删同等对待**——都会吓停正确的工作。

**R3 找不到 ≠ 已清**：目标缺失就停下来问，不许自行解释、不许自行替代。

**白名单与禁地**：
- 可以写：任务书**逐字点名**的测试工程（`/test` = `test.eprj2`；018 起含 `test2`）。
- **禁地（任何情况下不许写）**：`毕设FOC驱动板`、`CH340G.eprj2`、`ROBOT ctrl FOC.eprj2`
  ……以及一切真实工程。`tasks/012` 曾把 `test2` 与 CH340G 一并列为禁写，口径以**当前任务书**
  为准；任务书没点名 = 不许写，不靠猜。
- 写动作一律带 `pageUuid`（守卫实测拦下过两次错位写，见坑 1）。
- 破坏性/外向型操作（删除、推送、发布）先确认再动手；git 变更逐次经xianyuyijinban点头。

**R4 工程文件永不入库（2026-09-26 起，公司板红线）**：真实工程容器
（`.epro2/.eprj2/.eprj3/.epru/.esch/.epcb`）**一律不 commit**——公司板进公开仓库 =
设计泄漏，删文件没用，历史里还在。审查产物只进 `outputs/`、`.tmp_*`（均 gitignore）；
不 harvest 公司板进 blocklib，不做成夹具。机械防线：`tools/check_repo_hygiene.py`
（pytest `tests/test_repo_hygiene.py` 常跑 + 本机 pre-commit 钩子已装）；新夹具要入库 =
在同一笔提交里**显式**加 `ALLOWLIST` 路径，那就是评审时刻。

**R4b 公司板命名规范（2026-09-26 起）**：公司板在**一切公开产物**——commit 信息、
任务书、issue、release notes、文档、测试名——只用 `PCB1`/`PCB2`/`PCB3`… 匿名代号；
产品名、应用场景、客户、关键型号（能反推出产品的芯片/方案组合）**零出现**。方法论
数字可以留（如"5A 级控制器 vs 2.62A 电感"是教训本体），能定位到"是谁的板"的信息
一律抹掉。提交前 `grep -rli` 自查一遍。

## 5. bridge 高频动作速查（全表：`docs/bridge.md` §4）

调用形态：`boardwise bridge call --action <名字> --params '<JSON>'`；
`create` 类动作（新建文档）需 `--yes`，否则 daemon 回 `CONFIRMATION_REQUIRED`。
开了多个编辑器窗口时加 `--project <工程名或uuid>` 或 `--instance <windowKey>`（023）：
见 §2 多窗口那条。**多窗口验证基线是 3.2.186**——3.2.149 上第二个窗口的 connector 不上线
（页面重载后才上线；issue #4，见 §6 坑 18）。

| 动作 | 用途 / 关键参数 | 要点 |
|---|---|---|
| `ping` | daemon 活着吗 | daemon 自己答，`version` 是 daemon 版本；`bridge status` 就是它 |
| `doc.list` | 焦点工程 + 所有页/板 + 多工程视图 | 非焦点工程只给 `brief`（无文档树）；无焦点文档时 `active: null` |
| `document.current` | 活动文档/标签属于哪个工程 | 与 `doc.list` **不一致**是已知坑（坑 1） |
| `sys.probe` | 宿主 API 面在位检查 | `params:{"checks":true}` 按生成的名单逐个 `typeof`；`{"checks":{...}}` 显式名单逐名覆盖；`{"call":"<动作>","params":{...}}` 调白名单内四个只读动作（025 批 1，绕坑 8 的加载期目录，probe 专用）；权威依据是**真机 probe**，不是类型包声明 |
| `doc.open` | 打开/切到某个 uuid 的文档 | `{uuid}`；只在**活动工程**内寻址，跨工程找不到（坑 1） |
| `sch.readback` | 页内器件清单 | 键集合写死：**没有 value、没有 mpn**（坑 3） |
| `sch.geometry` | 原始几何 + 实测页面 bbox | `{bboxIds}`；整页只读一次的坐标来源（打标/定位用） |
| `sch.netlist` | 编辑器自己的网表 | 60 s；**没有** connector 内回退（旧 `getNetlist()` 实测会挂） |
| `export.render` | 页/选区/工程的 PNG/SVG/PDF | **验收图走这条**；`scope:'selection'` 需 `ids`；多页工程可能回 zip |
| `canvas.highlight` | 按 uuid 画框（overlay） | `{uuids, color, clear}`；uuid 解析不上的在 `unresolved`，非空 = 先确认焦点在哪张画布 |
| `review.mark` | 把审查发现画到焦点原理图页 | `{pageUuid, marks:[{ref,ruleId,severity,text}], clear, focus, markers}`；CLI 封装是 `boardwise review-mark` |
| `sch.set_component_attribute` | 改器件属性（单键 + 读回） | `applied` 的含义是**回读匹配**；`clobberedOtherKeys` 非空要警觉 |
| `sch.doc.save` | 显式保存 | `{saved:true}` ≠ 已落盘（坑 5） |
| `sch.delete_primitives` | 删件（按 id，逐件诚实结果） | **~3.7 s/件**，daemon 预算 150 s（坑 2）；`sch_PrimitiveAttribute` 无法按 id 寻址 |
| `export.fab` | Gerber + 坐标 + BOM + manifest | 240 s；`boardwise bridge export-fab --out DIR [--pcb] [--vendor generic]` 负责落盘 |

常用但不入表：`sys.identity`（018 新增：一次给两边焦点 + 是否一致；老版本报
`UNKNOWN_ACTION` 时改用 `doc.list` + `document.current` 双查）、`pcb.readback`、
`doc.focus`、`doc.delete_page`、`pcb.doc.new`（需 `confirm`）、`sch.modify_primitive`、
`sch.place_*`（画板流，见 `docs/draw.md`）、`lib.device.search` / `lib.recommend`、
`sch.component_pins`、`doc.rename`、`sys.self_update`（`boardwise bridge update-connector`）。

错误码（`docs/bridge.md` §5）：`UNAUTHENTICATED` 配对不对 / `PROTOCOL_VIOLATION` 两个编辑器
/ `NO_CONNECTOR` 编辑器没连上 / `UNKNOWN_ACTION` 动作不在目录（多为 daemon 版本旧）
/ `PAGE_MISMATCH` 焦点不在你以为的那页 / `NOT_FOUND`、`NOT_IMPLEMENTED`、`TIMEOUT`。

## 6. 真机事实坑表（每条都真机踩过，出处可查）

| # | 事实 | 怎么用 |
|---|---|---|
| 1 | **两层焦点可以不一致**：`doc.list` 报 `focused=/test`，而编辑区活动文档属另一个工程（实测是 `ROBOT ctrl FOC`，禁地）。`doc.open` 找 `/test` 的 uuid 三连 `CONNECTOR_ERROR`——它在**活动工程**内寻址。更早的形态：工程焦点与 `dmt_Schematic` 上下文页报不同答案 | 写前**双查**（`doc.list` + `document.current`），两边工程名逐字一致才动手；`doc.open` 报错本身就是守卫，不要绕过。出处 `tasks/016` §十.5、`outputs/012v2_probe.md` §三.1 |
| 2 | **删除逐件 ~3.7 s**（编辑器每件重解页面） | 17 件批删实测 63 s；daemon `DELETE_TIMEOUT=150 s`（约 40 件）。别按 30 s 估超时，别为凑超时偷偷分批。出处 `src/boardwise/bridge/protocol.py:120`、`outputs/012v2_probe.md` §三.3 |
| 3 | **`sch.readback` 没有 value / 没有 mpn 通道**：每行是写死的键集合（designator/name/footprint/supplier/supplierId/fields…），`Value`/`mpn` 都拿不到 | 需要 value/mpn 只能走**导出 `.epro2` + `review`/`edit plan`** 的解析通道。别拿 readback 当复查模型。出处 `outputs/016_probe_readback.txt` |
| 4 | **`.eprj2` 只是工程目录册**：`projects` / `project_structures`（页目录快照）/ `history_data` / `project_images`；**器件级内容不在里面**（新放器件的 uuid、MPN 全 0 命中） | 用 `grep` 工程文件验证器件落盘**此路不通**。器件级持久化只能走编辑器通道（关闭重开 → 回读/导出 `.epro2` → `review`）；删页之所以能验是因为它动的是结构层。出处 `tasks/016` §十.6 |
| 5 | **保存是异步落盘**：`save` 回 `{saved:true}` 不等于已落盘（结构层 updateTime 刷新 + mtime 跳变有延迟） | 说"已保存"要有第二证据：结构层刷新 / 关闭重开回读 / 导出 #2 复查 |
| 6 | `export.screenshot`（`bridge screenshot`）在 3.2.186 上返回**缓存空帧** | 截图证据用 `export.render`，或系统截图工具（Win+Shift+S）。出处 `docs/getting-started.md:197`、013 报告 |
| 7 | `review.mark` 的 `clear` **没有 page 守卫**；`markers:false`／宿主无 marker API／画布拒绝 → 降级成 `mode:'list'` 跳转清单（**这是契约，不是错误路径**） | 清标记前先确认焦点；别把降级当成失败 |
| 8 | **动作表是 daemon 加载期常量** | 改过代码/换过版本必须重启 daemon，否则明明实现好了却报 `UNKNOWN_ACTION` |
| 9 | `sch.place_netlabel` 在 3.2.186 上**根本不能用**（`createNetLabel` 是 v4 API）；`sch.place_text` 是**装饰性**的（编辑器网表不读它） | 网名靠 wire 承载 + text 给人看；别指望 text 建立连接 |
| 10 | 写动作可能**超时但已经落件**（`sch.place_component` 首次解析库超 30 s） | 错误文案自己写着 do NOT retry——**先回读，不盲重试**（盲重试会把器件叠一堆） |
| 11 | **坐标契约**：文件 ≡ 画布，y 向上；`.epro2` 存 `y = −canvas`，解析器只在边界取反一次；旋转 文件角 CCW、API 角 CW，`θ_file ≡ −θ_API` | 改任何坐标/角度前先读 `PROGRESS.md` 的 Coordinate contract（这项历史代价最大） |
| 12 | 已知**实现偏差**：断 daemon 时 `edit apply` 曾返 `2`（契约应为 `3` = 页状态不可陈述） | 018 §A 已定修（改 `cli.py` 该处 `return 3` + 补测试）；读到 2 时按"连不上"理解，别当成"效果不在板上" |
| 13 | **编辑器整关重开后读数可能是同步滞后的陈旧视图**：器件已持久化却短暂"消失"（R1 实测：08:58 读无、09:03 复活，值与 uuid 原样），追平后恢复 | 重启编辑器后**别立即信 readback**——判"丢件"前隔几十秒复读或导出复核；否则会把持久化误判成失效、甚至重复放置。出处 `outputs/016_scene6_final.txt` |
| 14 | **`review` 读 `.epro2` 的视图口径**（047 翻转）：缺省 view 是 **schematic**（设计真相）；`--view pcb` 读的是 PCB 文档自己那份副本，原理图改了而板子没同步时它是**旧的**（017 的幻影 finding 根因） | 审原理图不用带参数；审板级内容才 `--view pcb`。拿到 "0 组件 0 网" 先想 view，再想导出——显式 pcb 视图空时会补一行提示。出处 `outputs/016_scene6_final.txt` 教训 B、017 视图口径裁定 |
| 15 | `sch.geometry` 响应键是 `components/wires/pins/netlabels/bboxes/meta`——**没有 `parts`** | 写诊断脚本先打印 `list(d.keys())` 再取值；拿不存在的键 `.get()` 恒空，会编造出"空页"假象。出处 `outputs/016_scene6_final.txt` 教训 C |
| 16 | **热更/自更新后页面 reload，焦点抛到家页**（`type:home`，uuid 形似 `tab_page1`） | 热更后立刻读/写页面前先 `doc.open` 定点，否则动作落在家页报错。出处 025 批 1 |
| 17 | **主机 ERC 计数是 host-wide，不按页**：多页逐页调 `sch.drc_check` 各报同一读数（4 页都 `{warn:1}`），求和会编出 4 倍错误数；PCB DRC 树**没有 severity 字段**，叶子的 `parentId` 第二段才是编辑器自己的页签名 | ERC 计数全工程只报一次（标 `host-wide`）；PCB 叶子 severity 用 parentId 分流，读不出按 ERROR 并标 `assumed`。出处 `outputs/025c_checkup_live.txt`、025 批 3 |
| 18 | **3.2.149 开两个窗口时第二个编辑器窗口的 connector 不上线**（页面重载后第二个才上线）：窗口冻结/懒求值，与本机背景窗口冻结 7 小时同源，**不是** activate 派发问题（3.2.149.88089769 冷启动 activate 正常派发） | 多窗口作业先在 3.2.18x 上做；149 的多窗口等 Worker watchdog。出处 issue #4（2026-09-23）、`tasks/024-easyeda-3.2.149-bootstrap.md` §现场验证修订、`tasks/025-review-flow-v2.md:151` |
| 19 | **宿主 `sys_Timer` 也吃页面节流**：`eda.sys_Timer.setIntervalTimer` 的回调由宿主投到**页面任务队列**，后台窗口里与页面时钟吃同一张节流时刻表（三钟同段实测：宿主 150 s 只 18 次，48 s/60 s/35 s 三个大间隔与页面逐一重合；同段 Worker 158/158）。`...args` 透传是真的（`callbackArgs` 拿到 `['probe-arg', 42]`） | 想要"后台免疫"只能用 `blob:` Worker 自己的定时器（0.4.17 的 watchdog 就是它）；**别**把宿主定时器当后台闹钟。出处 `outputs/026_probe_p5_host_timer.txt`、`tasks/026-worker-watchdog.md` §三.5 |
| 20 | **让窗口真"后台"只能抢走前台**：`ShowWindow(SW_MINIMIZE)` / `WM_SYSCOMMAND:SC_MINIMIZE` / `SetWindowPos(HWND_BOTTOM)` 在本机**都不改变前台**（`IsIconic` 恒 false，只压 z 序）；窗口仍持前台时 Chromium **不节流**，后台读数全是废的。抢前台只有 `powershell -NoProfile -Command "…SetForegroundWindow…"` **内联**生效，同一段代码写成 `.ps1` 走 `-File` **不生效** | 用 `.tmp_026_fg.py`（`away`/`front`/枚举窗口）：抢完必须**复读** `GetForegroundWindow` 确认不是编辑器，后台成立的旁证是连接器心跳出现 **60 s 间隔**（audit 里 `ping role=connector` 的间距）。出处 026 P5、026b 批 2b |
| 21 | **诊断脚本自己会把现场搞死**（两个都实测踩过）：① `subprocess.run([... , "Start-Process", ...], capture_output=True)` 起后台进程**会一直等继承过去的管道 EOF** —— daemon 起来了，调用永不返回，脚本卡死而 `finally` 都跑不到；② 节流态下 `bridge status` 单次可以等 **~35 s**（它要 ping 到被节流的页面），拿它轮询会把脚本自己拖死 | ① 起后台进程一律 `Popen(..., creationflags=DETACHED_PROCESS\|CREATE_NEW_PROCESS_GROUP, stdout=DEVNULL)`，**不要** capture；② 量"重连时刻"这类事件**直接读 audit** 的 `{ts, action:"hello", role:"connector", projectName, instanceId}`，别问 CLI。出处 `outputs/026b_2b_throttled_recovery.txt` §五、026b 批 2b |
| 22 | **多窗口 update-connector 的三档行为与共享存储盲区**（030，xianyuyijinban 2026-09-24 实测四坑）：① 多窗又不寻址 → 旧版本直接把无 hint 的调用发出去，daemon 回 `WINDOW_UNSPECIFIED`（像"更新失败"）；现在 CLI **先读窗口表再拒绝**（exit 2）并列出窗口表 + 两种做法。② 一个编辑器里**多个窗口共用同一份扩展存储**（IndexedDB `User_<teamUuid>_v6`）：第二个窗口的 `sys.self_update` 报 `0.4.19 -> 0.4.19`（记录已被第一窗改过），不是出错也不是没写——**写就是 reload 的唯一触发器**（`location.reload()` 挂在同一个动作里），所以 `--all` 每窗都要写一次，去重只能体现在"同一存储记录只改动一次"的报告上。③ reload 后 **instance id 必变**（`newInstanceId()` 每次模块求值一次），旧 id 作废。④ reload 后有一段**匿名期**（xianyuyijinban见约 4 分钟；本机 2026-09-24 复测：10:55:09 重连 → 10:55:27 `--project test` 报 `PROJECT_NOT_CONNECTED` → 用 `--instance` 调一次 → 10:55:38 `--project` 就恢复了）：匿名期**用 `--instance <新 id>` 直达**，窗口一应答工程名就回来，不是等满 4 分钟，也不是显示 bug | 多窗更新用 `--all`（逐窗写、逐窗 reload、逐窗验收，每窗一行 verified/unknown）——**注意 `--all` 会 reload 每一个在线窗口，禁地窗（ROBOT、毕设FOC 等真实工程）在场时不许裸跑，先 `bridge status` 核窗口清单**；更新完 `bridge status` **逐窗核版本**；只更一窗用 `--instance <新读到的 id>`。verified 的判据是"**目标窗**旧身份从表里消失 + 写之后新出现的连接报出该版本"——别拿另一窗的应答当本窗的 verified（共享存储场景下那是假 yes）。出处 `outputs/030_*.txt`、`docs/bridge.md` §10.27 |

| 23 | **`export.render` 挂死 = 目标页自载入后从未被激活**（issue #5 正案，033）；**进度条 toast 漏是另一件事**（032）——两件事分开记，别混：3.2.149 + 0.4.21 上xianyuyijinban做了受控对照（同窗同页相隔 4 分钟，唯一变量是「导出前有没有 `doc.open` 过目标页」）：**没激活过 → png 与 svg 都挂死**（15:48:19 png 30s 超时；15:50:00 svg 同样超时）；`doc.open`（回 `activated: true`）之后 → **15:54:02 png ~2 秒成功**（662229B、magic 过）。**由此撤回两条旧结论**：①「PNG 卡死而 SVG 同刻可用」不成立——那是**单样本**（2026-09-23 18:05:53 那次成功是孤例，几分钟前 checkup 刚 `doc.open` 过那页，文档还「热」）；②「宿主不接受某个参数」与本症状无关（那是 2026-09-18 .d.ts 坑的真相，降为历史注脚）。一条机制解释全部历史观测：**checkup 从未失败**（它的画布阶段本就逐页 `doc.open` 再渲染——调用方碰巧做对了，所以 checkup **不改**），**每次裸调 `bridge call export.render` 都挂**（没先动焦点）。H1「必须是活动文档」/H2「载入后激活过一次即可」未分离，**修法相同**。**0.4.22 起 `export.render` 自己激活**：`scope=page` 时先解析目标 uuid（`params.pageUuid` ?? 当前活动文档）→ `dmt_EditorControl.openDocument(uuid)` → 成功才导出，结果带 `activatedPageUuid`；活动文档解析不到、或 `openDocument` 失败/不回 tab id → **诚实报错、不导出**（诊断沿用 `doc.open` 那套）；`scope=selection`/`project` 不动。031 的 **PNG→SVG 回退保留**（它是 checkup 超时不失败的保护），但它的旧前提已撤回：svg 在页面未激活时同样挂 | 裸调出图挂住时先查这条：**导出前目标页激活了吗**——传 `params.pageUuid`，或先 `doc.open`；checkup 对本病天然免疫（逐页 open + 渲染），**不用改**。**另一件事**：进度条 toast 漏（ManufactureData 管线开了不退，**成功也卡 99%**）——0.4.21 起 connector 在 `finally` 里 400ms 后 best-effort 拆（`destroyProgressBar`/`destroyLoading`，xianyuyijinban两样本验证通过）。心跳连续**仍不能**排除宿主故障（socket/心跳/路由计数只描述*通道*）。**149 上的根治验收归xianyuyijinban**：窗口刚载入、不 doc.open，裸调 `export.render` 应直接成功。出处 issue #5、`outputs/031_*.txt`、`outputs/032_*.txt`、`outputs/033_*.txt`、`docs/bridge.md` §10.28 `openDocument(uuid)` ≠ `activateDocument(tabId)`（**开标签页 vs 切前台激活，入参一个是 uuid、一个是 tab id**）——导出前必须**两者都做 + `getCurrentDocumentInfo()` 回读确认 `matchesRequest`** 才导出；0.4.22 只做了第一步，xianyuyijinban 149 验收当场未过（裸调仍 TIMEOUT ×2），0.4.23 补齐三步。H1/H2 **定案**：**每次导出前都要 activate**（不是"载入后激活过一次即可"）。 |
| 24 | **导出文件对删除永不重算**（035 四轮真机定论）：`save`、等 30 s、切页都不触发，四次导出逐字节一致仍报旧网表；create 会触发重算（029 实测）。⇒ 判据一句话：**导出新鲜当且仅当本 run 无删除**——含删除 run 的 pin 级新鲜读数只能走编辑器**活网表**（`sch.netlist` 的 `components[k].pinInfoMap[pin].net`，按名字给，未命名网一律空，单独证不了"两脚没共用未命名网"，**必须配画布双证**）。连带三条宿主习性：① 宿主给**悬空脚发单成员自动网**，导出名 `NET\d+`、活网表内部名 `$\S+`——**同一座岛两个名字，自动网名不是身份**（stale 检查对两个自动名视为同一岛；用户命名网仍逐名比）；② 相接的两段线被宿主**合并成一个 primitive**，接点在点表里重复上报（实测 `[345,300,345,290,255,300,345,300]`）——附着物判定必须读"脚在上报点表里"，按首尾点判会把 T 型误判成附着；③ `sch.doc.new` 的 name 参数被忽略 | pin 级验收 = 活网表 + 画布双证，缺一 exit 3，导出降级为事故报告附件；范围核对分家（含删除 → 画布身份级差异 `wiresVanished == [attachment.primitive_id]`；纯 create → 维持导出核对）。出处 `outputs/035c_live.txt`、`outputs/035d_live.txt`、`tasks/035-patch-pin.md` |
| 25 | **036 三条宿主习性（真机实证）**：① 宿主上报一条线的点会**重复结点**（实测 `[345,320,345,310,555,320,345,320]`），"最后一个点"可能只是拐角——**找线的远端要取离锚点最远的点**，单点线视为无远端、拒绝；② 宿主对撞上**工程全局**的位号会**静默改名**（要 R2、页面空、但 P4 已有 R2 → 落成 R3，改名发生在跑动中，plan 的 postcondition 随之不成立报 exit 3）⇒ 位号池必须取「**页面 ∪ 工程导出**」，只看页面必撞车；③ findings 签名别把"同一件事换措辞"和"自动网重编号"算新增（插入 100nF 后 decap 规则改措辞；悬空脚自动网 NET3→NET4）⇒ 签名 = `rule|severity|component|pins|命名网`（自动网名不计入） | 位号池、远端取点、findings 签名三处都已按此入码（036）；029 位号池同款盲点的修复见 036b。出处 `outputs/036_summary.txt`、`outputs/036_live.txt`、`tasks/036-insert-subcircuit.md` |
| 26 | **037 两条宿主习性（真机实证）**：① 宿主移动器件**不拖线**——`sch.modify_primitive` 把器件移走，线的上报端点留在原地（连接实际断开）⇒ 移动块必须删线 + 正交重画；② 宿主上报一条线是**点集不是路径**——`[445,320, 445,310, 655,320, 445,320]` 的相邻对里有从没画过的对角线 ⇒ 照抄点集"平移重画"会画出对角线挂死宿主（029-c 的课），按"相邻线段"判 T 会误报（5 单位外的脚落进幻影对角线容差，单器件移动曾被整片误拒）⇒ 附着/通脚判据只能说「**脚在不在上报点集里**」，漏判由网表恒等兜底（exit 2 按脚点名）。附带：`modify_primitive` 间歇抛宿主 `TypeError: Cannot destructure property 'cmdKey'…`（**改动前**抛，器件没动）⇒ 报错先回读位姿，证明没落地才许一次**举证重试**并写进报告 | 移动类流程一律 delete + `wire_route` 正交重画；T/附着判定禁用线段几何，用点集成员判定。出处 `outputs/037_probe.txt`、`outputs/037_live.txt`、`tasks/037-move-block.md` |
| 27 | **主机 ERC 没有逐项条目**（039 真机 probe 实证）：`sch.drc_check` 答复只有按 kind 合计（`counts/byType/total`），显式 verbose（`strict=true, includeVerboseError=true`）也只给合计、`raw=null`；42 个 action 的目录里**没有任何**能枚举 ERC 条目的动作。PCB DRC 相反——叶子带 `ruleName/explanation/obj1/obj2`，但引用是 netlist 级对象不是位号，归模块只能靠叶子的 `net` | ERC 警告分诊只摆**计数 + kind**、标 `host-wide`、文本空缺写 `textUnavailable`——不许把合计伪造成页内/逐条归属；逐条文本只能人去编辑器底部面板看。出处 `outputs/039c_erc_probe.txt` |
| 28 | **增量保存拆散 ATTR 邻接**（042 真机实证）：宿主增量保存把 COMPONENT 记录按 firstTicket 插回文档中段、新 ATTR 追加到文档尾（`parentId` 指回组件记录 id），且位移 ATTR 块会紧跟**另一颗**器件的块——按"ATTR 紧邻组件"归属不仅丢件，还会把邻居**改名**（ROBOT 49 丢 5 颗含全板电源、C11 被串名成 R14）。epro2 是 zip，**直接 grep 压缩包等于什么都没查** | 解析一律按 `parentId` 双程挂载（042 起 `_split_page` 如此）；ParseStats 看 `attrs_attached_by_parent_id` / `instances_without_designator`；查 epro2 内容先 unzip。出处 `tasks/042-parser-attr-parentid.md`、`outputs/042_evidence.txt` |
| 29 | **镜像与旋转的复合顺序是"先转后镜像"**（054 真机实测，八组采样）：CI 一处校准：`sch.place_component` 的 `(rotation, mirror)` 组合在画布上的效果是 `mirror_x ∘ CW(R)`——**镜子在旋转之后**、绕画布竖轴翻；而 `core.geometry.transform_point` 是**镜像再旋转**。两者在 0/180 一致、在 **90/270 不一致**：镜像姿态要**原角**交给 API，不取负（`mirror=False` 才取负）。错法后果 = 两脚对调（C1 首跑就被引脚回读抓住：`R1.1 reads back at (85, 710) but the plan expects (85, 750)`）。附带：`_editor_rotation` 的取负**只对 mirror=False 成立**，`draw.py` 的 006 回放把 mirror 与取负一起传（同款潜在偏差，未验，见遗留） | 落图/回放一律走 `engines/draw.py::_editor_pose(rotation, mirror)`，别自己拼角度；`engines/draw.py::_editor_rotation(rotation)` 仅在 mirror=False 时可用。出处 `outputs/054_c1/08_mirror_probe.json`、`tasks/054-draw-stage-c-editor.md` |
| 30 | **编辑器网表是工程级，不是页级**（054 C7 实测）：同名网跨页合并——第二页落了同名 `VIN` 的模块后，本页网表答 `R4.1 is on net 'VIN' with ['R1.1', 'R4.1']`，而 `R1.1` 在**另一页**。按"岛屿成员完全相等"判会拒掉一张完全按 plan 连好的图，且会拒掉**每一个**与先前模块同名的后续模块 | 判据收窄为：**plan 自己的引脚集合内**分区必须精确（模块内部短路/漏连仍然 exit 3），集合外的同网公司只作**证据**报告（`verification.sharedWithOutsidePins`）。跨页同名要不要合并是命名决策（052 labelPolicy，C2+）。出处 `outputs/054_c7/apply_C7_stdout.txt`、`outputs/054_c2/apply_report.json` |
| 31 | **`export.render` 的 `format` 词表是 `png|svg|pdf`**（054 首跑实测）：给 `image/png` 回 `[BAD_REQUEST] export.render needs params.format in png \| svg \| pdf`——图没出，但落图已经保存（那次 C1 的报告如实写了"没有图"） | 出图一律 `{"format":"png","scope":"page","pageUuid":<页>}`；报告里 `render.ok=False` 时按"缺证据"处理，别当成落图失败。出处 `outputs/054_c1/apply_report.json` |
| 32 | **相接的线会被宿主合并成一个 primitive、结点在点表里重复**（054 复核 035 的坑 24②）：054 画的分压抽头两条线（横支 + 竖干）落成一条 primitive，点表 `[(115,690),(85,690),(85,710),(85,690),(85,670),(85,690)]`——计划 4 条线上报 3 条 | 画布腿只判「计划里每条线的**两个端点**在不在该网的点集里 + 该网总长不短」，**不要**按 primitive 计数或按相邻对判几何（035 的附着判据同源）。出处 `outputs/054_c1/14_final_page_state.json`、`outputs/054_c1/apply_report.json` |
| 33 | **真机 AMS1117 符号是"单侧出脚"**（054 C3 实测三颗：C6186 / C351785 / C5205141 同一族）：引脚 1 GND、2 VOUT、3 VIN 全在**左侧**（y 各差 10），另有一颗**重复 VOUT**（4 号）在右侧；于是 `ldo` 文法默认的"in 左 core 中 out 右"**没有任何合法姿态**（`draw compile` 给 0 候选、`[presentation-poor]`，编译器自己的措辞是"right-of(C2,U1) is not honoured by this plan's own placement (a compiler bug — report it)"）。另：`role_pins` 按 id 排序取**第一个** VOUT（=左下的 2 号），而 `ldo._core_of` 用 `profile_pin_for` 只认**net 成员**——把 2 号写进 `nc[]`、只连 4 号，文法仍报"VOUT pin (number='2') … neither a net member nor an explicit nc" | **文法侧已由 055 G1 修好**：角色=**脚的集合**——任一同角色脚连网即算该角色已连、显式写进 `nc[]` 算"已处理"（`role_pins` 取 id 第一只脚、nc 不算数的说法作废；同角色两脚落两个网 = `circuit-invalid` 点名两网；失败文案不再自称 "compiler bug"，改报实测坐标与可执行动作）。**几何侧**仍只有两条出路，都在**输入**侧改：① `sidePreferences` 把 output 换成与符号几何相合的一侧（实测 `{"input":"left","output":"bottom"}` → 3 候选、evidence pass；文法本来就"跟着 sidePreferences 走"，053 sec.3 原文）——注意它是**说明哪一侧放输出支路**，不是"输出在下方"；② 换一颗 VIN/VOUT 反向的 LDO 符号。**不要**改编译器去迁就符号（053 sec.2 红线：不许为凑版式改脚号）。出处 `outputs/054_c3/{02_measured_parts.json,04_candidate_symbols.txt,05_side_default.txt,plan_C3b.json}`、`outputs/055_g1/{compile_outputs.txt,compile_B_sides_bottom.txt}` |
| 34 | **落图后的导出 `value` 字段是空的**（054 C3 实测）：`draw apply` 只写位号/坐标/镜像/旋转/LCSC，导出里 `value=''` 而 `mpn` 是库器件名（`CL05B104KO5NNNC`）——`decap-required-caps` 靠 MPN 的 EIA 码读值（104→100nF、226→22µF），所以**换成 MPN 解不出容值的料号，这条规则会判 unknown**。连带两条：① 本仓库 facts 要求 **AMS1117 输出 ≥22µF**，053 场景的 100n 输出电容 → 规则报 `decap-required-caps|WARN|U1\|2\|3V3`，`draw apply` 按 036 规矩（finding 只减不增）**拒绝保存**——图在页面上、两腿双证都过、就是没落盘（C3a 现场）；② findings 是**工程级**的，所以后续模块的 22µF 挂在同名 3V3 上会把这颗 U1 的 finding **消掉**（C3b 报告 `resolved: 1, new: 0`） | **055 起 `draw apply` 逐件写 `Value` 并回读**（plan 用 `valueKey` 声明，无 key/无值不写不报，`sch.set_component_attribute` 既有通道）；规则的取值顺序是**先读板值、读不出回落 MPN 的 EIA 码**——板值必须**是一个写得出容值的拼法**才读得出（裸数字一律不读；055 实测 `'22uF'`/`'22µF'` 读得出；**077 起中缀拼法也读**：`'22u'`、`'4u7'`、`'2n2'`——本条原先记的「`'22u'` 读不出仍走 MPN」自 077 起作废，见 `tasks/077-capacitance-infix.md`；CircuitSpec 里的值拼写照此写）。LDO 输出电容按 facts 用 ≥22µF（C45783 = 22µF 0805 实测可解）；053 场景值已同步改 22µF（055 G3），照抄场景去落图不会再被自己的规则挡。出处 `outputs/054_c3/{apply_report.json,apply_report_C3b.json,09_measured_22u.txt}`、`outputs/055_g2/{15_apply_ldo.txt,18_decap_channel.txt}` |
| 35 | **`tests/fixtures/drawapply/library.json` 是测试假库**（055 P9 实测）：里头的 R0402 是竖排 ±50，真机 0402（C25744）是横排 ±20——拿它跑真机 `draw apply`，库几何守卫（看的是文档）过得了，**引脚回读**过不去：拉线前 exit 3、件已放、未保存（055 P9 页就是这么来的，设计内拒绝不是事故） | 真机落图一律用**实测库**（§3.3 的探针量法；054 起存 `outputs/054_c1/measured_library.json`）；假库只服务离线测试。库几何守卫看不到编辑器侧几何，最后一道闸永远是放完后的引脚回读。出处 `outputs/055_g2/`（P9 申请记录与 exit 3 报告） |
| 36 | **`sch.modify_primitive` 是"位姿-only"，会把该件 `otherProperty` 整表清空**（057 真机 R12 实测：挪 100 单位后 Value `'10k'`→`''`，LCSC/封装/耐压全空串，且不复原），且**只接受 `ComponentType: part`**（对 netflag 报宿主"仅当器件类型为元件时允许使用该函数进行修改"）。**059 归因定案：宿主行为**——发给宿主的实参只有 `{x,y}`（connector 白名单过滤，decoy 九项哨兵一个没落），而清空后**键集逐键等于调用前的键集**（含只由我们写入、任何库器件都不声明的 `ZZZ-CUSTOM`）⇒ 那张空表出自宿主自己的器件视图；`otherProperty` 之外的字段（Designator/Manufacturer/SupplierId/UniqueId）不被清 | 任何"手改一件再复验"的流程（discard 身份、findings 只减不增、取值规则）都要预期值丢失；复原值走 `sch.set_component_attribute`（合并全表写，只给要改的键）；挪旗标/线一律 delete+重放。归因实验与结论见 `outputs/059_attr/VERDICT.md`（原始记录同目录 `01`–`30_*.json`）。出处 `outputs/057_live/e5/`、`outputs/059_attr/` |
| 37 | **位号池在 plan 与 apply 之间会变**（057 真机三次撞上，全 exit 4 `designator_taken` 零写入）：`draw plan`/`draw apply` 各自独立读工程导出，而宿主对**未保存的删除**、**手放件的自动编号**反映时序不同（实测 plan 池 23→apply 18、23→24、38→R12 被占） | 实作纪律：**plan 与 apply 背靠背跑**，中间不要手放件、不要 discard；撞了就重 plan 一次。出处 `outputs/057_live/`（e1b/e2/e7 的 exit 4 记录） |
| 38 | **手放件先落成 `R?`**（057 E2 实测）：`sch.place_component` 不给 designator → 画布未标注、census 按件计 0，但同一件**已进 keepouts**（`existing R? <id>`）；导出里稍后才编号，且编号取**活文档**已用号（会用未保存删除释放的号） | 手放件做现场后，等一次重读再 plan；别把 census 的 "0 part(s)" 当空页。出处 `outputs/057_live/e2/` |
| 39 | **findings 基线与 after 都读"活工程"（含未保存的落图）**（054 C3a→C3b、057 E4b→E4c 两次实证）：被拒绝保存的半成品页照样进下一次 run 的基线 | 半成品页会污染后续 run 的 findings 判据；清场用 `draw discard`，别指望"没保存就不算数"。出处 `outputs/057_live/e4/` |
| 40 | **INFO 级 report-only 规则也挡保存**（057 E1 实测）：`param-rc-cutoff` 命中 → `new_findings` exit 2 不保存（036 规矩按身份不看严重度）；该规则对**自带电压声明的轨名**（`5V0`/`+5V` 形态，011c whitelist）跳过，对 `VIN` 这类非声明名不跳过 | 电容与分压电阻共处的输入轨，轨名写成电压声明形态——这是命名约定，不是版式问题（与坑 34 同族）。出处 `outputs/057_live/e1/apply.txt`、`e1b/apply.json` |
| 41 | **模块级文法 finding 在 `draw plan` 命令行完全不可见**（057 E1 实测）：同一张图几何逐字节相同，轨名 `VIN`→`5V0` 后 `grammarFindings` 从 1 变 0，而 CLI 全文 0 处提及；离线 compile 只给计数不给文本 | 判据看 `verdict=pass` + `plan.evidence.grammarFindings`，别只看 CLI 文本。出处 `outputs/057_live/e1/plan2.txt` |
| 42 | （工具技巧，非坑）`bridge call --action export.render {"format":"svg"}` 的 SVG `<text>` 节点是**渲染内容的机器可读记录**（位号/值/网名逐个可 grep） | 模型看不到图时用它做"渲染里到底画了什么"的证据；人眼复核仍走 PNG。出处 `outputs/057_live/e1b/render_text_extract.txt` |
| 43 | **旗标自然姿态按符号分家**（库内 SYMBOL BBOX 实测 + 064 真机四姿态复测）：`Ground-*` 的 bars 挂在连接点**下方**（`Ground-GND BBOX (-10,0,10,-19)`），`Power-*` 的 bar 在连接点**上方**（`Power-VCC (-5,10,5,0)`、`Power-5V (-5,10,5,5)`）——同一个编辑器 rotation，两家字形朝向**相反**，所以罗盘（`drawcompiler._flag_rotation`）与字形盒（`symbolprofile.flag_glyph_box`）都必须**按符号分**，分类单点放 `symbolprofile.flag_glyph_kind`（按旗标名末段是不是地网名判）。**离线预览看不出来**：本仓库每颗旗标 profile 都写同一个约定盒 `(-6,0,6,18)`，预览画的是这个理想化盒、两家一模一样 | 060 的"全体 +180"只对 GND 成立（当时的 E1 页只有 GND 旗标），PWR-* 类全被翻反、3V3 那批场景哈希随之申报——**任何动旗标罗盘/字形盒的改动，前后都按坑 42 的手法解 `c_partid="netflag"` 组核"连接点→字形伸向"（四姿态逐颗，PWR-* 与 GND 对照）**；离线侧只用逐场景叶子级 diff 申报（`tools/064_flag_delta_audit.py`），digest 单独列、不作证据。出处 `outputs/064_railflag/`（真机 8/8 与罗盘逐数吻合）、`outputs/057_live/lib.json` |
| 44 | **`sch.geometry` 没有 `pageUuid` 参数，读的是焦点页**（065 真机实测）：`draw discard` 清完旧页后紧接着 `sch.geometry`，拿到的是**旧页**的图框读数（它恰成了"旧页已清"的证据），`doc.open` 切到目标页后再读才是新页 | 跨页作业的几何读取前先 `doc.open` 对焦到目标页（或先 `document.current` 确认焦点），别把焦点页读数当成指定页读数。出处 `outputs/065_capside/08_geometry_old_page_after_discard.json`、`07_geometry_p22.json` |
| 45 | **旗引线/stub 段穿越别网导体 = 缺陷（硬拒）**（074 真机 P23 实测）：069 的 pin2 3V3 旗引线「横 50 + 竖拐 25」的**竖拐**子线段与 5V0 横轨在 (60,740) 垂直交叉、**无 junction 圆点**——电气双岛正确（`C21.1/U10.2/U10.4` 同岛 3V3），但人眼第一读是「旗挂在 5V0 轨上」= 看着像短接；岳裁「必须改」。074 的尺子：候选引线**每个子线段**与别网导体（`router.edges` + 已落件引脚）做**严格内部**相交，共享端点/T 型衔接/共线重叠都不算；**只硬化旗引线/stub 段**，普通信号布线穿越维持 crossings 软指标 | 落图渲染里看到「旗引线跨在别的网上」先怀疑是 074 之前的图（074 起硬拒并报「哪段穿哪条导体 @ 交叉点」+ 动作）；改画法只动**引线形态**（距离档 → 逃逸方向 → 三折/两段 → 向无轨方向垂挂），**别用 junction 糊**（那是把两网真焊上）。代价：命中的形状可能少候选甚至 `layout-unsat`（那是契约内的合法答复）——E1 的 mirrored AMS1117 在默认间距梯（1x/1.5x/2.2x）上 0 候选，给到 3.5x 档就有零穿越图。出处 `tasks/074-flag-lead-foreign-crossing.md`、`evidence/074/`（真机 P23 v6：pin2 旗改「横 50 + 竖拐 25 **向下**」@(130,705) rot180，全旗 rot∈{0,180}，flag 网导线 Net 全空、TAP 带名，P22 归约串 sha256 未变） |
宿主版本：**3.2.149 是实测下限**（2026-09-23 在 3.2.149.88089769 上实测：打标/缩放等 8 个关键成员
typeof 全在位、activate 冷启动正常派发、render 实跑 308KB PNG——旧立论"3.2.183 以下这些接口不存在"
已被证伪，见 `tasks/027-editor-api-floor.md`）；**3.2.186 是唯一校准对象**。低于 149 没有证据，doctor 照卡。
宿主声明 ≠ 宿主实现（`sch_ManufactureData.getPngFile` 声明 v3.2.183 却回 `NOT_IMPLEMENTED`，两台实测机皆然）——
每一节的第一步都是真机 probe，probe 不通就如实降级，**不许照类型包硬写**。

## 7. 红线（开发/测试，改代码也照办）

- **不动 git**：不 `commit` / `add` / `checkout` / `restore`。任何 git 变更逐次经xianyuyijinban点头。
- **pytest 必带 `--basetemp=.tmp_pt_home`**：Windows 上否则汇总行被吞、假 exit 1。
  命令：`.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home`。
- **四线全绿才交卷**：pytest / `cd connector && npm test`（= build + `node --test`）/
  `npm run typecheck`（= `tsc --noEmit`；以 `connector/package.json` 实际脚本名为准）/
  `cd dsh-plugin && npm run typecheck && npm test && npm run build`（045 起；`npm run smoke`
  要真 daemon + 夹具，属真机验收不进默认线）。
- **新功能同步 dsh-plugin（045 §7，xianyuyijinban定的长期纪律）**：CLI 命令面变更时检查 dsh-plugin
  工具面要不要跟（跟=工具+bump+重 pack；不跟在交卷记录写明理由）；release 从 v0.4.26 起
  带第三附件 boardwise-dsh tgz；市场上架后 registry 版本同步 PR。漂移哨兵
  `tests/test_dsh_plugin_sync.py` 常跑。
- **变异验证 ≥2 个**：改一行源码 → 测试必须红 → 还原后 `sha256` 一致。
  **还原用 `cp` 备份做，禁用 `git checkout --`**（它会拉回 HEAD，把未提交的改动整个冲掉）。
- **派单纪律：串行小批，不派两小时黑箱**（xianyuyijinban 2026-09-28 定）：一个任务书只装
  一个缺口/一个文件域；多缺口的大批拆成串行小批（并行会同文件撞车），每批目标半小时内交卷。
  子代理上下文 500k 是 TaskStop 红线，但设计目标是**根本到不了**——上下文越重幻觉越多、
- **issue 不由我们关**（xianyuyijinban 2026-09-29 定，原话「问题还没确定解决就关掉」）：
  修复落地后只 comment「待验证」+ 验证步骤/commit hash，**由提出人实测确认后自己关**
  （或明说「关掉吧」）。代码完成 ≠ 问题解决。
  返工越多（060 三缺口合一批：41 万 tokens、跑满 2h timeout 被斩，实证）。
- **删除一律进回收站，禁 `rm` / `unlink` 直删**（xianyuyijinban 2026-09-28 定）——包括临时目录、
  变异备份、废弃产物，没有例外。Git Bash 里用 Windows 原生通道：

  ```bash
  # 文件（路径用绝对路径）：
  powershell -NoProfile -Command "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('D:\\path\\file', 'OnlyErrorDialogs', 'SendToRecycleBin')"
  # 目录（第三参同，方法换 DeleteDirectory）：
  powershell -NoProfile -Command "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('D:\\path\\dir', 'OnlyErrorDialogs', 'SendToRecycleBin')"
  ```
- **append 落盘后立刻 `grep -c` 独立计数**：出现 2 就是双执行，按偏移截断重写。
- 真机作业前先 `boardwise bridge status`（**daemon 会自行死亡**，死了先 `bridge start`）。
- 新增动作：`protocol.py` 目录 + connector handler + `docs/bridge.md` §4 三处必须同步
  （`tests/test_action_catalogue.py` 与 `connector/tests/contract-drift.test.mjs` 会拦）。
- 不碰历史证据：`outputs/011e*`、`014_*`、`015b_*`、`016_*`；不碰 `tests/fixtures/` 既有夹具。
- **connector 版本号每 bump 一次就发一个 GitHub Release**（xianyuyijinban 2026-09-25 定的规矩：版本史公开，
  更新节奏可视化）：`npm run package` 出 eext → `packaging/build_exe.py` 出 exe（内嵌 bundle 哈希
  进 notes）→ `gh release create v<版本> --prerelease` 双附件 → 验服务端 digest 与本机 sha256 一致。

## 8. 故障速查

| 症状 | 先看什么 |
|---|---|
| `daemon not reachable` | daemon 窗口还开着吗；`boardwise bridge status` |
| `UNKNOWN_ACTION` | daemon 是旧版本 → Ctrl-C 重启（动作表是加载期常量） |
| `NO_CONNECTOR` | 编辑器 `boardwise → About…` 看状态；扩展是否启用、是否重启过编辑器 |
| `PAGE_MISMATCH` | 焦点不在你以为的那页/那块板：先 `bridge call --action doc.list` 拿 uuid |
| 打标成功但看不到 | 标记画在最后聚焦的画布上；加 `--page <uuid>` 或先点一下目标页 |
| 命令答的是别的工程 | 多层焦点不一致（坑 1）：关掉多余编辑器窗口，`document.current` 双查 |
| 工程文件里多了东西 | `~/.boardwise/audit/` 当天日志逐动作可查 |
| `review` 退出 2 | `.epro2` 是加密导出 → 重新导出并取消加密；也见结构坏（072/073：明文一句话报位置，无 traceback） |
| `review`/`checkup` 退出 3 | **不是"板子干净"**：daemon/connector 不在，或 `completion.verdict` 是 `incomplete`（看 `completion.verdictWhy`）。空模型（0 器件 0 网络）多半是导出不全/被截断，或 `--view pcb` 看了一份只有原理图的导出。**`review --live` 也一样**（075）：在线拿到了模型、但模型是空的也退 3（与「根本没拿到模型」是两句不同的话，都不许读成通过） |

装环境与首次跑通，看 `docs/getting-started.md`（6 步，给非程序员写的）；
桥的协议与全部动作看 `docs/bridge.md`；画板流看 `docs/draw.md`。

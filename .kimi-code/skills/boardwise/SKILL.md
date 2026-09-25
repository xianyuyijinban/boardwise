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
boardwise doctor            # 7 项全绿 = 装好了；退出 0 = 全绿，1 = 有红项
```

- **只做审查（离线）**：不需要编辑器、不需要 daemon。给一个 `.epro2` 就能跑 `review`。
- **要读/写活着的编辑器**：需要 daemon（`boardwise bridge start`，前台窗口）+ 编辑器里的
  connector 扩展（`.eext`）。缺一不可，报错分别是 `daemon not reachable` / `NO_CONNECTOR`。
- 开发态用仓库解释器：`E:\boardwise\.venv\Scripts\python.exe -m boardwise.cli <命令>`。

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
`canvas-<页名>.png`（每张原理图页一张，PCB 页不出图）。

- **退出码**：`0` 无 ERROR / `1` 有 ERROR（主机 ERC fatalError/error、主机 PCB DRC 逐条、
  自有规则 ERROR 任一命中）/ `2` 输入不可用 / `3` 在线状态不可陈述（daemon 不通、没 connector、
  三级数据路全被拒）——`3` 绝不是"板子干净"。
- **报告自己说数据从哪来**（`source.tier`，缺一级就如实降级）：
  `project-file` 整工程归档（满血）→ `per-page` 逐页导出合并（跨页连通性按网名，
  不是追出来的连线）→ `netlist` 仅连通性（无值/无 MPN/无位姿）→ `file` 离线文件。
  `drc.*.checked=false` + `reason` 一律是"**没查**"，不是"零错误"。
- 只读：`doc.open` 只切焦点、`userInterface` 恒 false（不弹底部面板），每个阶段 `finally`
  把焦点复位。旧版 connector 缺某个动作时报告会记 `note` 并降级，不会瞎报。

**AI 要做的三件事（`report.json` 的 `ai_slots` 就是清单，逐条做完再答用户）**：

1. `unknown_parts[]` —— 每条 `{designator, name, mpn, reasons, question}`：
   去 WebSearch 规格书，核对**周边配置**是否符合典型应用（去耦/上下拉/限流/耐压），
   顺手确认可用型号。`reasons` 说明它为什么上榜（无 MPN / MPN 的值码解不出 / 无供应商），
   同一件事按同一个 `question` 回答即可。
2. `canvas_images[]` —— 每张图 `{page, file}`：**读图**看摆放、位号可读性、网络标识、
   模块区分度。图在 `--out` 里，路径是相对的：打开 `report.md` 点链接即可。
3. `summary_template` —— 按模板**原样留槽**填四段（结论先行 / 错误与归因 / 警告提醒 /
   建议动作），把上面的结论写进去，别重述 `report.json` 的全部内容。

**不要重算工具已经算过的东西**：DRC 计数与 PCB 逐条在 `drc` 段、模块划分在 `modules` 段、
规则 findings 在 `findings` 段（`summary` 里的 `ref` 指回它们）。模型只补三件事：
**查不熟的器件、看画布、写总结**。总结写完把 `report.md`（含图）交用户。

### 3.2 断连兜底与单点命令

没编辑器、只要一份规则体检，或要把发现画回画布/改一处值时，走下面这些单点命令。
**它们不替代 3.1**：3.1 能用就用 3.1。

- **手动导出 + 离线审查**（断连兜底）：编辑器 → 文件 → 导出 → **工程备份**，另存 `.epro2`
  （**导出时取消"加密"**，加密的读不了 → 退出码 2）。然后
  `boardwise review <导出.epro2> --view schematic --json report.json --md report.md`
  —— 看原理图**必须** `--view schematic`（011 家族规则对着 schematic 模型写；默认 `pcb` 视图在
  schematic-only 导出上是空的）。不知道文件在哪：`review --latest [<目录>]` 自动挑最新的 `.epro2`
  并先打印它选了哪个。退出码 `0`/`1` 同 3.1，`2` = 文件读不了。
- **eprj3 文件夹工程（V4，038 A 档只读）**：`boardwise review <工程目录> --view schematic --json ...`
  —— 目录内含 `<同名>.eprj3` 索引即识别（`sch/**/*.esch2` 逐页粘成一条记录流，原理图模型满血；
  必须显式 `--view schematic`）。`--view pcb` 对 eprj3 **诚实报错**"B 档未开"，不给空模型；
  `--latest` 认 eprj3 目录（按索引 mtime 参选）；工程 uuid 从索引 `owner_uuid` 取
  （补了"只有 .epro2 才带工程 uuid"的老缺口）。**一律只读**：写路径走 bridge API，不落盘。
- **器件事实库（039 parts 工具链，纯离线）**：`boardwise parts missing --file <工程>` 列出每颗
  IC 缺哪些事实（UNKNOWN 的来源清单，含 datasheetUrl）；`parts show <mpn>` 看库里已有什么
  （每条事实带出处页码）；`parts add <mpn> --lcsc <C码>` 追加候选条目。**`facts_verified: false`
  的候选事实不驱动任何规则**（规则视同无 facts 报 UNKNOWN）——核验的物理形态 = 岳审 git diff
  后翻 true。细则见 `docs/parts.md`。
- **把发现画回画布**（要 daemon + 焦点在那张原理图页）：
  `boardwise bridge call --action doc.list` 拿 `pageUuid` → `boardwise review-mark report.json --page <uuid>`。
  终端那张序号表就是图例（marker 只能画形状、不能写字，`marker#N` = 第 N 个红框）；
  `--focus 3` 跳最后一条、`--no-markers` 只看不画。清标记 `review-mark clear`
  **没有 page 守卫**（清的是最前面那块画布，2026-09-21 实测）。留证据图用 `export.render`，
  **不要**用 `bridge screenshot`（3.2.186 返回缓存空帧）。退出码 `0`/`1` 部分成功/`2` 输入坏。
- **从 finding 到局部修改**（可修范围很窄）：
  `boardwise edit plan --file <导出.epro2> --rule param-value-mpn-match --designator U3 -o plan.json`
  → `edit preview plan.json --file ...`（离线复查，永不写）→ `edit apply plan.json --file ... --json apply.json`。
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
- 破坏性/外向型操作（删除、推送、发布）先确认再动手；git 变更逐次经岳点头。

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
| 14 | **`review` 读 `.epro2` 缺省 view=board**：审原理图内容必须 `--view schematic`；缺省 view 对空 PCB 工程报 `0 components` 且无任何提示 | 审原理图永远带 `--view schematic`；拿到 "0 组件 0 网" 先想 view，再想导出。出处 `outputs/016_scene6_final.txt` 教训 B |
| 15 | `sch.geometry` 响应键是 `components/wires/pins/netlabels/bboxes/meta`——**没有 `parts`** | 写诊断脚本先打印 `list(d.keys())` 再取值；拿不存在的键 `.get()` 恒空，会编造出"空页"假象。出处 `outputs/016_scene6_final.txt` 教训 C |
| 16 | **热更/自更新后页面 reload，焦点抛到家页**（`type:home`，uuid 形似 `tab_page1`） | 热更后立刻读/写页面前先 `doc.open` 定点，否则动作落在家页报错。出处 025 批 1 |
| 17 | **主机 ERC 计数是 host-wide，不按页**：多页逐页调 `sch.drc_check` 各报同一读数（4 页都 `{warn:1}`），求和会编出 4 倍错误数；PCB DRC 树**没有 severity 字段**，叶子的 `parentId` 第二段才是编辑器自己的页签名 | ERC 计数全工程只报一次（标 `host-wide`）；PCB 叶子 severity 用 parentId 分流，读不出按 ERROR 并标 `assumed`。出处 `outputs/025c_checkup_live.txt`、025 批 3 |
| 18 | **3.2.149 开两个窗口时第二个编辑器窗口的 connector 不上线**（页面重载后第二个才上线）：窗口冻结/懒求值，与本机背景窗口冻结 7 小时同源，**不是** activate 派发问题（3.2.149.88089769 冷启动 activate 正常派发） | 多窗口作业先在 3.2.18x 上做；149 的多窗口等 Worker watchdog。出处 issue #4（2026-09-23）、`tasks/024-easyeda-3.2.149-bootstrap.md` §现场验证修订、`tasks/025-review-flow-v2.md:151` |
| 19 | **宿主 `sys_Timer` 也吃页面节流**：`eda.sys_Timer.setIntervalTimer` 的回调由宿主投到**页面任务队列**，后台窗口里与页面时钟吃同一张节流时刻表（三钟同段实测：宿主 150 s 只 18 次，48 s/60 s/35 s 三个大间隔与页面逐一重合；同段 Worker 158/158）。`...args` 透传是真的（`callbackArgs` 拿到 `['probe-arg', 42]`） | 想要"后台免疫"只能用 `blob:` Worker 自己的定时器（0.4.17 的 watchdog 就是它）；**别**把宿主定时器当后台闹钟。出处 `outputs/026_probe_p5_host_timer.txt`、`tasks/026-worker-watchdog.md` §三.5 |
| 20 | **让窗口真"后台"只能抢走前台**：`ShowWindow(SW_MINIMIZE)` / `WM_SYSCOMMAND:SC_MINIMIZE` / `SetWindowPos(HWND_BOTTOM)` 在本机**都不改变前台**（`IsIconic` 恒 false，只压 z 序）；窗口仍持前台时 Chromium **不节流**，后台读数全是废的。抢前台只有 `powershell -NoProfile -Command "…SetForegroundWindow…"` **内联**生效，同一段代码写成 `.ps1` 走 `-File` **不生效** | 用 `.tmp_026_fg.py`（`away`/`front`/枚举窗口）：抢完必须**复读** `GetForegroundWindow` 确认不是编辑器，后台成立的旁证是连接器心跳出现 **60 s 间隔**（audit 里 `ping role=connector` 的间距）。出处 026 P5、026b 批 2b |
| 21 | **诊断脚本自己会把现场搞死**（两个都实测踩过）：① `subprocess.run([... , "Start-Process", ...], capture_output=True)` 起后台进程**会一直等继承过去的管道 EOF** —— daemon 起来了，调用永不返回，脚本卡死而 `finally` 都跑不到；② 节流态下 `bridge status` 单次可以等 **~35 s**（它要 ping 到被节流的页面），拿它轮询会把脚本自己拖死 | ① 起后台进程一律 `Popen(..., creationflags=DETACHED_PROCESS\|CREATE_NEW_PROCESS_GROUP, stdout=DEVNULL)`，**不要** capture；② 量"重连时刻"这类事件**直接读 audit** 的 `{ts, action:"hello", role:"connector", projectName, instanceId}`，别问 CLI。出处 `outputs/026b_2b_throttled_recovery.txt` §五、026b 批 2b |
| 22 | **多窗口 update-connector 的三档行为与共享存储盲区**（030，岳 2026-09-24 实测四坑）：① 多窗又不寻址 → 旧版本直接把无 hint 的调用发出去，daemon 回 `WINDOW_UNSPECIFIED`（像"更新失败"）；现在 CLI **先读窗口表再拒绝**（exit 2）并列出窗口表 + 两种做法。② 一个编辑器里**多个窗口共用同一份扩展存储**（IndexedDB `User_<teamUuid>_v6`）：第二个窗口的 `sys.self_update` 报 `0.4.19 -> 0.4.19`（记录已被第一窗改过），不是出错也不是没写——**写就是 reload 的唯一触发器**（`location.reload()` 挂在同一个动作里），所以 `--all` 每窗都要写一次，去重只能体现在"同一存储记录只改动一次"的报告上。③ reload 后 **instance id 必变**（`newInstanceId()` 每次模块求值一次），旧 id 作废。④ reload 后有一段**匿名期**（岳见约 4 分钟；本机 2026-09-24 复测：10:55:09 重连 → 10:55:27 `--project test` 报 `PROJECT_NOT_CONNECTED` → 用 `--instance` 调一次 → 10:55:38 `--project` 就恢复了）：匿名期**用 `--instance <新 id>` 直达**，窗口一应答工程名就回来，不是等满 4 分钟，也不是显示 bug | 多窗更新用 `--all`（逐窗写、逐窗 reload、逐窗验收，每窗一行 verified/unknown）——**注意 `--all` 会 reload 每一个在线窗口，禁地窗（ROBOT、毕设FOC 等真实工程）在场时不许裸跑，先 `bridge status` 核窗口清单**；更新完 `bridge status` **逐窗核版本**；只更一窗用 `--instance <新读到的 id>`。verified 的判据是"**目标窗**旧身份从表里消失 + 写之后新出现的连接报出该版本"——别拿另一窗的应答当本窗的 verified（共享存储场景下那是假 yes）。出处 `outputs/030_*.txt`、`docs/bridge.md` §10.27 |

| 23 | **`export.render` 挂死 = 目标页自载入后从未被激活**（issue #5 正案，033）；**进度条 toast 漏是另一件事**（032）——两件事分开记，别混：3.2.149 + 0.4.21 上岳做了受控对照（同窗同页相隔 4 分钟，唯一变量是「导出前有没有 `doc.open` 过目标页」）：**没激活过 → png 与 svg 都挂死**（15:48:19 png 30s 超时；15:50:00 svg 同样超时）；`doc.open`（回 `activated: true`）之后 → **15:54:02 png ~2 秒成功**（662229B、magic 过）。**由此撤回两条旧结论**：①「PNG 卡死而 SVG 同刻可用」不成立——那是**单样本**（2026-09-23 18:05:53 那次成功是孤例，几分钟前 checkup 刚 `doc.open` 过那页，文档还「热」）；②「宿主不接受某个参数」与本症状无关（那是 2026-09-18 .d.ts 坑的真相，降为历史注脚）。一条机制解释全部历史观测：**checkup 从未失败**（它的画布阶段本就逐页 `doc.open` 再渲染——调用方碰巧做对了，所以 checkup **不改**），**每次裸调 `bridge call export.render` 都挂**（没先动焦点）。H1「必须是活动文档」/H2「载入后激活过一次即可」未分离，**修法相同**。**0.4.22 起 `export.render` 自己激活**：`scope=page` 时先解析目标 uuid（`params.pageUuid` ?? 当前活动文档）→ `dmt_EditorControl.openDocument(uuid)` → 成功才导出，结果带 `activatedPageUuid`；活动文档解析不到、或 `openDocument` 失败/不回 tab id → **诚实报错、不导出**（诊断沿用 `doc.open` 那套）；`scope=selection`/`project` 不动。031 的 **PNG→SVG 回退保留**（它是 checkup 超时不失败的保护），但它的旧前提已撤回：svg 在页面未激活时同样挂 | 裸调出图挂住时先查这条：**导出前目标页激活了吗**——传 `params.pageUuid`，或先 `doc.open`；checkup 对本病天然免疫（逐页 open + 渲染），**不用改**。**另一件事**：进度条 toast 漏（ManufactureData 管线开了不退，**成功也卡 99%**）——0.4.21 起 connector 在 `finally` 里 400ms 后 best-effort 拆（`destroyProgressBar`/`destroyLoading`，岳两样本验证通过）。心跳连续**仍不能**排除宿主故障（socket/心跳/路由计数只描述*通道*）。**149 上的根治验收归岳**：窗口刚载入、不 doc.open，裸调 `export.render` 应直接成功。出处 issue #5、`outputs/031_*.txt`、`outputs/032_*.txt`、`outputs/033_*.txt`、`docs/bridge.md` §10.28 `openDocument(uuid)` ≠ `activateDocument(tabId)`（**开标签页 vs 切前台激活，入参一个是 uuid、一个是 tab id**）——导出前必须**两者都做 + `getCurrentDocumentInfo()` 回读确认 `matchesRequest`** 才导出；0.4.22 只做了第一步，岳 149 验收当场未过（裸调仍 TIMEOUT ×2），0.4.23 补齐三步。H1/H2 **定案**：**每次导出前都要 activate**（不是"载入后激活过一次即可"）。 |
| 24 | **导出文件对删除永不重算**（035 四轮真机定论）：`save`、等 30 s、切页都不触发，四次导出逐字节一致仍报旧网表；create 会触发重算（029 实测）。⇒ 判据一句话：**导出新鲜当且仅当本 run 无删除**——含删除 run 的 pin 级新鲜读数只能走编辑器**活网表**（`sch.netlist` 的 `components[k].pinInfoMap[pin].net`，按名字给，未命名网一律空，单独证不了"两脚没共用未命名网"，**必须配画布双证**）。连带三条宿主习性：① 宿主给**悬空脚发单成员自动网**，导出名 `NET\d+`、活网表内部名 `$\S+`——**同一座岛两个名字，自动网名不是身份**（stale 检查对两个自动名视为同一岛；用户命名网仍逐名比）；② 相接的两段线被宿主**合并成一个 primitive**，接点在点表里重复上报（实测 `[345,300,345,290,255,300,345,300]`）——附着物判定必须读"脚在上报点表里"，按首尾点判会把 T 型误判成附着；③ `sch.doc.new` 的 name 参数被忽略 | pin 级验收 = 活网表 + 画布双证，缺一 exit 3，导出降级为事故报告附件；范围核对分家（含删除 → 画布身份级差异 `wiresVanished == [attachment.primitive_id]`；纯 create → 维持导出核对）。出处 `outputs/035c_live.txt`、`outputs/035d_live.txt`、`tasks/035-patch-pin.md` |
| 25 | **036 三条宿主习性（真机实证）**：① 宿主上报一条线的点会**重复结点**（实测 `[345,320,345,310,555,320,345,320]`），"最后一个点"可能只是拐角——**找线的远端要取离锚点最远的点**，单点线视为无远端、拒绝；② 宿主对撞上**工程全局**的位号会**静默改名**（要 R2、页面空、但 P4 已有 R2 → 落成 R3，改名发生在跑动中，plan 的 postcondition 随之不成立报 exit 3）⇒ 位号池必须取「**页面 ∪ 工程导出**」，只看页面必撞车；③ findings 签名别把"同一件事换措辞"和"自动网重编号"算新增（插入 100nF 后 decap 规则改措辞；悬空脚自动网 NET3→NET4）⇒ 签名 = `rule|severity|component|pins|命名网`（自动网名不计入） | 位号池、远端取点、findings 签名三处都已按此入码（036）；029 位号池同款盲点的修复见 036b。出处 `outputs/036_summary.txt`、`outputs/036_live.txt`、`tasks/036-insert-subcircuit.md` |
| 26 | **037 两条宿主习性（真机实证）**：① 宿主移动器件**不拖线**——`sch.modify_primitive` 把器件移走，线的上报端点留在原地（连接实际断开）⇒ 移动块必须删线 + 正交重画；② 宿主上报一条线是**点集不是路径**——`[445,320, 445,310, 655,320, 445,320]` 的相邻对里有从没画过的对角线 ⇒ 照抄点集"平移重画"会画出对角线挂死宿主（029-c 的课），按"相邻线段"判 T 会误报（5 单位外的脚落进幻影对角线容差，单器件移动曾被整片误拒）⇒ 附着/通脚判据只能说「**脚在不在上报点集里**」，漏判由网表恒等兜底（exit 2 按脚点名）。附带：`modify_primitive` 间歇抛宿主 `TypeError: Cannot destructure property 'cmdKey'…`（**改动前**抛，器件没动）⇒ 报错先回读位姿，证明没落地才许一次**举证重试**并写进报告 | 移动类流程一律 delete + `wire_route` 正交重画；T/附着判定禁用线段几何，用点集成员判定。出处 `outputs/037_probe.txt`、`outputs/037_live.txt`、`tasks/037-move-block.md` |
宿主版本：**3.2.149 是实测下限**（2026-09-23 在 3.2.149.88089769 上实测：打标/缩放等 8 个关键成员
typeof 全在位、activate 冷启动正常派发、render 实跑 308KB PNG——旧立论"3.2.183 以下这些接口不存在"
已被证伪，见 `tasks/027-editor-api-floor.md`）；**3.2.186 是唯一校准对象**。低于 149 没有证据，doctor 照卡。
宿主声明 ≠ 宿主实现（`sch_ManufactureData.getPngFile` 声明 v3.2.183 却回 `NOT_IMPLEMENTED`，两台实测机皆然）——
每一节的第一步都是真机 probe，probe 不通就如实降级，**不许照类型包硬写**。

## 7. 红线（开发/测试，改代码也照办）

- **不动 git**：不 `commit` / `add` / `checkout` / `restore`。任何 git 变更逐次经岳点头。
- **pytest 必带 `--basetemp=.tmp_pt_home`**：Windows 上否则汇总行被吞、假 exit 1。
  命令：`.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home`。
- **三线全绿才交卷**：pytest / `cd connector && npm test`（= build + `node --test`）/
  `npm run typecheck`（= `tsc --noEmit`；以 `connector/package.json` 实际脚本名为准）。
- **变异验证 ≥2 个**：改一行源码 → 测试必须红 → 还原后 `sha256` 一致。
  **还原用 `cp` 备份做，禁用 `git checkout --`**（它会拉回 HEAD，把未提交的改动整个冲掉）。
- **append 落盘后立刻 `grep -c` 独立计数**：出现 2 就是双执行，按偏移截断重写。
- 真机作业前先 `boardwise bridge status`（**daemon 会自行死亡**，死了先 `bridge start`）。
- 新增动作：`protocol.py` 目录 + connector handler + `docs/bridge.md` §4 三处必须同步
  （`tests/test_action_catalogue.py` 与 `connector/tests/contract-drift.test.mjs` 会拦）。
- 不碰历史证据：`outputs/011e*`、`014_*`、`015b_*`、`016_*`；不碰 `tests/fixtures/` 既有夹具。
- **connector 版本号每 bump 一次就发一个 GitHub Release**（岳 2026-09-25 定的规矩：版本史公开，
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
| `review` 退出 2 | `.epro2` 是加密导出 → 重新导出并取消加密 |

装环境与首次跑通，看 `docs/getting-started.md`（6 步，给非程序员写的）；
桥的协议与全部动作看 `docs/bridge.md`；画板流看 `docs/draw.md`。

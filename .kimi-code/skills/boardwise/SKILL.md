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
  可热更指定窗口，其回读等"任一窗口报到新版本"。

## 3. 审查闭环（朋友主用这条）

### 3.1 导出（人手，在编辑器里）
编辑器 → 文件 → 导出 → **工程备份**，另存 `.epro2`。
**导出时取消"加密"**——加密的 `.epro2` 读不了（`review` 退出码 2）。

### 3.2 离线审查
```bash
boardwise review <导出.epro2> --view schematic --json report.json --md report.md
```
- `.epro2` 看原理图**必须**加 `--view schematic`：011 家族规则是对着 schematic 模型写的，
  只有原理图的导出在默认 `pcb` 视图下是空的。
- 终端逐行打印发现；`report.json`/`report.md` 是同一份结果的两种格式。
- **不知道导出文件在哪**：`boardwise review --latest [<目录>]` 自动挑目录（含一层子目录）里最新修改的 `.epro2`，选中哪个先打印出来（含 mtime）；不给目录就扫 `~/Downloads`、`~/Desktop`、`E:\LC Project`（存在才扫）。与位置参数 `file` 互斥：同时给只打印一行错误、退出 2，不审任何东西。
- 退出码：`0` 无 ERROR / `1` 有 ERROR（这是**发现问题**，不是命令失败）/ `2` 文件读不了。

### 3.3 把发现画回画布（需要 daemon + 编辑器焦点在那张原理图页上）
```bash
boardwise bridge call --action doc.list        # 先拿 pageUuid，并确认焦点工程
boardwise review-mark report.json --page <pageUuid>
```
- 终端打一张序号表：`[序号] 级别 规则 位号 marker#N @ (x,y) 一句话`。
  **marker API 只能画形状、不能写字**，所以这张表就是图例：`marker#N` = 画布上第 N 个红框。
- 想跳到最后一条 / 只看不画：`--focus 3` / `--no-markers`。
- 清标记：`boardwise review-mark clear`。**注意 `clear` 没有 page 守卫**：它清的是最前面那块
  画布，可能不属于你以为的工程（2026-09-21 实测）。
- 退出码：`0` 全到位 / `1` 部分（哪个位号不在当前页会逐条写明）/ `2` 输入坏或 daemon 不可用。
- 要留证据图用 `--action export.render`；**不要**用 `boardwise bridge screenshot`
  （3.2.186 上返回缓存空帧，2026-09-21 实测）。

### 3.4 从 finding 到局部修改（M3 切片，可修范围很窄）
```bash
boardwise edit plan    --file <导出.epro2> --rule param-value-mpn-match --designator U3 -o plan.json
boardwise edit preview plan.json --file <导出.epro2>      # 离线复查，永不写
boardwise edit apply   plan.json --file <导出.epro2> --json apply.json
```
- **当前只有 `param-value-mpn-match`（单器件值）可修**；别的规则会被按名字拒绝。
- `apply` 走四道保护：写前重读页面 → 只写一个键 → 独立 geometry 回读 → save + 复查；
  重复执行会认 `already_applied` 且零写入。
- `apply` 退出码：`0` 已应用（或已应用过）/ `2` 承诺的效果不在板上（写被拒、回读不符、
  保存被拒、复查仍有该 finding）/ `3` 页状态不可陈述（超时或断连；**不重试**）/
  `4` plan 的前置条件不再成立或快照过期 / `5` plan 或输入不可用。
- 落盘诚实度：无"关闭重开"动作时只能报 `saved_unverified`；要 `saved_verified`
  必须走 关闭重开工程 → 回读/导出 #2 → 再 `review`（见 §6 坑 3、坑 4）。

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
见 §2 多窗口那条。

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

宿主版本：**3.2.183 是下限**（打标/缩放接口从这版才有），**3.2.186 是唯一校准对象**。
宿主声明 ≠ 宿主实现（`sch_ManufactureData.getPngFile` 声明 v3.2.183 却回 `NOT_IMPLEMENTED`）——
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

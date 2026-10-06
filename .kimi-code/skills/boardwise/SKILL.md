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
  `SKILL.md.bak-<年月日-时分秒>`，同一天装两次是两个备份文件、后者不覆盖前者）；别的 harness 跑
  `boardwise install-skill --agent` —— 它**打印一段
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

> **深水区外置（124 减重）**：审查 SOP 在 `docs/review-sop.md`（checkup 报告逐段读法、
> 架构走查、断连兜底与单点命令），画法 SOP 在 `docs/draw.md`（落图全流程）。
> 这一节只留路由图——判断「现在该上哪条链」；操作细节到对应文档读。
> **两种读法的家不一样**：在仓库里，引用文档就在 `docs/` 下原样读；用 install-skill 装的，
> 同目录 `references/` 下读同名文件（install-skill 会把引用的 references 全拷到 SKILL.md 旁边，
> 缺了重跑 `boardwise install-skill`，别手抄路径硬找）。

- **审板子**：`boardwise checkup` 一条出报告（ERC/DRC + 20 条自有规则 + 数据手册闸
  + 分诊/器件/总结槽位）。报告逐段读法、架构走查（044 起强制环节）、triage 分诊口径，
  全在 `docs/review-sop.md`。
- **断连兜底**：daemon 掉线重连、watchdog、匿名期、多窗口寻址的操作口径在
  `docs/review-sop.md` 的断连兜底段；机制全表在 `docs/bridge.md`。
- **画图（画法编译器落图）**：`boardwise draw compile`（离线出候选）→
  `boardwise draw plan`（候选 → ChangePlan）→ `boardwise draw apply`（守卫 → 落图
  → 回读 → 保存 → 出图）；画完一页先过 **`boardwise draw lint --page …`**（机器闸：
  压线/重叠/出界/同名导线段，P1 的 48E/20W/21I 基线就是它量的）再交付；
  **`boardwise draw propose`** 把意图合同提成 PresentationSpec 草稿（链的入口）。
  SOP（实测符号库工序、apply 执行序、支路顺序三来源、旗标画法）全在 `docs/draw.md`。
  **铁律**：`--profiles` 必须先在真机上量（编辑器不给库符号几何读口）；拿没量过的
  profile 去落图，引脚回读必然点名不符。
- **改图**：edit plan/apply（预览 → 授权 → 回读 → 复查），SOP 见 `docs/review-sop.md`。
- **PCB 审查**：DRC 闭环已出货（`drc.ruleset` 段 + 规则集元审查
  `blocklib/drc_ruleset_reference.json`）；按模块/器件的后续路线在
  `tasks/122-pcb-review-roadmap.md`。

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
设计泄漏，删文件没用，历史里还在。**派生副本同罪**（080/#41，推翻 047 的放行）：
`foo.epro2.bak/.orig/.backup/.old/.txt` 是同一容器换件马甲，守卫正则的
`(?:\.[^/]*)?` 后缀段一并拦，误报代价=同一提交里一行 ALLOWLIST。审查产物只进
`outputs/`、`.tmp_*`（均 gitignore）；不 harvest 公司板进 blocklib，不做成夹具。
机械防线：`tools/check_repo_hygiene.py`（pytest `tests/test_repo_hygiene.py` 常跑 +
本机 pre-commit 钩子已装）；新夹具要入库 = 在同一笔提交里**显式**加 `ALLOWLIST`
路径，那就是评审时刻。

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

> **124 减重**：全表外置到 `docs/pits.md`（45 条全文 + 用法 + 出处）；这里只留索引
> ——命中关键词就去 `docs/pits.md` 读全行。**加新坑两边一起加**（这里一行 + 全表一行）。
> 仓库里读 `docs/pits.md`；install-skill 装的读 SKILL.md 旁边的 `references/pits.md`。

| # | 一句话 |
|---|---|
| 1 | 两层焦点可以不一致 |
| 2 | 删除逐件 ~3.7 s |
| 3 | sch.readback` 没有 value / 没有 mpn 通道 |
| 4 | .eprj2` 只是工程目录册 |
| 5 | 保存是异步落盘 |
| 6 | 缓存空帧 |
| 7 | 没有 page 守卫 |
| 8 | 动作表是 daemon 加载期常量 |
| 9 | 根本不能用 |
| 10 | 超时但已经落件 |
| 11 | 坐标契约 |
| 12 | 实现偏差 |
| 13 | 编辑器整关重开后读数可能是同步滞后的陈旧视图 |
| 14 | review` 读 `.epro2` 的视图口径 |
| 15 | 没有 `parts |
| 16 | 热更/自更新后页面 reload |
| 17 | 主机 ERC 计数是 host-wide |
| 18 | 3.2.149 开两个窗口时第二个编辑器窗口的 connector 不上线 |
| 19 | 宿主 `sys_Timer` 也吃页面节流 |
| 20 | 让窗口真"后台"只能抢走前台 |
| 21 | 诊断脚本自己会把现场搞死 |
| 22 | 多窗口 update-connector 的三档行为与共享存储盲区 |
| 23 | export.render` 挂死 = 目标页自载入后从未被激活 |
| 24 | 导出文件对删除永不重算 |
| 25 | 036 三条宿主习性（真机实证） |
| 26 | 037 两条宿主习性（真机实证） |
| 27 | 主机 ERC 没有逐项条目 |
| 28 | 增量保存拆散 ATTR 邻接 |
| 29 | 镜像与旋转的复合顺序是"先转后镜像" |
| 30 | 编辑器网表是工程级 |
| 31 | export.render` 的 `format` 词表是 `png|svg|… |
| 32 | 相接的线会被宿主合并成一个 primitive、结点在点表里重复 |
| 33 | 真机 AMS1117 符号是"单侧出脚" |
| 34 | 落图后的导出 `value` 字段是空的 |
| 35 | tests/fixtures/drawapply/library.json` … |
| 36 | sch.modify_primitive` 是"位姿-only" |
| 37 | 位号池在 plan 与 apply 之间会变 |
| 38 | 手放件先落成 `R? |
| 39 | findings 基线与 after 都读"活工程"（含未保存的落图） |
| 40 | INFO 级 report-only 规则也会挡保存 |
| 41 | 模块级文法 finding 在 `draw plan` 命令行完全不可见 |
| 42 | 渲染内容的机器可读记录 |
| 43 | 旗标自然姿态按符号分家 |
| 44 | sch.geometry` 没有 `pageUuid` 参数 |
| 45 | 旗引线/stub 段穿越别网导体 = 缺陷（硬拒） |


宿主声明 ≠ 宿主实现（`sch_ManufactureData.getPngFile` 声明 v3.2.183 却回 `NOT_IMPLEMENTED`，两台实测互证）；
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
- **文档声明钉（doc-claims，xianyuyijinban 2026-10-03 定，issue #57 #7「病在文案」）**：
  README/docs 里的 load-bearing 声明**必须机器可验**（量化/对拍/grep 判真伪）并在
  `tests/test_doc_claims.py` 有钉；验不了的散文不许写成断言式口号（要么改写，要么补一个
  能验的机制）。规则常量凡引用板级证据必须在注释里声明 `evidence-boards:`（逗号分隔，
  评审集记录可唯一解析）。**声明失效=同批测试红——文案永远不许跑赢数据。**
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

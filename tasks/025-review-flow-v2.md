# 025 审查流程 v2：`boardwise checkup` 一键审查

> 2026-09-22 晚定稿。替代 SKILL.md §3 的四段式人工流程（§3.1 手动导出废除，降级为断连兜底）。
> 架构原则（岳拍板）：**工作流编译进工具，不写成 prompt 散文**。AI 只做三件它真正值钱的事——
> WebSearch 核查不熟器件、读画布图看美观、把槽位填成给用户的总结。

## 0. 事实基础（agent-42 查证，2026-09-22，宿主 3.2.186）

- `eda.sch_Drc.check(strict, userInterface, includeVerboseError)` 存在且为 function；静默可跑；
  但 `includeVerboseError:true` 也只回**聚合计数** `[{type:'fatalError'|'error'|'warn',count}]`，
  逐条错误只在底部面板，`SYS_PanelControl` 无读接口（宿主卡死）。
- `eda.pcb_Drc.check(strict, false, true)` 回**全量逐条结构化错误**（7 大组；叶子含
  ruleName/net/pos/explanation/obj1/obj2/layer）；不在 PCB 文档时返回 `undefined`。
  实时 DRC 三件套（`startRealTimeDrc` 等）宿主硬编码 `return false`——死桩，不碰。
- 零导出三条在线路（优先级序）：
  ① `sys_FileManager.getDocumentFile(uuid, 'epro2')` —— 宿主 function 在，但受
  「工程管理>下载工程 / 工程设计图>文件导出」权限门控，未真机验证；若可用，整条离线管线
  （`load_epru_text → build_schematic_model`）原样复用，规则零改动。
  ② `sys_FileManager.getDocumentSource()` —— 无权限注意项，宿主 function 在；返回
  文档源码字符串，**格式是否等价 .epru 记录流未证**。
  ③ `sch.netlist` + `sch.geometry` → `core/candidate.py`（`candidate_from_netlist:93` /
  `candidate_from_geometry:217`）—— 已跑通（`persistence` 在用，`cli.py:2260`），
  但只有连通性：无器件值/MPN/位姿，审查保真度受限。
- `run_review(model)`（`engines/review.py:62`）与模型来源完全解耦，不用动；
  断点只在 CLI 输入层（`_cmd_review:1265` / `_load_model:894` 只认磁盘路径）。
- 版本错位注意：宿主自带 pro-api **0.3.18**，编译依赖类型包 **0.4.25**——
  类型包声明 ≠ 宿主实现，一切以真机 probe 为准。

## 1. 目标命令

```bash
boardwise checkup [--project <名|uuid> | --instance <windowKey>] [--out DIR]
boardwise checkup --file <导出.epro2>          # 断连兜底：纯离线，跳过在线阶段
```

输出：`report.json`（结构化全量）+ `report.md`（人读）+ `ai_slots`（见 §5）+ 画布 PNG。
退出码沿用 review 语义：0 无 ERROR / 1 有 ERROR / 2 输入不可用 / 3 在线状态不可陈述。

## 2. 流程（编排全在 CLI 内，AI 不编排）

**阶段 A 数据获取（三级降级，报告里诚实标注用了哪级）**
A1 `getDocumentFile('epro2')` → base64 回传 → 临时文件 → 现有离线管线（满血）；
A2 `getDocumentSource()` → 格式等价性验证过才启用；
A3 netlist+geometry 候选模型（连通性级，报告头标注"降级模式：仅连通性审查"）。

**阶段 B DRC（在线，零用户操作）**
B1 原理图页：`sch_Drc.check(true,false,true)` 拿计数，进报告 `drc.schematic`；
   逐条细节由自有规则引擎（阶段 C）补足，报告注明来源。
B2 有 PCB 文档时：`pcb_Drc.check(true,false,true)` 逐条进报告 `drc.pcb`。
B3 分流：error/fatalError → 报告头部 + 归因段；warn → 末尾「提醒」段；全零 → pass 一行。

**阶段 C 分模块审查（现有规则引擎）**
C1 多页工程按页分模块；单页工程按连通性聚类（网表子图 + 启发式命名：
   电源/驱动/MCU/接口/其他——启发式宁可标「未命名模块 N」也不许瞎猜）。
C2 `run_review(model)` 全扫，findings 按模块分组。
C3 BOM/MPN 提取（现有 `bom`/`pintable` 积木）→ 生成 `unknown_parts` 候选清单
   （无 MPN、MPN 解码失败、或非常见封装/厂商的器件）。

**阶段 D 画布审查素材**
D1 每个原理图页 `export.render` 出 PNG 进 `canvas_images`（多页 zip 要拆）。
D2 不做几何规则化（对齐/碰撞）——本期画布判断全归 AI 读图。

**阶段 E 报告**
`report.json` = `{drc, modules[], findings[], ai_slots{unknown_parts, canvas_images, summary_template}, source:{tier, project, pageUuid, hostVersion, connectorVersion}}`；
`report.md` 渲染同一内容的人读版，summary 段留槽。

## 3. AI 槽位契约（skill 的唯一内容）

skill 缩为：「用户要审板子 → 跑 `boardwise checkup` → 按 `ai_slots` 逐一填：
unknown_parts 逐个 WebSearch 规格书核周边配置；canvas_images 逐张读图看摆放/区分度/
网络标识；填 summary → 交付用户」。SKILL.md §3 按此重写，§3.1 手动导出移到「断连兜底」。

## 4. 分批

**批 1 probe（真机验证，先于一切实现）**——需要先在 connector 注册最小动作
（或扩 `sys.probe` 支持"调用式探测"）：
  P1 `getDocumentFile('epro2')`：权限是否放行？返回 File 的 bytes 落盘后是否合法 zip、
     `load_epru_text` 能否解析、与同工程手动导出件**模型级 diff**（器件/网/值逐项）；
  P2 `getDocumentSource()`：返回格式采样（前 2KB + 结构特征），与 .epru 记录流对比判定等价性；
  P3 `sch_Drc.check(true,false,true)` 在 test 工程原理图页实测：计数、耗时、UI 副作用
     （底部面板是否呼出）；
  P4 `pcb_Drc.check(true,false,true)` 在含器件的 PCB 页实测（test/test2 都没有就在 test
     建一页放两器件一线）；记录逐条结构与「不在 PCB 页时返回 undefined」的边界。
  落盘 `outputs/025_probe_*.txt`；sys.probe 常备名单扩展三处同步
  （`tools/api_names.py` 命令行名单、`tests/test_api_names.py:30` NAMESPACES、
  可选 `NAMESPACE_NOTES`）；`DOCTOR_PROBE_CHECKS` **不加** DRC 项（5 项刻意克制）。

**批 2 数据路**：checkup 骨架 + 阶段 A 三级降级（A1 不过才落 A2，依此类推）+
  `review --live` 等价路径（`_load_model` 加在线分支，不动 `run_review`）。

**批 3 DRC 归一**：`sch_Drc`/`pcb_Drc` 结果 → Finding 映射层（pcb 逐条映射 ruleName/pos；
  sch 计数映射为摘要行，注明"逐条见规则引擎段"）。

**批 4 报告 + 槽位 + skill**：`report.json/md`、模块聚类、unknown_parts、export.render 打包、
  SKILL.md §3 重写、README/bridge.md 同步。

## 5. 验收

- 批 1：四项 probe 报告落盘，结论逐项回答「能用/不能用/有条件」；
- 批 2-4 完成后：本机 test 工程端到端 `checkup` 跑通（在线满血或诚实降级）；
  `--file` 兜底路径跑通；离线回归（黄金板 + 注入板 eval）逐字节不变；
- 三线全绿：pytest / connector / tsc；
- 变异验证 ≥2（降级逻辑与 DRC 映射各至少 1 靶）。

## 6. 守卫

- 真机只碰 `test`/`test2`；R1–R3 照旧；写动作带 pageUuid。
- `pcb_Drc.check` / `sch_Drc.check` 是**只读检查**，但有 UI 副作用（可能呼出底部面板）——
  probe 时记录，checkup 默认 `userInterface:false`。
- 禁地照旧（毕设FOC驱动板、CH340G、ROBOT ctrl FOC、反激辅助电源等一切真实工程）。

## 7. 交卷记录

（每批完成后 append，含测试计数、probe 结论、变异结果、还原 sha256。）

### 批 1（probe）· 2026-09-23 凌晨 · agent-43 执行

- 四动作注册（connector **0.4.14**）：`sys.get_document_file` / `sys.get_document_source` /
  `sch.drc_check` / `pcb.drc_check`；`sys.probe` 加 `call` 白名单通道（仅这四个只读动作，
  绕过 daemon 加载期目录——坑 8，probe 专用；批 2 第一件事：重启 daemon 后走真实路由复验）。
  `protocol.py` / `docs/bridge.md` §4 / `api-names.ts`（重生成 11 命名空间）三处同步，
  `DOCTOR_PROBE_CHECKS` 未动。
- 结论：**P1 能用**（权限放行、29672B 合法 zip、离线管线零改动跑通、位号集合与在线一致；
  注意是**文档级**导出，整工程须逐页导出或注册 `getProjectFile`，二选一留给批 2）；
  **P2 不能用**作 A2（丢 footprint 与全部连通性，P4 实测 0603/2 网 → ''/0 网）；
  **P3 能用**（计数/耗时/幂等/静默全测到，非原理图页 throw 已如实报）；
  **P4 能用有条件**（只在 PCB 页；真机是 throw 而非类型包写的 undefined；空 PCB1 仍答
  1 条 Netlist Error；器件/坐标类叶子未造出，待有器件 PCB 补测）。
- 三线：pytest 1321 不变 / connector **340→359** / tsc 干净；变异 3/3 CAUGHT
  （cp 备份 sha256 还原一致）。
- 证据：`outputs/025_probe_p{1,2,3,4}_*.txt` + `025_probe_api_names.txt`（未入库）；
  test 工程零残留（geometry/doc.list 前后逐字段一致）。
- 新坑入 SKILL 坑 16：热更后页面 reload 焦点抛家页，读页面前先 `doc.open` 定点。

### 批 2（数据路）· 2026-09-23 上午 · agent-43 执行

- daemon 重启 ×2（第二次因为 getProjectFile 的目录条目后写——**改目录 → 重启 daemon →
  热更 connector**，顺序反了新动作卡在目录里查不到）+ `bridge call --action` 真实路由复验
  四个批 1 动作全通（`outputs/025b_routed.txt`；pcb.drc_check 在原理图页 exit 1 是预期边界）。
- 新动作 `sys.get_project_file`（connector **0.4.15**，与 get_document_file 共用 readArchive；
  拒绝时给出**这次调用**的门）：真机**权限放行**，1,765,386 B 整工程归档 → **A1 满血路成立**；
  A1'（逐页导出合并）亦实测，位号集合与整工程模型逐项一致（`outputs/025b_project_file.txt`）。
- `boardwise checkup`（骨架 + 三级降级 A1→A1'→A3，A2 依批 1 P2 结论不启用）+ `review --live`；
  report.json 的 source/model 真实、drc/modules/findings/ai_slots 空且标 pending；
  exit 0/2/3 语义见 docstring（1 待批 3 填 findings 后可达）。
- test 工程端到端实录 `outputs/025b_checkup_skeleton.txt`（含两份 report.json），零残留。
- 三线：pytest **1336**（+15）/ connector **365**（+6）/ tsc 干净；离线 eval dev+holdout 与
  `d6dca3b` 基线**逐字节相同**（dev `bcaf42a8…`、holdout `33c4118a…`）。
- 变异 3/3 CAUGHT（关 A1' 分支 / tier 撒谎 / 删注册表项）；还原 sha256
  `cli.py 2cb149d703890b8f…`、`actions.ts 1805ec1344fbdeaf…`。
- 坑：daemon 重启后 connector 可能**长时间不回来**（后台冻结，本次 7 小时，前台化才自愈）——
  别只等 90 s，看 audit；`doc.open` 后焦点会变，批处理在 finally 里复位。
- 发现待办：`update-connector` 在 reload 未完成时误报 FAILED（回读应等预算耗尽再判 mismatch）——
  独立小修，未做。

### 批 3（DRC 归一）· 2026-09-23 上午 · agent-43 执行

- 新模块 `engines/drc.py`（713 行）：sch 计数原样进 `drc.schematic`（**不编造逐条**）；
  pcb 组树逐条映射进 `drc.pcb`（渲染三态 template/verbatim/fallback 标证据量）；
  **「没查」（throw/checked:false/离线）与「干净板」严格分开**。
- **实测修正任务书假设**：主机 ERC 计数**不按页**（4 页同值）——顶栏不累加，标
  `countsBasis:'host-wide'`；PCB 树无 severity 字段，叶子按 `parentId` 第二段
  （编辑器自己的 Errors 页签）分流，读不出按 ERROR 并标 `assumed`。
- checkup 填 `drc`/`findings`/`summary` 三段：findings 与 `review --json` 逐字段相同
  （有等式测试钉住）；**exit 1 首次可达**；控制台头部 ERROR 区 + 末尾 WARN 提醒段；
  离线路径不调 DRC（标 `offline-not-available`）。schema `boardwise.checkup/1` → `/2`。
- 真机：test 工程全链 exit 1（`outputs/025c_checkup_live.txt`）；**PCB 逐条补测未完成**——
  毕设FOC驱动板未在编辑器打开，桥无 project.open，R3 停下待岳（`outputs/025c_pcb_drc_bishe.txt`）。
- 三线：pytest **1363**（+27）/ connector 365 回归 / tsc 干净；离线 eval 与 dbd4570 逐字节相同；
  变异 4/4 CAUGHT（含一个「新字段没人读所以没人钉住」的发现，补断言后才中）。
- 坑：ERC 计数 host-wide（入 SKILL 坑 17）；bash heredoc 写 CRLF 混行——长文本追加走 Edit 工具。

### 批 4（报告 + 槽位 + skill）· 2026-09-23 中午 · agent-43 执行，Kimi 复验

- 新模块 `engines/checkup.py`（806 行）：**模块聚类**（≥2 页带器件 → 按页，工程师自己的切分；
  否则按**非地网**连通性聚类——GND 连一切，含它永远只有一块；同名页 uuid 前 8 位消歧；
  命名要 ≥1/3 功能器件命中家族特征，否则保守留白 `未命名模块 N`）+ **页归属浅扫**
  （整工程合并模型没有页切分，按 SCH_PAGE 文档重扫一遍；**必须按位置 join**——实测
  Designator 属性的 `parentId` 是实例 container id 而不是 COMPONENT 的 partId，
  按 id join 静默 0 页，比红更危险）+ **AI 槽位**（unknown_parts 逐条带 reasons/question、
  canvas_images 逐原理图页 PNG、summary_template 中文四段模板）+ `report.md` 渲染
  （与 report.json 同源同序）。`cli.py` +239（阶段 D 渲染、markdown 写出、控制台模块/槽位行、
  `pending` 清空但保留键——消费者靠它区分"没欠账"与"键丢了"）。
- 文档：README 英/中 checkup 段 + `/2` 各段含义表、getting-started 第 5 步插 5.0「一条命令」、
  **SKILL.md §3 重写**为「checkup 优先 + AI 填槽」一页 SOP（§4–§8 未动）、bridge.md §8
  命令表补 checkup 行（Kimi 收尾同步，"two commands" 标题随之改）。
- 三线：pytest **1384**（1363+21：test_025d 16 例 + checkup_cli 5 例）/ connector **365** 回归 /
  tsc 干净——Kimi 复验一致。离线 eval dev/holdout 与 `7ccf0a2` **逐字节相同**（sha256
  `bcaf42a8…`/`33c4118a…`，Kimi 亲手 diff=IDENTICAL）；`engines/review.py`、`rules/` 零 diff。
- 真机实录 `outputs/025d_checkup_full.txt`（437 行）：在线 `checkup` exit **1**（主机 PCB DRC
  `Import Changes` 1 条——test 工程 PCB 与原理图网表不一致，真实命中）、tier=project-file 满血、
  4 张 2362×1672 PNG 落 `--out`、三处 doc.open 焦点全复位、geometry/doc.list 逐字段零残留；
  `--file` 兜底 exit 0，drc 两段 `offline-not-available`（没查≠零错误）、canvas 空 + note。
  **PNG 经 Kimi 亲眼验证**：P1 空页边框、P4 页 R2 10K 在位（与模型 1 器件一致），真渲染非空帧。
- 变异 **3/3 CAUGHT**（`_dominant()` 恒真→无依据也命名 / unknown_parts 去掉「MPN 值码解不出」理由 /
  在线路径不出图且槽位不报原因），cp 备份 + sha256 还原逐字一致（`checkup.py 688ce48f…`、
  `cli.py 9c80cf50…`，备份 `.tmp_mut025d/`，Kimi 复验还原一致）。
- 坑：① 两个启发式假阳性被测试逮到——LCSC 码 `C57895` 的 `7895` 被无锚点 `78\d{2}` 当成
  7800 系稳压器（修法：匹配文本剔除供应商码 + 全模式加锚点）；`LM358` 运放命中 `LM\d{2,4}`
  被命名电源（修法：false-friends 黑名单）。② 单页板按连通性基本分不出模块——报告明说
  "划分信息量有限"而不是硬造结构。③ 一次在线 checkup ~15 s（4 张 render 占大头，单张 2–3 s），
  提速留给后续批次（并发出图）。④ `ai_slots` 多一个规格外键 `canvas_images_note`：
  列表为空时区分"没图"与"图丢了"。
- 待岳裁：`outputs/025d_*`（含 4 张 PNG ~630 KB）是否 `git add -f` 入库（outputs/ 默认 gitignore）。

### 批 2 待办关闭 · 2026-09-23 下午 · agent-43 执行，Kimi 复验（假 FAILED）

- **缺陷**：`_reloaded_window_version()`（修前 cli.py:4345-4389）第二分支把"写入目标窗口仍在线
  报别的版本"当 mismatch → 首次回读（reloadInMs 500ms + margin 0.5s 后）即判 FAILED/exit 1；
  真机实测 reload 要 **5 s**（08:39:36 写入 → 08:39:41 新 connector 报到），热更成功却报失败，
  与 020 WI-2 的"没回来 = UNKNOWN ≠ failed"冲突。
- **修复**：判据改为"**身份 + 版本**"——只有写入前不在线的连接（新 instance id）报出非存储版本
  才算 mismatch；旧 socket 仍在线 = "还没回来"，继续等，预算耗尽 exit 3；某窗口报存储版本 exit 0。
  写前取一次窗口表快照（`_snapshot_identities`），快照缺失时不许判 mismatch；两条路径统一读
  daemon 窗口表；删除 `_running_connector_version()`（sys.probe 读法多窗口下会被任意窗口作答、
  且无窗口身份）。三态语义与退出码一字未改。
- **测试**：`tests/test_bridge_cli.py` 39 例；新增 5 例，含回归靶
  `test_a_reload_still_in_flight_is_unknown_never_failed`（修前 **assert 1 == 3** 红，修复后绿）
  与"无 `--instance` 路径"同形态用例（原 `...instance_reports_a_window_still_on_the_old_build` 改写）。
- **变异 3/3 CAUGHT**：忽略快照 → 2 红；verified 不可达 → 4 红；快照缺失按"全新建"处理 → 1 红
  （第三次先没红，补 `ping_fails_before` 假件 + 用例后才红）。还原 sha256
  `cli.py 492b97c0c3107c7a…`（交付态 `d90fa3d8c671bf27…`，差两处注释；Kimi 复验交付态一致）。
- **三线**：pytest **1388**（+4）/ connector **365** 回归 / tsc 干净（均 Kimi 亲手复跑）；
  `docs/bridge.md` §8 与命令表行同步。
- **未做**：真机热更演练（并入 026 批任务 0）；证据 `outputs/025e_update_connector_false_failed.txt`。

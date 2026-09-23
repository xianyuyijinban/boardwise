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

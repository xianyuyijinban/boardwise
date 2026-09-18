# 任务 006：垂直切片——AI 从空白重画 CH340 USB-UART 板（原理图阶段）

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> **依赖：任务 005（golden-compare 裁判，含 SCH 侧模型构建器 `build_schematic_model`）+ 桥 0.2.5（任务 004d，零点击自连）验收后开工。**
> 前置阅读：`docs/architecture.md`、`docs/bridge.md`（004 产出）、`docs/format-epro2.md`（005 已补 SCH 侧章节）、`src/boardwise/bridge/`、`src/boardwise/parsers/`、`src/boardwise/core/compare.py`。

## 目标

以黄金板（岳翔宇现有的 CH340 小板，导出的不加密 `.epro2`，届时在 `tests/fixtures/ch340_golden.epro2`）解析出的连通性为**唯一设计输入**，让 AI 通过 boardwise 在 EasyEDA 中**从空白原理图重画这块板**，回读网表与黄金板逐 pin 比对——**零差异**才算画好。

本任务只到**原理图**，不碰 PCB 布局布线（那是任务 007）。

## 工作项

1. **桥写动作扩展**（在 004 协议上加，不动既有信封）：
   - `sch.doc.new`（在当前工程新建空白原理图页）
   - `sch.place_component`：按 LCSC 料号 / 库 uuid 放真实器件（经 `lib_Device` 搜索 → 放置符号），支持 x/y/旋转
   - `sch.place_wire`、`sch.place_netlabel`、`sch.place_power`（电源/地符号）
   - 每个写动作返回创建结果的 uuid 列表；失败要结构化报错
2. **生成器 v0**（`src/boardwise/engines/generate.py`）：
   - 输入：`DesignModel`（黄金板解析）→ 输出**有序动作计划**（放件网格布局 + 连线队列）
   - 布局美学本任务只做最朴素版：按连通性分簇、网格摆开、朝向统一、去耦电容靠近宿主芯片——审美规则后续任务再系统做
   - 纯函数可单测：计划生成不依赖桥
3. **候选模型构建（验证路径，架构决策，2026-09-13 Kimi 补）**：`boardwise draw` 的"回读比对"按优先级两条路，**先试首选再退退路，结论写进汇报**：
   - **首选：编辑器网表导出**。官方 API `sch_ManufactureData.getNetlistFile()`（参考实现的 debug exec 示例里出现过）是编辑器自己算的连通性，地面真值。先用 `easyeda debug exec` 探该 API 的输出格式与可达性；可用则新增第三个 DesignModel 构建器（netlist 文件 → DesignModel），**不要**在桥数据上重新推导连通性。
   - **退路：桥 readback + 005 的连通性推导**（并查集）。仅当网表导出 API 不存在/不可用时；readback 的 primitives 与文件侧同构，005 的逻辑可复用，但 wire 几何字段名要先侦察。
   - 无论走哪条，比对器不变；候选来源（netlist / readback）打印在 diff 报告头里。
4. **门禁流程**：执行前打印计划摘要（器件数/网络数/动作数）等待人工确认（CLI `--yes` 可跳过）；执行后自动回读，输出逐 pin 网表 diff 报告 + 画布截图
5. **CLI**：`boardwise draw --from tests/fixtures/ch340_golden.epro2 [--yes]`

## 测试

- fake connector 协议测试：新写动作的请求/响应契约
- 计划生成单测：输入黄金板 model → 计划覆盖全部器件与网络、无悬空引脚遗漏（NC 除外且需显式列出）
- 网表 diff 单测：合成两模型，验证逐 pin 比对能抓到错连/漏连/多连

## 约束

- Python 侧标准库（websockets 已在册）；connector 侧 TS + 官方类型包；英文代码；不碰 git
- 不实现自动布线、不实现 PCB 任何动作
- 网表 diff 必须**逐 pin**（器件位号 + 物理引脚号 → 网络名），不接受"网络数对得上"这种粗粒度

## 验收

- 自动测试全绿
- **真机手动验证（岳翔宇执行，步骤写进 docs/bridge.md 或 docs/draw.md）**：打开 EasyEDA 空白工程 → `boardwise draw --from ch340_golden.epro2` → 画布上出现 CH340 原理图 → diff 报告 0 差异 → 截图确认可读的布局
- 报告里如实列出：哪些动作失败重试过、哪些器件因库问题替换过

---

## 实现记录（2026-09-13 18:35，执行者：WorkBuddy/Claude）— 代码全部就绪，真机探针与验收待执行

### 侦察结论（任务书修订版第 3 项要求的第一步，结论如下）

- **首选路径（编辑器网表导出）API 确认可用**：`eda.sch_ManufactureData.getNetlistFile(fileName?, netlistType?): Promise<File|undefined>`，`ESYS_NetlistType` 枚举官方类型包实测值 `'EasyEDA' | 'JLCEDA' | 'Protel2' | 'PADS' | 'Allegro' | 'DISA' | 'DSNET'`。
- **两条实测宿主陷阱（来自参考实现 easyeda-agent 的 skill 文档，同一宿主 3.2.186）**：
  1. `sch_Netlist.getNetlist()` 已废弃**且可能挂起** ⇒ connector 的 `sch.netlist` **故意不做这个 fallback**（挂起会吊死动作槽），失败即结构化报错，退路放在 draw 流程层；
  2. `createNetLabel(x, y, net)` 在 3.2.186 **实测挂起**（参考 issue #191）⇒ draw 流程不使用 netlabel，命名改走 `createNetFlag`（电源网，每 pin 一面旗）+ `createNetPort('BI')`（信号网）；`sch.place_netlabel` 保留为动作但文档标注陷阱。
- 写动作 API 全部确认：`sch_PrimitiveComponent.create(item, x, y, subPart?, rotation, mirror, intoBom, intoPcb)`（`ILIB_DeviceSearchItem` 可直接传）、`createNetFlag`、`createNetPort`、`sch_PrimitiveWire.create(points, net?)`、`dmt_Schematic.getCurrentSchematicInfo()` → `createSchematicPage(uuid)`、建件返回 `getState_PrimitiveId()`。
- **网表文本格式无样例**（参考 connector 不在编辑器里，离线索引只有签名）⇒ `candidate_from_netlist` 按"拒绝瞎猜"实现（抛 `NetlistFormatError`），格式校准是真机探针（docs/draw.md §Machine probe）的第一产出；当前 draw 的候选来源实际走**退路（sch.geometry 回读 + 005 连通性推导）**，且退路完整实现并测试。

### 交付物

| 工作项 | 结果 |
|---|---|
| 桥写动作扩展 | ✅ 8 个新动作进 ACTIONS 闭集：`sch.netlist` / `sch.geometry` / `sch.doc.new` / `sch.place_component`（lcsc→keyword→uuid 三级解析，解析方式如实上报）/ `sch.place_wire` / `sch.place_netlabel` / `sch.place_power` / `sch.place_netport`；connector 0.3.0（105 测试全绿，.eext 14857 B 双验） |
| 生成器 v0 | ✅ `engines/generate.py`：`generate_plan`（host 芯片锚定 + 去耦电容同排 + 连通性 BFS 簇序，纯函数）+ `plan_nets`（回读坐标 → 电源网旗标 / 信号网曼哈顿线 + 端口，缺 pin 显式返回） |
| 候选模型构建 | ✅ 退路 `core/candidate.py::candidate_from_geometry`（容错字段匹配、逐节点记名防 union root 失效、孤立引脚不命名防 NC 误报）；首选 `candidate_from_netlist` 挂钩待校准；draw 流程按"先首选后退路"实现并打印来源 |
| 门禁流程 | ✅ `print_gate` 计划摘要 + 人工确认（`--yes` 跳过）；执行后自动回读 diff + 截图；报告如实列失败动作/缺失引脚/候选来源 |
| CLI | ✅ `boardwise draw --from … [--yes] [--pitch] [--per-row] [--screenshot]`；另加 `boardwise bridge call --action X [--params JSON]` 通用探针命令 |
| 测试 | ✅ Python **184**（+20：生成器 11 + 候选/draw 9，黄金板全覆盖断言）+ connector **105**（+10：新动作 wire 契约）+ tsc 干净 |
| 文档 | ✅ 新增 `docs/draw.md`（流程图、探针步骤、真机验收步骤、已知限度）；bridge.md §1 风险声明更新 + §5 动作表加 8 行 + 两条陷阱注记；README 中英双节加 `draw` 一节 |

### 真机待办（下一步，按 docs/draw.md）

1. 重启 daemon（61190 上现跑的进程还是旧 ACTIONS）；侧载 connector 0.3.0 并重启编辑器。
2. **探针**：`bridge call sch.netlist`（抓网表样例 → 校准 parser）+ `sch.geometry`（核对字段名假设：线几何字段名、pin 的 designator 归属、画布单位）——探针结论补进本文件与本汇报。
3. **验收**：`boardwise draw --from tests/fixtures/ch340_golden.epro2 --screenshot out.png` → 0 差异 + 截图可读。

---

## 修订二（2026-09-13 22:30，Kimi）：验证路径翻转——geometry 重建升首选

实测证据：网表导出 `getNetlistFile` 全天 1/7 可用（仅 golden P1 成功；test 各页 6+ 次全部静默返回 undefined，`save()` 返回 true 后重试 3/3 仍败）；而 `sch.geometry` 图元回读全天 7/7 可靠。验收路径必须确定性，故：

1. **首选 = geometry 重建**（`sch.geometry` + 005 并查集，`core/candidate.py` 已实现）；**网表导出降级**为"可用时的交叉验证"，候选来源如实写入报告头。
2. **定标实验先于验收**（零 UI 成本，用既有动作）：在 **golden P1 页**（人工已核对的地面真值）跑 `geometry → candidate → compare vs ch340_golden.epro2`，**0 差异才算仪器校准通过**，然后才准测 test P4。NC 约定、自动网名等系统性偏差在校准阶段暴露并修掉。
3. **禁止在 golden P1 页上做 API 放置实验**（曾提议在黄金页放 API 电阻试 H-A——污染基准，否决）。H-A/H-B 的判决改用 golden 工程遗留的 API 废页（`openDocument` 切页后导出）或由岳翔宇在 P4 手动点一次"导出网表"（UI 路径）顺带完成——**结果入知识库，不阻塞收官**。
4. H-A 细分注意：现有证据里"API 创建的图元"与"API 创建的图页"两个变量混淆（golden 废页恰好落在二者之间，是天然的分离样本）。

---

## 修订三（2026-09-13 23:20，Kimi）：生成器硬约束——岳翔宇亲验 P4 判"不可用/错误"

实测读图（test 工程 P4 编辑器截图）：器件放置与位号写入**已生效**（桥的写路径无罪）；判死刑的是生成器的布局布线：X1 压标题栏、U1 半身出页框、**C7 被一根竖线贯穿两极板（电气短路级错误）**、满页悬浮未贴线的网络端口、标签与导线互叠。

生成器必须新增**硬约束**（全部是离线纯函数、可单测，违例即计划作废，不许带伤进编辑器）：

1. **放置边界**：器件包围盒全部在图框内且避开标题栏区域（页框/标题栏几何从 readback 或图框模板取得）；器件两两包围盒不重叠。
2. **导线规则**：端点只能是引脚尖坐标或同网交汇点；曼哈顿走线（水平/垂直段）；**任何导线段不得穿过任何器件包围盒**（贯穿电容两极板这种直接判死）。
3. **端口/旗标附着**：每个 netport/netflag 必须精确落在本网导线的端点或引脚尖上，dangling = 违例。
4. **标注重叠**：网络标签文本框与导线段、器件标号之间留最小净距。
5. draw 流程在执行前打印**自检报告**（违例列表），有违例直接拒绝执行——把"画得对不对"的举证责任从用户眼睛转移到生成器自己头上。

校准→diff 的顺序不变（修订二）：golden P1 定标通过后才准动生成器，P4 diff 报告是 bug 清单的量化依据。

---

## 修订四（2026-09-13 23:50，Kimi）：从参考实现 1.4 架构抄两条（源码/文档证据见调查记录）

1. **视口截图一律不作证据**。参考实现实测 `getCurrentRenderedAreaImage` 会返回与板面状态无关的缓存旧帧（两次不同板面截图逐字节相同）；我们自己也观测过 highlight 前后截图逐字节相同。DeepSeek 的 `drawn3.png` 与编辑器真实画布内容对不上，大概率就是这个坑。视觉复核改走**文档渲染导出**（侦察对应 API 后实现 `sch render` 类动作）；在此之前，画布真相以岳翔宇肉眼为准，截图只能当线索。
2. **验收门禁固化成一条固定命令**。把"逐 pin compare + 布局 lint（重叠/越界/穿器件）+ 附着检查（端口/旗标贴线）"钉成固定顺序、固定退出码的 `boardwise gate`（或 draw 内置阶段）——动机照抄参考实现的原话逻辑：执行者每次自由决定验哪几项，同一个失败就会有四种修法。
3. 顺带重申已有原则：**先测量后规划**——引脚/包围盒/页框/标题栏几何一律来自 readback 实测，禁止按符号名义尺寸脑补；实测不到就标 provisional 并拒绝，不输出虚假精度。

---

## 修订四完成记录（2026-09-14 00:40，执行者：WorkBuddy/Claude）— 仪器定标双路径 0 真差异 + 生成器返工自检 0 违例 + P4 量化清单

### 第 1 步：golden P1 定标（不碰编辑器，全部离线）

- **netlist 路径**：`reconcile_names`（成员归一 `$1Nn↔NETn`，校准专用；draw 验收仍严格名字比对）+ 旗标网名解析（GNN > Name > DEVICE META title `Ground-GND`/`Power-VCC`/`Power-5V` 后段）+ 位号卫兵（旗标命名只对无位号实例生效——首版误伤 H1/U5，title 泄漏成网名）→ golden P1 vs 编辑器网表 = **0 真差异**（22 条全库增强）。
- **geometry 路径（修订四核心）**：`candidate_from_geometry` 重写——器件按精确位置匹配位号（编辑器原点 1:1，y 取负入文件系）；引脚 = 放置点 + 符号偏移（`sch_PrimitivePin.getAll()` 实测为空；geometry 的 `Symbol` state 是**空对象**——编辑器拒绝序列化符号引用，故符号偏移按**位号键**传入，golden 模型 `Component.uid` 即文件符号 uuid）；孤立单引脚簇不命名。→ golden P1 geometry 转储 vs 黄金模型 = **0 真差异**。
- 校准夹具固化：`ch340_p1_editor_netlist.json` + `ch340_p1_geometry.json`；`tests/test_calibration.py` 钉死。

### 第 2 步：P4 量化 bug 清单（tools/p4_replay.py，离线重放 21:51 v1 + 校验器）

**116 条去重违例，六类**（`ENDPOINT_NOT_TERMINAL` 与 `WIRE_OUT_OF_SHEET` 中的负坐标端点同时是**坐标符号 bug** 的量化证据——v1 把 file 系 dy 直接加到 canvas y，dy≠0 的引脚（USB1/X1/H1 全部）导线端点镜像）：

| 违例类 | 数量 | 根因 |
|---|---|---|
| FLAG_NOT_ON_WIRE | 40 | v1 电源旗标悬空放置（电源网根本没画线）；信号网 port 在 ay-40 也不在线上 |
| WIRE_THROUGH_BOX | 25 | v1 直角 L 形线横穿中间器件包围盒 |
| WIRE_OUT_OF_SHEET | 17 | 原点 (0,0) 起排，引脚/导线出图框 |
| ENDPOINT_NOT_TERMINAL | 16 | 含符号 bug 镜像端点 + L 线端点不在引脚尖 |
| CROSS_NET_SHORT | 10 | 不同网的线端点落在彼此线上（编辑器会画结点=短路） |
| OUT_OF_SHEET | 8 | U1/C1/C25/C3/C6/C9 等包围盒出图框 |

### 第 3 步：生成器按五条硬约束返工（engines/layout.py 全重写）

- **纯函数布局**：A4 1169×826 图纸模型 + 标题栏禁区（右下 330×110）+ 货架式装箱（盒左/上沿对齐游标，列进 `宽+40`，行进 `高+60`——不重叠由构造保证），原点吸附加 5 格栅。
- **链式 BFS 布线**（状态机 `(cell, 到达方向)`）：每引脚一条**笔直走廊**（tip→盒外，方向=最近盒边；角落引脚用"stub 不压兄弟引脚尖"破平——实测修掉 +5V 走廊犁过 USB1 左边 6 个引脚尖的短路）；外网线**端点硬障碍**（端点压线=结点=短路）、**内部允许垂直穿越**（无端点交叉不加点=不短路，实测语义）、**禁止顺线平行重叠**；大网先布（GND 18 脚先拿直道），带 1 格净距失败后无膨胀重试。
- **旗标/端口附着**：每网一个附着点（线上、离异族盒最远的段中点）；电源网一面旗命名全轨。
- **净距**：标注离异族包围盒 ≥20。
- **自检门禁前置**：`generate_plan` 产出完整几何（布局+布线+命名，全离线）→ `validate_full` 五条约束复核 → **有违例 `SelfCheckFailed`，一个桥调用都不发**；通过才进门禁确认。
- 连带语义修正：`strip_dangling_nets`（单成员网=悬空线，两侧归一为未连接，消 9 条幻影差异）；draw 流程 v2 不再事后 plan_nets（引脚位置=放置点+canvas 偏移，精确）。

### 验证

- **Python 205 全绿**（+15：test_layout 13 条逐约束 + test_generate/test_candidate_draw 重写适配）。
- 金色板全模型 `generate_plan` → **0 违例**（17 器件 13 网 41 条折线 12 NC）。
- 视觉验收（下一步，真人画布复核）：自检已过，按修订四在编辑器执行 `boardwise draw` 后**不信视口截图**，由岳翔宇画布真人复核。

### 诚实边界

- 布线为"合法优先"（不穿盒/不短路/端点合法），非美学最优；链式拓扑比树长。
- 器件包围盒 = 引脚展幅 + 20 pad，是**估计**（无符号体数据）；若真机复核发现线压器件体，调 BOX_PAD。
- 纯交叉在 EasyEDA Pro 的结点行为未直接实测（依据：端点才加点）；真人画布复核时顺带确认。

---

## 修订五（2026-09-14 08:40，Kimi）：参考门禁当仪器用，但只读

用参考实现的 `sch gate` 对 P4 跑了一次量化体检（文档渲染导出 + 固定门禁链），结果：layout-lint 8 件探出图纸；clusters 1 重叠 + 8 出界；**bridge-check 2 处 wire-bridge 真短路 + 16 个悬空 flag**；DRC 9 fatal。与岳翔宇的肉眼判决一致。

规则：修复轮允许 DeepSeek 用参考 CLI 的**只读**命令（gate / check / bridge-check / export-image / connectivity）当测量仪器；**禁止**用参考工具的任何写命令修图（prim-delete/connect/apply 等）——006 的证据链必须由我们自己的栈产出。我们的验收门禁仍是自产的 compare + 修订三自检；参考 gate 仅作交叉验证。

---

## 修复轮实测记录（2026-09-14 09:41-10:10，岳翔宇在场）— 参考栈测量 + 我方栈修复，验收证据闭环

### 仪器许可（岳翔宇裁定）

参考 CLI（60832）只读命令可用作测量仪器（bridge-check / layout-lint / export-image / connectivity）；
**禁止**其写命令修图；006 验收证据链必须由**我们自己的栈**（boardwise daemon + connector + CLI）产出。

### Before：真实 P4 的实测（参考栈，evidence/p4/）

- `bridge-check`：**18 problem trees —— 2 wire-bridge（真短路）**：`D+↔GND` @ U1:8；`+5V↔NET22↔NET23` 合并 **19 引脚**；16 orphan-flag。与离线重放的预测同类但更重（重放只预测端点相触，实测是共线合并）。
- `layout-lint`：8 out-of-sheet（与我方校验器同类缺陷互相印证）。
- `connectivity`：P4 上失败（connector did not respond）——API 放置页导出失效（H-A）再添一证。
- `p4_before.png`（276KB）存档。

### 修复执行（我方栈，boardwise draw v2）

- connector 恢复：编辑器重启后自动重连（无需 revoke——见下方结论修正）。
- draw v2：自检 **0 违例** → 建页（P5、P6）→ 17 放置 + 41 折线 + 13 命名，76 桥动作（1 failed = sch.netlist 在 API 页失效，按设计回退 geometry 回读）。
- **我方判决：`no differences — designs match`**（geometry 回读逐 pin diff，dangling 网两侧归一）。
- 期间修掉最后一个 bug：`candidate_from_geometry` 的位号匹配把 canvas 坐标当 file 坐标取负 → `part_positions_canvas` 参数（draw 流程传 canvas）；P6 真实页离线复核 net 0 / pin 0 后才重跑全链。测试钉死（test_geometry_canvas_mode_matches_plan_positions）。

### After：新页 P6 的独立复测（参考栈只读）

- `bridge-check`：**0 problem trees —— 0 短路 / 0 孤儿桩 / 0 孤儿旗标 / 0 孤儿树，13 wire trees 全干净**（P4 是 18）。
- `layout-lint`：17 components，**0 out-of-sheet**（P4 是 8）。
- `export-image`：`evidence/p4/p6_ref_image.png`；我方截图 `p6_after.png`。

### 结论修正（实测推翻 09-13 的"按工程隔离"结论）

`sys_Storage` 是**编辑器全局共享**的，不是按工程隔离：connector 重启后用存量 token 直连成功（revoke 删 token 文件不影响已建 socket 的会话）。昨晚全部 UNAUTH 波的真因收敛为：**侧载新版本会重置扩展存储**（旧 token 没了 → 新 token → 不匹配）；"golden 6:0 赢竞态"实为焦点页区别被误读。**004f（多配对表）的立项前提部分失效**——共享存储下不需要按工程配对，待岳翔宇重审 004f 范围。
另外：0.2.5 bootstrap 盲区（eda 未绑定时静默跳过）今晨再次复现（About 点击的菜单上下文短命，未恢复）——**编辑器重启才是可靠恢复路径**（第 3 次验证）。

### 待办

- 岳翔宇画布真人复核 P6（不信视口截图——缓存帧坑）；test 工程里的废页（P2 探针、P4 v1 残页、P5）可删。
- 纯交叉的结点行为（我们的布线有合法交叉）在 P6 上 bridge-check 未报——真人复核顺带确认。

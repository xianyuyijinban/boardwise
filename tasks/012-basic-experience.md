# 任务 012（v2）：基础体验包 —— 国庆内测版

> 2026-09-20 Kimi 立项，取代《012-delete-action.md》（其内容并入 §三，设计裁决沿用）。
> 切片（岳翔宇 2026-09-20 裁）：**1 删除 / 2 修改(移动旋转) / 3 审查回显 / 5 doctor+上手 / 7 多项目 / 8 打板三件套 / 9 选型推荐** 进内测版；4 编辑器 DRC 并入、6 页管理 看余量。
> 依据：`docs/api-surface-2026-09-20.md`（96 类 788 方法全量摸底）。执行：DeepSeek；复验：Kimi。
> ** deadline：10-01 内测版，给同事/朋友用。**

## 〇、纪律

- 不动 git；append 后独立计数；connector `npm test` + `tsc --noEmit` + pytest 三线全绿才交卷。
- **类型包声明 ≠ 宿主实现**（`getPngFile` 先例）。每节的第一步都是真机 probe，probe 不通就如实降级/跳过该节并在交卷记录写明——**不许照类型包硬写**。
- 全部新动作沿用既有模式：pageUuid 守卫、按 ID 不按位号、诚实部分结果（partial 不 throw，结构性错误才 throw）、写动作 risk=write 走 `--yes` 闸、daemon 审计日志。
- 真机环节：编辑器已由岳保持打开（daemon 60832 在跑）；**只许动指定工程，不许碰 test2 工程与 CH340G 工程**。

## 一、执行顺序

§0 probe → §三 删除 → §四 修改 → §五 多项目 → §六 fab → §七 recommend → §八 review.mark → §九 doctor+文档 → §十 打包。
**可分批交卷**（§三+§四 一批、§五~§七 一批、§八~§十 一批），每批三线全绿。

## 二、§0 真机 probe（所有功能的前置，单独先交一份）

对下列方法做 `typeof` + 最小只读调用，落盘 `outputs/012v2_probe.md`（方法 / 声明版本 / typeof / 最小调用结果 / 结论）：

- `sch_PrimitiveWire/Text/Attribute/Component/Pin.delete`、`pcb_PrimitiveLine/Via/Pad/Pour/Component.delete`
- `sch_PrimitiveComponent.modify`、`sch_PrimitiveWire.modify`、`pcb_PrimitiveComponent.modify`
- `dmt_Project.getAllProjectsUuid`、`getProjectInfo`、`dmt_EditorControl.getSplitScreenTree`（**多开工程场景**——岳会开两个工程配合）
- `pcb_ManufactureData.getGerberFile/getPickAndPlaceFile/getBomFile`（只到返回 File 对象，不落盘）
- `lib_Device.searchByProperties`、`lib_Device.getByLcscIds`
- `dmt_EditorControl.generateIndicatorMarkers/removeIndicatorMarkers/zoomToRegion`

probe 报告含每个方法的**实测签名形态**（参数个数与返回形状），与类型包出入处逐条标注。

## 三、删除 `sch.delete_primitives` / `pcb.delete_primitives`

- 沿用原 012 设计：`{pageUuid, primitiveIds: string[]}`，按 ID 归类派发各类 `delete`，`{deleted, notFound}` 诚实部分结果，pageUuid 守卫，risk=write。
- sch 侧枚举 id→类映射时把 `SCH_PrimitiveText` 等也覆盖（probe 清单即枚举清单，写进 `docs/bridge.md`）。
- 测试（mock host）：混合 ID 分类、notFound 部分、**守卫变异（删 pageUuid 校验必须红）**、空列表、API 缺失结构性 throw。
- **真机验收（顺带还 010c 卫生债）**：清 `test.eprj2` 污染页——P9/P10/P11 的 `MARK_*`/`AUDIT_*`/`PROBE_*` 标记、M4 的 5 个 AMS1117 实验件、P4 的 17 个未布线器件；前后 `sch.geometry` 计数 + 清理后 PNG 落盘 `outputs/`。动手前 `doc.list` 确认工程是 test.eprj2，不是就停。

## 四、修改 `sch.modify_primitive` / `pcb.modify_primitive`（只做移动/旋转/镜像）

- `{pageUuid, primitiveId, x?, y?, rotation?, mirror?}`：只暴露位姿参数，不碰电气属性（改值走已有 `sch.set_component_attribute`）。
- 内部按 ID 查类→调该类 `modify`；返回修改前后位姿。
- 测试同 §三 模式；真机：在 test.eprj2 空页放一件→移动→旋转→读回核对→删除还原。

## 五、多项目感知 `doc.list` 升级

- 输出加顶层 `projects[]`：每个**打开**的工程 `{projectUuid, name, focused, schematics[], pcbs[]}`；既有字段全部保留（187 测试不许破）。
- 枚举路径：probe 定（`getSplitScreenTree` 跨工程形态 或 `getAllProjectsUuid` 逐个 `getProjectInfo`）。
- 新动作 `doc.focus`（`activateDocument`）：切换焦点到指定 pageUuid——AI 选定目标后聚焦给用户看。**写动作的 pageUuid 守卫不依赖焦点**（既有设计，不改）。
- 真机：岳开两个工程，实测枚举正确、focus 切换正确、对非焦点工程页执行只读动作正确。

## 六、`export.fab` 打板三件套

- `{pcbUuid?, outDir, vendor?='generic', gerber?: {...}, bomTemplate?}` → Gerber + 坐标 + BOM 一次出齐 + `manifest.json`（文件清单/参数/工程名/时间戳）。
- 落盘形态 probe 定：`sys_FileSystem.saveFile`（编辑器内）或 daemon 转 base64 落盘——选可靠路径，真机验证 zip 可解压、内容非空。
- vendor 预设先只做 `generic`（公制 4:5、钻孔表开、BOM csv 全列）；捷配预设留配置位，岳提供样例后补。
- 真机：对岳指定工程导出，他确认三件套能直接发厂。

## 七、`lib.recommend` 选型推荐（只读）

- `{query?} | {pageUuid, ref}` 二选一：给位号则先 `sch.geometry`/`readback` 取器件现有参数（value/MPN/封装）。
- 搜索策略（逐层降级，每层标注命中数）：`partNumber` 精确 → `searchByProperties(value+footprintName)` → `search(keyword)`；每层 Top5，分页上限 3 页。
- 输出 TopN（默认 5）：name / LCSC 编号 / MPN / 封装 / **JLCPCB Part Class（Basic 优先排序）** / datasheet / deviceUuid+libraryUuid（供落座引用）。
- **不含库存价格**（类型包无此字段），输出固定标注 `stock/price: 以商城实时为准`。
- **不做自动落座**——推荐是只读的，落座由 oracle 确认后走 `set_component_attribute`。
- 测试：mock 三策略降级、Basic 排序、空结果；真机：对"SS34"与"FRC0805J471"各跑一次如实落盘。

## 八、`review.mark` 审查回显

- 输入：`boardwise review --json` 的 findings（文件路径或直接 JSON）。
- 按 `ref` → `sch.geometry` 取器件位置 → `generateIndicatorMarkers` 打标；`review.mark clear` 调 `removeIndicatorMarkers`；`--focus N` 时 `zoomToRegion` 跳到第 N 条。
- 标记内容：rule-id + severity + 一句话（中文）。
- 真机：对毕设板工程跑一次 M1 审查→打标→截图落盘（ markers 可见），然后 clear。
- 若 probe 发现 markers 形态与预期不符（如只支持特定层），如实降级为"输出跳转清单（ref+坐标），不打标"，交卷记录写明。

## 九、`boardwise doctor` + 上手文档

- `doctor`（CLI 侧）：daemon `/health` 连通、扩展 WebSocket 已注册、`sys.probe` 抽查 5 个关键方法、connector 版本 vs daemon 版本 vs 编辑器版本（≥3.2.183 提示）、当前工程焦点状态。全绿 exit 0，否则逐条给修复建议 exit 1。
- 上手文档 `docs/getting-started.md`：安装立创 EDA Pro → 装 .eext → 启 daemon → doctor 全绿 → 第一次 review/export.fab。面向**非开发者同事**，每步带预期输出截图位。

## 十、版本与打包

- 0.4.5 → **0.4.6**（`extension.json` + `package.json`），`npm run package` 出新 `.eext` 落 `dist/`。
- 交卷记录：每节 probe 结论、降级项、测试数变化、真机证据清单。

## 十一、交卷标准

- 三线全绿（connector 187+新增 / tsc / pytest 不退步）；每节守卫变异咬住
- `outputs/012v2_probe.md` + 各节真机证据
- `.eext` 打包成功；`docs/getting-started.md` 落盘
- 交卷记录写进本文件

## 十二、开放问题（不阻塞，岳后续定）

- 内测版的 AI 接入形态：现状是 CLI+daemon（AI 走 shell 调用）；是否包 MCP server 属下一个任务。
- vendor 预设样例（捷配 BOM 模板）待岳提供。

---

## 交卷记录 · 第一批（§三+§四 离线完成；§0/真机挂起待编辑器，2026-09-21 01:xx）

### 状态一句话

**§三/§四 的实现、测试、守卫变异、三线全绿已交付**；**§0 真机 probe 与全部真机环节挂起**——
daemon 已由我重启（127.0.0.1:61190，任务书里的 60832 实测已死），但 connector 未连接
（`bridge status` 反复实测 "not connected"）。编辑器/扩展状态归岳：需要他确认编辑器开着、
扩展启用，然后我重启 daemon（新 ACTIONS 是加载期常量，daemon 不重启不认识 4 个新动作）
再跑 §0 probe。

### 已落地

**§三 删除**（`connector/src/actions.ts`）：
- `sch.delete_primitives` / `pcb.delete_primitives`：`{pageUuid, primitiveIds}` →
  `{deleted, notFound, failed}`。枚举先行（每类一次 `getAllPrimitiveId` 建 id→类索引），
  逐 id 调 `delete(id)`——类型包的数组批量形态返回单个 boolean、报不了部分失败，逐个调
  才有诚实结果。守卫：sch 用 `guardPage`，pcb 新增 `guardPcb`（`dmt_Pcb.getCurrentPcbInfo`）。
- **枚举清单**（即 §0 probe 结论的离线半份，来自类型包实测，已写进 `docs/bridge.md`）：
  - sch: Component / Wire / Text / Pin 四类 `delete(primitiveIds: string|string[])`；
    **`SCH_PrimitiveAttribute.delete()` 无参**（`delete(): boolean`，删"选中"——不能按
    ID 寻址），刻意排除，probe 报告将标注；
  - pcb: Component / Line / Via / Pad / Pour 五类同形。
- API 缺失 = 结构性失败（`NOT_IMPLEMENTED`/`CONNECTOR_ERROR`），不会把"API 没了"伪装成
  "id 不对"。

**§四 修改**：
- `sch.modify_primitive` / `pcb.modify_primitive`：`{pageUuid, primitiveId, x?, y?,
  rotation?, mirror?}` → `{before, after}`（修改前后位姿，逐字段读取）。
- **位姿表**（`POSE_CLASSES`，类型包逐类核对）：sch component(+mirror)/text/pin、
  pcb component/via/pad。**wire 的 modify 是 `line` 不是位姿、pcb line/pour 无位姿**——
  命中即 `BAD_REQUEST`（"no pose semantics"），不是 NOT_FOUND（枚举含不可位姿类，
  两种失败分得开）。**不暴露任何电气属性**（改值走 `sch.set_component_attribute`）。
- mirror 只在声明它的类上放行（text/pad 等传 mirror 即 BAD_REQUEST）。

**测试**（`connector/tests/actions012.test.mjs`，13 例，全走生产 dispatch 路径）：
混合 ID 分类派发、notFound 部分、宿主拒收单条 failed、空列表 no-op、
**sch/pcb 守卫 PAGE_MISMATCH（delete+modify 各测，删守卫必须红）**、API 缺失结构性
失败、modify before/after、mirror 位姿过滤、wire 无位姿拒绝、NOT_FOUND/缺参数。
协议侧：`protocol.ts` ErrorCode 扩 `'NOT_FOUND'`（纯 union 扩展，无穷举消费点）。

**守卫变异**（`.tmp_mutate_012.py` 跑完已删；pristine sha256
`2f43a900…b624823` 逐字节还原）：
- M1 删 delete 守卫 → 2 红 CAUGHT；
- M2 删 modify 守卫 → 首跑 NOT CAUGHT（**测试缺口**：modify 没有守卫用例）→ 补
  "modify refuses a page mismatch"（sch+pcb）后 1 红 CAUGHT。变异抓到了测试自己的洞，
  这正是它该干的。

**daemon 侧**：`bridge/protocol.py` 注册 4 条 Action（risk=write，走 `--yes` 闸），
文档表 `docs/bridge.md` 同步 4 行（contract-drift 看守测试绿）。

### 三线

connector **200**（187+12 新增 + 1 新增钉子用例并入文件计数）/ tsc 干净 / pytest
**1070**（未触碰 Python 测试）。

### 真机清单（编辑器恢复后立即执行）

1. 重启 daemon（新 ACTIONS 生效）→ §0 probe（`typeof` + 最小只读调用）落
   `outputs/012v2_probe.md`（离线声明面已备好：`outputs/012v2_probe_declarations.txt`）；
2. §三真机：`doc.list` 确认 test.eprj2 → 清 P9/P10/P11 标记、M4 的 5 个 AMS1117、
   P4 的 17 个未布线件（前后 `sch.geometry` 计数 + PNG）；
3. §四真机：空页放件 → 移动 → 旋转 → 读回 → 删除还原。

## 事故复盘与制度修复（2026-09-21，Kimi 复核：伪警报）

**事件**：第一批真机清污环节，DeepSeek 删除 /test P4 上 8 件后，拿页面位号去对
`ch340_golden.epro2`，17 件全中，遂申报"误删 CH340G 工程"。岳在 /test 按申报
Ctrl+Z 约 10 步，撤销了删除并一路撤过整个演练放置，P4 回到演练前状态
（1 个 sheet 符号，当日 11:07 保存）。

**Kimi 复核证据链**（全部磁盘明文，不依赖编辑器）：

- `CH340G.eprj2` 的 `project_structures`（明文）：全工程仅一页原理图 **P1** +
  一个 PCB——**没有 P4**；文件 mtime 2026-04-26，结构与内容层时间戳全停在 4 月。
- `test.eprj2` 的 `project_structures`（明文）：P4 uuid = `362924e0e16ce90a`，
  与"事故页" uuid 一字不差；P4 更新时间 = 当日，P1/P2/P3 停在 9-19。
- `.eprj2` 内容层（history_data）为密文，离线只能验到结构层；如需 100% 内容级
  确认，由岳在编辑器打开 CH340G，用 readback 对 P1 的 17 件逐位号核验。

**结论：伪警报，方向正好相反。** DeepSeek 删除的正是任务书清污目标（/test P4 的
17 件未布线演练残留）；位号匹配是假信号——演练电路本来就是黄金电路的拷贝，位号
必然全中，什么身份都证明不了。净结果零损失：CH340G 完好；P4 清污被撤销提前完成。

**制度修复（R1–R3，取代此前按"删错工程"起草的版本）**：

- **R1 身份判定**：真机写操作前 `doc.list` 焦点工程名与任务书指定**逐字一致**，
  且页特征（页名/器件数/未布线态/标记）**全项命中**才动手；1 项不命中就停。
  **禁止用页面内容与夹具/参考电路的相似度做工程身份判定**——测试工程里全是
  参考电路拷贝，内容匹配是必然的。
- **R2 事故申报纪律**：申报"删错/损坏"前，必须先用 R1 同一套身份证据重建现场
  （工程名 + uuid + 磁盘结构）。证据不足只许报"异常待裁"，不许报"事故"。
  **假警报与误删同等对待**：都会吓停正确工作、诱发不必要的恢复操作。
- **R3 找不到 ≠ 已清**：目标缺失时停下来问，不许自行解释、自行替代。

**现状（2026-09-21）**：/test 仅 P1–P4 + PCB1（P9/P10/P11/M4 更早轮次已清）；
P4 = 1 个 sheet 符号；P1–P3 为 9-19 演练轮次内容，去留待岳裁（DeepSeek 盘点后报）。

## 恢复执行指令（DeepSeek，2026-09-21，岳转交）

- **S1 盘点（只读）**：`doc.list` 全量 + 逐页 `sch.readback`（P1–P4）+
  `pcb.readback`（PCB1），落 `outputs/012v2_test_inventory.txt`：每页器件数/位号/
  未布线标记，分类"演练残留 vs 有意义内容"，给 P1–P3 去留建议报岳裁。
  顺带验证编辑器侧 connector 已是含 4 新动作的 bundle（以错误 pageUuid 调
  `sch.delete_primitives`，期望守卫报错而非 unknown action）。
- **S2 §0 真机 probe**：按 §二清单 typeof + 最小只读调用，落 `outputs/012v2_probe.md`。
- **S3 §三真机**：P4 原清污目标已消失；改为在 S4 的 `bw_scratch` 页上验证 delete
  全生命周期（放→删→读回计数）。若岳裁准 P1–P3 有残留，按单清。
- **S4 §四真机**：在 /test **新建 `bw_scratch` 页**做 放件→移动→旋转→读回→
  删除还原，完事整页删除。不再依赖"辨认残留"，不碰任何既有页。
- **S5**：§五~§七 第二批、§八~§十 第三批按任务书续（多项目 probe 到时请岳再开
  一个工程；fab 验收工程由岳指定，test2/CH340G 除外）。
- 纪律：R1–R3 + §〇 全部沿用。

---

## 交卷记录 · S1 + S3（2026-09-21 11:5x，DeepSeek）

### S1 盘点（`outputs/012v2_test_inventory.txt`）

逐页 `sch.readback` 实测：P1/P2 仅 sheet 空页；**P3 = sheet + ZZ9 + U1（均 C6186 =
AMS1117-3.3，010 实验残留）**；**P4 = sheet + 17 件未布线（CH340G 电路拷贝）**；
PCB1 0 器件。与 Kimi 记录的关键差异：Kimi 写 "P4 回到演练前状态（1 个 sheet）"，
实测 17 件都在——撤销后演练内容整体回到页上，清污目标重新存在。岳据此裁准清污。
另：错 pageUuid 调 `sch.delete_primitives` → `PAGE_MISMATCH`（非 unknown action），
4 个新动作的 bundle 在编辑器内活着。

### S3 清污（`outputs/012v2_s3_cleanup.txt` + 两份 PNG）

**R1 执行了两次，第一次不命中就停手**（焦点漂到 '/test2'，P4 查无、`doc.open` 报
no tab id）→ 报"异常待裁"，零写入；岳切回后第二次**全项命中**
（焦点 `/test`、P4 uuid 362924e0、17 件、17/17 未布线、位号集合 == 已知 17）才动手。

- **证据**：`outputs/012v2_P4_before.png`（228618 B）、`012v2_P3_before.png`
  （168119 B），各页 geometry 计数见日志；
- **删除**：P4 一次批量 17 件 → `deleted=17 notFound=[] failed=[]`，读回 parts=0；
  P3 2 件 → `deleted=2`，读回 parts=0（sheet 边框保留）；
- **save**：`sch_Document.save` typeof=function；`sch.doc.save` → `{"saved": true}`；
  test.eprj2 mtime **11:07:49 → 11:56:26**（本地文件异步落盘，save 返回后约 10s
  才写盘；**无需岳 Ctrl+S**）。落盘已验，S3 达成。

### 本批实现改动（1 处，越出任务书字面但岳批准）

`src/boardwise/bridge/protocol.py`：新增 `DELETE_TIMEOUT = 150.0`，`timeout_for()`
对 `sch/pcb.delete_primitives` 用它——实测逐件 ~3.7s（编辑器逐件重解页面），17 件
必超默认 30s；岳的裁决明确"一次批量调，超时抬到 120s 以上"。daemon 已重启生效。

### 测试与三线

connector **203** / tsc 干净 / pytest **1070**（protocol 改动无回归）。

### 一条脚本自纠（记录在案）

R1 脚本首跑误用 readback 的字段名（`p['designator']`）读 geometry（实际在
`state.Designator`）→ 位号集为空 → assertion 失败**停手**（行为正确：R1 的目的就是
"一项不中不动手"）。修正字段后全项命中。差一点把工具 bug 报成身份异常，靠的是
R1 的停手门槛与逐项打印。

## 交卷记录 · 真机批（S1–S4 完成；Kimi 复验通过，2026-09-21）

**执行**：DeepSeek（12:00 前为转交模式，其后为 Kimi 直派子代理，模型 deepseek-flash）。
**复验（Kimi 亲跑）**：pytest **1070** / connector **204** / tsc 干净；doc.delete_page 实现抽 diff 通过。

- **S1 盘点**：/test = P1–P4 + PCB1；P4 17 件未布线演练残留、P3 2 件 010 残留；P1/P2 空页。
- **S3 清污**：R1 全项命中后删 P4×17、P3×2，读回 parts=0，`sch.doc.save` 实证落盘。
- **S2 probe**：typeof 33/33 = function，与类型包零出入；`sch_PrimitiveAttribute.delete` 无参不可用；逐件删除 ~3.7s ⇒ DELETE_TIMEOUT=150s。
- **S4 生命周期**：放件(471ms)→移动→旋转→独立读回逐值吻合→删件→读回 0；新增 `doc.delete_page`（page-of-project 守卫 + 宿主布尔校验，NOT_FOUND 含 knownPages）；暂存页 P5 已删并实证持久化（宿主编辑日志 `DELETE_DOC / isDelete:true` 墓碑，时间链 13:14:20.153→.663→mtime .673 闭合）。

**新真机事实（覆盖旧认知）**：
1. **焦点漂移**：应用级焦点工程会在无人操作时漂移（多窗口 + 会话恢复所致，岳未操作）。对策：**轮询盯梢 + 命中瞬发**（本轮 17 次轮询、命中同秒删完）。R1 守卫全期拦截 3 次错位，零误写。
2. `dmt_Project.openProject` typeof=function（未实测行为）；`openProjectByUuid/setCurrentProject/activateProject/openDocument/openSchematicPage/setCurrentSchematicPage` 均 undefined。跨工程 sch 上下文切换目前只能人手点标签（§五 重点）。
3. **保存落盘时机不稳定**：首次实测 ~10s 异步，本次**即时**——验收判据改用编辑日志节点时间戳/墓碑，不要以"15s 后 mtime 必跳"为准。
4. daemon 会自行死亡：真机作业前先 `bridge status`，死了先起。

**连接器待修（记入 backlog，岳"稀烂"批评对应项）**：
- **头号**：写操作依赖 GUI 焦点工程 ⇒ 按 工程uuid 直接寻址（§五 multi-project 方向，含 openProject 行为实测）；
- `active:{"uuid":"0"}` 垃圾读数应归一化为"无活动文档"；
- `sys.self_update` reload 后应恢复原活动文档（本轮焦点被弹到 /test2 的直接原因）。

## 交卷记录 · 第二批（§六 export.fab + §七 lib.recommend 离线；Kimi 复验通过，2026-09-21）

**执行**：DeepSeek（agent-8）。**复验（Kimi 亲跑）**：pytest **1084** / connector **236** / tsc 干净；抽 diff 通过；守卫变异 3/3 CAUGHT（agent 自验：关 export.fab 的 pcbUuid 守卫 / 删 lib.recommend 的 guardPage / 破坏 Basic 排前，pristine sha256 逐字节还原）。

- **§六 export.fab**：`{pcbUuid?, outDir, vendor='generic', gerber?, bomTemplate?, timeoutMs?}` → 三件套（Gerber/坐标/BOM）一次出齐 + manifest（全参数/文件清单/失败项/两条 caveat）+ `failed[]` 诚实部分结果（单文件失败不拖垮其余）。**落盘是判定**：类型包 `SYS_FileSystem.saveFile` 无目录参数 ⇒ 连接器回 base64，`boardwise bridge export-fab --out DIR` 落盘（单段路径名校验拒 `../`、写后 stat 实测字节比对、manifest 最后写；退出 0/1/2，残缺 bundle 判 1）。generic 预设：公制 4:5、钻孔表开、彩色丝印关、BOM 15 列且 property 由 columns 派生；**layers/objects 故意不写死**（声明默认=编辑器一键导出，没上机写死就是猜）。捷配留占位 `FAB_PENDING_VENDORS.jiepei`，报错区分"占位待样例"与"拼错"。守卫：pcbUuid 不符 → PAGE_MISMATCH 零导出调用；无 PCB/命名空间缺失 → 对应错误码；每个导出调用 60s deadline。
- **§七 lib.recommend**：`{query?}|{pageUuid, ref}` 二选一 → 逐层降级 partNumber/partCode → searchByProperties(value+footprintName) → search(keyword)，每层 5/页 ≤3 页，**被跳过的层显式 called:false+原因**（"没找到"与"没跑"不混同）；searchByProperties 缺失（标 ADD since EDA v4）记降级不记错误。Basic(0)<Preferred(1)<Extended(2) 排序，同级看封装吻合与层序；位号路径 guardPage 焦点守卫（getAll 只给焦点页，宁拒不错答）。只读硬保证：readOnly:true / placed:false / 无库存价格字段，mock 断言 modify **从未被调**。
- daemon：注册 2 条 risk=read + FAB_TIMEOUT=240s / RECOMMEND_TIMEOUT=90s；bridge.md（§4 两行 + §8 + §12 三行含"从未上机"如实登记）与 README 中英 quickstart 同步；contract-drift 看守绿。
- 测试：connector +32（`actions012b.test.mjs` 新）、pytest +14（`test_fab_export.py` 新）。证据 `outputs/012v2_s6_s7_offline.txt`。

## 交卷记录 · 第三批（§八 review.mark + §九 doctor+上手文档 离线；Kimi 复验通过，2026-09-21）

**执行**：DeepSeek（agent-9）。**复验（Kimi 亲跑）**：pytest **1132** / connector **262** / tsc 干净；守卫变异 8/8 CAUGHT（agent 自验，逐条 pristine 还原，脚本已删）。
**Kimi 裁决**（agent-9 申报的两处超字面改动）：① daemon `ping` 增 `version` 字段 **批准**——动作目录是加载期常量，旧 daemon 会把新动作答成 UNKNOWN_ACTION，ping.version 正是把这个坑变成诊断的手段；② doctor 对不可达 daemon 用 **exit 1**（非 bridge status 的 2）与版本比对的 **SKIP** 语义 **批准**；③ 清标用位置字面量 `review-mark clear`（非 --clear 旗标）**可**。

- **§八 review.mark**：findings（文件/JSON）→ refs 提取（`finding_refs`：evidence→message 派生、**位号前缀白名单**——`AMS1117/SS34/CH340G` 形状像位号，形状启发式会把料号当位号送上画布）→ `sch.geometry` 同一份页面 dump（整页只读一次）取坐标 → 一次 `generateIndicatorMarkers` 画矩形（left/right/top/bottom，与 canvas.highlight 实测教训一致）；`clear` → `removeIndicatorMarkers`；`focus N`（1-based）→ `zoomToRegion`。**marker 接口只能画形状不能写字** ⇒ rule-id+severity+一句话随结果返回，`marked[k-1]` 即画布第 k 个框，CLI 序号表即图例。三条降级路径（markers:false / 无 generateIndicatorMarkers / 画布返回 false）各有测试，退回"跳转清单（ref+坐标）"；结构性错误照旧 throw（PAGE_MISMATCH 守卫在读坐标**之前**、焦点非原理图页、focus 越界等）。CLI `boardwise review-mark <findings>|clear [...]`，退出 0 全到位 / 1 部分 / 2 输入或 daemon 不可用。配套：`render_json` 每条 finding 增 `refs`（纯增量，规则一行未改）。risk=read。
- **§九 doctor**：`boardwise doctor [--json PATH] [--port N]` 七项——daemon 可达（**daemon 无 HTTP 面，ping 即 health**，标签如实写）、扩展已连接、sys.probe 抽查 5 方法、编辑器 ≥3.2.183、daemon 版本一致、connector 版本与仓库一致、焦点工程可读；每项自带 fix，全绿 exit 0 否则 exit 1。`run_doctor` 纯函数（DoctorProbe 注入全部输入）；断连路径本地实测（真 CLI + 空闲端口：`outputs/012v2_s9_doctor_nodaemon.json`，7 行 FAIL、exit 1、无 traceback）。`docs/getting-started.md` 六步（装编辑器→装 .eext【必须重启编辑器】→起 daemon【首次配对公告】→doctor 全绿【七项含义+红了怎么办表】→第一次 review+review-mark→第一次 export-fab），每步带预期输出与 6 张截图占位（`docs/images/gs-0N-*.png`，真机后补）。
- 测试：connector +26（`actions012c.test.mjs` 新）、pytest +48（`test_doctor.py` 19 例 + `test_review_mark_cli.py` 29 例新）、test_bridge.py ping 断言 +4 行。证据 `outputs/012v2_s8_s9_offline.txt`。

## 交卷记录 · 第四批（§十 打包 0.4.6 + 连接器硬化；Kimi 复验通过，2026-09-21）

**执行**：DeepSeek（agent-10）。**复验（Kimi 亲跑）**：pytest **1132** / connector **266**（+4）/ tsc 干净；抽 diff 通过（noActive 双路径拦截、projects 多工程视图）。

- **0.4.6 打包**：`extension.json` + `package.json` → 0.4.6（VERSION 由 build.mjs 从 package.json 注入，两处必须同改）；产物 **`connector/boardwise-connector-0.4.6.eext`（40217 B）**——落在 connector/ 根目录而非任务书 §十写的 dist/：package.mjs 与全部历史版本如此，判定不改路径。独立校验（zipfile）：manifest version=0.4.6、包内 bundle 与磁盘 dist/index.js 逐字节相同、与 0.4.5 包内 bundle 不同（确实带 012 全部新动作）。
- **active:{"uuid":"0"} 归一化**：`PLACEHOLDER_DOC_UUIDS={'0'}`（多窗口无焦点时宿主的占位读数，实测 2026-09-21）；在 `activeDocument()` 出口统一拦截——**直读与回退两条路径都拦**，返回 null + 原始读数进 problems（doc.list 即 notes）。放在两条读取路径的唯一共享点是判定：doc.list 与 document.current 对同一事实不许分歧。+4 测试（占位/正常/回退/双读者同口径）；变异 M1（关直读判据）M2（关回退判据）CAUGHT，还原逐字节一致。
- **self_update 恢复焦点：判定不做**（任务书授权降级），bridge.md §8 落设计说明三条理由：① activateDocument 只切 tab 层、sch 上下文跨工程不跟随 ⇒ "恢复"是半真，**看得见的漂移好过看起来完整的恢复**；② 无 editor-ready 信号（register 回调不可靠），只能定时猜——正是本文档反复记录的静默失败形态；③ tab id 每次加载重算，reload 后原页甚至可能没恢复出来。替代指引：doctor 绿后 `doc.list` 看焦点 → `doc.focus`/`doc.open` 切回 → 写前复查。
- **bridge.md 11 处陈旧修正**：§4 导语（doc.delete_page 已存在）、document.current/doc.list 返回形状、DISCONNECTED 错误码补行、bundle 大小 ~164kB、§10 item 4（012 写动作已加）、§12 总计 1132/266、§13 产物名与测试数等；核对过仍准确的（39 动作表、§12 分节计数、"client=0.4.1"行）未动，未改文风。
- **连带修红灯**：`test_doctor.py` 把探针 connector 版本写死 0.4.5，版本一升即红——改为从仓库读 `_repo_connector_version()`（绿灯不能写死，注释说明）。
- **遗留登记**：① `cli.py` doctor 的 "uuid=0" 措辞与 `test_doctor.py` 对应用例前提已过期（connector 不再吐该形状；doctor 输出恰好不变故无红灯）——下批对齐；② §5 错误码表可补 PAGE_MISMATCH/NOT_FOUND；③ `getting-started.md:119` 样例输出写 0.4.5、`PROGRESS.md:14` 旧版本号（后者归属待岳裁）；④ §4 导语 "Two tests" 措辞（文件内实为 3 个 test 函数）未动。

## 真机验证积压（编辑器扩展自 2026-09-21 ~13:20 未重连；重连后按此顺序，先重启 daemon 再 update-connector）

1. **不挑工程先做**：§九 doctor 真机首跑（七项是否全绿、5 抽查方法在 3.2.186 是否 function、generateIndicatorMarkers 是 [beta]）；§七 SS34 / FRC0805J471 各跑一次（searchByProperties 是否存在、otherProperty 键名）。
2. **§五 多项目**：双工程打开（test + test2）→ doc.list 的 projects[] 枚举/focused 标记；doc.focus 切换；非焦点工程页只读性；`dmt_Project.openProject` 行为实测（typeof=function 已证，行为未知；其余激活类 API 全 undefined；activateDocument 只切 tab 层）。
3. **§八 review.mark**（岳指定工程，R1–R3）：毕设板工程审查 → mark → 截图落盘（关键未知数：宿主是否接受矩形/可见性/单位；zoomToRegion 形参顺序；clear 生效）→ 故意错 pageUuid 验 PAGE_MISMATCH 且画布无变化 → 焦点切 PCB 应 CONNECTOR_ERROR。
4. **§六 export.fab**（验收工程岳指定）：**最大风险=BOM 15 列宿主接受度**（改 `FAB_BOM_COLUMNS` 一处）；gerber 是否真为 zip；大板 base64 是否逼近 daemon 32MiB 帧上限。
5. **上手文档**：按同事视角走一遍六步 + 补 6 张截图（文档与真机不符时以真机为准改文档）。

## 交卷记录 · 第四批补充（遗留①②③ + getting-started 路径修正；Kimi 复验通过，2026-09-21）

**执行**：DeepSeek（agent-10 resume ×2）。**复验（Kimi 亲跑）**：pytest **1134**（+2：1 旧用例换 3 个）/ connector **266** / tsc 干净；抽 diff 通过。

- **① doctor uuid=0 措辞对齐**：`cli.py` project 检查改三分支——正常 uuid 原样；占位读数（旧 connector 直给 `uuid:"0"`，或 0.4.6 归一化后 notes 带原始读数）→"宿主报占位读数 uuid=0：没有焦点文档，多窗口下常见"；纯 `active:null` →"编辑器里没有焦点文档"。保留 `uuid=="0"` 判据是刻意的（doctor 可能面对 <0.4.6 的旧 build）。测试 1 换 3：归一化形状 / 旧 connector 形状 / 纯无焦点（且不得出现 uuid=0 字样）；四种形状真函数冒烟，正常形状输出逐字不变。
- **② bridge.md §5 补 PAGE_MISMATCH / NOT_FOUND 两行**（触发点已核对实现：guardPage/guardPcb/export.fab 板守卫；doc.focus/modify_primitive/delete_page/lib.recommend ref 路径）。
- **③ getting-started.md**：doctor 样例 0.4.5→0.4.6（其余字段逐条对过实现均一致）；**:45 产物路径 `connector/dist/` → `connector/` 根目录**（package.mjs:131 实测，非开发者照旧文案会扑空；同文件无其他 dist/ 误导，bridge.md 的 dist/ 提法指包内 bundle 均正确）。

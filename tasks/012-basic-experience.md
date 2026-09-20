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

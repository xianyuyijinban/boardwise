# 立创 EDA Pro 扩展 API 能力矩阵（2026-09-20 摸底）

来源：`@jlceda/pro-api-types` **v0.4.25**（`connector/node_modules/`，19437 行类型声明，官方随编辑器发布）。
方法：脚本枚举全部顶层 API 类与公开方法（接口数据类 `I*` 不计）。
规模：**96 个 API 类、788 个方法**。编辑器实测版本 3.2.186。

> 再生成：`.tmp` 脚本已删；需要时按 `tools/api_names.py` 同款思路从 `index.d.ts` 重新枚举。
> 注意 `ADD since v3.2.x` 标注：类型包声明 ≠ 宿主实现（`getPngFile` 声明于 3.2.183，宿主实测 NOT_IMPLEMENTED），新动作落地前必须真机 probe。

## 一、按域全景

| 域 | 类数 | 关键能力 |
|---|---|---|
| SCH_* 原理图 | 21 | 全部图元 CRUD（Component/Wire/Pin/Text/Arc/Circle/Rect/Polygon/Bus/Attribute）、**NetLabel 创建**、Net 查询、**Netlist 读写**、**DRC**、BOM/网表/仿真网表导出、事件监听、仿真引擎 pushData |
| PCB_*  PCB | 25 | 全部图元 CRUD（Line/Arc/Via/Pad/Pour/Fill/Region/Component/String/Dimension/Image/Polyline）、**DRC + 规则配置全套**（NetClass/差分对/等长组/PadPair）、层与叠层管理、**importChanges（ECO）**、autoRouting/autoLayout、Gerber/BOM/坐标/3D/Altium 导出、事件（含**实时 DRC 结果事件**、cross-probe） |
| DMT_* 文档管理 | 11 | 工程/板/原理图/面板 CRUD、页管理（建/删/改名/重排/标题栏）、焦点与分屏、zoom 系列、**generateIndicatorMarkers（画布标注）** |
| LIB_* 库 | 10 | Device/Symbol/Footprint/3DModel/Cbb/SimulationModel 全套 CRUD + search + **searchByProperties** + getByLcscIds，分类树，库列表 |
| SYS_* 系统 | 27 | 对话框/IFrame/消息总线/WebSocket、文件系统（读写/列目录/项目路径）、**SYS_Tool 三方比较（网表/原理图/PCB）**、单位换算、字体、快捷键、存储、多语言 |
| PNL_* 面板 | 1 | save |

## 二、boardwise 现状对照（19 个动作）

已有：`doc.list/open/rename`、`sch.geometry/readback/component_pins/netlist`、`sch.place_{component,wire,netlabel,netport,power,text}`、`sch.set_component_attribute`、`pcb.readback`、`lib.{device,symbol,footprint}.{search,get}` 族、`export.{render,screenshot}`、`sys.{probe,self_update}`。

**缺口（按日常画板操作频度排序）**：

| 缺口 | API 依据 | 影响 |
|---|---|---|
| **删除** | 每类图元都有 `delete` | 010c 被咬三次；AI 改板的基本动作 |
| **修改/移动/旋转/改几何** | 每类图元都有 `modify` | 现在只能"删了重放"，且没有删 |
| **审查结果回显画布** | `generateIndicatorMarkers` + `zoomToRegion` | M1 审出的问题只能看报告，不能在编辑器里亮起——**体验杀手锏** |
| **编辑器 DRC 并入审查** | `SCH_Drc.check` / `PCB_Drc.check` | 第一道检查应该是编辑器自己的，我们补语义级 |
| **ECO（原理图→PCB 同步）** | `PCB_Document.importChanges` | 改完原理图无法同步 PCB，工作流断 |
| **页管理** | `dmt_Schematic.createSchematicPage/deleteSchematicPage/reorder` | AI 只能往现有页画 |
| **PCB 侧写** | `PCB_Primitive*` 全套 CRUD | PCB 只读，不能改走线/铺铜 |
| **环境自查** | `sys.probe` 已有，缺打包 | 新用户不知道装没装对 |
| 事件订阅（边画边审） | `SCH_Event`/`PCB_Event` | 实时审查，P2 |
| 仿真通路 | `getSimulationNetlistFile` + `SCH_SimulationEngine.pushData` | 岳提过"后面要仿真"，P2 |
| 库建设 | `LIB_*` CRUD | AI 建库，P2 |

## 三、012v2「基础体验包」候选（待 oracle 裁切片）

1. `sch.delete_primitives`（原 012 内容，按 ID、pageUuid 守卫、诚实部分结果）
2. `sch.modify_primitive` / `pcb.delete_primitives` / `pcb.modify_primitive`（按 ID 归类派发）
3. `review.mark`——M1 审查结果经 `generateIndicatorMarkers` 画回编辑器 + `zoomTo` 逐条跳转
4. `sch.drc`——编辑器 DRC 结果并入 review 报告（标记来源，与自有规则分列）
5. `boardwise doctor`——环境自查（daemon 活？扩展连？版本对？编辑器版本够？）+ 上手文档
6. 页管理（建页/删页/改名）

P1（内测后）：ECO importChanges、PCB 侧写、事件订阅实时审、仿真通路、库建设。

## 五、岳 2026-09-20 新增两个需求的 API 依据（已查证）

### 5.1 多项目感知（"AI 看到所有打开的项目并自主选择目标"）

- 现状：`doc.list` 以**焦点工程**为中心（`dmt_Project.getCurrentProjectInfo` + `getSplitScreenTree` + `getAllSchematicsInfo/getAllPcbsInfo`）。
- API 依据：`dmt_Project.getAllProjectsUuid` / `getProjectInfo` / `openProject`；`dmt_EditorControl.getSplitScreenTree` / `activateDocument`。
- **架构天然适配**：boardwise 全部写动作带 pageUuid 守卫（010 焦点漂移翻车后立的设计）——AI 先枚举再按 uuid 选目标，不依赖焦点。缺的只是"枚举所有打开的工程"这一层。
- 待真机 probe：多开工程时 `getSplitScreenTree` 是否跨工程列 tab；`getCurrentProjectInfo` 之外的工程如何取 info（`getProjectInfo(uuid)` 应行）。

### 5.2 打板/SMT 文件导出（捷配等非立创厂商）

- API 依据（`PCB_ManufactureData`，全部返回 `File`，官方示例配套 `sys_FileSystem.saveFile` 落盘）：
  - `getGerberFile(fileName, colorSilkscreen, unit, digitalFormat, layers, objects)`——单位/数字格式（4:5、英制 3:6）/钻孔表/层与对象全可控
  - `getPickAndPlaceFile(fileName, 'xlsx'|'csv', unit)`——SMT 坐标
  - `getBomFile(fileName, 'xlsx'|'csv', template, filterOptions, statistics, property, columns)`——**自定义模板与列**，非立创厂商格式的关键
    - 【2026-09-21 真机更正③（013 批②）】**`filterOptions` 是"排除"规则，不是"保留"**：`includeValue` 是"该属性等于此值就把这一行删掉"。宿主 `api.js` 的 `mne`/`gne` 把它写进 `filterRules`（并先把取值非 `'yes'` 的归一到 `'no'`），`pro-sch` 的 BOM 生成 `verify` 一旦命中就丢行。于是类型包示例的 `{property:'Add into BOM', includeValue:'yes'}` 会删光所有"加入BOM"的器件——122 器件的板子只剩 152 B 表头（15 个列定义照样被逐字接受，所以"表头全接受"并不证明过滤对）。改发 `'no'`（宿主机自带默认规则的取值，`checked:true`）后 68 行、122 个位号齐全。见 `outputs/013_p3_evidence/013_p3_bom_filter_root.txt`、`outputs/013_fab_bishe2/`
    - 【2026-09-21 真机更正④（013 批②）】**三件套的文件名不是同一套规则**：gerber/坐标是 `new File([data], t || c.fileName)`——原样回传我们传的 `fileName`（故 preset 名必须自带 `.zip`/`.csv`，否则落盘无扩展名）；BOM 是宿主自己拼 `fileName + '.' + fileType`（故 preset 的 BOM 名**不能**带 `.csv`，否则得到 `fab_bom.csv.csv`）
    - 【2026-09-21 真机更正⑤（013 批②，已修）】**`statistics` 与 `property` 必须**不重不漏地合成列集**：宿主 `api.js` 用 `statistics + property` 建表且**不去重**，同一个列名给两处就会出两列 —— preset 原先把 `No.`/`Quantity` 两处都给，于是 15 列的 preset 出了 **17 列表头**（`序号`…`Number`、`数量`…`Quantity`）。而两个参数**不可互换**：只有 `statistics` 的条目会过 `hne`（把 `No.` 改写成宿主 BOM 引擎编号用的 `Number` 列），`property` 的条目永远不会被列检查匹配到，所以**不能反过来删掉 statistics**——`getBomFile` 的列检查是 `p.includes(m.property) … else return`，一旦某列两个列表都没有，整次调用返回 `undefined`（**一个 BOM 文件都不给**）。现修法：统计两列只走 `statistics`，其余 13 列由 `FAB_BOM_COLUMNS` 派生成 `property`，二者并集 = 15 列；真机表头逐字 15 列。见 `outputs/013_fab_bishe3/`
  - 补充：`getTestPointFile`（飞针）、`getPdfFile`、`getDxfFile`、`get3DFile`
- 候选动作 `export.fab`：一次出"Gerber + 坐标 + BOM"三件套到指定目录；厂商差异通过 BOM template/columns 参数承载，后续攒厂商预设（捷配等）。
- 待真机 probe：**File 对象的落盘路径形态已实测（见更正④）**；BOM 模板语法仍待 probe（`getBomTemplates` 一侧）。

两项加入 012v2 候选（编号 7/8）。

### 5.3 器件选型推荐（岳 2026-09-20 场景：不知名器件匹配不上 / AD 导入后重选）

- API 依据（`LIB_Device`，全部实测可用——011b 的 CH340G 身份就是这条桥查到的）：
  - `search(key, libraryUuid?, classification?, ...)`：关键字搜，默认**系统库**（即编辑器放器件时检索的立创库）
  - **`searchByProperties({name, value, symbolName, footprintName, supplierFootprint, supplierId, partNumber, partCode}, ...)`**：八字段组合搜——`partNumber`=MPN、`partCode`=LCSC 编号，声明里写作两条精确通路
    - 【2026-09-21 真机更正①】这两条精确通路在 3.2.186 上**不生效**：方法存在且可调用，但 partNumber / partCode / value 四种属性集全部 0 命中、无 error。见 `outputs/013_f4_searchbyprops.txt`
    - 【2026-09-21 真机更正②（F4 矩阵，定论）】"空转"的说法**只对部分键成立**，方法本身可用：`{supplierId:"C8678"}` 精确命中 1 条（伪造号 `C99999999999` 命中 0 ⇒ 真被当过滤条件），`partNumber`/`partCode`/`value` 被执行但无索引（返回 `[]`，而"被忽略的键"会返回整库默认页 10 条 ⇒ 0 不可能是忽略），`name`/`footprintName` 被忽略（返回默认页，与未知键同形）。实参形状无关（1 参 / 6 参、带不带 libraryUuid 结果不变），故与 `getPngFile`/`createNetLabel` **不是同一族**：是键选择错，不是方法空转。`lib.recommend` 的 exact 层因此改发 `{supplierId}`；见 `outputs/013_f4_probes_real.json`、`docs/bridge.md` §12
  - `getByLcscIds(lcscIds, ...)`：LCSC 编号直查，支持批量
  - 返回 `ILIB_DeviceSearchItem`：uuid/name/符号/封装/3D/图片/description/otherProperty（`otherProperty` 里带 LCSC Part Name、Manufacturer Part、**JLCPCB Part Class（Basic/Extended——SMT 换料费维度）**、Datasheet 链接，011b 在 META 里实测到这些键）
- 候选动作 `lib.recommend`：输入位号/MPN/参数描述 → 多策略搜（MPN 精确 → 参数组合 → 关键字）→ TopN 候选（封装匹配 + Basic 件优先 + datasheet 链接）→ oracle 确认 → `set_component_attribute` 落座。
- **诚实限制**：类型包中搜索返回**无库存/价格字段**——首版推荐不带库存价格，标注"以商城实时为准"；库存维度要商城侧接口，属后续。
- AD 导入场景配套：`SYS_FormatConversion.convertAltiumDesignerLibrariesToEasyEDA*`（库转换）存在；原理图导入后的器件重选走 `lib.recommend` 逐位号映射。

加入 012v2 候选（编号 9）。

## 四、国庆内测版（10-01）倒排

剩余约 10 天。M1 收官（014 + 一次性提交）不阻塞体验包——014 是半小时级标注活。
体验包 1–5 是内测版的躯干；6 看余量。

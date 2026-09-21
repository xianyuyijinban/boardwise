# 013 — 012 真机验证轮（内测版 0.4.6 的真机验收）

> 2026-09-21 立项。012（`e2bb78c`）提交时编辑器扩展离线，真机验证积压整体转入本任务书。
> 执行契约沿用 `tasks/012-basic-experience.md` 的 R1–R3 铁律与 probe 纪律。
> 环境基线（主代理已备）：daemon = 012 代码（新动作+ping.version 已加载）；
> 编辑器内 connector = **0.4.6**（hello 实测 `connector=0.4.6`）；
> 焦点工程 `/test`（test.eprj2）；`active:null` + notes 占位读数——uuid="0" 归一化真机已生效（批前实测）。

## 批次划分

- **批①（本批，不挑工程、只读为主）**：§九 doctor 首跑；§七 lib.recommend query 路径；§五 projects[]/focused/active 实测；`dmt_Project.openProject` 行为实测。
- **批②（待岳指定/开工程）**：§八 review.mark（毕设板工程）；§六 export.fab（验收工程，BOM 15 列风险）；上手文档截图 ×6；§五 双工程段（doc.focus 切换）。

## 批① 验收判据

1. `boardwise doctor` 真机首跑：七项逐项记录；5 个抽查方法（含 [beta] 的 generateIndicatorMarkers）在 3.2.186 的 typeof 必须落证据；任何 FAIL 如实记录并归因，**不许现场改代码修**。
2. `lib.recommend` query 路径：SS34 与 FRC0805J471 各跑一次——逐层 called/hitCount 落证据；`searchByProperties` 在 3.2.186 是否存在（called:false 还是抛错）；返回候选的字段形状（otherProperty 键名、layer 字段）。
3. §五：projects[] 枚举与 focused 标记实测（批前主代理已测一次，复核并正式落证据）；`active:null`+notes 的归一化形状复核。
4. `dmt_Project.openProject` 行为实测：对 test2（或批① 时编辑器内实际可用的第二工程；若无第二工程则如实记"无法实测"）调用，记录：返回形状、焦点是否切换、doc.list 前后对比。**只许打开，不许对工程内容做任何写操作**。

## 硬边界

- 本批**禁止一切工程内容写操作**：delete/modify/place/mark/fab 全不许碰；唯一允许改变编辑器状态的动作是 openProject 与 doc.focus（焦点类）。
- 全场 R1：任何动作前 doc.list 焦点工程名核对；R2/R3 照章。
- 证据落 `outputs/013_*`；交卷报告写明：每项判据的过/不过、真机新事实（与离线预期不符的）、需要批② 或修复轮跟进的事项。

## 交卷记录 · 批①（只读验证；Kimi 复验通过，2026-09-21）

**执行**：DeepSeek（agent-11）。**复验（Kimi 亲看）**：doctor JSON `ok:true` 七项全 PASS；`013_findings.txt` 逐项核对；R1 快照 10 次逐字节一致（焦点始终 `/test`）；工作区除本任务书外零改动；动作时间线 16 行无重复。

**判据结果**：
1. **doctor 真机首跑 7/7 绿**（exit 0）：daemon 可达、connector 已注册（指纹 962bf45e）、5/5 抽查方法 function（含 generateIndicatorMarkers；"[beta]"系上游说法，本地文档无此标注）、编辑器 3.2.186≥3.2.183、daemon 0.1.0==本机、connector 0.4.6==仓库、焦点工程可读（活动文档"无（占位 uuid=0）"——归一化措辞真机生效）。
2. **lib.recommend**：SS34 / FRC0805J471 的 exact 与 properties 层均 called=true **hit 0**，keyword 层各 hit 5/2；附加判别（C8678 / SS34_C8678）证明 `searchByProperties` **存在可调用但一个属性集都匹配不到**（返回空数组非抛错）——exact/properties 两层实质空转，**keyword 层是唯一出货的层**。候选 17 键、6 个读取键全部以首选拼写原样存在；`hitCount:5` 是页大小截断值非匹配数（宿主默认页 10）。**残留不可判**：无法区分"宿主忽略键"与"实参错位"（F4）。
3. **§五 单工程段**：projects[] 枚举/focused/notes 全形状与离线预期一致；`active:null` 两读者（doc.list / document.current）同口径；**但 `document.current.project={}`**——documentCurrent 走 snapshot() 只读 getState_* 原型成员，工程信息是普通属性 ⇒ F3 修复项（改 plainGet 或兜底）。
4. **openProject 无法实测（如实记录）**：桥无该动作入口（UNKNOWN_ACTION 出自 daemon，帧未到编辑器，零副作用）；typeof 表与 0.4.5 读数逐字一致（openProject=function，openProjectByUuid/setCurrentProject/activateProject=undefined）；projects[] 仅 /test 一项。**Kimi 裁决：不加 project.open 动作**（doc.open 是 tab 级不是工程级；为验证造 API 不值，且批② 本就需要岳开工程）。

**跟进清单**：
- F1/F2（§五 双工程段 + focused 翻转 + doc.focus 真机）→ 批②，等岳开 test2。
- **F3** document.current.project={} 口径修复 → 修复轮（小改 + mock 测试）。
- **F4** searchByProperties 参数语义 → 修复轮（需要可换实参的探针通道或类型包深挖；**影响：lib.recommend 的 exact/properties 降级层在 3.2.186 上是死重，keyword 层扛全部**——内测用户可感知：选型推荐能用，但精确匹配层不生效）。
- **F5** doctor "5 页原理图"计数含容器节点（实 4 页）→ 修复轮纯文案对齐 schematicPages。
- 批②：§八 review.mark（毕设板工程）、§六 export.fab（验收工程，BOM 15 列风险）、截图 ×6、§五 双工程段——**等岳开工程**。

**证据**（outputs/，19 份）：013_findings.txt（161 行事实记录）、013_doctor{,.json,_stdout.txt}、013_sys_probe_doctor.json、013_lib_recommend_{SS34,FRC0805J471,C8678,SS34_C8678}.json、013_lib_device_search_SS34.json、013_doclist_{before,after,r1a…r1i}.json、013_document_current.json、013_probe_dmt_project.json、013_openproject_attempt.json、013_action_timeline.txt。

## 交卷记录 · 修复轮（F3+F5+F4 调查；Kimi 复验通过，2026-09-21）

**执行**：DeepSeek（agent-12，两批：F3/F5 修复 + F4 调查 → 版本升级/文档口径/打包）。
**复验（Kimi 亲跑）**：pytest **1136**、connector `npm test` **268**、`npx tsc --noEmit` 干净；抽 diff 通过；
两处守卫变异（F3 去掉 projectIdentity 合并 → connector 用例红；F5 计数改回列表长度 → pytest 用例红）
还原后 sha256 与改前一致；`.eext` 独立 zipfile 校验见下。禁止 git / 禁止真机，全场未碰。

### F3 — `document.current.project` 口径修复（connector）

`connector/src/actions.ts` 新增共享读 `identityField`/`projectIdentity`（普通属性优先、`getState_*` 兜底，
键名用 `doc.list` 的 `projectUuid`/`name`/`friendlyName`），`document.current` 的 project 盒子改由
`readProject` 组装 = `snapshot()` **并上** `projectIdentity`，`doc.list` 的 `projectRows` 也改走同一段读 ——
两读者对「当前工程」不可能再各说一套；理由（真机 3.2.186 上工程信息是普通属性对象、`snapshot` 只走
`getState_*` 原型成员故得 `{}`；而同一动作的 pcb/schematicPage 盒子该宿主上走 `getState_*`，所以只有
project 空）按 `activeDocument` 的注释风格写进代码。
**测试**：`connector/tests/actions012.test.mjs`（真机形状：普通属性工程对象，断言 `document.current.project`
与 `doc.list.projects[focused]` 同值）、`connector/tests/actions.test.mjs`（`getState_*` 形状不被破坏）。
connector 测试 **266 → 268**。

### F5 — doctor「N 页原理图」计数口径（Python）

`src/boardwise/cli.py` 新增 `_project_counts`，doctor 的 project 行改用 `doc.list` 已算好的
`schematicPages`/`pcbs`（非数字时才回退 `projects[].schematics`/`pcbs` 的列表长度，老/畸形载荷不抛异常）；
`schematics[]` 是含容器节点 `schematic1` 的文档列表，长度不是页数。
**测试**：`tests/test_doctor.py` 新增 2 例（含容器节点时报 4 页且不得出现「5 页原理图」；旧载荷回退）。
pytest **1134 → 1136**。真数据复核（喂批① 的 `013_doclist_before.json`）：project 行现为
「焦点工程：test（ea80fff6…，**4** 页原理图 / 1 个 PCB）」，ok=True。

### F4 — `searchByProperties` 参数语义（只调查，未改行为；报告 `outputs/013_f4_searchbyprops.txt`）

1. **声明逐字关键行**（`@jlceda/pro-api-types` 0.4.25，index.d.ts:1958）：
   `public searchByProperties(properties: ILIB_DevicePropertiesForSearch, libraryUuid?: string, classification?: Array<string>, symbolType?: ELIB_SymbolType, itemsOfPage?: number, page?: number): Promise<Array<ILIB_DeviceSearchItem>>` —— 6 形参，
   `properties` 唯一必填，jsdoc 带 `@beta` 与 **ADD since EDA v4**（该行夹在 classification 与 symbolType 之间）；
   `ILIB_DevicePropertiesForSearch`（:1849-1866）8 键全可选：name/value/symbolName/footprintName/
   supplierFootprint/supplierId/partNumber/partCode —— **没有** otherProperty 那套带空格键名。
2. **实参错位被静态排除**：调用处 `actions.ts:4552-4557` 是
   `searchByProperties.call(ns, properties, undefined, undefined, undefined, 5, page)` —— 6 实参，**没有第 7 位**；
   与能出货的 keyword 层 `search.call(ns, keyword, undefined, undefined, undefined, 5, page)` 共用**同一段实参尾巴**，
   且两法声明形参表同序同量（唯一差别是第 1 位类型、第 3 位 classification 更窄）——若尾巴错位，`search` 也该坏，
   而它每次命中（5/1/2，pagesFetched=1）。另 `lib.device.search` 动作只传 1 个实参即得宿主默认 10 条，
   说明该宿主允许省略尾部。真机试过的四种属性集全在声明键内、拼写逐字一致（partNumber=SS34 / partCode=C8678 /
   value=SS34 / partNumber=SS34_C8678），"传了声明外的键"也不成立。
3. **定性：声明在、运行时空转**（与同族先例 `getPngFile`、`createNetLabel` 一列）：真机上方法 typeof=function、
   三种属性集 called=true、无 error、返回空数组，而同名 keyword 层每次都命中 —— 即 exact/properties 两层实质空转，
   keyword 层扛全部。仓内 grep：`tools/` 无任何相关探针脚本，只有 docs 与 012v2/013 的文字记录。
4. **判别方案（后续轮候选，只写不改）**：给 `lib.recommend` 加**只读、可选、封顶**的 `probes`
   参数（逐项按调用者原样传参，未给的形参不传），一次真机调用跑矩阵：`({})` / `({name:"SS34_C8678"})` /
   `({supplierId:"C8678"})` / `({partNumber:"SS34"}, "<候选实测 libraryUuid>")` / 只传 1 参 / 改 itemsOfPage=10 /
   `getByLcscIds("C8678")`；判读表见报告 §四（键有效但无索引 → 改发可用键；参数位置敏感 → 固定调用形状；
   全 0 → 如实降级/撤层；`getByLcscIds` 可用则 exact 层改挂它）。先导（5 分钟）：`sys.probe` checks 模式
   每个成员多报 `arity: fn.length`（纯信息）。

### 版本升级与打包（0.4.6 → 0.4.7）

`connector/extension.json` + `connector/package.json` 0.4.6 → **0.4.7**（两处同改；VERSION 由 build.mjs 从
package.json 注入），`npm run package` 产出 **`connector/boardwise-connector-0.4.7.eext`（40439 B）**
（沿用 0.4.6 那次的落点：connector/ 根目录）。独立校验（Python `zipfile`）：
包内 2 条目 = `extension.json` + `dist/index.js`；manifest **version=0.4.7**（与磁盘 extension.json、
package.json 一致）；包内 bundle 与磁盘 `dist/index.js` **逐字节相同**（sha256 8b855adf…，168855 B）；
与 **0.4.6 包内 bundle 不同**（e2377123…，167750 B，manifest 0.4.6），且新 bundle 含 `projectIdentity`
—— 确认真带 F3 修复。文档同步：`docs/getting-started.md` doctor 样例 0.4.6→0.4.7；
`docs/bridge.md` §13 打包行 0.4.7、`npm test` 266→268。
**未做（留裁决）**：编辑器内的热更新（`bridge update-connector`）与真机复跑 —— 本轮禁真机；
`PROGRESS.md` 的 Current baseline 段（版本/测试数/commit 号）按"锚定 e2bb78c"的语义未动，待提交时一并刷新。

### 文档口径更新（F4 结论落地）

`docs/bridge.md:429-431`（§4 散文）补一句"声明**在**也不够：3.2.186 上存在可调用但照样匹配不到，见 §12 行"；
`docs/bridge.md:1052`（§12 证据表）：把"searchByProperties 到底存不存在"的未决措辞改成实测结论（存在可调用、
四属性集全 0、无 error；声明在运行时空转，与 getPngFile/createNetLabel 同族；该宿主上 exact/properties 层不生效、
keyword 层扛全部），export.fab 的 BOM 列问题仍记为未决；`docs/api-surface-2026-09-20.md:77` 加"2026-09-21 真机更正"
小节（两条精确通路不生效）。该文件是**手写的一次性摸底报告**（文件名带日期，非生成物；其"再生成"注明脚本已删），
故只加更正、不重写。`docs/bridge.md:380`（§4 动作表行）未改：它描述契约（四层阶梯照样存在并被调用），非过时陈述。

## 工作项 · F4 实施批（2026-09-21，批② 空窗插入）

批② 阻塞于岳开工程；lib.recommend 的库查询**不挑焦点工程**，F4 判别方案在此空窗实施：

1. `lib.recommend` 加可选只读参数 `probes: [{properties, libraryUuid?, classification?, symbolType?, itemsOfPage?, page?}]`——逐项按调用者给的原样调用（保留 arguments.length 差异），回 `{args, called, hitCount, pageSize, firstKeys[], error?}`；不传时路径与现状逐字节相同；长度封顶、沿用现有超时、只读。
2. `sys.probe` checks 模式每个成员多报 `arity: fn.length`（纯信息增量）。
3. 热更后真机跑判读矩阵：`({})` / `({name:"SS34_C8678"})` / `({supplierId:"C8678"})` / `({partNumber:"SS34"}, libraryUuid)` / 单参 `({partNumber:"SS34"})` / `itemsOfPage=10` / `getByLcscIds("C8678")`。
4. 判读落地：键有效但无索引 → 改发可用键；参数位置敏感 → 固定调用形状；全 0 无 error → 与 getPngFile 同族，exact/properties 层如实降级或撤层；getByLcscIds 可用 → exact 层改挂它。
5. 边界：增量参数、默认路径零变化；不自动试错轮询；真机部分不碰任何工程内容（纯库查询）。

## 交卷记录 · F4 真机矩阵（2026-09-21）

**执行**：执行子代理（离线实现 → 热更 → 真机矩阵）。**环境**：daemon 61190（未重启），编辑器 3.2.186，
connector **0.4.7 → 0.4.8**（`bridge update-connector --yes`：`ok: 0.4.7 -> 0.4.8`，173383 B）。
每步前后 `bridge status` 均 connected（配对指纹 962bf45e）。**纯库查询，未碰任何工程内容；禁用 git。**

### 1. 版本与打包（0.4.7 → 0.4.8）

`connector/extension.json` + `connector/package.json` 0.4.8；`npm run package` → `connector/boardwise-connector-0.4.8.eext`
（41360 B，sha256 **2031916b…**）。独立 zipfile 校验：包内 2 条目 `extension.json` + `dist/index.js`；manifest
version=0.4.8（与磁盘两处一致）；包内 bundle 与磁盘 `dist/index.js` **逐字节相同**（173383 B，sha256
**4992ed877d9dae9e…**）；与 0.4.7 包内 bundle（168855 B，8b855adf…）不同，且含 `probesOnly` / `arity[member]` /
`searchByProperties probe`。`docs/getting-started.md` doctor 样例 0.4.7→0.4.8；`docs/bridge.md` §13 打包行 0.4.8。

### 2. arity 先导（新 bundle 已生效的判据）

`sys.probe --params '{"checks":{"lib_Device":["searchByProperties"]}}'` → `connector: "0.4.8"` **且带
`arity: {searchByProperties: 4}`** ⇒ 热更生效（旧 bundle 无 arity 字段）。附加对照（一次调用，只读）：

| 成员 | typeof | arity | 声明形参 |
|---|---|---|---|
| `lib_Device.searchByProperties` | function | **4** | 6 |
| `lib_Device.search` | function | **4** | 6 |
| `lib_Device.get` | function | 2 | 2 |
| `lib_Device.getByLcscIds` | function | 2 | 2（+ 可选尾参） |
| `lib_Footprint.searchByProperties` | function | 2 | 2 |
| `lib_Symbol.searchByProperties` | function | 2 | 2 |

判读：`lib_Device` 的两法**同为 4**，而 `search`（keyword 层）每次命中、`searchByProperties` 只对个别键命中
⇒ **实参个数/位置不是根因**（"宿主形参个数≠6 ⇒ 位置问题"的先导假设被对照否掉；`Function.length` 在本宿主
上对 `lib_Device` 两法都失真，与 F4 报告"只能当线索"的备注一致）。

### 3. 判读矩阵 P1–P6（`outputs/013_f4_probes_real.json`，原始 JSON）

| # | 实参（调用者原样） | 实参数 | called | hitCount | pageSize | firstKeys |
|---|---|---|---|---|---|---|
| P1 | `{}` | 1 | true | **10** | null | 16 键 |
| P2 | `{name:"SS34_C8678"}` | 1 | true | **10** | null | 16 键 |
| P3 | `{supplierId:"C8678"}` | 1 | true | **1** | null | 16 键 |
| P4 | `{partNumber:"SS34"}, "0819f05c…"` | 2 | true | **0** | null | [] |
| P5 | `{partNumber:"SS34"}` | 1 | true | **0** | null | [] |
| P6 | `{value:"SS34"}, u,u,u, 10, 1` | 6 | true | **0** | 10 | [] |

附加对照（`outputs/013_f4_probes_control.json`，为把"未识别键"与"空过滤"分开而加，非 P1–P6 之内）：

| # | 实参 | hitCount |
|---|---|---|
| C1 | `{totallyUnknownKey:"zzz"}` | **10**（默认页） |
| C2 | `{name:"THIS_NAME_CANNOT_EXIST_9f3a"}` | **10**（默认页 ⇒ `name` 与未知键同形：**被忽略**） |
| C3 | `{supplierId:"C99999999999"}` | **0**（⇒ `supplierId` **真被应用**为过滤条件） |

命中项的键形状（16，P1/P2/P3 一致）：`uuid, libraryUuid, ordinal, name, symbolName, symbolUuid, symbol,
footprintName, footprintUuid, footprint, model3DName, model3DUuid, model3D, imageUuid, description,
otherProperty`（`otherProperty` 在 ⇒ `recommendCandidate` 的映射面可用）。空属性与未识别键返回的是**整库默认页
10 条**（与批①"宿主默认页 10"一致）。

### 4. 判读结论

1. **宿主认这份 properties 对象**（不是"方法空转"）：`{supplierId:"C8678"}` 恰好命中 1 条 —— 即 SS34 那个器件
   （LCSC 号直查），且伪造号 `C99999999999` 命中 0 ⇒ 该键被真正当作过滤条件执行。
2. **`partNumber` / `value` 被应用但无该值的索引**：两者都返回 0，而"未识别键"返回默认页 10 ⇒ 0 不可能是"键被
   忽略"，只能是"过滤执行了、库里没有"。批① exact 层发 `{partNumber, partCode}`、properties 层发
   `{value, footprintName}`，两个键都落在这一类 ⇒ **恒 0 的根因是键选择，不是方法不工作**。
3. **`name` 被忽略**（C2 与 C1 同形）——P2 的 10 是伪命中，不构成"name 可用"。
4. **尾参无关**：P5（1 实参）与 P6（6 实参、`itemsOfPage=10`）同为 0；P4 多加 `libraryUuid` 仍 0 ⇒
   "参数位置/个数敏感"**排除**（与 §2 的 arity 对照一致）。
5. **结论定性**：`lib_Device.searchByProperties` 在 3.2.186 上**可用**，但该库只对 `supplierId`（LCSC 号）一类
   键有索引 —— 与 `getPngFile`（运行时缺席）、`createNetLabel`（永不 settle）**不是同一族**。
6. 判读表对应行 = **"P3 命中、P4 不命中 → 键有效但字段无索引 → 改发可用键"**（P2 需按 3 修正为伪命中）。

### 5. 处置：停手待裁（按批前约定"若有命中即停手报告"）

- 本轮**未改任何代码行为**、**未改 `docs/bridge.md` §12 的定论措辞**、未动 exact/properties 层的调用形状。
- 候选改法（供主代理裁决）：exact 层改发 **`{supplierId: <LCSC 号>}`**（`target.partCode` 已是该号）；
  properties 层待定（`value` 无索引，`footprintName` 本批未测）。
- **风险提示（必须一并处理）**：`docs/bridge.md:1052`（§12 证据行）与 §4 散文（:429-433）现在写着
  "matches nothing / 声明在运行时空转 / 与 getPngFile 同族"，本矩阵已证伪（只对 `partNumber`/`partCode`/
  `value`/`name` 成立，`supplierId` 可用）——口径需与改法一并重写，否则文档继续误导。
- P7（`getByLcscIds("C8678")`）本批不做（probes 通道只调 `searchByProperties`，只读路径无 `getByLcscIds` 入口）。

### 6. 证据

`outputs/013_f4_probes_real.json`（P1–P6 原始帧）、`013_f4_probes_control.json`（C1–C3 对照）、
`013_f4_arity_probe.txt`（arity 先导，connector 0.4.8）、`013_f4_arity_control.txt`（六成员 arity 对照，
含 topLevel 92 个命名空间清单）、`013_f4_probes_mock.txt`（离线实现的 mock 形状示例，**非真机**）。

## 交卷记录 · F4 落地（exact 层改键）（2026-09-21）

**执行**：执行子代理。**依据**：主代理对矩阵的裁决——"P3 命中、P4 不 → 键有效但字段无索引 → 改发
可用键"。**环境**：daemon 61190（未重启）、编辑器 3.2.186、connector **0.4.8 → 0.4.9**。
除库查询外未碰工程内容；禁用 git；每步前后 `bridge status` 均 connected。

### 1. 补测 footprintName（`outputs/013_f4_footprint_probe.json`）

| # | 实参 | hitCount | 判读 |
|---|---|---|---|
| F1 | `{footprintName:"SMA(DO-214AC)"}` | **10** | 默认页 ⇒ **被忽略** |
| F2 | `{footprintName:"0805"}` | **10** | 默认页 ⇒ **被忽略** |

→ properties 层按裁决**维持现构造不动**（`{value, footprintName}`），并在 `notes` 与代码注释里注明
"3.2.186 上 value 无索引、footprintName 被忽略，此层不可能命中"。

### 2. 代码改动（`connector/src/actions.ts`）

- **exact 层**：`{partNumber, partCode}` → **`{supplierId: target.partCode}`**；无 partCode 时该层
  `called:false`，原因写明"no partCode (LCSC code) is known for this part — and supplierId, the key this
  host indexes, has nothing to carry (measured 2026-09-21)"。**不再落无索引空调用。**
- **properties 层**：构造不变；新增 `deadRungs` 通道——该层**跑过且 0 命中**时往 `notes` 追加一条
  说明（"cannot match on this host — value is applied but has no index and footprintName is ignored
  outright…"），使"这一层永远不可能命中"不会被读成"库里没有这个器件"。
- 阶梯文档注释、`probes` 段注释同步改口径。
- **mock 测试**：记录器断言新属性集（exact `{supplierId:"C8678"}`）；新增 properties 死层 note 断言；
  查询路径测试改为"裸 MPN 不进 exact 层、exact 记 called:false + 原因"；`GOLDEN_REF_ANSWER` **有意重录**
  （注释写明"Re-recorded 2026-09-21 (F4 matrix, deliberate)"）。connector 测试 **275 → 275**（改 6 例、无新增）。

### 3. 文档证伪段重写

- `docs/bridge.md` §12 证据行（原"matches nothing / 与 getPngFile 同族"）→ 真机定论：方法可用但只按
  **索引键**过滤（`supplierId` 精确；`partNumber`/`partCode`/`value` 被应用而无索引；`name`/`footprintName`
  被忽略返回默认页；实参个数/位置无关，arity `search`=`searchByProperties`=4）。
- `docs/bridge.md` §4 散文（:429-437）与 §4 动作表行（:380）：exact 层改发 `{supplierId}` 并注明理由。
- `docs/api-surface-2026-09-20.md:78-79`：把"空转"更正为更正①（原未决）+ 更正②（F4 定论）。
- `src/boardwise/bridge/protocol.py`：lib.recommend 的 summary / params_schema 同步（含"裸 MPN 只进
  keyword 层"的操作提示）。

### 4. 三线 + 变异

- pytest **1136 passed**；connector `npm test` **275 pass / 0 fail**；`npx tsc --noEmit` 干净。
- 变异①（exact 键改回 `partNumber`）→ **6 红**；还原 `sha256 e86bc006…` 字节一致。
- 变异②（删 properties 死层 `deadRungs` 注入）→ **2 红**（阶梯用例子 + 逐字节基线）；还原字节一致。

### 5. 热更 + 真机复核（0.4.9）

- 打包：`boardwise-connector-0.4.9.eext`（41688 B）；独立 zipfile 校验：2 条目、manifest **0.4.9**
  （与 extension.json / package.json 一致）、包内 bundle 与磁盘 `dist/index.js` 逐字节相同
  （174274 B，sha256 **3f9e16e2…**）、与 0.4.8 bundle（4992ed87…）不同且含 `supplierId` / 死层文案 / `0.4.9`。
- `bridge update-connector --yes` → `ok: 0.4.8 -> 0.4.9`；`sys.probe` 复核 `connector:"0.4.9"` + `arity`
  （`searchByProperties`=4）⇒ 新构建生效。
- **`--action lib.recommend --params '{"query":"SS34"}'`（`outputs/013_f4_exact_real.json`）**：
  **exact 层 `called:false`**（裸 MPN 无 LCSC 号 ⇒ 无 `supplierId` 可发，按新语义不落空调用）
  → properties 0 → keyword **5 条**（首位即 `SS34_C8678`）。**与裁决文本里"exact 层应命中"的预期不符，
  原因是设计使然**：exact 层现在只认 LCSC 号，而 `query:"SS34"` 不是 LCSC 号。
- **补跑真正走 supplierId 通路的一发（`outputs/013_f4_exact_real_c8678.json`）**：
  `--action lib.recommend --params '{"query":"C8678"}'` → **exact 层 `{supplierId:"C8678"}` hitCount 1**，
  候选整行可用：`name SS34_C8678 / mpn SS34 / manufacturer MDD(辰达半导体) / supplierFootprint
  SMA(DO-214AC) / partClass Basic Part(rank 0) / datasheet 链接 / description / deviceUuid 009407ea… /
  symbolUuid / footprintUuid`，keyword 层因此未被调用（"an earlier rung matched"）。**F4 落地真机验证通过。**
- doctor 收尾 **7/7 PASS**（`outputs/013_f4_doctor_049.txt`，其中 connector 0.4.9 == 仓库）。

### 6. 遗留（需主代理裁决/跟进）

1. **`query` 路径的 exact 层不再触发**：裸 MPN 查询没有 LCSC 号，按裁决"没有 partCode 即不落空调用"，
   该层记 `called:false`。若希望 MPN 查询仍走精确层，需要"按宿主观察到的可用键依次尝试"的策略
   （当前只对 3.2.186 这台标定，`partNumber` 无索引，故本轮不引入）。
2. **supplierId 命中项的 `libraryUuid` 为空**：同一器件（`deviceUuid 009407ea…`）在 keyword 层带回
   `libraryUuid=0819f05c…`，在 exact 层为 `''`（`outputs/013_f4_exact_real*.json` 对照）。候选行其余字段齐全，
   但 `sch.place_component` 的"deviceUuid + libraryUuid"提示里少一个 uuid——可选跟进：命中后补一发
   `lib.device.get(uuid)` 取回 libraryUuid。
3. P7（`getByLcscIds`）仍未做（probes 通道只调 `searchByProperties`；只读路径无该入口）。

## Kimi 复验落笔 · F4 实施+落地（2026-09-21）

亲跑三线（每次均在子代理最终改动之后）：pytest **1136** / connector **275** / tsc 干净（两轮亲跑一致）。抽 diff：probes 分支（undefined 补位防实参错位、argCount 记录器钉 [1,2,6,1]、默认路径 GOLDEN_REF_ANSWER 逐字节钉住）、exact 层改键（注释含矩阵证据原文）——通过。变异累计 6 次全 CAUGHT（两路混跑 / 删 arity / arity 置空 / exact 键改回 / 删 deadRunes 通道），还原均字节一致。真机证据亲看：P1–P6 矩阵、C1–C3 对照、arity 先导（lib_Device 两法同报 4，位置假设排除）、`C8678` exact 命中完整候选、热更后 doctor 7/7（0.4.9）。GOLDEN_REF_ANSWER 基线重录为**有意变更**（测试注释已注明 2026-09-21 F4 矩阵改键），批准。

**遗留登记（不阻塞 013 提交）**：① query 路径裸 MPN 无 exact 层（裸 MPN 只进 keyword，设计现实）；② supplierId 命中项 libraryUuid 为空（keyword 层同器件有；可选跟进 lib.device.get 补发）；③ P7 getByLcscIds 只读无入口（未做）。

## 交卷记录 · 批②（真机验收 §五/§八/§六 + 三项修复；Kimi 复验通过，2026-09-21）

**执行**：DeepSeek（agent-14 验收、agent-15 修复）。**复验（Kimi）**：三线亲跑 pytest **1136** / connector **279** / tsc 干净；抽 diff（BOM filterOptions 根因注释、clear 幂等口径、FAB_BOM_OVERRIDE_KEYS 设计说明）通过；**打标 PNG 亲眼看**（`013_mark_P1.png` 标记态 vs `013_mark_cleared.png` 清除态：相同缩略视图下中部亮红空心矩形出现/消失对比可见，叠加子代理像素测量纯红 186→548、最长竖红线段 7→42px——**可见性确证**）；`review.mark {clear:true}` 在 active:null 下亲测 `cleared:true`（幂等新口径真机生效）。

**Kimi 裁决**：agent-14 申报的两处超字面——doc.open 前置（risk=read、自述不改工程内容、无它 §八/§六 不可做）**批准**；焦点漂移申报（非子代理造成）**采信**（根因后由 agent-15 挖明，见下）。

### §五 双工程段（定性结论与预期不同，如实）

`projects[]` 20+ 次采样**恒为 1 项**（焦点工程，opened:"yes"/documents:"full"），非焦点分支（opened:"unknown"/documents:"brief"）在该宿主**从未出现**——`getAllProjectsUuid()` 只报当前工程。doc.focus 试切 test2 → NOT_FOUND（当时连工程页标签都没有；不能据此判 test2 已关）。**多工程枚举路径在 3.2.186 上不可用**；`document.current.tabs[]` 是更干净的标签树读法（新读数）。

### §八 review.mark（毕设板，全链）

夹具审查 15 条 WARN → R1 通过（焦点逐字"毕设FOC驱动板"）→ schematic1/P1（9/15 refs 命中，171 器件）→ mark **9/9 accepted**（unresolved 6 逐条给因）→ clear `cleared:true`；错 pageUuid → **PAGE_MISMATCH**（取坐标之前拦截，画布无变化）；焦点 PCB1 → **CONNECTOR_ERROR**。末次已清画布（岳的工程无残留标记）。
真机新事实：`export.screenshot`（bridge screenshot）在本机**恒返回同一张缓存空帧**（三次+`--fit` sha256 全同）——"viewport capture 从来不是证据"现在有实测坐标；取证只能走"抬升窗口+屏幕抓图"（`outputs/013_p2_screengrab.ps1`）。

### §六 export.fab（毕设板 PCB1 122 器件）

三件套出齐（exit 0、failed=[]）：gerber **真 zip**（16 条目 testzip=None）；pnp 122 行齐；base64 总量 ~0.3MB ≪ 32MiB 帧上限。**BOM 零数据行硬伤 → 根因定死**：`includeValue` 语义与名称**相反**（命中即丢行；宿主随包源码逐字证据 `013_p3_evidence/`）——类型包示例 `'yes'` 恰好删掉全部 BOM 器件。改发 `[{Add into BOM:'no'}]` ⇒ **68 行分组 BOM，Quantity 求和=122，位号集合与 pnp 完全相等（一个不少）**。新增 `params.bom.filterOptions` 覆盖通道（null=宿主默认，≠[]）。
**文件名**改 `fab_gerber.zip`/`fab_pick_and_place.csv`/`fab_bom.csv`（宿主对 BOM 自补 .csv，加后缀兜底防 .csv.csv），与 getting-started 第 6 步逐字一致。
**17 列表头旧账**：宿主 `tableAttrKeys = statistics + property` 不去重；改 `FAB_BOM_STATISTICS`（2）与派生 `FAB_BOM_PROPERTY`（13）**互斥** ⇒ 表头恰好 15 列、68 行、Quantity=122（`outputs/013_fab_bishe3/` 为交付件，bishe2 是 17 列历史档）。

### review.mark clear 口径

无页面守卫保留（清除不针对页，文档写明）；active:null 从"cleared:false+canvas refused（误导）"改 **cleared:true + "no active canvas — nothing to remove"**（幂等：无可清即已清）。

### ⚠ 架构级根因（本轮最大发现，已写进 bridge.md）

**"焦点漂移"不是人手也不是玄学**：daemon 只保留一个 connector 连接，而多窗口编辑器的**每个窗口都各自注册**，焦点工程随"最后注册的窗口"翻（审计日志同分钟记到 0.4.10/0.4.9 不同 socket、焦点 test→test2→毕设板连翻）。后果已实测：**R1 全绿的导出也可能是旧 build 窗口答的**（版本号相同区分不了，靠 17 vs 15 列的行为判定抓住；重推同版 bundle 后自愈）。**内测口径：一次只开一个编辑器窗口**——必须写进 getting-started；daemon 多连接路由/stand-down 属 M2 后议。另：`doc.open` 不能跨工程（焦点在 test2 时 open 毕设板 PCB1 → CONNECTOR_ERROR，R3 不替代）。

### 截图 ×6 处置

`bridge screenshot` 缓存空帧 ⇒ 画布类只能抬窗抓屏或岳手截。gs-05 素材（`013_mark_P1.png`+序号表）已确证可用；gs-04/06 终端文本可替；gs-01/02/03 需岳手截（配对公告只在首次配对出现，revoke 复现是破坏性的，不做）。**docs/images/ 未建、文档未塞图**——留岳定夺口径。

### 版本与验证

connector 0.4.9→**0.4.10**（eext 43097 B，三处 bundle 一致：磁盘/包内/编辑器加载）；热更 0.4.9→0.4.10 + 同版重推（治旧窗口）；doctor 7/7。变异累计 4 次全 CAUGHT（filterOptions 改回 / clear 分支改回 / FAB_BOM_PROPERTY 去 filter / 前述批次），还原均字节一致。证据：`outputs/013_p2_*`（批②）、`outputs/013_p3_*`（修复）、`outputs/013_fab_bishe{2,3}/`。

## 交卷记录 · 同事视角走查（Kimi 亲做，2026-09-21）

按内测版标准对 `docs/getting-started.md` 全文做同事视角走查（离线文字核对，逐命令对照 CLI 实现与批①批②真机输出）：

- **核对通过**：doctor 样例与真机输出逐字一致（013_p2_doctor.txt 比对，版本号 0.4.10 已同步）；`review` 参数形态与退出码（2=读不了/1=有 ERROR/0=无）与 `_cmd_review` 实现一致；review-mark / export-fab / doc.list 命令形态一致；fab 四文件名与 0.4.10 落盘现实一致。
- **修正 1 处矛盾**：第 5 步曾把 `bridge screenshot review.png --fit` 当推荐命令，与批② 实测（3.2.186 恒返回缓存空帧）及本文档 gs-05 注自相矛盾——已改为"截图用系统工具（Win+Shift+S），bridge screenshot 别当证据"。
- **gs-05 已补**（`docs/images/gs-05-review-mark.png` = 批② 真机打标抓图，Kimi 亲看确证）；文档头部截图总注同步（gs-04/06 终端可截、gs-01/02/03 需手截）。
- 新增**多窗口警告**（文档头部）：一次只开一个编辑器窗口（批② 架构级根因）。
- **README.md 走查（同批，中英双语段同步修 4 处过时）**：① 桥描述"只读编辑器，不改设计 / 抓一张画布原生截图"→ 对齐现实（只读为主 + 逐页守卫后可放置/移动/删除 + 导出制板，写操作受控可审计）；② 内置规则"3 条 L1 启发式"→ 15 条按连通/电源路径/参数三族全列；③ `bridge screenshot` 行加 3.2.186 缓存空帧警告；④ 英文段同步。已记入 `tasks/013-commit-checklist.md` §2。
- **gs-04/06 已补**（`docs/images/`）：gs-04 = 本机实跑 `boardwise doctor` 当下真实输出（7/7、0.4.10）；gs-06 = 批② 毕设板导出 manifest 的真实文件名/字节数（目录名按文档叙事写作 fab/）。两图均以终端样式渲染（临时 venv + Pillow，已清理），Kimi 亲看复核；正文截图位注同步。剩 gs-01/02/03 需岳手截。

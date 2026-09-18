# 任务 006c：架构护栏——契约防漂移 + 坐标空间守卫 + 模块边界清算

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> **硬依赖：006b 验收盖章之后才能开工**（文件重叠：generate.py / layout / schematic.py / connector 测试）。
> 性质：**既有行为零变更**——除新增测试/文档与工作项 6 的**纯新增**动作外，所有既有测试必须原样通过（守卫测试自身的负向验证除外，见验收 3）。
> 前置阅读：`docs/architecture.md`（要扩写的对象）、`src/boardwise/bridge/protocol.py`（ACTIONS 目录表）、`connector/src/actions.ts`（handlers 注册表）、`src/boardwise/core/geometry.py`（mil 单位域）、`src/boardwise/engines/generate.py:120`（`canvas_pin_offsets`，坐标转换唯一合法入口的样板）。

## 背景

Kimi 架构评审（2026-09-14）结论：分层骨架正确（core 无依赖枢纽、依赖单向、协议闭集、facade 收口），但三条增长轴无护栏，007（PCB）+ 仿真进来会开始烂。本任务把三条护栏装上，顺手清算两处已知边界欠账。**不做 CLI 拆分**（P1，随 007 开工再做）。

## 工作项

### 1. 动作契约漂移守卫（最高优先级）

现状风险：加一个桥动作要动 5 处（`protocol.py` ACTIONS 条目、`actions.ts` handler + 注册表、两侧测试、`docs/bridge.md` 表），而 Python 目录与 TS 注册表之间**没有任何自动化比对**——漏一边就是运行时才爆的 UNKNOWN_ACTION。

- `connector/tests/` 新增文本扫描测试（沿用 `source-guard.test.mjs` 的既有手法）：从 `src/boardwise/bridge/protocol.py` 抠出全部 `name="..."`，从 `actions.ts` 抠出 handlers 注册表的全部 key，**断言两个集合严格相等**（双向差集都必须为空，报错信息列出差异项）。路径用相对仓库根解析，保证在仓库任何工作目录下可跑。
- Python 侧新增目录表自洽测试：动作名必须匹配 `^(daemon 保留名|[a-z]+\.[a-z_]+)$` 命名域约定（hello/ping 无点，其余一律 `domain.verb`）；`owner` 只能是 `connector|daemon`；`params` 无重复。防止目录表自己退化。

### 2. `docs/architecture.md` 扩写（v0.3）

新增三节，写完即生效为项目宪法：

- **模块规则**：分层图（已有）配上 import 规则——`core` 不 import 任何 boardwise 模块；`parsers`/`rules` 只能 import `core`；`engines` 可 import `core`+`parsers`；`bridge` 只认识自己；`cli` 是唯一的组装层。违规即 PR 打回。
- **三套坐标空间**：file 空间（.epru 记录原样，mil、y 轴方向按段类型实测记录）/ canvas 空间（编辑器画布，y 向下）/ mm（只用于给人看的报告）。规则：**转换只许发生在解析器边界和 `canvas_pin_offsets`**；engines 层出现 mil 换算 = bug；变量/参数命名后缀 `_canvas`/`_file` 自证身份。
- **加一个桥动作的清单**：5 个触点逐一列出（protocol.py 条目 → actions.ts handler → 注册表 → 两侧测试 → bridge.md 表），并注明工作项 1 的守卫会抓住漏项。

### 3. 坐标空间守卫测试

文本扫描测试（与守卫 1 同手法）：

- `src/boardwise/engines/**` 禁止出现 `mil_to_mm` / `25.4` / `39.37`（engines 只许说 canvas）；
- `src/boardwise/parsers/**` 禁止出现 `canvas`（解析器只许说 file）。

### 4. epru 分帧层提公共（纯移动重构）

现状：`parsers/schematic.py` 在 import `parsers.epru` 的**私有** `_load_epru_text`——分帧层被 PCB 几何模块绑架了。

- 新建 `parsers/epru_stream.py`：把记录分帧/迭代（`iter_epru_records`、`_load_epru_text` 转正为公开名、`ParseStats`、DOCHEAD 相关常量）整体迁入，全部公开命名。
- `parsers/epru.py` 只留 PCB 几何构建；`parsers/schematic.py` 改从 `epru_stream` 导入。
- `parsers/__init__.py` 导出同步更新；epru.py 保留兼容再导出与否由执行者判断，**但新代码一律从 epru_stream 导入**。
- 判定标准：测试零修改全绿。

### 5. layout 双引擎边界落成

006b 交付后核：`engines/layout` 下**黄金回放（默认）**与**通用求解器（兜底）**必须边界显式——`generate.py` 里策略选择一处可见，默认 replay，无黄金几何时才落 solver。若 006b 已落成此结构，本项只验证 + 把边界写进 architecture.md 的模块规则节；若 006b 把两者搅在一个文件里，本项负责拆开（纯移动，行为不变）。

## 验收

1. Python `pytest -q` 全绿，计数 **≥ 006b 交付基线**（只能多不能少）；connector `npm test` 全绿；`tsc --noEmit` 干净。
2. 守卫测试负向验证：执行者必须**故意制造一次漂移**（TS 注册表删一个 key / engines 文件里写一次 mil_to_mm），展示两个守卫测试变红的输出，然后还原。不许只写不测。
3. 除守卫测试的负向验证外，**既有测试零修改**。
4. architecture.md v0.3 三节齐备，Kimi 审读通过。
5. 完成记录写回本任务书（惯例：假设判定、实测证据、欠账）。

### 6. 工程文档管理动作：图页与 PCB 的探查 / 新建 / 打开 / 编辑（岳翔宇 2026-09-14 增补）

动机：007（PCB）的前置地基；同时清算"动作只认前台页"的隐式焦点状态——golden/test 页张冠李戴已经咬过我们两次。**明确不要删除能力**（岳翔宇原话）。

新增桥动作（命名守 `domain.verb` 约定，进 ACTIONS 闭集 + 注册表，受工作项 1 的漂移守卫约束）：

| 动作 | 语义 | 返回要点 |
|---|---|---|
| `doc.list` | **探查**：枚举当前工程全部文档（原理图页 + PCB），含 uuid / 名称 / 类型 / 是否活动文档 | `documents: [{uuid, name, type, active}]` |
| `doc.open` | **打开**：按 uuid 切换编辑器活动文档（页或 PCB） | `{uuid, active: true}`，切换后编辑器真的跳转（真机验证） |
| `pcb.doc.new` | **新建 PCB**：镜像既有 `sch.doc.new`，在当前工程内建一块板 | `{pcbUuid, focused}` |
| `doc.rename` | **编辑**（最小语义）：按 uuid 重命名页/板 | `{uuid, name}` |

**创建确认门禁（岳翔宇硬约束，2026-09-14）**：创建图页/PCB **必须先问用户**。实现定死，不许自由发挥：

- ACTIONS 目录表每个条目新增 `risk` 字段：`read`（回读类）/ `write`（放置、连线、改名）/ `create`（`sch.doc.new`、`pcb.doc.new`，未来所有"产生新文档"的动作）。工作项 1 的 Python 自洽测试同步断言该字段齐备且取值合法。
- **daemon 单一收口**：`create` 类动作转发前检查 `params.confirm is True`，否则抛新错误码 `CONFIRMATION_REQUIRED`（进 `ErrorCodes`），confirm 参数就地消费、不转发给 connector。connector 保持哑手，零改动。
- CLI 语义：不带 `--yes` 时收到 `CONFIRMATION_REQUIRED` → 交互式询问用户 → 同意后带 `confirm=True` 重试；带 `--yes` 直接放行（脚本化逃生门）。draw 流程内部的建页走它自己的运行级确认门禁，过闸后内部调用带 confirm。
- 测试钉住三条：无 confirm 调 `create` → `CONFIRMATION_REQUIRED`；confirm 非 `True`（如字符串）同样拒；confirm 参数不出现在转发帧里。

**先侦察后动手**（原文不变）：`@jlceda/pro-api-types` 里挖文档枚举（`dmt_Schematic.getCurrentSchematicInfo` 已知）、PCB 创建、按 uuid 激活文档、重命名的真实入口；哪条 API 不存在就**如实回报，不许伪造实现**（比如用"新建同名页"冒充重命名）。找不到激活入口时，带证据回来找 Kimi 裁量替代语义。

验收（真机，test 工程）：`doc.list` 输出与编辑器 UI 里的页/板清单逐条对上；桥建一页 + 一板，`doc.open` 逐个切换且编辑器真实跳转；在打开的页上 `sch.place_wire` 成功（证明"打开后即可编辑"闭环）；全程**零删除类动作**出现。

## 不许动的部分

006b 的绘图链路语义（回放变换、标签命名路径、export.render）；桥协议信封与 ACTIONS 的**现有条目**（只能加守卫，不能改表现有动作）；TOFU 配对；CLI 结构（拆分是 007 时的 P1）。


---

## 完成记录（2026-09-16）

执行者：DeepSeek。基线（岳翔宇独立复跑）：Python **291** / connector **142** / `tsc` 干净。
交付后：Python **368** / connector **161** / `tsc` 干净（**只多不少**）。
版本 **0.4.0**（新增动作面），打包用 Python `zipfile.testzip()` 独立复验通过。

### 工作项 1 — 动作契约漂移守卫

* `connector/tests/contract-drift.test.mjs`：从 `protocol.py` 抠 `name=`，从
  `actions.ts` 抠 `buildHandlers` 注册表 key，双向差集断言为空。**另外把
  `docs/bridge.md` §4 表格也纳入同一守卫**（见下"第五触点"）。
  路径按 `import.meta.url` 相对仓库根解析，任意工作目录可跑。
  **`daemon` 拥有的 `hello`/`ping` 不参与比较**——它们由 daemon 自己应答、按设计没有
  connector handler；守卫比的是"目录 ↔ connector"这份契约，不是目录的全部内容。
* `tests/test_action_catalogue.py`：命名域、`owner`、`params` 无重复、`risk` 齐备且合法、
  **名字唯一**、`create` 动作必须声明 `confirm`。
* **守卫第一次运行就抓到活漂移**：`sch.set_component_value` —— 0.3.18 改名前注册的
  handler，目录里早已没有这个名字，daemon 永远以 `UNKNOWN_ACTION` 拒掉，
  **handler 不可达且看不出来**。已删。
* 目录表本身也有一处退化：`lib.device.search` **重复两条**（`ACTION_NAMES` 是 frozenset、
  `_ACTIONS_BY_NAME` 取最后一个，所以没人发现，只有 `--help` 会打两遍）。已删，
  并加了唯一性断言。

### 工作项 2 — `docs/architecture.md` v0.3

三节齐备（模块规则 / 三套坐标空间 / 加一个桥动作的 5 个触点），状态行升 v0.3，
决策日志加两条。**写规则时当场发现两处违例**（这就是"可执行规则"的意义）：

1. **`core` → `parsers` 反向依赖**：`core/candidate.py` 在函数体里
   `from boardwise.parsers.schematic import _transform_point` —— 既破分层方向，
   又跨层引用**私有名**。`transform_point` 已迁入 `core/geometry.py`
   （返回**元组**不是 `Point`：它要和元组比字典键，`Point` 是 dataclass 会比不等），
   `parsers` 与 `engines` 各自从 core 取。
2. **另外两个私有名跨层**：`engines/draw.py` 从 `core/candidate.py` 取 `_field`/`_as_float`。
   两个模块共用的容错查表助手**属于 core 的公开接口**，已公开化为
   `field_of` / `as_float`（纯改名，行为不变）。

另加 `tests/test_layer_rules.py`：把模块规则做成可跑的表（方向表 + 同层豁免 +
`core` 不许 import 包内任何模块），并把这些违规钉死。

### 工作项 3 — 坐标空间守卫

`tests/test_coordinate_guards.py`：用 `tokenize` 只看**标识符与数字字面量**
（注释/docstring 是散文，必须允许——`epru.py` 里 `"CANVAS"` 是 `.epru` 记录类型，
不是坐标主张；解析器也要能*描述*它在边界上做的转换）。

* `engines/**`：禁 `mil_to_mm`/`mm_to_mil`/`mil2mm`/`mm2mil` 与 `25.4`/`39.37`/`0.0254`/`0.03937`；
* `parsers/**`：禁标识符含 `canvas`；
* 附带钉住两个"合法的转换入口点"必须存在（`canvas_pin_offsets`、`core.transform_point`）。

### 工作项 4 — epru 分帧层提公共

新建 `parsers/epru_stream.py`（14 个公开名）：`EncryptedProjectError`、文档类型常量、
`KEPT_DOC_TYPES`、`KNOWN_RECORD_TYPES`、`FIELD_SEP`、`EpruRecord`、`Document`、
`iter_epru_records`、`split_documents`、`read_project_meta`、**`load_epru_text`**（原私有
`_load_epru_text` 转正）、`ParseStats`。

**一处与任务书字面的偏离**：`ParseStats` **不是**迁入，而是**从 `core.geometry` 再导出**。
它定义在 `core/geometry.py`，而且 `BoardGeometry` 带着一个它——把它搬到 `parsers` 会让
`core` 反过来 import `parsers`（正是工作项 2 刚修掉的那类违例）。故此处保持 core 为归属、
在 stream 模块再导出，使 `from .epru_stream import ParseStats` 成立。

`epru.py` 只留 PCB 几何并再导出框架名（`cli.py` / `epro2_model` / 既有测试因此零修改）；
`schematic.py` 改从 `epru_stream` 导入（6 处调用点由 `_load_epru_text` 改名 `load_epru_text`）；
`parsers/__init__.py` 同步。**判定标准达成：测试零修改全绿。**

### 工作项 5 — layout 双引擎边界

**已落成，故本项只做验证 + 文档化。** `replay_or_solver` 是唯一选择点（默认 replay，
无黄金几何才落 solver），返回 `(plan, source)`，报告打印 source、`plan.notes` 说明降级原因，
两个引擎分属 `replay.py` 与 `generate.py`+`layout.py`。新增
`tests/test_engine_boundary.py` 把"默认是 replay / 降级有具名理由 / 没人绕过选择点"钉住。
边界写入 architecture.md 的模块规则节。

### 工作项 6 — 文档管理动作（真机验收待办）

**侦察结论（全部存在，无一需要伪造）**：

| 动作 | 真实入口 | 可见性 |
|---|---|---|
| `doc.list` | `dmt_Schematic.getAllSchematicsInfo` / `getAllSchematicPagesInfo`、`dmt_Pcb.getAllPcbsInfo`、`dmt_SelectControl.getCurrentDocumentInfo` | @beta/… |
| `doc.open` | `dmt_EditorControl.openDocument(documentUuid)` —— 接受 schematic / **page** / PCB uuid，返回 **tabId**；`activateDocument(tabId)` 是同一动作的后半段（它收 tabId 不是 uuid） | @public |
| `pcb.doc.new` | `dmt_Pcb.createPcb(boardName?)` | @public |
| `doc.rename` | `modifySchematicPageName` / `modifySchematicName` / `modifyPcbName`（按类型分派） | @beta/@public |

`modifyBoardName` 收的是**板名**不是 uuid，故不用（不能按契约寻址）。
**未使用任何删除类 API。**

* `ACTIONS` 每条新增 `risk`（`read`/`write`/`create`），**无默认值**——漏写就是不可见的
  未门禁动作。`canvas.highlight` 记 `read`（只画 view 标记，不动文档内容），
  `doc.open` 记 `read`（改的是编辑器活动文档，不是工程内容）。
* **daemon 单一收口**：`BridgeError(CONFIRMATION_REQUIRED)` 进 `ErrorCodes`；
  判定键是 `spec.risk`，**不是** `params` 里有没有 `confirm`——后者会**失效开放**
  （漏声明的条目反而永不拒绝）。`confirm` 就地消费，不进转发帧。
  顺带给 `sch.doc.new` 补声明 `confirm`（它本来就在门禁范围内；draw 流程过闸后带 confirm 调用）。
* CLI：`--yes` 直接注入 `confirm=True`；无 `--yes` 收到 `CONFIRMATION_REQUIRED` 时
  **仅在有终端时**询问，同意后带 confirm 重试一次；管道 stdin 不算同意，直接报错并提示用 `--yes`。
* 测试：`tests/test_confirmation_gate.py`（24 条，含任务要求的三条 + 端到端确认帧里没有 confirm）、
  `tests/test_confirmation_cli.py`（11 条）、`connector/tests/doc-actions.test.mjs`（16 条，
  含"modify 说成功但其实没改"必须报错、新 PCB 聚焦不了必须拒绝）。

### 第五触点（bridge.md）也是机器检查的了

任务书列的第 5 个触点是文档表。实测它**已经漂了**：11 个动作没进表（其中 7 个早于本轮）。
已补齐 29/29，并给表加了 `risk` 列；`contract-drift.test.mjs` 现在同时断言
**目录 == 注册表 == 文档表**。§5 错误码表补 `CONFIRMATION_REQUIRED`。

### 验收 2 — 负向验证（两个守卫都当场变红）

1. **契约漂移**：删掉 `'sch.geometry': bind(schGeometry),`
   → `not ok 1 - the catalogue and the connector registry list the same actions`，
   `actual: 0: 'sch.geometry'`，报错文案指明"daemon 会转发、connector 会答 UNKNOWN_ACTION"。已还原。
2. **坐标（engines 侧）**：向 `engines/layout.py` 注入 `mil_to_mm(value)` 与 `* 25.4`
   → `layout.py:1134 uses 'mil_to_mm'` / `layout.py:1135 carries the conversion factor 25.4`。
3. **坐标（parsers 侧）**：向 `parsers/epru_stream.py` 注入 `canvas_y`
   → `epru_stream.py:291 defines 'canvas_y'`。两处均已还原并复跑全绿。

### 验收 3 — 既有测试零修改

除新增文件外，**没有改动任何既有测试**。工作项 4 的纯移动重构后既有测试原样通过，
即为该项的判定标准。

### 欠账

1. **真机验收未做**（需岳翔宇在场逐条核）：`doc.list` 与编辑器 UI 清单是否逐条对上；
   `doc.open` 是否真实跳转；桥建一页 + 一板的闭环；`sch.place_wire` 在打开页上成功；
   全程零删除动作出现。**daemon 需重启**（动作表变了）——已按约定把构建完成告诉岳翔宇。
2. **`replay_or_solver` 的 `strategy`/`prefer_replay` 参数没有 CLI 暴露**，只有代码内调用；
   若将来要"用求解器画一张"作为对照，需要补 CLI 开关（本轮未做，任务书未要求）。
3. **bridge.md §12「How the claims here were verified」未随本轮更新**——本轮新增的实测
   （撤回 §J.3 的"聚焦页"结论、陈旧读数是真现象）只写在 §10；§12 的证据清单还是旧的。
4. **`ParseStats` 的归属与任务书字面不符**（见工作项 4），已说明理由；若岳翔宇要它真搬到
   `parsers/epru_stream.py`，需要同时把 `BoardGeometry.stats` 的引用一起重构，
   那是一次真正的分层变更，建议单独一轮。
5. **CLI 拆分（P1）未做**——按任务书"不做 CLI 拆分"，随 007 开工再做。
6. `tools/` 下的实验室脚本未纳入分层守卫（它不在 `src/boardwise` 内）；
   `tools/p4_replay.py` 之类仍可直接 import 任意层。

---

## 验收戳（006c 正式收官，2026-09-15，Kimi）

**离线复验（Kimi 亲跑）**：Python **368** / connector **161** / `tsc` 干净，与报告一致；
0.4.0 包 `testzip`+md5 双验通过；三个守卫测试与 4 个新动作（`risk` ×29）在库。
DeepSeek 自报的三处动手（死别名/重复条目清理、`transform_point` 迁 core、confirm 补声明）
与两处偏离（命名域 2~3 段、ParseStats 再导出）——**理由成立，Kimi 全部签字**。

**真机验收（0.4.0，daemon 已重启，岳翔宇在场）**：

| 项 | 结果 |
|---|---|
| 创建门禁负向 | 无 confirm / `confirm:"yes"` 字符串 → 均 `CONFIRMATION_REQUIRED`，零转发 ✅ |
| `sch.doc.new` | P3 建成聚焦 ✅ |
| `pcb.doc.new` | PCB2 建成聚焦 ✅（岳翔宇亲眼看到跳转） |
| `doc.open` | P2 跳转 `activated/matchesRequest: true` ✅ |
| 打开即可编辑 | 新页 `place_wire` 成功 ✅ |
| `doc.rename` | P3→P3_ACC、PCB2→PCB2_ACC，`doc.list` 复读一致 ✅ |
| 零删除动作 | 全程未碰 ✅ |
| `doc.list` 对 UI | P1/P2/P3_ACC/PCB1/PCB2_ACC 逐条对上 ✅，**但漏报 Panel1**（见下） |

**遗留（不阻塞验收，进 backlog）**：`doc.list` 不覆盖 Panel 类型文档（UI 有 Panel1，
输出没有）。要么纳入枚举，要么在 bridge.md 注明排除理由——007 开工前定。

**006c 验收通过。** 测试页 P3_ACC（含一根测试线）与 PCB2_ACC 由岳翔宇删除。

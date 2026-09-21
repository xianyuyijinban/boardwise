# 012v2 §0 真机 probe 报告（完整版）

> 2026-09-21，宿主 3.2.186 / connector 0.4.5 / daemon 61190。
> 环境：岳重启编辑器后自连；工程 `/test`（= test.eprj2，磁盘 project_structures 证据）。
> 结构：① typeof 全清单（sys.probe checks，33/33 function）；② 最小只读调用实测；
> ③ 随各节实现的延后项（需要新动作才能做调用的方法，逐条列出何时补）。

## 一、typeof 全清单（33/33 = function，与类型包零出入）

| 命名空间 | 方法 | 声明标注 | typeof |
|---|---|---|---|
| sch_PrimitiveWire | delete / modify | beta | function / function |
| sch_PrimitiveText | delete / modify | beta | function / function |
| sch_PrimitiveAttribute | delete / modify | delete=**internal**、modify=beta | function / function |
| sch_PrimitiveComponent | delete / modify | beta | function / function |
| sch_PrimitivePin | delete / modify | beta | function / function |
| pcb_PrimitiveLine | delete / modify | delete=beta | function / function |
| pcb_PrimitiveVia | delete / modify | 同上 | function / function |
| pcb_PrimitivePad | delete / modify | 同上 | function / function |
| pcb_PrimitivePour | delete / modify | 同上 | function / function |
| pcb_PrimitiveComponent | delete / modify | 同上 | function / function |
| dmt_Project | getAllProjectsUuid / getProjectInfo / getCurrentProjectInfo | 无标注 | function ×3 |
| dmt_EditorControl | getSplitScreenTree / generateIndicatorMarkers / removeIndicatorMarkers / zoomToRegion / activateDocument | markers/zoom=beta | function ×5 |
| pcb_ManufactureData | getGerberFile / getPickAndPlaceFile / getBomFile | beta | function ×3 |
| lib_Device | searchByProperties / getByLcscIds / search | searchByProperties=beta **ADD since v4** | function ×3 |

**与类型包的出入：无。** 类型包声明存在的方法在宿主全部存在（含 `ADD since v4`
的 `searchByProperties`——声明版本高于宿主版本的情形未发生）。
`sch_PrimitiveAttribute.delete` 声明即 **无参**（`delete(): boolean`，删"选中"），
**不能按 ID 寻址**——`delete_primitives` 两表均刻意排除它（见 actions.ts 注释）。

## 二、最小只读调用（借现有动作实测）

| 方法 | 实测形态 | 结果 |
|---|---|---|
| `dmt_Project.getCurrentProjectInfo()` | plain 对象 `{uuid, name, friendlyName, data[]}`；**name='/test'** | ✓ doc.list 的 `projects[]` 数据源 |
| `dmt_Project.getAllProjectsUuid()` | 无参 → **string[]，实测返回 1 项**（当前焦点工程） | ✓ doc.list 逐项 getProjectInfo |
| `dmt_Project.getProjectInfo(uuid)` | `{uuid, friendlyName, teamUuid}` —— **Brief，无文档树** | ✓ 非焦点工程 `documents: 'brief'` 的诚实依据 |
| `dmt_EditorControl.getSplitScreenTree()` | `{id, tabs:[{title, tabId, documentType}]}`；tabId = `"<docUuid>@<工程hash>"` | ✓ doc.focus 的 tabId 解析（title 实测如 `"P4.Schematic1"`） |
| `dmt_EditorControl.activateDocument(tabId)` | 返回 true；**只切 tab 层，`sch_*` 上下文跨工程不跟** | ✓ 见下方"实测陷阱" |
| `sch_Primitive*.getAllPrimitiveId()` | 无参 → string[]（id→类索引的唯一来源） | ✓ delete/modify 的枚举依据 |
| `sch_PrimitiveComponent/Wire/Text/Pin.delete(id)` | 逐 id 调用，返回 boolean；**逐件 ~3.7s**（编辑器重解页面） | ✓ P4 17/17、P3 2/2 真机删除成功 |
| `sch_PrimitiveAttribute.delete` | 声明无参 ⇒ 无法按 ID 调用 | — 刻意不派发（probe 结论即"不可用"） |

## 三、实测陷阱（写进 skill §18）

1. **工程焦点与 sch 上下文页可以不一致**：`dmt_Project.getCurrentProjectInfo` 报
   '/test' 的同时，`dmt_Schematic.getCurrentSchematicPageInfo` 可以仍报另一个工程的
   页面（实测 c7c82860）。跨工程切换**必须人手点标签**——`openDocument` /
   `activateDocument` 只到 tab 层。
2. **pageUuid 守卫的实战价值**：上述错位下，`sch.delete_primitives` 以 PAGE_MISMATCH
   拒绝（实测两次），没有守卫删除就会落到错误上下文。
3. **删除慢**：~3.7s/件 ⇒ daemon `DELETE_TIMEOUT=150s`（本批新增），17 件一次批量
   63s 实测通过。
4. **保存异步落盘**：`sch_Document.save` 返回 `{saved: true}` 后，本地 `.eprj2`
   的 mtime 约 10s 后才跳变（实测 11:07:49 → 11:56:26）。

## 四、延后项（需新动作，随各节实现时补调用）

| 方法 | 待补于 |
|---|---|
| `sch_PrimitiveComponent.modify` / `sch_PrimitiveWire.modify` / `pcb_PrimitiveComponent.modify` | S4（bw_scratch 生命周期：移动/旋转/读回） |
| `pcb_ManufactureData.getGerberFile/getPickAndPlaceFile/getBomFile` | §六 `export.fab` 实现时（只到 File 对象，不落盘） |
| `lib_Device.searchByProperties` / `getByLcscIds` | §七 `lib.recommend` 实现时 |
| `dmt_EditorControl.generateIndicatorMarkers / removeIndicatorMarkers / zoomToRegion` | §八 `review.mark` 实现时 |

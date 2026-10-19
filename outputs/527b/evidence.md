# 527B 证据：`pcb.readback` 的页型守卫，以及这条改动自己的挖洞结果

日期：2026-10-19　版本：v0.5.18（内测）　相关：`tasks/527_pre060_loose_ends.md` §527B

## 1. 要治的缺陷（用户真机反馈，B4）

真机：编辑器 3.2.149，焦点在某**原理图页**，调 `pcb.readback`：

```
TypeError: Cannot read properties of null (reading 'map')
```

同一会话里 `pcb.geometry` 报 `bboxes: 0`。

根因：`connector/src/actions.ts` 的 `readback(eda, kind, params)` **不看当前激活页是什么类型**，
直接对 `kind` 对应的命名空间调 `getAll()`。焦点不在该类页上时宿主回 `null`（或含 null 空洞的
数组），读端要么崩，要么把空洞变成一行「所有字段皆空」的幻影器件。

**与 `pcb.geometry` 的关系：无。** 这条要写清楚，因为第一版注释把它写错了（见 §3 F6）：
`pcb.geometry` 的 id 来自**调用方** `params.bboxIds`，它既不调 `readback` 也不调任何 `getAll`，
全仓 `pcb_PrimitiveComponent.getAll` 的调用点只有 `readback` 与另一处。`bboxes: 0` 是**同一份
报告里的另一件事**，这次的改动**没有**治它——`pcb.geometry` 至今没有页型守卫，停在原理图页上它
会把每个 id 记成 `meta.unreadable: ["<id>: the host returned no box for this id"]`，读者分不清
「这些 id 本来就没有盒子」和「你停错了页」。要不要治是另一件事（见 §5）。

## 2. 守卫的形状

1. 用**已有的** `activeDocument()` 读焦点（同一份读数 `doc.list` / `document.current` 用）。
2. 只在读数来自**精确**来源 `dmt_SelectControl.getCurrentDocumentInfo` 时才可能拒绝——
   `dmt_Schematic.getCurrentSchematicPageInfo` / `dmt_Pcb.getCurrentPcbInfo` 这两个 per-kind
   回退只能回答「有某类的页开着」，**不能**回答「它是焦点」，把它当证据会误拒今天能用的读。
3. 类型映射：`pcb`→`pcb`，`page`/`schematic`→`sch`，其余→`null`（不拒绝）。
4. 命中（精确 + 类型可命名 + 与请求的 kind 不同）→ `ActionError('PAGE_MISMATCH', …)`，
   **一次宿主调用都不发**，message 点名「请求读什么 / 当前激活是什么 / 怎么修」。
5. 未知类型**不拒绝**（「不知道不是证据」），但**必须留痕**：`problems` 进返回体（见 §3 F3）。

错误码用既有的 `PAGE_MISMATCH`（`guardPage` / `guardPcb` / `pcb.export_fab` /
`pcb.drc_ruleset` 都用它），**不新造** `WRONG_DOCUMENT`——第一版造了，被主代理否掉：
一个事实两个名字会导致调用方只匹配其中一个、把拒绝当载荷读。

## 3. 挖洞（只读红队，独立上下文）结果与处置

派了一个只读子代理专挖这条改动（不是整仓）。它给出 8 条，**全部核实成立**，处置如下：

| # | 严重度 | 洞 | 处置 |
|---|---|---|---|
| F1 | **高** | `activeDocument` 的 uuid 按**两种形状**读（own-key + `getState_*` 兜底），`documentType` 却只读 own-key → 宿主用 `getState_` 形状答时类型读成 `undefined`→`'unknown'`，**守卫静默不触发**，而 `source` 仍是「精确」 | **已修**：新增 `infoDocumentType()`（同款两形状兜底）；并把「精确但类型不可命名」显式写进 `problems` |
| F2 | 中 | `documentType` 枚举里 `8/9`（仿真原理图页）、`12/15`（PCB 2D/3D 预览）落在 `unknown` → 同样漏拒（实测 `documentType=12` 时 `sch.readback` 照读） | **已修**：`DOC_KIND_BY_TYPE` 补这 4 个值 |
| F3 | 中 | `problems` 在 `readback` 里被**彻底丢弃**（死变量，`tsc` 不报）→「宿主读不出焦点」与「我确认是这块板」在返回体上同形 | **已修**：`problems` 进返回体（与 `document.current` 同口径） |
| F4 | 中 | `includePrimitives` 那条路**没跟着修**：null 空洞仍变成 `{primitiveId:'', fields:{}}` 幻影行，且 `__meta.returned` 把它算进真实读数；零测试 | **已修**：同一套过滤 + `__meta.nullEntries` 计数 |
| F5 | 中 | 声明与实现脱节：`unreadable` 换了含义（现在是**计数**，含 null 空槽）而 `protocol.py` 的 `returns` 与 `docs/bridge.md` §4 都没动；同名字段在 `pcb.geometry`/`pcb.drc_ruleset` 是**字符串列表** | **已修**：`returns` 与 §4 两行补齐，并写明 `unreadable` 是计数、逐条原因不保留 |
| F6 | 低 | 注释里两句事实错误：①`pcb.geometry` 的 id 来自 `readback`（错）；②`pcb.drc_check` 抛 `PAGE_MISMATCH`（错，那是 `pcb.drc_ruleset`） | **已修**（注释改正） |
| F7 | 低 | 测试 6 恒真（改动前也绿）；缺 6 类真实失效模式覆盖 | **已修**：测试 6 换成有鉴别力的断言；补 5 条（getState 形状 / 12 与 9 / 直接但无名 / `getAll` 抛错 / `includePrimitives` 空洞） |
| F8 | 低 | B3 文档「`(§3.5)`」引用错（§3.5 讲窗口 hub，与退出码无关）；`unreadable` 描述误导 | **已修**：改指排障表，`unreadable` 改成「计数」 |

**这一节为什么留在这里**：B4 是「工具知道正确答案却没拦住我拿到错的那个」。这条改动本身第一版
就有同一个病——守卫写好了，但在「宿主换一种形状答」时静默失效，而且日志里没有任何信号。
**没有挖洞这一环，这次提交会把「已修」写进 release notes 而实际只在一种宿主形状上有效。**

## 4. 读数（本机，可复现）

```
cd connector && npm run typecheck      # tsc --noEmit，干净
cd connector && npm test               # 532 passed / 0 failed（含新文件 11 条）
```

变异（`cp` 备份 + `cmp` 逐字节还原，未用 `git checkout`；每次变异后重跑 `node build.mjs`，
因为测试 import 的是 `dist/esm`）：

| 变异 | 结果 |
|---|---|
| 守卫条件短路（`&& false`） | 2 红（两个方向的拒绝） |
| `items = raw`（去掉 `.filter(Boolean)`） | 1 红（null 空洞计数） |
| 类型读回 `plainGet(info,'documentType')`（撤 F1） | 1 红（getState 形状） |
| 去掉 `9`/`12` 两个映射（撤 F2） | 1 红（预览页/仿真页） |
| `items = raw`（撤 F4，primitives 路径） | 1 红（`includePrimitives` 空洞） |

**爆炸半径**：Python 侧**没有任何调用方**调 `pcb.readback` / `sch.readback`（只有
`sch.geometry`），所以这条硬拒绝只影响 `bridge call` 的人类/脚本调用方——也就是踩到 B4 的那类人。

## 5. 没做 / 边界

- **`pcb.geometry` 仍无页型守卫**（F6 ①）。它是独立的洞：id 由调用方给，停错页时输出
  「每个 id 都没有盒子」。本批不修（不在 0.6.0 前必须收口的清单里），留记录。
- **`pcb.drc_ruleset` 之外还有哪些 action 在错页上静默**：本批只挖了 readback 这一条缝，
  没做全仓普查。
- **真机未验证**：`getCurrentDocumentInfo` 在 3.2.149 上到底答哪种形状（own-key 还是
  `getState_`）、`documentType` 在原理图页上的实际取值，都是**代码推断**；真机验证归发版的上机闸。
- **JSON 里 `documentType` 是否总是数字枚举**：未验。

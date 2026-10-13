# R1 证据（v0.5.12 桥能力补齐）— 离线半

开发机：Windows 11，**无立创 EDA Pro**（`boardwise bridge status`：daemon 自动拉起、`connector: not connected`）。
因此本节只有离线证据；四件的真机部分全部**未跑**，步骤在同目录 `runbook.md`，原始读数位 `live/` 为空。
基线：main `68ee63c`（v0.5.11 + 路线图回退）。

## R1-1 `pcb.place_component`

**侦察**（类型包 `@jlceda/pro-api-types` 0.4.25，`connector/node_modules/@jlceda/pro-api-types/index.d.ts`）：

- `PCB_PrimitiveComponent.create(component, layer: TPCB_LayersOfComponent, x, y, rotation?, primitiveLock?)`
  → `Promise<IPCB_PrimitiveComponent | undefined>`，`@beta`；`component` 可为 `{libraryUuid, uuid}`（器件）
  或 `{libraryType: FOOTPRINT, libraryUuid, uuid}`（封装）。`TPCB_LayersOfComponent = TOP(1) | BOTTOM(2)`。
- 同类还有 `getAllPrimitiveId(layer?, lock?)`、`delete(ids)`、`placeComponentWithMouse`（绑鼠标、立即返回，不可用于自动化）。
- **声明 ≠ 实现**：3.2.186 是否真有 `create` 只能真机 `sys.probe` 答（runbook R1-1 第 2 步）。

**实现**（`connector/src/actions.ts`）：

- 新动作 `pcb.place_component`；解析梯子（uuid 对 / LCSC / keyword）从 `sch.place_component` **原样抽出**为
  `resolvePlacementDevice`，两条放置共用一份（唯一改动：BAD_REQUEST 文案里的动作名参数化）。
- 与 `sch.place_component` 的有意差异（docstring 逐条写明）：`pageUuid` **必填**且须是焦点 PCB（`guardPcb`）；
  器件以裸 `{libraryUuid, uuid}` 交给宿主；未落地按「超时 / 抛错 / 空答」分码，读回用**板级器件 id 前后差分**
  （不用邻近判定——点上已有的件会被读成落地）；`primitiveLock=false`；不设位号。
- 双表：`protocol.py` ACTIONS（connector 所有、`write`）+ `timeout_for` 与 `sch.place_component` 同档 60 s；
  `docs/bridge.md` §4 一行。

## R1-2 `sys.get_document_source` 带身份

- 每次读都先读活动文档（以前只在给了 `uuid` 时读），返回加 `uuid` / `name` / `type`（`doc.list` 拼法，
  名字取自 `doc.list` 同一个 `collectDocumentRows`）；**读后再读一次焦点**，变了就三项 `null` + `notes` 说明。
  无活动文档 → 三项 `null` + note；列表里没有该文档 → 保留 `uuid`/`type`，`name: null` + note。
- 纯增量：`source`（宿主调用路径）、`data`/`chars`/`truncated`/`tail`/`note` 不动；179 的 `DOC_NOT_ACTIVE` 契约不动。

## R1-3 / R1-4

- R1-3：**未做**。桥上无可调 `setDocumentSource` 的动作，`sys.probe` 的 `call` 模式按设计只放行只读动作；
  加不加临时写口是设计决策，交主代理裁决（runbook 列了两个选项与侦察步骤）。`doc.rename` 未改动。
- R1-4：**未做**（纯真机探针）。runbook 给了三颗轨旗的放置/读回/清理步骤与两种结论各自的后续动作；
  180 的按符号放置**未推广**——没有证据不动代码。

## 版本

四处同源升 0.5.12：`connector/package.json`、`connector/extension.json`、`src/boardwise/__init__.py`、`pyproject.toml`。

## 测试

| 线 | 结果 |
|---|---|
| connector `npm test` | 500 pass / 0 fail（基线 479；新增 `pcb-place-component.test.mjs` 13 条、`source-identity.test.mjs` 8 条） |
| connector `npm run typecheck` | 通过 |
| dsh-plugin typecheck + test + build | 48 pass / 1 skip（未改动，照纪律跑） |
| pytest 全量（`-n 8`，`--basetemp` 在 NTFS 盘） | 5388 passed / 20 failed / 36 skipped；基线 5382 / 20 / 36。新增 `tests/test_r1_bridge_completion.py` 6 条全绿。20 红与基线**逐条相同**：16 条缺 gitignore 掉的 `outputs/*.json`、3 条 `test_069c` 读真实 home 的 skill 安装态、1 条 `test_126a` 指纹（换行问题，PR #77 修） |

## 变异验证（cp 备份 → 改 → 跑锚 → cp 还原 → sha256 比对）

| # | 变异 | 锚 | 结果 | 还原 |
|---|---|---|---|---|
| M1 | `pageUuid` 不再必填（`if (!pageUuid)` → `if (false)`） | pcb-place-component.test.mjs | 12 pass / 1 fail → CAUGHT | sha256 一致 |
| M2 | 未落地读回不再差分（`after = before`） | pcb-place-component.test.mjs | 11 pass / 2 fail → CAUGHT | sha256 一致 |
| M3 | 身份不再做读后焦点复核 | source-identity.test.mjs | 7 pass / 1 fail → CAUGHT | sha256 一致 |
| M4 | daemon 预算漏掉 `pcb.place_component` | test_r1_bridge_completion.py | 1 fail / 5 pass → CAUGHT | sha256 一致 |

## 遗留

1. 四件真机全部待跑（runbook）；R1-1 若宿主不实现 `create`，按任务书走「如实写宿主不支持 + 替代侦察」。
2. R1-3 的仪器（临时 `dangerous` 写口 vs 不做）待裁决。
3. `pageUuid` 必填是我按「PCB 写不许无守卫」定的，与 `sch.place_component`（可省略）不对称；若主代理要对称，改一行。
4. 参数名沿用 `pageUuid`（= PCB 文档 uuid，与 `pcb.delete_primitives` / `pcb.modify_primitive` 同名同守卫），
   没有用任务书建议的 `boardUuid`：同一条放-删链路两个名字会让调用方写错。

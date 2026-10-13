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

---

# R1 真机半（2026-10-13 18:20–18:35，有编辑器的机器）

环境：宿主 **3.2.186**，内建 connector **0.5.12**（`sys.probe` 自报）。`bridge status` 两窗口：
`test`（inst-102017400-798az89f，0.5.12）与 `毕设FOC驱动板`（inst-030312986-lgpmdd69，0.4.29）。
**只对 test 路由**，另一窗口零路由（只在 status 里被读到过名字）。原始读数全在 `live/`。

## 意外 0：首轮 `--project test` 路由不通，根因是**驻留 daemon 陈旧**（已按环境约定处置）

1. 第一次照抄 §0 的两条命令：`bridge status` 报 daemon 已在跑，但 test 窗口列为 `(no project)`；
   `doc.list --project test` 回 `PROJECT_NOT_CONNECTED`（`live/00_doc_list.err` 记录了原话，00_doc_list.json 为空）。
2. 用 `--instance inst-102017400-798az89f` 一问，doc.list **能**拿到完整工程（`projects[0]` name `/test`、
   friendlyName `test`、focused true）——因此不是"读不到工程"，是 hello 期的工程名读空了
   （`IDENTITY_DEADLINE_MS=1500ms`）。**这一问本身把窗口的 context 刷新了**（daemon 按每帧 context
   跟随后续变化），此后 `--project test` 直接可用。
3. 但真正卡住 R1-1 的是第二件事：`pcb.place_component` 回 **`UNKNOWN_ACTION`**（存 `live/13a_place_unknown_action.json`）。
   现码的 `bridge --help` 明明列出该动作（`protocol.py:963`），而端口 61190 的 LISTENING 进程
   PID 38796 起于 **08:39**（0.5.12 代码落地之前）——daemon 的 ACTIONS 是加载期常量，动作没入册。
   按环境约定 kill 掉驻留 daemon（`Stop-Process`），下一条命令自动拉起新的；两窗口约 5 s 内自行重连，
   这次 test 窗口的 hello **带上了工程名**（status 只剩 `test` / `毕设FOC驱动板` 两个有名窗口）。
4. 重连后 §0 重跑通过。**这是 runbook 之外的环境事故，不是代码缺陷**；`live/` 里保留了失败读数。

## §0 身份核验（过）

- `00_doc_list.json`（重跑版）：`projects[]` 唯一项 `focused: true`，`name "/test"` / `friendlyName "test"`；
  daemon 取 friendlyName → `bridge status` 打印 **`test`**，与任务书逐字一致。
- `PCB1` = `5dc38976c1fa45ce`；`01_pcb_readback.json`：`componentCount: 0`（**空板**，R1 通过）。

## R1-1 `pcb.place_component`：放 → 读 → 量 → 删（过）

| 读数 | 文件 | 结果 |
|---|---|---|
| 宿主有没有这三条调用 | `12_probe.json` | `pcb_PrimitiveComponent` present，`create`/`getAllPrimitiveId`/`delete`/`getAll` **全 function**，`create` arity 6 |
| 放置 | `13_place.json` | `uuid 18994061da7286d2`，`appeared` **恰好一个且等于 uuid**；`elapsedMs 973` |
| 坐标 | 同上 | `requested {x0,y0,rot0,layer "top"}` 与 `placed {x0,y0,rot0,layer 1,designator "R1"}` 逐项相同 → **宿主没有吸附**，`layer` 回读 1（TOP） |
| 读回 | `14_readback.json` | `componentCount 1`；器件在位号 `R1`、`SupplierId C25804`、两个焊盘（Pad 1/2，±29.7） |
| 量盒 | `15_bbox.json` | 器件盒 `[-57.531,-29.008, 57.531,29.008]`、ATTR 盒 `[-57.531,34.008, -16.531,79.008]`，两个都有限；`meta.measured 2/2` |
| 删除 | `16_delete.json` | `deleted: ["18994061da7286d2"]`，`notFound`/`failed` 空 |
| 复原 | `17_after.json` | `componentCount 0` |

**偏差（runbook 的 14 拿不到 ATTR id）**：`pcb.readback` 的 primitive 子集只有 pads/tracks/vias，
`14_readback.json` 里**没有位号 ATTR 图元**，所以 runbook 第 4 步"从 14 里找 `$ATTR`"照抄跑不通。
补一发 `14b_pcb_source.json`（`sys.get_document_source` 读 PCB1 全文，29725 字符），从记录流里取
`{"type":"ATTR",...,"key":"Designator","value":"R1"}` 的 **id `18994061da7286d2e16`**（parentId = 器件 uuid，
layerId 3，fontSize 45）——与 `src/boardwise/cli.py:_designator_attr_ids` 同一口径，checkup 的实测丝印
走的就是这条路，所以量的是同一条盒，没有引入第二套口径。

## R2-3 丝印实测（插在放件与删件之间）

见 `outputs/R2/evidence.md` §R2-3 与 `outputs/R2/live/checkup_silk/`。一句话：**字宽来源是实测，
不是估算**（finding 原文：`文字宽度：实测（宿主 primitive bbox） 1 个、估算值（字宽比带，非读数） 0 个`），
就是本 R1-1 放下的这颗 0603 的位号。

## R1-2 `sys.get_document_source` 带身份（过）

| 焦点 | 文件 | 读数 |
|---|---|---|
| 原理图页 P1 (`b4298962367251c8`) | `21_source.json` / `22_doc_list.json` | `uuid b4298962367251c8` / `name "P1"` / `type "page"`，与 22 里 `active: true` 行的三项**逐字相同**；**无 `notes` 键** |
| PCB1 (`5dc38976c1fa45ce`) | `23_source_pcb.json` / `24_doc_list.json` | `uuid 5dc38976c1fa45ce` / `name "PCB1"` / `type "pcb"`，与活动行逐字相同；无 `notes` |

两份里都只有原有的 `note`（截断说明），不是身份降级的 `notes`。

## R1-3 `sys.set_document_source` 改名侦察（过；**写通行，改名不通**）

`31_scratch.json` 建 scratch 页 → `pageUuid 82d8ac2229f026f0`，`focused: true`，
`32_focus.json` 核到它就是活动页。

**偏差（R3 停手点，已按纪律处理）**：`33_source.json` 全源 11121 字符里**没有 `R1-scratch`**——
`sch.doc.new(name="R1-scratch")` 传的名字**宿主没用**，页面被自动命名 `P23`（`doc.list` 也报 `P23`）。
runbook 的 `assert 'R1-scratch' in src` 因此会失败。**目标字段本身在场**：源里有一条
`ATTR key="@Page Name" value="P23"`（ticket 14，id `0edaf7f80fecb4b1`），改名侦察要改的正是它，
所以没有写回未改动的源，也没有自行换目标：把**该条**记录的 value 改成 `R1-renamed`（`34_diff.txt`
证明只有这一行不同，11121 → 11128 字符），其余字节不动。

| 读数 | 文件 | 结果 |
|---|---|---|
| 写回 | `36_set_source.json` | `hostAnswer: true`，`readBack: "differs"`，`readBackChars 11128` |
| `differs` 是什么 | `38_diff_vs_sent.txt` | **只有 DOCHEAD 一行不同**：宿主把 `client` 与 `updateTime`/`version` 重新戳了（`c6fccf7de…`→`12abe91ed…`，`1791887328998`→`1791887390968`），其余 33 行**逐字节相同**——正是 runbook 预告的"宿主重序列化" |
| 文档现在持有那段文本吗 | `38_source_after.json` | `R1-renamed` 在、`P23` 不在；`chars 11128`；身份三项 `82d8ac2229f026f0 / "P23" / "page"` |
| 页名变了吗 | `37_doc_list.json` | **没变**：该页仍叫 `P23`（documents[] 与 `projects[0].schematics[]` 里都是 `P23`） |
| 收尾 | `39_delete.json` / `39b_doc_list.json` | `deleted: true`；doc.list 回到 4 份文档，scratch 页不在 |

**判读**：`setDocumentSource` 这条宿主调用**存在且接受文本**（`hostAnswer true`，回读持有的就是我们写的那份
文本——只差宿主自己重戳的头），写通路**通**。但**改 `ATTR key="@Page Name"` 不能改页名**：`doc.list`
仍报 `P23`。也就是说 `doc.rename` 的 `NOT_SUPPORTED` **不能靠"改写源里的页名字段"这条路修**
（至少不是页面上这条 ATTR）。`doc.rename` 的动作代码**一行未动**；本结论交主代理裁决。
另记一笔：`sch.doc.new` 的 `name` 参数在 3.2.186 上**不生效**（宿主自命名 P23）——与 R1-3 无关，
但是本机实测事实。

## R1-4 Power 旗字形（过 → **与地旗同病**）

| 读数 | 文件 | 结果 |
|---|---|---|
| 三颗旗落地 | `41_place_VIN5.json` / `41_place__5V.json` / `41_place_SEC_12V.json` | uuid 分别 `1fb29667083e1d96` / `4c9bcc7c90cc0125` / `991ff37d43ce423c`，都非空 |
| 符号名（uuid 级，178b 读法） | `42_geometry.json` | 三颗的 `state.Symbol` **全是同一个** `{name "Power-5V", uuid 125152e45b373de7}`；落点 x = 0 / 200 / 400 |

`VIN5` / `+5V` / `SEC_12V` 三个不同网络，画布上**同一个 `Power-5V` 字形**——与 178b/180 的地旗
（`place_power(kind=Ground, net=X)` 恒落 `Ground-GND`）**同病**：宿主按 `kind` 挑符号，不按 `net`。

库族对照（`43_power_family.json` 宽搜 + `43b_power_family_exact.json` 逐名精确比对）：

- `lib.device.search(keyword="Power-")` 宽搜回 10 条**全是不相干的芯片**（L78M05ABDT-TR 等），
  模糊匹配把 "Power" 当词根，**不能**用它证伪族的存在；
- 逐名精确比对：`Ground-GND`、`Ground-PGND` 有同名器件（各 1 条精确命中）；`Power-5V`、`Power-VCC`
  有同名器件；而 **`Power-VIN5` / `Power-+5V` / `Power-SEC_12V` 三条都没有同名器件**（精确名一条没有）。

**按 runbook 判读表：同字形 → 结论 `与地旗同病`；代码不动**（任务书明示"结论我拿去裁决"）。
附一条对裁决有用的事实：即便把 180 的按符号放置推广到 rail 旗，本机库里也只有 `Power-5V`/`Power-VCC`
这类通用轨旗，**没有** `Power-VIN5`/`Power-+5V`/`Power-SEC_12V`，这三个 net 仍会落到回落分支。

收尾：`44_delete_flags.json`（三颗旗 `deleted` 全中）→ `45_delete_page.json`（`deleted: true`）→
`46_doc_list.json`（scratch 页不在）。

## 终态复原（doc.list 探前/终态**逐字节同形**，其余项读数归零）

| 项 | 探前 | 终态 | 证据 |
|---|---|---|---|
| doc.list 文档集 | 4 份（schematic1 / P1 / P22 / PCB1） | **同样 4 份，uuid 逐条相同** | `00_doc_list.json` vs `46_doc_list.json` |
| PCB1 器件 | `componentCount 0` | **0** | `01_pcb_readback.json` vs `90_final_pcb_readback.json` |
| PCB1 源 | （探前未单读此档；放置后是 29725 字符） | **27590 字符**，不含 `18994061da7286d2`、不含 `"value":"R1"`、不含任何 `key":"Designator"` 记录 | `14b_pcb_source.json`（放置态）→ `91_final_pcb_source.json` |
| scratch 页 | 无 | **无**（两页都已删） | `39b_doc_list.json` / `46_doc_list.json` |

写操作只落在 PCB1 与两张 scratch 页上，终态零残留。

## 意外清单（与 runbook 预期不符的全部读数）

1. **驻留 daemon 陈旧**（见上）：`pcb.place_component` 一度 `UNKNOWN_ACTION`；处置 = kill 重启。
2. **hello 期工程名读空**：首轮 `--project test` 路由不通；任何一发经该窗口的调用都会把 context 刷新，
   此后正常。runbook §0 没有这一步。
3. **`pcb.readback` 不含位号 ATTR 图元**：runbook 第 4 步"从 14 里找 `$ATTR`"做不到（改用 PCB 源读）。
4. **`sch.doc.new` 的 `name` 不生效**：建页得到的名字是宿主自命的 `P23`，不是 `R1-scratch`；R1-3 的
   assert 因此失败（已按 R3 处理：改的是真正的页名字段，未写回未改动的源）。
5. **`export.render` 在空 PCB 上 TIMEOUT**：`format=png, scope=page` 30 s 未 settle（`93_final_render.json`
   是错误原文）；`export.screenshot` 回的是 **89 字节 1×1 PNG**（`92_final_screenshot.json`）——两者都
   **不作为证据**，复原由 `90`/`91`/`46` 三份读数钉住。顺带记：`export.render` 的 `format` 收
   `png|svg|pdf`（不吃 `image/png`）、`scope` 收 `page|selection|project`（不吃 `document`）。

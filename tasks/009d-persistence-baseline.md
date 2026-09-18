# 任务 009d（M0-P0d）：持久化与失败现场基线

> 执行者：DeepSeek（代码与审计）；真机四场景由 Kimi + 岳翔宇在场执行。
> 工作目录：`E:\boardwise`。
> 前置阅读：`tasks/009-schematic-review-m0.md`（M0 立项书，P0d 行）、
> `docs/roadmap-2026-09-18.md` §3 表格"桥与回读"行、§5 M0"持久化与失败现场基线"、
> `docs/bridge.md`、`docs/draw.md`。
> 背景教训：上游 easyeda-agent 公开 issue #216 报告过 v1.4.8 的写入持久化
> 问题（保存后重开内容丢）。我们的宿主编码是 3.2.186，行为必须实测，
> 不许假设。

## 为什么

"写入 API 返回 ok" ≠ "编辑器状态对" ≠ "保存到文件了"。三层是三个事实。
当前 draw 链路有读回比对（netlist compare），但"持久化"这一层的语义
从没被认真区分过；bridge 调用超时后的行为也没人审计过。M0 晋级要求：
**读回未稳定、保存未验证，均不许报完成。**

## 第一步：现状审计（先交这个，再动代码）

把 draw 写入链路的每一步列成证据表：哪一步调了什么 eda API、返回值
怎么被解释、save 在哪调、读回在哪做、超时发生在哪一层（bridge client
`bridge/client.py`、daemon、connector 各自语义）、超时后 CLI 报什么、
audit log 记什么。每条给文件:行号。审计结论只能是"代码里读到的"，
不许猜。审计报告写进本文件末尾"审计记录"节。

## 第二步：按裁决补机制

### 裁决 1：持久化三态分离

- `placed`：写入 + 编辑器内读回一致（现有 compare 做的是这层）
- `saved_unverified`：save API 返回 ok，未做落盘验证
- `saved_verified`：关闭工程重开后网表/几何比对一致——**只有这一态
  算"持久化"**

draw 的 CLI 报告与 audit log 必须分开表达三态；"saved" 字样只许用于
第三态或带限定词。任何把 `placed` 或 `saved_unverified` 说成
"已保存/saved" 的输出都是 bug。

### 裁决 2：超时先重读，不重复创建

bridge 调用超时后，draw/CLI 必须先发起一次读回（geometry 或 netlist），
报告"实际写入了什么"，exit 码表达"未知/部分完成"；**严禁**把超时
解释成"没写入"而自动重试创建。

### 裁决 3：离线可测

mock bridge 模拟三种故障（超时、部分写入、断连），断言：不重复创建、
报告三态正确、超时路径上确实发起了重读调用。真机不在这步碰。

## 第三步：真机四场景的验证手段（你写，Kimi + 岳翔宇执行）

把四个场景写成可逐条执行的命令序列（markdown 检查单），每个场景给出
预期输出与判定标准：

a. **保存-重开一致**：draw → save → 关工程 → 重开 → 网表 + 几何比对
b. **断连恢复**：draw 中途 kill daemon → 重连 → 状态审计（不重放写入）
c. **部分写入**：构造超时（手段自定，写明）→ 重读 → 报告与实际一致
d. **幂等重跑**：同一 spec draw 两次 → 不重复创建（replay 层已有幂等
   测试，这里验证端到端）

检查单落 `docs/persistence-baseline.md`。已知事实供参考：编辑器
`sch.netlist` 需先 `sch.doc.save` 否则返回空；审计日志在
`C:\Users\xiangyu\.boardwise\audit\`；专用测试工程用岳翔宇的 test 工程
（当前已清空）。

## 交卷标准

- 审计记录节完成（每条带文件:行号）
- 三态与超时重读机制落地，离线测试覆盖三种故障
- pytest（837+N）/ connector 183 / tsc 三线全绿
- 变异验证 ≥2（例：摘掉超时后的重读调用 → 测试必须咬红）
- `docs/persistence-baseline.md` 检查单可照做
- 既有测试语义不动；例外逐条列出并说明

纪律：不动 git；不碰真机；代码/注释全英文；Windows 坑（文件显式
`encoding='utf-8'`、控制台 `PYTHONIOENCODING=utf-8`、不用 /tmp，临时
文件用仓内 `.tmp_*`）；最小改动。

交卷报告：审计结论摘要、改动文件清单、测试数变化、变异验证记录、
检查单落点、发现的坑。

---

# 审计记录（第一步；2026-09-18）

全部结论来自**代码阅读**，逐条给 `文件:行号`。**任何未运行的推断都标注为推断**。

## A. draw 写入链路的每一步

| # | 步骤 | 调用的 action | 落点 | 返回值怎么被解释 |
|---|---|---|---|---|
| 1 | 建空白页 | `sch.doc.new {"confirm": True}` | `cli.py:809-815` | `page is None` ⇒ `return result`（**不重试**）；`pageUuid` 取出后无校验 |
| 2 | 放器件 | `sch.place_component` | `draw.py:834` | `placed` 为 None 时只记 StepRecord；`uuid`/`device` 存在才取。**无重试、无读回** |
| 3 | 写属性 | `sch.set_component_attribute` | `draw.py:870-886` | **检查** `applied is False` ⇒ 记失败行（`:880-886`）——本仓**已有的"核对自报"先例** |
| 4 | 读回前保存 | `sch.doc.save` | `draw.py:659` | **返回值被丢弃**（`await _call(...)` 未赋值） |
| 5 | 读回网表 | `sch.netlist {"type":"EasyEDA"}` | `draw.py:660-663` | 无 `text` ⇒ 记 "cannot verify"，返回 `(None,{},None)`，**绘制继续**（`:665-673`） |
| 6 | 器件级判决 | `verify_placements` | `draw.py:682-696` | `report.ok` 决定 StepRecord；`report is None` 不阻断，`report` 非 ok 阻断后续铜 |
| 7 | 走线/名字 | `sch.place_wire` / `place_netlabel` / `place_text` / `place_power` | `draw.py:1036` | 逐个 `_call` 记录；失败不中断循环 |
| 8 | 读回+保存 settle | `sch.doc.save` + `sch.netlist` **各最多 4 次** | `draw.py:337-347` | 保存返回值**丢弃**；`settled` = 两次连续导出一致（`:344-345`） |
| 9 | 兜底候选 | `sch.geometry`（+ `_census_primitives`） | `draw.py:1082-1097` | 只有 netlist 失败时才走 |
| 10 | 比对 | `compare_models(model, candidate)` | `draw.py:1193` | `is_empty` ⇒ 退出码 0，否则 1（`cli.py:1362-1379`） |
| 11 | 出图 | `export.render` / `export.screenshot` | `draw.py:1208-1213` | 仅写文件 |

**A1**：链路上**只有 `set_component_attribute`（步骤 3）检查了自报字段**。
两个 `sch.doc.save`（步骤 4、8）的返回都被丢弃 —— 与步骤 3 的既有纪律不一致。

## B. 超时发生在哪一层

| 层 | 语义 | 落点 |
|---|---|---|
| connector（TS） | 自己的预算；miss 时**读回**并告诉调用方**别盲目重试** | `actions.ts:2232`（`PLACE_COMPONENT_TIMEOUT_MS = 30_000`）、`:2242`（`componentsNear`）、`:2279-2284`（注释） |
| daemon（Python） | `asyncio.wait_for(future, timeout=timeout_for(action))`，超时 ⇒ `BridgeError(TIMEOUT)` | `daemon.py:609`、`:610-614` |
| daemon `finally` | `self.pending.pop(request_id)` —— **只放弃等待，从不通知编辑器取消** | `daemon.py:615-616` |
| 超时预算表 | `ACTION_TIMEOUT=30.0` / `SCREENSHOT_TIMEOUT=60.0` / `PLACEMENT_TIMEOUT=60.0` / `HELLO_TIMEOUT=5.0` | `protocol.py:99-113`、`:709-720` |
| client（Python） | **`call()` 完全没有超时** —— `await recv()` 永久阻塞；`open()` 只有 `open_timeout=10` | `client.py:65-77`、`:48` |
| draw 层 | `_call` **捕获一切异常** ⇒ `StepRecord(ok=False, message)` ⇒ 返回 `None` | `draw.py:155-170` |

**B1（本任务的核心风险）**：`daemon.py:615-616` 只 `pop` 未来，**没有任何取消帧发给
connector**。所以"daemon 报超时"与"写入没发生"是两件事 —— 编辑器可能在 daemon 放弃
之后才把写入落下去。**超时后必须重读，不能当成"没写入"。**

**B2**：`draw.py:167-170` 把超时（`BridgeError.code == "TIMEOUT"`）与"编辑器拒绝"压成
同一个 `None`，**draw 层无法区分**，因此也无从据此决定要不要重读。

## C. 超时后 CLI 报什么

- `_call` 记下的失败行渲染在 `failed actions (N):`（`cli.py:1343-1349`），内容是
  `record.summary` + `record.detail`（= `BridgeError.message`，例：
  `save before readback` / `sch.doc.save timed out after 30s`）。
- **退出码与超时无关**：`cli.py:1362-1379` 只由 `report.is_empty` 决定 0 / 1。
  ⇒ **若保存超时但网表读回恰好与 golden 一致，退出码是 0** —— 一个超时以"成功"收尾。
- 无"部分完成"、无"未知"的表达。已核：`tests/` **无一处**断言 `draw` 的退出码
  ⇒ 新增一个码不与既有测试冲突。

## D. 保存 API 的真实语义（**与任务书假设不同，以代码为准**）

- 动作声明 `returns="{saved: true}"`（`protocol.py:394`）。
- connector 实现：`sch_Document.save()` 为假时 **throw `ActionError('CONNECTOR_ERROR', ...)`**，
  成功才 `return { saved: true }`（`actions.ts:2211-2220`）。
  ⇒ **当前 connector 永远不会返回 `saved: false`。** 保存失败是**异常**，
  被 `draw.py:167-170` 吞成 `None`，且调用点丢弃返回 ⇒ **保存失败在报告里等于没发生。**
- 立项书提到的"`saved:false` 结合脏状态解释"在本宿主**无此路径**；真实存在的是
  `ok:true/false` + 异常，以及**没有任何落盘验证**。

## E. `saved_verified` 能否由桥自己建立？**不能**

- 协议中与文档开合相关的只有 `doc.list`（`protocol.py:476`）与 `doc.open`（`:492`）。
- `doc.open` 是 **`risk="read"`**，声明 "Changes the editor's active document, **never the
  project's content**"（`:495-498`）⇒ **只切焦点，不从磁盘重载**。
- **没有** close-project / reopen-project 动作（动作目录全表 `protocol.py:151-524`）。
  ⇒ 编辑器内存状态在 `doc.open` 前后不变，**`saved_verified` 无法由桥单独建立**。
  它只能由"人在编辑器里关工程重开"产生 ⇒ 属于第三步检查单，不属于 draw 命令。

## F. audit log 记什么

- 位置 `~/.boardwise/audit/YYYY-MM-DD.jsonl`（`daemon.py:131-138`、`:160-161`），
  与任务书给的 `C:\Users\xiangyu\.boardwise\audit\` 一致。
- 每条 `{ts, action, role, ok, ms}`；失败加 `error=<code>`（`daemon.py:781-792`）。
- **不记 `data`** ⇒ `saved:true` 不在日志里；**无任何持久化状态字段** ⇒
  三态在日志里目前**完全无法区分**。
- CLI 可以自己写日志，有先例：`_cmd_bridge_revoke` 直接调
  `daemon_module.append_audit(None, action=..., role="cli", ...)`（`cli.py:764-772`）。

## G. 审计结论汇总（决定了要改什么）

1. `sch.doc.save` 的返回必须被**检查**（步骤 4、8），作为"save 成功"的唯一依据
   —— 步骤 3 已经这么做，这里是不一致。
2. 超时必须与其它失败**区分**，并在超时路径上**先重读**（`sch.geometry` 最便宜），
   报告"实际写入了什么"，且**严禁重试创建**。
3. 三态要同时出现在 **CLI 报告**与 **audit log**；`saved_verified` 不可由 draw 声称。
4. 需要一条**只读**命令，把"关工程重开后的实际内容"变成可比对的证据 —— 否则第三态
   没有机器判据，只能靠人眼，等于不可验收。

---

# 交卷记录（第二步 + 第三步；2026-09-18）

三条全绿：pytest **866 passed**（基线 837，**+29**）/ connector **183 pass** /
`tsc --noEmit` 干净。**既有测试零修改**（本任务没有需要改的旧语义）。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/boardwise/engines/draw.py` | `PERSISTENCE_*` 四态词汇 + `PERSISTENCE_WORDS` 措辞；`StepRecord.timed_out`；`TIMEOUT_CODE`；`_call` 标记超时；新增 `_call_write`（超时先重读、绝不重发）、`_read_back_after_timeout`、`_save_project`（**检查** save 返回）；`_settled_netlist` 改收 `result`；`DrawResult.save_ok` / `saved_verified` / `timeouts` / `persistence`；新增 `geometry_fingerprint`（去 id 摘要）与 `fingerprint_total`；`run_draw` 的 6 个写调用改走 `_call_write` |
| `src/boardwise/cli.py` | `_render_draw_result` 增 persistence 段（三态 + 超时清单 + 限定语）；**退出码 3**（超时可覆盖 clean diff）；`_audit_draw_persistence`（三态进审计日志）；新增 `boardwise persistence` 子命令（`--out` / `--baseline`）+ `_compare_persistence` + `_audit_persistence_verified` |
| `src/boardwise/bridge/daemon.py` | `AUDIT_DRAW_PERSISTENCE` / `AUDIT_PERSISTENCE_VERIFIED` 两个审计记录名（+ `__all__`） |
| `tests/test_candidate_draw.py` | 新增 `FaultClient`（三故障注入）+ 13 条测试（超时标记 / 重读 / 不重试 / 三态 / 退出码 / 审计落盘） |
| `tests/test_persistence.py` | **新建**，16 条：指纹（含去 id 与双重计数两个坑）、比较的 6 条路径、命令面的 6 条 |
| `docs/persistence-baseline.md` | **新建**：真机四场景检查单（第三步交付物） |
| `docs/draw.md` | 新增 "Persistence: three states" 一节 |
| `docs/roadmap-2026-09-18.md` | M0 交付项 ✅ + `saved:false` 假设的勘误 |

## 测试数变化：837 → 866（+29）

`test_candidate_draw.py` +13、`tests/test_persistence.py` +16（新文件）。
**被改既有测试：0 条** —— 本任务没有需要改的旧语义，所有既有断言原样通过。

## 变异验证记录（5 个，全部 CAUGHT + 还原 sha256 一致）

| # | 变异 | 咬红 |
|---|---|---|
| M1 | 摘掉超时后的重读调用 | 1 条 |
| M2 | 超时不再被标记（`timed_out=False`） | 3 条 |
| M3 | save 返回再次被丢弃（`save_ok = True`） | 2 条 |
| M4 | 摘掉退出码 3 分支 | 1 条 |
| M5 | 不可判（geometry 读不到）改成放行 | 1 条 |

## 第三步交付物

`docs/persistence-baseline.md` —— 四场景（保存-重开一致 / 断连恢复 / 部分写入 /
幂等重跑），每条给命令、预期输出、判定标准（全用**计数或退出码**，不用印象）。
**按项目规矩用英文写**（`docs/` 全英文）。

## 发现的坑（除了交卷标准里列的三条机制）

1. **`sch.geometry` 的真实形状里没有 `primitives` 键。** 现有的
   `_census_types` 读的就是 `primitives`，所以它在真机 dump 上**恒返回 `{}`** ——
   "netlist 失败后的 page census" 这个诊断在真机上是空的。它降级得诚实
   （`_census_primitives` 会记一条 "geometry dump carried no primitive list" 失败行，
   不会假装数过），所以我**没有顺手改**它（改它属于动一个无关既有特性的语义）。
   持久化指纹另写了 shape-aware 的 `geometry_fingerprint`。**建议 M1 单独收编这两条。**
2. **`saved:false` 在本宿主不存在**（见勘误）：connector 在保存被拒时是 throw。
   立项书那句假设要按代码改写 —— 真正的问题是**返回值被丢弃**。
3. **`fingerprint_total` 的必要性**：把"每列表总数"和"每类型小计"一起求和会**双重计数**
   （35 components + 33 wires 被报成 136）。已加助手 + 测试钉住。
4. **真机上 daemon 级超时没有杠杆**：超时是模块常量，无 flag/环境变量可覆盖 ⇒
   只能"等"不能"构造"。daemon 级超时路径**只在离线被覆盖**（注入
   `BridgeError(ErrorCodes.TIMEOUT)`）。检查单里已单独列出这条缺口，避免后人把离线
   覆盖读成真机实测。

## 纪律

不动 git；**未执行任何真机场景**（四场景由 Kimi + 岳翔宇执行）。过程中为冒烟检查单
的命令**只读**碰了一次在线编辑器（`sch.netlist` / `sch.geometry`，都是 `risk=read`，
未改动任何内容；该次调用如实返回 `CONNECTOR_ERROR: both netlist exports failed`）。
代码/注释全英文；临时文件用仓内 `.tmp_*` 且已删。

---

# Follow-up（009d2）：断连路径的 persistence 谎报 —— 已交卷（2026-09-18）

三条全绿：pytest **877 passed**（基线 866，**+11**）/ connector **183** / tsc 干净。

## 现象（真机实证，Kimi 执行场景 B 抓出）

`taskkill //F` 杀 daemon 后：audit log 实证 `sch.doc.new` ×1 + `sch.place_component` ×5
**成功返回**（5 件落到 P4 页），而 draw 报告写
`persistence: not_placed — nothing was written`。**这是谎报**，且是最危险的那类：
信它去重画，同一页就有两套件。

## 根因（文件:行号，改前）

| # | 位置 | 问题 |
|---|---|---|
| 1 | `engines/draw.py:184-190`（原 `persistence` 属性） | 判据只有 `save_ok` / `comparison`，**没有任何"写入已被确认"的概念** ⇒ 把"流程没走完"（`comparison is None`）直接等同于"什么都没写"。**这是谎报的直接来源。** |
| 2 | `engines/draw.py`（原 `_call` 失败分支） | 只把 `code == "TIMEOUT"` 记为 `timed_out`；daemon 被杀抛的是 `websockets.exceptions.ConnectionClosed`（**既非 `OSError` 也非 `BridgeError`，无 `code` 属性**）⇒ 落进普通失败。 |
| 3 | `engines/draw.py`（原 `_call_write`） | 只对 `records[-1].timed_out` 反应 ⇒ 断连不触发读回、不标未知。 |
| 4 | `engines/draw.py:1326-1330` | `candidate is None` 时 `return result`，`comparison` 从未设置 —— 这是 #1 把状态误判为 `not_placed` 的实际触发路径。 |

## 修法

**分层：谁持有传输谁负责归一化。**

- `bridge/protocol.py`：新增 `ErrorCodes.DISCONNECTED`（**只能由 client 合成**——daemon 没了，
  没人能回答；它存在的唯一理由是让"传输死了"与"动作被拒"可区分）。
- `bridge/client.py::call`：把 `(websockets.ConnectionClosed, OSError)` 归一化为
  `BridgeError(DISCONNECTED)`。这是**唯一**知道 `websockets` 的层；`engines/` 不 import
  `bridge/`（刻意分层），只能按字符串读 `code`，所以契约必须在这里守住。
- `bridge/client.py::close`：容忍"已经死掉的 socket"——它在 CLI 的 `finally` 里跑，
  抛异常会把"失败但已被如实报告"的 draw 换成一个 traceback，丢掉"哪些写入无从交代"的报告。
- `engines/draw.py`：
  - `StepRecord` 增 `disconnected` / `wrote`，加 `unknown_outcome` 属性；
  - `DISCONNECTED_CODE` / `READBACK_ACTION` 常量；
  - 新增 `PERSISTENCE_UNKNOWN`（**不在三态阶梯上**——它不是更弱的断言，而是"断言做不了"）；
  - `DrawResult.acknowledged_writes` / `unknown_writes`：`not_placed` 改为**只许在
    「零个写入被确认 且 零个未知」时使用**（确有零写入的实证），不再是"没看完"的推论；
  - `_read_back_after_unknown`（原 `_read_back_after_timeout` 改名，因为现在两种形状都走它）：
    读回失败如实记 **"could not look"**，**绝不许读成"是空的"**；同一轮里若已确认传输死了，
    后续写入不再重复试探，改为明写"没有再看（已经知道没得看）"——否则一行关键信息会被淹掉。
  - `_call_write` 用 **index** 定位自己那条记录（原来是 `records[-1]`，读回会插行，不够稳）。
- `cli.py`：`unknown` 时报告**分两段列出**"已确认落页的写入"与"从未答复的写入"，并明确警告
  **不要在这个页面上重画**；退出码 **3 覆盖 0 和 1**（"diff 不同"也是对一个内容不再确定的
  页面的断言）；`draw` 子命令 help 同步退出码；审计记录增 `writesAcknowledged` /
  `writesUnknown`（**日志本身就能反驳"什么都没写"**，不必翻终端回滚）。

## 测试清单（+11）

`tests/test_candidate_draw.py`（+8）：
`test_a_transport_death_never_claims_nothing_was_written`（场景 B 复现：`die_after=5`，
断言 `unknown` 而非 `not_placed`、措辞不含 "nothing was written"、已确认写入含 2 个
`sch.place_component` + `sch.doc.new`）、
`test_the_dead_transport_is_never_read_as_an_empty_page`（"could not look"、且**不得**出现
`0 component(s)`）、
`test_the_page_is_looked_at_once_not_once_per_write`、
`test_the_writes_are_never_reissued_after_a_transport_death`、
`test_a_death_on_the_first_write_is_unknown_too`、
`test_not_placed_still_belongs_to_a_refusal_before_any_write`（**边界守护**：拒绝是答复，
零写入有实证 ⇒ `not_placed` 仍可达，否则该状态就废了）、
`test_a_transport_death_cannot_finish_green_and_names_what_landed`（退出码 3，且是**从 1
升级**上来的 —— 这个场景 `comparison is None`，原来会给 1）、
`test_the_audit_log_alone_contradicts_nothing_was_written`。

`FaultClient` 增 `die_after=k`：前 k 次调用正常，之后全部断连 —— 这是**某一时刻 daemon
死掉**的形状（比逐动作设故障更贴近场景 B），也是"部分落页 + 其余未知"能离线复现的原因。

`tests/test_bridge_cli.py`（+3）：`test_a_dead_transport_becomes_a_disconnected_code`
（参数化 `ConnectionClosed` 与 `OSError` 两形状；用**真实**的 `ConnectionClosedError`
构造，不用手搓替身 —— 否则"catch 的是不是真类型"根本没测到）、
`test_closing_a_socket_that_is_already_gone_is_not_an_error`。

## 变异验证（5 个，全部 CAUGHT + 还原 sha256 一致）

| # | 变异 | 咬红 |
|---|---|---|
| M1 | **把断连路径重新映射回 `not_placed`**（即原 bug） | 3 条 |
| M2 | 断连不再被标记（`disconnected=False`） | 2 条 |
| M3 | 未知路径上完全不读回 | 1 条 |
| M4 | `unknown` 不再覆盖 diff（摘掉退出码 3） | 1 条 |
| M5 | 断连不再归一化成错误码 | 2 条 |

## 被改既有测试（1 条，逐条说明）

`tests/test_candidate_draw.py::test_a_timed_out_write_reads_the_page_back_and_is_never_retried`
—— 它断言 `"may have landed" in record.detail`，而新措辞为 "may **still** have landed"
并同时说明两种失败形状（"a timeout is not a cancellation and a dropped connection is not
a failed write"）。**这是文案精化，不是语义改动**：该测试钉的实质（结果是未知、绝不重发）
一字未变，我还为它补了两条断言（两种形状都要写明）。**其余 866 条一字未动。**

## 纪律

不动 git、不碰真机、全英文注释、临时文件用仓内 `.tmp_*` 且已删。

## 报备：`tests/` 里两处同名顶层定义重复（**既有，非本任务引入**）

`ast` 扫描 `tests/*.py` 发现两处**逐字节相同**的重复定义：
`test_bridge_cli.py::test_status_ignores_an_ambient_http_proxy`（:334 / :369）与
`test_candidate_draw.py::test_geometry_canvas_mode_matches_plan_positions`（:458 / :489）。
Python 保留最后一个 ⇒ 前者是静默死代码，实际测试数比看起来少 1。
**两处都在本任务改动之前**（我核对过行号位置），且 `tests/test_module_hygiene.py` 只扫
`src/boardwise` ⇒ 这个形状在 `tests/` 里**目前无人守**。按"最小改动、既有测试语义不动"
未动它们。**建议后续单独处理，并把 `test_module_hygiene` 的扫描面扩到 `tests/`。**




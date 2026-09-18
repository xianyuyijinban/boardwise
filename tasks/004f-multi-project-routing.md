# 任务 004f：多工程路由——按工程配对表 + 工程寻址

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 前置阅读：`tasks/004d-activate-root-cause.md` 完成记录（H2 实锤段）、`docs/bridge.md` §3/§10、`src/boardwise/bridge/daemon.py`、`connector/src/index.ts`。
> 现场参照：参考实现就是活的多实例路由模型——`easyeda health` 输出的 `windows[]`（windowId + context.projectUuid/projectName）+ CLI 的 `--project/--window` 寻址。可借鉴其模型，不照搬代码。

## 背景（006 真机实测定案，直接信任）

**每个 EasyEDA Pro 工程一个独立的扩展宿主上下文，`sys_Storage` 按工程隔离**（判决实验：revoke 后自动配上的是 test 工程实例，`sch.geometry` 随即显示 test 空白页）。推论：

1. 每开一个工程就活一个连接器实例，各持 token。当前**单配对文件**模型下，切工程 = 新实例 = UNAUTH 死循环，必须人工 revoke——今天的 18:51/20:53/21:15 三波 UNAUTH 全是这个。
2. 更危险的是**转发目标歧义**：daemon 只握一个"当前连接器"，用户切了工程，动作却发往旧实例——`draw` 这类写动作存在"画进错误工程"的隐患类别，必须在架构层封死。

## 威胁模型修订（先说清再动手）

配对表语义 = **任何新实例自动配对**（不再是"只信第一个"）。安全性论证：loopback-only + 004e Origin 白名单（浏览器网页在握手层被拒）之后，能摸到配对口的只剩本机进程；而本机进程本来就能读 `~/.boardwise/token`（CLI token）——边际风险为零，自动配对不扩大实际攻击面。**因此 004e 从"可选加固"升级为本任务的前置**（顺序：先 004e 后本任务，或合并执行）。

## 修改项

1. **配对表**：`~/.boardwise/connectors.json`——fingerprint → `{projectUuid, projectName, pairedAt, lastSeen}`。hello 里 connector 上报 `projectUuid`/`projectName`（连接后调 `dmt_Project.getCurrentProjectInfo`；拿不到记 `null` 并在 status 里标注）。旧 `connector-token` 单文件做一次性迁移，迁移后删除。
2. **hello 协议**：connector 角色新增可选字段 `projectUuid`/`projectName`；daemon 未知 fingerprint → 自动配对 + 审计 `pairing`（带工程名）；已知 fingerprint → 更新 lastSeen/projectUuid。
3. **路由**：daemon 维护在线连接器实例集合。转发规则——只有一个在线实例就发它；多于一个时，动作必须带 `--project`（工程名或 uuid 前缀），否则结构化错误 `AMBIGUOUS_TARGET`（响应里列出可选工程名）。CLI 所有桥子命令加 `--project`；`bridge call` 同步支持。
4. **draw 绑定**（防错工程）：`boardwise draw` 从 `sch.doc.new` 的返回确定目标 projectUuid，全程动作绑定同一实例；实例中途离线 → 报错退出而不是漂移到别的实例。
5. **status 输出**：实例列表（fingerprint 前 8 + 工程名 + 在线/离线）。
6. **文档**：bridge.md §3 握手补新字段；§10 删"按工程隔离"限制（转已解决）；README 双节同步。

## 不许动的部分

信封格式；`role=cli` 鉴权语义；TOFU 自动配对语义（扩表不改信任模型）；既有测试断言（除直接相关）。代码/注释英文；不执行任何 git 命令；测试秒级。

## 验收

- golden 工程 + test 工程**同时开着**：`bridge status` 列出两个实例；不带 `--project` 的动作收到 `AMBIGUOUS_TARGET` 且响应列出两个工程名；带 `--project` 命中正确工程（截图内容可证）。
- **切工程零操作**：不再出现 UNAUTH 死循环；侧载升级（存储被抹出新 token）只影响对应工程的重配对，其他工程配对不受牵连。
- 真机回归：test 工程里 `boardwise draw --from tests/fixtures/ch340_golden.epro2` 重跑，逐 pin diff 0 差异（即 006 收官路径不被本任务破坏）。
- 全部测试绿（含：双实例路由、配对表迁移、AMBIGUOUS_TARGET、draw 实例漂移拒绝）。

---

## 重审修订（2026-09-14，Kimi）：前提被实测推翻，scope 重写

DeepSeek 实测翻案：**`sys_Storage` 是编辑器全局共享，不按工程隔离**（重启后 connector 用存量 token 直连成功；revoke 不影响活 socket）。此前"按工程隔离/配对竞态"的结论系焦点页误读。因此：

**作废**：按工程配对表、`connectors.json`、工程寻址路由（`--project`/`AMBIGUOUS_TARGET`）——单实例模型成立，这些都不需要。

**保留并重排为本任务实际 scope**（桥加固三件套）：

1. **文档更正**：`docs/bridge.md` §10"按工程隔离"条目改写为实测结论（全局共享存储；侧载重置存储是 UNAUTH 波的唯一真因）。
2. **侧载重配对自愈**：侧载新版 connector → 存储重置 → 新 token → 撞旧配对 UNAUTH。修法：当当前配对连接器**不在线**时，带未知 token 的 `role=connector` hello 视为重配对（覆盖配对文件 + 审计 `re-pairing`）；在线时仍严格拒绝。威胁模型不变（loopback + 004e）。
3. **bootstrap 盲区根因**（P0——它破坏"零操作自连"承诺）：0.2.5 起第三次复现"编辑器重启后不自连，About 菜单上下文也救不回，只有再重启编辑器才好"。收证据查根因（候选：bootstrap 时 ws API 未就绪/异常吞掉/重连退避到顶放弃），修复后验收 = 连续 5 次冷启动编辑器全部零点击 connected。

**多窗口路由**：明确暂缓（单窗口是主流场景），bridge.md §10 标注为已知限制。

---

## 增补两项（2026-09-15，Kimi，006c 验收后追加）

### 4. `document.current` 前台判定漂移修复（P1，今天实测咬人）

**实测**：图页在前台时 `document.current` 报 `type: "unknown"`、project 空 —— 它从
分屏标签树**推导**active，而本机标签对象没有 `documentType` 字段（代码 337-343 行
已在容忍这件事）。同一天 `doc.list` 用 `dmt_SelectControl.getCurrentDocumentInfo`
报的 active（P1→P3_ACC）**逐次全对**。

**修法**：`document.current` 的 active 判定改走 `getCurrentDocumentInfo`（与 `doc.list`
同源），标签树只作补充展示；推导逻辑若保留必须标注"启发式，不可作判据"。
补一条 connector 测试：前台图页时 active 必须是该页 uuid。

### 5. hello 帧带 connector 版本（P2，收尾 0.3.11 的半个方案）

现状：版本自证靠 `sys.probe`（得主动问）和 About 菜单（得人看）。**hello 握手帧
加 `connectorVersion` 字段**（值即 `__BOARDWISE_VERSION__`），daemon 收到即审计留痕
（`client: boardwise-connector/<editor>` 这行扩成含 connector 版本）。收益：每次连接
都能在审计里回答"跑的是哪一版"，侧载串版事故（已发生两次）事后可查。
daemon 对缺该字段的旧 connector **不拒绝**（向后兼容），只在审计里标 `(version unknown)`。

### 验收增补

- 原三条不变（文档更正 / 侧载重配对自愈 / bootstrap 盲区连续 5 次冷启动零点击 connected）。
- 增补：前台图页时 `document.current` 的 active 与 `doc.list` 一致；审计日志里能看到
  `connectorVersion` 留痕。
- bootstrap 盲区的 5 次冷启动验收**需要岳翔宇配合重启编辑器**，排到最后一项做。
- 动作面若变，daemon 由 Kimi 重启（纪律沿用）。


---

## 完成记录（2026-09-16，DeepSeek，connector 0.4.1）

基线：Python **368** / connector **161** / `tsc` 干净。交付后：Python **372** / connector **167** /
`tsc` 干净。`boardwise-connector-0.4.1.eext` 用 Python `zipfile.testzip()` 独立复验通过
（含 `connectorVersion`、`getCurrentDocumentInfo`、`bootstrap FAILED/retry`，`Function.prototype` 0 次）。
**动作面未变**（无新动作、`ACTIONS` 未改），但 **daemon 需重启**：配对规则与 hello 字段都在
daemon 的 Python 代码里，是加载期生效的。

### 1. 文档更正

`docs/bridge.md` 里**并没有**"按工程隔离"这条限制——它只存在于本任务书与
`tasks/006-ch340-vertical-slice.md`。所以不是"改写条目"，而是**把实测结论写进去**：新增
**§10.24**（`sys_Storage` 是编辑器全局共享、不是按工程隔离；按工程配对表 / `connectors.json` /
`AMBIGUOUS_TARGET` 在**建成之前**就已作废；侧载重置存储才是 UNAUTH 波的唯一真因），
并在 **§10.2** 标注"多工程路由明确暂缓"、指向条目 24 说明理由。另：§3.4 补第 4 行（重配对）
与残留情形，§3.3 补 `connectorVersion`，§10.5 撤回旧的第 5 条，§10.13 补重配对，
新增 **§10.25**（bootstrap 盲区）。§12 证据表补 4 行。

### 2. 侧载重配对自愈

规则按原文实现：配对文件在、token 不符、**当前无连接器在线** → 覆盖配对 + 审计 `re-pairing`
（带 `replacedFingerprint`）+ 控制台公告（`PairingNotice.repaired`）；**有连接器在线** → 仍严格拒绝，
且错误文案改写为"已有一个连接器在连接；若你刚侧载，先关掉它或 revoke"，不再只念 revoke 命令。

**五条既有测试被改动，全部属于直接相关**（它们断言的正是被本项改掉的语义）：
`test_hello_rejects_bad_token`、`test_pairing_a_connector_does_not_touch_the_cli_token`、
`test_revoke_forgets_...`、`test_a_connector_pairs_itself_...`（CLI）、
`test_every_call_is_audited`。改动方式是**让被配对的连接器保持在线**——旧写法先 `await ws.close()`
再让"陌生人"连，而关闭是异步的，daemon 何时清掉 `daemon.connector` 不确定；新写法要么保持
socket 打开，要么用 `_until(lambda: daemon.connector is None)` 等事实成立（不 sleep 猜）。

新增 4 条测试：无在线连接器时新 token 重配对（含审计与公告措辞）、有在线连接器时不被顶掉、
hello 记录 connectorVersion、旧 connector 缺字段被接受并标 `(version unknown)`。

**残留情形如实说明**（文档也写了）：侧载后**两个实例同时活着**（旧 bundle 的 socket 没关，
典型成因是装完只点 Reconnect 而没完全重启进程）→ 旧的在线、新的仍被拒。此时只能真正重启
或用 `Re-pair on next connect` 菜单。daemon 不会从活 socket 手里把配对抽走。

### 3. bootstrap 盲区（P0）——两处确凿缺陷已修，5 次冷启动验收未做

代码层找到两个能精确产生该症状的缺陷，都已修并有测试钉住：

1. **`void bootstrapAtModuleLoad()` 没有 `.catch`**。`connectOnce()` 是 async，一旦 reject
   （敌对的 `sys_Storage`、`resolveConfig` 抛错、token 生成失败……），**一次性 claim 已被拿走**，
   于是 `activate()`、self-arm、Reconnect 此后**全是 no-op**，日志面板与 About 都一片空白——
   表现恰是"只有重启编辑器才好"，因为重启是唯一能重跑 bootstrap 的事。
   修：catch → 记日志 + 进 armNotes（About 可见）+ **释放 claim** + 有界重试。
2. **`hasHost()` 在求值时为假就永久收工**（只记一条 note，然后等一个宿主未必会发的 `activate()`）。
   修：改为**有界重试**（250/750/1500/3000/5000/8000/10000 ms，约 29 秒），每次都留痕。

**关于"宿主会丢弃定时器"这条旧结论，我给出不同读法**（写进代码注释与 §10.25）：0.2.3 的 1s/4s
探针"没留下痕迹"是因为**那次 bundle 根本没被加载**（004d 已固定事实 2）——一个从未被调度的
定时器证明不了定时器会被丢弃。反过来，**实测成立的只有一条**：模块求值期发起的链条能自持
48 分钟（274 次审计 connect）。所以本项的重试定时器挂在模块求值上下文里，且**有界**（不是
重连策略，一旦 socket 建立就交给 transport 的退避循环）。

**验收未做**：连续 5 次冷启动、零点击 connected，需要岳翔宇在场配合重启——按任务书排在最后。
若 5 次里有失败，现在的日志面板与 About 会给出 `bootstrap FAILED: …` /
`bootstrap retry N in … ms` / `bootstrap gave up after N retries: …`，不再是沉默。

### 4. `document.current` 前台判定（P1）

抽出 **唯一一条读取路径** `activeDocument()`（`dmt_SelectControl.getCurrentDocumentInfo`，
失败才退到分种类 getter），`doc.list` 与 `document.current` **共用**——之前两处各读各的，
才会出现"同一个事实两个答案"（这正是 2026-09-15 咬人的形态）。
`document.current` 现在返回 `active`（uuid/type/source）、`type`（仍为 `sch|pcb|unknown`，
兼容既有消费者，但现在=前台文档的种类）、`typeSource`、`heuristic`（=true 表示来自兜底，
**不可作判据**）；`tabs[]` 保留但**仅作展示**。
顺带：删掉已无用的 `DOC_TYPE`；新增 `infoUuid()` 同时容忍 plain 属性与 `getState_Uuid`
两种形状（`getCurrentPcbInfo` 在真机上是后者，旧代码在兜底路径上会误报"无文档"）。
新增 3 条 connector 测试，含任务要求的"前台图页时 active 必须是该页 uuid"。

### 5. hello 帧带 connectorVersion（P2）

`transport.ts` 新增可选 `connectorVersion`（仅非空时进帧，旧构建不发的仍不发），
`index.ts` 传 `VERSION`；daemon 在 `_handshake` 读入并存进 `Connection`，
审计 `hello` 记录的 `client` 扩成 `… connector=0.4.1`，缺字段时写 `(version unknown)`
并**不拒绝**；另加 `connectorVersion` 字段便于机器检索。
新增 `client_with_version()`（`daemon` 导出，`UNKNOWN_CONNECTOR_VERSION` 常量）。

### 欠账

1. **bootstrap 的 5 次冷启动验收未做**（需岳翔宇在场）。
2. **daemon 需重启**（本轮 Python 代码变了：配对规则 + hello 字段 + 审计）。
3. 真机未验：`document.current.active` 与 `doc.list` 在真机上是否逐次一致（离线与单测已钉）；
   审计里 `connectorVersion` 是否如期望出现（需重启 daemon 后看一次审计行）。
4. `sys.probe` 的 `connector` 字段与 hello 的 `connectorVersion` 现在是两条独立来源；
   若将来要"以哪一个为准"，需定一条（目前二者同源，都来自 `__BOARDWISE_VERSION__`）。


---

## 真机验收（2026-09-16 08:2x，connector 0.4.1 在线，岳翔宇在场）

### 第 5 项 — 已验 ✅

daemon 重启 + 0.4.1 侧载后，审计 `hello` 记录：

```
08:27:16 hello  ok=True  client='boardwise-connector/3.2.186 connector=0.4.1'  connectorVersion='0.4.1'
```

`client` 行按设计扩成含 connector 版本，且另有独立字段便于检索。**"跑的是哪一版"以后从审计回答。**

### 第 2 项 — 真机自愈已验 ✅

同一次重启过程中，审计自然记录了完整的自愈序列（**没有任何手工 `revoke`**）：

```
08:26:30 hello       ok=False  error=UNAUTHENTICATED
08:26:51 hello       ok=False  error=UNAUTHENTICATED
08:27:16 re-pairing  ok=True   fingerprint=46b59031  replacedFingerprint=6d87bbd1
08:27:16 hello       ok=True   client='… connector=0.4.1'
```

正是"侧载重置存储 → 新 token → 一两次 UNAUTH → 无连接器在线时自动重配对"的形态，
且 `replacedFingerprint` 留下了它替换掉的那个指纹。

### 第 4 项 — 已验 ✅（决定性）

`doc.open` 真机跳转成功（**006c 的欠账一并清掉**）：

```json
{"uuid":"b4298962367251c8","tabId":"b4298962…@ea80ff…","opened":true,"activated":true,
 "document":{"uuid":"b4298962367251c8","type":1,"matchesRequest":true}}
```

切到 `P1.Schematic1` 前台后，两侧读取**逐字段相同**：

| | uuid | type | tabId | source |
|---|---|---|---|---|
| `doc.list.active` | `b4298962367251c8` | `page` | `b4298962…@ea80ff…` | `dmt_SelectControl.getCurrentDocumentInfo` |
| `document.current.active` | `b4298962367251c8` | `page` | `b4298962…@ea80ff…` | `dmt_SelectControl.getCurrentDocumentInfo` |

`document.current.type` = `sch`（修复前在这里会答 `unknown`），`typeSource` 指名直读、
`heuristic:false`。**同时拿到旧缺陷的直接证据**：`tabs` 为
`[('Start Page', None), ('P1.Schematic1', None)]` —— 标签树的 `documentType` 全是 `None`，
旧逻辑除了 `unknown` 无话可说。

### 第 3 项 — 已验 ✅（连续 5 次冷启动，08:36–08:59，岳翔宇在场逐次重启）

**5/5 零点击 connected。** 每一轮的形态完全一致：旧 socket `disconnect` → 10~19 秒后
**单个** `EDITOR connect` → 同一秒 `hello ok=True`（`connector=0.4.1`）。

| 轮 | 旧实例掉线 | 新实例自连 | 间隔 | 配对事件 |
|---|---|---|---|---|
| 1 | 08:36:09 | 08:36:23 | 14 s | 无 |
| 2 | 08:55:21 | 08:55:34 | 13 s | 无 |
| 3 | 08:56:31 | 08:56:50 | 19 s | 无 |
| 4 | 08:57:50 | 08:58:02 | 12 s | 无 |
| 5 | 08:58:39 | 08:58:49 | 10 s | 无 |

**窗口内汇总**（08:27 起，含侧载那次）：`EDITOR connect` 6 次 = 1 次侧载重配对 + **正好 5 次冷启动**；
`hello ok` 6 次、**失败 0 次**；`pairing`/`re-pairing` 仅 `08:27:16` 一条 ——
**五轮冷启动一次配对事件都没有**，即五轮都复用同一存量 token（指纹恒为 `46b59031`）。

**判读方式**（不只看 `status: connected`，否则一次手动点击也会看起来像成功）：每轮看三件事——
① 旧 socket 是否 `disconnect`；② 随后是否**只有一次** Editor `connect`（多于一次 = 有人点过）；
③ 是否出现 `pairing`/`re-pairing`（出现 = 多消耗了一次配对，不是零操作）。
五轮三项全部符合预期。**这是 0.2.5 以来第三次复现的那个盲区，至此关闭。**

### 顺带记录的真机事实

`document.current.schematicPage` 在本次读取中 `Name` 为空（`null`）——**与本轮改动无关**
（该字段是既有的 `snapshot()` 路径，未改），但记下来：若要靠它拿页名，先按"可能为空"处理；
拿页名应当走 `doc.list`（那里逐条正确）。

---

## 验收戳（004f 正式收官，2026-09-16，Kimi）

**离线复验（Kimi 亲跑）**：Python **372** / connector **167** / `tsc` 干净（与报告一致）；
0.4.1 包 `testzip`+md5 双验通过。

**五条验收逐项独立复核**：

1. **文档更正** ✅ —— bridge.md §10.24（`sys_Storage` 全局共享实测结论）、§10.25（bootstrap
   根因：未 catch 的 `void bootstrapAtModuleLoad()` + host 未绑定时的静默 stand-down）、
   §12 证据清单补 wiring 测试行，均在文。
2. **侧载重配对自愈** ✅ —— 审计实测：08:26:30/51 两次 `UNAUTHENTICATED` → 08:27:16
   **`re-pairing`** → 后续 hello 全 ok。**Kimi 今日零手工 revoke**，指纹 6d87bbd1→46b59031
   是自愈完成的。
3. **bootstrap 5/5 冷启动** ✅ —— 审计窗口内 `re-pairing` 总数恒为 1（即只有 08:27 那次），
   五轮冷启动全为"存量 token 直连、零配对事件"，与 DeepSeek 表格一致。
4. **document.current 与 doc.list 一致** ✅ —— Kimi 真机双测：空白前台时两侧同报
   `uuid 0`；`doc.open` P1 后两侧同报 `b4298962367251c8 / page`，`type: sch`，
   `heuristic: false`。旧缺陷（标签树推不出 type）关闭。
5. **connectorVersion 留痕** ✅ —— 审计 hello 行带 `connector=0.4.1`。

顺带核销 006c 欠账（doc.open 真机跳转）✅。

**004f 验收通过。** 桥加固三件套 + 增补两项全部落地。

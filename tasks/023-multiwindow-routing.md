# 023 多窗口路由（向 easyeda-agent 看齐）

> 岳（2026-09-22 ~17:10）："多窗口的方案你这个太妥协了，还有谁跟你说我们是单窗口了？
> 只要是硬件工程师一次开三四个窗口就是家常便饭。我希望今晚多窗口能向 easyeda 看齐。"
>
> 目标：daemon 从「单活跃防护」升级为「多连接注册 + 按工程路由」——
> 岳开的三四个窗口全部连上，AI 用 `--project` 指哪打哪，不再要人去点窗口。

## 上游架构实测摘要（证据：`.tmp_upstream_hub.go` / `.tmp_upstream_dispatch.go`，zhoushoujianwork/easyeda-agent `internal/daemon/`）

1. **Window 是一等公民**：每个 connector 连接注册 `windowID + Context{ProjectUUID, ProjectName, DocumentUUID, DocumentType, TabID, Unit}`，hub 持有全部连接。
2. **context 永葆新鲜**：connector 在**每个 action response 里附 live context**（`applyResponseContext` 合并非空字段），另有主动 ContextMessage——用户切文档，路由信息不冻结。
3. **路由**（`dispatch.go:168-243`）：显式 `windowId` 直达；`--project` hint → `windowForProject`（name/uuid 匹配：单匹配直达；多匹配按动作文档域 narrow；同 tab 重复连接选最新；否则 ambiguous 报错列候选）；旧 windowId 失效按 project 重路由（`resolveRetired`）；窗口未连报错列出"哪些窗口在线"。
4. **并发**：`acquireExclusive(action, windowId)` per-window 写互斥，跨窗口并行。
5. **去重**：同 project+document+tab 的重复连接（重连/3.2.175 双激活）保留高版本或新 socket。

## 我们的现状（改造起点）

- `src/boardwise/bridge/daemon.py`：018 单活跃防护——第二个连接 `CONNECTOR_ALREADY_ACTIVE` 拒绝。**这就是要拆掉重建的东西**。
- `src/boardwise/bridge/protocol.py`：`Connection` 已有 `project_name`/`project_uuid`（021 加的）。
- connector（`connector/src/transport.ts`）：hello 已带 `projectName`/`projectUuid`（021）。
- CLI：`bridge call --action X --params JSON`；`bridge status` 有 `projects seen` 雏形。
- 我们的 daemon 是裸 WebSocket（无上游的 HTTP 层），CLI↔daemon 也是 WS（role=client）。

## 设计（Kimi 定，两棒接口以此为准）

### 协议字段约定

1. **connector→daemon response 帧**：顶层加可选 `context` 字段：
   `{"projectName": "...", "projectUuid": "...", "pageUuid": "...", "pageType": "sch"|"pcb"|null}`
   每个 action 响应现读现附；读不到的键省略（null 不覆盖已知值——同上游 merge 语义）。
2. **CLI→daemon 请求帧**：顶层加可选 `targetProject`（工程 name 或 uuid）。
   daemon 路由后转发给选中的 connector；不带则按默认规则。
3. hello 已有 `projectName`/`projectUuid`（021），继续保留，作为连接初始 context。

### daemon（棒 1，Python）

- **hub 注册表**：全接纳通过 pairing/token 校验的 connector（**拆除 018 拒绝逻辑**，
  `refuse_if_held` 删除或改写为登记）；`instanceId` 为连接键（windowId 语义）。
- **context 簿记**：hello 初始化 + 每个 response 的 `context` 合并非空字段。
- **路由**：
  - `targetProject` 给定时：按 name/uuid 匹配连接——1 个直达；0 个 → 错误 `PROJECT_NOT_CONNECTED`，
    消息列出在线窗口清单（`projectName (instanceId)`）；>1 个 → 错误 `PROJECT_AMBIGUOUS` 列候选。
  - 未给定时：1 个连接直达；>1 个 → 错误 `WINDOW_UNSPECIFIED` 列候选（诚实，不瞎猜）。
  - 连接断开（WS close）即除名。
- **per-window 写互斥**：同一连接的写动作串行（现有单连接时的串行语义自然推广；动作白名单沿用现有 read/write 分类）。
- **status**：列出全部在线窗口（instanceId + projectName/Uuid + connectedAt + lastSeen）；
  `projects seen` 行升级为在线窗口表。
- **018 的防护精神保留**：审计日志记录每个连接的 hello/断开/被路由次数；CLI `bridge status` 可见全部窗口——"看不见"才是真正的风险。

### connector（棒 2，TypeScript）

- 每个 action 响应帧附 `context`（见协议约定）：从动作执行时的 eda 上下文现读
  （复用 `currentProjectIdentity` + 当前文档信息；读不到省略键，**永不抛、永不编造**）。
- 响应路径加 context 不得破坏既有动作的结果形状（context 在帧顶层，不在 result 里）。
- 单测：mock eda 下 response 帧带 context；读不到时省略；pageType 词汇与 daemon 一致。

### CLI（棒 1）

- `bridge call --project NAME_OR_UUID --action ... --params ...`（映射到 `targetProject`）。
- `bridge status`：多窗口表。

### 今晚不做（列出防膨胀）

- retired window 重路由（窗口 reload 后旧 id 找回）——先报错列在线窗口；
- 同 tab 重复连接去重（3.2.175 双激活）——先 ambiguous 报错，人能看到；
- connector 主动推 context change（切文档即时刷新）——response 回流已够用；
- review/draw/edit 高层命令的 --project 适配——bridge call 层先通，适配列下一棒；
- 多窗口并发写的健康观测（writeHealth 上游有，我们从简）。

## 红线

- 禁地工程（反激辅助电源、毕设FOC、CH340G、ROBOT ctrl FOC 等一切真实工程）：真机只读，写动作只在 test/test2。
- 不动 git；pytest `--basetemp=.tmp_pt_023a`（棒1）/ connector `npm test` 子集（棒2）；写文件显式 UTF-8；
  证据 `outputs/023_*`；不碰 tests/fixtures。
- 真机三窗口验证由 Kimi 做（岳环境现成：/test、test2、反激辅助电源）。

## 验收

1. 单测：hub 注册/路由（直达/ambiguous/未连接列在线）、response context merge、断开除名、per-window 互斥；CLI --project。
2. 真机：三窗口全连上；`bridge status` 列三工程；`--project test2 doc.list` 通；
   `--project 反激辅助电源 sys.identity` 只读通；不带 --project 多连接时报错列候选；
   写 test2 成功且 test/反激辅助电源零影响（R1 全程）。
3. 三线全绿（pytest / connector npm test / tsc）。

## 交卷记录

（子代理交卷后追加）

### 棒 2 · connector（2026-09-22，子代理交卷）

- 改动：`connector/src/{protocol,transport,actions,index}.ts` 修改，新增 `connector/tests/context.test.mjs`；
  **未碰** `src/`、`tests/`（Python）与 docs（棒 1 范围）。
- 协议落地：每个 action 响应帧**顶层**附 `context`，四键
  `projectName` / `projectUuid` / `pageUuid` / `pageType`（`"sch" | "pcb" | null`；
  原理图页 -> `sch`，PCB -> `pcb`，词表与 `document.current` 逐字一致）；
  `data`（动作结果）形状一个字节未变 —— 单测钉住。
- 唯一收口点：`Transport.reply()` —— 成功帧、ActionError 帧、INTERNAL 帧、
  "请求帧无 action"的 BAD_REQUEST 帧共用；在 action handler **之后**现读现附
  （`doc.open`/`doc.focus` 之后报告的是新文档）。
- 防抛/超时：整段 context 读取由 transport 侧 `readWithDeadline`（1500 ms，同 021 hello 模式）
  包住，抛异常/永不 settle = 对应键省略，绝不拖住已执行完的动作响应；帧侧再按词表清洗。
  读不到时**省略键**（不是空值、不是 `null`、不会沿用上一次读数）。
- 工程身份复用 `currentProjectIdentity`；当前文档复用 `activeDocument`（`doc.list`/
  `document.current` 那套共享读，含宿主占位 uuid `"0"` 的"未聚焦"语义）。
- 证据：`outputs/023_connector_context.txt`（UTF-8；含逐字响应帧样例、两组变异抽验与还原哈希）。
- 两线：`npm test` **325 / 325 全绿**（既有 310 + 新增 15）；`npm run typecheck` 干净；
  `npm run build` 成功且 `dist/index.js` 含新代码。
- 交棒 1：daemon 侧读 `context` 合并非空字段（`null` 不覆盖已知值）；另注意
  `src/boardwise/bridge/protocol.py` 模块 docstring 里 "results in `data` instead of
  `result`/`context`/`artifacts`" 一句与 023 新增的顶层 `context` 读起来有歧义，措辞由棒 1 定。

### 棒 1 · daemon / protocol / CLI（2026-09-22，子代理交卷）

- 改动：`src/boardwise/bridge/{daemon,protocol,client}.py`、`src/boardwise/cli.py`、
  `tests/test_bridge.py`、`tests/test_bridge_cli.py`、`docs/bridge.md`、
  `.kimi-code/skills/boardwise/SKILL.md`。**未碰** `connector/`、未动 git、
  未重启 daemon（PID 27208 仍是旧代码，新代码等 Kimi 重启后生效）。
- hub：`WindowConnection` 注册表，键 = `hello` 的 `instanceId`（同 id 双活时第二条加 `~2` 后缀、
  两条都留，审计记 `duplicateInstanceId`）；`refuse_if_held` / `RejectionNotice` / `on_rejection` /
  `recent_rejections` / `active_instance()` / `ActiveConnector` 全删；死 socket 复用原 key
  （`tookOverFrom` = reload 路径）。配对口径随之变成"任一在线窗口即视为 attached"，强度不变。
- context 簿记：`hello` 初始化 + 每个 response 帧顶层 `context` 合并非空键
  （`protocol.merge_context`：null / 空串 / 非字符串 / 非字典 / 未知键一律不动已知值；
  `pageType` 原样记录、不翻译、不校验词表）。中继给 CLI 的 response/error 帧顶层带
  `context` = 应答窗口的实时身份（旧连接器无 context 时用 hello 上下文填）。
- 路由三态（逐字消息见 `outputs/023_daemon_routing.txt`）：命中 1 个直达（name 或 uuid 均可）；
  0 个 → `PROJECT_NOT_CONNECTED` 列 `projectName (instanceId)`；>1 个 → `PROJECT_AMBIGUOUS` 列候选且
  一个字节都不转发；无 hint 多窗口 → `WINDOW_UNSPECIFIED` 列候选；无 hint 且只有一个窗口 = 023 前
  行为逐字节不变。一个窗口都没连时（带不带 hint）仍是 `NO_CONNECTOR`（见证据文件"偏离"1）。
- per-window 写互斥：写动作取该窗口的 `asyncio.Lock`，读动作不取锁，跨窗口并行；
  pending 调用记住目标窗口，响应只接受"我发给的那个窗口"的帧（id 只算相关性、不算证明）。
- status：`ping` 返回 `windows[]`（windowKey / instanceId / instanceIdSource / client /
  connectorVersion / peer / connectedAt / lastSeen / routed / projectName / projectUuid /
  pageUuid / pageType，可选值一律 `null` 而非缺键）；`status_lines` 每窗口一块，
  `projects seen:` 升级为在线窗口表（带 windowKey）。旧 `activeInstance` / `recentRejections` 键移除，
  不做兼容层。
- 审计：`hello` 加 windowKey / tookOverFrom / duplicateInstanceId / windowsOnline；
  每条被转发的动作记录加 windowKey + projectName；`disconnect` 加该窗口最后已知的工程/页/routed。
  退役名保留两个：`ErrorCodes.CONNECTOR_ALREADY_ACTIVE`（§5 表已标退役）与
  `daemon.AUDIT_CONNECTOR_REJECTED`（不在 `__all__`）——旧日志与在野连接器读得到，删了反而"查无此码"；
  用例 `test_the_refusal_machinery_is_gone_and_its_code_is_retired` 钉住"机制不许回来"。
- CLI：`bridge call --project NAME_OR_UUID`（写进顶层 `targetProject`，**绝不进 `params`**；
  确认重试走同一个 hint）；`--params` / `--yes` 行为不变。

#### 顺手核了棒 2 的接口（只读 `connector/`，未改一行）
- `connector/src/transport.ts:496 reply()` 用 `withContext(frame, …)` 把 `context` 放在**帧顶层**，
  与 daemon 的读取位置一致；error 帧同样带，而 daemon 对 `ok:false` 的响应帧一样合并 context。
- `hello` 仍带 `instanceId`（`transport.ts:372`）与 `projectName`/`projectUuid`（`573-577`），
  hub 的初始 context 有来源。
- 棒 2 交棒的两点都已满足：合并非空字段；`protocol.py` 那句 docstring 已改写为
  "results in `data` instead of `result`/`artifacts`（`context` 保留为 `data` 的顶层兄弟，023）"。

#### 测试与三线
- `pytest tests/test_bridge.py tests/test_bridge_cli.py -q --basetemp=.tmp_pt_023a` → **103 passed**
  （`tests/test_bridge.py` 单跑 72 passed；018 段的用例按新行为改写，没有删了事）。
- `pytest tests/ -q --basetemp=.tmp_pt_023a_full` → **1312 passed**（全量回归，确认无连带破坏）。
- `cd connector && npm test` → **325 / 325**；`npm run typecheck` → 干净。（这两条是棒 2 的产物，
  本棒只复跑确认没被连带打坏。）
- 新用例覆盖验收 1 全项：注册（两窗口均 ok，无人被拒）、路由三态、context merge（含 null 不覆盖）、
  断开只除名该窗口、per-window 互斥（同窗串行 / 异窗并行 / 读不取锁）、响应窗口身份校验、
  同 instanceId 双活、reload 复用 key、CLI `--project` 端到端（真 daemon 子进程 + 两个假窗口）。
- 证据：`outputs/023_daemon_routing.txt`（真实帧 + status 渲染 + 审计原文 + 逐字错误消息 +
  偏离与遗留清单，UTF-8）。

#### 遗留（请 Kimi 真机验证；daemon 必须先重启）
1. 三窗口 /test、test2、反激辅助电源 全连上 → `bridge status` 三块 `window:` + `projects seen:` 三工程。
2. `bridge call --action doc.list --project test2` 通；`--project 反激辅助电源 sys.identity` 只读通。
3. 不带 `--project`（三窗口）→ exit 1 + `WINDOW_UNSPECIFIED` 列候选；不存在的名字 → `PROJECT_NOT_CONNECTED`。
4. 在某个窗口里切工程后再用**新**工程名 `--project` → 仍命中（daemon 侧链路已通，真机首次验真机 context）。
5. 写 test2 成功且 test / 反激辅助电源 零影响（R1：写前 `doc.list` 焦点工程逐字）。
6. 待裁定：真机若出现"同工程两个窗口"，`PROJECT_AMBIGUOUS` 与 `~2` 后缀在错误消息里的可读性是否够
   ——这是设计上留给"人能看到"的诚实代价，不是 bug。

### 棒 3 · 按 instanceId 直达窗口（2026-09-22，子代理交卷）

- 动机（真机实测）：编辑器重启后窗口先 hello、API 后可用 → 三个窗口 context 全 null →
  `--project` 谁也匹配不上，**此时没有任何手段选中一个窗口**（连热更都做不到：
  `update-connector` 无 hint 多连接会 WINDOW_UNSPECIFIED）。上游 easyeda-agent 的解法是
  `req.WindowID` 显式直达（`dispatch.go:196` `hub.target(windowID)`），本棒对齐它。
- 协议：请求帧顶层新增 `targetInstance`（与 `targetProject` 并存；两个都给时 **instance 优先**——
  实例精确到一条连接，工程名可能被多个窗口共用）。`request_frame` / `BridgeClient.call` /
  daemon 转发路径三处贯通；hint 仍**绝不进 `params`**。
- daemon `route()`：instance 分支放在最前（无窗口仍 NO_CONNECTOR）→ `window_for_instance()`
  先比 **key** 再比 **instanceId**：命中直达；未命中抛 `ErrorCodes.WINDOW_NOT_CONNECTED`，
  消息 `no connected window is instance 'X'; online windows: <projectName (key)>`，detail 带
  `targetInstance` + `candidates`（格式与 PROJECT_NOT_CONNECTED 一致）。同 instanceId 双活按 key
  精确匹配即可（`inst-x` → 先注册者，`inst-x~2` → 后者），不做歧义处理。
  顺带：`PROJECT_NOT_CONNECTED` / `WINDOW_UNSPECIFIED` 消息末尾补一句"也可用 `--instance`"
  （真机死胡同里，只说 `--project` 等于把人留原地）。
- CLI：
  - `bridge call --instance INSTANCE_ID`（写顶层 `targetInstance`；与 `--project` 同给时两个都发）。
  - `bridge update-connector --instance INSTANCE_ID`：写动作路由到该窗口（帧顶层），
    头行打印 `-> window INST`（reload 后没人能问"是哪个窗口"）。
  - **verified（020）在 --instance 下的语义**：窗口 reload 后以**新 instanceId** 重连，旧名字已不
    存在，故回读改走 daemon 自答的 `ping` windows 表 —— 任一在线窗口报到刚写入的版本 = verified
    (0)；被指名的窗口仍以自己的 key 在线且报旧版本 = FAILED (1)；预算内无匹配 = UNKNOWN (3)。
    不带 `--instance` 时回读一个字节未变（仍是 `sys.probe` 单连接读法）。代价写进 docs §8：
    该读法只能证明"某个窗口在跑新版本"，不能证明"就是那个窗口"。
- 测试：`pytest tests/test_bridge.py tests/test_bridge_cli.py -q --basetemp=.tmp_pt_023b` → **112 passed**
  （基线 103；新增 9：instance 直达无工程场景 / 未命中列在线 / instance 压过 project / `~2` 双活可寻址 /
  请求帧三键契约 / update-connector --instance 成功·FAILED·UNKNOWN 三态 / CLI 端到端 + flag 接线，
  并改了 3 处旧文案断言）。全量 `pytest tests/ -q --basetemp=.tmp_pt_023b_full2` → **1321 passed**
  （基线 1312）。变异抽验 2 处（`route()` instance 分支失效 → 6 红；`_reloaded_window_version`
  的 verified 分支失效 → 1 红），`cp` 还原后 sha256/cmp 字节一致再复跑全绿。
- 证据：`outputs/023_instance_routing.txt`（真实 WebSocket 帧：直达命中 / 三态错误逐字 / 审计行 /
  变异哈希 / 语义与遗留）。docs：`docs/bridge.md` §2 §3.1 §3.5 §5 §8 §10 §12 §13；
  skill `.kimi-code/skills/boardwise/SKILL.md` §2/§5 补 `--instance`。
- 未碰：connector/、tests/fixtures、git；未重启 daemon（PID 11732 跑旧代码，**新动作必须先重启才生效**）。
- 遗留：① 真机未验（需重启 daemon 后按 docs §13 E3：三窗口 + 重启编辑器 context 全 null 场景，
  `--instance` 应直达而 `--project` 应报未命中）；② `update-connector --instance` 真机三态未验（写操作）；
  ③ --instance 的 verified 无法绑定"回来的连接 = 被更的窗口"（需 connector 侧提供跨 reload 稳定的窗口
  标识，下一棒）；④ 对 pre-023 daemon（`ping` 无 `windows` 键）`--instance` 会被忽略且回读落到 exit 3
  UNKNOWN（诚实但仍需升级 daemon）；⑤ review/draw/edit 高层命令未加 `--instance`（沿用 §今晚不做）。

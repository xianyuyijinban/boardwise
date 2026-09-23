# 026 — Worker watchdog：实现批任务书（v1，形态 A）

> 2026-09-23 定稿。前置：probe 批结论（`outputs/026_probe.md`、本任务书系列 §六）——
> **形态 A（Worker 闹钟）定案**：Worker 可起（P1）、Worker 里无 `eda`（P2，形态 B 出局）、
> 页面后台时钟压到整分钟级而 Worker 153/153 一次不落（P3）、宿主 `sys_Timer` 同吃节流（P5）。
> 本批把 probe 结论变成产品行为：**后台窗口的 connector 不再"永不回来"**。

## 一、要治的病（行为定义，不是猜测）

| 状态 | 页面定时器 | 现状（无 watchdog） | 目标（有 watchdog） |
|---|---|---|---|
| 前台 | 正常 | 正常 | 不变 |
| 后台（节流态，P3 实测） | 压到 ~1 次/分钟 | 心跳慢到分钟级（daemon 容忍，半开）；daemon 重启后重连退避也吃节流 | **至多落后一个节流周期（≤ ~70 s）就重连** |
| 冻结态（7 小时事故态） | 全停 | **永不重连**（025 批 2 实测 7 小时，前台化才自愈） | 解冻瞬间立即重连（wake 已排队，不等退避） |
| 页面被丢弃 | 全死 | 无解（Worker 同死） | 无解——如实声明，不假装覆盖 |

诚实边界：P3 证明 Worker 在**节流态**免疫；**冻结态 Worker 是否也活**没有受控复现
（probe 未做 #2）——实现批的真机验收只承诺节流态指标 + 解冻即连，不许吹"冻结态必活"。

## 二、批 2a：P6 探针 + 形态 A 实现 + 单测 + 清理

### P6 前置探针（小，但必须先做——它决定有没有 B' 这条路）

`sys.worker_probe` 加 `nativeWs` 模式：**页面与 Worker 各自** `new WebSocket('ws://127.0.0.1:61190/eda')`：
- 页面侧：原生 WS 能不能连 daemon（CSP connect-src 是未知数）；
- **Worker 侧**：能连 ⇒ 存在"形态 B'"（transport 整体入 Worker、页面只做 eda 执行器）——
  **本批不实现 B'**，只在 probe 报告补一行"可行/不可行 + 理由"，供后续评估；
  不能连 ⇒ 形态 A 是唯一解，probe 报告 likewise。
- 探完如实记，不许编（同 P1–P5 纪律）。

### 形态 A 实现（connector 内部，daemon 零改动）

1. **所有权**：Watchdog Worker 挂在**共享 transport 运行时**上（024b 的
   `SHARED_RUNTIME_MEMBERS` 同款纪律）——菜单点击会重求值 bundle，**每次求值各起一个
   Worker 就是泄漏**。必须有"已存在即接管/不重复创建"的单例语义，且 `stop()` 连 Worker
   一起 terminate（现有"stopped transport sends nothing"断言扩展到 Worker）。
2. **活性协议**（全部走 `postMessage`，无共享状态）：
   - 页面侧 transport 每次活动（heartbeat 发送、收到任何帧、重连尝试、connect 成功）
     向 Worker 报一个 `{type:'activity'}`（fire-and-forget，不await）；
   - Worker 每 **15 s** 检查一次 `now - lastActivity > 45 s`（心跳 5 s × 3 miss 的 3 倍，
     余量覆盖节流周期），超了就每拍发 `{type:'wake'}`，直到活性恢复；
   - 页面收到 `wake`：transport 未连接 → **立即 `connect()` 并复位退避**；
     已连接但心跳逾期 → 立即补一次心跳；一切正常 → 只回活性戳。
3. **降级**：`new Worker` 失败（CSP 变了、宿主禁了）→ 回退现状（无 watchdog），
   About 加一行 `watchdog: running|unavailable(<原因>)`，不许静默。
4. **清理（probe 批去留已裁）**：`sys.worker_probe` 删 `worker`/`pageTimer`/`workerTimer`/
   `hostTimer` 四个测量模式 + P6 用的 `nativeWs` 模式；`status` 改名 **`sys.connector_status`**
   独立成动作（不再叫 probe），doctor 第八项后加为第九项？——**不**，先不动 doctor 检查数：
   本批只把 `sys.connector_status` 注册为正式只读动作并入 bridge.md 目录，doctor 集成留给
   下一批（避免一次改太多面）。
5. **文档**：bridge.md §7 重写（watchdog 机制、三态行为表、诚实边界）+ §4 目录
   （`sys.connector_status` 正式、`sys.worker_probe` 删除）+ About 新行。
   connector 0.4.17。

### 单测（connector mock，全离线）

- Worker 可注入（`globalThis.Worker` 替换，同 `BOARDWISE_TOKEN` 注入套路）；
- 沉默 ≥45 s → 页面收到 wake → 未连接时 `connect()` 被调且退避复位；
- 重求值场景（模拟 024b 的 fresh evaluation）→ **不重复创建 Worker**（单例断言）；
- `stop()` → Worker terminated、之后零消息（对齐现有 stopped-transport 断言风格）；
- `new Worker` 抛错 → 降级路径 + About 行报 unavailable；
- 变异 ≥2：① watchdog 收到 wake 不动作（假闹钟）；② 每次求值都新建 Worker（泄漏）——
  都必须有测试咬住。

## 三、批 2b：真机验收 + 文档收官

1. **节流态恢复**：test 窗口压后台（probe 批的抢前台方法，`.tmp_026_fg.py` 模式）→
   重启 daemon → 测 time-to-reconnect。**基线**（无 watchdog）：≥ 数分钟或永不；
   **目标**：≤ 90 s（一个节流周期 + 余量），audit 时间线作证。
2. **解冻即连**：后台 10 分钟后回前台 → 已在 wake 驱动下先行重连（audit 里 reconnect
   早于前台化时刻）。
3. **三窗口**：两窗压后台一窗前台，重启 daemon，三窗全部回来。
4. **前台回归**：正常操作（checkup 全链）零变化；geometry/doc.list 零残留。
5. **149 验证**（岳工作电脑，列为交付物之一）：第二个窗口能不能上线——
  若上线，issue #4 的多窗口症状关闭；若仍不上线，如实记"149 第二窗口是另一层病"
  （bootstrap 级，watchdog 管不到），不硬吹。
6. bridge.md §7/§10.22 同步、SKILL 坑表加 P5/抢前台两条、PROGRESS 更新。

## 四、验收（两批合并判）

- 三线全绿（pytest `--basetemp=.tmp_pt_home` / connector / tsc）；
- P6 结论入 `outputs/026_probe.md`（补节，不改原结论）；
- 批 2b 真机证据落 `outputs/026b_*.txt`（节流恢复时间线、三窗口、零残留复核）；
- 变异 ≥2（批 2a 指定两靶）；
- 真机只碰 test/test2；不动 git；文件显式 UTF-8。

## 五、守卫

- **daemon 一行不改**：watchdog 是 connector 内部机制，协议帧零变化——若发现需要
  daemon 配合，停下来报主代理（架构约束）。
- Worker 脚本必须内联（blob），不引外部文件（eext 单文件分发改不起）。
- 禁止向 Worker 转发任何 `eda` 调用（P2 已证不可行，别留"将来也许"的转发脚手架）。
- About 的 watchdog 行只报事实（running/unavailable+原因），不许报"免疫"。

## 六、交卷记录

### 026b 批 2a · 交卷（2026-09-23，子代理 agent-43）

- 范围：P6 探针 + 形态 A 实现 + mock 单测 + 清理；**未碰真机**、未动 git；批 2b 未做。
- 交付：`connector/` 0.4.17。新模块 `src/watchdog.ts`（Worker 闹钟 + 页面半边 + 降级 + stop 连带 terminate）；
  `transport.ts` 四处活性上报 + `wake()` 四分支 + `reconnectNow()`；`index.ts` `ensureWatchdog()` 单例
  （挂 024 共享运行时）+ About `watchdog:` 行 + `ConnectorStatus.watchdog`；`actions.ts` 删 4 个测量模式（−703 行）、
  `status` 转正 `sys.connector_status`、`sys.worker_probe` 只剩 `nativeWs`（P6）；`protocol.py` + `docs/bridge.md`
  §4/§6/§7 同步（§7 重写为 7.1：机制 + 三态表 + 诚实边界 + 单例）。
- 三线（交付态）：pytest **1388 passed**（基线同数）· connector **418 pass / 0 fail** · `tsc --noEmit` 干净；
  dist `sha256 8fe4f591…`，**256827 B**。
- 变异 **2/2 CAUGHT**：①`Transport.wake()` 收了 wake 不动作 → 5 红；②删 `ensureWatchdog` 单例守卫 → 2 红；
  还原 sha256 `transport.ts ae9ae2bf…`、`index.ts 85157990…`（cp 备份 + cmp 一致，未用 git checkout）。
- P6：**daemon 侧实测通**（Node 原生 WebSocket 51 ms 连上、54 ms 收 banner，无子协议要求，
  `outputs/026b_p6_offline.txt`）；**页面/Worker 侧待批 2b**（CSP 是页面内事实，用
  `sys.worker_probe {"mode":"nativeWs"}` 测）。探针两半跑同一段代码，`verdict` 三档不许合并。
- 2b 前置：`sys.connector_status` 是新目录项，**先重启 daemon** 才能 `bridge call` 到它。
- 未做（属 2b）：SKILL 坑表 / PROGRESS / §10.22 同步；doctor 集成（§2.4 明确本批不动）。

### 主代理复验（2026-09-23）

- 亲手复跑三线：pytest **1388 passed**（114.5s）· connector **418 pass / 0 fail** · tsc 干净——与交卷一致。
- sha256 抽核一致：dist `8fe4f591…`（256827 B）、`transport.ts ae9ae2bf…`、`index.ts 85157990…`。
- **裁决**：`nativeWs` 保留为 `sys.worker_probe` 唯一模式（PROBE-ONLY），批准——批 2b 的 P6 页面侧判定
  依赖它，2b 跑完即删；任务书 §2.4 的"删净"以本裁决为准顺延到 2b。

### 026b 批 2b · 交卷（2026-09-23，子代理 agent-43；第 1–4、6 项，第 5 项归岳）

- 前置：热更 0.4.17（exit 0，`verified`）→ 重启 daemon（`sys.connector_status` 真机跑通，证明新目录生效）。
- ① 节流态恢复：**目标未达成**。三次实测重连 151.5 s / 135.5 s / 139.7–145.5 s（三窗口那次三窗全回），
  全部 > 90 s。重连者是 watchdog（`lastError: watchdog wake (worker alarm after 5920x ms of page
  silence): 3 heartbeats unanswered`；`state: running, wakes 6→14`）。门是 `heartbeatMissLimit=3`
  × ~60 s 节流心跳 ⇒ 批 2c 把"wake + 有未答心跳"直接判死（主代理已裁，见下）。
- ② 解冻即连：成立——重连发生在后台（17:57:1x），比回前台（17:59:45）早 2 分 28 秒，回前台后 90 s
  无新重连。**偏差**：hold 实测 4 分 47 秒（脚本卡死，未达任务书 10 分钟要求）。
- ③ 三窗口：test + test2 + 岳的 ROBOT 窗，三窗全回（139.7 / 145.4 / 145.5 s）；压后台只压非禁地窗口，
  所有调用显式 `--project`。附带发现：新开的第二窗口**上线但不报工程名**（3 s 上线、`projectName=None`，
  重连后才报 test2）——3.2.186 上的"第二个窗口"是"匿名上线"而非"不上线"。
- ④ 前台回归：checkup 与 025c 基线**逐行一致**，geometry/doc.list 零残留。
- P6 真机：**两半都通**（页面 5 ms、Worker 19 ms 各收到 daemon banner）⇒ 形态 B′ 在连通性层无障碍；
  未测应用层 hello/配对。已补进 `outputs/026_probe.md`（补记，不改原结论）。
- 文档：`docs/bridge.md` §7.1 加"第一次真机测量"、§10 第 1 条与第 22 条各补实测；
  `SKILL.md` 坑表加第 19 条（宿主 `sys_Timer` 同吃节流）、第 20 条（抢前台方法）。
- 三线：pytest 1388 · connector 418/0 · tsc clean；dist sha256 `8fe4f591…` 未变（2b 未改代码）。
- 证据：`outputs/026b_2b_{prereq,throttled_recovery,thaw_reconnect,three_windows,checkup_regression,
  p6_nativews,connector_status}.txt`。

### 主代理复验与裁决（2026-09-23）

- 抽查：7 份证据文件齐；`git status` 仅 SKILL.md + bridge.md 两改动（PROGRESS 未被碰 ✔）；
  坑 19/20 原文在表；`watchdog wake` 原文在节流证据中 ×2。
- **裁决 1（批 2c 规格变更，批准）**：wake 触发时若已有任何未答心跳（`missed > 0`）即判死并
  `reconnectNow()`，不等 `missLimit=3`。依据：socket 活着时 daemon 的 pong 会立即回页刷新活性，
  根本攒不到 45 s 静默；"wake + 有未答心跳"已是强死亡证据。预期恢复 ~45–60 s，达 ≤90 s 目标。
- **裁决 2（批准删）**：`sys.worker_probe`（nativeWs）使命完成（P6 两半真机实测），批 2c 删净。
- 遗留：`test2` 窗口留开（岳自行处置）；第 5 项 149 第二窗口验证归岳。

### 026c · 交卷（2026-09-23，子代理 agent-43）

- **裁决 1 实现**：`Transport.wake()` 的 `connected` 分支改为「`missed > 0` 即判死 → `reconnectNow()`」，
  原「先补 ping 等 missLimit」分支删除；`missed = 0`、connecting/handshaking、idle/reconnecting 三支语义不变。
- **额外修复（主代理已追认，见下）**：`reconnectNow()` 原走 `scheduleReconnect(reason, 0)` = `setTimeout(…,0)`，
  而节流页面会把 0 延时定时器一起压到下一拍 ⇒ 「立即重连」里藏着最多一整拍（≈60 s）。现改为
  `dropAttempt(reason)`（清定时器/关 socket/置 reconnecting/写日志与 lastError）+ **直接 `connect()`**（同步注册）。
  诊断依据：三次复测中两次 101.3 s / 96.7 s，与验收目标直接冲突。mock 新增同步性钉子用例。
- **删净 `sys.worker_probe`**：actions.ts（动作+两个 helper+worker 源码，−250 行）、protocol.py 目录、bridge.md §4 行、
  P6/退役模式用例；新增「registry 里已无该动作」用例。真机实证：`UNKNOWN_ACTION unknown action 'sys.worker_probe'` ✔，
  对照 `sys.connector_status` 仍可用 ✔。P6 证据文件与 `026_probe.md` 的 P6 节未动。
- **SKILL 第 21 条**（工具坑①②）已加；**PROGRESS 未动**。版本 0.4.18，dist `2e047a6a…`（252952 B），已热更到 test 窗口。
- **真机复测（5 次，压后台 + 杀 daemon + audit 量 hello）**：
  A 62.8/57.9、B 114.9/60.6（该次 daemon 自身慢启动 54.3 s）、C 101.3/96.7、D 93.4/88.8、E 74.6/70.0（秒；kill/监听两口径），
  判死分支五次全是 `1 unanswered heartbeat(s)`，wake 报告静默 48.5–51.1 s。
  ⇒ **连接器自身份额 48.5–51.1 s 达标（预期 45–60 s，2b 为 135–152 s）**；**kill→hello 总时长受页面节流相位支配，
  2/5 命中 ≤90 s**（监听口径 4/5）。不凑数，五次全记。D 次同刻对照：未节流的 ROBOT 窗 24 s 回来，
  被压最底的 test 窗 93 s——同一 daemon 同一杀法，差别只在页面是否被节流。
- 变异 CAUGHT（指定靶，404 中 3 红）；还原 `transport.ts 88e6940b…`（cp 备份 + cmp 一致）。
- 三线：pytest 1388 · connector 404/0 · tsc clean。前台回归：checkup 与 025c 基线逐行一致，零残留。
- 遗留：test2 与 ROBOT 窗口仍跑 0.4.17（等各自页面 reload 自然升级）；test2 窗口未关。

### 主代理复验与第二裁（2026-09-23）

- 抽查：dist `2e047a6a…` / `transport.ts 88e6940b…` 与交卷一致；7 份证据 + summary 齐；
  `git status` 文件清单与交卷一致；UNKNOWN_ACTION 实证 ×2 在案；`reconnectNow()` 终码亲读
  （reset backoff → dropAttempt → 同步 connect，注释带实测依据）。
- **追认额外修复**：`reconnectNow` 去定时器与裁决 1 同一意图（"立即"重连被一个可被节流的
  `setTimeout(0)` 架空，属实现缺陷），不予回退，记入规格。
- **裁决 3（批 2d 规格）**：相位项（kill→hello 中 0–60 s 的随机等待）来自"等下一个被节流的心跳定时器
  把 ping 发出去"。消法不是调短常数，而是**让 wake 本身当探针**——`wake()` 的 `connected` 且
  `missed === 0` 分支从"只盖戳返回"改为**立即同步 `sendPing()`**：活 socket 的 pong 毫秒内回来刷新活性
  （上线证据代替自我盖戳）；死 socket 则 `missed` 变 1，下一拍 wake 即判死。同时静默阈值 45→**30 s**
  （检查仍 15 s）：稳态由闹钟每 ~30 s 驱动一次探针，死亡判定最坏 2×30+15 ≈ 75 s，kill→hello 稳定
  ≤90 s 有余量。误杀代价可忽略（loopback 30 s 无 pong = daemon 真挂了；重连廉价）。
- 2c 五项其余结论接受；「kill→hello 2/5 命中」不定罪——根因已定位且 2d 有针对性规格。

### 026d · 交卷（2026-09-23，子代理 agent-43）

- **裁决 3 实现**：`Transport.wake()` 的 `connected` 且 `missed === 0` 分支改为**同步 `sendPing()`**（wake 即探针；
  活 socket 的 pong 作入帧刷新活性，代替自我盖戳）；`connected` 两支不再自我盖戳，另两支保留（避免重连期被反复 wake）。
  静默阈值 `WATCHDOG_ACTIVITY_TIMEOUT_MS` 45 000 → **30 000**（检查仍 15 000）；About/`sys.connector_status` 文案同步。
- **推导核对**：成立，实测优于上界——wake#2 只等 **1 个 15 s 检查**（探针不再盖戳、静默保持、每次检查都发 wake）；
  且 daemon 死后页面自身心跳常已把 `missed` 置 1 ⇒ 有时**一次 wake 就判死**。严格 `>` + 15 s 网格使首拍 wake 落在静默 30–45 s。
- **真机复测 3/3 ≤90 s**：kill→hello **39.6 / 27.1 / 45.8 s**（监听口径 34.9 / 22.5 / 41.1 s），判死分支全为
  `1 unanswered heartbeat(s)`，`activityTimeoutMs` 读回 30000；三次 daemon 启动均 4.6–4.7 s。历史对照（同方法）：
  2b 151.5/135.5/139.7–145.5 → 2c 62.8/114.9/101.3/93.4/74.6 → **2d 39.6/27.1/45.8** ⇒ 相位项已消。
- **变异 CAUGHT**（指定靶：删健康分支 sendPing）：405 中 2 红；还原 `transport.ts 25de7863…`（cp 备份 + cmp 一致）。
- mock：404 → **405**（新增"探针+pong 刷新"与"两次 wake 序列"两条，阈值用例改 30000）。
- 文档：§7.1（机制三态 + 30 s + 2d 实测表 + 状态表）、§6 About 示例 30000、§10 第 22 条补"相位项已消"。
  版本 0.4.19，dist `378a59bb…`（253495 B），已热更到 test 窗口（verified）。
- 前台回归：checkup 与 025c 基线逐行一致；零残留 `components=1 / docs=6 active=P1`。
- 三线：pytest 1388 · connector 405/0 · tsc clean。
- 遗留：test2 / ROBOT 窗仍 0.4.17（等页面 reload 自然升级）；test2 窗未关；"长调用被误判死亡"按裁决接受、记录在案。

### 主代理复验（2026-09-23）

- sha256 三处与交卷一致（dist `378a59bb…`、`transport.ts 25de7863…`、`watchdog.ts 95772252…`）；
  常数 `WATCHDOG_ACTIVITY_TIMEOUT_MS = 30_000` 亲见（下划线分隔符）；6 份证据齐；`git status` 清单相符。
- **026 全线收官**（probe 定案 → 形态 A → 判死规格 → 相位消除）：多窗口后台冻结从"永不恢复"到有界
  ~27–46 s。剩 149 第二窗口验证（岳）与 test2/ROBOT 窗自然升级。

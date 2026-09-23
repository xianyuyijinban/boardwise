# 024 适配立创 EDA 3.2.149（bootstrap 自举）

> 岳（2026-09-22 ~17:50）："新任务：适配立创EDA 3.2.149版本，我现在工作电脑用的这个版本
> 但是用不了我们的插件"。工作电脑版本号 3.2.149.88089769（与上游 #221 环境逐字一致，国际版）。

## 根因（已查明，上游 issue #219/#221/#222 + 源码实读）

**宿主缺陷**：3.2.149 的 `pro-api/0.3.4/api.js` 里，用户扩展激活依赖用户信息就绪：
`hw()` 先设 `isExtensionsInitialized = true` 再调 `Ig()`，而 `Ig()` 在用户信息缺失时
（`ec()` 为 false）**直接 return**。冷启动时 `hw()` 跑在 `user.setUserInfo` 之前 →
用户扩展的 `activate()` **永远不被派发**（后续 setUserInfo 到来时初始化标记已置位，跳过）。
现象：插件只在「导入当次」工作，编辑器重启后 daemon 零连接、顶栏无菜单。

**上游修复**（easyeda-agent Unreleased，在 macOS 3.2.203 验证；Windows 3.2.149 未验证）：
connector bundle **模块加载即自举**，不等 activate()：
1. `index.ts` 模块作用域直接调 `bootstrapFromModuleLoad()`；
2. 宿主共享的 per-extension `eda` 对象上挂版本化运行时
   （`__easyedaAgentTransportRuntime`，签名 `version:cross-eval-v1`）——重复 bundle 求值
   复用同一控制器，重导入不同 build 时先 stop 旧控制器；
3. `localStart` 幂等（`activateObserved` / `handshakeVerified` / `isConnecting` 防重）；
4. bootstrap 用「立即 + setTimeout(0)」两次尝试（sandbox globals 可能下个 macrotask 才就绪）；
5. 另有 always-on watchdog（Web Worker 驱动，规避 Electron 背景页定时器节流）。
   证据：`.tmp_upstream_ext_index.ts` / `.tmp_upstream_ext_transport.ts`。

## 我们的现状

`connector/src/index.ts`：只在 `activate()` 里 start——3.2.149 上 activate 永不派发 = 永不启动。
`connector/src/transport.ts`：有退避重连（1s×2 上限 30s），无共享运行时、无 bootstrap、
无 Worker watchdog（背景节流实测存在：daemon 重启后背景窗口 ~4 分钟才重连）。

## 本任务范围（棒 1，connector/TS）

1. **bootstrap 移植**（核心，照上游范式做我们的实现）：
   - `index.ts` 模块作用域调 bootstrap；`activate()` 保持且幂等；
   - 共享运行时 key `__boardwiseTransportRuntime`（签名带 connector 版本 + `cross-eval-v1`），
     重复求值复用、旧 build 先 stop；
   - bootstrap 立即 + setTimeout(0) 两试；start 幂等（已 connected/connecting 不重入）；
   - 诊断计数（`moduleBootstrapObserved` / `activateObserved`）暴露给 About/状态读取，便于真机分辨
     「bundle 被评估但 activate 未派发」vs「bundle 根本没被评估」（后者 bootstrap 也救不了，
     真机验证要能区分这两种）。
2. **版本 bump 0.4.12**：`connector/extension.json`（+ 钉版本号的测试同步）。
3. **单测**：mock 重复求值（两次 import 同一 transport 模块状态）/ activate 未派发时 bootstrap
   自连 / activate 后来时幂等不双连 / 旧 build 控制器被 stop。
4. **不做**（本轮）：Worker watchdog 背景节流免疫（列入 025 候选，它同时治多窗口重连慢）；
   3.2.149 的 API 能力分层（等真机连通后 sys.probe 实测再定降级清单）。

## 验证路径（Kimi + 岳）

1. 三线全绿后打 `boardwise-connector-0.4.12.eext`（`npm run package`，产物不入库）。
2. 岳拿到工作电脑：卸载旧扩展 → 完全重启编辑器 → 导入 0.4.12 → **再次完全重启编辑器** →
   观察：daemon 侧 hello（带身份）/ 顶栏 boardwise 菜单 / `boardwise bridge status`。
   关键分辨点：重启后 bundle 是否被评估（诊断计数可见）——评估了但 activate 未派发 → bootstrap 自救成功；
   完全没评估 → 宿主连 bundle 都不加载，只剩「每次启动重新导入」或升级编辑器两条路。
3. 连通后 `sys.probe` 实测 3.2.149 的 API 面（dmt_*/sch_* 缺失清单），再定能力降级。

## 红线

不动 git；connector `npm test` 子集 + `npm run typecheck`；证据 `outputs/024_*`（UTF-8）；
不碰 Python 侧（本任务纯 connector）；append 交卷记录后 `grep -c` 防双执行。

## 交卷记录

（子代理交卷后追加）

### 交卷：执行子代理（2026-09-22）

**结论：bootstrap 机制已移植，connector 0.4.12，三线全绿（npm test 336/336、typecheck 干净、
build 干净）；未打 .eext；未动 git / Python 侧。**

改动（connector/）：
- `src/transport.ts` +225：跨求值运行时注册表（`__boardwiseTransportRuntime`，签名
  `<version>:cross-eval-v1`：read/getOrCreate/publishIfEmpty/release，复用 + 旧 build 先
  stop 且 stop 抛错不阻接管）+ `Transport.start()` 幂等（connecting/handshaking/connected
  不重入，并取消待定重连定时器）。
- `src/index.ts` +577：控制器「发布时间化」——记录发布在编辑器的 per-extension 对象 `eda`
  上，记录成员闭包持有首次求值的模块状态；所有导出（activate/reconnect/stopConnection/
  about/getStatus/…）经 `runtime()` 取控制器；bootstrap 为模块作用域主路径（立即 +
  setTimeout(0) 两试，接在既有 250ms…10s 梯子上，不吞档位）；采纳优先于覆盖；
  `getStatus()` 增计数器 `moduleBootstrapObserved`/`activateObserved`/`evaluations`/
  `bootstrapAt`/`activateAt`，`About…` 增 lifecycle 与 bootstrap 两行（真机分辨
  「求值了但 activate 未派发」vs「bundle 根本没被求值」）；`logLine()` 在 host 可达时
  顺手建 facade（bootstrap 早期日志原来只进 console，日志面板看不到）。
- `src/facade.ts` +18：`hostObject()`（不建 facade 的只读 host 读取，仍守「只有 facade 碰 eda」）。
- `extension.json` / `package.json` / `package-lock.json`：0.4.11 → **0.4.12**。
- `tests/bootstrap.test.mjs` 新增 401 行 / 11 条：重复求值复用（用
  `import('.../index.mjs?x=…')` 造真正独立的第二次求值）/ 未派发 activate 自连（含冷启动形）/
  activate 晚到与早到均幂等 / 旧 build 控制器被 stop（含 stop 抛错）/ host 拒绝发布仍连通 /
  下一 macrotask 第二试 / 两计数暴露。既有 325 条全绿未改。

证据：`outputs/024_bootstrap.txt`（UTF-8；含时序 A–D、与上游差异 6 点及理由、变异自检、
遗留）。变异自检：`isReusableRuntime` 加 `return false` → 复用测试变红（register 2 次），
cp 还原后 sha256 逐字节一致（`a4073e29…`）。

待岳真机：导入 0.4.12 → 完全重启 → 看日志面板是否有
`[boardwise] module evaluated (evaluation N …)`、About… 的 lifecycle 两行、daemon 侧 hello。
若 `moduleBootstrapObserved=no`/无日志行 = 宿主连 bundle 都不加载（bootstrap 救不了）。

### 现场验证修订（2026-09-23，issue #4）

> 本节只增不改：上文 §根因、§我们的现状、§验证路径 的历史原文一律保留（它们是当时的判断，
> 不是要抹掉的错），修订口径以本节为准。

**实测现场**（岳的工作电脑，2026-09-23 上午）：EasyEDA Pro **3.2.149.88089769** +
connector **0.4.15**，扩展经 `update-connector` **正式写入扩展库**（不是 sideload 导入态）。

- **冷启动正常派发 `activate()`**：`About…` 读 `activation: 10:25:01 ok`、
  `lifecycle: moduleBootstrapObserved=yes activateObserved=yes evaluations=3`、
  `state: connected`、`pairing: paired`。**关窗再开同样派发。**
- 即：`moduleBootstrapObserved=yes` 与 `activateObserved=yes` 同时成立——bundle 被评估，
  activate 也来了，不是「评估了但没派发」，更不是「bundle 根本没被评估」。

**结论修正（口径）**

1. §根因 里「3.2.149 上用户扩展的 `activate()` **永远不被派发**」与 §我们的现状 里
   「3.2.149 上 activate 永不派发 = 永不启动」**声明确认过宽**：上游 #219/#221 报告的现象
   在 3.2.149.88089769 上**未复现**（上面这轮现场数据是反例）。缺陷归属改成
   「**上游报告 + 本机 3.2.149.88089769 未复现（issue #4）**」，不再作为本版宿主的确定事实引用。
2. **bootstrap 定位修正**：从「绕过已确认缺陷」改为「**幂等防御**」，机制**保留**——
   它本身正确且无害（模块加载即自举、重复求值复用同一运行时、旧 build 先 stop、
   activate 晚到/早到均幂等、诊断计数可见），代价近乎零；它真正覆盖的场景是
   「**不重启编辑器、只 reload 扩展**」这类 activate 不重发的情形（`docs/bridge.md` §10.22），
   而不是本机的冷启动。
3. 因此本文档的任务范围不变，**不需要**回滚 0.4.12–0.4.15 的任何改动。

**未验证假设（待测，岳提出）**

- 假设：024 当时观察到的现象发生在扩展处于 **sideload 导入态**；正式注册进扩展库后宿主就
  正常派发 activate。
- **待测组合：sideload 态冷启动**——导入 0.4.15 的 `.eext` 但不入库 → 完全重启编辑器 →
  看 `About…` 的 `activateObserved`。
  - 读到 `no` → 上游缺陷可钉在这一版宿主上，bootstrap 是绕行手段；
  - 读到 `yes` → 「3.2.149 跳过 activate」应整个撤回（届时 §根因 的结论按本节口径再降一级）。

**遗留症状的重新归因（多窗口）**

开两个窗口时 daemon 只识别到一个，**页面重载之后**第二个窗口才上线。这不是 activate 派发
问题，而是**窗口冻结 / 懒求值**：与本机 3.2.186 上观察到的背景窗口冻结 7 小时同源
（`tasks/025-review-flow-v2.md:151`，前台化才自愈）。所以：149 上做多窗口作业前先避开，
多窗口的验证基线仍是 3.2.186，149 的多窗口等 Worker watchdog。

> 本轮为文档修订：未改代码、未动 git、未重跑测试（无代码变化）。

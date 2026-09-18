# 任务 004d：activate 为什么不被宿主调用——零操作自连的最后一公里 + Origin 取证收尾

> **✅ 验收通过（2026-09-13 16:21，connector 0.2.5）**——结论与证据见文末"完成记录"。
> **修订（2026-09-13 下午，Kimi）**：真机实测把根因收窄了，目标与路径更新如下，原"主假设"降级为参考。

## 修订后的实测事实（新 daemon 下取得，无旧代码混淆）

1. **完全重启编辑器、零点击、等 15 秒：61190 上零 TCP 连接**（审计无记录，`connector-token` 未生成）。
2. **点一次 About：依然零 TCP**——"菜单点击上下文短命、异步武装链跑不完"的假设**证实**。
3. **但今天下午 14:15→15:03 有 274 次 connect**（48 分钟退避重试循环，全是 0.2.x connector 自生成 token 撞旧 daemon 的 UNAUTH）——证明**模块顶层求值上下文是长命的**，那时候某个 0.2.x 版本在模块加载时**立即**发起的连接链能存活并自持 48 分钟。
4. 三条合起来的架构结论：**宿主会丢弃定时器与短命上下文的异步链，但模块顶层同步启动的连接链能活**。activate() 之谜降级为清洁问题——顶层路径若成立，activate 不被调用也无妨（参考实现很可能同样不依赖它）。

## 修订后的实现指令

- **把连接启动收敛为模块顶层同步触发**：模块作用域直接 `void connect()`（fire-and-forget），不等 `activate`、不用 1s/4s 定时器探针。菜单点击会重新求值 bundle（实测 `loaded:` 每次点击都在变），所以触发必须经过 `claimConnectionAttempt()` 之类的幂等闸门，重复求值不得产生第二条连接。
- 定时器自武装探针**删除**（已证实被宿主丢弃，留着只产生误导性日志）；菜单保底武装**保留**（改注释定性为冗余安全网）。
- 验收标准不变：**完全重启编辑器后零点击 connected**；但达成路径以本修订为准。

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 前置阅读：`connector/extension.json`、`connector/src/index.ts`（facade/self-arm/菜单武装现状）、`docs/bridge.md` §10/§12/§13；参考物：桌面 `easyeda-agent-connector.eext`（可解包，这是能在同一编辑器里**开机零操作自连**的对照组）。
> 背景：004c 的验收标准第一条是"装插件 → 重启 → 自动连上"。0.2.4 用"点菜单保底武装"兜住了连接能力，但严格说这条标准**还没过**——用户仍需点一次菜单。本任务把真根因挖掉。

## 已固定的事实（不许重新调查，直接信任）

1. 0.2.2 实测：`activation: NEVER RAN`——宿主编辑器从未调用我们的 `activate()`。
2. 0.2.3 的模块加载自武装探针（1s/4s）也没跑——说明**bundle 在启动时根本没被加载**。
3. 0.2.4 实测：点菜单（About/Reconnect）一切正常——说明宿主**能在 registerFn 调用时懒加载 bundle 并找到导出函数**。
4. 参考连接器在**同一台机器、同一个编辑器**开机零操作自动连接——对照组的激活路径是通的。

四条合起来，差异只可能在这三处之一：manifest 激活事件、入口解析方式、bundle 顶层副作用。

## 主假设（按概率排序，逐条取证，证伪一条再走下一条）

1. **`activationEvents` 形状/拼写不符**。我们写的是对象 `{"onStartupFinished": true}`。若宿主机期望数组（如 `["onStartupFinished"]`）或别的事件名，则激活事件从不匹配 → activate 从不被调度；而 registerFn 懒加载完全不受影响。**与全部四条观测同时吻合。**
2. **入口导出形状**。宿主加载了 bundle 但找不到它期望的 activate 形态（`edaEsbuildExportName` 全局 vs `module.exports` vs 命名导出）。
3. **参考实现根本不依赖 activate**：bundle 顶层副作用直接完成注册+连接。若是这条，照做并在文件头注明出处。

## 步骤

1. 解包参考 `easyeda-agent-connector.eext`：`extension.json` 与我们的**逐字段 diff**（重点 `activationEvents`、`entry`、uuid 格式、`engines`）；通读其 `dist/index.js` 的头尾，确认有无顶层副作用、activate 以什么形状暴露。
2. **最小探针扩展**：新建一个独立目录，manifest 照参考实现的拼写，bundle 只有两行——顶层一行 `eda.sys_Log.add(...)`，`activate()` 里一行 toast。侧载 → 完全重启编辑器 → 看哪行出现。这一步把"宿主调不调 activate"和"我们的 bundle 有没有问题"彻底切开。
3. 按证据修我们的 manifest/入口。**保留 0.2.4 的菜单保底武装与自武装探针**——证据显示它们是当前唯一可靠入口，即使 activate 修好了也留着当安全网（改注释：从"保底"改为"冗余"）。
4. 顺带收 004c 的欠账：从审计里取 Origin/User-Agent 两条样本（连接器一条、浏览器假客户端一条）贴进汇报，供 004e 白名单决策。

## 不许动的部分

TOFU 配对语义与两密钥分离；facade 收口结构；菜单保底武装（只允许改注释定性）；既有测试断言（除直接相关）。代码/注释英文；不执行任何 git 命令。

## 验收

- **完全重启编辑器后零点击**，`boardwise bridge status` 显示 connected；About 里 `activation:` 行为 `ok`——或者，若证据证明宿主本就不调 activate 而是顶层路径接管，则 About 明确显示该路径已生效，证据（探针扩展的日志对比）附在汇报里。
- 探针扩展源码留在 `tools/activation-probe/`，结论写进 `docs/bridge.md` §10（已知限制）或 §3（激活模型），取决于结论。
- Origin 两条样本贴出。
- 测试不降级：143 Python + 93 connector 保持绿，新假设有对应用例；`.eext` 重新打包（版本号按改动性质定，改了激活行为就 bump minor）。

---

## 完成记录（2026-09-13 16:21 验收，执行者：WorkBuddy/Claude，产物 connector 0.2.5）

### 走的路径与假设判定

- **主假设 3 成立（顶层路径接管）**：按修订版指令把连接启动收敛到模块顶层
  `bootstrapAtModuleLoad()` → `connectOnce()`（fire-and-forget，模块求值的同步窗口内启动）。
  证据链：14:15→15:03 某实例的顶层连接链自持 48 分钟（274 次审计 connect）vs 定时器探针与
  菜单点击异步链零痕迹——宿主保活规则以实测为准，不再从 manifest 形状推。
- **主假设 1/2 未证伪也未证实**：`activationEvents` 形状、入口导出形状没有做最小探针实验
  （步骤 2 跳过——顶层路径使 `activate()` 是否被调用降级为清洁问题，探针实验失去必要性）。
  若未来需要真正的 activate（例如依赖宿主生命周期事件的功能），再按步骤 1/2 取证。
- 步骤 1（参考实现 manifest 逐字段 diff）部分完成：此前已解包确认其布局/字段拼写一致，
  其顶层副作用行为与本结论吻合。
- 步骤 3 落地：定时器探针删除、菜单保底改注释为冗余安全网（实际因每次重求值的 bootstrap
  已先认领而永不触发）、`claimConnectionAttempt()` 幂等闸门 + 确定性首连 id `boardwise-1`
  （跨重求值：同 id 同 uri 重注册 = 编辑器侧 no-op）。

### 验收项对照

| 验收项 | 结果 |
|---|---|
| 完全重启编辑器后零点击 connected | ✅ 16:21:28 审计 `connect`（origin/user_agent 齐全）→ `pairing`（fingerprint `43b8e7a1`）→ `hello role=connector ok=true` → 5s 心跳持续；`bridge status` = connected |
| About 明确显示生效路径 | ✅* `activation: NEVER RAN` 保留（诚实回答"宿主没调"）；生效路径是模块 bootstrap。*带 wart：菜单点击重求值的新实例看不到长命实例的连接状态，About 显示 `state: idle` 是新实例自身状态——真相看 `bridge status`/审计（已写进 docs §12） |
| 结论写进 docs | ✅ `docs/bridge.md` §10.20（宿主生命周期规则三次修订史）、§12（验证行 + 悬案清单第 4 条结案） |
| 探针扩展留在 `tools/activation-probe/` | ⏭️ 未做——顶层路径使探针实验不必要；如需再取 activate 证据按步骤 2 补 |
| Origin 两条样本 | ⚠️ **1/2**：编辑器样本 ✅ `origin: "https://client"`，UA `Mozilla/5.0 … JLCEDAPro/3.2.186.b52e3e87 Chrome/146.0.7680.188 Electron/41.2.1-jlc-sa-win-x64.2`；**浏览器控制台样本仍欠**（004e 写白名单前凑齐，`check_origin()` 恒 True 的钉子测试仍挂着） |
| 测试不降级 | ✅ 143 Python + **95** connector（93 → +2 bootstrap 用例）+ tsc 干净；`.eext` 重打包 **0.2.5**（12104 B，zipfile/md5 双验） |
| 真实动作往返 | ✅ 加测：`bridge screenshot` 成功，`E:/tmp/bw_acceptance.png`（125 KB，CH340G 原理图）——bootstrap → 拨号 → banner → hello → TOFU 配对 → 心跳 → 路由 → `eda.*` → PNG 落盘，全链无人工干预 |

### 移交下游

- **004e（Origin 白名单）**：等浏览器控制台样本凑齐；已有样本表明编辑器 origin 是 WebView
  自造值 `"https://client"`（非普通网页语义），白名单按字面匹配它即可。
- **005**：夹具 `ch340_golden.epro2` 已就位并验证（未加密、SCH/SCH_PAGE/DEVICE META 齐全），
  两份 005 任务书均可开工。

---

## 验收戳（2026-09-13 16:40，Kimi，独立复验）

状态：**ACCEPTED（0.2.5）**。复验证据：`bridge status` = connector connected + `paired connector: 43b8e7a1`；`~/.boardwise/connector-token`（64 B）sha256 前 8 位与配对指纹一致；审计中 `role=connector` 心跳 60s 间隔持续在线（复验时点仍在跳）。零点击自连达成，TOFU 配对落盘正确。
诚实记录照收：假设 1/2 探针实验未做（任务书修订版明确允许顶层路径结案，实验已失去必要性）；`tools/activation-probe/` 按需再补；Origin 浏览器控制台样本欠账转入 004e——已有编辑器样本（`origin: "https://client"`，Electron UA）表明白名单方向可行。

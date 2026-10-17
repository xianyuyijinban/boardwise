# R4 证据（真·热更 —— 实验先行）

开发机**没有立创 EDA Pro**，阶段一的五个真机实验**一个都没跑**，所以也没有进入阶段二（任务书：不过实验不写代码）。本 PR 交三样东西：

1. **实验 ①② 的仪器**：`sys.probe {realm: true}`（connector）。
   - 只读；只执行 connector 里写死的常量代码（三种方式：间接 `eval`、`new Function`、`import(data:…)`），每种都应答出 `6 * 7 = 42`；
   - 从不执行参数里的任何东西（`realm` 只接受 `true`，其他值一律拒绝，测试钉住了）；
   - 同时读出阶段二要依赖的环境事实：`crypto.subtle`（经 `random.ts` 读取，遵守源码守卫）、`WebSocket`、`fetch` 等。
   - 在 Node 环境里实测三种方式都返回 42。编辑器里会怎样，**未测**。
2. **实验 ③④ 的 runbook**（`runbook.md`）。实验 ④ 缺一个「只写不 reload」的仪器，要么给 `sys.self_update` 加 `reload:false`，要么接受仪器不可得；**待裁决**。
3. **阶段二安全设计草案**（`design-proposal.md`），只有设计，待评审。核心建议是**在 stub 里用内置的发布者公钥验签**，与任务书写的「daemon 侧持有公钥 / hash 白名单」不同，理由写在草案 §4。

## 改动
- `connector/src/actions.ts`：`realmProbe` 和 `sys.probe` 的 `realm` 分支；从 `random.ts` 引入 `ambientRandomHost` / `describeRandomHost`。
- `src/boardwise/bridge/protocol.py`：`sys.probe` 的 params 加上 `realm`，returns 补充说明。
- `docs/bridge.md` §4：`sys.probe` 行补上 realm 模式。
- `connector/tests/realm-probe.test.mjs`：4 条。

## 测试
- connector `npm test` 483 pass / 0 fail（基线 479，新增 4）；`npm run typecheck` 通过。
- pytest 全量见 PR 描述。

## 变异验证（cp 备份 + sha256 还原）
| 变异 | 结果 |
|---|---|
| M1 `realm` 接受任意值 | CAUGHT |
| M2 抛错的环境不再被捕获（探针直接崩） | CAUGHT |
| M3 去掉哨兵比对（任何答案都算 ok） | 第一轮**存活**；补了「代码跑了但答非 42」的测试后 CAUGHT |

## 过程记录
第一版直接读了 `globalThis.crypto`，被源码守卫 `source-guard.test.mjs` 拦下（只有 `random.ts` 可以碰全局 crypto）。改为经由 `random.ts` 读取，没有绕过守卫。

## 阶段一实验 ①②：realm 能力（主代理真机，2026-10-13，connector 0.5.12 / 宿主 3.2.186）

原始读数 `live/realm_probe_0.5.12.json`。结论：**动态执行三通**——indirectEval / new Function /
动态 import(data: URL) 各回哨兵值 42；fetch/WebSocket/Worker/Blob/URL/TextEncoder/indexedDB 在场。
**缺口：`crypto.subtle` undefined**（`crypto` 本身在）——载荷验签不能用 WebCrypto，
stub 设计需纯 JS 验签实现或换摘要+带外指纹方案。实验③热更通道本机同日双证
（0.4.29→0.4.30、0.5.11→0.5.12 均六秒激活 verified）；④菜单点击免 reload 激活未测
（需手工点菜单，留岳）。阶段二 stub 立不立项由岳定优先级——通道现状已可用。

---

## R4a（2026-10-17，真热更阶段一收尾 + 安全设计定稿；执行：coder 子代理）

任务书 `tasks/R4a_hot_update_stage1b.md`。本批**没改 `connector/src` 正式源码**、没改 `src/boardwise` 的 Python、没碰 191B 的工作树改动、无 git 写操作、无 `rm`、无 npm 安装（只 `npm view` 只读）。
真机只碰 `test` 窗。**connector 版本全程 0.5.13（V0），未发生任何热更**——理由见 A。

### A. 实验④（菜单点击免 reload 激活）：**仪器缺口已证，本批不推写入**

#### A0. 现状读数（2026-10-17 02:1x，`outputs/R4/live/`）

| 项 | 读数 | 出处 |
|---|---|---|
| connector 版本 V0 | **0.5.13** | `r4a_00_status_initial.txt`（`bridge status`） |
| 窗口 | **1 个**：`inst-170647638-txbd3bng`，project `test`（uuid `ea80fff6…`），page `pcb 5dc38976c1fa45ce` | 同上 |
| 焦点工程身份（R1） | `doc.list` → projects 里 `test`、uuid 与任务书/既有记录逐字一致 | `r4a_01_doc_list.json` |
| 运行期求值次数 | `evaluations: 1`，`bootstrapAt=2026-10-16T17:06:47Z`（= 本机 01:06:47，该窗连接时刻） | `r4a_02_connector_status_V0.json` |
| realm 事实（复测） | `newFunction.ok=true`（回 42）、`indirectEval`/`dynamicImportDataUrl` 都 true；**`crypto.subtle=undefined`**（`crypto` 本身 `crypto=ok`）；`fetch`/`WebSocket`/`Worker`/`Blob`/`URL`/`TextEncoder`/`indexedDB` 在场，`importScripts`/`SharedArrayBuffer` undefined | `r4a_03_realm_0.5.13.json` |

`evaluations: 1` 且 bootstrap 时刻 = 该窗连接时刻 ⇒ **自启动以来这个窗一次都没重求值过**（没 reload、没菜单点击），是干净的 ④ 基线。

#### A1. 测试 bundle 已就位（`.tmp_r4a/probe/bundle/dist/index.js`，**只改版本串**）

构建方式：用 `connector/node_modules` 里的 esbuild，对 `connector/src/index.ts` 打两次 IIFE（`build.mjs` 同参数：`target es2020 / globalName edaEsbuildExportName / platform neutral`，uuid 取自 `extension.json`），一次 `__BOARDWISE_VERSION__="0.5.13"`、一次 `"0.5.13-r4probe"`，输出都在 `.tmp_r4a/`（`connector/dist` 一个字节没动）。脚本 `.tmp_r4a/build-probe.mjs`。

字节级证明（机器可验，不是「应该只有版本串变了」）：

```
sha256 connector/dist/index.js            = f1c979053aa1554b82f2661d3488f511167c5107b898c16a3423549c730dfaaf
sha256 .tmp_r4a/probe/base/dist/index.js  = f1c979053aa1554b82f2661d3488f511167c5107b898c16a3423549c730dfaaf   ← 与仓内已发布件逐字节相同
sha256 .tmp_r4a/probe/bundle/dist/index.js= 7ae7a15fcb12b4fd4cb80d7313cd47afce692737a4b632a27797373b6c258eae
probe 去掉 8 字节后缀 == base : True（偏移 18740 插入 "-r4probe"）
上下文：base  var VERSION = true ? "0.5.13" : "unknown"   →  probe  "0.5.13-r4probe"
大小 293526 → 293534 B（+8 = len("-r4probe")）
```

顺带封了两条旧账：① 仓内 `connector/dist/index.js` 与当前源码**同哈希**（dist 不是陈旧件）；② 探针 bundle 的加载风险 = 0（与已发布件只差一个字符串字面量里的 8 字节）。

#### A2. 为什么**没有**把探针 bundle 推进去（对任务书 A1 的偏离，理由是硬的）

任务书 A1 写「写入……**不 reload**」。**现有仪器做不到「只写不 reload」**，三条证据：

1. `connector/src/self-update.ts:283-284`：`host.setTimeout(() => host.location.reload(), RELOAD_DELAY_MS)` —— 写在动作体里、**无条件**，`params` 里没有任何开关（`protocol.py:284` 的 `sys.self_update` params 只有 `bundleB64/version/confirm`）。
2. SKILL.md 坑 22 ②：「**写就是 reload 的唯一触发器**（`location.reload()` 挂在同一个动作里）」，030 真机实测四坑之一。
3. 030 §二.5 真机实测：「写一窗不会连带 reload 别的窗」——只被写的那一窗 reload。

所以推写入会**立刻**把 0.5.13-r4probe 变成运行版本（reload 生效，③ 已三次实证），于是 A2「点菜单后读到 -r4probe」就**无法区分**是菜单点击求值的还是 reload 干的了——照推下去 ④ 会得到一个**假 positive**，而这正是 ④ 唯一要回答的问题。这不是省事，是不许把实验做成没有分辨力的实验。

**因此本批选择：不推、不 reload、不动真机状态**（也避免打断并行批 191B 与用户的编辑器会话）。任务书要求的「恢复」因此是零动作——最后读数仍是 V0（见 D）。

#### A3. ④ 的两条可执行路线（给主代理与岳一起做时用）

**路线 A（推荐，零代码改动，用现有仪器）——两个窗口 + 共享存储**

机理：一个编辑器里所有窗口共用同一份扩展存储记录（`User_<teamUuid>_v6`，030 真机实测：test/test2/ROBOT 三窗写的是同一条记录），而 reload 只发生在**被写的那一窗**。所以让另一窗去写，被测窗就处在「存储是新载荷、运行的是旧代码」的状态——④ 需要的那个缺口。

1. 岳在同一个编辑器里再开一个窗口（建议开 `test2`，工程名不同可避免 `PROJECT_AMBIGUOUS`；**禁地工程一律不许开进这一步**）。
2. `bridge status` 记下两窗 instance id。
3. 基线：`bridge call --action sys.connector_status --params '{}' --instance <test 窗 id>` → 记 `evaluations`。
4. 只推给**另一窗**（写成 `test2` 的窗 id）：
   `.venv/Scripts/python.exe -m boardwise.cli bridge update-connector --instance <另一窗 id> --bundle .tmp_r4a/probe/bundle/dist/index.js --version 0.5.13-r4probe --yes`
5. `bridge status` → 确认另一窗已 `0.5.13-r4probe`、**test 窗仍是 0.5.13 且 instance id 未变**（这就是缺口成立的现场证据，务必落盘）。
6. 岳在 **test 窗**点一次 `boardwise → About…`。
7. 再读：`bridge call --action sys.connector_status --params '{}' --instance <test 窗 id>`
   - `evaluations` 变大 ⇒ 菜单点击**确实重求值** bundle（这一半不需要写入就能测，见下）；
   - test 窗报 `0.5.13-r4probe` ⇒ **④ 成立**（菜单点击把存储里的新 bundle 跑起来了）；
   - test 窗仍报 `0.5.13` ⇒ **④ 不成立**（重求值也只跑宿主手里那份旧包，或压根没重求值）⇒ 阶段二「换载荷零操作」不成立，只剩 reload 通道。
   - 注意：若 ④ 成立，该窗会**换新 instance id**（每次求值 `newInstanceId()`），第 7 步读不到时先 `bridge status` 重取。
8. 恢复：对**两个窗**各跑一次默认 bundle 的更新（不给 `--bundle`）回到 0.5.13；只有在线窗口集合恰为 test/test2 时才可用 `--all`（`--all` 会 reload 每个在线窗，**禁地窗在场时不许裸跑**）。

**路线 B（R4b 做）：给 `sys.self_update` 加 `reload:false`**

只跳过 `self-update.ts:284` 那一行、其余不变，单窗即可完成 ④（写 → 不 reload → 点菜单 → 读版本）。代价：这是 `dangerous` 档动作的行为扩张，且要动 `connector/src`（属 R4b 范围，需岳点头）。

**免费的一半（零风险，建议无论如何都测）**：`sys.connector_status.evaluations` 由共享 runtime 的发布者计数（`index.ts:238/311` + `noteEvaluation`），菜单点击的求值会 `+1`。所以「菜单点击会不会重求值 bundle」这一步**不需要任何写入**：点前点后各读一次 `evaluations` 即可。本批基线 = **1**。它只回答「有没有重求值」，**不回答**「重求值跑的是不是新字节」——后者才是路线 A/B 要回答的（也正是 165 那个谜面的核心）。

### B. 165「写≠激活」复现条件（只读调查；本机复现需第二个窗口，见 A3 路线 A）

#### B1. 165 场报告的**原始可观察量**（仓库里能查到的全部，逐字来源）

- `outputs/165/evidence.md:57-65`（现场口径）：写入回执 **`ok: 0.4.25 -> 0.4.29`**，而**回读一直是 `0.4.25`**；机理被写成「宿主在加载期只评估扩展包一次，reload 重新读记录但不会重新评估编辑器认为『已评估』的那份代码」。
- `docs/bridge.md:1070-1076`（同一段落的英文定稿）：同一读数；并声明这是**现场转述**（`field measurement 2026-10-12`）。
- 来源：`PROGRESS.md:589`「165+166 现场修复合批（agent-289/292，**岳另一台机器的 AI 实测反馈**）」。
- **报告里没记的**：宿主版本、窗口数、是否多窗同工程、IndexedDB 记录名、写后过了多久做的回读、回读用的是 `About…` 还是 `bridge status`。这几项缺失本身是结论的一部分——**它无法与正例逐项对齐**，所以「复现条件」只能到工作电脑上去量（R3：找不到就停下问，不自行替代）。

#### B2. 与正例的逐项对照

| 可观察量 | 165 场报告（工作电脑 10-12） | 030 正例（09-24） | 031 正例（09-24） | 165 补遗（本机 10-12） | R4 阶段一③（本机 10-13） | 本批（10-17） |
|---|---|---|---|---|---|---|
| 宿主版本 | **未记录**（同机既往记录是 **3.2.149.88089769**，见 tasks/024、issue #3-#7，但**这次没写**） | 3.2.186 | 3.2.186 | 3.2.186 | 3.2.186 | 3.2.186（probe 读数） |
| 在线窗口数 | **未记录** | **3**（test/test2/ROBOT） | **3** | 1（单窗 `--instance`） | 1 | **1** |
| 写后是否 reload | 是（动作体无条件 reload），但**运行版本没变** | 是，**运行版本变了**（每窗各自 update） | 是，变了 | 是，变了 | 是，变了 | 未写 |
| 回读手段/时点 | **未记录**（只写「回读仍是 0.4.25」） | CLI 窗口表逐窗核（等过 `reloadInMs`，30 s 上限） | 同 | CLI 窗口表 | CLI 窗口表 | `sys.connector_status` |
| 存储记录名 | **未记录** | `User_08be6a96fc064a03b488fd9d5a25ccea_v6`（与 test2/ROBOT 共用） | 同上 | 同一条记录 | 未记（同机同记录） | — |
| 版本 | 0.4.25→0.4.29 | 0.4.17→0.4.19（test 先 4.19→4.19 等值重写） | 0.4.19→0.4.20 | 0.4.29→0.4.30 | 0.5.11→0.5.12 | — |
| 结果 | **写成功、运行未变** | verified（逐窗） | verified（4 s） | verified（6.2 s） | verified（双证） | 未测 |

**本机审计侧的频次读数**（`~/.boardwise/audit/*.jsonl`，只读统计）：`sys.self_update` 帧共 124 条，其中 **`ok=true` 57 条**（2026-09-18 → 2026-10-16，跨 11 天），失败 7 条且**全是写入之前就被拒**：`UNKNOWN_ACTION` 1 / `NO_CONNECTOR` 4 / `WINDOW_UNSPECIFIED` 1 / `CONFIRMATION_REQUIRED` 1。**本机没有任何一条「写入成功但没激活」的记录**（审计只记路由帧，CLI 的 exit 码不在里面；但 outputs/ 里 4 次带 verified 输出的正例都在 3.2.186 上）。即：这台机器上 165 是 0/57 的孤例形态，工作电脑上是 1/1。

#### B3. 可观察差异 → 候选成因（每条都给出**能证伪它的观测**，不写成断言）

- **H1 宿主版本（149 vs 186）**：工作电脑既往记录是 3.2.149.88089769，而 149 有已实测的「窗口冻结/懒求值」家族性质（坑 18：149 上第二个窗口的 connector 不上线，页面重载后才上线；本机背景窗口冻结 7 小时同源）。若 149 的页面 reload 后扩展包由宿主**懒求值**，reload 就等于没换代码——与 165 的读数完全吻合。
  *证伪法*：在工作电脑 `About…` 读宿主版本；若是 3.2.186 而问题仍在，H1 倒。
- **H2 多窗 + 共享存储（写在一窗、看的是另一窗）**：030 真机实测「写一窗不 reload 别的窗」，031 现场留下过活样本——存储记录写着 0.4.19 时，**ROBOT 窗一直跑着 0.4.17**。若 165 那次会话开了多个窗口、而被观察的是**没被写的那一窗**，读数就是「回读仍是旧版本」。
  *证伪法*：`bridge status` 逐窗看版本（不是只看「有窗报新版本」）；或按 A3 路线 A 在本机主动造一次多窗缺口——**这条本机可复现**，但需要第二个窗口（要人开）。
- **H3 回读时点太早（旧 socket 还在表里）**：reload **替换**连接（新 instance id），旧 socket 直到编辑器把页面拆掉才消失——**实测 5 秒**；CLI 因此要等过 `reloadInMs` 再读窗口表（020/025 的「假失败」教训，`docs/bridge.md:1050-1059`）。现场若在写后立刻回读，会读到那条**正在退场的旧连接**，答的正是旧版本号。
  *证伪法*：看现场的回读时点与手段；本机可复现（写一次、0.5 s 内读 status，应当读到旧版本 —— 需要一次写入，故本批未做）。
- **H4 记录被宿主回滚**：`newVersion` 是**CLI 自己输入的复读**（`docs/bridge.md:1041-1043` 明写「不是证明」），真正的证明只有运行版本。若宿主在页面加载时用自己的内存副本重写扩展记录，就会「写进去了、回读还是旧的」（现场读数形态正是这样）。
  *证伪法*：在崩溃/编辑器重启后再回读记录里的版本（需要工作电脑或一次本机写入 + 一次编辑器重启）。
- **H5 IndexedDB 权限/存储差异**（工作电脑 renderer profile）：`outputs/165/evidence.md:199` 的推测，**无观测支撑**，只作为兜底假设列出。

#### B4. 本机能复现到哪一步（如实）

- **本批能做的**：只读对照（B2）+ 频次读数（B2 末）+ 机理核对（`self-update.ts` 与 030/031 的实测）。**这几项都没能把 165 复现出来**——本机当前是 1 窗、0.5.13、`evaluations=1`，没有缺口可用。
- **本机可复现、但需要人工的**：H2（多窗共享存储缺口）——按 A3 路线 A：开第二窗、只更一窗、看 test 窗。**这正好是 ④ 那次实验**，两件事一次做完即可（④ 的现场就是 H2 的现场）。
- **本机可复现、但需要一次写入的**：H3（旧 socket 5 秒窗口）——写一次后 0.5 s 内读 `bridge status`。本批没做（不推写入，理由同 A2）；建议在 ④ 那次会话顺手做（推给第二窗后，立刻读 status，可见 test 窗的旧实例仍在 + 第二窗短暂匿名）。
- **需工作电脑**：H1（宿主版本核对）、H4（记录是否被宿主回滚）、以及 165 报告缺失的那几个可观察量本身。**不碰工作电脑**（任务书 B 段）。

### C. 安全设计定稿（改 `outputs/R4/design-proposal.md`）

- 新增 **§3b 纯 JS 验签**：候选表（`tweetnacl@1.0.3` / `@noble/ed25519@3.2.0` / `@noble/hashes@2.4.0` 的版本、体积、依赖、许可、是否需要 `subtle`，全部来自 `npm view` 只读调研，**未安装任何包**）；**推荐 `tweetnacl@1.0.3` 并钉死**（零依赖、Unlicense、Cure53 2017 审计过、`nacl.sign.detached.verify` 同步、verifying 路径不碰随机数、不需要给任何 hashes 钩子赋值）；`@noble/ed25519` 落选的关键一条是它默认 async 路依赖的正是缺席的 `crypto.subtle`，同步路要另挂 SHA-512 来源。
- **realm 内跑不了的诚实说明 + 本机替代证明**：现有探针通道**按设计不接受任何代码**（`sys.probe {realm:true}` 是布尔开关，`actions.ts` 的 `realmProbe` 只跑写死的常量），所以 realm 内自检需要 R4b 加一个**只读常量自检动作**（形状抄 `realmProbe`，不接收入参）。本批的替代证明在 Node + `globalThis.crypto` 被删成 undefined 的条件下做，**且经 `new Function` 执行**（与 stub 执行载荷同一条路径，该路径本身已在真机验证）：
  - 自写最小 Ed25519 verify：源码 5 573 字符，esbuild 压后 **2 786 字符**（压后那份也实测跑通，见 `r4a_07_ed25519_minified_check.txt`）；
  - RFC 8032 §7.1 TEST 1/2/3 三个官方向量：**全 true**；同一组向量交给 `node:crypto` 独立实现：**也全 true**（防「向量记错」伪造成「实现正确」）；
  - 负对照 **5 条全 false 且不抛**：签名在 R 里翻 bit（byte 3 / byte 10）、在 S 里翻 bit（byte 40）、消息翻 bit、一整条垃圾 64 字节签名。**这条是踩出来的**：第一版 verifier 在「R 解压失败」时抛 TypeError 而不是拒绝，官方向量与第一次挑的那个字节都没暴露它（换第二个字节位置才炸）→ 已修（构造右式前先判空），口径落进 §3b 与 §5：**验签器对畸形输入只许答 false，不许抛**；
  - **压后形态的执行契约坑**：2 786 字符那份用 `new Function(code)`（函数体）或 `eval(code)` 都能跑（三个向量 true、负对照 false），但**包成 `return (code)` 表达式形态报语法错**（本机实测 `SyntaxError: Unexpected token ';'`）——载荷的执行形态要在 R4b 里明确选定，别假设随便包一层就能取到返回值；
  - SHA-512 先与公开的 `SHA-512("")`/`SHA-512("abc")` 对上才开始验签，且**80 个 K 与 8 个 H 是运行时从素数立方/平方根推出来的**（没有可记错的表常量）。
  - 原始输出：`outputs/R4/live/r4a_04_ed25519_selfcheck.txt`；仪器：`outputs/R4/live/r4a_ed25519_selfcheck.mjs.txt`（**只是证据附件，不进 connector 源码**）。
- **密钥管理三选项**（① GitHub Actions secret 签名 / ② 岳本机离线私钥手签 / ③ 主+备双公钥内置 stub 带过期时间）的利弊与推荐理由全在 §3b；**不替岳选**，推荐「先 ②、要代发版时再升 ①、③ 不在第一版上」，并点出 ③ 的过期时间**只能当提示不能当拒绝依据**（本机时钟可改，与 §2.4 同一条纪律）。
- §4 保持「验签放 stub 而非 daemon」，**新增硬要求：daemon 侧不需要任何密钥材料**（不持公钥、不持 hash 白名单、不参与验签，只原样转交 `{version, seq, sha256, code}` + 签名；否则等于两层信任、攻击面翻倍）。
- 同时修了两处已被真机读数推翻的旧前提：文件头的「前提是 `crypto.subtle` 存在」→ 改为「动态执行三通成立即立项，验签走 §3b 纯 JS」；§2.1 的「Ed25519 或 ECDSA P-256 取决于宿主 WebCrypto 支持哪个」→ 改为「探针已给答案：`subtle` 缺席，只能纯 JS Ed25519」。§3 从「放弃是唯一出路」改成「放弃仍是合法退路，但不再是唯一，见 §3b」。§5 验收补三条（验签器自身的官方向量测试、realm 内验签要有真机读数、daemon 零密钥材料要有钉子）。

### D. 纪律与最终读数

- **没改**：`connector/src/**`（正式源码）、`src/boardwise/**`（191B 在跑）、`tests/**`、`connector/dist`（一个字节没动，见 A1 的哈希）。**改了的文件**：`outputs/R4/design-proposal.md`、`outputs/R4/evidence.md`（本节）、`PROGRESS.md`（append 一行）、`outputs/R4/live/` 下 4 个读数文件 + 1 个证据附件。
- 无 git 写操作（只读用了 `git log`/`git check-ignore`/`git status`）；无 `rm`；无 npm 安装（`npm view` 只读，需代理时 `export https_proxy=http://127.0.0.1:7890`）。
- 临时物：`.tmp_r4a/`（gitignore `.tmp_*` 覆盖）——**本批未回收**，因为 A3 路线 A 还需要里面的探针 bundle（一次性产物，做完实验后回收即可；探针 bundle 与自检脚本的证据副本已落在 `outputs/R4/live/`）。构建过程误在 `connector/` 下留过一个 `.tmp_r4a/probe/…` 空壳，已走回收站删除（`DeleteDirectory` + `SendToRecycleBin`）。
- **最终读数（交卷时）**：connector 仍是 **0.5.13 = V0**，窗口仍 1 个（见本节 D 之后的收尾读数），**本批没有发生任何写入或 reload**，所以「恢复」是零动作。若 ④ 会话（A3 路线 A）执行过，恢复命令 = 对两个窗各跑一次 `bridge update-connector --instance <id> --yes`（不带 `--bundle`，即仓内的 0.5.13），跑完 `bridge status` 逐窗核 0.5.13。

### D2. 收尾读数（2026-10-17 02:31，全部只读）

```
$ .venv/Scripts/python.exe -m boardwise.cli bridge status          # outputs/R4/live/r4a_05_status_final.txt
已连接 1 个窗口：test
  window: inst-170647638-txbd3bng (connector 0.5.13)  [project test (ea80fff6…)]
    peer: 127.0.0.1:63816  connected: 2026-10-17 01:06:47  last seen: 2026-10-17 02:30:53  routed: 186

$ ... bridge call --action sys.connector_status --instance inst-170647638-txbd3bng   # r4a_06_connector_status_final.json
state=connected  evaluations=1  instance id 与开工时逐字相同
```

⇒ **connector 最终版本 0.5.13（= 开工时的 V0）、instance id 未变（无 reload）、`evaluations` 仍是 1（自启动以来未重求值）**。`routed` 从 176 涨到 186 = 本批 10 次全只读调用（status×2 / doc.list / connector_status×2 / realm probe / 及统计前的核对），没有一次写入。

## 实验④（菜单点击免重载激活）—— 路线 A 实测，2026-10-17，宿主 3.2.186 / connector 0.5.14

**结论：成立。** 步骤：test2 窗写入探针 bundle（`0.5.14` → `0.5.14-r4probe`，仅版本串 +8B，探针由当前发布 dist 单点替换生成，写入共享记录 `User_08be6a96fc064a03b488fd9d5a25ccea_v6`）；test 窗保持不动（同 instance、0.5.14、`evaluations=1`，写后复读三项不变——共享记录写入不波及未重载窗）。岳在 test 窗点一次扩展菜单（无 reload）：test 窗 instance 更换（inst-031914557… → inst-064408323…），`bridge status` 报 **0.5.14-r4probe**——菜单点击触发重求值**且**激活新 bundle。随后 `update-connector --all` 恢复两窗 0.5.14 verified。

对 165 的含义：本机宿主上「菜单点击即激活」成立，165（工作电脑写≠激活）的候选收敛到 H1（宿主版本/窗口冻结态差异）与 H3（回读时点太早）——工作电脑补测那一项仍挂着。
对 R4 的含义：「免重载热更」在用户态已经是「写 + 点一次菜单」，stub 的增量价值只剩「连菜单都不用点」——立项价值重估，钥匙管理三选项（design-proposal §3b）待岳裁。

顺带发现（已记 192C 之后的欠账）：`--all` 两窗几乎同秒 reload 时，逐窗验收的两行证据引用了**同一条**新连接 id（inst-064726033 被算给两窗）——结论对（两窗确实都 0.5.14），但 per-window 证据归属仍可能错配，排进后续。

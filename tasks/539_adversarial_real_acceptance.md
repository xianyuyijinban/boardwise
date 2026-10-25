# 539 — 537/538 对抗审查、真机验收与提交

- 立项：2026-10-25，按用户明确指示：先编排子 agent 到各缝挖洞，再无问题后真机测，最后 commit 汇报。
- 前批：537 审查流程、538 块级独立子岛编译均已完成并通过四线（Python 7708 / connector 536 / dsh-plugin 113+1 skip）。

## 1. 顺序与授权

1. 小领域对抗审查：scope/identity、compile/recompile、finalize/present、live/read-only/environment。
   子代理只读生产文件，探针只能写各自 `.tmp_adversarial/<领域>/`；不得改生产代码、不得跑全量、不得操作桥或真实工程。
2. 主线复现每个具体发现，按 blocker/high/medium/low/note 分诊。实际缺陷串行小批修复，变异验证后跑聚焦与完整四线。
3. 真机验收只在下述 `test` 身份与既有能力范围内执行。其他真实工程与任务书未逐字点名的窗口一律不写；禁写工程名不录入公开任务书。
4. 真机和全量回归均通过后，分类审查工作树、敏感信息与工程容器，显式暂存并复核 staged diff，最后创建一次 commit 并汇报哈希。

## 2. 真机 R1 身份快照（2026-10-25 只读读取）

- daemon 127.0.0.1:61190 可达；daemon/boardwise 0.5.21；宿主 3.2.186。
- 在线窗口两个：一个禁写真实工程窗口与 `test`（inst-144927030-6y9x48j6）。
- 唯一允许真机测试的工程：`/test`，friendlyName `test`，projectUuid
  `ea80fff642fa86cdc95882ab0201b0bb7ee6d966412a8958fec3ff95fa13f489`。
- 当前焦点工程与活动文档一致（`sys.identity.consistent=true`）：活动页 `534probe`，uuid
  `a49f56119597d6d5`，type=`page`，父文档 `schematic2`；本批不修改该既有页。
- 运行 connector 0.5.18，仓库 0.5.21。两个 P1 tab 带 `isUnSaved` 标记；活动 534probe 无该标记。
  未获单独安全确认前，不热更新/重载该窗口，避免影响未保存内容。
- 真机动作默认只用旧 connector 已支持的只读 readback/netlist/geometry/export.render；若必须升级或新增落图
  才能验收，先停下报告，不把旧接口结果冒充新版本全能力验证，也不以 `doc.list` 的内容相似度替代 R1。

## 3. 真机能力边界

538 只有块级 `compile_island(s)` / `recompile_island`，没有组装配、页级 pack、ChangePlan 或落图入口。
真机验收应优先验证：从 `test` 只读取得的实时网表/库/页面信息与离线编译输入一致；局部 plan 的引脚、
网名、旗标/标签、身份、几何和渲染可回读核对。不得为了赶验收临时实现装配或 ChangePlan。

如确需新测试页，只能在本任务书明确授权后的独立小批中于 `/test` 新建专用页，记录新页 uuid 后再写；
不得复用或修改 534probe/P1，不得删除页。没有该小批与页级身份记录时，本任务不授权任何设计写。

## 4. 完成定义

- 对抗发现均有证据与处置；没有未处置 blocker/high/medium。low/note 必须写明为何不影响提交。
- 完整 Python、connector、dsh-plugin/typecheck/build 全绿；真机证据与限制如实记录。
- 不把局部 `ok=True`、离线 render、旧 connector 的只读结果说成整页/新版本/视觉全能力通过。
- 无真实工程容器、公司板数据、临时 hunt/evidence 目录或敏感信息被误加入提交；staged diff 经主线复核。
- commit 在全部检查通过后创建，汇报提交哈希、真机证据、剩余限制。未通过则不提交。

## 5. 验收记录

- doctor：`--project test` 8/9；唯一红项为运行 connector 0.5.18 vs 仓库 0.5.21。多窗未指定时的 4 个未验证是寻址歧义，不是板级失败。
- 对抗审查、真机与提交：待记录。
- 2026-10-25 用户再次明确要求先完成 539 真机核验和提交；本次允许显式暂存与一次 commit，
  不推送。540B/C 暂停，540A/B 的未提交改动不得混入。真机仍只读，不热更新、不新建页、不写工程。
- R1 复核：bridge status 仍为一个禁写真实工程窗口与 test 两窗；`/test` 的 friendlyName、
  projectUuid、活动 534probe uuid 与上文逐字一致，`sys.identity.consistent=true`。
  `document.current` 两个 P1 tab 仍带 isUnSaved，活动 534probe 无该标记；继续禁止热更新。
- 当前源码 `doctor --project test` 仍 8/9：SOP/daemon/probe/宿主/焦点均 PASS，
  唯一 FAIL 为运行 connector 0.5.18 vs 仓库 0.5.21。该命令 exit 1 是已知环境限制，不记板级失败。
- 暂存依赖审查：538 需要 534 soft-floor 与 536 schema/identity 才能形成可运行闭包；
  534/536 作为明确前置审查，540A/B/C 与其他历史内容按 `evidence/539/staging-plan.md` 排除。

## 6. 小域对抗处置

### 6.1 scope / compile / recompile（主线复现并修复）

| 编号 | 级别 | 复现与处置 |
| --- | --- | --- |
| F1 | high | 页锁被当成块局部坐标，多岛模块锁也缺少模块帧。修复：页锁不进入独立块闸并在 evidence 披露；单岛模块锁仍精确检查，多岛模块锁返回 `presentation-poor` 且无候选。 |
| F2 | medium | dict/None profile 在整份库扫描中抛 `AttributeError`。修复：布局前校验整份公开 profile 映射，逐岛返回 `facts-missing`；真正缺少某岛 profile 的原有局部隔离不变。 |
| F3 | medium | 未声明器件的锁被 scope 跳过。修复：compile 先返回 `facts-missing`，直接 readability 检查也始终报告未知锁部件。 |
| F4 | low | 同一读取同时有硬闸与 soft-floor 时分类顺序遮住硬闸原因。修复：硬闸优先，保留具体 category/action。 |
| F5 | low | frozen request 只冻结引用，原对象改后仍声称 unchanged。修复：记录 circuit/presentation/profiles 内容指纹，重编译当前内容时明确披露变化，不冒充快照。 |
| F6 | low | 显式等值 budget 被记为 changed。修复：按值比较，并把原 `budget=None` 解读为默认 IslandBudget；等值默认预算属于未变输入。 |
| F7 | low | 布局与检查器的 grid 可能分裂。修复：readability 总是收到实际 IslandBudget grid。 |
| F8 | note | IslandBudget 缺值域检查。修复：构造时拒绝非有限/非正 grid、channel、text_row，负几何间距、非法 rung 计数与非字符串旗标配置。 |

- 原探针：`.tmp_adversarial/scope-compile/probe_locks.py`、`probe_shapes.py`、`probe_recompile.py`；
  主线先复现原失败，修后三项均按上述契约完成。F6 另由主线探针补出「原 budget=None、后传显式默认预算」分支并修复。
- 回归：`test_539_island_locks.py`、`test_539_island_compile.py`、538 两组及 530 相邻三组，
  **127 passed**（独立 basetemp `.tmp_pt_539_compile_main4`）。默认 `scope=None` 与 538 单岛/作用域语义未放宽。
- 变异：未知锁、非法 profile、等值默认预算、零 grid 四组均使聚焦测试变红；随后用备份恢复，
  当前源码 SHA-256 与各自原值一致且无 `539-MUTANT` 残留。日志/备份在本地 `.tmp_539/mutation/`，不入库。
- 本域没有未处置 blocker/high/medium；low/note 也已修复，不以文档说明代替代码处置。

### 6.2 finalize / present / review-read / triage / live-read-only

- 现有 537 Python 工作流与实时证据测试主线复跑 **617 passed**；DSH finalize/receipt/present
  三组 **56 passed**。手写 finalize.json、跨 Session、并行 present、同尺寸改写、未跟踪文件、
  路径逃逸和普通文件不受影响均有真实测试；本域未复现新的未修复 fail-open。
- 537F 与消费者复跑 **146 passed / 1 failed**。唯一失败为 rulebody 固定摘要期待 537F 树，
  而工作树另有 540B1 的 `rules/facts.py` 改动；539 未改 rules。该红项留作脏树归属证据，
  不改摘要，最终由排除 540 的候选树全量验证。
- 真机第一次 finalize 因两处 summary 文案不一致返回 1 且零写入：顶部结论不等于权威
  `report.conclusion`，连接句含易误读的「已通过」。只修正人工 summary 后通过，未放宽校验器。

### 6.3 F9（medium）：同名原理图页覆盖 canvas 证据

- 真机 `test` 的两张 schematic 都有 P1。原在线渲染把两页都写成 `canvas-P1.png`，后图覆盖前图，
  而报告保留两个不同 bytes/sha256；`review-read artifacts` 复现为第一行 `bytes-mismatch`。
  这会错位视觉证据并阻止 finalize，不能手改报告绕过。
- 修复复用离线 192A 的撞名规则：首个保持原名，冲突时追加页 uuid 短后缀；PNG 与 SVG 回退、
  `export.render.fileName`、报告引用和实际落盘使用同一文件名。新增双 P1 端到端假桥回归。
- `test_checkup_cli`、192A、537 artifacts/evidence、025d 共 **131 passed**；canvas 变异被新测杀死，
  备份恢复后 SHA-256 一致。真机重跑后三份 canvas 全部 bytes/hash 吻合，第二份 P1 为
  `canvas-P1-a73c11.png`，`review-read artifacts.status=ok`。

### 6.4 真机只读验收记录

- R1 新快照：当前一个已连接窗口，实例 `inst-031432920-gt1ds6g2`；`/test` 的 friendlyName 与
  projectUuid 均与任务书一致，`sys.identity.consistent=true`。活动页变为 schematic1 的 P1
  （uuid `790ff841f8a73c11`），目标工程并未缺失。未热更新、未新建页、未写设计。
- 当前源码 `doctor --project test` 仍 **8/9**，唯一 FAIL 为运行 connector 0.5.18 / 仓库 0.5.21；
  按任务授权不执行建议中的热更新。
- 当前源码 `checkup --project test --out outputs/review/539`：exit 3，`completion=incomplete`，
  在线归档与实时原理图均为 0 器件/0 网络，不能解释为干净板或通过。
- `review-evidence`：exit 1，identity.verifiedAgainstReport=true，原 P1 焦点恢复成功；
  最终覆盖为 liveSchematic=failed、archivePcb=ok、livePcb=ok、schematicImage=failed、
  pcbImage=failed、datasheets=unavailable。两块 PCB 渲染 TIMEOUT，未声称视觉验收。
- `review finalize` 最终 exit 0：verdict=incomplete、delivery=partial、pending=0、needsManual=0；
  仅交付一致，不是板级通过。CLI 收据引用 14 个文件并逐一重算通过；第二次 finalize 后全目录
  19 个文件逐字节不变，最终 artifacts=ok。产物留在本地 `outputs/review/539/`，不入提交。
- 538 真机对拍：**不可判定**。`test` 当前没有可用于岛编译的非空电路、岛规格和对应实测 profile；
  不以空模型冒充 538 真机成功，也不临时实现装配、ChangePlan 或落图入口。538 的已验证范围仍是
  离线块级 compile/recompile，不是整页或真机视觉验收。
- 至此 F1–F9 均有代码/测试与真机处置；没有未处置 blocker/high/medium。完整候选树回归与提交哈希
  见后续记录。

## 7. 候选树、回归与提交审查

- 暂存闭包为 100 个实际有内容差异的文件；另两个允许路径经 Git 规范化后与 HEAD 无差异。
  540A/B/C、旧版本策略、工作区清理记录、真实工程容器和本地 evidence/outputs 均未进入。
  混合文件只收 534/536/537F/538/539 hunk；`git diff --cached --check` 通过。
- 公开 docs/tasks 已去除原会话 id、禁写工程名与具体实时引脚映射；剩余命中仅为
  匿名合成测试数据或同文件移动的既有注释。工程容器与 540 源码标记扫描通过。
- 最终暂存候选树全量 Python：**7731 passed / 20 skipped / 5 xfailed**。skip 原因已逐项读取，
  为既有布局闸、当前真机页态/私有工程、类型包或生成物状态等，不是大面积缺失证据被当作通过。
- connector：build + **536 passed** + typecheck。dsh-plugin：typecheck + **113 passed / 1 skipped**
  + build。生成物/同步/文档声明补跑 **42 passed**。
- 初次候选运行暴露的 archive Git 元数据、行尾、临时仓库环境和 `.venv` 缺口均只修测试环境；
  唯一源码回归（`scope=None` 未知锁旧文案）已修复并复跑。最终全量绿才允许创建一次 commit。
- 本次只提交，不推送、不发布。最终提交哈希在 commit 后汇报；真机限制仍按 §6.4，不写成
  connector 已升级、整页通过、视觉通过或 538 真机对拍成功。

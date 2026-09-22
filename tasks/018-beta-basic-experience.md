# 018：朋友内测版基础体验与发布准备（2026-09-22，deadline 17:00）

岳原话：① 多窗口切换基础体验（"012 就该做好的"）；② 安装包做好；③ skill 统合装载；④ 审查是重中之重（朋友主要用审查）。
执行纪律：实现与测试一律 commandcode/deepseek-v4.1-flash 子代理；Kimi 规划、复验、真机裁决。

## 总纪律（每个执行者必读）

- 不动 git（不 commit / add / checkout / restore）。
- pytest 必带 `--basetemp=.tmp_pt_home`（Windows 否则汇总行被吞假 exit 1）。
- 命令：`E:\boardwise\.venv\Scripts\python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home`；connector `cd E:\boardwise\connector && npm test`；tsc `npm run typecheck`（若 package.json 里脚本名不同以实际为准）。
- 不碰 `outputs/011e*`、`014_*`、`015b_*`、`016_*` 历史报告；不碰 `tests/fixtures/` 既有夹具。
- **禁止任何真机操作**（不跑 `bridge call` / `bridge start` / 不动 daemon 与编辑器；测试全部 mock）。真机验证归 Kimi。
- 基线：pytest 1196 / connector 279 / tsc 干净。交卷时三线只能增不能红。
- 变异验证 ≥2 个（cp 备份 + sha256 还原，禁用 git checkout）。
- 交卷格式：改动文件清单 / 三线数字 / 变异结果 / 偏差与存疑记录。发现任务书错了，如实上报，不许编造通过。

## §A daemon 单活跃 connector 防护（子代理 A）

**事故根因**（2026-09-21 实测）：两个 EasyEDA 编辑器窗口各装一个 connector，daemon 接受"后连接顶掉先连接"，两实例每 5 分钟交替抢占，写动作落到错误工程。

**设计决策（已裁定，照做）**：
1. connector hello 增加 `instanceId`（扩展加载时生成的随机 id，一次扩展生命周期内不变；connector 侧改动归子代理 B，本子代理只做 daemon 侧：hello 没有 instanceId 时按连接级 uuid 兜底）。
2. daemon 维护"活跃 connector 实例"：新 connector 连接到来时——
   - 无活跃实例 → 接纳为活跃；
   - 有活跃实例但其 WebSocket 已断开 → 新实例接管（正常 reload 路径，必须顺滑）；
   - 有活跃实例且连接活着 → **拒绝**（或在协议允许时接受连接但立即返回明确错误并关闭），审计日志记录 `connector_rejected`（含对端 instanceId/版本），daemon stdout 打印一行人话（"另一个编辑器实例已连接（instance …, connector x.y.z）。若非预期，请关闭多余的 EasyEDA 窗口"）。
3. `bridge status` 输出活跃实例信息 + 最近拒绝记录。
4. 相关的 daemon 文件：`src/boardwise/bridge/daemon.py`（连接/hello/审计都在这一带，以实际代码为准）；protocol 变更同步 `src/boardwise/bridge/protocol.py` 与 `docs/bridge.md`。
5. 测试：mock 双 connector 场景（活跃占用→第二个被拒；旧死→新接管；无 instanceId 兜底）。审计事件名固定 `connector_rejected`。
6. 顺手修：`cli.py:4201` edit apply 连接失败 `return 2` → **`return 3`**（CLI 契约：3 = 页状态不可陈述；连不上 daemon 时无法陈述页状态。016 场景 5 实测发现的 bug）。补测试钉住 exit 3。**注意**：只改 edit apply 这一处（`_cmd_edit_apply` 路径），其他子命令的 exit 码不动。

## §B connector 体验三件套（子代理 B）

**背景**：昨夜真机两层焦点不一致（doc.list 报 focused=/test，编辑区活动文档属 ROBOT ctrl FOC），doc.open 按活动工程寻址找不到 test 的 uuid，报错救了场但文案无指引。

**设计决策（已裁定）**：
1. **doc.open 报错指引**：openDocument 返回空 tabId 时，错误信息补上：当前活动工程名/uuid（经 document.current 通道）+ 若 doc.list 能在**别的已打开工程**里找到该 uuid → 明示"该 uuid 属于工程 X（focused 与否），当前活动工程是 Y；请先切换工程"。找不到也如实说"任何已打开工程里都没有"。错误码保持 CONNECTOR_ERROR。
2. **新增只读动作 `sys.identity`**：返回 ① doc.list 的 focused 工程 ② document.current 的活动文档所属工程 ③ 二者是否一致 ④ 活动页 pageUuid。供 CLI/AI 写前核查。进 `protocol.py` 动作表 + `docs/bridge.md` + api-names 生成源（若 api-names 是生成文件，改生成源并重新生成，别手改产物）。
3. **connector 版本协商**：hello 载荷已有 connectorVersion（审计实测）。daemon 侧记录即可（子代理 A 已做拒绝逻辑），本子代理做：**connector 启动时若发现自己版本 < daemon 声明的最低版本**（daemon hello-ack 里加 `minConnectorVersion`，初始值与当前版本相同），在编辑器里 toast 提示升级。daemon 侧加字段归本子代理一并改（很小）。
4. 测试：connector jest 全 mock；新增动作进既有 action 测试模式（参考 delete_primitives/modify_primitive 的测试写法）。
5. 打包版本号先不动（打包归 §D）。

## §C CLI 审查体验（子代理 C）

**背景**：朋友主要用审查。当前流程：用户手动导出 .epro2 → 告诉 AI 路径 → `boardwise review <file> --view schematic`。痛点：找文件麻烦、报告全英文。

**设计决策（已裁定）**：
1. **`boardwise review --latest <目录>`**：扫描目录（含子目录一层）里最新修改的 `.epro2`，打印选中了哪个文件（含 mtime），然后照常审查。默认目录参数缺省时扫 `~/Downloads`、`~/Desktop`、`E:\LC Project`（存在才扫）。与位置参数 `file` 互斥，同时给 → BAD_USAGE。
2. **报告中文摘要**：`--md` 报告顶部加一节中文摘要（findings 计数、每条 finding 的中文一行：规则中文名+位号+关键数值）。规则消息本体**不翻译**（英文留在原文行，评测配对不受影响）。规则 id → 中文名映射表放 `src/boardwise/rules/__init__.py` 或新 `rules/i18n.py`，只覆盖现有规则 id，缺 id 时回退英文 id 原文。
3. `review --json` 输出 schema 不变（评测 harness 只读它认识的键，不许动）。
4. 测试：`--latest` 选择逻辑（多文件取最新、空目录报错、与 file 互斥）、中文摘要渲染（快照比对要点而非全文）、schema 不变断言。

## §D 安装包（子代理 D）

**目标**：朋友（硬件工程师，未必有 Python）30 分钟装好。

**决策（已裁定）**：
1. 先调查后动手：connector 现有打包流程（`connector/package.json` scripts、015 是否打过 .eext、产物在哪）、Python 包现状（`pyproject.toml`/`setup.py`、依赖、Python 版本下限）、`boardwise doctor` 覆盖了哪些检查。**调查报告先落 `outputs/018_packaging_survey.txt`**。
2. `scripts/install.bat`：检查 Python（3.10+，没有则给官网链接并退出）→ 建 `.venv` → `pip install -e .`（或 pip install .，以调查为准）→ 跑 `boardwise doctor` → 打印下一步（装 connector、配对）。全程中文 echo，每步失败有明确提示。
3. `scripts/start-daemon.bat`：可见窗口起 daemon（标题 "boardwise daemon"，窗口内打印连接状态），附 `scripts/stop-daemon.bat`。
4. connector 打包：`scripts/build-connector.bat`（npm ci → build → 产物 .eext 路径打印）。若现有流程已是 npm 脚本，bat 只做封装。
5. `docs/install.md`：朋友视角安装指南（装 Python → install.bat → 编辑器装 .eext → 配对 → doctor → 第一次审查）。配图占位（图后补）。
6. 不实际执行安装（不建 venv 不 pip install），只产出脚本与文档 + 静态验证（bat 语法、路径引用存在性）。真机安装验证归 Kimi/岳。

## §E skill 统合（子代理 E）

**背景**：岳说"skill 写得非常散，把它统合好"。朋友 clone 仓库后，AI 应自动装载。

**决策（已裁定）**：
1. 先盘点：`C:\Users\xiangyu\.kimi-code\skills\` 下所有 boardwise/EDA 相关 skill（文件名、行数、内容主题、互相重叠），以及 `E:\boardwise\` 内是否已有 `.kimi-code` / `AGENTS.md` 约定。盘点落 `outputs/018_skill_survey.txt`。
2. 统合产物：**仓库内单一项目 skill** `E:\boardwise\.kimi-code\skills\boardwise\SKILL.md`（朋友 clone 即得）。结构：
   - 何时加载（提到立创 EDA / EasyEDA / 原理图审查 / boardwise / 画板）
   - 审查闭环流程（导出 → review → 报告 → review.mark 画布标记 → 016 的 edit plan/preview/apply）
   - 真机纪律 R1–R3 + 只碰 test/test2 的禁令（禁地：毕设FOC驱动板、CH340G、ROBOT ctrl FOC 等一切真实工程）
   - bridge 动作速查（从 docs/bridge.md 提炼高频 15 个，注明全表位置）
   - 真机事实坑表（从用户 skill 既有 §17/§18 条目迁入：两层焦点不一致、delete 逐件 ~3.7s、readback 无 mpn 通道、.eprj2 是目录册等）
   - 红线：不动 git、pytest 带 basetemp、变异验证纪律
3. 用户级旧 skill 文件**不删**（岳自己决定），在统合 SKILL.md 里注明"本文件为唯一权威，用户级散件以本为准"。
4. 中文写作，给 AI 读，祈使句、可执行检查清单风格。≤400 行。

## 复验矩阵（Kimi 收卷后跑）

- 三线：pytest / connector / tsc 全绿且数字 ≥ 基线 + 新增。
- mock 双 connector 抢占演示（子代理 A 的测试即证）。
- `review --latest` 在 outputs/ 上实测。
- 安装脚本静态核查 + 岳朋友机实测（发布后）。
- 真机：daemon 防护的行为验证（模拟第二连接）、sys.identity 真机读、doc.open 报错文案真机读（归 Kimi，编辑器在）。

## 016 收尾挂起项（不阻塞 018）

- 场景 6 重开验证（需岳本人关闭重开 test 工程 + 导出 #2）——岳醒后 Kimi 跟进。
- 016 提交与 onboarding 文档提交：等岳点头，随 018 一起。

---

## 交卷记录（2026-09-22 01:45，Kimi 汇总）

### 波①五路（agent-21~25）+ 波②两路收尾（agent-26/27），全部 commandcode/deepseek-v4.1-flash

- **§A daemon 防护**：hello 接纳/拒绝/接管三态 + connector_rejected 审计 + hello-ack minConnectorVersion="0.4.10" + status_lines。变异 4 CAUGHT。
- **§B connector 三件套**：sys.identity（两层焦点+一致性）、doc.open 诊断式报错（点名所属工程/活动工程/切换指引）、hello 带 instanceId、minConnectorVersion toast。变异 4 CAUGHT。
- **§C CLI**：edit apply 断连 exit 2→**3** 修复（016 场景 5 的 bug）；review --latest（缺省扫 ~/Downloads、~/Desktop、E:\LC Project）；--md 中文摘要（i18n.py 15 规则 id，--json schema 逐字节不变）。变异 3 CAUGHT。
- **§D 安装包**：install/start-daemon/stop-daemon/build-connector 四个 bat（**GBK+CRLF 编码决策**，UTF-8 实测被 cmd 解析错位；调查报告 outputs/018_packaging_survey.txt）+ docs/install.md。T1-T5 运行级验证（假监听器，未碰真机）。
- **§E skill 统合**：仓库首份项目级 skill `.kimi-code/skills/boardwise/SKILL.md`（197 行）+ 75 条机器核验声明全绿。重要事实：用户级 boardwise skill 实为 0 个（§17/§18 条目原在仓库报告里，已迁入并注明出处）。
- **波②收尾**：CONNECTOR_ALREADY_ACTIVE 入 ErrorCodes；status_lines 接线 bridge status；非 daemon 占用端口的 traceback 修复；bridge.md/README/getting-started 文档同步；仓库根 AGENTS.md（26 行轻量指向）。

### 复验（Kimi 串行，无并发）

- pytest **1244 passed**（1196→1244，+48）/ connector **305 pass**（279→305，+26）/ tsc 干净 / skill 核验器 75 claims 0 failed。
- 评审基线：test_review_eval 全绿（--json schema 不变钉死）；outputs/011e|014|015b|016 历史报告零触碰。
- **真 daemon 五拍验证**（mock connector 打 61190，无编辑器依赖）：A 接纳（ack 带 minConnectorVersion）→ B 拒绝 CONNECTOR_ALREADY_ACTIVE（文案点名持有者+socket 关闭，status 列出拒绝记录）→ A 死 C 接管 → 断开无残留（paired 962bf45e 不变）。**0.4.9↔0.4.10 交替抢占在新 daemon 上机制性不再可能。**
- connector **0.4.11** bump（package/extension/lock 三处 + lock 的 name 修正）→ `boardwise-connector-0.4.11.eext` 46.8KB 落盘；打包后 305/tsc 复绿。

### 岳醒后清单（真机遗留项）——2026-09-22 上午全部落定

1. ~~编辑器装 0.4.11~~ → 改走 **`bridge update-connector` 热更**（08:50 完成，0.4.10→0.4.11 顺滑接管；面板清单版本号仍显示 0.4.10，运行时代码已是 0.4.11）。
2. ~~真机读 sys.identity / doc.open~~ → **完成**（`outputs/018_live_reads.txt`）：identity consistent=true；doc.open 跨工程 uuid 被拒且报错含焦点工程/活动文档/doc.list 指引（诚实降级形态命中）。
3. ~~016 场景 6~~ → **PASS（saved_verified）**，一度误判 FAIL 后翻案，全证据见 `outputs/016_scene6_final.txt` 与 `tasks/016` §十.8；坑表新增 13/14/15。
4. git 提交（016+018 合并单提）——等岳点头，清单 `tasks/018-commit-checklist.md`（已 dry-run 验证）。
5. ~~install.bat 朋友机实测~~ → 已用干净沙盒实测 PASS 关闭（`outputs/018_install_test.txt`）。

### 未做/挂起（如实记录）

- 017 评测集扩充（8-12 板）：草稿在 tasks/017-eval-set-expansion.md，待岳裁选板/triage/节奏，本波未动。
- ~~install.bat 真装未验~~（已关闭：2026-09-22 08:4x 干净沙盒实测 PASS，见补记与 `outputs/018_install_test.txt`）；start-daemon.bat 主路径未端到端跑（仅岳机上实际用过）。
- tests/test_bridge_cli.py 有 35 行×2 逐字节重复测试（波②发现，待裁删）；test_module_hygiene 只扫 src 不扫 tests 的盲区同源。
- 僵尸 socket 风险（无 FIN 时新实例被拒直到 TCP 回收）：daemon 无协议级 ping 是早前决策，未改；真机观察点=reload 扩展后审计是否出现 disconnect。

### 补记（2026-09-22 06:0x）：edit apply 写前 sys.identity 一致性核查

- 执行者 agent-28 两次 2h 超时（实现与测试早已落盘，疑陷全量 pytest 循环），Kimi 接管复验：实现质量达标——sys.identity 在 geometry 重读**之前**；不一致 → exit 4 `focus_inconsistent` 零写入 + 两层工程信息中文提示；无法判定 → 降级 note 继续；老 connector（UNKNOWN_ACTION）→ 降级 note 继续（向后兼容 0.4.10，朋友可能装旧版）。
- 复验：`tests/test_016_edit_cli.py` 55 passed（+4）；全量 pytest **1248 passed**。变异双 CAUGHT：M1 不一致放行→红 exit 4 用例；M2 不可用当拒绝→红降级用例。sha256 还原一致。
- 教训：子代理任务书须写死"只跑受影响子集，禁止全量 pytest 循环"，并给私有 basetemp。

### 补记（2026-09-22 08:4x，Kimi）：安装沙盒实测 + install.md 走查修正 + 提交清单落位

- **install.bat 干净环境实测 PASS**：仓库最小集复制到一次性沙盒 `E:\tmp_018_install_test\`（模拟朋友拿到的 zip），后台 `cmd //c scripts\install.bat` 全程无干预跑完——自建 .venv → pip install -e .（websockets 17.1）→ doctor 自检 → 中文四步指引。功能实证：沙盒 venv 的 `boardwise --help` 正常、import 链指向沙盒 src。doctor 2/7（5 项 FAIL 全是"扩展未连接"，沙盒无编辑器的预期结果）。结论 `outputs/018_install_test.txt`，沙盒已删除。此条**关闭下方"未做/挂起"中 install.bat 一项**（start-daemon.bat 仍只在岳机上用过）。
- **install.md 三处修正**（交卷后走查发现）：两处版本示例 0.4.10→0.4.11（build 产物路径、About 弹窗）；补"第 0 步 · 拿到仓库"（原文默认朋友已有仓库，缺 zip 解压/.eext 放置指引——17:00 交付的真缺口）；"为避免 confusion"改中文。无测试锚定 install.md（已 grep 确认）。
- **提交清单**：`tasks/018-commit-checklist.md` 新写——35 条 git status 逐条归置，建议 **016+018 合并单提**（cli.py 同载两任务改动按文件不可拆，理由写在§1）；`tasks/016-commit-checklist.md` 标注被取代并补定波②实测结论。等岳点头。

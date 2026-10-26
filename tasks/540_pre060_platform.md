# 540 — 0.6.0 前工作区、业务边界与 Rust 平台准备

- 立项：2026-10-25，按岳的新路线指示。
- 前批：537（审查流程）与 538（块级独立子岛编译）均已验收，并随 `539` 的 `0f638de`
  提交（含在 0.5.22 历史中）。
- 本批不是绘制算法批，不是审查规则批，也不是 Rust 业务翻译批。

## 0. 当前基线核对

- 537/538 的关键生产文件、测试和路线文档 SHA-256 与各自验收记录逐项吻合。
- 2026-10-25 主线重新串行复跑当前树：
  - Python：**7708 passed / 19 skipped / 5 xfailed**，独立 basetemp `.tmp_pt_pre060_baseline`；
  - connector：**536 passed** + typecheck；
  - dsh-plugin：**113 passed / 1 skipped** + typecheck + build。
- `git diff --check` 通过。`537/538/534/536` 与 `539` 已随 `0f638de` 提交（含在
  0.5.22 历史中）；工作树剩余 `540` 与少量 2026-10-24 插件文档残渣，
  不得把整棵脏树归入 540，也不得用 git 写或覆盖操作“整理”它。
- 539 已单独收口：F1–F9、对抗审查、只读真机与全量复核完成，commit `0f638de`
  （含在 0.5.22 历史中）；真机结论 `completion=incomplete / delivery=partial`，
  不是板子通过。它不记为 540 的成果，也不在本批暗补真机或 commit。
- TASKMAP 首页的“在途无 / 工作树无”和 0.5.x 版本叙述已陈旧，文档收尾必须按实际状态修正，
  不能改写历史验收记录。

## 1. 三组 scope（不扩项）

### 540A — 工作区整理与固定目录约定

1. 先只读盘点仓库根与已注册 worktree；不整盘扫描，不读取真实设计容器内容。
2. 将源码/任务文档、长期证据、审查产物、实验、pytest 缓存、临时脚本、废弃 worktree
   分成 **保留 / 归档 / 可回收**；untracked 或 ignored 本身不是回收依据。
3. 建立固定目录约定，使探针、审查产物、实验和测试临时目录不再散落在仓库根。
4. 未经岳确认不移动、不删除；删除只能走 Windows 回收站。活动 worktree、真实工程、
   黄金板和历史证据不动。`git worktree remove/prune/add` 也属于 git 写，逐次询问。

### 540B — 共享底座 + 审查/绘制两条业务线

保持**一个仓库、一个模块化单体**：不复制 parser/model/bridge，不另建第二套业务逻辑。

- 共享底座：`.epro2` / netlist 解析、`DesignModel`、单位/几何、设计身份、公开电气意图、
  bridge/connector/daemon 的传输与权限。
- 审查线：规则、checkup、PCB review、证据/覆盖、review-read、triage/finalize、ReviewReport。
- 绘制线：PresentationSpec、岛划分、布局/布线、文字/旗标、LayoutPlan、draw apply/lint、
  连通与视觉验收。
- 两线只经公开导出、LayoutPlan 或报告产物交互；禁止内部互相 import。
- CLI 按线拆命令模块，主入口只组装/路由；旧命令参数、退出码和输出保持兼容。
- DSH 工具面按线组织，旧工具名以薄适配兼容；TS 不承接业务判断。
- 两线的任务书、排期、交接和 worktree 约定分开；共享底座、全量测试和真机操作串行。
- 用 AST/导入守卫测试机器执行边界。共享 parser/model/bridge/CLI 的改动是集成改动，
  单独复审，不夹在某一业务线的算法批里。
- 优先复用既有合同与模块；不得为目录美观做大搬家。本组不改审查规则、布局/布线算法或绘制输出。

### 540C — Rust 迁移平台准备

1. 冻结跨语言合同：CLI 参数、退出码、错误码、JSON schema、ReviewReport、LayoutPlan。
2. 用匿名合成或现有公开夹具建立 Python/Rust 差分与 golden 框架；不复制真实工程。
3. 建最小 Cargo workspace：core library + CLI skeleton + 一个无业务 smoke contract test。
4. 实际运行 `cargo fmt --check`、`cargo clippy -- -D warnings`、`cargo test`；先探测工具链，
   不擅自全局安装。
5. 进程边界优先采用 **Rust CLI + structured JSON**；不引入 PyO3/WASM/Node native addon。
6. 记录迁移顺序：纯函数/几何 → parser/model → 审查线 → 绘制线 → daemon 最后。
   Python fallback 只作过渡，不形成长期双业务实现。

## 2. 串行小批与派单

1. **540A0/A1**：只读盘点与目录约定；任何移动/回收另等确认。
2. **540B0**：模块归属、公开合同与依赖守卫；先给现状导入图和兼容命令快照。
3. **540B1+**：共享底座集成改动、业务线边界、CLI、DSH、独立排期/交接，逐小批串行；
   每一批只给一个文件域，主线独立复审。实际 worktree 创建前先问。
4. **540C0**：Rust 工具链与现有合同只读侦察。
5. **540C1/C2**：合同与差分/golden；随后最小 Cargo skeleton 和 smoke，不与业务迁移混批。
6. 文档随各组同步，最后统一串行全量验收；发版候选只报证据，不自行发版。

## 3. 0.6.0 后的双主线（写入权威路线，不在本批提前实施）

- **A 绘制线**：多岛、布局/布线、可读性、CH343 与后续真实设计。每个算法批仍过三关：
  机器闸、逐脚连通回验、视觉自审。
- **B Rust strangler**：0.6.x 新工具/引擎默认 Rust，例外必须登记；旧工具按垂直切片迁移
  （合同对齐 → Rust 默认 → 临时 Python fallback → 删除旧实现）。迁移与算法变化不得同批。
- **0.7.0**：目标是 Rust 接管全部受支持主流程，不是逐行翻译所有 Python；connector 与 DSH
  薄适配不要求 Rust 化。

## 4. 完成定义

- 固定目录约定生效；没有未确认的移动/删除，真实工程和历史证据未受影响。
- 审查/绘制依赖守卫通过，两线可独立派单，共享底座/集成测试有明确串行机制；行为不变。
- Rust skeleton、smoke、差分/golden 框架实际运行；Python/connector/DSH/Rust 检查全绿。
- roadmap、TASKMAP、SCHEDULE、handoff、AGENTS 及必要架构文档说清 0.6.x 与 0.7.0 的
  边界、验收和非目标；目录/构建/协作约定变化有可执行钉。
- 全量测试一次只跑一轮，真机操作串行且只在任务书逐字授权范围。
- 删除、真实工程写、git 写、推送、发布均逐次取得岳的明确批准；0.6.0 不自行发布。

## 5. 非目标

- 不修审查规则、不改布局/布线算法、不追求新的 `draw compile ok=True`。
- 不批量翻译 Python，不做第二仓库，不复制解析器/模型/桥，不引入双份长期业务逻辑。
- 不为赶演示补 538 明确没有的组装配、页级 pack、ChangePlan 或落图能力。
- 不清理整盘，不碰活动/档案 worktree、真实工程、黄金板、历史证据与既有 fixtures。
- 不做 git add/commit/checkout/restore/push，不发布；旧 539 不在本批暗中收口。

## 6. 验收记录

- 540A：**完成**。只读清单在 `evidence/540/workspace-inventory.md`，固定约定在
  `docs/workspace-conventions.md`；`.gitignore`、AGENTS、handoff、TASKMAP 已同步。
  520 hunt 辅助链改为显式 `tmp_path`，代理 RED/GREEN 后 **47 passed**；主线独立复跑
  520 + 目录守卫 + doc-claims **82 passed**。根 `hunt520-*` 在修复验收前后均 168。
  岳明确批准 A+B 后，315 个目录全部经 `DeleteDirectory+SendToRecycleBin` 回收：
  168 hunt + 5 空 tmp + 140 pytest basetemp + 2 缓存；后置计数为零，4 个 `.tmp_pt_*` 文件、
  C 类根散 dump、旧 worktree、其余老 `.tmp_*`、证据与真实工程均保留。
  逐项日志 `evidence/540/recycle-approved-20261025.json`（SHA-256
  `d54e2ce67ae7f33c19138e4a1926496df0aed119d8303309bc759c029a3845a9`）。
- 540B0：架构侦察与主线裁定完成，记录 `evidence/540/b0-architecture-review.md`。
  只保留 shared/review/draw/assembly 四类 owner，edit 归 draw；真实跨线债 5 处，其他 edit/draw 内边不扩大重构。
  侦察代理一次根临时文件误写+自行回收的纪律偏差已留痕，无既有文件影响。
- 540B0.1：**完成（主线复跑 24 passed）**。134 模块逐一归属，实际违规精确等于 5 条 legacy；
  合成越线边正控、根包 metadata-only、assemble shared 均有机器钉。三类变异后恢复并复绿。
  三份 SHA 与代理交卷一致。代理另自报一次对自建 basetemp 使用 `rm -rf`，属删除纪律违规，
  已留痕；未影响既有文件，后续 basetemp 不自行清理。
  详细小批顺序与完成定义见 `tasks/540b_review_draw_decoupling.md`。
- 540B1：**完成**。共享 `domain_of` / `is_auto_net`，legacy 5→2；行为基线
  `evidence/540/naming-baseline.json` 逐项不变，独立集成复跑 **284 passed / 2 skipped**。
- 540B2：**完成**。共享引脚连通与 NC 判定，patchpin 脱离 review，legacy 2→1；
  冻结行为见 `tests/test_540_shared_connectivity.py`，邻域 **294 passed**，两个变异体均被杀死并恢复。
- 540B3：**完成**。共享去耦库存/值恢复/`CapDecision`，137 模块/0 legacy；邻域
  **298 passed / 1 skipped**，规则指纹与报告来源 **153 passed**，两个变异体均被杀死并恢复。
- 540B4：**完成**。draw/edit/layout-lint/pintable/spec-validate 注册与分派抽取，139 模块/0 legacy；
  完整 parser 前后逐字节相同，draw 域合同 **10 passed**、draw CLI 邻域 **380 passed**、
  edit/lint/validate 邻域 **462 passed**，pintable 与联合守卫 **100 passed**，三个变异体均被杀死并恢复。
- 540B5：**完成**。review/checkup/triage/evidence/review-mark/parts/bom 注册与分派抽取，
  140 模块/0 legacy；联合合同 **118 passed**、行为邻域 **914 passed**，两个变异体均被杀死并恢复。
- 540B6：**完成**。shared/assembly CLI 注册与分派抽取，142 模块/0 legacy；24 个命令全部
  由 owner 模块注册/路由，最终合同 **127 passed**、行为邻域 **528 passed / 3 skipped**，
  两个变异体均被杀死并恢复。
- 540B7：**完成**。DSH 按 review/shared/draw 分线注册，旧 8 工具兼容并新增两个离线 draw 工具；
  **122 passed / 1 skipped** + typecheck + build，真实离线 smoke 为 3 candidates / 6 artifacts
  与 replay lint exit 0，两个变异体均被杀死并恢复；未发布。
- 540B8：**完成**。24 命令/10 DSH 工具行为矩阵、review/draw/shared 独立派单与集成锁、
  0.6.x/0.7.0 路线均已同步；文档与联合守卫 **85 passed**，`git diff --check` 通过。
  详细记录见 `tasks/540b_review_draw_decoupling.md`。
- 540C：**完成**。CLI/JSON/ReviewReport/LayoutPlan 合同、四 case Python/Rust 差分、
  最小两 crate workspace 与构建/派单文档均已落地；合同 28、合同+差分 35、Cargo 7 tests，
  fmt/clippy/test 全绿，联合守卫 89 passed。早期“MSVC 组件齐全”误判已纠正：只在任务目录
  使用官方 x64 载荷，没有全局安装或混合 CRT。证据 `evidence/540/c-acceptance.md` 及同目录
  toolchain、comparison、mutation 记录；详细拆分见 `tasks/540c_rust_platform.md`。
- 集成验收：**完成**。540C 与最终文档后串行复跑：Python **7876 passed / 21 skipped /
  5 xfailed**（480.63 s），connector **536 passed** + typecheck，DSH **122 passed / 1 skipped**
  + typecheck + build，Rust **7 passed** + fmt + Clippy 零警告；全部 exit 0。`git diff --check`
  通过，CLI 合同与 mutant 恢复 SHA-256 再核验通过。日志与命令见
  `evidence/540/final-regression.md`。540 全部工作因此在工作树完成、仍未提交；0.6.0 原有
  产品门槛不因此关闭，无真机写、git 写、推送或发布。

## 6.1 对抗修复与真机追加验收（2026-10-25/26，当前状态）

> 本节追加在 §6 旧验收之后，**不改写上面的历史读数**。三份读数分层要分清：
> `evidence/540/final-regression.md` = **首轮**（Python 7876/21/5、connector 536、
> DSH 122/1、Rust 7、4 case）；`evidence/540/final-regression-adversarial.md` =
> **对抗后首轮**（Python **8206 passed / 19 skipped / 5 xfailed / 1 failed**、
> connector 536、DSH 127/1、Rust 45 + 显式 4、5 case）。对抗后首轮**不是全绿**，
> 唯一红是 rulebody 源码指纹钉（见下）。

- **权威证据索引**（按用途取，不互相冒充）：
  - 最终候选读数：`evidence/540/candidate-regression.md` —— **由后续步骤产生；
    该文件存在并绿之前，不视为候选已通过**。
  - 本轮收口（指纹 + 真机摘要）：`evidence/540/final-regression-followup.md`。
  - 真机：`evidence/540/real-machine-instance-20261025-233933/25-final-report.md`
    与 `outputs/review/540/`；shared 行为 `evidence/540/b-behavior-equivalence.md`；
    540C `evidence/540/c-acceptance.md`；构建/差分见 `docs/rust-platform.md`。
- **指纹收口**：B2 权威化修复后 direct `7e3ac51a` → **`ea1d06e0`**、recursive
  `43979be9` → **`25b7de70`**，属**源码位置变化，不是 verdict 改变**；
  `tests/test_126a_pcb_review_plumbing.py` + `tests/test_540_shared_connectivity.py`
  **28 passed**。对抗后首轮那 1 红由此处置（不是重跑换读数）。
- **540C 对抗后**：8 个合同文件 **346 passed**；Rust 默认 **45 passed / 4 ignored**、
  显式语料 **4 passed**；真实差分 **5 case**（新增 `compile-page-result-projection`），
  双侧 normalized SHA-256 同为 `5230498201445920e02058bb11e99274e82be02c91952f38b9f2f919cb9d5f7c`。
- **DSH**：**127 passed / 1 skipped** + typecheck + build；真实离线 smoke 为
  3 candidates / 6 artifacts + page 8 pages / 16 artifacts + lint replay exit 0。
  **未热加载、未发布**。
- **真机（只读，风险面全程未写设计）**：R1 friendlyName **`test`**、
  projectUuid 前缀 `ea80fff6…`（全值见权威报告）、活动页 P1、`consistent=true`；
  doctor **8/9**（运行 connector 0.5.21 ≠ 仓库 0.5.22，未热更新）；checkup **exit 3** /
  `conclusion=incomplete`（0 器件 0 网络）；`review-evidence` exit 1 但
  `identity.verifiedAgainstReport=true` 且焦点已还原；`review-read` 六段可用
  （artifacts ok）；finalize 两次 **exit 0**、15 文件逐字节幂等；`delivery=partial`、
  `pending/needsManual=0`。通道权威值：`liveSchematic=failed / archivePcb=ok /
  livePcb=ok / schematicImage=failed / pcbImage=failed / datasheets=unavailable`；
  `livePcb=ok` 是**读数**通道，视觉复核**未完成**，`netlist=missing`。
- **证据上的收口纪律**：真机证据曾误引 checkup **初始**值，已由主线纠正为
  `review-evidence` 合并后的权威值并重算 manifest；最终记录只引用"最终只读结构化输出"。
- **裁决**：`finalize ok` 只表示交付内容与重算后的报告一致，**不是板级通过**；
  540 仍未提交、未推送、未发布；环境修复（daemon 重启 / revoke）仅经明确授权后执行，
  **最终 instance 只读轮未再做环境修复**；全程未热更新、未写设计；
  0.6.0 原有产品门槛（200A/B/C 与人工反激视觉锚）不因此关闭。

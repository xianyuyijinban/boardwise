# 540B — 共享底座与审查/绘制两线解耦

- 母任务：`tasks/540_pre060_platform.md`；架构裁定：`evidence/540/b0-architecture-review.md`。
- 原则：不改审查规则、布局/布线算法、命令参数/退出码/输出或绘制结果；只做边界、合同与适配。
- 四类 owner：shared / review / draw / assembly。edit 归 draw，不另设第三业务线；assembly 不是业务线。
  纯 `engines.assemble` 只组装公开 BoardSpec→DesignModel/PageLayout，归 shared；不作为布局算法。

## 小批顺序

### B0.1 owner manifest 与依赖守卫

文件域：`contracts/module-owners.json`、`tests/test_owner_rules.py`、`docs/architecture.md`。
逐模块完备归属，AST 覆盖函数内 import；当前只允许五条登记的 draw→review 债，合成越线边必红。
后续每修一批必须删除对应例外，最终空例外。

### B1 共享命名原语

文件域：新 `core/netdomains.py` 及 focground/facts/drawcompiler/islandlayout/drawapply 的窄导入改动、
owner 守卫与相邻测试。`domain_of` 两词表和 `is_auto_net` 正则只有一个实现，旧导入面保持兼容。
不改词表、大小写、前缀顺序、空串或自动网名语义。独立集成复审与规则指纹实测。

### B2 共享 NC/引脚连通

文件域：新 `core/connectivity.py`、facts/patchpin 的窄改动、owner 守卫与 035/相邻测试。
共享 pin_net/pin_company/nc_violation（必要时 pin_dangles），facts 保留旧名；review 仍拥有规则与 Finding。

### B3 共享去耦电气合同

文件域：新 `core/decap.py`、rules.decap/addcomponent 的窄改动、owner 守卫与 011d/029/039b/086/527D3 等测试。
core 只承载库存、候选、值恢复与 CapDecision；rules.decap 保留 Finding、严重度、模式与同网检查包装。
旧私有包装/公开导入面按需保留，不复制第二份决策。独立集成复审与规则指纹实测。

### B4–B6 CLI 兼容抽取

1. 固定 24 个顶层命令、draw 7 个子命令及现有顺序；同时保护 93 处 monkeypatch 的动态解析行为。
2. 按 draw → review → shared/assembly 串行抽取命令注册与分派；每批只动一个命令域和必要文本守卫。
3. 既有 handler 通过运行时注册表/namespace 动态解析，不让 `cli._open_cli` 等 patch 静默失效。
   `test_dsh_plugin_sync`、`test_157_auto_daemon`、test_092/093 的源文本依赖同批迁移。
4. 主入口最终只组装 parser 与路由。只改文件名、只搬 parser 不搬分派、或让命令模块反向 import cli
   都不算完成；不为追求行数另起大规模重写。

### B7 DSH 分线适配

- `index.ts` 只组装 review/draw/shared 注册；现有 8 个公开工具名保持兼容。
- 新 `boardwise_draw_compile` 只走离线 `draw compile`；新 `boardwise_draw_lint` 只接受
  `--snapshot` + `--render` 离线回放，不暴露 live page 或任何 apply。
- 结果经完整 JSON 文件 transport；TS 不计算候选、lint、verdict 或连通。构建产物同步生成，不发布。

### B8 独立派单与文档

- 分 review/draw 的任务入口、滚动排期和交接；共享平台单独排期，明确集成锁。
- 全量测试一次一轮，真机串行且逐字授权；迁移与算法永不同批。
- worktree 路径/分支/归属分开约定；任何实际 `git worktree add/remove/prune` 先单独问岳。
- 更新 architecture/handoff/TASKMAP/SCHEDULE/roadmap 与必要 AGENTS 文档，不虚称已建未授权 worktree。

## 完成定义

- owner 覆盖全部生产模块，draw↔review 与 shared→业务 import 为零，positive control 有效。
- 五条 legacy 边全部消除且没有新增边；旧规则/绘制行为与相邻测试保持。
- CLI 旧命令兼容、monkeypatch 可观察行为不失效；DSH 旧名兼容，新离线工具实际通过测试。
- 两线可独立派单，shared/全量/真机串行；文档与真实 worktree 状态一致。
- Python/connector/DSH 全量串行复跑通过；无真实工程写、git 写、发布或未确认删除。

## 验收记录

- B0.1：完成；主线复跑 24 passed，134 模块/5 legacy，三类变异恢复后复绿。
- B1：完成；`core/netdomains.py` 共享地网域与自动网名原语，旧导入面保持对象同一，
  legacy 5→2。冻结命名样例逐项不变，独立集成复跑 **284 passed / 2 skipped**。
- B2：完成；`core/connectivity.py` 共享 `pin_net` / `pin_company` / `nc_violation` /
  `pin_dangles`，patchpin 不再 import review，legacy 2→1。五个冻结 NC/readback 样例不变，
  邻域复跑 **294 passed**；named-net 与 dangle-inversion 两个变异体均被杀死并按 SHA-256 恢复。
- B3：完成；`core/decap.py` 共享门控电容库存、值恢复与 `CapDecision`，addcomponent 不再
  import review，137 模块/0 legacy。review 仍拥有 Finding、严重度、模式与同网包装；邻域复跑
  **298 passed / 1 skipped**，规则指纹与报告来源复跑 **153 passed**。gated-inventory 与
  threshold 两个变异体均被杀死并按 SHA-256 恢复；direct/recursive 指纹实测量为
  `7e3ac51a` / `43979be9`，账本说明位移来自源码下沉而非判决变化。
- B4：完成；`commands/draw.py` 拥有 draw/edit/layout-lint/pintable/spec-validate 注册与运行时
  dispatch，不反向 import `cli`，handler/helper 保持原位，注册表与直接 handler 均由
  assembly 在调用时提供。139 模块/0 legacy；完整 argparse 树、帮助、默认值与 9 组
  namespace 前后逐字节相同（SHA-256
  `500134aaf813af231dfd3e807480dca10c54d89abb4b3663ea2c2fb15d6413d6`）。
  draw 域合同 **10 passed**，owner/DSH/doc/layer 联合守卫 **58 passed**；draw CLI 邻域
  **380 passed**，edit/lint/validate 邻域 **462 passed**，pintable 与联合守卫 **100 passed**。
  dispatch-subcommand、
  parser-registration、edit-dispatch 三个变异体均被杀死并按 SHA-256 恢复。
- B5：完成；`commands/review.py` 拥有 review/checkup/triage/evidence/review-mark/parts/bom
  注册与分派，9 个 direct handler 和 2 个 registry 均由 assembly 在调用时提供；不反向
  import `cli`，仅引用 review 引擎的 parser 常量。140 模块/0 legacy；完整 parser 仍与
  B4 前基线逐字节相同。联合合同 **118 passed**，review 行为邻域 **914 passed**，恢复后
  合同 **7 passed**；direct-dispatch 与 parts-selection 两个变异体均被杀死并按 SHA-256 恢复。
- B6：完成；`commands/shared.py` 拥有 bridge/doctor/compare/persistence/arch/intent/config
  注册与分派且无包内 import，`commands/assembly.py` 拥有 install-skill。142 模块/0 legacy；
  `build_parser` 为 24 个注册调用、`main` 为 24 个路由且无直接 `_cmd_*` 调用，均有结构钉。
  最终联合合同 **127 passed**，行为邻域 **528 passed / 3 skipped**；完整 parser 仍与
  B4 前基线逐字节相同。direct-dispatch 与 bridge-selection 两个变异体均被杀死并按
  SHA-256 恢复。
- B7：完成；`index.ts` 只组装 review/shared/draw 注册与 delivery，旧 8 个工具名、顺序、
  参数和 JSON 行为不变，末尾追加 `boardwise_draw_compile` / `boardwise_draw_lint`（共 10 个，
  无 apply/live page 面）。compile exit 0/5 与 lint exit 0/1 经完整 `--json` 文件 transport；
  TS 不计算候选、finding、severity 或 verdict。DSH **122 passed / 1 skipped** + typecheck + build；
  真实离线 smoke 为 **3 candidates / 6 artifacts** 与 replay lint exit 0。两个 transport/argv
  变异体均被杀死并按 SHA-256 恢复，README 与构建产物已同步，未发布。
- B8：完成；行为矩阵 `evidence/540/b-behavior-equivalence.md` 覆盖 24 个 CLI 命令和
  10 个 DSH 工具，review/draw/shared 三份派单入口与集成锁已接入 AGENTS、architecture、
  roadmap、TASKMAP、SCHEDULE、handoff。没有声称创建专用 worktree。文档/owner/layer/
  workspace/CLI 联合复核 **85 passed**，`git diff --check` 通过。540 最终全量在 540C 之后串行
  （结果见本文末追加段与 `evidence/540/final-regression*.md`）。

## 对抗修复与追加验收（2026-10-25/26）

> 上面的 B0.1–B8 记录一律保持原样。**B3 记录里的 `7e3ac51a` / `43979be9` 是当时的
> 历史读数**，本节追加对抗修复后的新值，不回头改写。

- **B2 权威化（追加）**：caller-held component 视为权威，`detached` / key-mismatch /
  stale-copy 三种状态不再被误判成"件在场"或"连通成立"。这是**同一条判定收紧**，
  不是新增规则，也不改 `Finding`、严重度或 CLI 行为。
- **指纹随源码下沉而变**：direct `7e3ac51a` → **`ea1d06e0`**、recursive `43979be9` →
  **`25b7de70`**。原因是权威数据的落点从规则体内移到共享/源码位置，**不是判决改变**；
  `tests/test_126a_pcb_review_plumbing.py` + `tests/test_540_shared_connectivity.py`
  合跑 **28 passed**（对抗后首轮全量里唯一的红就是这条钉，由此收口）。
- **Origin 语义**：pairing-write 只豁免**精确** `https://client`（scheme/host 的大小写按
  URL 语义等价，`HTTPS://Client` 同样接受）；其他 http(s) origin 仍一律拒，lookalike 有
  **安全负例**钉住：`http` scheme、端口、路径/尾斜杠、userinfo、query/fragment、相似主机名
  等变体都不得豁免。bridge/doc 邻域 **160 passed**。
- **真机侧旁证**：出现 `connect origin=https://client` → pairing → hello ok，首次配对恢复。
  环境修复（daemon 重启 / revoke）仅经明确授权；**最终 instance 只读轮未再做环境修复**；
  全程未热更新、未写设计 —— Origin 豁免也不要写成"设计写"。
- **变异**：最终 mutant **3 failed** → 按备份 `sha256`/`cmp` 还原后 **17 passed**；
  恢复复核 SHA-256 `c4d0e8e0afede4c451f609b60b6f95c701ea22764e3567f9ca9f02b5af78dfaa`。
  全程未用 `git checkout --`。
- **纪律留痕（如实记，不掩盖）**：此前一名 DSH 执行代理对**当时并不存在**的自建临时目录
  执行了 `rm -rf`。实际**没有删除任何文件**，但这违反删除纪律（AGENTS 红线 4：删除一律
  进回收站，自建 basetemp 也不能例外）。本次**没有**清理该目录，既有文件与证据未受影响；
  此后 basetemp 一律不自删，交由人工/批准流程处置。

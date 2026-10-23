# 交接记忆 —— 换 harness / 开新会话先读这份

> **这份文件是路由，不是规格。** 它只回答三件事：这是什么项目、三条线现在各在哪、
> 干活要去读哪份权威文件。细节一律不在这里复制；两处说法冲突时以它指的文件为准。
> 写它的场合：从 Kimi Code 迁到 DeepSeek Harness（dsh）这类**换 harness**、开新会话、
> 或换人接手。口径是岳定的那句：**机制不搬，只搬记忆**。最后核对：**2026-10-23**。

## 1. 一句话

boardwise 是**立创 EDA Pro（EasyEDA Pro）的 AI harness**，五条能力：① 离线审查
（20 条自有规则 + 主机 ERC/DRC + 数据手册闸）② 把审查发现画回编辑器画布 ③ 从一条 finding
生成并执行局部修改 ④ 经本机 bridge 读写**活着的**编辑器 ⑤ 原理图自动绘制（画法编译器
`draw compile → plan → apply → lint`）。

仓库 `E:\boardwise`（GitHub `xianyuyijinban/boardwise`，分支 `main`）。跑 Python 一律用
**仓库自己的解释器** `.venv/Scripts/python.exe`。桥 daemon 默认 `127.0.0.1:61190`，
不在时任何需要桥的命令会自己 detached 拉起（日志 `~/.boardwise/log/`）。

## 2. 先读哪几份（入口路由）

| 什么时候 | 读哪份 |
|---|---|
| 动手之前（任何一次） | [`AGENTS.md`](../AGENTS.md)——红线 + 项目地图；**dsh 原生自动读它** |
| 审查 SOP（何时加载 / 闭环 / R1–R3 / 坑表 / 命令面） | `SKILL.md` 的**两份同步副本**：`.kimi-code/skills/boardwise/SKILL.md`（kimi 的约定路径）与 `.agents/skills/boardwise/SKILL.md`（dsh 等通用入口）；两份**逐字节相同**，同步由 `tests/test_doc_claims.py` 盯着 |
| 现在在哪 / 版本骨架 / 方向 | [`docs/roadmap.md`](roadmap.md)（**稳定层**） |
| 做什么、不做什么 | [`docs/product-boundary.md`](product-boundary.md) |
| 任务全图（编号 / 状态 / 证据） | [`tasks/TASKMAP.md`](../tasks/TASKMAP.md) |
| 下一版排期 | [`tasks/SCHEDULE.md`](../tasks/SCHEDULE.md) |
| 查历史细节 | `PROGRESS.md`——**不要从头读**（1000+ 行流水账），只在需要时 grep |

深水区各自的权威件：审查操作细节 [`docs/review-sop.md`](review-sop.md)｜画法
[`docs/draw.md`](draw.md)｜桥协议全表 [`docs/bridge.md`](bridge.md)｜真机坑全表
[`docs/pits.md`](pits.md)｜测试与保密闸地图 [`docs/testing-doctrine.md`](testing-doctrine.md)。

## 3. 三条线的当前状态（核对日期 2026-10-23）

> **2026-10-23 已合并提交到 `17893f4`（version 0.5.20）**：绘图线 worktree 已并回 main
> （merge `534d21f`），审查线 #83–#86、插件线 shim、记忆交接均已 commit。工作树另有一笔
> **未 commit 的 535 跟进修复**（143 F1 分支序，见 §3.2 末）。一切 git 写操作仍逐次经岳批准。

### 3.1 审查线 —— 实板反馈的修复循环

GitHub issue **#83–#88 全部仍是 OPEN**。仓库纪律：**issue 不由我们关**——修复落地只
comment「待验证」+ 验证步骤，由提出人实测确认后自己关；代码完成 ≠ 问题解决。

| # | 一句话 | 状态 |
|---|---|---|
| 83 | `core/measure.py::_capsule_distance` 的铺铜包含性判据两个析取项都拿多边形比**自己的顶点** → 有铺铜的配对**恒判 `contained`**（间距静默丢行、岛数恒相连） | **修复已在工作树**：`src/boardwise/core/measure.py`；新回归 `tests/test_83_pour_containment.py`（手算几何） |
| 84 | `pcb-track-ampacity` 不建模铺铜/分支：铺铜担主电流、10 mil 细线只做取样时按最小线宽判过载（实板 4 条假 ERROR） | **修复已在工作树**：`measure.py` 新增 `conductor_copper`（分段分辨率 + 铺铜面积/跨度粗读），`ipc.py` 有承担铜（门槛 `max(3×最窄段, 所需宽度)`，屋规）时细线档降 **UNKNOWN(INFO)** 逐段点名；新回归 `tests/test_84_ampacity_branch.py`（11 条）；实板 A 6 ERROR→0/5 INFO |
| 85 | `pcb-voltage-spacing` 把**同一颗器件封装内**的焊盘对当间距违规（实板 10 条 WARN 里 4 条同颗） | **修复已在工作树**：`measure.py` 新增 `_Shape.component` / `ClearanceResult.within_one_footprint` / `net_clearance(ignore_within_component=…)`，消费侧 `src/boardwise/rules/pcb/ipc.py`（并排报间距、不当 WARN） |
| 86 | 去耦候选池：旧库实例 `Value` 为空时读不到容值（MPN/货架其实有）→ 身旁去耦被报成很远 | **修复已在工作树**：`rules/decap.py`（`value_source` + `recovered_capacitance`，原理图 `Value` 为空时按货架 MPN / C 号补值并标注来源），消费侧 `rules/pcb/distance.py` / `pcb/regulator.py`；新回归 `tests/test_86_legacy_value.py` |
| 87 | 审查顺手性五条：报告不带引擎版本 / `export.render` 对 PCB 超时 / `review-summary` 覆盖 / finding 无元素身份 / `sch.readback` 无 value | 未动 |
| 88 | **#83 的修复带出来的新问题**：铺铜多边形用 `PourShape.points`（弧当弦，见 135）参与间距/连通判定 → 假 0.0 短路 WARN 与假岛数 | 已开；作为 **5 条 `xfail(strict=True)`** 记档（`test_126c` ×2、`test_131f`、`test_133d`、`test_135`）；根因是弧当弦的视图，修法指向「弧展开的 rings 视图」 |

**下一步**：#87（顺手性五条，未动）→ 回收 #88（现在有 5 条 xfail 占位，修好会自己变红提醒摘掉）。

### 3.2 绘图线 —— 多岛原理图（**已并回 main**，worktree 仅作证据档案）

- **规格（当前有效）**：`docs/schematic-style-spec.md`——黄金板绘图规格 S-01…S-21，每条标
  `[硬]`（违反即判废）/`[统计]`/`[观察]`。算法困境与接口简报在
  [`docs/drawing-brief-v2.md`](drawing-brief-v2.md)（它已取代 `docs/drawing-algorithm-brief.md`）；
  画法宪法（R1–R12）在 [`docs/schematic-conventions.md`](schematic-conventions.md)。
- **520a2–533 已全部并回 main**（merge `534d21f`，绘图线分支 `drawing-530-533` =
  `73c5e1d`）。worktree `E:\boardwise-wt520` 保留为证据档案（`evidence/520*/53x*` 在那边，
  未入 git 是惯例），别再往里写东西。
- **合并暴露的三层回归（535 批修复，commit `2c71844`）**——worktree 没拷 `outputs/`，
  一批夹具测试在那边一直 skip，合并到主树才真跑（「全绿变假」）：
  ① `pin-text-press`（同器件符号内部艺术字自压，摆放不可分离）单模块路径按岛路径同条款
  容忍（`drawcompiler.single_module_gate_violations`，cap=3，tolerated 记 notes 不进
  hard_violations）；② 地网布线失败的降级改为**旗标+记账**（530A 铁律：地/电源不许网络
  标签），unrouted 分支重排顺带消除了 520E 记录被 clobber 的潜伏 bug；③ 埋脚逃逸
  （`_no_step_out` + `_elbow_route(crossings=)`：搜索一步迈不出时才许取被跨线拒的 L）。
  全量 **6942 passed / 0 failed / 19 skipped / 5 xfailed**。
- **工作树里还有一笔未 commit 的 535 跟进**：自审抓到自己把 gnd 降级排到了 143 F1 拒绝
  （库无旗标符号的多脚网不许落成标签）**前面**，已把 `flag_downgraded` 拒绝挪回 gnd 分支
  之前。**提交前先跑受影响的测试文件 + 全量**。
- **下一步**：534（`tasks/534_ch343_uart.md` 已备好）——CH343 USB 转 UART 小板，绘图线
  第一次画全新设计，三关全过才算完。

### 3.3 插件线 —— boardwise-dsh（发给 dsh 用户的产品面）

- `dsh-plugin/package.json` 0.1.2 → **0.1.3**（commit `23b2a53`）：`npm run check` 全绿
  （50 passed / 1 skipped + typecheck + build），`npm pack` 出 `boardwise-dsh-0.1.3.tgz`，
  `npm publish --dry-run` exit 0。
- 仓库根 `package.json` **shim 已随 23b2a53 入库**（`main`/`types` 指进 `dsh-plugin/lib/`）——
  DSH STORE 那条 `dsh plugin add github:xianyuyijinban/boardwise` 以 **push 后的 HEAD 树**
  为准，push 前商城安装仍装到空壳。
- **待做**：`npm login` → `cd dsh-plugin && npm publish --access public`（**岳的 npm 账号，
  未 publish**）；push 后等几小时复检商城页。
- 纪律：**TS 侧不实现任何审查逻辑**；CLI 命令面变更时检查 dsh-plugin 工具面要不要跟，
  漂移哨兵 `tests/test_dsh_plugin_sync.py` 常跑；插件版本号等 0.6.0 再同步。

### 3.4 迁移线（Kimi Code → dsh）

方案在**仓库外**：`C:\Users\xiangyu\.kbw-dsh-migration\migration-to-dsh.md`（782 行，调研稿，
**待岳审 §5 的 Q1–Q14**）。口径是「**机制不搬，只搬记忆**」：

- **dsh 原生的**（不用自建）：`AGENTS.md` 自动注入（含用户级 $DSH_HOME/AGENTS.md）、
  `subagent` / `subagent_fork` / `workflow` / `jobs` 的派单与并行、`session.v4.jsonl.zstd` +
  `headless --json` 事件流、`/compact` 与 `compaction-basic`。
- **本次搬的**：SOP 落点 → `.agents/skills/boardwise/SKILL.md`（+ 与 kimi 路径的同步测试）；
  `AGENTS.md` 权威指针 → 两份同步副本；这份 `docs/handoff.md`。
- **与 harness 正交、原样生效的**：保密闸（`.githooks/*` + `tools/check_repo_hygiene.py`）、
  进程闸（`tests/conftest.py` → `tests/_process_guards.py`）、`evidence/`+`outputs/` 惯例。
- **dsh 侧已知硬约束**（动手前先读方案，别现场发现）：Windows 上 dsh 的 agent **只有 pwsh 工具、
  没有 bash**（`tool-bash` 在 win32 被 base 关掉）；`dsh-schedule` 默认不装且 headless 装不上
  （要 Host Web 的 session controller）；`maxActiveSubagents` 默认 8，与仓库「整机全量槽 = 2」
  不联动，**要降到 2**；Kimi 那边第三方网关（opencode 等 provider）在 dsh 侧没有对应物。

## 4. 铁律索引（为什么、怎么做都在权威件里，这里只指路）

| 铁律 | 权威件 |
|---|---|
| 不动 git；**删除一律进回收站**（禁 `rm`/`rm -f`/`unlink` 直删，临时目录/变异备份也没有例外） | `AGENTS.md` §红线；SKILL.md §7（Windows 原生通道写法） |
| 真机写操作前：**R1 身份判定**（`doc.list` 焦点工程名与任务书**逐字一致** + 页特征全项命中）/ **R2 事故申报**（证据不足只许报「异常待裁」，假警报与误删同等对待）/ **R3 找不到 ≠ 已清** | SKILL.md §4；`tasks/012-basic-experience.md` |
| 只碰任务书**逐字点名**的测试工程；真实工程是禁地（`CH340G.eprj2` 等一律不许写） | SKILL.md §4 |
| 工程容器文件（`.epro2/.eprj2/.eprj3/.epru/.esch/.epcb`）**永不入库**，派生副本（`.bak`/`.orig`…）同罪 | SKILL.md §4 R4；`tools/check_repo_hygiene.py` |
| 公开产物里公司板只用 `PCB1/PCB2/PCB3` 匿名代号；产品名/应用场景/客户/关键型号零出现 | SKILL.md §4 R4b |
| **绘图交付红线**：100% 横平竖直、导线不穿器件框、交叉趋零、内容不进标题栏、交付前过 `draw lint` | `docs/schematic-style-spec.md`（S-01/S-08/S-10/S-11…）；SKILL.md §3 |
| 文档里 load-bearing 的声明必须**机器可验**，并在 `tests/test_doc_claims.py` 有钉（文案不许跑赢数据） | SKILL.md §7；`tests/test_doc_claims.py` 的模块 docstring |
| 发布闸三闸（挖洞 swarm / 上机 / 实测）缺一不发；正式版一周最多一发、何时发由岳定 | `docs/testing-doctrine.md` §发布闸；`docs/roadmap.md` §1 |
| 新增 bridge 动作三处同步（`protocol.py` 目录 + connector handler + `docs/bridge.md` §4） | SKILL.md §7 |

## 5. 怎么干活

**四线（全绿才交卷）**——

```bash
.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile --basetemp=.tmp_pt_home
cd connector && npm test && npm run typecheck
cd dsh-plugin && npm run typecheck && npm test && npm run build
```

- `--basetemp` 一个字都不能省（Windows 上否则汇总行被吞、假 exit 1）；并行**只许**
  `-n 4 --dist loadfile`——`-n auto` 打满主机被岳叫停过，`--dist load` 会把同文件的测试对拆到
  不同 worker；多前场并行时各用各的 `.tmp_pt_<批名>`。
- **子代理纪律**：一个任务书只装一个缺口 / 一个文件域，串行小批，每批半小时内交卷
  （两小时黑箱 + 大上下文 = 幻觉与返工，060 实测被 timeout 斩）。整机全量并发槽只有 2
  （`tests/_process_guards.py` 在机器侧兜底，理由见 `AGENTS.md` §子代理纪律）；探针/脚本
  单进程；长命令带 timeout；交卷前收干净自己起的 daemon 与后台任务。
- **证据惯例**：`evidence/<批号>/`（报告 + `probes/` + `raw/` + 产物 sha256）、`outputs/`、
  `.tmp_*`——后两者与 `evidence/` 均 gitignore。变异验证 ≥2（**`cp` 备份 + `sha256`/`cmp`
  还原，禁用 `git checkout --`**：它拉回 HEAD，会把未提交的改动整个冲掉）；append 落盘后
  立刻 `grep -c` 独立计数防双执行。

## 6. 还没定的（换会话/换 harness 时别自作主张）

- **v0.5.20（正式版，6.0.0 前最后一个正式版）发布在途**：修复与合并已提交到
  `17893f4`；发布闸②上机（在线≡文件对拍 56=56、draw lint、daemon 0.5.20）与③实测
  （exe 重打 `ffdec920…`、隔离端口冒烟、版本同号、全量 6942 绿）已过；闸①挖洞因子代理
  通道全死（opencode go 429 / step-5 400 / space-bunny 403 / commandcode 欠费）改主循环
  自审——自审抓到并修了一个洞（143 F1 分支序，未 commit）。**剩下的发布步骤**：535 跟进
  commit → 全量复跑 → exe 重打（代码变了必须重打）→ SCHEDULE.md 行 → tag v0.5.20 →
  push（git 走代理 `https_proxy=http://127.0.0.1:7890`）→ gh release。
- **地网旗标降级的电源类问题待岳裁**：`_label_fallback` 现在只对 gnd 类改旗标；power 类
  （如 HVDC/SEC_12V）仍按 520E 落网络标签——岳的 520E 与 530A 两条裁定在这里冲突，
  是他的电话，不是我们的默认值。
- **E: 盘三项待岳拍板**：`E:\boardwise-sources-backup-20261015`（21MB，与
  `blocklib/sources/` 逐字节冗余）；两个 mirror（`boardwise-mirror-backup-2026101{5,7}`，
  共 85MB，10-15 历史清洗前旧历史的**唯一**副本）；11 个注册旧实验 worktree
  （`.tmp_cpsat` 等，约 1.2GB，可 `git worktree remove`）。
- **迁移方案 §5 的 Q1–Q14 全部待岳裁**：主代理载体（Web / Desktop / headless）·
  `DSH_HOME` 要不要做一次性 pnpm 重链（store 分裂，裸 `dsh plugin` 必报
  `ERR_PNPM_UNEXPECTED_STORE`）· 子代理模型接不接第三方网关 · 500k 红线纪律怎么改写 ·
  cron 怎么接 · 阶段 2 做哪几个 layer。方案里的【推断】不是裁决。
- **版本**：`v0.5.19` 已发（内测，tag）；`v0.6.0` 冻到 10 月底，**四个阻塞项缺一不发**——
  122 E 阶段（200A/B/C）+ 高速 A 档 1~3、**绘图线过锚**、527D2/527D3（✅ 已落）。
  见 `tasks/528_060_gate.md`。
- `R4` stub 冻结到 0.6.x 之后；`201C` 与 `121` 搁置（`201C` 备份在 `.tmp_201c_hold/`）；
  `text_overlap` 代价项由 526 撤回（「只做一半的约束比不做更差」）；`v0.6.x` 起做 V4 适配。

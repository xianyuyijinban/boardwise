# 审查线派单入口（540B8）

> 这是 review 线的任务路由，不复制规则规格。操作 SOP 以 `.agents/skills/boardwise/SKILL.md`
> 为准；现状与证据以 `tasks/540b_review_draw_decoupling.md` 和
> `evidence/540/b-behavior-equivalence.md` 为准。

## 1. 业务边界

| 可以派给 review 线 | 不应夹带 |
|---|---|
| `rules/**`（shared 的 `rules.base`/`rules.values` 除外） | 布局、布线、旗标、文字几何或绘制算法 |
| checkup、PCB review、证据/覆盖、review-read、triage/finalize、ReviewReport | `engines/draw*`、`core/layoutplan.py` 等 draw 内部 |
| parts/BOM/datasheet/catalog/harvest 等资料与器件链 | shared parser/model/bridge 的“顺手优化” |
| `commands/review.py` 的审查命令注册/分派 | 其他 19 个顶层命令的注册或 DSH draw 工具 |

依赖方向只能是 **review → shared / review**。不得新增 review→draw；shared 不能反向
import review。Finding、severity、mode 与报告措辞仍归 review；B1–B3 下沉的命名、
引脚连通、去耦库存和 CapDecision 是 shared 合同，不能在规则里复制第二份。

## 2. 公开入口

- CLI：`review`、`checkup`、`need-datasheet`、`triage`、`triage-batch`、
  `review-evidence`、`review-read`、`review-eval`、`review-mark`、`parts`、`bom`。
- DSH：现有 review 工具名保持；`review finalize` 的 Session receipt 与 delivery gate 不变。
- 共享输入：公开导出 / DesignModel / CircuitSpec / DesignIntent / 部件货架；输出是报告与
  审查证据，不是 LayoutPlan 的内部对象。

## 3. 派单规则

1. 一张派单只写一个缺口和一个文件域，先列允许文件与相邻测试；不夹带 shared 或 draw 改动。
2. 确需改 shared parser/model/bridge/core/CLI 时，停止按普通 review 批处理，改走
   `tasks/shared-platform.md` 的集成锁；审查规则变化与迁移不得同批。
3. 规则语义、严重度或 verdict 变化必须先有行为证据和反例；纯解耦批不得借测试红灯改判。
4. 全量 pytest 一次只跑一轮，`-n 4 --dist loadfile` 且每批独立 basetemp；真机操作串行，
   只碰任务书逐字点名的 `test`/`test2`，真实工程不写。
5. 任何 git 写、push、发布、删除或 worktree add/remove/prune 都要另获岳的明确批准。

## 4. 验收与交接

- 小批先跑 `tests/test_540_cli_review.py`、对应规则/报告邻域和 `tests/test_owner_rules.py`；
  shared 边界改动另跑 `tests/test_540_shared_{naming,connectivity,decap}.py`。
- 最终串行验收包含全量 Python、connector、DSH 和（540C 后）Rust；邻域读数不能写成全量。
- 交接写清：行为基线、实际命令与读数、变异及 SHA-256 恢复、未覆盖项、后续依赖。
- 当前路线债：0.6.0 的 200A/B/C 仍按 `tasks/528_060_gate.md` 验收；540B 不替它们报完成。
- Rust 顺序：shared 纯函数/几何与 parser/model 之后才是 review；不在本线提前批量翻译。

**当前 worktree 状态**：没有为 review 线创建专用 worktree。若以后确需隔离，先在派单里
写明路径、分支、owner、集成点和独有证据，再逐次申请 git worktree 操作。

# 任务书：自动网候选别名（C，2026-10-30）

> 用户实报：原理图模型 `NET34`，同一脚 PCB/编辑器网表为 `$1N436`。
> 只读调查证明 `$1N…` 是编辑器内部 id，归档原理图无派生算法，编号稀疏且会变。
> **不得**实现 `$1N{next_index}`、替换 `Net.name` 或硬编码 436。

## 1. 完成条件

1. 在 `crossView` 增加**可选** `autoNetAliases`，只读记录
   `{schematicNet, pcbNet, members, status:"candidate", evidence}`：
   - 两侧都按 `is_auto_net` 识别自动名，且 `schematicNet != pcbNet`；
   - `(designator, pin)` 成员集合去重后**完全相等**、非空；
   - 成员桶在原理图和 PCB 两侧都必须一一对应；任一侧有重复/歧义桶则整桶不出别名；
   - evidence 明确 `basis:"same-pin-members"`、`pcb:"archivePcb"`、
     `schematic:"archiveSchematic"`，说明是候选而非确认。
2. 只在 `crossView.checked=true` 时生成；无别名时不得新增空数组键。旧
   `candidateMappings` 与 `same-net-name`、live enrich、status/verdict/findings 不变。
3. 不改 `parsers/schematic.py`、`Net.name`、shared model、CLI、schema、finding 文案、
   绘制线或 `engines/draw.py`。`review-read crossView` 应能原样读到双名与成员。
4. 文档明确：这是跨视图候选别名，不是编辑器派生算法、不是确认同一网，也不会把
   所有规则消息批量改写。真实 `$1N436` 只有用户 oracle，以合成例复现。

## 2. 允许文件域

- `src/boardwise/engines/pcbreview.py`
- 新增 `tests/test_auto_net_alias.py`
- 邻域：`tests/test_189a2_schematic_nets.py`、`tests/test_537c_crossview_candidates.py`、
  `tests/test_537c_live_candidates.py`、`tests/test_537d_review_read_netlist.py`、
  `tests/test_537d_review_read_artifacts.py`、`tests/test_537d_review_read.py`、
  `tests/test_080_reconcile_names.py`、`tests/test_138_netn_collision.py`、
  `tests/test_117_net_merge_root_cause.py`、`tests/test_107_dup_net_unproven.py`、
  `tests/test_calibration.py`、`tests/test_540_shared_naming.py`、
  `tests/test_540_shared_connectivity.py`
- `contracts/differential/**` 仅官方生成器更新（如真实 golden 出现别名）
- 新增 `outputs/review/auto-net-alias.md`；探针 `.tmp_auto_net_alias/`，pytest
  `.tmp_pt_auto_net_alias`

不改其他生产文件；确需 shared/CLI/schema 改动则停止交主代理。无 git 写、无真机。

## 3. 验证

1. 合成 `NET34 ↔ $1N436` 全等脚集合得到 candidate；空集、子集、重复桶、非同员、
   显式命名网、unchecked 均不得出别名；旧 candidateMappings/live enrich 不变。
2. 跑新测试、上述邻域、`tests/test_540_cli_review.py`、`tests/test_owner_rules.py`、
   `tests/test_doc_claims.py`；必要时官方生成器，不能手改 golden/manifest。
3. 至少两处有效变异：允许子集冒充全等、允许重复桶冒充一一对应；目标测试先红，
   `cp` 备份恢复并核 SHA-256，日志 `.tmp_auto_net_alias/mutations/`。
4. 证据区分用户实报与合成验证，写清未实现编辑器派生名和未批量改消息边界。

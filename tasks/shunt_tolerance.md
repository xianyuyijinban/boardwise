# 任务书：采样电阻专用 1.5× 容差（B，2026-10-30）

> 岳已裁定：shunt 专用 1.5×，达到即进入现有矛盾/判责路径；普通电阻继续 015 的 3×。
> 用户实报 R21/R28/R32 板上 0.05Ω vs MPN 0.1Ω，旧规则 2× 被 3× 静默放过。

## 1. 完成条件

1. 新增 `MPN_AMPLITUDE_TOLERANCE_SHUNT = 1.5`。shunt 判定必须复用
   `ShuntSenseLink._is_shunt` 的既有证据（`classify_part` + 正值电阻 ≤50mΩ），
   不得只按 R 位号或另造一套值域。普通电阻 3.0、电容 25.0 不变。
2. 在 `param-value-mpn-match` 的 tolerance 选择中只对 shunt 用 1.5：
   - `ratio < 1.5` 才允许走容差内 OK；`ratio >= 1.5` 进入**现有**矛盾/UNKNOWN/
     锚定判责路径，不新增一律 WARN 的旁路，不跳过锚定要求。
   - 0.05Ω vs 0.1Ω 的 2.00x 必须可见，不得再出现 below 3x 的静默 OK。
   - 1.49x shunt 容差内、1.50x 边界、普通电阻 2.13x 仍按 3×、零值与锚定负例保持。
3. 常量注释写明岳 2026-10-30 的专用裁定与 015 普通电阻边界；不虚构新实板夹具或证据。
4. 更新 direct/recursive rulebody 账本与官方 differential，保留 #87④、200A/B/C 全部记录。

## 2. 允许文件域

- `src/boardwise/rules/params.py`（可导入既有 `ShuntSenseLink`，但不修改该文件）
- 新增 `tests/test_shunt_tolerance.py`
- 邻域：`tests/test_011d_rules.py`、`tests/test_018_cli_review.py`、
  `tests/test_025d_checkup_report.py`、`tests/test_040b_boards.py`、
  `tests/test_058_needs_datasheet.py`、`tests/test_092_rail_ratings.py`、
  `tests/test_093_arch_closure.py`、`tests/test_review_eval.py`、
  `tests/test_finding_target_schema.py`、`tests/test_annotations.py`、
  `tests/test_checkup_cli.py`、`tests/test_070_triage_key.py`、
  `tests/test_016_edit_cli.py`、`tests/test_025c_drc_mapping.py`、
  `tests/test_injected_variants.py`、`tests/test_537d_finalize_validation.py`
- `tests/test_126a_pcb_review_plumbing.py` 的账本与 direct/recursive 断言
- `contracts/differential/**` 仅官方生成器更新
- 新增 `outputs/review/shunt-tolerance.md`；探针 `.tmp_shunt_tolerance/`，pytest
  `.tmp_pt_shunt_tolerance`

不改 connectivity、sensebias、其他规则、shared、CLI、schema、fixtures、connector/DSH/Rust；
不做 git 写或真机操作。

## 3. 验证

1. 合成 R21/R28/R32 各 0.05Ω vs 0.1Ω，断言全部离开容差 OK；另测边界、普通电阻、
   电容、非 shunt 毫欧以上电阻、锚定与零值。
2. 跑新测试、上述邻域、`tests/test_540_cli_review.py`、`tests/test_owner_rules.py`、
   `tests/test_doc_claims.py`；不跑全量。
3. 至少两处变异：shunt 阈值退回 3.0、shunt 判定失效；目标测试先红，`cp` 备份恢复
   并核 SHA-256，日志 `.tmp_shunt_tolerance/mutations/`。
4. 用户实报只作 oracle，不声称独立复测真实板。证据写清 direct/recursive 新值、
   实际命令、计数与剩余夹具缺口。

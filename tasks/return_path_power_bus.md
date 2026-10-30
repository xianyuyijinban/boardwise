# 任务书：return-path 高压母线名识别（E，2026-10-30）

> 用户实报：`pcb-foc-return-path` 把 `V_310V` 当未识别网。A 已修 rail/定价，
> 本批只修 `is_power_net` 的母线名族，不动 return-path 几何或投影。

## 1. 完成条件

1. `rules/pcb/foc.py` 增加窄的 `POWER_BUS_NET_PATTERN`：仅 `V_<数字>V`
   （如 `V_310V`、`V_5V`，允许大小写与数字小数），不把 `VCC`、`V310`、`NET1`、
   任意 `V_*` 字符串或所有电压名都纳入功率网。
2. `is_power_net` 在 gate/switch/sense 之外承认该母线名族；`POWER_NET_PREFIXES`
   同步 `V_`，让 R11/R13 的词表不漂移。`pcb-foc-return-path` 对 `V_310V` 实际出
   投影测量行，不再只落未识别清单。
3. 不改 `return_path_projection`、`return_path_cover`、PLANE 语义、阈值、其他网名、
   A 的电压文法或 D 的六路栅极名。用户实板不在仓库，用合成几何验证。
4. 更新 recursive rulebody 账本与官方 differential，保留全部既有记录。

## 2. 允许文件域

- `src/boardwise/rules/pcb/foc.py`
- 新增 `tests/test_return_path_power_bus.py`
- 邻域：`tests/test_133b_foc_rules.py`、`tests/test_133c_foc_ground.py`、
  `tests/test_133d_foc_thermal.py`、`tests/test_131f_mcu_crystal_keepout.py`、
  `tests/test_126a_pcb_review_plumbing.py`、`tests/test_126b_pcb_distance_rules.py`、
  `tests/test_126c_pcb_ipc_rules.py`、`tests/test_127b_blind_review_fixes.py`、
  `tests/test_164a_foc_view_truth.py`、`tests/test_163b_gate_truth.py`、
  `tests/test_gate_net_names.py`、`tests/test_hv_supply_identity.py`
- `contracts/differential/**` 仅官方生成器更新
- 新增 `outputs/review/return-path-power-bus.md`；探针 `.tmp_return_path_bus/`，pytest
  `.tmp_pt_return_path_bus`

不改 focground 生产文件、其他规则、shared、CLI、schema、fixtures、connector/DSH/Rust；
不做 git 写或真机操作。

## 3. 验证

1. `V_310V` 正例与 `VCC/V310/NET1/V_FOO/V_` 反例；D 六路与 GH/GL 兼容；
   实际 FocReturnPath 投影行、未识别反例和既有 PLANE 行为。
2. 跑新测试、上述邻域、`tests/test_540_cli_review.py`、`tests/test_owner_rules.py`、
   `tests/test_doc_claims.py`；不跑全量。
3. 至少两处有效变异：删除母线 pattern、删除 `V_` 前缀/识别分支；目标测试先红，
   `cp` 备份恢复并核 SHA-256，日志 `.tmp_return_path_bus/mutations/`。
4. 交实际命令、计数、recursive 新值与实板证据缺口。

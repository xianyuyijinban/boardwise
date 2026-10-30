# 任务书：200C1 高速 A2 换层伴随地孔（2026-10-30）

> 依据 `tasks/200_v060_scope.md` 200C 的 A2。复用 200B 的 `high_speed_nets`，
> 一批只交付 `pcb-hs-via-ground-companion`，不夹带 A3。

## 1. 完成条件

1. 对每个 `via.net ∈ high_speed_nets(board)` 的过孔，以其中心到全部 GND 类过孔中心的
   欧氏距离寻找最近地孔；`is_ground_net` 与 200B 高速网集合每次规则运行各只算一次。
2. 最近距离 **> 50.0 mil 或没有任何 GND 过孔** → 一条 WARN；**≤ 50.0 mil（含边界）**
   → 静默。常量 `GROUND_VIA_RADIUS_MIL = 50.0`，docstring/source 写明 house rule，可调。
3. id `pcb-hs-via-ground-companion`。每个高速过孔至多一条 finding，message/evidence 给出
   信号过孔 id/net/坐标、阈值、最近地孔 id/距离（没有则明确无地孔）。非高速过孔静默。
4. 本批只判“半径内是否存在 GND 过孔”：不判该地孔是否跨接相同参考层，不引入
   `unused_inner_layers` 新语义，不做回流孔阵列、stub 或阻抗。该限制写入证据。
5. 合成正反例、注册、真实夹具读数完成；`kicad_hs` 必跑，但 0 via 只能记覆盖不足。

## 2. 允许文件域

- `src/boardwise/core/highspeed.py`（纯几何最近地孔读数）
- `src/boardwise/rules/pcb/highspeed.py`
- `src/boardwise/engines/pcbreview.py`
- 新增 `tests/test_200c1_ground_via.py`
- `tests/test_182_highspeed_scaffold.py`（仅在注册顺序确需同步时）
- 既有注册/指纹锚：`tests/test_126a_pcb_review_plumbing.py`、
  `tests/test_126b_pcb_distance_rules.py`、`tests/test_126c_pcb_ipc_rules.py`、
  `tests/test_131e_mcu_supply_reset.py`、`tests/test_131f_mcu_crystal_keepout.py`、
  `tests/test_133b_foc_rules.py`、`tests/test_133c_foc_ground.py`、
  `tests/test_133d_foc_thermal.py`
- `tests/test_200b_cross_split.py`（主代理复验补入：仅同步追加规则后的尾项位置断言）
- `contracts/differential/**` 仅由官方生成器更新。
- 新增 `outputs/200c1/evidence.md`；探针 `.tmp_200c1/`，pytest `.tmp_pt_200c1`。

不得改 `core/measure.py`、parser、shared、CLI、checkup、connector/DSH/Rust 或其他生产文件；
确需扩域时停止交回。

## 3. 禁止事项

- 不做 A3、A1 返工、阻抗、3W、stub、Tpd，不改既有 fixtures。
- 不覆盖 #87④、200A、200B 的未提交改动；共同锚文件只追加本批记录。
- 不碰真机或真实工程，不执行 commit/add/checkout/restore/push，不删除文件或发布。

## 4. 验证与交卷

1. 测试至少含 40 mil 静默、50 mil 边界静默、50.1/55 mil WARN、无地孔 WARN、
   非高速静默、多个地孔取最近、零地孔数组和注册身份。
2. 聚焦跑新测试、182、上述锚、200B、`tests/test_540_cli_review.py`、
   `tests/test_owner_rules.py`、`tests/test_doc_claims.py`；rulebody 实算重钉并保留既有账本，
   官方生成器同步 differential。
3. 只读跑 `kicad_hs`、FOC 1.0.0、ROBOT，记录高速过孔数、有/无伴随地孔数和限制；
   0 finding 不等于高速合格。
4. 至少两处有效变异（破坏 50 mil 比较与 GND/高速集合判定），目标测试先红；
   `cp` 备份恢复并核对 SHA-256，日志 `.tmp_200c1/mutations/`。
5. 交实际文件、命令、计数、真实读数、性能、变异和未解决项；不跑全量。

# 任务书：200C2 高速 A3 差分对内（2026-10-30）

> 依据 `tasks/200_v060_scope.md` 200C 的 A3。复用 182 `DiffPair` 和既有
> `track_width_stats` / `NetGeometry.via_count`，一批交付两条规则，不做其他高速项。

## 1. 完成条件

1. **读数**：每个 182 差分对记录正/负网总 track 长度、绝对长度差、逐层长度、
   未分层 track 数及各自过孔数。长度用 `track_width_stats`，不新写第二份长度算法。
2. **`pcb-hs-diffpair-skew`（WARN）**：
   - 长度差 **> 5.0 mil**（常量 `DIFFPAIR_SKEW_MIL = 5.0`，含 5.0 边界静默）；
   - 或两侧有效层 id 集合不同。
   每对至多一条 WARN，同时列出两种事实；阈值注明 house rule，可调。
3. **`pcb-hs-diffpair-via-parity`（INFO）**：两侧过孔数不等时每对至多一条 INFO；
   与 skew WARN 可以并存，因为回答的是另一个几何事实。
4. **不可测边界**：任一网没有 track，整对不产 finding；任一侧有未分层 track 时，
   长度和过孔读数仍可给，但不得判层集合不一致。无差分对静默。
5. message/evidence 给 group、正/负网、声明/启发式来源、长度差、逐层长度、过孔数；
   不做阻抗、Tpd、等长组新配置、3W、stub 或 A1/A2 返工。
6. 合成正反例、注册、真实夹具读数完成；`kicad_hs` 必跑，其差分对无铜只能记覆盖不足。

## 2. 允许文件域

- `src/boardwise/core/highspeed.py`
- `src/boardwise/rules/pcb/highspeed.py`
- `src/boardwise/engines/pcbreview.py`
- 新增 `tests/test_200c2_diffpair.py`
- 追加规则后的位置断言：`tests/test_182_highspeed_scaffold.py`、
  `tests/test_200b_cross_split.py`、`tests/test_200c1_ground_via.py`
- 注册/指纹锚：`tests/test_126a_pcb_review_plumbing.py`、
  `tests/test_126b_pcb_distance_rules.py`、`tests/test_126c_pcb_ipc_rules.py`、
  `tests/test_131e_mcu_supply_reset.py`、`tests/test_131f_mcu_crystal_keepout.py`、
  `tests/test_133b_foc_rules.py`、`tests/test_133c_foc_ground.py`、
  `tests/test_133d_foc_thermal.py`
- `contracts/differential/**` 仅由官方生成器更新。
- 新增 `outputs/200c2/evidence.md`；探针 `.tmp_200c2/`，pytest `.tmp_pt_200c2`。

不得改 `core/measure.py`、parser、shared、CLI、checkup、connector/DSH/Rust 或其他生产文件；
确需扩域时停止交回。

## 3. 禁止事项

- 不改既有 fixtures，不覆盖 #87④、200A、200B、200C1 未提交改动；共同锚只追加。
- 不碰真机或真实工程，不执行 commit/add/checkout/restore/push，不删除文件或发布。

## 4. 验证与交卷

1. 测试至少含：等长同层同孔静默；5.0 边界静默；5.1/6 mil WARN；不同层段 WARN；
   过孔 2:1 INFO；三类事实可组合；缺一侧 track 整对静默；未分层 track 不伪造层差异；
   声明/启发式来源保留及注册顺序。
2. 聚焦跑新测试、182、200B、200C1、上述锚、`tests/test_540_cli_review.py`、
   `tests/test_owner_rules.py`、`tests/test_doc_claims.py`；rulebody 实算重钉并保留账本，
   官方生成器同步 differential。
3. 只读跑 `kicad_hs`、FOC 1.0.0、ROBOT，逐对记录长度差、层集合、过孔数与 finding；
   无铜/无差分对不写成合格。
4. 至少两处有效变异（破坏 5 mil 比较、破坏层/过孔比较），目标测试先红；
   `cp` 备份恢复并核对 SHA-256，日志 `.tmp_200c2/mutations/`。
5. 交实际文件、命令、计数、真实读数、性能、变异和未解决项；不跑全量。

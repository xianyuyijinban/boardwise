# 任务书：200B 高速 A1 跨分割（2026-10-30）

> 依据 `tasks/200_v060_scope.md` 与 `outputs/highspeed_rules_survey/README.md` A 档 1。
> 一批只交付 `pcb-hs-cross-split`，不夹带 A2/A3 或阻抗/3W/stub。

## 1. 完成条件

1. **高速网集合**：182 `identify_diff_pairs` 的成员，加网名/netclass 前缀启发式
   （CLK/SCK/USB/ETH/RGMII/PCIE/DDR/DQS/MIPI/HDMI/LVDS）。每次规则运行只计算一次集合；
   非高速网静默，不新增用户配置面。
2. **逐段测量**：对高速 track 用 `reference_layer_for` 取物理相邻参考层，沿段中线求
   ground-class 有效铺铜的连续覆盖区间：
   - 任意一段无有效铜覆盖，且全程至少有一段有覆盖 → `gap`，一条 WARN；
   - 相邻覆盖区间没有共同 pour 对象（发生 pour/net 切换）→ `boundary`，一条 WARN；
   - 同一 pour 或重叠区间有共同对象 → 不误报。一个 track 至多一条 finding，列出全部断点。
3. **有效铜与不可测边界**：
   - 参考层为 `PLANE` 时无分割几何，静默；证据文档必须写明“未测，不是平面完整”。
   - 无参考层、无 ground pour、整段无任何覆盖、零长度段均静默，不伪造 gap。
   - `POURED` 用 `rings or [points]`，外环减 void；被 POURED 取代的旧 POUR 不重复计算。
   - pour 切换以 `board.pours` 的对象序号区分，record id 只作证据，不当作岛级唯一身份。
4. **几何口径**：使用段与每个 ring 边的参数交点形成精确区间，不用固定步长采样，
   不复用四角 `return_path_projection` 作为跨缝结论。区间中点用外环减 void 判定。
5. **finding**：id `pcb-hs-cross-split`，severity WARN；message/evidence 给 track id、net、
   信号层/参考层、gap/boundary 类别及坐标；阈值/判据注明 house rule（200B，可迭代）。
   target 保留网名，不改其他 finding、verdict 或 exit code。
6. **注册与证据**：加入 `BUILTIN_PCB_RULES`，合成正/反例和真实夹具读数表；
   `kicad_hs` 必跑，但其无 zone/via 的局限只能记为覆盖不足，不能冒充正例。

## 2. 允许文件域

- `src/boardwise/core/highspeed.py`
- `src/boardwise/rules/pcb/highspeed.py`
- `src/boardwise/engines/pcbreview.py`
- 新增 `tests/test_200b_cross_split.py`
- `tests/test_182_highspeed_scaffold.py`
- 规则注册/指纹锚：`tests/test_126a_pcb_review_plumbing.py`、
  `tests/test_126c_pcb_ipc_rules.py`、`tests/test_131f_mcu_crystal_keepout.py`、
  `tests/test_133b_mcu_reset.py`、`tests/test_133c_mcu_crystal.py`
- 主代理复验补入的同类注册锚：`tests/test_126b_pcb_distance_rules.py`、
  `tests/test_131e_mcu_supply_reset.py`、`tests/test_133d_foc_thermal.py`
- `contracts/differential/**` 只能由官方生成器 `.venv/Scripts/python.exe -m
  tools.build_differential_fixtures` 更新，不手改 golden/manifest。
- 新增 `outputs/200b/evidence.md`；探针 `.tmp_200b/`，pytest `.tmp_pt_200b`。

若确需改 `core/measure.py`、parser、shared、CLI、checkup 报告层或其他生产文件，停止交回主代理。

## 3. 禁止事项

- 不做 A2/A3、阻抗、3W、stub、Tpd、netclass 新解析或新 CLI。
- 不改既有 `tests/fixtures/**`，不碰 #87④ 的 measure/ipc/schema/测试业务改动；
  对共同锚文件只能追加本批记录，禁止恢复或整理既有变更。
- 不改 200A 的 `checkup.py`，不改 connector/DSH/Rust，不碰真机或真实工程。
- 不执行 commit/add/checkout/restore/push，不删除文件，不发布或评论 issue。

## 4. 验证与交卷

1. 先写行为反例：连续单 pour 无 finding；跨无铜缝、跨直接相接的两个 pour、rings void
   各有 WARN；非高速、PLANE、无 pour、零覆盖均静默；重叠而有共同 pour 不误报。
2. 聚焦跑新测试、182、上述注册/指纹锚、`tests/test_540_cli_review.py`、
   `tests/test_owner_rules.py`、`tests/test_doc_claims.py`；rulebody 用实际算法重钉，
   保留 #87④ 既有账本，官方生成器同步 differential。
3. 真实只读跑 `kicad_hs`、毕设 FOC 1.0.0 与 llc，记录高速网数、可测 track 数、
   gap/boundary 数和覆盖限制；不把 0 finding 写成板子高速合格。
4. 至少两处有效变异（破坏 gap 检测、破坏高速网/边界判定的各一），目标测试先红；
   每次 `cp` 备份、恢复并核对 SHA-256。日志放 `.tmp_200b/mutations/`。
5. 交卷报告实际文件、命令、计数、真实读数、变异哈希、性能和未解决项；不跑全量，
   主代理独立复验后才关闭本批。

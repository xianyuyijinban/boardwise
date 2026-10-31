# 任务书：#89B FBPlacement 同网跨层距离（2026-10-30）

> 前置：`d2130b7` 已提交；#89A 的 `regulator.py` / 新测试 / 合同改动仍在工作树，
> 已完成主代理集成验收但未提交。不得覆盖或整理这些改动。本批只处理 issue #89 的
> `pcb-regulator-fb-placement` 垂直切片，不关 issue。

## 1. 完成条件

1. **输出电容距离**：`RegulatorFbPlacement._nearest_output_cap` 对每个 `output_net`，
   复用 #89A 的 `regulator.same_net_loop_distance(board, divider.upper, candidate, output_net)`，
   量上分压电阻到电容在该输出网的焊盘边到边平面投影。storage 优先、池内最近、pool 判定不变。
2. **FB 节点电容距离**：`_one_divider` 对 `sense_caps` 复用同一 helper，参数为
   `(board, divider.ic, candidate, divider.tap_net)`；只量 FB 网，不拿地脚或其他网冒充。
3. **分压电阻腿保持原口径**：IC→upper/lower 仍用 `component_distance`，既非去耦环路，
   不得改共享函数；`FindingTarget.measurement` 仍锚 upper leg，severity/verdict/exit code 不扩改。
4. 同网跨层 SMD 对必须可测；在板但目标网无焊盘为不可测，不是 0，也不是未放置。
   `out_cap_text` / `sense_text` 和 evidence 必须区分：无候选、候选未放置、在板但无可测
   同网焊盘对；不得再把后两种合并成“no capacitor … is placed”。
5. 有可测值时保留消息主体、actual pad_a/pad_b、最近选择、INFO 与 evidence。真实夹具
   读数变化必须从实际离线规则/checkup 读取，不得手编数字。

## 2. 允许文件域

- `src/boardwise/rules/pcb/fbplacement.py`
- 新增 `tests/test_89b_fb_same_net_distance.py`
- `tests/test_131c_regulator_fb_placement.py` 按真实新读数/消息重钉
- `tests/test_126a_pcb_review_plumbing.py` 仅 direct/recursive rulebody 账本
- `contracts/differential/**` 仅官方生成器更新
- 新增 `outputs/review/issue-89b-fbplacement.md`；探针 `.tmp_issue89b/`，pytest
  `.tmp_pt_issue89b`

**禁止**：改 `regulator.py`、`core/measure.py`、`distance.py`、其他规则、parser/model、
CLI/schema/connector/DSH/Rust/绘制线、既有 fixtures；不覆盖 #89A 文件；不做 git 写、
真机或真实工程操作，不关/评 issue。

## 3. 必须覆盖的测试

1. 输出电容只有同网且跨层焊盘对：旧 `component_distance` 为 None，新规则从 **upper leg**
   量出正确边到边距离与焊盘身份；异网更近焊盘不得冒名。
2. FB 节点电容同样从 **IC 的 FB 网焊盘**量；跨层可测，地脚/其他网不进入最小值。
3. 多个输出候选的池内最近与 storage 优先不变；上分压/下分压腿读数和 target measurement 不变。
4. 无候选、未放置、在板但无目标网焊盘三条路径分别断言，消息不得互相冒充。
5. 真实 FOC 夹具的 U11 行按实际结果重钉，并保留 R14/R21 既有异网腿距离锚。
6. #89A 新测试保持全绿，不能通过修改它来迁就本批。

## 4. 验证与交卷

1. 跑新测试、`tests/test_89a_regulator_same_net_distance.py`、
   `tests/test_131b_regulator_cap_distance.py`、`tests/test_131c_regulator_fb_placement.py`、
   `tests/test_126a_pcb_review_plumbing.py`、`tests/test_126b_pcb_distance_rules.py`、
   `tests/test_540_cli_review.py`、`tests/test_owner_rules.py`、`tests/test_doc_claims.py`、
   `tests/test_540c_differential.py`；独立 basetemp，不跑全量。
2. rulebody 变化只用官方 `tools.build_differential_fixtures`，禁止手改 golden/manifest。
3. 至少两处独立有效变异：输出电容恢复旧口径/去掉 net 筛选；FB 电容恢复旧口径或跨层
   拒绝。每次 `cp` 备份、目标测试变红、`cp` 恢复并核 SHA-256；禁止 git 恢复。
4. 交实际文件、命令与计数、代表性新旧距离和消息、direct/recursive 指纹、变异恢复哈希、
   未覆盖项。真实板数据只作离线公开夹具或用户 oracle，不声称真机复测。
5. 最多 40 步或 30 分钟；需扩大文件域、连续失败无新信息或证据不一致时停止交回。

# 任务书：#89A Regulator 去耦同网跨层距离（2026-10-30）

> 前置：整组审查候选已提交 `d2130b7`。本批只处理 issue #89 的
> `pcb-regulator-cap-distance` 垂直切片，不关 issue、不改 `FBPlacement`。

## 1. 根因与完成条件

`RegulatorCapDistance._one_pool` 用 `component_distance` 量去耦环路；该共享函数故意拒绝
同网焊盘对和无共同铜层焊盘对，全部拒绝后返回 `None`。调用方又把 `None` 写成
“candidates exist but none is placed”，与 `board.component(...)` 已证明器件在板上的事实冲突。

本批完成条件：

1. `RegulatorCapDistance` 对当前 `(regulator, candidate, net)` 改用与 `DecapDistance`
   相同的**同网焊盘边到边平面投影**口径：只取双方 `pad.net == net` 的焊盘，复用
   `core.measure.pad_edge_distance`，取最小值并保留实际 `pad_a` / `pad_b`。
2. 同网且跨层的 SMD 焊盘对必须可测；这里测的是去耦环路平面投影，不得重新引入
   `component_distance` 的同网/跨层拒绝，也不得伪造 0 mil。
3. 候选在板上但没有该网焊盘对时，保持不可测；消息必须明确“在板上但无可测同网焊盘对”，
   **不得**再说 `none is placed`。真正不在该 PCB 文档的候选仍按旧路径排除。
4. 有可测候选时，保留既有 INFO、最近颗选择、measurement、FindingTarget、文案主体与
   evidence；新读数必须能与 `DecapDistance` 的同网环路距离一致。无候选/未放置/不可测
   三种情况不得互相冒充，severity/verdict/exit code 语义不扩改。
5. `component_distance` 保留给其他异网器件间距规则；本批不改 shared 几何/API。

## 2. 允许文件域

- `src/boardwise/rules/pcb/regulator.py`
- 新增 `tests/test_89a_regulator_same_net_distance.py`
- 邻域测试按需更新：`tests/test_131b_regulator_cap_distance.py`、
  `tests/test_131c_regulator_fb_placement.py`、`tests/test_164b_supply_view_truth.py`、
  `tests/test_164c_silent_truth.py`
- `tests/test_126a_pcb_review_plumbing.py` 仅 direct/recursive rulebody 账本
- `contracts/differential/**` 仅官方生成器更新
- 新增 `outputs/review/issue-89a-regulator.md`；探针 `.tmp_issue89a/`，pytest
  `.tmp_pt_issue89a`

**禁止**：改 `core/measure.py`、`distance.py`、`fbplacement.py`、其他规则、parser/model、
CLI/schema/connector/DSH/Rust/绘制线、既有 fixtures；不做任何 git 写、真机或真实工程操作，
不关/评 issue，不索取真实板文件。

## 3. 必须覆盖的测试

1. 用 issue #89 的最小几何：U1 顶层、C7 底层，双方只有 `+12V`/GND 同网焊盘；
   旧 `component_distance` 为 None，新规则必须给出 `+12V` 焊盘边到边距离，且不含
   `none is placed`。
2. 同层同网、跨层同网、多个同网焊盘取最近、最近候选选择；边到边值用几何精确断言。
3. 在板但无该网焊盘、真正未放置、无候选三种路径分别断言；不可测不得写成 0 或未放置。
4. 同一上下文的 `DecapDistance` 与 `RegulatorCapDistance` 同网环路距离一致；若构造完整
   DecapDistance 上下文需要扩文件域，停止并交主代理，不复制第二套测量算法。
5. 既有非去耦 `component_distance` 行为不变，本批不修改它的测试来迁就新行为。

## 4. 验证与交卷

1. 开发期跑新测试及以上邻域、`tests/test_126a_pcb_review_plumbing.py`、
   `tests/test_126b_pcb_distance_rules.py`、`tests/test_540_cli_review.py`、
   `tests/test_owner_rules.py`、`tests/test_doc_claims.py`；pytest 必须独立 basetemp。
   不跑全量，主代理负责最终集成。
2. rulebody 变化用官方 `tools.build_differential_fixtures`，不得手改 golden/manifest。
3. 至少两处独立有效变异：恢复旧 `component_distance` 口径；去掉同网焊盘筛选或重新拒绝
   跨层对。每次必须 `cp` 备份、目标测试变红、`cp` 恢复并核 SHA-256；禁止 git 恢复。
4. 交卷列出实际文件、命令与计数、代表性新消息/距离、direct/recursive 指纹、变异与恢复
   哈希、未覆盖项。真实板三对读数仅作用户 oracle，不声称独立复测。
5. 最多 40 步或 30 分钟；范围不够、连续失败无新信息或需要扩大文件域时停止并交回。

# 115 — 反激整页出图：支路×owner 序关系 + pin token 同尺

**来源**：114 收尾定位（`outputs/114/SUMMARY.md` 申报节 + agent-182 的
机制报告）。113 的语法、114 的传递归属与孤岛 lane 都已就位；反激整页
仍 0 candidates，剩最后两件事 + 一件③。

## 三件事（机制都已定位，照做）

### ① 支路×owner 序关系的摆放消费

- **病**：`_branch_basis` 对挂在「支路×owner」上的序关系一律不给 basis，
  方向退到 pin 指向（读 U5.4/D2.2 那根脚自己的指向）。
- **实证**（spacing=1 pose=0，栅格 5 公差 2.5）：
  `right-of(C10,U5)`/`below(C10,U5)` 两轴恰好相等被拒；
  `near(C10,U5)` hypot=520 > 300；`below(C7,D2)` 实测 C7 反在上 60。
- **治**：让 `_branch_offset_direction` 在这类关系上读序关系给的方向。
- **硬约束（114 的回撤教训，必须写进测试）**：114 做过一版能让验收达成，
  但零移动闸报 098 scene 08 变了一个字节（`cd23f7d0…`→`fcd6ac6c…`）而
  撤回——该 basis 对五语法全生效。**本棒必须先查清 098 scene 08 为什么会变**
  （哪条既有关系被新 basis 接了），再把触发条件收紧到「默认 pin 方向
  **会违反**该序关系时才用序关系方向」这类保守判据——既有五语法的输出
  一个字节都不许变。

### ② pin token 同尺（位号 vs 名字）

- **病**（已验证到单行）：`readability._derive`（`readability.py:537`）按
  `f"{part_id}.{number}"`（profile 位号）建 `pin_points` 键；规范侧网成员
  用作者写的 token（`D1.A`/`D1.K`，同一符号的 `D2.1`/`D2.2` 又是位号）——
  键对不上 → 6 条闸报（`required-pin-not-connected`「符号没有 A/K 这根脚」
  + `netlist-partition-mismatch` 里 `D1.1`/`D1.2` 成 unmentioned）。
- **治**：派生网表/必连检查按**规范侧 token** 取点——与
  `drawcompiler._pin_of_token` 同一把尺（先位号后名字）；或让
  `_PlacedPart.pins` 同时以位号与名字双键。选一把，注释写明为什么；
  不许出现两把不一致的尺。

### ③ ② 修好后独立暴露的两条 text-overlap

`R10` 值（`2k 1% 0603`）压 `VFB_NF` 旗标名、`T1` 值压 `PGND` 旗标名——
旗标/文字摆位。能顺手治就治（保守），治不了就实测记录并归 116，
**不许为治它引入新的排版风险**。

## 验收（硬数字）

1. `blocklib/specs/flyback_uc3845.*` 整页编译 `ok=True`、candidates ≥1、
   关系/义务/可读性闸全零 findings；候选预览 SVG 落 `outputs/115/`。
2. 113 的 skip 测试更新：编译出图那一半**转绿为真断言**（plan 存在、
   闸通过）；live 快照那一半保留 skip（理由文本更新——真机落图归岳）。
3. 既有五语法输出逐字节不变（83 预览 + 15 板 sha256 全同）——**含 098
   scene 08 的回归钉**：把「新 basis 不得改变它的输出」写成一条测试。
4. 合成单测：支路×owner 序关系被消费（C10/C7 形态）；pin token 双写
   （A/K 与 1/2 混用）同尺通过。

## 纪律（同款）

红测先行；变异 ≥2（cp+sha256 还原）；全量 pytest
`--basetemp=.tmp_pt_home`（基线 **3619 passed + 1 skipped**，跑期间零改动）；
`PROGRESS.md` 单行（`grep -c "^- 115 "`=1）；证据落 `outputs/115/`
（SUMMARY 含如实申报节）；禁 git/真机/daemon；删除走回收站；
grammar/*.py 绑定判断一字不改（spec JSON 的 pin token 写法可以改——
若选「spec 统一用位号」当②的解，要先证明 `D1` 库符号位号声明在场，
并把「作者侧约定」写进 spec 注释；但优先做同尺，不许只会改输入）。

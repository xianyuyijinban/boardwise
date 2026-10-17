# 任务书：201A — 地/电源符号策略重写（一地一符号，朝向由摆放决定）

- 批号：**201A**　日期：2026-10-17　来源：岳的三条吐槽（GND 标识重复该合并、GND/电阻无意义翻转 180°、线绕弯）+ 121c 实测：反激页编译失败的**第一死因是地旗**（`outputs/121/live/121c_FINDINGS.md`：SEC_GND/PGND 每脚一旗的引线穿 SRC 轨 → layout-unsat；把 PWR-GND 从库里拿掉立刻编过，只剩 2 旗）。
- 现状（侦察 200a 证据）：`_Expression.style=="flag"` 的网**每只脚各挂一颗同名旗**（`drawcompiler.py:4520` 原文 "every member gets the same flag"）；`_detached_pins:4703` 对散热脚重复脚又各出 stub 各挂旗；`_flag_rotation:5302` 只允许 0/180，角度查 `FLAG_GLYPH_ROTATION_OFFSETS` 表按族补——**是查表，不是布局决策**。旗标逻辑散在 7+ 个函数。

## 目标策略

1. **一个地网域在一个可读位置放一个符号**，不是每脚一颗：同页同域的 GND 类网，旗数 = 域数（域 = 173/C 的 `_ground_domains`，PGND/AGND/DGND 仍分开，绝不并地——这条红线不动）。
   - 脚的连通性不靠旗表达：每只脚照常接短线入网表；旗是「这条网在这里接参考地」的**标注**，挂在该网的一根线上。
2. **旗的朝向由摆放位置决定**（在器件下方就朝下、上方就朝上），删掉按族查表 180° 的路径；`FLAG_GLYPH_ROTATION_OFFSETS` 退役或降级为「符号自身字形补偿」常量（每个族一次，不再按页调整）。
3. **旗引线不穿别网导体**：引线预留（`_lead_lane_reservations`）保留，但旗少了，预留需求随之大减；仍有冲突时降级为「就近挪旗位」，不许穿线。
4. 多模块页（pagecompiler）同规则：旗位在模块内解决。

## 验收锚（全部要过）

- 合成页（tests/fixtures/drawapply/divider 三件套 + 新造一个「一颗运放 + 两个 GND 脚 + 一个散热脚」的最小 spec）：GND 旗数从 N 变 1，连通性不变（netlist 逐脚对拍）。
- **反激三件套** `blocklib/specs/flyback_uc3845.*`：`draw compile` 从「0 candidates」变成至少 1 个 `ok=True` 候选（若还有别的死因，如实报下一死因，不许为此放宽 readability 硬闸）。
- 全部既有夹具的零移动闸（`tools/053b_previews.py`、`056/088/098/112/114/116/117` 系列）：**预期会动**——逐张出前后 SVG 对比，把「旗更少/朝向更正」的改善证据贴进 evidence，再按流程重钉。
- `draw lint` 的 P1 基线（48E/20W/21I）不许变差。
- 岳 060 裁过的两条不动：「电容按归属脚分侧」「重复脚默认接上」。

## 纪律

- 只动 `engines/drawcompiler.py` 旗标相关函数 + 新测试 `tests/test_201a_flags.py`；**不碰** `_place`/`_variants`/router（201B 在做布局）。
- 零移动闸重钉时附前后 SVG 对比证据；全量绿 `--basetemp=.tmp_pt_201a -n 4 --dist loadfile`。
- 企业项目名零出现；不动 git；不 rm（回收站）；不碰真机。
- 证据 `outputs/201a/evidence.md`（含反激 compile 前后的失败类目、旗数对比表、SVG 对比）；PROGRESS.md append 一行；**不要 commit**。

# 120 — 第二孤岛落子质量 + WE 料收口（反激整页出图的最后一段）

**来源**：岳选了 WE 749118105 放在 P1（两绕组真品料）。主代理已完成
（工作树未提交，**不许返工**）：

- `circuit.json`：T1 → C17189451（datasheet 实测 pinout：N1=1-3 原边
  HVDC→1 / SW→3，N2=4-6 副边 SEC_SW→4 / SEC_GND→6，pin 2/5 = NC）；
  辅助链拆除（D2/C7/AUX/VCC 全出 spec——语法设计上 aux 是可选角色）。
- `library.json`：T1 profile 换 WE 六脚实测（原点 (320,510) 量：
  1:(-40,-10)L 2:(-40,-20)L 3:(-40,+30)L 4:(+40,+30)R 5:(+40,-20)R
  6:(+40,-10)R，len 20；body = 实测 bbox [-20.5,-13.5,20.5,30.5]；
  证据 `outputs/118/probe/xfmr_swap_probe.json` 的续页自己写一条）。
- `presentation.json`：flyback_core 19 件（D2/C7 已除名）。
- 语法**绑定通过**（绕组判读/双地/光耦全认）——病的不是语法。

**实测现状**（`tools/119_pose_ladder_widening_evidence.py` 在这棵树上
跑出来，尾部 KeyError 是它硬编码旧料名查体框，属台子遗留可顺手修）：

- 基阶梯 6 档全拒 `same-column(Q1,R5)`；加宽 18 档**无一再拒它**；
- 加宽后改拒：`near(C13,T1)` / `near(R15,T1)` / `right-of(C10,U5)`；
- 关系闸让开后：5/6 档死于 `layout-unsat SEC_12V` / `layout-unsat gate`。

## 本棒任务（先量后治，不许先调参）

1. **孤岛落子根因**：量清 C13/R15/D3 实际落在哪、哪一步把它们放到离
   T1 三百多单位的地方（114 的 `_branch_lane_groups` / levelling 链路，
   drawcompiler.py:2976-3010 与 1568 附近）。**near 的 300 单位上限是
   岳的画法含义（钳位贴着变压器读），不许动它**——治落子，不治尺子。
2. **走廊死因**：SEC_12V/gate 的 layout-unsat 是走廊边界
   （SEARCH_MARGIN=160）不够还是孤岛封路——量出来再治，边界放宽要有
   实测出处注释。
3. `right-of(C10,U5)` 在新几何下要么被 116 松弛覆盖要么写清为什么不。
4. **测试随 WE 料改写**：119 钉七脚 XREE 的断言按六脚 WE 现实重写
   （七脚证据作为 119 的记录留在 outputs/119/）；118 的五脚发现继续是
   历史记录。改的是主张，不是掩盖。

## 验收（这次必须出图）

1. `draw compile` 三件套 **ok=True、candidates ≥1、readability 闸零硬违反**；
   预览 SVG + PNG 落 `outputs/120/`（**PNG 主代理要亲看**——用工具把 SVG
   渲出来，仓库里有 svgpreview/渲染先例）。
2. 113 skip 测试：编译半边真断言保住；live 半边 skip 保留。
3. 零移动：83 预览 + 15 板 sha256 全同 + 098 scene 08 钉。
4. 合成单测：孤岛落子根因形态 + 走廊形态各至少一条。

## 纪律（同款）

红测先行；变异 ≥2；全量两轮 `--basetemp=.tmp_pt_home`（基线
**3682 passed + 7 skipped**，≤12 分钟）；`PROGRESS.md` 不动（主代理统一）；
禁 git 写操作；真机只读（test 工程，窗口 inst-122525753-7bjcs91m）；
删除走回收站；grammar/*.py 与 library.json 的 T1 实测几何一字不改；
做不完留全绿中间态 + SUMMARY 精确断点。

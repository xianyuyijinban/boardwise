# 119 — 位姿阶梯加宽 + 七脚变压器收口

**来源**：岳 2026-10-04 深夜裁定换料（选项 1）。主代理已完成的部分**不许返工**：

- T1 换 `C49118510`（XREE16-050624 卧式 5+5，实测符号 7 脚：左侧 1-5、
  右侧 6/10，体框 bbox 实测；证据 `outputs/118/probe/xfmr_swap_probe.json`；
  同门 C49118511 立式 4+4 实测只有 3 脚含 NC，已否）。
- `library.json`：T1 profile 换成 7 脚实测（symbolRef `XFMR-XREE16-050624`）。
- `circuit.json`：T1 lcsc/symbolRef/value 换新；脚位映射 `SEC_GND T1.4→T1.10`、
  `PGND += T1.2`（辅助绕组冷端第一次有了真脚，归原边地——物理正确）。
- library schema 课：profile 里的 `bodySource` 键 CLI 校验不收、
  `notes` 必须是字符串数组——已手工折叠。**顺手把
  `tools/118_measure_profiles.py` 改成吐合法键**（bodySource → notes 数组成员），
  让再生成不踩同一坑。

**当前红绿状态**：compile 只剩 `same-column(Q1,R5)` 一条拒全六档；
`tests/test_118_measured_profiles.py` 等 **7 条测试红**（它们钉的是五脚
变压器现实，换料后按新现实改写——五脚缺陷作为 118 的**发现**留在
SUMMARY/证据里，测试主张改写，历史不抹）。

## 任务 A：位姿阶梯加宽（编译器）

病：`_variants` 只探索 `pose_index 0/1`（drawcompiler.py:4874 附近
`range(min(choices, 2))`）。same-column(Q1,R5) 六档全拒，而 118 实测
**R5 转 90° 能救**——那个位姿不在阶梯里。

治：**只有当所有变体都因同一条（组）关系被拒时**，把涉事件的其它接受位姿
加入阶梯重试一轮。边界写死（每件最多补到 accepted poses 全试完为止），
解不出照旧诚实拒绝。**结构性零移动**：该路径只在 candidates=0 时才会
点火——凡是现在能编译的东西它永远不动；仍要跑 A/B（五族 83 预览 + 15 板）
用证据钉死这个论证。

## 任务 B：测试改写（换料后的新现实）

- 7 条红逐条过：主张换成七脚现实（T1 七脚 1-5/6/10、AUX 有真脚对、
  PGND 含 T1.2）；「五脚装不下三绕组」改写成**118 的发现记录**
  （引 outputs/118/SUMMARY.md 与穷举证据），不再是当前现实断言。
- 113/117 的编译断言回到「ok=True + 闸零硬违反」真断言。

## 验收

1. `draw compile` 反激三件套：**ok=True、candidates ≥1、闸零硬违反**，
   预览 SVG+PNG 落 `outputs/119/`（PNG 我要亲看）。
2. 113 skip 测试的编译半边维持真断言；live 半边保留 skip。
3. 五族 83 预览 + 15 板 sha256 全同 + 098 scene 08 钉。
4. 合成单测：阶梯加宽救回 same-column 形态 + 全拒仍诚实拒绝形态。

## 纪律（同款）

红测先行；变异 ≥2；全量两轮 `--basetemp=.tmp_pt_home`（基线 3679+1skip，
≤12 分钟）；`PROGRESS.md` 不动（主代理统一）；禁 git/真机写操作
（真机只读探针可以，窗口 inst-122525753-7bjcs91m，只碰 test 工程）；
删除走回收站；grammar/*.py 一字不改；做不完留全绿中间态 + 精确断点。

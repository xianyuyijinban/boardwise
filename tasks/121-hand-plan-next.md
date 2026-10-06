# 121b / 反激规划落图（路径 2）· 接续任务书

> 状态：**已暂停在 121a 之后**（commit `52bf896`）。岳 2026-10-06：PCB 审查优先级可能更高，
> 本棒随时可续。这一张写清「已经量到什么、下一步做什么」，接手者不需要重挖。

## 已定方向（岳裁）

走**规划落图路径**：编译器位姿搜索出不来全绿的图（120 如实入账），改用 **userLocks 手编位姿**
（052 sec.4 的合法缝，`PresentationSpec.user_locks`，编译器**原样遵守、绝不吸附、绝不挪动**，
与语法冲突时点名报告），编译器补全布线/文字/旗标，`draw apply` 落 P1，`draw lint` + 渲染验收。

## 已经量到的（121a 之后的地貌）

- `tools/121_hand_plan_dump.py`：逐档转储可建 plan（关系闸让开、可读性闸**真实**）+
  每档真实关系违例 + SVG + `drawapply.module_plan` 的完整 ChangePlan JSON。产物在
  `outputs/121/buildable/`（outputs 不入库，本地证据）。
- 订正后的 spec（121a）下 **1/6 档可建**：`spacing=2.2 pose-variant=0`，布线全通、
  可读性闸**零硬违反**。
- 该档**最终 plan 实测**：same-column(Q1,R5) 成立（松弛趟已把两颗对齐 x=0）、
  right-of(C10,U5) 成立（C10 x=150 > U5 x=0）——**唯一违例是 near(C13,T1)**：
  T1=(0,-150)、C13=(110,-450)，hypot=319.6 > 300（超 19.6，不到一格的七倍）。
  **注意**：dump 工具印的违例表是在 `_place` 的**松弛前**落点上量的（已知缺陷），
  以上「唯一违例」是从 plan 的**最终** parts 坐标算的——接手时先把工具的测量面
  改成最终 plan（`_relation_violations(circuit, binding, origin_of=..., pin_of=...)`
  可直接对 plan.parts 量），别信 stdout 那张表。
- 该 plan 的旗标情况：`powerSymbols=[]`，全是标签（PGND×5/SEC_GND×5/CLAMP×3/GATE/
  VFB_NF）。岳的画法偏好是**电源轨用竖直旗标**、有旗不反复标——要不要在
  presentation 层强制旗标，**岳定**（grammar 的 uniform-gnd 目前接受全标签）。

## 下一步（续工时从这里走）

1. 修 dump 工具的测量面（关系按最终 plan 量）。
2. 以 `spacing=2.2 pose=0` 的 plan 为骨架写 userLocks：全部 19 件按它的落点钉，
   **C13 单独改钉**到 T1 副边侧近旁（hypot ≤ 300 内，与 C11 并排），
   跑**不让人任何闸**的 `dc.compile`——目标 `ok=True`。
3. `draw plan` → `draw apply --instance inst-122525753-7bjcs91m`（P1 现为空页，
   只剩图幅；WE 探针件已删）——引脚回读守卫应过（WE 几何是实测的）。
4. `draw lint --page P1 --instance …` + `export.render` 出 PNG，与 110 手绘版
   （基线 48E/20W/21I，快照 `outputs/111/geo_P1_live.json` + `render_P1.svg`）对比，
   向岳出报告。
5. R3/R15 缺料号：岳裁过 **C23242**（`--lcsc R3=C23242 --lcsc R15=C23242`）。

## 记录在案未治（别重复挖）

- **潜伏崩溃**：spec 给某件 0 个接受位姿时，`_place`（drawcompiler.py:2360）抛
  `IndexError` 而不是拒绝文案（`_accepted_poses` 已备好 GrammarFailure，没人接住）。
- **116 baseline 过滤器**：第一档成立的关系之后每档都被滤掉（120 SUMMARY §8.3
  精确断点；两种豁免写法都动字节闸且对目标无用，未落地）。
- **right-of(C10,U5) vs same-column(Q1,R5) 结构性互斥**只在**无锁**位姿搜索里成立
  （一根 pose_index 指针装不下两颗件的两档）；userLocks 路径下不存在这个问题——
  锁是两颗各自钉的。
- 布线层死因（120 收口）：关系闸让开后 12/24 档可建，剩 12 档全死
  HVDC/SEC_12V/SW 直连义务——`SEARCH_MARGIN=160` 实测不是瓶颈，是走法问题。
  若路径 2 走通，这一堆大概率不再值得治（先问岳）。

## 现场

- daemon：`bash-uuee3txr` 常驻 61190；窗口 `inst-122525753-7bjcs91m`（project test）。
- P1 空页（只有图幅 b5ba3517c5abec68）；P22/P23/P24 是零误报验收页，**禁碰**。
- WE 749118105 实测：脚 1:(-40,-10)L / 2:(-40,-20)L=NC / 3:(-40,+30)L=SW(点端) /
  4:(+40,+30)R=SEC_SW(点端) / 5 NC / 6:(+40,-10)R=SEC_GND；体框 (-20.5,-13.5,20.5,30.5)；
  原始探针记录 `outputs/118/probe/we_749118105_probe.json`。
- 基线：全量 **3693 passed + 3 skipped**（~554s）；四线全绿。

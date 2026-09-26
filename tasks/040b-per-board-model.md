# 040b：一板一模型（per-board model + findings 板归属）

040 把页拆开了（F1/F2/F3），但模型层仍是"一位号一组件"：`components['U2']` 静默只留
最后一个 placement（毕设板里实际是 5f0f 页那颗，40daf 页那颗 2×6 排针只剩引脚进网）。
本批把模型层改成**一板一模型**，findings 带上板归属。A1 判案不变（跨板重号仍是 ERROR，
理由岳已签：BOM/网表/布局都是工程作用域）——本批改的是**判案用的模型**，不是判案。

## 板身份结构事实（主代理 2026-09-26 已核，不许重查）

板归属链：`SCH_PAGE.META.schematic` → `SCH.META.board` → `BOARD.META.title`。

- 六个真实夹具 100% 命中：毕设板（3 BOARD / 3 SCH / 4 SCH_PAGE / 3 PCB）、
  高速电机控制器（2/2/3/2，板名自定义）、ROBOT、智能药箱、CH340G、llc、golden（均 1 板）。
- 毕设板 Board1 有**两页**（5f0f 的 P1 + b0342 的 P2）——一板可以多页，页≠板。
- PCB 文档也带 `META.board`（PCB1→Board1…），与原理图侧链一致。
- **注入件例外**：`reviewsets/injected/duplicate-designator.epro2` 的 P2 **没有 SCH 注册**
  （`schematic` 引用悬空——注入时是追加页不是建档）。其余注入件全部单板单页。
- eprj3 文件夹格式（038 A 档）有没有 BOARD 等价物 = 工作项 0 要查的事。

## 工作项 0（先查后修）：eprj3 与孤儿页

1. 查 038 合成夹具与官方示例工程（`.tmp_eprj3_ref/`，gitignored 只对照）里有没有
   BOARD/SCH 容器等价物 → 结论决定 eprj3 走"单隐式板"还是也分板。查不到就当没有，
   走单隐式板，不许编。
2. 孤儿页归并规则定案：页的 `schematic` 引用悬空时——工程只有一块 BOARD 就并入它；
   多块 BOARD 就进显式的"未归属"组，报告如实说"这页不在任何板档里"。
   两种形态都要有用例（注入件 duplicate-designator 是现成的第一种）。

## 工作项 1：板分区（解析层）

- `parsers/schematic.py` 新增板分区：按 DOCHEAD 段 META 链把页分组到板
  （board uuid + title + pages），无 BOARD 文档的工程 = 一块隐式板（"Board1"）。
- 分区结果是纯数据（哪个页属哪块板），不改 F1/F2/F3 的页内解析。
- eprj3 路径按工作项 0 结论接入或保持单隐式板。

## 工作项 2：一板一模型

- `build_schematic_model` 出**每板一个 `DesignModel`**；项目层新 wrapper
  （`ProjectModel {boards: [BoardModel]}`，BoardModel = DesignModel + board {uuid,title,pageUuids}）。
- "一位号一组件"契约收窄为"**一板内**一位号一组件"；跨板同名在两份板模型里各自完整
  （两棵 U2 都活着，不再静默丢 placement）。
- 现有单页/单板消费者拿到的形态不许变：单板工程的 `DesignModel` 行为逐字节同前
  （golden/llc 回归钉照旧是硬验收）。

## 工作项 3：规则与 finding 板归属

- 规则**按板跑**（每板一份模型，规则代码除重号规则外一行不改——这是设计目标，
  做不到就说明切错了）；`Finding` 增 `board` 字段（板 title），schema 只加不改。
- 重号三类语义落位：同页（ERROR，011c）、同板跨页（ERROR，同一网表）、
  跨板（**仍 ERROR，A1**——但消息点名跨了哪几块板，与"同板跨页"区分开）。
  `CROSS_PAGE_REPEAT_IS_A_DEFECT` 常量退役与否由实现时定：三类全 ERROR 的话
  常量就没有存在理由，删掉并改测试。
- checkup report：findings/modules 带 board；`model.boards` 列板清单。
  schema **只加字段不 bump**（031 先例）；动了既有键语义才 bump。
- `_merge_schematic_models`（per-page 档）重写为板分区合并或如实退役——
  合并动作本身在板分区后应该消失，留存量要说明理由。

## 工作项 4：消费方

- `edit plan` 歧义安全阀板感知：位号跨板重复时拒绝并**点名各板**（不只是"一对多"）。
- checkup 的 ambiguity 集合按板解析（`repeated_designators()` 的板级对应物）。
- `review`/`checkup` 的 console 与 report.md 在**多板**时按板分节；单板输出一字不变。

## 工作项 5：验收（全部硬断言进测试）

- 毕设板出 3 个板模型：位号集与 040 铜层对照脚本（`.tmp_040/copper_crosscheck.py`）
  逐板一致；两棵 U2 各自完整（40daf 的排针与 5f0f 的那颗都在）。
- 注入件 duplicate-designator 仍 ERROR（P2 孤儿并入 Board1 → 同板跨页类）；
  eval 双指标不降；毕设板 30 条 A1 仍全抓（类名可变、severity 不许变）。
- golden / llc / 其余单板夹具 findings 逐字节不变。
- eval delta 每格逐条解释（本批预期毕设板 findings 文本会带板名——这种变化要有
  "改的是措辞不是判案"的逐条对照）。

## 纪律与边界

- pytest 必带 `--basetemp=.tmp_pt_home`；三线全绿才交卷；变异 ≥2
  （`cp` 备份 + `sha256` 还原，禁 `git checkout --`）；append 落盘后 `grep -c`。
- 不碰 git / PROGRESS.md / SKILL.md / tests/fixtures / reviewsets 既有标注。
- 纯离线活，不需要真机。
- 交卷 `outputs/040b_summary.txt`：板分区数据 / eprj3 结论 / 测试结果 /
  eval delta 逐条 / 变异 / 遗留。
- **不许**顺带做：跨板网络连通性分析（同一网名跨板是不是真连着——这是另一个问题，
  留给 041 候选）、PCB 视图分板（`--view pcb` 的板归属）。

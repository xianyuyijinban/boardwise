# 109 / A4 提案器批（A 主线最后一棒：intent blocks[] → presentation 草稿）

岳 2026-10-04 裁「开」。全部离线。**先读三份背景再动手**：
`docs/design-intent-channel.md`（A4 行 §102、「未落地」§384 起）、
`tasks/095-A4-intent-driven-order.md` §8（本批的原始出处与三条边界）、
`tasks/098-ic-periphery-grammar.md` §一（三来源纪律：声明 > 合同 > 结构，冲突并列原文拒绝）。

## 要做什么

今天语法是**逐条**读合同的（095 的 branchOrder 三来源、098 的 core 三来源）。
提案器把 intent 文档**一次变成一份 PresentationSpec 草稿**（模块清单 + flow + 角色分工），
让模型/工程师拿到的是一张可以改的全图草稿，而不是让每条语法各自去合同里翻。
**草稿=提案**：它走与手写规格**完全相同的**封闭 schema 加载/校验通道，编译器照旧验证——
提案器只负责「写出来」，正确性仍由既有编译链裁决。

- 输入：intent 文档（`intentVersion/requirements/blocks[]/decisions[]`，
  样例 `blocklib/intents/robot-ctrl-foc.intent.json`）。
- 输出：PresentationSpec 草稿（`core/presentationspec.py` 的
  `PresentationModule(id,parts,role,grammar_ref,side_preferences,branch_order,core)`
  + `FlowEdge(from_module,to_module,main_path)`）。
- CLI：`draw propose --intent PATH [--out PATH]`（命名照 CLI 既有词族，先查再定）——
  草稿打印或落盘；**R3 纪律**：任何输入元素没被读就必须明说，不许静默忽略。

## 提案规则（四条，每条都可机器验）

1. **模块清单**：block.id→module.id、block.parts→module.parts、
   block.kind→module.grammar_ref——**映射表是声明出来的封闭集合**（power-entry→power_entry、
   current-sense→ic-periphery 之类；**先读语法注册表与 intentspec 的 kind 词表再定表**），
   表外 kind 不猜——草稿里如实标注 unmapped（模块仍在、grammar_ref 空 + notes 写明），
   由人或模型补。
2. **core 提案**：按 098 的来源顺序——`modules[].core`（没有，草稿是产物）→ 
   intent 声明（blocks[].parts 里唯一 >2 脚件）→ 结构；**冲突不替裁**：声明与结构不一致
   时该字段留空 + notes 并列两源原文（098 同款），不静默选边。
3. **flow 提案**：从 blocks 的 parts **共网**推邻接（两块在同一网上有件=候选边）；
   **方向只从声明的 kind 角色表给**（如 power-entry 是源）；给不出方向的边如实标注
   underdetermined 而不是猜——mainPath 只在「唯一一条贯穿主链」可判定才标，
   判不出就全不标。056 pagecompiler 的 flow 语义（偏序非路径、无边按模块名序）先读。
4. **角色分工（bulk/TVS 等）**：intent **声明了**才抄（095 的 decisions 消费路径怎么读
   就怎么抄，decisions 是引用不是解释）；**绝不**从值/封装推（053 sec.6 红线：
   哪颗是 TVS 是值与封装的事实，语法/提案器都无权读）。没声明=字段留空，
   回退语法自己的三来源。

## 验收形状

- **round-trip**：草稿 `serialize→parse` 稳定（封闭 schema 纪律）；机器人合同
  （robot-ctrl-foc.intent.json）出的草稿：inlet=power-entry 模块、senseU/senseW 各成模块、
  flow 有 inlet→sense* 邻接；**与 095/098 既有消费路径在同输入上的结论一致**
  （branchOrder/core 不因走提案器而走样——提案器不写它们就回退语法三来源，写了就必须同值）。
- **红测**：①机器人合同草稿断言；②unmapped kind 不猜；③core 声明与结构冲突→留空+双源
  原文；④flow 方向 underdetermined→标注不猜；⑤R3：任何 blocks/decisions 元素没被读→
  报告里点名。测试放 `tests/test_109_intent_proposer.py`。
- **零移动**：五族预览 83 张逐字节 + 21 板对账 + 语料；`intent=None`/不传 `--intent`
  的既有路径逐字节不动（095 同款钉子）。

## 纪律

- pytest 必带 `--basetemp=.tmp_pt_home`，全量亲跑，基线 **3457 passed**；
  **跑全量期间不许改任何源码/测试文件**。
- 变异 ≥2 组（cp+sha256）：M1 kind→grammar 映射退回「全 unmapped」→红；
  M2 core/flow 提案各摘一处→对应红测回红。
- 不碰 git、不写 PROGRESS、**删除一律回收站（PowerShell SendToRecycleBin）**、
  不碰 `tests/fixtures/` 既有夹具与 outputs 禁地。
- 交付 `outputs/109/`：SUMMARY（红→修→绿、映射表与角色表全文、round-trip 证据、
  变异、零移动、全量行）。
- **边界外（不许做）**：页级 pagecompiler 读合同（095 §8② 留记录）、CLI 默认 intent
  落点（095 §8③ 留记录）、页级 flow 跨模块布线。拿不准写遗留。

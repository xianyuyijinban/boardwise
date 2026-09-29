# 072：边界失败处置 + verdict 覆盖闸（issue #28/#29/#30，岳已裁）

## 来源与裁定

岳外部 harness 抓的「边界失败」族三条，同一根：**解析/审查失败的信息在，但不 gate**。
岳裁（两个岔路都按主代理推荐）：

- **岔路 1**：文件能读（合法 zip/JSON 没坏）但产出 0 器件 0 网 → 覆盖问题，
  走 **verdict: incomplete**（理由「归档读不出内容/模型为空，可能被截断/损坏」），
  **不走 exit 2**。exit 2 只留给 #28 那种结构坏。已知代价（岳认可）：
  合法空工程也吃这条——空 ≠ 干净，是对的。
- **岔路 2**：规则抛异常 → **逐条 catch**，崩的规则记进 coverage（`rulesErrored`）、
  verdict 降级，其余规则继续跑完，**报告照出**。不再是裸 RuntimeError + 不写报告。

## 范围（三项）

1. **#28 结构校验 → 干净 exit 2**：
   `parsers/enet.py::enet_dict_to_model` 与 `parsers/epro2_model.py` 同路径加结构校验
   （`components` 必须 dict、每项必须 dict、`props`/`pinInfoMap` 必须 dict、顶层必须 dict），
   违反抛**解析器自己的错误类型**（仓内已有通道，学 `parts.py::library_from_json` 的
   `PartError` 先例），CLI 映射 **exit 2**、stderr 是 boardwise 一句话报错（带位置信息，
   如「components 第 3 项不是对象」）**不是 traceback**。六种崩溃形状
   （components 是 list/null/项是 int/props 是 list/pinInfoMap 是 list/顶层是 list）
   各一条断言：exit 2 + 无 traceback。`checkup --file` 同路径同样处置。
2. **#29 空模型守卫**：`review`/`checkup` 拿到的模型 **0 器件且 0 网**
   （.epro2 路径铜箔也为空）→ 一律不是干净板：`verdict: incomplete`，
   verdictWhy 写明「归档读不出内容/模型为空，可能被截断或损坏」。
   这是覆盖闸 `parseIncomplete` 的极端形态（见第 3 项），不是独立特例。
   既有 `_pcb_view_read_nothing`（cli.py:2295，只对 --view pcb 打一行提示）的
   立场统一进来。
3. **#30 覆盖闸**：`completion` 新增 `coverage` 段，与现有五项并列**进 verdict 判据**：
   ```jsonc
   "coverage": {
     "parseIncomplete": false,   // 解析流中途结束/空模型（④）
     "pagesDropped": 0,          // per-page 有页导出失败（⑤，attempts[].pages 已有数据）
     "rulesRefused": 0,          // #19 未证实网实际 withheld 的规则结论数（③）
     "recordsDropped": 0,        // ParseStats（pins_dropped_no_number + components_without_symbol）
     "rulesErrored": []          // 跑到一半抛异常的规则 id（岔路 2）
   }
   ```
   - 判据（岳已批）：**任一覆盖失败 ⇒ 不得 `complete`**，落 `complete-with-open-items`；
     **整个审查没输入**（空模型）⇒ `incomplete`。`verdictWhy` 逐条列是哪类。
   - `ParseStats` 两项计数**进 report.json**（现在只打印到控制台，cli.py:2500/2547），
     位置自决申报（source 段或 coverage 段，只加不改键）。
   - `rulesRefused` 的计数来源：#19 的 `rules/unproven.py` 已登记
     `NET_MEMBERSHIP_RULES`， withheld 实例 = 理由含 `UNPROVEN_BY_NAME` 的
     UNKNOWN 结论数（形状自决申报）。注意 `source.unprovenNets` 已有
     `rulesRefused: 7`（是「可能拒绝的规则数」）——coverage 要的是
     「本模型实际 withheld 的结论数」，两者语义不同，别混用字段名，申报区分。
   - per-page 少页：`attempts[].pages` 的成败记录接进 `pagesDropped`。
   - 多页单板工程在 per-page 档下跨页网是常态 → 这些工程 verdict 从此常驻
     `complete-with-open-items`：这是档位降级的如实表达，岳已认可。

## 验收

- 先写失败测试：#28 六形状、#29 截断 .epro2（issue 里的 1/3 截断脚本，
  用 `tests/fixtures/ch340_golden.epro2` 复制到临时目录再造，**不改夹具本体**）、
  #30 覆盖闸各字段单项/组合进 verdict（含「coverage 全净 → complete 不受影响」
  与「空模型 → incomplete」）、规则抛异常 → 报告照出且 coverage.rulesErrored 点名。
  再修到绿。测试落 cli/checkup/解析器同域文件。
- **回归申报**：全部既有夹具/reviewsets 板子的 verdict before/after——
  单页工程必须 0 移动；任何移动（如某夹具 ParseStats 有 drop 计数被升级）
  逐个申报原因。`report.md` 渲染同步（coverage 段要渲染出来，按
  「render only what the JSON says」契约），结论头行与 verdict 一致性
  （#21 的交叉不变式）保持绿。
- 变异 ≥2：①结构校验去掉 → #28 钉子红；②覆盖闸从 verdict 判据拿掉 → #30 钉子红
  （cp+sha256 还原 cmp）。
- 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 绿
  （跑全量期间不写 src）。
- 交卷：改动文件 sha256 before/after、测试原文、变异证据、verdict 回归申报、
  全量输出尾行、自决项清单。不改 PROGRESS.md。

## 边界与纪律

- 零 git 写操作；不碰真机；不改 tests/fixtures/ 与 reviewsets/ 既有内容。
- 可碰：cli.py（completion/checkup/解析调用点/report 渲染）、parsers/enet.py、
  parsers/epro2_model.py、core/（ParseStats 定义处）、engines/review.py
  （_run_rules 所在处）、tests 同域文件。rules/ 业务规则本体不碰。
- 先读 `E:/boardwise/AGENTS.md` 与 `.kimi-code/skills/boardwise/SKILL.md` §7。

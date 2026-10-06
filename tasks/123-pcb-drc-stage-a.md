# 123 / PCB 审查阶段 A：DRC 闭环（一棒两阶段）

> 上游：122 路线图（`tasks/122-pcb-review-roadmap.md`，六条裁定已落槌）。
> 本棒只到「test 工程全绿 + 报告出新 section」；**毕设 FOC 的真板验收不在本棒**
> （要岳开板，主代理来做）。

## 背景（已探明的事实，别重探）

- `pcb.drc_check` 早在 025 批就通了（`outputs/025_probe_p4_pcb_drc.txt`），
  `engines/drc.py` 的 `pcb_section()` 已消费 groups；checkup.py 已有
  `pcb-drc:<severity>:<label>:<net>` 叶子身份（基线/diff 的钩子现成）。
- `cli.py:_read_online_drc`（约 5847 行）已经在 review 流程里自动跑
  `sch.drc_check`（逐页）+ `pcb.drc_check`（**只读第一块 PCB**，多板留待后续
  ——本棒要补上循环）；焦点复位在 `finally` 里，这条纪律不许动。
- **规则集可读**（2026-10-06 主代理探针，3.2.186 + connector 0.4.28，
  sys.probe 实测 45 个成员）：`getCurrentRuleConfiguration` /
  `getCurrentRuleConfigurationName` / `getDefaultRuleConfigurationName` /
  `getRealTimeDrcStatus` / `getAllRuleConfigurations` 全是 function。
  但 bridge 动作表**没有**它们（UNKNOWN_ACTION）——要新注册一个 connector 动作。
- 新动作的注册形制照抄 111b 的 `sys.log_read`（connector 0.4.28 加的）：
  `connector/src/actions.ts` 处理器 + 两个注册表（约 7556/7627 行）+
  `PROBE_CALL_ACTIONS` 白名单 + `src/boardwise/bridge/protocol.py` 的
  Action 条目（`risk="read"`）。

## 棒 1：connector 动作 `pcb.drc_ruleset`（TypeScript）

READ-ONLY，读出当前 DRC 规则集：

- 调 `pcb_Drc.getCurrentRuleConfigurationName()`、
  `pcb_Drc.getCurrentRuleConfiguration()`、`pcb_Drc.getDefaultRuleConfigurationName()`、
  `pcb_Drc.getRealTimeDrcStatus()`，原样返回（保守整形：Date/函数剥掉，
  循环引用截断——照同文件既有动作的 sanitize 惯例）。
- **焦点纪律照 `pcb.drc_check`**：焦点文档必须是 PCB，否则报清错误
  （不许自动 doc.open——开文档是调用方的事，025 的边界形态在
  `outputs/025_probe_p4_pcb_drc.txt` §1）。
- **写操作一个都不碰**（create/delete/modify/overwrite/rename/save/
  setAsDefault/startRealTimeDrc/stopRealTimeDrc 全是写或改编辑器状态）。
- 注册三处 + 版本 bump 到 **0.4.29**（package.json 及所有该同步的地方，
  照 0.4.28 那次的 diff 找全）。
- connector 自己的 npm test + typecheck 全绿；给新动作写测试
  （照 sys.log_read 的测试形制：参数校验、错误形态、注册表在位）。

## 棒 2：cli 侧（Python）

1. **多板循环**：`_read_online_drc` 把「只读 pcbs[0]」改成逐块读，
   每块一条 reading；焦点复位纪律原样保留。留待注释删掉。
2. **新 section `drc.ruleset`**：在 review/checkup 报告里加一段——
   当前规则集读数原样落 + **元审查**：与参考表逐键对比，超界落 finding。
   参考表做成**数据文件**（`blocklib/drc_ruleset_reference.json` 或同级合适位置），
   键名**以真机实际读到的字段为准**（棒 1 落地后先在 test/PCB1 上读一次拿到
   形状，再定键）；参考值是「嘉立创双层板常规工艺」的默认起点，文件头写明
   provenance「默认值，岳校」。读不到的字段**不编**——元审查只覆盖读到的。
3. **基线**：确认 checkup 的 digest/回归覆盖 pcb-drc 叶子与 ruleset 段；
   缺则补。
4. **测试**：离线夹具单测（构造 ruleset 读数）+ 真机 test/PCB1 验证一次。

## 纪律（与前几棒相同）

- 真机只碰 test 工程：窗口 `inst-122525753-7bjcs91m`，PCB1 uuid
  `5dc38976c1fa45ce`。**禁地**：毕设FOC驱动板 / ROBOT ctrl FOC / CH340G.eprj2
  及一切真实工程；`doc.open` 只许开 test 工程的文档。
- pytest 必带 `--basetemp=.tmp_pt_home`；零移动：83 预览 + 15 板 findingsha +
  098 scene08 钉 `cd23f7d0…`（本棒按理碰不到它们，但字节闸测试会替你看着）。
- 红测先行；新增行为要有测试；变异验证 ≥2 组（cp+sha256 还原，禁 git checkout）。
- **不碰 git 任何写操作**；删除一律回收站（PowerShell 单引号写法见 AGENTS.md §4）。
- `grammar/`、`blocklib/specs/` 不碰；PROGRESS.md 不写（主代理收口时写）。
- connector 构建产物留在本地；**release 与 update-connector 由主代理做**。

## 交付物清单

1. connector：`pcb.drc_ruleset` 动作 + 注册三处 + 0.4.29 bump + 测试绿 + typecheck 绿。
2. cli：多板 DRC 循环 + `drc.ruleset` section + 参考表 JSON + 基线确认/补全 + 测试绿。
3. 真机证据：test/PCB1 的 `pcb.drc_ruleset` 读数原文 + review 报告新 section 样例
   （落 `outputs/123/`）。
4. 全量 pytest 两轮 + connector/dsh-plugin 三线，数字报给主代理。
5. SUMMARY（`outputs/123/SUMMARY.md`）：形状发现（规则集到底长什么样）、
   哪些字段进了元审查、哪些没读到、没做到的事如实申报。

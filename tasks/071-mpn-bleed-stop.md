# 071：MPN 解码止血批（岳裁「先止血再架构」）

## 来源

岳外部 harness 连抓六条 MPN 案卷（#18 → #22/#23/#24/#25/#26），根因一句话：
**MPN 是查询键不是文档**，正则解码是枚举厂商私有语法，枚举永远做不完
（#18 补一个 witness，#25 几小时内拿出 5 个，四家主流厂三种电压码位置）。
岳裁：**先止血（本批）再架构（facts 优先，072 候选）**。

止血总纲（主代理定，岳已批方向）：**字符串解码的输出永远不许单独产生
VIOLATION/WARN**——任何解码 bug 的爆炸半径缩成「UNKNOWN 代替检查」，
与编码形态无关，不需要知道下一个 witness 长什么样。

## 范围（四项 + 申报义务）

1. **置信闸（主闸，杀 #25/#26 及一切未来形态）**：
   `param-value-mpn-match`（rules/params.py + rules/values.py）里，MPN 字符串
   解码读法与板值**矛盾** → 不再 WARN，改报 **UNKNOWN**，理由注明
   「MPN 字符串解码，低置信：无 facts 佐证」。**匹配 → 判过不变**。
   代价明说：规则的真阳性 WARN 同步暂停（评测夹具
   `value-mpn-mismatch.epro2` 等的 WARN 期望会变 UNKNOWN）——
   **评测基线变化必须逐条申报；若 eval 有用例依赖 decode-WARN 得分，
   先停下报告，不许直接 rebaseline**。
2. **两个解析器并一个（#23）**：`connectivity.parse_resistance_ohms`
   不认中缀（`4K7`→None → 整件被规则跳过，比漏报重）。把板值侧解析
   **委托给 `values.py` 的实现**（`mpn_resistance_readings` 的中缀逻辑
   认识 `4K7/1K0/2M2/100R`）——一个判定只有一份实现（仓库宪法）。
   签名保持，调用方零改；电容侧若有同款分裂（`parse_capacitance_farads`
   vs values.py 的电容读法）一并合并，申报。
   注意反向例：`0R5` 板值侧给 0.5、MPN 侧给 []——合并后语义以
   values.py 为准并申报变化面。
3. **封装尺寸码是语法不是厂商形态（#22 + #24 部分）**：
   尺寸码是行业标准有限集（英制 0402/0603/0805/1206/1210 +
   公制 105/160/188/201/321/322/451/453），认它不是枚举 witness。
   ①值码候选守卫补公制 3 位 → `GRM188R71C104KA01D` 解出 `104`
   （修前 188 混进候选 → 歧义吞掉 → 静默漏报）；
   ②中缀匹配的数字 run 先剥前导尺寸码 → `CRCW060310K0FKEA` 产出真值
   `10K0` 而不是跨字段伪读法 `310K0`（伪读法撞错值判假通过 #24）。
4. **中缀空 run 守卫（#26 建议 1）**：中缀字母前无有效数字（run=''）
   或字母紧跟另一字母（系列名内 `WR06` 的 R、`RK73` 的 K）→ 不产读法。
   `WR06X1002FTL` 的 `R06`=0.06Ω 伪读法就是这么来的。

**明确不做（留 072 架构批）**：E-96 尾放宽（#26 建议 2，形态枚举类）；
电解形态继续补（#25 建议的形态三路，同上）；系列前缀白名单语法；
harvest 扩被动件 + `value` fact（架构本体）；UNKNOWN 进报告的可见性
增强（架构批配套）。#24 在本闸下：真值读法产出后板值 310K 与全部读法
矛盾 → UNKNOWN（诚实），伪读法假通过消失。

**搭车两条小活（独立测试、独立变异）**：

5. **#21**：`summary.conclusion` 是第七道闸没跟上 #14——只读
   errors/unreviewed/marked，骨架缺失与待分诊（生成时不传 pending_triage）
   都不进头版，可与 verdict=incomplete 同时出现。修：conclusion 判据补
   「骨架缺失」与「待分诊」（checkup 生成时把 pending_triage 传进去），
   并补交叉断言：conclusion 说「无 ERROR」时 verdict 必为 complete。
   conclusion 的信息句式保留（不改写成 verdict 三态串）。
6. **#20**：`test_057_page_offline.py` 的墙钟断言 `<2.0s` 机器相关
   （岳 A/B 证明旧代码同样 2.2–3.3s，非 069 回归）。按 issue 建议 1 改
   **相对判据**（search 路由耗时 ≤ lattice 路由 ×N，N 取宽裕值并注释
   「这是退化判据不是性能基线」），字节相等断言（memo-vs-search）不动。

## 验收

- 先写失败测试复现每条（#22 GRM188、#23 4K7、#24 CRCW、#25 五颗电解
  全部变 UNKNOWN 不 WARN、#26 WR06、#21 conclusion×verdict 交叉、
  #20 相对判据），再修到绿。测试落同域文件。
- 回归申报：仓库内 MPN token 语料（fixtures/docs/reviewsets 字符串
  字面量，#18 批用过的 5464 那个口径）old→new 行为对比，逐类申报：
  解码结果变化 / WARN→UNKNOWN 迁移 / 漏报→可查 三类各多少、有无意外。
- 变异每项 ≥1（闸去掉 / 解析合并拆开 / 尺寸守卫去掉 / 空 run 守卫去掉 /
  conclusion 闸去掉 / 相对判据改回墙钟）→ 各自新测试红；cp+sha256 还原 cmp。
- 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 绿
  （跑全量期间不写 src）；connector/dsh 面本批不碰。
- 交卷：改动文件 sha256 before/after、测试原文、变异证据、语料回归申报、
  eval 影响申报（若 rebaseline 需主代理点头）、自决项清单。不改 PROGRESS.md。

## 边界与纪律

- 零 git 写操作；不碰真机；不改 tests/fixtures/ 既有夹具（eval 期望若变
  是测试断言层的事，夹具不动）。
- 只碰 rules/values.py、rules/params.py、rules/connectivity.py（解析委托）、
  cli.py（conclusion 与 checkup 生成调用点）、tests 同域文件。
  core/、engines/review.py、rules/base|facts|decap|unproven.py 不碰。
- 先读 `E:/boardwise/AGENTS.md` 与 `.kimi-code/skills/boardwise/SKILL.md` §7。

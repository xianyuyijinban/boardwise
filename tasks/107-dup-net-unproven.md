# 107 / 重复位号网上的结论降级批（issue #57 B4b 遗留①，岳 2026-10-03 裁定「需要」）

背景：B4b（105）让网成员资格只跟保留 placement 走，DCDC 板因此多出一条**真阳性**
`decap-required-caps` WARN（VCC 没去耦）。但这条 WARN 有一个记录在案的认知缺口：
**被丢弃的 placement 可能正好就是这张网的去耦件**——它真的画在图上、真的接着 VCC，
只是模型按 049 合同只保留了第一份。岳裁定：这种网上的结论不该是自信的 WARN，
要降级 UNKNOWN（把「我们知道得不全」说出来）。

## 修法方向

模型已有 `unproven_nets` + `rules/unproven.py` 的「拒绝下结论」机制（B4a 的 #11 刚保证它
过 reconcile 不丢）。本批把「**这张网的成员清单因重复位号被截断**」这个事实接进同一通道：

1. **事实收集**（`parsers/schematic.py` 成员填充循环）：守卫跳过非保留 placement 时，
   把它**本想写入的网名**记下来（它每个引脚落在自己簇里、簇名已知）——这些网是
   「成员可能被截断」的网。按 `duplicate_designators`（同页）/`cross_page_designators`
   （跨页）区分来源写进 `unproven_nets`（理由串如实写「位号 '100NF' 的第 2+ 份 placement
   的成员未计入，该网结论可能不全」——措辞照 unproven 既有词汇家族）。
2. **消费**：`rules/unproven.py` 的拒绝机制读 `unproven_nets` 后，对落在这些网上的规则
   结论改报 UNKNOWN（缺事实句点名「位号重复、成员可能截断」）。**先读通 unproven.py
   现有的覆盖面**：它是全局拦还是按规则白名单？哪些规则行会被它改报？拿不准的边界写遗留。
3. **不该动的**：没有重复位号的板逐字节不动；`conn-duplicate-designators` ERROR 照旧；
    WARN 本身的内容不变（变的是它在去重板上的**呈现级别**）。

## 预期移动（必须逐板申报）

- **DCDC 夹具**（'100NF'×4、'10UF'×2）：B4b 新增的 decap WARN → UNKNOWN（本批的**目的**）。
- **高速电机控制器 / 毕设FOC驱动板 / 毕设滤波采样 / injected**（B4a 实测带 dup/cross 事实）：
  落在受影响网上的规则行若有级别变化，逐板逐条申报「从什么变成什么」。
- 无重复位号的 19 板：零移动（钉子测试）。

## 纪律

- 红测先行：DCDC 夹具那条 WARN 修前=WARN、修后=UNKNOWN（缺事实句点名截断）；
  unproven 通道的既有行为（B4a #11 的三字段）不因本批回退；无重复板钉子。
  测试放 `tests/test_107_dup_net_unproven.py`。
- pytest 必带 `--basetemp=.tmp_pt_home`，全量亲跑，基线 **3420 passed**，增量恰=新测试数。
  **跑全量期间不许改任何源码/测试文件。**
- 变异 ≥2 组（cp+sha256）：M1 摘掉事实收集→DCDC 回到 WARN=红；M2 摘掉消费侧降级→红。
- 零移动：21 板对账 + 语料 + 五族预览 83 张；除预期移动外的任何移动=停下报告。
- 不碰 git、不写 PROGRESS、**删除一律回收站（临时产物无例外，PowerShell SendToRecycleBin）**、
  不碰 `tests/fixtures/` 既有夹具与 outputs 禁地。
- 交付 `outputs/107/`：SUMMARY（红→修→绿、变异、逐板申报、全量行）。
- 拿不准（同页 vs 跨页待遇、unproven 覆盖面边界）写遗留，别扩大改动面。

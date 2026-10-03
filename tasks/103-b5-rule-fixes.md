# 103 / B5 规则修正批（issue #57 之 #14 #17）

来源：外部审计 `.tmp_bug_report.md` "## 14." "## 17." 两节。跟踪 issue：GitHub #57。
每条先红测复现再修。全部离线。

## #14 param-led-current 并联电阻被求和 — `src/boardwise/rules/params.py:784-786, :850-858, :879, :993`

规则对每个远端网各出一条再**求和** ⇒ 并联电阻被加总。审计实测：两颗 2.2kΩ 并联报成
**4400Ω** 并 WARN「above the window [470, 2200]」——真实阻值 1100Ω，结论恰好相反；
跨在 LED 上的电阻还会被数两次。
修：并联支路不得求和——同一 LED 回路的串联段才相加，并联段按并联合并（或按电路语义
如实归并），双数的件只数一次。**先读懂这条规则现有的回路建模**（far net 是什么、
串联段怎么识别），按它自己的语义修，别新造一套；修法若对「什么样的拓扑算并联」
有拿不准的边界，写遗留别自行扩大。

## #17 build_bom 假「两器件值不同」冲突 — `src/boardwise/engines/bom.py:268, :279-280, :292`

placement 没有 `value` 参数时，`build_bom` 拿它跟条目的 **MPN 兜底串**比，宣布
「值不同」、把 JLC `Comment` 格清空，还给同料的后续每个 placement 各记一条无意义
open question。审计用仓库自己的 `tests/test_bom.py` 构造器复现：三个 placement
明明一致却 `ok=False`、CSV `Comment` 为空。**潜伏**（现有 blocklib 块还没有这个形状）。
修：placement 缺 `value` 不算「值不同」——比较只在双方都真的声明了值时才可能冲突；
缺值侧按「未声明」处理（与条目兜底一致），Comment 不清空、不记 open question。

## 纪律

- 测试放 `tests/test_103_b5_rule_fixes.py`；#14 的红测必须含「两颗 2.2kΩ 并联」与
  「一件被双数」两形，#17 用审计同款的 test_bom 构造器形状。
- pytest 必带 `--basetemp=.tmp_pt_home`；全量亲跑，基线 **3362 passed**，增量恰=新测试数。
- 变异 ≥2 组（cp+sha256）：M1 恢复求和 → #14 红测回红；M2 恢复 MPN 兜底比较 → #17 红测回红。
- 零移动：21 板规则输出对账（087 机具）+ 五族预览 83 张；#14/#17 若让任何既有夹具/语料板的
  规则结论变化，逐板申报（并联求和改并联合并后结论应当只在「真有并联」的板上动）。
- 不碰 git、不写 PROGRESS、删除一律回收站、不碰 `tests/fixtures/` 既有夹具。
- 交付 `outputs/103/`：SUMMARY（红→修→绿、变异、零移动、全量行）。
- 拿不准写遗留，别扩大改动面。

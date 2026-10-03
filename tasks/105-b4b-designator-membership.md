# 105 / B4b 位号混网批（issue #57 之 #1，审计最重的一条，单独成批）

来源：外部审计 `.tmp_bug_report.md` "## 1." 节。跟踪 issue：GitHub #57。
先红测复现再修。全部离线。

## 缺陷（已亲核的代码事实）

`src/boardwise/parsers/schematic.py:1737-1739`：union-find 节点是**全限定**的
`(inst.page, designator, number, placement)`（:1729），每个物理引脚都落在正确的簇里；
但网成员键是 `member = (component.designator, number)`（:1737）**没有 placement 维度**。
于是同位号的不同物理件把**同一个二元组**推进**不同的网**：

```
DCDC 夹具实测（tests/fixtures/DCDC-12V9V转5V3V3_2026-09-27.epro2，该文件真的存了 4 颗 100NF、2 颗 10UF）：
('100NF','1') -> ['GND','NET1','VCC','VCCA']     ('10UF','2') -> ['+5V','VCC']
```

**一个引脚同时在四个网上，是任何布局都产不出的状态**；下游所有规则/比较/BOM/网表导出
都在这张电气不可能的网表上下结论。死代码 `pin_nodes`（:1610，写了从不读）与 :1601-1607
的注释证明当年修了一半：union-find 那一半落了，网表键这一半没落。

## 模型自己的合同（修法必须顺着它，别逆着）

`:1540-1556` 的注释白纸黑字：**"one designator, one component"**——
`model.components.setdefault(designator, component)` 只保留**第一个** placement，
理由是 049 实测（毕设 FOC 的 U15/U16：第一份拷贝的引脚才是 PCB 的引脚）。
040/040b 把两种重复分开：同页重复=真冲突（`duplicate_designators`，CONN-1 的 ERROR），
跨页重复=另一块板自己编号（`cross_page_designators`）。

**修法方向**：网成员资格跟着「模型真正保留的那个 placement」走——成员填充循环里，
非保留 placement 不推 member（它们的引脚仍在自己节点上拿网名、仍参与
duplicate/cross_page 元数据，但不再往 `net.pins` 里焊幻影成员）。这样：
- 每个 `(designator, pin)` 元组恰好出现在**一个**网里（=保留 placement 自己的簇）；
- 无重复位号的板**逐字节不动**（skip 从不触发）；
- 带重复的板成员清单**收缩**到保留 placement——这是本批**有意的移动**，逐板申报。
审计暗示的「全 placement 限定键」大重构**不做**（与 049 合同冲突、牵动每个消费者）。

## 必须做的消费者普查

`net.pins` 的每个消费点（rules/、compare.py、netlist 导出、BOM、draw、`_members` 家族）
过去都可能读到「同一元组在多网」。修后要全库 grep 一遍，确认没有消费者**依赖**那个
不可能状态（比如靠「同一元组出现在两网」来发现重复——重复的发现应该走
`duplicate_designators` 元数据）。`conn-duplicate-designators` 规则修后必须照样开火
（它读元数据，理应不受影响，红测钉住）。

## 纪律

- 红测：①DCDC 夹具亲跑——`('100NF','1')` 修前在 4 网、修后恰在 1 网（且是保留 placement
  的那一网），`('10UF','2')` 同理；②合成夹具同页重复 + 跨页重复两形；③「无重复板
  逐字节不动」钉子。测试放 `tests/test_105_b4b_designator_membership.py`。
- pytest 必带 `--basetemp=.tmp_pt_home`；全量亲跑，基线 **3381 passed**，增量恰=新测试数。
  **跑全量期间不许改任何源码/测试文件。**
- 变异 ≥2 组（cp+sha256）：M1 摘掉「非保留 placement 不推 member」→ DCDC 红测回红
  （4 网复现）；M2 自选一个消费面反向变异。
- 零移动：21 板对账（**重点申报带重复位号的板**：DCDC 夹具、高速电机控制器、毕设FOC、
  毕设滤波采样——B4a 实测它们带 dup/cross 事实；成员清单收缩后这些板的规则结论若变，
  逐板逐条申报「从什么变成什么、为什么这是修复」）+ 语料 + 五族预览 83 张。
- 不碰 git、不写 PROGRESS、删除一律回收站、不碰 `tests/fixtures/` 既有夹具。
- 交付 `outputs/105/`：SUMMARY（红→修→绿、消费者普查结论、变异、零移动逐板申报、全量行）。
- 拿不准写遗留（比如跨页重复与同页重复该不该同一待遇——先按合同同一待遇，有歧义写遗留），
  别扩大改动面。

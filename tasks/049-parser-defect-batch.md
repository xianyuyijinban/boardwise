# 049 任务书：解析器缺陷批（P1 定性 / P2 修复 / P3 修复）

> 2026-09-27 立。执行者：DeepSeek 子代理（commandcode/deepseek-v4.1-flash）。
> 三件：P1 DCDC 板疑似并网（调查定性 → 确认是 bug）；P2 级联 14 pin dropped + U3（调查定性）；
> P3 `conn-usb-cc-pulldown` 被连接器自身遮蔽（已钉位置，直接修）。
> 红线：不碰 git / 真机 / bridge / connector / `reviewsets/*.json` 标注；
> **eval 两条红线（holdout 检出 42/42、高优精确 42/42）不许破——破了停下报告，不许改标注**。
> 证据全文：`outputs/049_evidence.txt`；eval 产物：`outputs/049_eval_{holdout,dev}.{txt,json}`。

**一句话结论**：P1 是**真解析器 bug**（同页重名位号 → 引脚节点同号 → 多个走线岛被焊成一个簇、
网名被字典序改判）；修复已写并实测，但会让 holdout 高优精确掉到 42/44，**按红线不落盘**，
补丁与本报告一并交主代理请示 oracle。P2 是**一半 bug 一半实情**：14 个"丢脚"是 bug（脚号在
文件里，只是被增量保存挪到 SYMBOL 文档末尾），已修；U3 是源文件实情（SCH 文档整条记录缺失，
只在 PCB 文档），登记为已知限制。P3 已修（FPC 板的 R24/R27 = 5.1K 现在拿得到 OK）。

---

## P1 DCDC 板疑似并网（调查定性 → bug，修复 hold）

### 现场（`tests/fixtures/DCDC-12V9V转5V3V3_2026-09-27.epro2`，单页 schematic）

- U10 = `RT9013-33GB`（symbol `29d71f5b…`，`record_id=e6597`，rot=0）；
- 脚位：`1 VIN@(254,744)`、`2 GND@(254,724)`、`3 CE@(254,734)`、`4 NC@(334,724)`、
  **`5 VOUT@(334,744)`**；
- pin5 落在走线组 `e14930`，该组的 `NET` 标签原文 = **`'VCC'`**；`e38515`（U10 的 VIN/CE）
  的标签是 `'+5V'`。
  ⇒ **图纸把 VOUT 画在 VCC 走线上**，与 oracle xianyuyijinban的裁决逐条一致；模型里的 +5V 不是图纸的事。

### 病根（解析器 bug，两段叠加）

1. **引脚节点身份不足**：`_fill_board_model` 的并查集节点键是
   `("p", page, designator, number)`，同页重名位号（本板 `100NF`×4、`10UF`×2 =
   板上那两条 `conn-duplicate-designators` ERROR）**共用同一个节点**，于是每个放置点所在的
   走线岛都被这条节点串起来；
2. **簇名取"组内显式标签字典序最小者"**：焊并后的簇里有
   `GND / VCCA / VCC / +5V`，`'+5V' < 'GND' < 'VCC' < 'VCCA'` ⇒ 整簇叫 `+5V`。

实测簇：`root=('p', <page>, 'R5', '1')`，含走线组
`[e10225(GND), e10783(无标签), e11449(VCCA), e14930(VCC), e38515(+5V)]` 与 11 个脚
（`100NF.1 10UF.2 10UH.1 10UH.2 12UH.2 4.7UF.1 R5.1 U10.1 U10.3 U10.5 U9.1`）——
一个把 GND 与 +5V 焊在一起的岛。并查集日志给出的链路：
`100NF.1` 的 4 个放置点分别命中 `e10225 / e10783 / e14930 / e11449`，`10UF.2` 的 2 个命中
`e38515 / e14930`。

顺带解释了 017 草稿 §D.1 的两条现象：`+5V` 上的"电压来源冲突"（5.0V vs U10 的 3.3V）与
"`10UH` 两脚同网"（实际是 pin1 在 VCCA、pin2 在 VCC，被焊进同一簇）。

### 修法（hold 补丁 `outputs/049_p1_hold.diff`，41 行）

引脚节点多带一个"放置点下标"（`enumerate(placed)`），其余字典序/自动网名规范序不动：

```diff
-    for inst, component, pins in placed:
-            node = ("p",) + key
+    for placement, (inst, component, pins) in enumerate(placed):
+            node = key + (placement,)
```

实测（补丁在位）：`U10` 五脚 = `1 VIN=+5V / 2 GND=GND / 3 CE=+5V / 4 NC=None / 5 VOUT=VCC`，
`10UH` = `1 VCCA / 2 VCC`，`+5V / VCC / VCCA / GND` 各自成网。

### 为什么不落盘：eval 红线实测

| 状态 | 检出 | 高优精确 | locate |
|---|---|---|---|
| 补丁在位 | 42/42 | **42/44**（2 条无 oracle 记录） | 64/76 |
| 补丁撤离（交付态） | 42/42 | 42/42 | 64/76 |

两条新 finding 都在 holdout 的 `ProPrj_毕设FOC驱动板_2026-09-17` Board1：

```
Board1 WARN | U15 pin8: no grounded capacitor found on net 'NET88' (required 0.1uF)
Board1 WARN | U16 pin8: no grounded capacitor found on net 'NET96' (required 0.1uF)
```

U15/U16 正是该板**同页重名**的两个位号：焊并时它们与"另一份放置点"的电容同岛（decap 判 OK），
拆开后"模型保留的那份放置点"的 pin8 落在没有电容的岛上。这是"重名位号只能保留一份放置点"
的老限制被暴露出来的新读数，**无 oracle 记录**，且该板在 holdout 是已签状态（43 条）。
按任务书口径**停下报告**：补丁留在 `outputs/049_p1_hold.diff`，请示 oracle 三选一
（补 2 条标注 / 把该板状态改回待裁决 / 接受 42/44）。装上/撤回各一条命令（两份文件同时放在
`outputs/` 与 `.tmp_049/`，`outputs/049_base_schematic.py` 就是交付态那份，
sha256 `b5cf9b02…`）：

```bash
cp outputs/049_p1_schematic_ready.py src/boardwise/parsers/schematic.py   # 装上（sha256 7cb231ba…）
cp outputs/049_base_schematic.py     src/boardwise/parsers/schematic.py   # 撤回（sha256 b5cf9b02…）
```

---

## P2 级联 14 pin dropped + U3 仅存 PCB 文档（调查定性：一半 bug、一半实情）

### 14 个丢脚：**bug**（形状未覆盖）

夹具 `tests/fixtures/级联多电平-主拓扑_2026-09-27.epro2`，模块符号 `f371d0767f223ad5`
（`级联H桥驱动`）有 10 条 `PIN`：`1 15V+ / 2 15V- / 7 Q2G / 8 Q2S / 9 Q3G / 10 Q3S /
11 Q1G / 12 Q1S / 13 Q4G / 14 Q4S`（`zIndex` 值 1,2,7..14）。脚名与类型跟着各自的 PIN 行，
**脚号却在文档末尾的一整块 `Pin Number` ATTR 里**（line 3427-3434，`'3'..'10'`），每条
`parentId` 指回各自 PIN 行的 id（`52d927f901cf5fe5` 等）——即 042 在组件层测到的"增量保存把
属性追加到文档尾"的形状，在 SYMBOL 文档里复现。旧 `_collect_symbols` 只按流位置配对，那块
8 条全被"最后打开的那段"（z=14）吸收（恰好写对 '10'），`z=7..13` 七个脚丢号 → 整脚丢弃
（名字、位置、所有连线）→ 每份符号 7 个、两个实例 = **14**。

两条独立佐证（不依赖 `parentId`）：① 那些 `Pin Number` 的标注坐标与各自 pin 端点同行
（`'3'` at (15,-29.08) 对 z=11 (30,-30)；`'10'` at (15,40.91) 对 z=14 (30,40)）；
② 模块 footprint（PCB 文档 `5148911b9c9b2d7c`）的 pad 编号就是 1..10。

**同根因一并验证**：`llc_board.epro2` 同样是尾块形状（line 5984-5991），丢脚 14 → 0
（020 当年记的"7 个有名无号脚"是误读，脚号在文件里）；`级联多电平-驱动模块` 丢脚 14 → 0
（任务书写"12 pin(s) dropped"，实测与主拓扑同为 **14**，以实测为准）；`FPC触屏游戏机`
是**相反形状**——PS7516 的脚属性在自己的 `PIN` 行**之前**，按位置配对整体错位一格，
丢脚 12 → 0，U8 的 GND 脚从自动网归位到 GND。

### 修法

`src/boardwise/parsers/schematic.py`：`_collect_symbols` 改成按文档整体提交
（新 `_commit_symbol`），**两趟**——先收齐该文档所有 `PIN`（同时按"PIN 行自己的 id"与格式
ref 建**两个**索引），再按 `parentId` 归档 `Pin Number` / `Pin Name` / `Pin Type`；
`parentId` 指不到任何脚时退回流位置（老规则），**任何字段都不覆盖**（先到先得，所以老读数
一个都不动）。新增私有件：`_PinRun`、`_pin_ref`、`_fill_pin_attr`、`_PIN_ATTR_KEYS`；
原 `flush()` 的计数语义（文档结束仍无脚号 → `pins_dropped_no_number += 1`）原样保留。
附带修掉一族隐患：两个 id 索引**不能合并成一个 dict**（eprj3 流里 `id=e1,e2` 而 ref 是
`e2,e3`，一个脚的 ref 恰是邻居的 id，合并会把属性交给邻居）。

### U3：**源文件实情**（不是解析丢弃）

- 整份 `.epru`（约 2 MB）里字符串 `U3` 只出现一次：PCB 文档的一条
  `ATTR Designator='U3' parentId=4c9e95b667d00546`（后者是该 PCB 文档的 `COMPONENT`）；
- SCH_PAGE 文档 64 条 `COMPONENT`、57 条带位号，**没有 U3 这条记录**；
- PCB 58 位号 − SCH 57 位号 = `['U3']`（唯一差集）；
- 结论：**SCH 文档里整条记录缺失**，设计里这颗模块只放进了 PCB、没画进原理图页；
  原理图模型看不到它是定义使然（pcb 视图看得到：10 个 pad 全无网络）。
  如实登记为**已知限制**——解析器变不出原理图里没有的器件；要不要在 reviewer 面前点名
  "本板有 PCB-only 器件"，属产品口径，本批不动。

### eval 影响：**零**（红线保持）

20 份夹具快照对比：`pins_dropped_no_number` 变化的只有那 4 份（12/14/14/14 → 0），
其余 16 份逐字节不变；holdout 的 **signed-clean 板（级联多电平-主拓扑）修好后仍是 0 finding**
（eval 该板段落逐字未变），与 017 的 clean signed 记录**不冲突**，无需请示 oracle。
驱动模块仍是 4 WARN / 10 INFO（逐字一致）。

---

## P3 `conn-usb-cc-pulldown` 被连接器自己遮蔽（已修）

`src/boardwise/rules/facts.py::UsbCcPulldown._resistance_to`：旧实现返回**第一个**"自己也有脚
挂在 `to_net`"的器件当电阻；USB-C 连接器天然满足（CC 脚挂 `net`、GND 脚挂 `to_net`）且排在
真下拉电阻之前，于是 `parse_resistance_ohms('TYPE-C 16PIN 2MD(073)')` = None →
`(None, 'USB1')` → UNKNOWN。017 遗留的正是这条（FPC 板 R24/R27 = 5.1K 拿不到 OK）。

修法：只接受**货架认得的电阻**（`entry.category == "resistor"`，与规则自己 `_rows()` 里的
`entry_for` 同款入口）；有货架条目却声明为别的类别（connector / capacitor / ic.*）不作候选；
**无货架条目**的器件仍按"值能解析成电阻"参与（沿用规则既有口径）。net 上**没有任何电阻样
器件**时保留旧的"第一个跨两网的器件"读数（否则"无候选"分支会把它变成 ERROR —— 实测
`injected/duplicate-designator` 板会因此从 UNKNOWN 变 ERROR，高优精确 42/43）。

实测：`FPC触屏游戏机` 与 `超声波` 两块板各 2 条 UNKNOWN → **OK**（R24/R27 (5100Ω)、
(5100Ω)）；`ch340_golden`、`injected/fixed-base` 逐字不变；`injected/duplicate-designator`
刻意保持 UNKNOWN。

---

## 通用交付要求（本批执行情况）

- 定向 `pytest --basetemp=.tmp_pt_049`（未跑全量为先；见交卷记录）。
- 变异验证：P2 ×2、P3 ×2，`cp` 备份 + sha256 还原（明细见交卷记录与
  `outputs/049_evidence.txt` §5）。
- eval 复跑 holdout + dev，与 046b 基线对比，逐条解释（证据 §4）。
- 不 commit。append 落盘后 `grep -c` 防双执行。

---

## 交卷记录

（执行者，DeepSeek 子代理，2026-09-27；证据全文 `outputs/049_evidence.txt`）

### 三件各自：定性 + 改动文件 + 两行摘要

| 件 | 定性 | 改动文件 | 两行摘要 |
|---|---|---|---|
| P1 | **bug**（同页重名位号 → 引脚节点同号 → 多个走线岛焊成一簇，簇名被字典序改判为 +5V；图纸本身把 VOUT 画在 VCC 上，与xianyuyijinban的裁决一致） | 无（补丁 `.tmp_049/schematic_with_p1_ready.py`，diff `outputs/049_p1_hold.diff` 41 行） | 修法 = 引脚节点多带放置点下标；实测 U10.5→VCC、10UH 两脚 VCCA/VCC、四网分开。装上后 holdout 高优精确 42/44（新增 2 条 decap WARN 在毕设FOC板 U15/U16 pin8），按红线**不落盘**、请示 oracle。 |
| P2 | **一半 bug 一半实情**：14 个丢脚是 bug（脚号在文件里、被增量保存追加到 SYMBOL 文档尾，`parentId` 指回各自 PIN 行）；U3 是源文件实情（SCH 文档整条记录缺失，只在 PCB 文档） | `src/boardwise/parsers/schematic.py`（`_collect_symbols` 重写 + `_commit_symbol`/`_PinRun`/`_pin_ref`/`_fill_pin_attr`/`_PIN_ATTR_KEYS`）；`tests/test_049_parser_defects.py`（新，6 用例）；`tests/test_020_parse_drops.py`、`tests/test_040_page_scope.py`（旧测量重钉） | 修法 = 按 `parentId` 归档引脚属性、位置作退路、字段不覆盖；实测主拓扑/驱动模块/llc 丢脚 14→0、FPC 12→0，模块 10 脚与端子网络全部读到。eval 三条红线全保持（signed-clean 板仍 0 finding），仅 UNKNOWN 覆盖 116/183→114/183；U3 登记为已知限制。 |
| P3 | **规则 bug**（连接器自己满足"两脚都在"，遮蔽真下拉电阻；017 遗留） | `src/boardwise/rules/facts.py`（`_resistance_to` + 新 `_resistor_like`）；`tests/test_011d_rules.py`（+4 用例） | 修法 = 只接受货架认得的电阻；无货架条目按值判；无电阻样器件时保留旧读数（避免模型重名限制变成 ERROR）。实测 FPC 与超声波各 2 条 UNKNOWN→OK（R24/R27 5100Ω），golden/fixed-base 逐字不变。 |

### 新增测试与定向结果（`--basetemp=.tmp_pt_049`）

- **P2/P3 新增 10 用例**：`tests/test_049_parser_defects.py` 6 条（尾块形状、属性前置形状、
  两个 id 索引不串门、主拓扑模块端子、驱动模块模块、FPC PS7516 不位移）；
  `tests/test_011d_rules.py` 4 条（连接器不再遮蔽 + 真下拉拿 OK、只有连接器时保持 UNKNOWN、
  电容不算电阻、FPC 真实板 CC 两条 OK）。
- 旧测量用例按新读数重钉 5 处：`test_020` 三条（llc 14→0，note 性质移到合成流 `_unnumbered`）、
  `test_040` 一条（llc 冻结签名 111→118 脚，器件/网数不变）、`test_020`
  模块 docstring 与 `_symbol_doc` 注释（"唯一还该丢的形状"）。
- 定向读数：`test_049_parser_defects.py` **6 passed**、`test_020_parse_drops.py` **12 passed**、
  `test_011d_rules.py` **52 passed**、`test_040_page_scope.py + test_040b_boards.py +
  test_038_eprj3.py + test_020 + test_042_attr_parentid.py` **68 passed**、
  三件合并一轮 **70 passed**。
- **全量一轮**（`pytest tests/ -q --basetemp=.tmp_pt_049`）：首轮 **5 failed / 1825 passed**
  （全部是上面那 5 处被旧测量钉死的用例），重钉后**1840 passed**（125.63s，exit 0，含本批
  新增 10 用例）；docstring 清理之后又跑一轮 **1840 passed**（116.49s，exit 0）——交付态读数。
- 文档同步：`docs/epru-format.md` 新增 **§8.1 "Schematics: a SYMBOL pin attribute is owned by
  `parentId`"**（两趟归档、`id` 与 `e<zIndex>` 两种拼法不能合表、真无名脚才该丢、PCB-only 器件
  U3 属源文件实情）——P2 的形状是**格式事实**，落在这里而不是只留在测试里。

### 变异明细（cp 备份 → 改一行 → 必红 → cp 还原 → sha256 一致）

| # | 件 | 变异 | 结果 |
|---|---|---|---|
| M1 | P2 | 归档顺序 `(named, open_run)` → `(open_run, named)` | **CAUGHT** 5 红（`test_049`×3 + `test_020`×2） |
| M2 | P2 | `run_named_by` 去掉"PIN 行自己的 id"索引 | **CAUGHT** 同样 5 红 |
| M3 | P3 | `_resistance_to` 退回"第一个跨两网的器件" | **CAUGHT** 4 红 |
| M4 | P3 | `_resistor_like` 忽略货架类别 | **CAUGHT** 同样 4 红 |

还原后逐字节复核：`schematic.py` `67dd209ea6378aa957a3663e70066afecdca543118a8832df091041f74156b2a`、
`facts.py` `941440b38a8ff7dc2f323e76ad9ffc21fc070a2cf7edcb3d53bbe5312fb9ee87`。
（变异之后又做了一次**纯注释**清理：模块 docstring 里"Pin Number 的 parentId 是
`e<zIndex>`"那句改成两种拼法都写明（`docs/epru-format.md` §8.1 同步），`schematic.py`
最终 sha256 变为 `b5cf9b02511715a23e190d51254b819bd3d63018b7c82704801cc74dd4375b55`；
改动只在 docstring 内，随后重跑定向 128 passed 与全量见下。）

### eval 对比（046b → 049）

| 指标 | 046b holdout | 049 holdout | 事前 dev | 049 dev |
|---|---|---|---|---|
| defect detection | **42/42** | **42/42** | 4/5 | 4/5 |
| high-priority precision | **42/42** | **42/42** | 4/5 | 4/5 |
| locate success | **64/76** | **64/76** | 64/76 | 64/76 |
| UNKNOWN 覆盖 | 116/183 | **114/183** | 116/183 | **114/183** |

逐条解释（holdout 文本 diff 的全部变化）：① FPC 表头 60→59 网（P2 把 U8 的 GND 脚归位后两张
自动网合一）；② FPC `conn-usb-cc-pulldown` UNKNOWN 2→OK 2（P3）；③ 超声波 同 2→2（P3）；
④ UNKNOWN 覆盖 116→114 与 `conn-usb-cc-pulldown 3/11→1/11`：正是上面两处 (规则×板) 对从
"有 UNKNOWN"变为"无"；⑤ `value-unreadable` 明细 7→3 条（那 4 条 `missing_fact` 都是
"a readable value on USB1" = 被遮蔽的占位读数）；⑥ rulebody 哈希变化，唯一原因是改了
`rules/facts.py`（ruleset `232eee40`、规则 14 条未变）。其余 13 块板（含 signed-clean 的
级联多电平-主拓扑）逐字节未变。P1 补丁在位的对照：检出 42/42、**高优 42/44**、locate 64/76。

### 遗留

1. **P1 待 oracle 裁决**：补丁 `outputs/049_p1_hold.diff` + `outputs/049_p1_schematic_ready.py`
   （一条 `cp` 装上，撤回用 `outputs/049_base_schematic.py`）。
2. P1 第二层限制：同页重名位号只保留最后放置点——修好后网成员表里同一位置号会出现在多张网上
   （`conn-duplicate-designators` 已在报这条冲突）。
3. **U3 无解析器解法**（原理图文档里没有这条记录）；是否点名 PCB-only 器件属产品口径。
4. 真实夹具现在丢脚全为 0，"解析丢脚"告警暂无真实现场，性质由合成流承载。
5. connector / dsh-plugin / tsc 三线未跑（本批只动 Python；由主代理统一跑四线）；
   未 commit、未碰真机/bridge、未改 `reviewsets/*.json`。

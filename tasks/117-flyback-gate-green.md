# 117 — 反激整页翻绿：AUX/PGND 网表合并 + 文字/旗标摆位 + _order_wanted 符号

**来源**：116 交付后的全部剩余（`outputs/116/SUMMARY.md` §六 +
`outputs/116/flyback_gate_verdict.txt` 原文 11 条；§四 的继承缺陷）。
116 之后反激六条变体全部越过关系闸，整页停在 readability 闸 11 条硬违反。
**这是反激链的最后一棒：翻绿即出图。**

## 三件事

### ① netlist-partition-mismatch（1 条，真几何）

闸报原文（`flyback_gate_verdict.txt` [1]）：
`pins[C10.2]+[C6.2]+[C7.2]+[D2.1]+[R10.2]+[R5.2]+[T1.A2]+[U5.3]` 被 plan
并成同一个节点——其中 `D2.1`/`T1.A1` 在 spec 的 **AUX** 网上，其余在
**PGND** 族。即辅助绕组热端被几何地并进了 PGND 结点簇。

先查清根因再治（三种候选，实测定）：
a. PGND 旗标/ stub 落到了 AUX 节点上（旗标摆位病）；
b. 布线把 AUX 热端接到了 PGND 结点簇（布线病）；
c. T1 的 A1/A2 脚在符号 profile 里的归属读错（profile 病）。
**查清哪一种， SUMMARY 里写死**；治法对症，不许三类一起糊。

### ② text-overlap（10 条，文字/旗标摆位）

两类形态（`flyback_gate_verdict.txt` [2]-[11]）：
- **值文本 × 旗标名/位号**：长值（`22uF/25V X5R 0805`、`EE16_3+3_V02 (…)`）
  压 AUX/VFB_NF/PGND 旗名、压 D3 位号；
- **文本落在器件体上**：C10/1nF 值落 U5 体、T1 值落 D3 体、PGND/AUX 旗名
  落 U5/C7 体。

素材：编译器自己有字宽表（`drawcompiler.GLYPH_ADVANCE`，053 sec.5 的
加宽表——drawlint 实测过它比渲染 Arial 宽 1.26 倍，**预留空间用它是对的方向**）
与 `_text_walls` 机制（:1781，文字盒参与避障早已有）。方向：
- 摆放/布线阶段把**值文本盒**（位号行+值行，按 GLYPH_ADVANCE 估宽）当
  一等墙——旗标位与文本位分配时互相避让；
- 旗标名贴着旗走但**不压器件体与文本盒**（P22/P23/P24 的合法形态：
  旗名悬在旗旁 ~15-19 单位，坑 43 实测几何）。
- 别发明新的文字渲染；估算就标估算（drawlint 同款纪律）。

### ③ _order_wanted 水平符号（116 §四 揭的继承缺陷）

`drawcompiler._order_wanted`（115①）水平两类（left-of/right-of）与闸
**符号相反**，竖直两类对；115 的唯一真病例是竖直所以从未显形。116 不敢改
（不在它的闸内），本棒收：
- 红测先行：合成一条**水平**支路×owner 序关系用例，现行代码下方向给反
  → 红；修符号 → 绿。
- **A/B 身份证明**：当前所有真实输入（五语法 + flyback spec）没有一条
  水平支路×owner 序关系走这条路（116 的 C10 是支路×别链件，走 `_order_asks`），
  所以修复对全部真实输出**零效应**——83 预览 + 15 板 + flyback 编译结果
  逐字节不变，这是必须达标的闸，不是期望。

## 验收（反激链的里程碑）

1. `blocklib/specs/flyback_uc3845.*` 整页编译 **ok=True、candidates ≥1、
   readability 闸零硬违反**；候选**预览 SVG 落 `outputs/117/`**——
   这是编译器第一次产出反激整页。
2. 113 的 skip 测试：live 快照那一半之外的全部理由应已消失——把测试改成
   「编译出图 + 闸全绿」的真断言（live lint 那一半保留 skip 并更新理由）。
3. 既有五语法 83 预览 + 15 板 sha256 全同（含 098 scene 08 钉）。
4. 合成单测：①的根因形态、②的两类形态、③的水平符号。

## 纪律（同款）

红测先行；变异 ≥2（cp+sha256 还原）；全量 pytest
`--basetemp=.tmp_pt_home`（基线 **3640 passed + 1 skipped**——116 交了
11 条新测试，先核实再报）；`PROGRESS.md` 单行（`grep -c "^- 117 "`=1）；
证据落 `outputs/117/`；禁 git/真机/daemon；删除走回收站；
grammar/*.py 一字不改；**①②③ 各自独立可验**，做不完就按 ③→①→②
的顺序交，留全绿中间态 + SUMMARY 精确断点。

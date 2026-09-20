# 干净基底（fixed-base）与变体重派生报告

oracle 终裁 2026-09-19：①**U3 正确值 = 1k（value 对，MPN `FRC0805J471` 错）**；②**V3 正确接法 = 短接 VCC**。
生成器：`reviewsets/injected/make_variants.py`（唯一写入者）。流水线变为两层：

```
tests/fixtures/ch340_golden.epro2  --[两处修复]-->  fixed-base.epro2  --[六个注入]-->  6 个变体
```

## 一、逐变体结果

| 变体 | 预期规则 | ref | 严重级 | det/hint | 交叉 | 误报 | **基底是否已触发** |
|---|---|---|---|---|---|---|---|
| `duplicate-designator` | conn-duplicate-designators | R24 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ 隔离 |
| `nc-pin-grounded` | conn-nc-and-must-connect | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ 隔离 |
| `overvoltage-rail` | pwr-domain-vs-range | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ 隔离 |
| `ldo-no-headroom` | path-ldo-dropout | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ 隔离 |
| `value-mpn-mismatch` | param-value-mpn-match | U3 | WARN | 1/1 | 0 | 0 | 0/1 ✓ 隔离 |
| `v3-decap-missing` | decap-required-caps | U1 | WARN | **0/1** | 0 | 0 | 0/1 —— **注入不可见** |

数据：`outputs/011d2_variants_summary.txt`；机制取证：`outputs/011d2_v3_decap_analysis.txt`。

## 二、(b) 基底干净的证据

- **零发现**：`fixed-base` 上任何规则都不报（0 ERROR / 0 WARN / 0 INFO），全部误报列为 0；
- **两条原生 defect 消失**：黄金集的两条 defect 记录在基上 `det=0 / missed=1 / violations=0`，
  而**在同一份标注集下的黄金板上仍是 `det=1 / violations=1`** —— 证明是"板修好了"，不是"尺子放水"；
- 模型级：`U3.mpn == FRC0805J102 TS`（value 1000 与 code 102 一致，规则报 OK）；`U1 pin4` 落在 **VCC**
  网上（与 pin16 同网），网数 13→12。

修复怎么做的：
- **U3**：只改**实例**的 `Manufacturer Part`（`FRC0805J471 TS` → `FRC0805J102 TS`，同系列 1k 兄弟）。
  不改它指向的**本地库器件文档**（那一改要重写库文档，且 1k 兄弟的真 C 号离线无法核实，
  编一个就是造谣）—— 详见报告末"已知局限"。
- **V3**：把 V3 那根线**已有的空 `NET` 标签**改写成 `VCC`（原理图里"这张网叫 VCC"正是这样表达的）。
  不动走线、不删 C1 —— C1 因此变成 VCC 的退耦电容，正是 3.3V 模式参考设计的样子。

## 三、必须让 oracle 定的一件事：`v3-decap-missing` 是**静默**的

删掉 C1 之后，`decap-required-caps` 在这块板上**什么都不报**（`det=0/1`），两块板的规则输出逐条相同：

| 检查点 | 基底 | 变体 | 原因 |
|---|---|---|---|
| U1 pin4（V3） | OK | OK | 3.3V 模式下 V3 只需挂在 VCC 上（事实记录 `mode: 5V` 的电容要求在 3.3V 网不适用） |
| U1 pin16（VCC） | OK | OK | 该网需要的 0.1uF 由 **C9（2.2uF）**满足；C1 在与不在都不影响 |

⇒ **不是规则 bug，也不是 harness bug**：CH340 的 V3 电容本来就是 5V 模式的要求；在这块板上，
"删 C1"这件事对规则不可见。附带实测：**本板任何"单颗电容被删"都不会触发该规则**——VCC 网上有
C1/C6/C7/C9 四颗可确定值的电容，规则取**最大**那颗（C9 2.2uF）比对所需值，"无电容/容值不足"
两个分支都只有在**成组删除**时才可达。

**两个处置选项待裁**（我不自行改道）：
1. **退役 #1**（与 #6 同样处理）：从表里移除，并在 011e 记明"缺失退耦"这条路径的覆盖靠
   `decap-required-caps` 的合成 model 单测（011d 已有），不靠本板；
2. **重新界定 #1**：把注入改为"**删掉 C6**（U1 pin16 需要的那颗 0.1uF）"并**同时**让基底的
   V3 修复顺手去掉 C1（3.3V 板不需要那颗 5V 模式电容），这样 VCC 网上只剩 C6 是唯一可满足项，
   删除即触发。选项 2 需要你签一条新提案（改的是"注入什么"，不是实现细节）。

## 四、(d) `led-overcurrent` 已移除

表、`BUILDERS`、两个文件全部清掉；测试 `test_the_led_overcurrent_proposal_is_gone` 钉住。

## 五、(a) 终裁已写入标注集

黄金集两条 defect 的 `note` 末尾各加一段 `FINAL RULING 2026-09-19`：U3 那条写明"value 对、MPN 错，
已在 fixed-base 修正"；U1 那条写明"正确接法是 V3 短接 VCC，已在 fixed-base 修正"。

## 六、本轮抓到的三个真问题（都已修）

1. **`--check` 曾是"先写后比"，会把突变态变成新基线**。原实现先 `generate()` 覆写落盘产物、
   再比对，于是一旦某次变异把产物写成突变态，之后每次 check 都"一致通过"——变异 M1 因此**假存活**。
   现已改为**构建到仓内 scratch（`.tmp_variant_check`）只做读比对**，并新增
   `test_check_reports_drift_without_rewriting_the_fixture` 钉住"守卫必须只读"。
2. **网名标签先到先得**：每根线本来就带一条（多为空值）`NET` 标签，解析器取**第一条**——
   我第一版是**新增**一条 `"VCC"` 标签，结果被那条空标签遮住，基底依旧违反（网数 13 未变）。
   正解是**改写那条空记录**。教训：给一个已有多值/有默认的字段"加一条"，要先问"谁先被读到"。
3. **黄金集里有一个重复的 JSON 键**（U1 那条 defect 的 `severity` 出现两次）。JSON 容忍重复键、
   loader 取后者，所以功能上无害，但它让"规范化重写"变成一次隐性改动。已顺手规范化（写前先自检
   "重新序列化 == 原文"，只在差异恰好是那一行时才允许重写）。

## 七、验证

| 项 | 结果 |
|---|---|
| pytest | **1043 passed**（基线 1031，+12；净增 11 条 + 1 条只读守卫） |
| connector / tsc | **187 / 0 fail**，tsc 干净（零 TS 改动） |
| 变异验证 | **6 个全 CAUGHT**，生成器与 14 个产物逐字节还原 |
| 确定性 | `--check`：7 块板**及其标注集**重建逐字节一致 |

变异清单：①V3 标签不再命名；②U3 的 MPN 修正变空操作；③变体改从 golden 派生；④门闩不再拒绝未签项；
⑤基底标注集把黄金的两条 defect 也抄进来；⑥**把已落盘的基底换成 golden**（产物级，只有内容断言能咬住）。
前五个是生成器级，靠"重建逐字节比对"咬住 —— 这也正是本轮把 `--check` 的覆盖面**从 `.epro2` 扩到标注集**
的原因（否则第 ⑤ 个会静默漏过）。

## 八、已知局限（明说，不隐藏）

- 基底只改了 U3 **实例**的 MPN 声明；它指向的本地库器件文档里仍写着 `FRC0805J471` 与 470Ω 的
  `LCSC Part Name`。真正的设计修复是**换器件**（连带库文档与供应商字段），而 1k 兄弟的真 C 号
  需要联网核实（属 011b 的 catalog-select 职责）⇒ 不臆造。harness 读的是实例字段（
  `resolve_component_identity`：实例非空优先），所以规则层不受影响。
- 所有注入板仍是 **dev split**；holdout 划分归 011e。

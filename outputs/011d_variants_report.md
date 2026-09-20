# 注入缺陷板生成报告（011d §四 · 已签子集）

生成器：`reviewsets/injected/make_variants.py`（唯一写入者）
来源夹具：`tests/fixtures/ch340_golden.epro2`
签名：岳翔宇 2026-09-19（#1–#5、#7）；#6 原案已撤下，替换案待签

## 一、逐变体结果

| 变体 | 预期规则 | ref | 严重级 | det/hinted | 交叉 | 误报 | 基底板是否已触发 |
|---|---|---|---|---|---|---|---|
| `v3-decap-missing` | decap-required-caps | U1 | WARN | 1/1 | 0 | 0 | **1/1（不隔离）** |
| `duplicate-designator` | conn-duplicate-designators | R24 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ |
| `nc-pin-grounded` | conn-nc-and-must-connect | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ |
| `overvoltage-rail` | pwr-domain-vs-range | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ |
| `ldo-no-headroom` | path-ldo-dropout | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ |
| `value-mpn-mismatch` | param-value-mpn-match | U3 | WARN | 1/1 | 0 | 0 | **1/1（不隔离）** |
| `led-overcurrent` | param-led-current | LED1 | WARN | — | — | — | **未生成（未签）** |

每条变体都能被解析、预期规则精确命中一次且无误报；逐变体的完整报告在
`outputs/011d_variant_<id>.txt`。表中"误报"指**预期规则自身**的 fp 列——单条标注集的
板子上，基底板原有的其它发现会落进**其它规则**的 `fp-unexpl` 列，这是 harness 的设计
（"标注集就是该板的全部地面真值"），已在注释文件里写明。

## 二、两处必须让 oracle 知道的事

### 1. `v3-decap-missing` 与 `value-mpn-mismatch` 不是隔离实验

- **`v3-decap-missing`**：黄金板**本来**就违反 V3 接线（3.3V 模式下手册要求 V3 短接 VCC，
  板上没接），所以删掉 C1 之后规则报的是**同一件事**（`U1 pin4 must sit on net 'VCC'`），
  只是 V3 网因位号/网号重排由 `NET1` 变成 `NET12`。⇒ 该变体是**回归板**（证明电容消失、
  网号重排后规则仍报且配对不散），**不是**"缺失电容被抓到"的证明。
  要真正隔离这条路径，需要一块**先把 V3 正确接到 VCC**、再删 C1 的变体（新提案，待签）。
- **`value-mpn-mismatch`**：黄金板 U3 的 `1kΩ` 与 MPN `FRC0805J471`（470Ω）**本来就矛盾**
  （这正是 011c/011d 的 U3 defect）。本次编辑把矛盾拉大到 `2.2kΩ`，**同时**把 LED 限流
  从"跨阈值 UNKNOWN"推成"整体低于下限 VIOLATION"（`0.05–0.27 mA < 0.5 mA`）——一次编辑、
  两个后果。⇒ 该变体仍是有效回归板，但"单字段矛盾"这个说法只在**基底板本来一致**时才纯粹。

两条都写进了 `make_variants.py` 的 `oracle_note` 与 `tests/test_injected_variants.py::
test_two_variants_are_regression_boards_not_isolations`，不会被后读者误当成强证明。

### 2. 生成器门闩改为"已签子集"模式

- `--generate` 无参数 ⇒ 生成**全部已签**变体；指定 id ⇒ 只要其中有一个未签就整体拒绝（exit 2）；
- `--list` 打印每个提案的签名状态；`--check` 重建并逐字节比对已落盘产物；
- 未签的 `led-overcurrent` **不落任何文件**（测试钉住）。

## 三、harness 的一处真 bug（已修）

配对算法原来**边走 finding 边决定归属**，交叉匹配会**抢走**本该归给被提示规则的缺陷。
实测触发：`value-mpn-mismatch` 板上 `param-led-current` 的 finding 也提到 U3（它就是 LED 的
限流电阻），而它的规则在 `BUILTIN_RULES` 里排在 `param-value-mpn-match` 之前 ⇒ 缺陷被交叉
匹配吞掉，预期规则 det=0/1、跨匹配 1。

修法：**两趟配对**——第 1 趟只做"提示规则自身"的精确配对（先到先得留给正主），第 2 趟才做
交叉/例外/无解释。新增测试 `test_the_hinted_rule_wins_its_own_defect_even_when_another_rule_
names_the_ref_first` 钉住；变异 M1（把第 1 趟关掉）咬红。

## 四、验证

| 项 | 结果 |
|---|---|
| pytest | **1031 passed**（基线 1013，+18） |
| connector / tsc | 见交卷记录（零 TS 改动） |
| 变异验证 | **4 个全 CAUGHT**，源码与 12 个产物逐字节还原 |
| 生成确定性 | `--check` 逐字节一致（固定 DOS 时间戳 + sha1 派生记录 id） |

变异覆盖：①关掉两趟配对的第 1 趟 ⇒ 新增配对测试红；②门闩不再拒绝未签项 ⇒ 拒绝测试红；
③新记录追加到文件尾而非页区 ⇒ 逐字节一致性测试红（该变异**只**能被重建比对咬住——测试读的
是已落盘夹具，生成期缺陷必须靠重建来抓）；④记录 id 不再由变体 id 派生 ⇒ 同上。

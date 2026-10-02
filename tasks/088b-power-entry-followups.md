# 088b 电源入口跟进批：GND 出处符号 + 声明式支路顺序

主线 088 的跟进。088 离线半已落账（`967bb17`，全量 2940 passed），复验时发现三处与岳样板的可见偏差，
岳 2026-10-02 逐条裁决（原文在 `tasks/088b-power-entry-deltas-DRAFT.md` 末尾「裁决结果」节）：

1. **旗位置：保持现状**（挂入口侧轨脚），不照样板改 → **本批零代码改动**，只把 088 钉的两条
   「今天是这样、待裁决」测试注释转为「2026-10-02 岳裁决确认保持」。
2. **底轨加一个接地符号**：实体线保留，在**底轨远端**（背向连接器那端）放**一个** GND 电源符号，竖直。
3. **支路顺序声明化**：TVS/二极管不许乱排，TVS 必须最靠入口（要及时泄放电压尖峰）。语法不看
   位号/值/封装（053 §6 红线不动），由 PresentationSpec 新增可选 `modules[].branchOrder` 声明顺序。

## 〇、权威来源（先读，别猜）

- 088 实现：`src/boardwise/engines/grammar/power_entry.py`（绑定/约束/义务全在这）、
  `tests/test_088_power_entry.py`（36 条，含两条「待裁决」钉案）。
- 旗/符号发射：`src/boardwise/engines/drawcompiler.py` 的 069 旗规则（`_power_flag_pin`、
  `plan.power_symbols` 的产出处）——**公共路径，本批唯一允许碰它的方式就是加「只对本语法义务网
  生效」的支路，既有行为一条不许变**。
- spec 侧：`src/boardwise/core/presentationspec.py`（modules 的 schema 封闭性、可选字段先例）；
  可选字段纪律照 088 的 `SpecOpenInterface.part`（`core/circuitspec.py`）：缺省不写出、旧文档逐字节、
  spec_version 不升、未知键报错点名。
- 场景/预览：`tools/088_previews.py`、`outputs/088_preview/`（本批产物落 `outputs/088b_preview/`）。

## 一、GND 出处符号（裁决②）

- 独立编译 power-entry 模块时：gnd 轨是实体线（不变）+ **恰好一个** GND 电源符号，位置 = 底轨上
  **离 entry 的 gnd 脚最远**的那个成员脚（即「轨的远端」；side=left 时自动镜像到右端），竖直
  （rot∈{0,180}，与 069 旗的朝向纪律一致）。
- +24V 旗不动（仍在入口侧轨脚，裁决①）。
- **机制自决，但 contract 钉死**：触发必须 scoped 到「本语法义务的 gnd 网」，既有 053b（21）+
  056（18）场景哈希零移动是硬约束；选了什么机制、为什么最小，写进交卷报告。候选方向（可另提）：
  新义务 kind（词汇表变更，要同步 architecture.md 与注册面）/ spec 侧 hint / 编译器对既有义务
  组合的响应。禁止直改 `_power_flag_pin` 既有选点逻辑。
- **2026-10-02 最终裁决（主代理复验后补记，覆盖上面这段的"scoped"读法）**：`gnd-outlet` 义务
  由语法**每次绑定都发，无门控**。执行代理第一版为保住 088 既有断言，把义务门控在"presentation
  声明了模块"上（实测：去掉门控会让 088 的 4 条断言转红，见 `evidence/088b/mutation_M1.txt`
  的第一版）；主代理复验裁定**收回该门控**——岳的原话「加一个接地符号」没有"声明模块才加"这个
  前提，而 088 的模块级场景（他的样板）恰恰不声明模块，门控等于没执行裁决。随之 088 的 4 条
  断言按裁决改写（那是它自己钉的"今天是这样、待裁决"），`outputs/088_preview/` 相应变几张。
  053b/056 的零移动仍然成立（别的语法不发这条 kind，实测复核）。
- 页级（pagecompiler）行为：先实测。若页级 GND 已走 069 旗（088 场景 10 钉的就是旗），模块内
  出处符号在页级出不出、怎么出，实测后钉测试写理由；**不许为了页级一致性改动 069 v3 既有行为**。

## 二、声明式支路顺序（裁决③）

- `PresentationSpec.modules[].branchOrder`: optional `list[str]`，从**入口端往远**排列支路位号，
  如 `["D1", "C115", "C116"]` → D1 最靠入口。缺省 = 088 现状（位号字典序），旧文档逐字节不变。
- 校验（措辞钉测试）：未知位号 / 重复位号 → spec 报错点名；位号不是本模块 shunt（比如把 entry
  或别模块的件写进来）→ 语法绑定拒绝点名；只写了一部分支路 → 未点名的按位号序接在已声明的后面
  （还是直接拒绝？实测哪种更不易误导，钉一条理由）。
- 语法消费：按声明顺序在相邻支路间发 left-of/right-of 约束链（side=left 镜像）；与 entry↔shunt
  的既有约束不冲突。`test_the_grammar_module_carries_no_scenario_specific_constant` 不许破：
  顺序来自文档，不许在语法里写死任何位号。
- 模型怎么知道哪颗是 TVS：写 PresentationSpec 的模型读得到 CircuitSpec 的值/料号（SMCJ28CA），
  意图由它声明——这句话写进 `docs/schematic-conventions.md` 新条目（见 §四）。

## 三、场景与测试

进 `tests/test_088b_followups.py`（新文件；088 既有 36 条只许动两条注释，断言一字不变）：

1. 样板 + branchOrder=[D1 在先] → 从入口往远 = D1、C115、C116；GND 符号恰一个在远端脚、竖直；
   可读性零硬违规。
2. 镜像（side=left）：顺序与 GND 符号位置同步镜像。
3. 缺省 branchOrder → 与 088 现状逐位一致（回归钉）。
4. branchOrder 校验三态（未知/重复/非 shunt）措辞。
5. GND 符号唯一性：多支路（4 颗）也只有一个；+24V 旗仍在入口侧、数量不变。
6. 页级实测一条（机制怎么选就钉什么样的页级行为）。
7. spec 封闭性：branchOrder 未知键/旧文档回读逐字节。

## 四、文档同步（随代码同批，不后补）

- `tasks/088-power-entry-grammar.md` §七：三处「待岳定」更新为裁决结果（①保持现状 ②③ 本批落地）。
- `docs/schematic-conventions.md`：新增两条画法裁决——「电源入口底轨要有且只有一个 GND 出处符号
  （远端）」「泄放类器件（TVS/二极管）最靠入口，顺序经 branchOrder 声明、语法不看器件身份」。
- `docs/architecture.md`：若 §一选了新义务 kind 或 spec 词汇变化，同步。

## 五、验收与纪律（同 088，逐项交证据）

- 全量 pytest 绿（基线 **2940**），必带 `--basetemp=.tmp_pt_home`；connector/daemon/dsh 零改动；
  纯离线，不碰 bridge/真机。
- 场景哈希：053b 21 + 056 18 零移动（跑 `evidence/088/scene_hash_check.sh` 同款流程，证据落
  `evidence/088b/`）；088 自己的 14 张预览允许变（②③ 就是改它们），逐张列「变/不变」清单。
- 预览两遍跑 byte-identical（确定性），产物 `outputs/088b_preview/`。
- 变异 ≥2 组（②机制一组、③顺序一组），cp+sha256 还原，禁 sed 禁 git apply。
- 不动 git、不写 PROGRESS；交卷报告=自决项清单+机制实测结论+每场景候选数+「变/不变」清单。

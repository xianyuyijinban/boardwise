# 088：第四种画法语法 `power-entry`——电源入口模块（岳截图样板）

主线按 052 路线图推进；国庆视频死线 2026-10-07。本批只做**离线半**：语法 + 编译器接入 + 场景 + SVG 预览。真机落图是下一批（089）。

**样板**（岳 2026-10-01 聊天里贴的 24V 输入截图，逐条转述，无文件）：
连接器 CN1（XT30PW-M，两脚）在**右端**；顶轨 +24V、底轨 GND 各一条**实体横线**；
D1（SMCJ28CA TVS）、C115、C116（330µF 电解，CAP-TH_BD10.0-P5.00）三条两脚支路从顶轨**下垂**到底轨，
支路在两条轨之间竖放；**+24V 电源旗在顶轨左端、GND 符号在底轨左端**（轨的另一端终结于连接器）；
位号/容值文字在各支路左侧，不压线。从连接器往左的支路顺序：TVS 最靠入口，然后电容。

## 〇、权威来源（先读，别猜）

- 词汇表唯一权威：`engines/grammar/base.py` 模块 docstring（约束/义务 kind、四分类、角色是脚集三条性质）。
- 最近邻实现：`engines/grammar/rc_lowpass.py`（并联支路 + 主干，本语法与它的差别=没有串联件、多一条「实体总线」义务）。
- 注册面：`engines/grammar/__init__.py`（NAMES/_CLASSES/ROLES_BY_GRAMMAR）+ `core/presentationspec.py:112 GRAMMARS`。
- 编译器消费侧：`engines/drawcompiler.py`（约束投票/义务消费/069 旗规则所在）、`engines/pagecompiler.py` 的 `_net_style`（069 v3 mainPath 例外）。
- 场景/测试先例：`tests/test_053b_grammar.py`、`tests/test_053b_drawcompiler.py`（12 场景 9 过 3 拒计数与既有断言**一字不许变**）。

## 一、绑定判据（结构性；不看位号前缀、不看值、不看封装名）

1. `rail` = class=power 的网，`gnd` = class=gnd 的网；各缺一 → `facts-missing`（照 rc 的措辞模式点名该写哪）。
2. `entry`（连接器）**不能纯拓扑推导**（并联支路与连接器在图上同构）。事实通道：给 `core/circuitspec.py::SpecOpenInterface` 加**可选**字段 `part: str = ""`——「这个开放接口由哪颗连接器件实体化」。rail 网的 openInterfaces 条目 direction ∈ {input, source} 且带 part → 该 part 即 entry。
   - rail 无 openInterfaces 或 part 为空 → `facts-missing`：「which connector feeds the rail — state it in openInterfaces[].part」。
   - part 指向不存在的器件 / 该器件不是跨 rail↔gnd 的两脚件 → `circuit-invalid` 点名。
   - 序列化/反序列化/哈希：可选字段缺省不写出（旧文档逐字节不变），schema 封闭性不破（未知键照拒，这个新键登记进白名单）。spec_version 不升（纯可选增量）。
3. `shunt` = 其余每颗跨 rail↔gnd 的两脚件（TVS、体电容同构，语法不区分——**支路顺序不在本语法承诺里**，理由见 §五遗留）。
4. provenance 取最弱（照 rc）；同脚跨网/短路由 CircuitSpec 规范化层早已拒，不重复。

角色表：`ROLES = ("entry", "shunt", "rail", "gnd")`，语法名 `power-entry`。

## 二、约束与义务（**只许用现有 kind**；真不够再按 §四升级流程）

- `same-row`（entry, 每个 shunt）：所有件的 rail 侧脚落在顶轨线上，支路体垂在轨下（reason 写明哪端，照 rc 模式）。
- `same-row` 同构于底轨由各件 gnd 侧脚保证——若编译器靠 same-row 单轴已够，不重复声明；实测不够再加（交卷说明）。
- entry 在轨的输入端端头：先看 `left-of`/`right-of` 语义能否承载（它们的定义是「电源侧在左/右时 subject 在电源侧」，对本模块语义牵强）。**若牵强，允许新增一个 kind `at-end`**（subject 终结该 row 的由 sidePreferences.input 指明的那一端），走 §四流程。
- `near`（shunt, entry)：支路属于这条轨的局部拓扑，不跨模块。
- 义务 `direct-wire`（rail 全体成员的链 + gnd 全体成员的链）：**轨是实体总线**，与 069 全旗风格的差别就在这句话——端头旗由编译器 069③ 规则照常出，但轨线本体不许被拆成纯旗标点接。与 `_net_style`/`_is_bus` 的交互**先实测**（E1 场景编译出来的轨到底是线还是旗点），若电源网默认被拆旗，本语法的 direct-wire 义务必须压过它（最小侵入；裁决理由写进交卷报告）。
- 义务 `uniform-gnd`：模块内地表达统一。
- 义务 `owned-branch`（rail 网）：每条支路读起来属于这条轨。

## 三、注册与发现性

- `__init__.py` 三处注册 + `presentationspec.py:112 GRAMMARS` 加 `power-entry`（spec 字面量与实现名同串）。
- 语法模块 docstring 按 rc/ldo 格式：053 风格表格、绑定判据、约束逐条理由。
- `docs/architecture.md` 的 grammar 条目补一句（四种语法）。
- README 不动（路线图行的「分压/RC/LDO」在下一批真机落成后一起改成四种——本批先不动，防半成品写进门面）。

## 四、新增 kind 的升级流程（仅当 §二判定需要 `at-end`）

先在 `base.py` docstring 词汇表写定义（唯一权威），再进 `CONSTRAINT_KINDS`，再让编译器投票/消费侧认识它。三步缺一不收。若发现编译器对既有 kind 的消费也要改动才能承载本语法——**停下来申报**，不许顺手改编译器公共路径语义。

## 五、场景（全离线，进 `tests/` 新文件；SVG 预览落 `outputs/088_preview/`）

1. **岳样板**：entry + TVS + 2×330µF，sidePreferences.input=right → entry 右端、轨实体线、三支路下垂、+24V/GND 旗在左端且竖直（rot∈{0,180}）、文字不压线。可读性检查器零硬违规。
2. 镜像：input=left → 全图左右翻转，关系不变。
3. 最小：entry + 1 电容。
4. 多 shunt：entry + TVS + 3 电容（支路数弹性）。
5. rail 网无 openInterfaces/part → facts-missing，措辞钉死。
6. entry part 不跨 rail↔gnd / 不存在 → circuit-invalid 点名。
7. 无 power 或无 gnd class → facts-missing（两个各一条）。
8. 长文字（位号+容值长串）+ 大体格电解符号：间距自适应，文字不压线不穿体。
9. 窄区域 → layout-unsat 如实拒绝（报实测尺寸+建议），不挤压字。
10. **页级集成**：本模块 + 一个分压模块同页（pagecompiler），rail 标 mainPath 时实体线保留、GND 跨模块仍走旗（069 v3 行为不回归）。

场景哈希申报制照旧：本批新增场景之外，**既有 24+8 场景哈希零移动**是硬约束。

## 六、验收与纪律

- 测试基线：当前全量 **2904 passed**，本批只增不减；`--basetemp=.tmp_pt_home` 必带。
- 变异 ≥2 组（语法绑定判据/轨实体线义务各至少一组），cp+sha256 还原，禁 sed 禁 git apply。
- connector/daemon/dsh 零改动。
- 交卷报告：自决项清单、§二 direct-wire 与 069 旗规则的实测结论、每个场景的候选数与拒绝分类、预览文件清单。
- 主代理复验项：diff 亲审、全量亲跑、SVG 预览亲看（场景 1 必须像岳那张截图）。

## 七、复验裁决（2026-10-02 主代理亲验后补记 + 岳裁决回填）

复验通过落账：全量 **2940 passed**（2904+36）亲跑复核；既有 053b 21 + 056 18 场景哈希零移动亲跑
`scene_hash_check.sh` 复核；变异 4 组 CAUGHT + sha256 还原 YES；场景 1/场景 10 SVG 主代理亲看，
画法成立（入口终结右端、两轨实体横线、支路下垂、文字不压线；页级 rail 主线实体线、GND 走旗）。

**§一/§五.1 明文样板的两处偏差已由岳 2026-10-02 逐条裁决**（原文
`tasks/088b-power-entry-deltas-DRAFT.md` 末尾「裁决结果」，执行任务书
`tasks/088b-power-entry-followups.md`）：

1. **旗位置：保持现状**（挂入口侧轨脚，`PWR-+24V @ (-50, 65)` rot=0）。
   岳裁决 = **不改**；本条落成 088b 的两条注释更新（`test_088_power_entry.py` 场景 1 的
   文档串与 GND 断言上方，转为「2026-10-02 岳裁决确认保持」），**断言一字未动**。
2. **底轨 GND 符号：加**（实体线保留）。088b 落成 `gnd-outlet` 义务（`engines/grammar/base.py`
   词汇表第五个 kind）：语法**每次绑定都发**（无条件），编译器按 `sidePreferences.input`
   找出底轨远端、在那儿挂**恰好一个**竖直符号（`rot ∈ {0,180}`）。本文件场景 1 的两条断言
   （「旗在入口侧」保持、「底轨没有符号」改成「恰一个在远端、竖直」）与 `test_the_obligations_...`
   的义务清单按裁决②更新——**这是"今天是这样、待裁决"的钉案，裁决到了，断言=执行裁决**；
   页级 069 v3 行为未动（GND 仍走旗）。
   *过程注*：088b 第一版把这条义务门控在"声明了模块"上（为保住本文件的图逐字节不变），
   主代理 2026-10-02 复验裁定**收回该门控**（岳的样板本来就不声明模块，门控等于没执行裁决）；
   本文件与 `outputs/088_preview/` 的相应变化即由此而来。

实测两处**跨模块既有矛盾**（非本批契约，测试已各自钉一条实测，修法属公共路径）。
**096（页级两缺陷修复，`tasks/096-page-two-defects.md`）已修**：两条钉案改写为钉修复后行为，
原实测记录按 096 §三要求**原样保留**在测试 docstring 里（历史价值）。

a) `pagecompiler._net_style` 的 mainPath 例外与 `readability._check_main_paths` 的 `_is_bus` 判据
不一致——4 成员宽轨标 mainPath 时模块各自能编译、页级 0 候选（089 真机半要避开：宽轨不标 mainPath）。
**096 修法**：判据抽成单一出处 `core.presentationspec.main_path_wire`，两处同问（069 v3 例外一体
适用；**阈值没有被抬高，是被拿掉了**）。修后 4 成员宽轨页级有候选、rail 仍一条实体线、GND 仍走旗——
**089 真机半"宽轨不标 mainPath"的限制因此解除**。
b) `_anchor_to_page` 页边距+格点吸附 vs `_overflow` 1e-6 容差——1170×825 声明页面对岳样板 0 候选，
不声明页面（page_box=None）正常。**096 修法**：吸附改为**朝页内**（左/下边 ceil、右/上边 floor），
`_overflow` 的 1e-6 容差一个字没动（页边是作者的约束，格点是编译器的便利）。修后岳样板在
1170×825 上有候选且全部落回页边内。096 同时实测到一条**遗留**：`_annotation_allowance` 对这张图
的横向留白估短 4 单位，内吸带来的格点增量恰好吃掉它——估算仍是估算，详见 096 交卷报告遗留项。

支路顺序（样板「TVS 最靠入口」）在 088 里不是语法承诺（三支路同构、053 §6 禁场景常量），
落图按位号排。**岳 2026-10-02 裁决③ = 升级成承诺**：顺序由 `PresentationSpec.modules[].branchOrder`
声明、语法只执行与核验；088b 落地（本批）。缺省仍是位号序，所以本批的 088 图不变。

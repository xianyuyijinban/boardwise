# 055：画图编译器收尾批——G1 文法角色脚 / G2 写 Value / G3 场景合规 / G6 文案

054 C1 落图后遗留的四个小而独立的 correctness 缺口（出处：`tasks/054-draw-stage-c-editor.md` §九遗留 G1/G2/G3/G6）。
G4（findings 工程级合并语义）与 G5（写入后拒绝的 rollback）**不在本批**，归 C2 任务书。
主代理已裁决的方向在每项开头写明，不许推翻；实现选型（怎么改最小）由执行者定，自决项交卷时列出。

## 一、G1：`ldo` 文法重复角色脚与 `nc[]` 通路

**裁决**：修文法，两条都认——(a) 某角色**任一**同角色脚是 net 成员即算该角色已连；(b) 角色脚显式写进 `nc[]` 即算"已显式处理"，不再报 "neither a net member nor an explicit nc"。

- 现状（054 实测）：真机 AMS1117 符号（C6186/C351785/C5205141 同族）右侧有**重复 VOUT**（4 号脚，与 2 号 VOUT 内部相连）。把 4 号连上网、2 号写进 `nc[]`，文法仍报 `VOUT pin (number='2') … neither a net member nor an explicit nc`——`role_pins` 取 id 排序第一个 VOUT 且 `profile_pin_for` 只认 net 成员。编译器自己的失败文案写着 "a compiler bug — report it"。
- 边界：`engines/drawcompiler.py` 与 `engines/grammar/ldo.py`（或角色判定实际所在的文件）可动；**12 场景 9 过 3 拒的计数与分类一字不许变**（`tests/test_053b_drawcompiler.py` 全绿是硬约束）；`engines/grammar/base.py` docstring 词汇表仍是唯一权威，若角色判定语义有措辞变化先改词汇表再改代码。
- 必须新增回归：AMS1117 形状的 SymbolProfile（VIN×1 + VOUT×2 + GND×1）——重复脚连网 + 主脚 nc、主脚连网 + 重复脚 nc、两脚都连（同名网）三种形态各自应有确定、合理的结果（出图或点名拒绝，绝不报 "compiler bug"）。
- `draw compile` 对该形状默认侧（in 左 out 右）仍无解是**合法结果**（单侧出脚的几何约束），不许为了出图放松布局约束。

## 二、G2：`draw apply` 写器件 Value

**裁决**：写。CircuitSpec 里的值就是设计意图，画到画布上就该落在器件属性里；MPN 是料号不是设计值（与 reviewsets 17 颗器件的裁决一致：设计值为准）。

- 通道：既有 `sch.set_component_attribute`（016 已用），**零新增 connector 动作**。
- 范围：只写本模块放置的器件（plan 自己 parts 列表），范围外一个属性不动——沿用 036 范围守卫。
- ChangePlan 声明：value 写进 plan（`draw-module` kind 的 parts 载荷扩展），apply 时逐件写入并**回读核对**（写后读回不符 = postcondition 失败，按既有双证框架入账）。
- 顺序：放件 → 写 Value → 引脚回读 → 走线（Value 写入不影响几何，顺序自决但交卷说明理由）。
- 空值处理：CircuitSpec 无 value 的器件不写、不报（不是错误）；有 value 写不进才报。
- 真机抽验：test 工程新页跑一次带值的分压 apply，回读两颗电阻 Value 与 plan 一致；渲染图里值可见。遵守 R1–R3（先 `bridge status` + `doc.list` 逐字对焦 test；禁地名单见 SKILL）。
- 顺手验证：写 Value 后 `decap-required-caps` 对 LDO 模块的判定是否仍只靠 MPN EIA 码（预期是——本批不改规则，只记录实测行为）。

## 三、G3：053 LDO 场景与本仓 facts 对齐

**裁决**：场景合规化——`tests/test_053b_drawcompiler.py::ldo_circuit`（及同名变体场景）输出电容 100n → **22µF**，让示例电路在真机也能过本仓 `decap-required-caps`（facts 要求 AMS1117 输出 ≥22µF）。

- 只允许改场景输入值与因值而变的期望文本；**9 过 3 拒计数、其余场景、快照几何不许变**（值不进几何断言的话应零波及；若有波及，停下来申报，不许顺手改断言）。
- 若某场景**故意**用不合规值测拒绝路径，改值前确认该场景的测试目的不受影响；目的冲突时保留原值并在场景注释写明"示例电路不追求合规"（两条路选一条，交卷说明）。

## 四、G6：register 文案清扫（零行为变化）

054 注册表补齐后残留的旧口径文案，改成与 register 实际口径一致：

- `src/boardwise/engines/review_eval.py:1064` 文本报告头 "M3's live repair results"。
- `src/boardwise/engines/review_eval.py:866–879` JSON `fix_success.note`（"M3's … five slices' task books"）。
- `src/boardwise/cli.py:3861–3865` 注释 "five slices' task books"。
- 改法：不再点名 M3/五片，改为"注册表登记的六种 change kind（五个 M3 片 + 054 画图）"之类**与实现一致且未来加 kind 不必再改**的措辞。测试里若断言了旧文案子串，同步改断言（先 grep 确认）。

## 五、复验纪律

- 定向 pytest 用 `--basetemp=.tmp_pt_74`；全量归主代理。
- 变异 ≥2 组（建议：G1 的"任一角色脚已连"退恒真 → 红；G2 的 value 回读核对退恒真 → 红），cp 备份 + sha256 还原，禁 `git checkout`。
- 零 git 操作；不碰 `README.md`、`PROGRESS.md`、reviewsets、tests/fixtures 既有夹具（G3 改的是 `test_053b_drawcompiler.py` 内联场景，不是 fixtures 目录）。
- dsh 工具面零新增；connector 零新增（G2 用既有动作）。
- 真机只碰 test；动手前 R1 对焦。
- eval holdout 59/59 双 1.00 红线（G6 动了 `review_eval.py` 文案——报告文本变化若影响 eval 输出比对，申报；预期 fix_success 段措辞变化不进 holdout 计分）。

## 六、交卷要求

- 每 G 一节：改了什么（文件+sha256(12) 前后）、自决项、测试证据（定向计数）。
- G1 附三种重复脚形态的 `draw compile` 实际输出摘录。
- G2 附真机抽验的 plan/apply 报告要点（Value 回读一致、范围外零写、渲染图路径）与 decap 实测记录。
- 变异组与还原哈希。
- 遗留：本批没收口的，写明归谁。

# 081：pintable gate 3 的 role≠球名（#48，a+b1 混合——岳已拍板）

载体 issue：#48（岳亲报，带复现探针与方向分析）。080 批 4 把 gate 3 升成引脚级时引入了一句
不普遍成立的前提（`pintable_check.py` docstring：「A port's `role` and a pin table's `number`
are both the ball's name」）——它只对球名 role 的测试夹具成立，本仓 `blocklib/blocks/*.json`
的接口 role 全是功能名（GND/VCC/RX/TX），接到 pintable 上会把**完全正确的板**报 defect。

**修法（岳拍板 a+b1 混合）**：

- **a（兜底，必选）**：MCU 端口的球不可知时（role 非球名形、又无 ball 字段），pin 级比对
  ** withhold **——给 NOTE 说明「该端口无球名证据，未做引脚级比对」，**永不许出 DEFECT**，
  方向 2 的 OPEN_QUESTION 措辞也不许声称「firmware 没用过这颗球」。
- **b1（证据通道）**：`BlockPort` 加**可选** `ball` 字段（`"ball": "PA5"`），
  `load_block_template` 校验球名形（ malformed 报点名字段的 BlockError），序列化 round-trip
  不丢。gate 3 有 ball 用 ball、无 ball 但 role 本身是球名形（`is_port_pin`）用 role、
  两者都无 → 走 a 的 withhold。

## 1. 现状落点（主代理已核）

- `engines/pintable_check.py:285-352`：方向 1 `spec_mcu_roles`（net→role 集）+ `unwired =
  set(pins) - roles`（:328）——pins 是球名（PA5）、roles 可能是功能名（SPI_SCK），差集恒非空
  → 假 DEFECT。方向 2（:353-396）：`elsewhere` 用 `role in net_of_pin`（:362）拿功能名查球名表
  恒不命中 → 真「一球两网」漏报、firmware 已用的球被误报 OPEN_QUESTION。
- `core/blocks.py`：`BlockPort`（:255-:330，dataclass，字段 role/net/net_class/position/
  direction/voltage/level）；端口装载校验在 :709-768（`_check_keys` 白名单 :716、role 必填
  去重、net_class 枚举）；序列化出口 :900 起（`"role": port.role, …`）。
- 球名判据已有两抄：`core/pintable.py:80` `_PORT_PIN = ^P[A-Z]\d{1,2}$`（:130 `is_port_pin`
  公开判定）与 `core/architecture.py:191` `^P[A-H]\d{1,2}(?![0-9])`（**两抄不一致**——边界外
  发现，只报不修）。本批 blocks.py 需要球名判定时**复用 pintable 的 `is_port_pin`**（先查
  import 方向无环；若有环再议，**不许造第三抄**——071「一个判据一个实现」）。
- remap 说明（写进 docstring/文档）：模板符号画的是一个具体封装，`ball` 是「这个端口在这块
  模板上就是这颗球」；功能可复位的 MCU，块作者要么填模板所画封装的球、要么不填走 withhold。

## 2. 硬规则（范围钉死）

- 只许动：`engines/pintable_check.py`（gate 3 + docstring 错误前提删除）、
  `core/blocks.py`（ball 字段+装载校验+序列化）、`tests/test_pintable.py` 与
  `tests/test_blocks.py`（或新 test_081 文件）、`docs/pintable.md`、`docs/blocks.md`。
- 不碰：`core/pintable.py` 与 `core/architecture.py` 的两抄 `_PORT_PIN`（不一致申报即可）、
  `blocklib/blocks/*.json` 既有五块（不加 ball——它们不是 MCU 块，gate 不适用）、
  `cross_check`（firmware↔.ioc 两边都是球名，不受影响）、`tests/fixtures/` 既有夹具。
- shipped 回归：智能药箱 pintable 无 spec、ch340g spec 不过 pintable gate——改动后两者
  行为**逐字不变**（实测对照）。

## 3. 验收契约

1. **#48 复现形**（功能名 role）：MCU 块端口 `role='SPI_SCK'`（无 ball）接 net `SPI1_SCK`，
   firmware 如实 `PA5/SPI_SCK/SPI1_SCK` → **零 DEFECT、零假 OPEN_QUESTION**，出一条 NOTE
   点名「端口 SPI_SCK 无球名证据，引脚级比对未做」；`matched_nets` 不灌水（不计 +1）。
2. **#35 复现形不回归**（球名 role）：批 4 的 `role='PA3'/'PB6'` 夹具行为逐字不变，
   错球板照报 DEFECT。
3. **ball 字段路径**：新夹具 MCU 块 `role='SPI_SCK', ball='PA5'`——
   firmware PA5 在正确的网 → 计 matched；firmware PB6 上该网 → 方向 1 DEFECT；
   spec 把该口接 net X 而 firmware 把 PA5 放 net Y → 方向 2 「一球两网」DEFECT
   （经 ball 字段打通，不再恒不命中）。
4. **装载校验**：`"ball": "SPI_SCK"`（非球名形）→ BlockError 点名 `<spot>.ball`；
   `ball` 缺省 → None 不报错；序列化写出再读回逐字一致（round-trip 测试）。
5. 混合形：同一块三个端口分别「ball 字段」「球名 role」「功能名 role 无 ball」——
   前两个参与比对、第三个 withhold，NOTE 点名第三个。

## 4. 纪律

- pytest 必带 `--basetemp=.tmp_pt_home`；全量主跑一遍（当前基线 **2714 passed**）。
- 零 git 写操作；不写 PROGRESS.md；Edit 或字节级脚本（禁 sed -i，CRLF）。
- 变异 ≥2 组（建议：withhold 分支失效=功能名 role 照旧进差集 / ball 字段装载校验失效），
  备份 `.tmp_mut/`（禁 basetemp 内）、字节级 replace、`cp` 还原+sha256，证据落 `evidence/081/`；
  变异脚本还原进 finally、stdout 防 GBK（078 坑）；**弱变异要换证人加强**（079 坑：
  lookbehind 弱化曾被既有证人的其他形状保命，主代理复验会带自己的变异）。
- 纯离线批：不重启 daemon、不碰真机。

## 5. 交卷

改动文件 sha256 before/after；测试账目（新/改逐条）；验收契约 5 条逐条实证；变异证据；
`BlockPort` 全部构造点与 `port.ball` 全部消费点审计表；shipped 两 spec 行为对照；
边界外发现（两抄 `_PORT_PIN` 不一致等，只报）。

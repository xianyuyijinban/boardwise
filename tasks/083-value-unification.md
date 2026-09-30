# 083：值解析三处漏网统一（#51/#52/#53）

同一病根：**同一个量的解析/比较在仓里长了多份，都没委托 `rules/values.py`**（071 §2「一个判据一个实现」）。
三 issue 全文在 `.tmp_mut/issue51.md` / `.tmp_mut/issue52.md` / `.tmp_mut/issue53.md`（先读），本任务书是裁决后的施工图。

## 0. 分层约束（先读，决定 import 方式）

- `core/` 今天**从不** import `rules/`；反向（rules→core、engines→rules/core）合法。
  `rules/values.py` 本身只依赖 stdlib（math/re）。
- 所以 `core/compare.py` 与 `core/blocks.py` 消费 values.py 的两个解析器时，用 **081 先例的函数内延迟 import**
  （`from boardwise.rules.values import parse_resistance_ohms` 写在函数体内，注释点名防环理由——rules/__init__
   eager import 一串 rules 模块、它们回头 import core，模块级 import 会把 core 卷进环）。
- `engines/validate_spec.py` import rules 合法，正常模块级 import。
- **values.py 物理下移到 core 是更干净的终态，但 28 处 import 点 + shim 枚举是另一批的事**——本批不动，
  记边界外发现。

## 1. #51 compare.py 委托统一解析器

落点 `src/boardwise/core/compare.py:155-230`：删 `_QUANTITY_RE` / `_UNAMBIGUOUS_PREFIXES` / `_RESISTOR_R_RE` /
`_parse_quantity` 四件自造实现（先全仓 grep 确认无其他消费点，含 tests）。

`values_equal` 新语义（**逐字保住现有契约的两条**）：

1. 去空格后精确串等 → True（旧有）；
2. 大小写不敏感串等 → True（旧有，`10k` vs `10K`；这是 compare 的契约，bom 没有，别删）；
3. 两侧都解析得出**且 kind 相同**（resistance/capacitance 随数走——`100Ω`≠`100nF` 是 #39 的教训）→
   `math.isclose(rel_tol=1e-9)`（**不再是 `==`**：`100nF`=`1.0000000000000001e-07` vs `0.1uF`=`1e-07`）；
4. 其余 → False（多 token、小写 m 歧义、解析不出 = 退化字符串比对的拒绝语义，**别丢**——那是 005 的正经契约）。

解析委托：先 `parse_resistance_ohms` 出数 → ('resistance', v)，否则 `parse_capacitance_farads` → ('capacitance', v)，
否则 None（形状照 `engines/bom.py:201` `_quantity`，但**不要去 import bom**——core 引 engines 更糟；
bom 自己的 `_values_agree` 保持原样不动，它语义差一条大小写步、且 engines→rules 本就合法）。

模块 docstring 里「normalisation rules are fixed here on purpose」那段要改写：契约保留，实现委托，
点名 #51/#23/#39 与 071 §2。

## 2. #52 blocks.py 约束器委托

落点 `src/boardwise/core/blocks.py:85-119`：`_check_resistor`/`_check_capacitor` 改为委托
`parse_resistance_ohms`/`parse_capacitance_farads`（解析得出即通过），**保留**空值拒绝文案
（"is empty; a ... value is required"）与拒绝文案形状（"is not a ... value: %r"）。
`_FREQUENCY_RE` 不动（出界）。

**先发测量，后动手**：列一张发散矩阵——旧 `_RESISTOR_RE`/`_CAPACITOR_RE` 接受而 values.py 解析器拒收的写法
（重点嫌疑：裸 `'100R'` 尾 R、`'470Ω'`、`'2.2kΩ'`、裸 `'470'`、`'4R7'`）。矩阵落 `evidence/083/`。
- 合法行业写法若被解析器拒（如真有 `'100R'`）：**本批不改 values.py**（078/079 刚钉死），在 blocks.py
  留一条具名补充模式+注释点名理由（方向=不误收，缩紧是回归）；
-  `'abc'`/`''`/电容位写 `'5.1K'` 仍必须拒。

## 3. #53 power-tree 电压归一化

`rules/values.py` 新增 `parse_voltage_volts(text) -> float | None`（一个判据一个实现，注释点名 #53）：

- 收：`'3.3V'`/`'3.3'`/`'3.30V'`/`'3.3 V'`/`'5V'`/`'12V'` → 数字；**V 作小数点**的中缀 `'3V3'`→3.3、`'1V8'`→1.8
  （V 中缀是电压版的 R 中缀，portmeta 自己就写 `3V3`）；可选前导 `'+'`/`'-'`（`'+24V'`→24、'-12V'→-12——
  真实网名/轨电压带符号，拒了才是真 bug）；
- 拒：空、多 token、`'abc'`、`'3V3V'`、无数字；只拒不猜（`parse_***` 族同款 None 语义）。

`engines/validate_spec.py:979` 的 `port.voltage != source.voltage` 改为：

- 两侧都解析得出 → `math.isclose(rel_tol=1e-9)` 不等才 VIOLATION；
- 任一侧解析不出 → **退回旧字符串不等判定**（fail-closed 方向保住，怪写法行为不变）；
- Finding 的 message/evidence **保留原始拼写**（用户写的是啥就报啥），别替换成归一化后的数。

**消费点普查**（证据落盘）：全仓 grep `.voltage` 的**比较**用法——主代理已预扫：唯一字符串比较点就是
validate_spec.py:979（blocks.py:969 只是透传、facts.py 是从网名推断电压的另一机制不动）。
agent 须独立复核一遍并把结果写进交卷。

## 4. 测试（新文件 `tests/test_083_value_unification.py`，三节分钉）

- §#51：issue 验收表全钉（`4K7`≡`4700`/`4.7k`、`4u7`≡`4.7uF`、`2M2`≡`2.2M`、`0.1uF`≡`100nF`；
  `4K7` vs `4.8k` 不等；`'472M 1KV'` 多 token 退化字符串；`100Ω` vs `100nF` kind 不同不等）+
  一条 `compare_models` 端到端（golden vs candidate 只差拼写 → 无 value diff）；
- §#52：issue 验收形全钉（`4K7/1M0/2M2/4u7/2n2/5p1` 过；`abc`/空/`5.1K`当电容 拒）+
  **发散矩阵回归**（旧正则接受集逐条仍过，照 §2 实测矩阵写成参数化）；
- §#53：`parse_voltage_volts` 单元（收/拒两族）+ gate 级（`3V3` source vs `3.3V` sink 过、
  `5V` vs `5.0V` 过、`3.3V` vs `5V` 仍 VIOLATION、不可解析写法退回字符串语义）+
  portmeta 实景（`ch340_power_3v3` 的 `3V3` source + 写 `3.3V` 的 sink → 过）。
- 既有测试零改动绿；若某条既有断言因修复必须翻，逐条摆出来等主代理裁决，不许顺手改。

## 5. 纪律

- pytest 必带 `--basetemp=.tmp_pt_home`；全量主跑一遍（基线 **2749 passed**）。
- 零 git 写操作；不写 PROGRESS.md；Edit 或字节级脚本（禁 sed -i，CRLF）。
- 每处修复变异 ≥2 组（备份 `.tmp_mut/` 禁 basetemp 内、字节级 replace、cp 还原+sha256、还原进 finally、
  stdout 防 GBK；弱变异换证人加强），证据落 `evidence/083/`。
- 纯离线批：不重启 daemon、不碰真机。
- eval holdout 与本批无关（不动 rules 的 finding 逻辑），但 cli.py 的 compare 出口变了——跑一遍
  `outputs/` 无关、不用 eval；若 compare 有快照类测试变了要申报。

## 6. 交卷

改动文件 sha256 before/after；三 issue 各自的 before→after 行为表；§2 发散矩阵；§3 消费点普查结果；
变异证据（逐组：变异内容→哪条测试红→还原 sha256 YES）；全量 pytest 计数；边界外发现（只报）。

---

## 083 part 2 追加任务书（主代理裁决，2026-09-30 深夜）

**背景**：agent-124 施工时发现本任务书 §0 的分层前提错误——081 的函数内延迟 import 先例是 core→core
（同层），不是 core→rules；`tests/test_layer_rules.py`（006c 的可执行宪法）用 ast.walk 抓**一切**跨层
import，函数体内的一样抓（它的 docstring 明说就是为抓「藏在函数里的跨层导入」写的）。agent 拒绝了三条
变通路（importlib 藏导入 = 骗守卫、top 层注入全局 = 006c 记的绕过接缝、改 ALLOWED = 宪法变更需用户点头），
把 #51/#52 的完整实现留在 `evidence/083/pending_51_52/` 等裁决。**它是对的，裁决如下。**

**裁决：走 agent 的选项①——`rules/values.py` 物理下移到 `core/values.py`，原位置留转发 shim。**
分层箭头一寸不动：shim 在 rules 层 import core（合法方向），compare.py/blocks.py import core 兄弟模块
（同层合法，**模块级 import，不要延迟 import**——延迟是防环用的，同层无环可防）。宪法零改动。

### 施工要求

1. **`core/values.py` = 现 `rules/values.py` 的逐字节内容**（含本批新增的 `parse_voltage_volts`），
   只在模块 docstring 开头加一段迁徙记（083、#51/#52、071 §2、006c 箭头不动、shim 指针）。
2. **`rules/values.py` 重写为 shim**：`from boardwise.core.values import *` + 模块级 `__getattr__`
   （PEP 562）转发私有名——`tests/test_011d_rules.py` 直接 import `_without_leading_size` 这类私有名，
   星号导入拿不到，必须 `__getattr__` 兜底。docstring 写清「实现已下移 core.values，这里是兼容 shim，
   新代码请 import core.values」。
3. **import 面普查先行**：全仓（含 tests）grep `rules.values` / `.values import` / `rules import values`
   的每一个点名 import，列清单落 `evidence/083/import_surface.txt`；施工后逐名断言可 import
   （写进测试或探针脚本）。若有人 `from rules.values import *`，shim 需补 `__all__`。
4. compare.py / blocks.py 落 `evidence/083/pending_51_52/` 的既定实现，但 **lazy import 改成模块级
   sibling import**（`from .values import ...` / `from boardwise.core.values import ...`）。
   **禁用 `git apply`**（它把工作树写成 LF——agent 已踩过一次）；用 Edit/字节级脚本重新落。
5. 测试文件是**合并不是覆盖**：`tests/test_083_value_unification.py` 已有 §#53 的 56 条（已落盘），
   把 pending 的 §#51/§#52 两节（71 条）**追加合并**进去，合计 127 条。
6. values.py 正文逻辑**零改动**（078/079 钉死的锚点/符号行为一寸不动，搬迁是字节级的）。

### 验收

- 全量 pytest（必带 `--basetemp=.tmp_pt_home`）：**2749 + 127 = 2876 passed** 预期。
- `tests/test_layer_rules.py` 全绿（宪法不动）。
- import 面普查全通过；`from boardwise.rules.values import <每个历史名>` 逐一可达。
- 变异：#51/#52 每处 ≥2 组（备份 `.tmp_mut/`、字节级、还原 sha256 YES、进 finally、防 GBK；
  建议：values_equal 的 isclose 退回 `==`、kind 校验删除、blocks 委托删除、补充模式删除）。
- connector/dsh 树不动不跑；纯离线批，daemon/真机零触碰。

### 边界外发现（记入 PROGRESS，不修）

- `core/power_domains.py:45-48` 是**第四份电压语法**（`_V_FORM`/`_MN_FORM` 供 `voltage_from_net_name`
  从网名推电压，facts.py 消费），无长度上限无 `_finite` 守卫——字段不同（网名 vs 电压字段），
  收编另批。
- `_MID_LETTER_KINDS` 不能直接收编电压（`_without_leading_size` 剥尺寸码对轨电压是错语义，`1206V`
  会被误剥）——083 已在 `parse_voltage_volts` docstring 记明。
- 电压前缀（`5V5`/`3300mV`）未支持——解析器语法扩展另批。
- #51 落盘后 `engines/draw.py:1621` 的 draw 验收会**少报**假差异（方向=更少拦），落盘后看一眼。

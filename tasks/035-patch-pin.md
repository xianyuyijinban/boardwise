# 035 patch-pin：修单个引脚连接（M3 第 3 片）

## 背景与入口裁决

M3 顺序第 3 刀（016 改值 ✅ → 029 补件 ✅ → **patch-pin** → insert-subcircuit → move-block）。
主代理已盘完规则侧，入口定为 **`conn-nc-and-must-connect`**（`rules/facts.py:146`）——它是现有 15 条里
唯一天然产出"引脚级连接错误"的规则，且一条规则给出**三个修复形态**：

| 形态 | 规则发现（VIOLATION） | 修复 |
|---|---|---|
| **connect** | must_connect 脚悬空（net=None）→ 目标网 T | 接线：wire / power-flag（029 机制） |
| **disconnect** | NC 脚坐在网 N 上 | 摘除该脚的连接（删附着的线/网标） |
| **reconnect** | must_connect 脚坐在错网 N 上 → 应接 T | 断 N + 接 T（复合） |

不可修复形态（**不给 target**，029 先例）：mode-tagged 条件义务（无电压证据）、free-text 目标
（`target not in model.nets`）、任何 UNKNOWN。

`conn-usb-cc-pulldown` 已盘：脚悬空是 UNKNOWN、缺下拉电阻归 029 add-component、阻值错归 016——
**不需要 patch-pin，本批不碰**。

## 工作项

### 1. 规则侧（`rules/facts.py`）

- VIOLATION 行补 `FindingTarget`（schema 已有 `pin_refs`/`net_refs`/`expected_before`/`suggested_after`，
  016 立的格式）：
  - NC 方向：`component_ref`+`pin_refs=[pin]`+`net_refs=[当前网]`，`expected_before=当前网`，
    `suggested_after=""`（**空串 = 断开**，写入文档）。
  - must_connect：`pin_refs=[pin]`，`net_refs=[当前网?, 目标网]`（悬空时只有目标网），
    `expected_before=当前网或""`，`suggested_after=目标网`。
- UNKNOWN / mode-tagged / free-text 行**不给** target。

### 2. ChangePlan（`core/changeplan.py`）

- `SUPPORTED_KINDS` 加 `patch-pin`；`_LATER_KINDS` 摘除（拒绝文案同步）；`REPAIRABLE_RULES` 加
  `conn-nc-and-must-connect: patch-pin`（`cli.py:5554`）。
- plan payload（字段名实现定，但必须覆盖）：pin（designator+脚号）、`before_net`、
  `after_net`（空串=断开）、connect 机制（`wire`/`label`/`power-flag`，**判定函数复用 029 那套**：
  label 只在页面已用该名、power-flag 是唯一能凭空建轨的——029-d 红线）、disconnect 的附着物描述
  （见工作项 3）。
- 016/029 既有 JSON 一字不变（round-trip 测试仍绿是回归钉）。

### 3. 离线 plan/preview/apply（`cli.py` edit 系列 + 新 `engines/patchpin.py`）

- **connect**：复用 029 机制——`pin_points`/`wire_route`（强制正交）/`nearest_wire_point`/
  `landing_spot`/`power_flag_kind`；脚坐标真机来自 `sch.component_pins`。
- **disconnect（本片最危险处，写死纪律）**：
  - 附着物只认两种、且必须**画布实证**：端点**恰落在脚坐标**上的 wire 段（`wire_vertices`），
    或恰落在脚上的 netlabel；
  - 脚坐在贯穿线段中段（T 型）/ 附着物多于一个分不清 / 找不到附着物 → **拒绝，不猜**；
  - 删除动作用 connector 既有的删 wire/删 netlabel 能力——**第一天先核实动作目录里有没有**；
    没有删线动作就**停下来报主代理**，不许绕。
- 四保护沿用 016/029：页守卫 + 改前重读（脚当前网必须 == before_net，否则 stale exit 4）+
  范围差异恰为预期（connect +1 线或 +1 旗；disconnect −1 附着物；reconnect 复合）+
  回读网表判定（脚落 after_net / 从 before_net 消失；**范围外网表零差异**）+ 断连 unknown（exit 3）。
- 幂等：重复 apply = already_applied 零写入（幂等探测与规则判定同一函数，029 立的规矩）。

### 4. 测试与验收

- 离线（pytest）：三形态 plan/preview/apply 编排（活工程 export→parse 实证幂等）、歧义附着拒绝、
  mode-tagged/free-text 无 plan、016/029 round-trip 回归。
- 变异 ≥2（connect 幂等漏判 / disconnect 范围外误删）。
- 真机（**只碰 test/test2**，`--project/--instance` 显式寻址）：三形态各至少一次真成功 +
  幂等重放 + stale_before + 保存持久化（沿用 016/029 状态分层）。夹具策略：先从 facts 库挑 test
  工程里已有的带 nc_pins/must_connect 器件；没有就在 test 页现场放一个再构造违例。**ROBOT 等
  禁地全程只读**。
- 证据 `outputs/035_*.txt`。

### 5. 文档

- SKILL.md 动作表/审查闭环段落补 patch-pin 一行；坑表若踩新坑再加。
- 不改 bridge.md（无新 bridge 动作的预期；真要加说明例外）。

## 守卫

照旧：pytest 必带 `--basetemp=.tmp_pt_home`；变异 cp 备份 + sha256/cmp 还原；
不碰 git 与 PROGRESS；connector 预期零改动——**若发现必须动 connector（如缺删线动作），
停下来报主代理**；交卷文本同时写 `outputs/035_summary.txt`。

## 交卷记录

（子代理交文本，主代理 append 并复验。）

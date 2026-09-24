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

（子代理四轮交卷全文：`outputs/035_summary.txt`；真机原件：`outputs/035_live.txt`、`outputs/035c_live.txt`、`outputs/035d_live.txt`。）

### 子代理交卷浓缩（agent-43，2026-09-24）

**round-1**：离线三形态全部落地（plan/preview/apply 编排 + 幂等 + 歧义附着拒绝），pytest 1478，
变异 2/2 CAUGHT。真机 disconnect 走到诚实失败：删线成功（画布回读 `attachmentGone:true`）但导出网表
仍报 `NET4=[U3.2,U3.4]` → exit 2 未保存。两条实测落进代码：NC 判据「坐在网上」=「与别人共网」
（刚断开的脚留在单成员自动网 `NET6`）；附着物判定读「脚在上报点表里」（宿主把相接两段线合并成一个
primitive，接点重复上报）。

**round-2**：NC 判据统一一个函数——`pin_ruling()`（规则行与 repair 共用）+ `nc_violation()` +
`is_auto_net()`：≥2 成员网=违例 / 单成员自动网=OK / 单成员用户命名网=违例 / 无网=OK，pytest 1484。
诊断 B 定论：**根因是导出滞后，不是符号 2/4 脚内部绑定**——活网表删除后立刻正确（2 与 4 分开），
导出在 0s / save+3s / +30s / 切页后四次读数完全一致；滞后不自愈 ⇒ 唯一新鲜读数是活网表。

**round-3**（裁决 c + 两条收紧落地）：pin 级验收 = **活网表 + 画布双证**，缺一 exit 3
`verification_disagrees`；connect/reconnect 目标网必须**用户命名网**（自动网 plan 时拒，exit 5）；
范围核对分家（delete → 画布身份级 `wiresVanished == [attachment.primitive_id]`；create → 维持导出核对）。
真机三形态一次跑齐（只碰 test 窗）：**A disconnect**（真架 `nc_pins:["4"]`）、**B connect**、
**C reconnect**（B/C 用 test-only facts 架，must_connect 事实逐字标注为测试编造，临时 cwd
`%TEMP%\bw035c\`，真库 `blocklib/parts.json` 未写）——各 applied + saved + 重审 resolved +
幂等重放 already_applied + stale exit 4 零写入。重审读数：删过东西的 run 用活网表覆盖导出
（`patchpin.overlay_live_nets`）；纯 create 仍读导出。规则侧镜像修复 `pin_dangles()`（够不着任何网 →
connect 形态而非 reconnect）。pytest 1497 / connector 419 / tsc 干净；变异 7/7 CAUGHT。

**round-4**（三条裁决落地）：范围分家定案——**「导出新鲜当且仅当本 run 无删除」**写进 `cli.py` §6c，
新增可读字段 `verification.outsideScopeBasis`；被幻影差异拦过的 reconnect 夹具（错网=两成员自动网
pin5↔pin1）重跑 applied + saved。`edit plan --pin` 共享选择器 `_select_report_finding()`（patch-pin 与
029 decap `--report` 共用）：多条命中拒绝并点名候选脚号 / 无匹配拒绝 / 配 `--file` 拒绝；真机三态实证
（U3 同页 pin4 NC + pin5 must_connect：无参 exit 5 列候选、`--pin 5` 建 reconnect plan、`--pin 9` exit 5）。
第四个实测发现：导出与活网表对同一匿名网给两个名字（`NET3` vs `$57N2`）⇒ `is_auto_net` 词表扩为
`^(NET\d+|\$\S+)$`，stale 检查两个自动名视为同一岛（用户命名网仍逐字比，测试钉住）。pytest **1507** /
connector **419** / tsc 干净；变异 4/4 CAUGHT（四轮累计 2+2+7+4 全 CAUGHT）。现场零残留：scratch 页全删、
6 文档、焦点回 P1、identity consistent；ROBOT/test2 全程未寻址。

裁决留痕：netlabel 附着 → **拒绝并点名**（本机 `sch_PrimitiveNetLabel` 连读都不存在；不给 connector
加无法验收的删除类别）。

### 主代理复验（2026-09-24）

- sha256 抽核 6 件全对：cli.py `94c54f42…`、changeplan.py `d6edaf05…`、facts.py `7c4e4d6f…`、
  patchpin.py `dcc5bce0…`、test_035_patchpin.py `aa151b70…`、test_016_edit_cli.py `9026c911…`。
- 三线复跑：pytest **1507 passed** / connector **419 passed** / `tsc --noEmit` 干净。
- `git status` 无测试架污染（test-only `parts.json` 只在 `%TEMP%\bw035c\`）；connector/daemon 零改动，
  仍 0.4.23。
- SKILL.md 坑表补第 24 条（导出不重算定论 + 三条宿主习性），动作说明区补 patch-pin 用法与 `--pin`。

# 任务 008b：选型管线——curated 件库（旧板播种）+ 在线比对选型

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> **硬前置**：岳翔宇的四块旧板重导出为 `.epro2`（未加密），优先 `smart_pillbox`
> （门槛最低，岳翔宇 2026-09-16 定）。文件到手放进 `blocklib/sources/` 再开工。
> 前置阅读：`tasks/008-generation-pipeline.md`（架构宪法）、`blocklib/blocks/*.json`
> （provenance 格式样板）、参考实现 `C:\Users\xiangyu\.claude\skills\easyeda-agent\
> references\part-selection.md` 与 `scripts\parts-select.py`（**只读借鉴，不抄代码**）。

## 目标

008c 的"模型选块"到时必须有确定性货架可挑。本任务把货架建出来：

1. **curated 件库**：每条目 = 已验证的真实器件身份（MPN + LCSC C 号 + 库 deviceUuid +
   库封装名 + 电气参数原文），来源可溯（哪块板哪个位号）。
2. **选型工具**：离线件库优先（零网络）；在线 JLC SMT 目录比对为显式 opt-in
   （库存/basic/preferred/价格排序）。

## 工作项

### 1. 件库格式（`blocklib/parts.json`）

每条目字段：`key`（分类.语义名，如 `res.5k1_0402`）/ `value` / `mpn` / `lcsc` /
`manufacturer` / `deviceUuid` + `libraryUuid` / `footprint_name`（**库词汇表**，如 `R0402`，
不许存人读标签——006b §I 的词汇表结论）/ `params`（电气参数原文，单位保留：
`Resistance: "5.1kΩ ±1%"` 原样存，不做归一化猜测）/ `datasheetUrl` + `datasheetPdfUrl`
（有就存）/ `provenance`（`{kind: "board-extract", source, designators}` 或
`{kind: "catalog-select", ...}`）/ `basic`（JLC 基础件标记，有证据才写）。

### 2. 旧板播种工具（`tools/harvest_parts.py`）

从解析后的板模型收割器件身份：遍历组件 → 取 device 名 / LCSC（Supplier Part）/
MPN / 库封装 uuid + libraryUuid → 经桥 `lib.device.get` + `lib.footprint.get` 反查
**库封装名**核验（词汇表必须是库名；查不到就如实标 `unverified`，不许写猜测值）。
同一 LCSC 跨板复用合并为一条，provenance.designators 累加（"C1@smart_pillbox +
R7@thesis_FOC" 这种履历本身就是置信度）。

**判定标准**：每条目能与它的来源板重新对账（工具重跑幂等：同一板收两次产出同一条目，
差异只在 designators 履历追加——且追加也不许重复）。

### 3. 选型 CLI（`boardwise parts select "<query>" [--qty N] [--json] [--online]`）

- **默认离线**：只查 `blocklib/parts.json`。查询支持显式单位阻值（`5.1kΩ`）与封装词
  （`0402` 命中库名 `R0402` 的前缀归一化——**这是唯一允许的词汇表映射，写成显式表**：
  `0402→{R0402,C0402,L0402,LED0402…}` 按类别词消歧，不在表内不映射）。
- **阻值门禁**（照 #202 的纪律，参考实现里有完整语义）：显式带单位的阻值查询只接受
  **具名属性字段**的数值相等匹配；SI 前缀区分大小写（`330mΩ=0.33Ω` 永不等 `33Ω`）；
  不许从料号猜数值；无精确候选时退出码 1，不输出模糊推荐。
- **`--online` 显式 opt-in**：JLC SMT `selectSmtComponentList`，base+general 双查合并，
  排序 = spec 匹配 → 库存≥qty → basic → preferred → 最低价。**daemon 侧或工具侧实现，
  connector 不许碰网络**（webview 不能跨域 fetch，参考实现同此约束）。
- 在线选定后的身份解析必须**确定性**：按 C 号走桥 `lib.device.search`（C 号是精确键，
  不是模糊关键字），拿 deviceUuid 回写件库。

### 4. replay.py 死代码清理（岳翔宇已批）

`engines/replay.py` 第 624–701 行（`_on_segment`/`_key`/`split_at_junctions` 的第一份
定义，与 704–780 逐字节相同）删除。语义可证不变：既有测试零修改全绿即为判定。

## 验收

1. `smart_pillbox` 播种产出件库（条目数如实报告）；每条目通过"与来源板对账"复跑。
2. `parts select` 离线命中播种件；显式阻值门禁负向测试（`330mΩ` 查询**不得**推荐
   `33Ω` 件；无候选退出码 1）。
3. 封装词汇表映射只有显式表一条路径；未知封装词不映射（负向测试钉住）。
4. replay.py 清理后测试全绿零修改。
5. 测试计数只增不减（基线 **Python 451 / connector 167 / tsc 干净**）。
6. 完成记录写回本任务书；新增桥动作须先报 Kimi 评估（daemon 重启归 Kimi）。

## 不许动的部分

draw/assemble/compare/lint 既有语义；块模板格式（008a 冻结）；创建确认门禁；
**不碰 datasheet 提取与模型选块**（那是 008c）；在线路径默认关闭，
测试不许打真网络（mock 或录制响应）。

---

# 008b 完成记录（2026-09-16）

## 前置条件的更正：到手的是 `.eprj2`，而这反而是更好的来源

任务书写「硬前置 = 四块旧板重导出为不加密 `.epro2`」；14:10 落进 `blocklib/sources/`
的是四个 **`.eprj2`**（本地工程数据库）。量过之后发现：**这四块板不是一个形态**，
而 004 那条「本地工程不带库元数据」的结论只对其中一种成立。

| 板 | `documents`/`devices`/`attributes` | 能否播种 |
|---|---|---|
| `smart_pillbox`（智能药箱） | 2 / 32 / 592 行 | ✅ 13 条目 |
| `thesis_FOC_board`（24V FOC 驱动板） | 3 / 76 / 1662 行 | ✅ 41 条目 |
| `highspeed_motor_ctrl` | 0 / 0 / 0（只在加密编辑日志里） | ❌ |
| `ROBOT_ctrl_FOC` | 0 / 0 / 0 | ❌ |

**根因**：库属性不在文档流里，而在 **`attributes` 表**（按 `devices.uuid` 的键值：
`Supplier Part` = LCSC、`Manufacturer Part`、`Datasheet`、`Supplier Footprint`、电气参数）。
**本地另存**的工程会把状态物化到 `documents`/`components`/`devices` 并在 `attributes` 里带上库元数据；
**只缓存了编辑日志**的工程这几张表全空 —— 那种文件**不可能**播种件库，解密也无济于事
（属性从来没被存进去）。⇒ 结论改成：**编辑日志形态的 `.eprj2` 需要「本地另存」或导出 `.epro2`**，
不是「解密更难一点」。已更正 `tools/eprj2-recon/README.md`，细节写进 `docs/parts.md`。

顺带钉死两条格式事实：物化文档的 `dataStr` = `"base64" + base64(gzip(记录文本))`，**未加密**
（不需要 pycryptodome）；记录是**位置数组形**（`["ATTR","e69","e67","Designator","U1",…]`），
不是 `.epru` 的信封形 —— 阅读器只读**已确证位置**的两种记录，绝不去猜数组下标。

## 交付物

| 路径 | 角色 |
|---|---|
| `src/boardwise/core/parts.py` | 条目/库 schema、**阻值门禁**（#202）、**封装词汇表**（唯一映射） |
| `src/boardwise/parsers/eprj2.py` | `.eprj2` 阅读器（`mode=ro`）：文档 + 库身份 |
| `src/boardwise/engines/harvest.py` | 板 → 条目；跨板合并；`verifier` 接缝 |
| `src/boardwise/engines/catalog.py` | JLC SMT 客户端（fetcher 接缝，测试永不触网） |
| `src/boardwise/engines/select.py` | 离线/在线排序 + 按 C 号确定性解析身份 |
| `tools/harvest_parts.py` | 收割 CLI（`--check` 幂等复跑 / `--verify` 经桥核对） |
| `blocklib/parts.json` | 件库，**50 条目**（13 + 41，含 4 条跨板共享） |
| `docs/parts.md` | 格式、门禁、词汇表、在线路径与诚实边界 |
| `tests/test_parts_library.py` / `test_harvest.py` / `test_select.py` / `test_catalog.py` / `test_module_hygiene.py` | 137 个新用例（+1 条代理回归，落在既有 `test_bridge_cli.py`） |

**不需要新桥动作**：`protocol.py` 未改（`ACTIONS` 仍 29 条），用的是既有的
`lib.device.search` / `lib.footprint.get`；daemon 只 import `protocol`，
**本轮不需要重启 daemon**。Kimi 那边没有待办。

## 六条验收

| # | 验收 | 结果 |
|---|---|---|
| 1 | `smart_pillbox` 播种 + 与来源板对账 + 复跑 | ✅ **13 条目**（43 个放置 → 13 个不同 C 号）；`reconcile_counts` = smart_pillbox 13 / thesis_FOC_board 41，两块合计 = 50 条目 + 4 条共享；`--check` 报 `matches a fresh harvest — the harvest is idempotent`；同源收两次 JSON 逐字节相同、`designators` 无重复 |
| 2 | 离线命中 + 阻值门禁负向 + 退出码 1 | ✅ `5mΩ 2512 → C46634460`（`ohms=0.005`）、`470Ω 0805 → C2907329`、`100nF 0805`、`CH340N`；**合成一对 330mΩ/33Ω 0805 做尖负向**：`330mΩ` 只出 330mΩ 件、`33Ω` 只出 33Ω 件、`330MΩ` 一个都不出；不可解析的 `1/2Ω`/`3e3ohm` 关门且 **exit 1**；`330mΩ`/`10kΩ` 无候选 **exit 1**；模糊查询空结果 exit 0 |
| 3 | 词汇表只有显式表一条路径 | ✅ `FOOTPRINT_ALIASES` 是唯一映射（`0402→{R0402,C0402,L0402,LED0402}`，`cap 0402→C0402`）；`9999`/`0201`/`QFN-64` 一律 `unmapped` 且**不施加约束**（负向钉住）；尺寸词是过滤器、不是检索词 |
| 4 | replay.py 清理 | ✅ 删 **81 行**（`_on_segment`/`_key`/`split_at_junctions` 的第一份定义，与第二份逐字节相同，用 AST 段哈希证过）；定义现各一处（623/637/641 行）；**既有测试零修改全绿**；新增 `tests/test_module_hygiene.py` 把「同一模块不许重复定义顶层名」变成守卫（带正向对照） |
| 5 | 计数只增不减 | ✅ Python **451 → 589**（+138）、connector **167**（未改）、`tsc` 干净 |
| 6 | 记录 + 新动作报备 | ✅ 本条；无需新动作 |

## 顺带修的一个真 bug（不在 008b 范围，但它让测试变红）

`websockets 17` 的 `connect(..., proxy=True)` 是默认值 = 「按 `HTTPS_PROXY`/`HTTP_PROXY`/
`ALL_PROXY` 走代理」，而 daemon 在 **loopback**。本机环境带着沙箱代理时，
`ws://127.0.0.1:61190/eda` 被送去代理并回 `InvalidProxyStatus: proxy rejected connection: HTTP 502`
—— 读起来**和「daemon 不在」一模一样**，而 daemon 好好的。`BridgeClient.open` 现在显式传
`proxy=None`，并加了回归测试 `test_status_ignores_an_ambient_http_proxy`。
（发现方式：全量跑出现 1 条 `test_bridge_cli` 失败 → 先怀疑环境而不是结论，
`env | grep -i proxy` 证实；这也解释了为什么它在本会话之前是绿的。）

## 诚实的边界（写进 `docs/parts.md` 了）

- **在线路径从未对真实服务跑过。** 请求形状与响应键来自参考实现记录的 2026-09 实测；
  客户端写成「形状变了就出空字段 + 一条 note」，不静默变空列表。真机跑需要有人持网。
- **`--verify` / `--resolve` 从未对真实编辑器跑过**：已实现、已用桩做过单测；
  搜索项的字段形状只由 connector 自己的文档钉住（`supplierId`/`footprintName`/`footprintUuid`），
  所以解析器**报告它命中了哪个键**而不是假定。
- **件库里 `footprint_name_verified` 全是 `null`** —— 还没跑过桥核对，这就是诚实状态；
  `tools/harvest_parts.py --verify` 是改它的唯一途径。
- 收割只取**板子上放了的**器件；库里没用到的真实器件（15 + 4 个）与**抽象占位件**
  （`Res_0603`/`CAP_0402` 这类无 C 号的）都**如实报告**、不入库 —— 后者正是 006b「库件替换」的形状。

## 需要岳翔宇决定 / 提供的一件事

`highspeed_motor_ctrl` 与 `ROBOT_ctrl_FOC` 是编辑日志形态，**无法播种**。若要把这两块板纳入件库，
请在编辑器里**本地另存**一次（或导出不加密 `.epro2`），放进 `blocklib/sources/` 后重跑：

```bash
python tools/harvest_parts.py --sources blocklib/sources/*.eprj2 --check
```

---

# 008b 补记（2026-09-16 晚）：两块板的 `.epro2` 到手，件库扩到 85 条

岳翔宇当天就把那两块板导出为 `.epro2`，放在 `tests/fixtures/`
（`ProPrj_高速电机控制器_2026-09-16.epro2`、`ProPrj_ROBOT ctrl FOC_2026-09-16.epro2`）。
于是**同两块板、两种形态并排跑通**，这正好把我上一轮的根因结论变成可复现的测量。

## 新增：`.epro2` 阅读器（任务书工作项 2 本来就要的路径）

`parsers/eprj2.py` 改名为 **`parsers/board_source.py`**（它现在读两种格式，名字不能再说谎），
对外两个读取器 + 一个按后缀分派的入口 `load_board_source()`。

| | `.eprj2` | `.epro2` |
|---|---|---|
| 库器件 | `devices` 表 + `attributes` 表 | `DEVICE` 文档的 `META.attributes` |
| 库身份 | `devices.source` = `库docUuid\|库uuid` | `META.source`，同一形式 |
| 封装名 | `components.title`（**被小写化**） | `FOOTPRINT` 的 `META.title`（**库原拼写**） |
| placement | 示意文档的数组记录 | `SCH_PAGE` 文档，**走已验证的 `_split_page`** |

**★ 一个真正的坑（值得记）**：我第一版自己按「ATTR 跟着最近的 COMPONENT」重写了分组，
结果 highspeed 板"找到 85 个 placement"——**是另一组 85 个**。`_split_page` 的规则有四条
（属性 run 遇任何其他元素即结束，但 `ELE_PLACEHOLDER` 与 `LINE` 除外；无 body 的记录也结束它），
漏一条就会把位号挂到错误的器件上。**结论：不要重写已验证的分组逻辑，直接调它。**
`tests/test_board_source.py` 对四个 `.epro2` 逐个做「设计符集合 == `build_schematic_model`」的交叉验证。

## 测量结果（同两块板，两种形态）

| 板 | `.eprj2`（本地工程） | `.epro2`（导出） |
|---|---|---|
| highspeed_motor_ctrl / ProPrj_高速电机控制器 | ❌ 只有编辑日志 → 0 条 | ✅ 85 placements → **47 条** |
| ROBOT_ctrl_FOC / ProPrj_ROBOT ctrl FOC | ❌ 只有编辑日志 → 0 条 | ✅ 44 placements → **15 条** |

跑一次全量收割（四块板全给，两种格式一起）时，报告里这两种结论**并排出现** ——
这就是"编辑日志形态无法播种、导出即恢复"的可复现证据。

## 件库现在的样子

**85 条**（13 + 41 + 47 + 15，跨板共享 31 条计入各自）。
`CH340N`（C2977777）**四块板全有** —— 履历 `U10@smart_pillbox` / `U8@thesis_FOC_board` / …，
这是件库里证据最强的一条。另有 `res.5k1_0402`（C2906948）——**006b 当时只能手工挑的那个 0402 5.1k**，
现在货架直接答得出（`parts select "5.1kΩ 0402"`）。

### 又一条踩出来的测量：库名的大小写

同一条目在两块板上给出**大小写不同**的封装名：`.eprj2` 给 `r0603`、`.epro2` 给 `R0603`
（编辑器的本地工程库把文档标题折叠成小写）。006b 实测 `lib.footprint.get` 回的是 `R0402`
——**保大小写的那份才是库的写法**。所以：

- 合并时**只差大小写不算冲突**，取保大小写的那份（20 条命中此规则）；
- **只有单一来源**的条目**保持原样**，只加一条 note —— 没有第二份拼写可比对时不改写，
  和"不许猜封装名"是同一条规则（30 条如此）；
- 真冲突从 35 条降到 **9 条**，剩下的都是不同板库快照之间的**真实数据分歧**
  （LED 的 `Forward Current 20mA vs 25mA`、USB-C 的 `Connect-Disconnect Life 5千次 vs 1万次`、
  晶振描述措辞），按 #202 第 4 条**记录而不平均**。

## 计数（补记后）

Python **451 → 608**（+157）/ connector **167**（未改）/ `tsc` 干净。
新增 `tests/test_board_source.py`（17 例，含两个读取器的交叉验证与"同板两形态"证据）。

## 仍待真机的两项（未变）

`--verify`（经桥核对封装名，件库里 `footprint_name_verified` **仍是全 `null`**）
与 `--resolve`（按 C 号解析身份）。两者都只有桩测试 —— 编辑器的搜索项字段形状仍待真机确认。
在线目录比对同样从未对真实服务跑过。

---

# 008b 修复：`--verify` 走器件链（2026-09-16 晚，Kimi 真机定位）

## 缺陷

`tools/harvest_parts.py` 的 `_collect_footprint_names` 拿**工程内局部**的封装 uuid 去调
`lib.footprint.get`，真机上**每个器件都抛错**。这正是 006b 早就量过的那条：
**项目局部的文档 uuid 不是库的键**（当时是 `Symbol`，这次是 `Footprint`）——
我把 `deviceUuid` 的规则写对了，却在封装那一跳用了局部 uuid。

**真机验证过的可用链路**（Kimi）：

```
lib.device.get(uuid=条目 deviceUuid, libraryUuid=条目 libraryUuid)
   → item.association.footprintUuid
lib.footprint.get(uuid=那个 footprintUuid, libraryUuid=同一个 libraryUuid)
   → name
```

## 改动

1. `_collect_footprint_names`（改名公开 `collect_footprint_names(sources, *, client=None)`）
   **按器件收集**：遍历 sources 的可收割器件，把 `(library device uuid, library uuid)` 去重，
   每个器件的两条调用跑完才拿名字；答案键改成**器件 uuid 对**。
   `client` 可注入 —— 整条链因此能在桩上跑，不需要编辑器。
2. `engines/harvest.py`：`Verifier` 的语义注释、`_entry_for` 的调用点与末尾 note 全部改成
   **器件对**（`device.library_doc_uuid` / `device.library_uuid`）。
3. **加的字段探针**：`footprint_uuid_of_device(item)` 按 5 条**有记录的**路径找 footprint uuid
   —— `association.footprintUuid`（真机验证过的那条，**排第一**）→ `association.footprint.uuid`
   → `association.footprint` → `footprintUuid` → `footprint.uuid`；命中哪条**写进报告**
   （`via association.footprintUuid`）。找不到就当作"答不出来"，**继续调 `footprint.get` 之前就停**。
4. **"哪些器件可收割"只留一份定义**：新增 `placed_devices(project)` 与 `devices_to_verify(sources)`，
   收割与核验共用同一条规则（两份拷贝正是核验和收割走偏的方式）。
   新增测试 `test_the_devices_to_verify_are_the_ones_the_harvest_would_write` 把两者钉在一起。
5. 删掉 `parsers/board_source.py::footprint_library_uuid` —— 它**编码的正是那条走错的键**，
   并原地留一条注释说明为什么不能再用它（避免下次有人重新推导）。
6. **失败处理未变**：单件失败不致命、如实打到 stderr、条目保持 `unverified`；
   "库答出的名字与项目拼写不同 ⇒ 采用库的写法 + note"的更正逻辑原样保留。

## 顺手发现并处理的一件事

件库 `blocklib/parts.json` 原来带着**你那次真机 `--verify` 失败留下的痕迹**：
85/85 条都有 "could not be asked …" 的 note（`footprint_name_verified` 全 `null`）。
已用**不带 `--verify`** 的干净收割重写（85 条，0 条带该 note），因为"工具重跑幂等"是验收项，
而带失败痕迹的产物无法被一次普通收割复现。

同时给 `--check` 加了一条规矩：若磁盘上的件库**带着核验痕迹**而你这次没开 `--verify`，
它会说明"这些名字来自库，普通收割复现不了"，并**只比较核验不会改动的字段**
（identity / 参数 / 履历照常逐字比）—— 免得将来一次成功的 `--verify` 让 `--check` 变成一个费解的红色。

## 测试

- `tests/test_harvest_verify.py`（新，10 例）：整条链的桩测试 —— 两次调用的参数形状、
  一次设备两条调用（不按放置重复）、注入的 client 不被关闭、答案喂回收割后 `verified=True`；
  **三个负向**：`lib.device.get` 抛错 / `association` 里没有 footprintUuid（且**不再调** footprint.get）
  / `lib.footprint.get` 抛错；外加"一个器件失败不影响其他"与"无可核验器件的板子不是错误"。
- `tests/test_harvest.py` 新增/补回 7 例：`footprint_uuid_of_device` 的 10 组路径与空值、
  **verifier 收到的必须是器件对**（用记录型桩检查"问的是谁"，而不只是答案）、
  `devices_to_verify` 与收割写出的器件对相等。

**计数：Python 608 → 625**（+17）/ connector **167**（未改）/ `tsc` 干净。

**没有动动作表**（`ACTIONS` 仍 29 条）⇒ **不需要重启 daemon**。

## 仍然诚实的部分

- 探针里 `association.footprintUuid` 是**你真机验证过的那条**；另外四条 fallback **没有**真机样本，
  它们只是形状变体，所以命中哪条会被打印出来，而不是假定。
- `footprint_name_verified` 现在**仍是全 `null`** —— 修复的是链路，不是核对结果；
  你复跑 `--verify` 之后才会变成 `true`（以及若干条拼写更正）。




---

## 验收戳（008b 正式收官，2026-09-16，Kimi）

**复验（全部 Kimi 亲跑，非转述）**：

- 测试：Python **625** 全绿 / connector **167** / `tsc` 干净（基线 451 → 625，只增不减 ✓）。
- 真机 `--verify`：**83/85 条核验通过**，库正名 48 条折叠拼写（`r0603`→`R0402` 类）。
  抽查 `res.5k1_0402`→`R0402`、`ic.ch340n`→`SOP-8_L4.9-W3.9-P1.27-LS6.0-BL`、
  `ic.stm32g431rbt6`→`LQFP-64_L10.0-W10.0-P0.50-LS12.0-BL`，与库逐字一致。
- 幂等终验 `--check --verify`：**"matches a fresh harvest — the harvest is idempotent"**
  （含核验痕迹的逐字节一致）。
- 真机探测顺带定案 `lib.device.search` 搜索项字段形状（`supplierId`/`footprintName`/
  `footprintUuid` 齐）——008b 最后一项"待真机"关闭；`--resolve` 的字段假设被真机证实。
- 离线门禁早前已验：`5.1kΩ 0402` → C2906948（R0402）；`330mΩ 2512` 无候选 **exit 1**。

**如实记录的未决尾项（不挡验收）**：`ic.drv8350srtvr`（C2861195）与 `ic.hb04n090s`
（C49423996）来自个人库 "FOC"，`libraryUuid` 存的是库名而非 uuid，`lib.device.get`
两条路均 `found:false`，条目按机制如实保持 `unverified`。两颗料在系统库按 C 号可搜到
唯一命中且封装名一致——收尾走新增的 `--rehome`（按 C 号重锚身份，显式 opt-in），
已派发 DeepSeek，完成后由 Kimi 真机复验。

**008b 验收通过。** 下一任务：008c（任务书已就位：`tasks/008c-input-understanding.md`）。

---

# 008b 尾账（2026-09-17）：`--rehome` 就绪 + datasheet PDF 回填完成

## 一笔：datasheetPdfUrl —— 已完成（真机网络跑过）

新增 `tools/backfill_datasheets.py` + `engines/catalog.py::fetch_product_detail`：

```
GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=<C号>
  -> {"code":200,"result":{ ..., "pdfUrl":"https://datasheet.lcsc.com/…pdf" }}
```

**实测结果：85 条中 82 条填上**，另 3 条**如实留空并分类报告**（三类答案不合并）：

| C 号 | 结果 | 含义 |
|---|---|---|
| C160183 | `result` 有、`pdfUrl` 空 | 该器件页上没有 PDF |
| C22369707 | `{"code":200,"result":null}` | 服务不认识这个 C 号 |
| C9900097986 | 同上 | **10 位 C 号**，不是目录会发的形状 —— 源头数据问题（`conn.mx1_25_lt_3`，来自 ROBOT/高速两块板），值得回头找岳翔宇确认 |

**★ 关键设计**：链接同时写进**旁车** `blocklib/parts.corrections.json`，并且
`harvest()` 会应用它 —— 否则「离线 `--check` 逐字节复现」这条 008b 验收会当场失效
（harvest 读板子，板子上只有 datasheet **网页**，没有文件）。旁车机制沿用 006b 黄金
旁车的先例：**夹具（件库）不动，更正走旁车**。

## 另一笔：`--rehome` —— 机制就绪，真机执行待你

`tools/harvest_parts.py --rehome`（**显式 opt-in，独立模式**）：

- **候选判定是本地可查的**（`libraryUuid` 不是 32 位 hex）⇒ 不靠桥也能复现「哪两条要重锚」，
  实测恰为那两条：`ic.drv8350srtvr`（C2861195）、`ic.hb04n090s`（C49423996）。
- 重锚走 `lib.device.search`，**C 号是精确键**：0 命中/多命中/缺 device uuid/答案不是 uuid
  —— 四种情况全部拒绝（与 `parts select --resolve` 同一条纪律）。
- **`--rehome` 只写旁车**，件库由随后的 `--verify` 刷新（`--rehome --verify` 会被拒，
  免得「只想改两条身份」的一跑把 85 条一起重curate）。旁车在**问桥之前**生效，所以
  `--verify` 问的是重锚后的 uuid 对 —— 这正是修复的要点（问原 uuid 对必然 `found:false`）。

**真机两步（Kimi）**：

```bash
python tools/harvest_parts.py --rehome                     # 写旁车（两条）
python tools/harvest_parts.py --sources blocklib/sources/*.eprj2 \
    "tests/fixtures/ProPrj_高速电机控制器_2026-09-16.epro2" \
    "tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2" --verify      # 刷新件库
python tools/harvest_parts.py --sources ... --check --verify             # 逐字节终验
```

## 顺带修掉的两个**真**缺陷（都是这次改造暴露出来的）

1. **`provenance.source` 曾按命令行顺序拼接** ⇒ 同一组来源换个 `--sources` 次序产出不同字节，
   「工具重跑幂等」只在某一个参数次序下成立。改为**排序后的集合**渲染（来源列表本来就没有
   顺序语义）。
2. **`--check` 的忽略集不完整**：`--verify` 会写一条「桥问不到」的 note，普通 `--check`
   复现不了它 ⇒ 报成差异。规则下沉到引擎的 `harvest.BRIDGE_DECIDED_FIELDS` +
   `strip_bridge_decided()`，工具与测试**共用一份**（两份拷贝正是检查器与作者停止一致的路径）。

另：schema 现在**拒绝**「`footprint_name_verified: true` 而 `libraryUuid` 不是库 uuid」的条目
—— 唯一能拿到该答案的链路要求身份可解析，接受这种声明等于让文件主张一次不可能发生的检查。

## 计数

Python **625 → 666**（+41：`test_rehome.py` 20、`test_datasheet_backfill.py` 19、
`test_parts_library.py` +1、`test_harvest.py` +1）/ connector **167**（未改）/ `tsc` 干净。
**未动动作表**（`ACTIONS` 仍 29 条）⇒ 不需要重启 daemon。

---

## 008b 尾账销记（2026-09-17，Kimi 复验）

DeepSeek 交付：`--rehome`（旁车身份更正）+ `tools/backfill_datasheets.py`（wmsc 接口
`pdfUrl` 回填，更正走旁车 `blocklib/parts.corrections.json`，件库保持"源板 + 旁车"的
确定性函数）；顺带修掉两个真缺陷（`provenance.source` 依赖命令行参数顺序 ⇒ 改为排序集合；
`--check` 忽略集不完整 ⇒ 规则下沉 `harvest.BRIDGE_DECIDED_FIELDS`），并加固 schema 守卫
（`verified:true` 而身份不可解析 ⇒ 拒绝加载）。

**Kimi 亲跑复验**：

- 真机 `--rehome`：C2861195 / C49423996 按 C 号重锚到系统库器件 ✅
- 复验中抓到并派发修复：`corrections_from_json` 判重写成跨段（同一 C 号同时在
  identity + datasheets 两段被误拒）——DeepSeek 已修并补测试。
- 终态：**`footprint_name_verified` 85/85 全 True**（两条重锚件封装名随库正名），
  `datasheetPdfUrl` 82/85（3 条为服务端无 PDF / 目录无此号，如实留空；
  C9900097986 是 10 位异常 C 号，源头数据问题，留给岳翔宇回头确认）。
- `--verify` exit 0 + `--check --verify` **逐字节幂等** ✅
- 计数：Python 625 → 695 → **733** / connector **167** / `tsc` 干净。

**设计裁决（Kimi）**：`--rehome` 维持"只写旁车、不刷件库"——旁车是输入、件库是产物，
标准流程就是 `--rehome` 后跑 `--verify`，不绑在一起。

**008b 全部结清。**

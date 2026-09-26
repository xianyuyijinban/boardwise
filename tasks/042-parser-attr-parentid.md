# 042：解析器 ATTR 归属改双程 parentId 挂载（静默丢器件修复）

日期：2026-09-26。发现场景：ROBOT ctrl FOC 真机盲审。

## §1 症状

`build_project_model` 解析 ROBOT ctrl FOC 的 epro2（`E:\boardwise\.tmp_robot_review\robot_live.epro2`）
得到 **44 个器件**，而活工程（`sch.geometry` / `sch.netlist` 实测）有 **49 个真实器件**。
丢失的 5 颗：**R4（U 相采样电阻）、U8（AMS1117-3.3，全板 3.3V 电源！）、USB1（Type-C）、
SWD（调试座）、C11**。ParseStats 全程无感：`components_without_symbol=0`、
`malformed_records=0`、`pins_dropped_no_number=0`——**静默丢失**，审查因此对电源入口、
USB 座、调试座完全失明（规则引擎 0 findings 是假的）。

## §2 机理（已定位，证据确凿）

epro2 是 zip；工程正文在 entry `ROBOT ctrl FOC.epru`。SCH_PAGE 文档内：

- R4 的 `COMPONENT` 记录（ticket=188043，id=`55938e9efdab989f`，**firstTicket=165848**）
  被宿主**插回排序位置**（文件中段），其后紧跟的是**另一个** COMPONENT（ticket=165906）；
- R4 的 26 条 ATTR（ticket 188044–188069，含 `Designator=R4`、`Symbol=5152ea5f69cfb743`）
  全部**追加在文件尾部**（行 2340–2359），每条 `parentId=55938e9efdab989f`。

即：立创增量保存时，COMPONENT 记录按 firstTicket 插回旧位置，新 ATTR 追加在文档尾——
**"ATTR 紧邻 COMPONENT"这一假设对任何经过增量编辑的工程都不成立**。

`_split_page`（src/boardwise/parsers/schematic.py:606）目前只做单程邻接归属，
于是这 5 颗器件的 ATTR 全部落空 → 无 Designator → 下游静默丢弃。

佐证：该页 25 条 COMPONENT 记录，**全部**能经 parentId 找到 ATTR（0 孤儿）。

## §3 修复方案（双程挂载）

在 `_split_page` 内改双程：

1. **第一程**：照旧遍历记录，收集 `_Instance`（COMPONENT）——新增字段保存组件记录的
   `id`（如 `record_id`）；同时把每条 ATTR（含 page）暂存起来。LINE/NET/wire group/
   DOCHEAD 等其余逻辑一律不动。
2. **第二程**：逐条 ATTR 归属——
   - `key == "NET"` / `"NO_CONNECT"` → 照旧 loose（现行规则不变）；
   - `parentId` 命中某实例的 `record_id` → 挂到该实例（跨页 parentId 是全局 uuid，
     天然安全；为稳妥可再校验 page 一致，不一致则计 loose 并留统计）；
   - `"Global Net Name"` 特殊情形保留现行逻辑（parentId 可能是容器 id 或库模板 id）；
   - 其余 → loose（与现行一致）。
3. 现有 7 个真实夹具上邻接法结果必须与 parentId 法**完全一致**（回归测试断言这一点，
   不允许行为漂移）。

## §4 ParseStats 补强（防再静默）

- 新增 `attrs_attached_by_parent_id` 计数（双程挂载命中数）；
- 新增 `instances_without_designator` 计数（无 Designator 且非电源符号的实例数）——
  >0 时 checkup 报告应可见（仅统计字段即可，CLI 展示不在本任务强制范围）。

## §5 测试要求

- **不得**把岳的真实工程提交进仓库。用最小合成夹具复现交错结构：
  一个 SCH_PAGE 文本片段，COMPONENT 记录后紧跟另一个 COMPONENT，其 ATTR（含
  Designator）放在片段尾部、parentId 指回前者 id。
- 回归：现有 fixtures 全量行为不变；全量 pytest 绿。
- 验收解析：`build_project_model('.tmp_robot_review/robot_live.epro2')` 应得
  **49 个真实器件**，含 R4/U8/USB1/SWD/C11，且 R4.attrs['Designator']=='R4'、
  U8 的 Manufacturer Part 含 AMS1117。（该文件在本机磁盘，不入库。）

## §6 边界

- 只动 `src/boardwise/parsers/schematic.py`（必要时 `core/model.py` 加字段）与测试；
  connector 不碰；CLI 不碰（统计字段展示另议）。
- pytest 必带 `--basetemp=.tmp_pt_home`。
- 完成后报告：修改文件清单、测试结果、§5 验收解析的实际输出（器件数与 5 颗关键件）。

## §7 裁决记录（岳翔宇，2026-09-26）

三项裁决，逐条落账：

1. **§3.3「7 个真实夹具零漂移」偏离 —— 批准。**
   定性一句：高速板 85→145 个位号不是本批引入的漂移，而是**同一个增量保存病灶在更大规模上的
   一并治愈**——它自己的 PCB 文档就列着其中 13 颗（`C2/C49/C5/C59/C6/C7/D2/R33–R38`），
   即旧读数当时确实看不见真实存在的器件；而 robot_live 与 ROBOT 的 44→49 是任务书 §1 点名
   要修的那 5 颗，两者结构同类，不存在"只修 ROBOT 不动高速"的合理规则。
   证据链：`outputs/042_evidence.txt` A 节（PCB 交叉验证）、B 节（同一实例集上电气分组不变量
   逐夹具相同）、`outputs/042_summary.txt` 第六/七节。页面图框例外（图框的页面属性留 loose）
   同时获批为 §3 的唯一有意偏离。
2. **item 2（重收 `blocklib/parts.json`）—— 批准执行。**
   以 `tools/harvest_parts.py --verify` 经 bridge 忠实重收（只读库查询，不写任何工程；
   真机禁地纪律不受影响）。执行结果见 `outputs/042_library_reharvest.txt`。
3. **item 3（`param-value-mpn-match` 对 `RC0603FR-074K7L` 解成 7e+04 Ω）—— 已转
   `tasks/043-mpn-value-decode.md` 跟进。**
   与本任务解耦：042 只负责让这颗器件可见，MPN 解码偏差是规则侧的事，本批不改规则。


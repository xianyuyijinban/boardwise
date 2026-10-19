# 任务书：527 — v0.6.0 之前必须收口的尾巴（v0.5.18 内测批）

- 批号：**527**（拆 527A/527B/527C/527D）　立项：2026-10-19　发版目标：**v0.5.18（内测）**
- 依据：`tasks/SCHEDULE.md` 的「待岳拍板」五条 + `tasks/TASKMAP.md` 的「规划/搁置」行 +
  v0.5.17 的实板复验报告（§3 `IntentSource`、§4 B3/B4）
- **不包含 200A/200B/200C**：岳 2026-10-17 裁「0.6.0 的 122 E 阶段 + 高速 A 档冻结到月底前一周再动」，
  故 0.6.0 自己的范围不在本批；本批只清「0.6.0 之前必须落地、否则会带着错结论进正式版」的尾巴。

## 0. 清点：0.6.0 之前还欠什么（逐条给处置）

| 来源 | 条目 | 处置 |
|---|---|---|
| 复验报告 §3 | `IntentSource` 没有 `rails`/`signals`/`buses`，而 `rules/pcb/ipc.py` 用 `getattr(intent, "rails")` 问它 → 按文档构造的合成上下文里**合同被静默读成空** | **527A 修**（三个小节转发 + 4 条回归 + 变异 2/2） |
| 复验报告 §4（B4） | `pcb.readback` 不看当前激活页 → 焦点不在 PCB 页时 `getAll()` 返回 null → `TypeError: … reading 'map'`；同因表现为 `pcb.geometry` 的 `bboxes: 0` | **527B 修**（页型守卫 + 错误码 `WRONG_DOCUMENT`） |
| 复验报告 §4（B3） | 协议帧 `{ok,data}`/`{ok,error}` 与 `bridge call` 解包后的 stdout 两件事文档没说，脚本作者按 `result` 取键必炸 | **527B 补文档**（不是代码缺陷） |
| TASKMAP 189A2 / 待拍板 | 跨视图检查在四块夹具板上出声 7/8/6/2 条；岳已裁「保持 `CROSS_VIEW_MIN_PINS=3`，先分类」 | **527C 分类 + 裁定**（只出证据，不改判据） |
| TASKMAP 523 / 待拍板 | `--apply-facts` 只写 facts 不写 `category` → 机器核验的件仍判不了类型；唯一出路是手改 `blocklib/parts.json` | **527D 修**（`parts classify` + `category_trust`） |
| 待拍板 189A1 | `read_stackup.used_copper_layer_ids` 维持「文档声明口径」还是改物理读数 | **结案：不改**。裁决注释已在 `core/measure.py:321`，改读 `effective_layer_ids` 会把通孔盘的内层带进 used 集，与 `test_125_pcb_measure.py::test_foc_main_board_used_layers` 的岳亲裁实读 `[1,2,16]` 冲突 |
| 待拍板 121 | 反激规划落图（10-06 暂停） | **不动**（岳未重开） |
| 待拍板 051 / 088b | 两份过时 DRAFT 是否标注归档 | **527E 标注归档**（文档动作，不删） |
| 待拍板 191D | 去耦四档数值是主代理初值 | **不动**（随实板反馈调，本期无新反馈） |
| SCHEDULE v0.5.18 | R4 真热更阶段二 stub | **不立项**（岳裁：stub 立不立项待定；不是缺陷） |
| TASKMAP 201E / 515A / 201C | A\* 效率、绘制修洞、布线协商 | **不动**（绘制线，岳 10-18 裁「后面慢慢磨」） |
| roadmap R3 / R5 / R6-L2c | KiCad 第二宿主、SPICE、提取面扩科 | **不动**（0.6.0 后 / 冻结 / 规划） |

**本批的判据**：清完之后，「0.6.0 之前必须做的」为空；剩下的全部是**有明文理由的延后**。

## 527A `IntentSource` 转发三个需求小节（已落）

- `core/designintent.py`：`rails` / `signals` / `buses` 三个只读属性转发到 `document`。
  **只转这三个**——PCB 规则按名字问的就是它们；`blocks` / `accepted_unknown` 没人按名字问，
  加了只是第二套会漂的 API。
- `tests/test_527_intent_source_sections.py` 4 条：两个载体的 `declared_voltages` /
  `declared_currents` **逐字相同**（连出处字符串一起比），空合同与裸对象仍是空。
- 变异 2/2 咬住：去掉 `rails` → 3 红；只去 `signals` → 2 红。

## 527B connector：读回页型守卫 + 信封文档

- `pcb.readback` / `sch.readback`：**精确**得知当前激活文档类型且与请求不符时抛
  `ActionError(WRONG_DOCUMENT)`，文案点名请求类型、当前类型、怎么修；类型未知（启发式来源）
  照旧读，但 `null` 元素要变成 `unreadable` 行而不是崩。
- `docs/bridge.md`：补「协议帧两条形状」+「`bridge call` 已解包，脚本别找 `result`」。
- 顺手：`connector/src/transport.ts` 里罗列 hello `data` 字段的注释补齐（187C 遗留）。

## 527C 189A2 分类（已落：结论是「旧读数本身错了」）

**7/8/6/2 不是这条检查的读数。** `outputs/189a2/probe15.py::singles_and_cross` 拿
`build_project_model().boards[0]` 去配 `docs[0]`，没走 154 的板链（`schematic_board_for`）。
四块板里有两块因此比错了板：09-17 的 **PCB3 配了 Board1**、高速的 **PCB2 配了 Board1**。

**接线后的真读数**（我独立复核了两块：v1.0.0 `PCB1=6 / PCB2=1`、高速 `PCB2=10`）：

| 归档 | 板入口 | 出声 |
|---|---|---|
| `ProPrj_ROBOT ctrl FOC_2026-09-16` | PCB1 | 7 |
| `ProPrj_毕设FOC驱动板_2026-09-17` | PCB3 | 10（旧读数 8，少算 2） |
| `ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07` | PCB1 / PCB2 | 6 + 1（旧读数 6，漏了 PCB2） |
| `ProPrj_高速电机控制器_2026-09-16` | PCB2 | 10（旧读数 2，少算 8） |

合计 **34 条 / 5 个板入口 / 4 个归档**。逐条分类（`outputs/189a2c/evidence.md`，23 行表 +
34 条重算）：**A（真伪网）0 / B（归档自身不一致）34 / C（口径外噪声）0**。
两类 B 的判据都是几何，不是网名：ROBOT 那 7 个脚在图纸上**根本没有导线**（tip 距最近线端
10–40 单位），v1.0.0 那 6 个脚**精确落在自己的 36 单位网络标签引线上**（`SHA/SLA/…`）——
两次都是「图纸本身把这一脚放在另一个名字上」，工具没读错。

**裁定**
1. `CROSS_VIEW_MIN_PINS` **保持 3**。实测 `min_pins` 3→101 扫描：4/5/6/10 与 3 **逐格相同**
   （这批器件是 8/12/33/64/100 脚），抬到 17 才一把抹掉 09-17 的 10 条、34 抹掉 v1.0.0 PCB1 的
   6 条——那是钝刀，不是降噪。岳 10-19 的裁定被这批测量支持。
2. **不按网名/成员关系降噪**（最重要的一条反例）：189A2 的实板样本退回旧序能复现 14 条 A 类，
   其中 9 条有同名网、7 条满足「同名网 == PCB 网去掉这个脚」，与 ROBOT 的 7 条 B 类**在名字与
   成员关系上不可分辨**；几何分得开（那 14 个脚在正确位姿下全部精确落线 0.0）。
   所以任何基于名字的便宜判别式都会吞掉真发现。
3. 报告措辞该分两句（B 的两种成因），但**界线只能取几何**：需要把 parser 的导线几何传进
   `cross_view_lonely_pins`，不是三行改动 → 另立 **527C2**（见下）。
4. `engines/pcbreview.py` 的 docstring 里「23 rows across the 14 fixtures」已改：那两个排除是
   **构造性**的（循环里 `continue`），只有行数是读数——行数连同出处搬进证据文件，不再手抄进代码。

**527C2（规划，未做）**：`cross_view_lonely_pins` 接线几何，把 note 分成「图纸没画线（陈旧板）」
/「落线了但网名不同（图纸连法不同）」/「整块落线率异常（落位嫌疑）」，并在 `checkup` 的 note 里
点名全部位号（现在每板只列前 6 个，ROBOT 的 7 条读成 6 + `…`，容易数错）。

## 527D `category` 的授予路径（523，已落）

- `boardwise parts classify <entry> <category> [--from …] [--page N] [--quote …] [--cache] [--library] [--json]`：
  词表外的词拒绝（列出 12 个顶层族 + `ic.*` 子词）；entry 找不到拒绝且不新建；
  证据三件套齐全 → 机器档，全不给 → 人工档（输出里明说「无引文，按人工签署记账」），给一半 → 拒绝。
- `PartEntry.category_trust`：缺省 = 人工档，所以 109 条旧条目行为与字节**逐字不变**
  （`verified` 不落盘；`entry_from_json` 对 `null`/拼错值按 522 对 `facts_trust` 的同一条规矩报错）。
- 两道闸都要问**分类自己的档位**：
  - `rules/facts.py::_category_state`：机器档只在 `allow_machine=True`（计算类规则）时算数，
    原因文案换一句「分类是机器核验的…本规则要人签字」；
  - `core/partkind.py::shelf_declaration`（判型路径的真闸，`distance`/`sensebias`/`archclosure`/
    `classify_part` 都走它）：**主代理补的**。子代理交付时这里只问 `facts_trust`，于是
    「facts 已人工核验 + 分类是机器档」——正是 `classify --from … --quote …` 最常写出的状态——
    会把机器档分类当人签的，直送所有结论规则。补后带回归
    `test_shelf_declaration_asks_the_category_its_own_tier`，变异咬住（去掉那道闸 → 1 红）。
- 复用而非新写：`_shelf_lookup` 寻址、521 的 `fold_whitespace`/`QUOTE_MIN_CHARS`/`QUOTE_MIN_TOKENS`/
  `quote_is_on_page`、`hunt.extract_pages`/`Cache`、`_write_shelf_document`/`_write_parts_json`、
  `CATEGORY_VOCABULARY`（`category_families()` 从它派生族清单，不手抄第二份）。

**527D 的挖洞结果（独立只读红队，8 条全部核实成立）**

| # | 严重度 | 洞 | 处置 |
|---|---|---|---|
| H1 | **高** | `parts hunt --apply-facts` 的 `_hunt_write_shelf` **逐字段手抄**重建条目，漏了 `category_trust` → 机器档分类**静默升格成人工签署**（522/527D 要防的唯一方向）；触发路径正是文档主推的「先 classify 再补 facts」 | **已修**：继承该字段；并加**结构性**回归（从 `PartEntry` 的 dataclass 字段推导「每个 `*_trust` 都必须在重建里出现」），下一个字段再漏就会红 |
| H2 | **高** | `machine_trust_note` 只读 `facts_trust` → 「facts 人签 + 分类机器授」的 finding **一个字的免责都没有**，522 的物理保证在这里没有对偶的一半 | **已修**：两个档位各出一句，并说清是哪一半未确认（参数 / 分类 / 两者） |
| H3 | **高** | `entry.category` 的**直读点成片存在**（`rules/pcb/mcureset.py`、`mcusupply`、`crystal`、`regulator`、`fbplacement`、`foc`、`focground`、`rules/params.py`、`paramspec.py`、`decap.py`、`archclosure.py`、`railratings.py`、`core/architecture.py`、`core/power_domains.py`）→ 机器档分类仍能驱动结论规则 | **未修（527D3）**。修法不是逐个改规则，而是给这些读点一个**分档感知**的入口（`declared_category(entry, allow_machine=…)`），要先逐条判定每条规则属于「数字」还是「结论」——那是 190/192 锚上的设计改动，不在发版夜动手。**文档与 release notes 已把承诺收窄到实际生效的两道闸** |
| H4 | 中 | `checkup.shelf_can_drive_rules` 不看 `category_trust` → 机器授分类的件被移出「未审」写进「已审」，同时规则对它回 UNKNOWN | **已修**（并加回归） |
| H5 | 中 | `category_trust: candidate` 在 `allow_machine=True` 下被当已分类 —— 比 `machine_verified` **更宽**，与 `facts_trust` 三档不同构 | **已修**：candidate 无条件挡（与 facts 侧同构） |
| L1 | 低 | `_category_absent_reason` 的分支顺序会发出**错的工单**（candidate facts + machine category 时叫人去签分类，签了也没用） | **已修**：顺序与 `_category_state` 逐步对齐，并加「candidate facts 时不发分类工单」的守卫 |
| L4 | 低 | 回滚 `copy2` 没有 try，回滚失败 → traceback + 货架停在半写状态 | **已修**：明确报「回滚也失败了 + 备份在哪」 |
| L2/L3 | 低 | `--json` 的 `ok: true` 先于货架落盘；别处改 `category` 会**继承**旧机器档（`parts add --category`）；`category` 与 `facts` 无交叉校验 | **未修，记入 527D3**。第一条是 039 工具链的既有约定（不只 classify）；第二、三条是设计问题 |

**为什么要写这么细**：H1 是最危险的那一类——它不是「没实现」，是「实现好了被人悄悄改回去」，而且改回去的方向正好是「机器的结论变成人的签字」。结构性回归（H1 那条按 dataclass 字段推导的测试）比一条夹具更难被遗忘。

**527D 的已知边界（写在这里，别当已解决）**

1. **证据不落货架**：`--from/--page/--quote` 只出现在终端与 `--json`，`provenance`/`notes` 一字未写。
   于是 `machine_verified` 这条分类**事后无法追溯出处**——与 521「每条 fact 自带出处」的口径不一致。
   要补得动「只改两个键」这条约束（→ 527D2）。
2. `parts classify` 只写可写架：冻结态下只存在于内置架的条目会 exit 2「找不到」，没提示「它在内置架、改不了」。
3. `--from http(s)` 核的是「该条目身份」的缓存 dump，**不校验 URL 与缓存记录的 URL 是否同一个**（文档已写明）。
4. `SKILL.md` 加不进一行（320 行硬顶 + `docs/parts.md` 不在打包清单），所以 `parts classify` 目前只在
   `docs/parts.md` 与 `--help` 里；要让 AI 路由层认识它，得先压一行或把 `docs/parts.md` 进打包清单。

## 527E 文档与版本（主代理）

- `TASKMAP` / `SCHEDULE` / `roadmap` / `PROGRESS` 收口；189A1 结案、两份 DRAFT 标归档。
- 版本 0.5.18（`pyproject.toml` + `connector/package.json`，dsh 插件仍 0.1.2）。

## 三闸（发版前）

1. **实测**：pytest 全量 + connector（`npm test && npm run typecheck`）+ dsh-plugin
   （`npm run typecheck && npm test && npm run build`）。
2. **挖洞**：只读 swarm 按缝分工（connecter/Python 各一缝，至少 2 个上下文）。
3. **上机**：真机子代理，只碰 `test` / `test2`；A1 那 4 条高侧间距、191D 有无假警报、
   B4 页型守卫是否真的挡住（这条要**故意**在原理图页上敲 `pcb.readback`）。

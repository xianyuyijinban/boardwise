# 126 / PCB 审查阶段 C：模块识别 + 通用层规则化（1/4/8/9）

> 路线图：`tasks/122-pcb-review-roadmap.md` 阶段 C 行。
> 验收出口：**毕设 FOC 出模块级 PCB 报告，岳盲审命中率评估**；随后推 ROBOT ctrl FOC。
> 依赖：阶段 B 测量库（`core/measure.py`，125 已落账）——本阶段所有判定都建立在它的读数上。

## 侦察结论（193 已核实，不是假设）

- `architecture.md` **没有模块章节**；`report.architecture.chains.rails` 只有 loads 计数没有
  members。「模块清单一源」的落地路径定为：**`modules[]`（basis=page/connectivity）打底 +
  `design-intent.blocks[].parts` 覆盖**（ROBOT 有契约、毕设FOC 没有——无契约板自动退打底）。
- 规则执行：`engines/review.py::BUILTIN_RULES` 手写有序列表（21 条），`Rule.check(model)`
  吃的是**原理图** DesignModel；`checkup` 恒走 `CHECKUP_VIEW="schematic"`。
- finding 合同：`Finding.asdict + refs` 进 `findings[]`——**review-mark 和 warning_triage
  都消费它，PCB finding 必须进同一数组**，进数组后模块归因自动接上（`module_of[designator]`）。
- `rulebody_fingerprint`（`engines/review_eval.py:1194`）只哈希 `rules/` **直接**放的 `*.py`，
  子包不在配方里——不扩配方，报告版本号会说谎。
- `completion.verdict` 算术在 `cli.py::_build_completion`；新增判据属于语义扩展，
  **bump schema 到 `boardwise.checkup/7`**（090 加读数段不 bump 的先例不适用于 verdict 语义）。
- `mayClaimPassed` 窄义不动（datasheet 闸），PCB 侧表达走 `completion.verdictWhy` 加条。
- 报告段纪律：**缺席而非空**（`layout_review`/`architecture` 先例）。

## 架构钉死（不许漂移）

1. **平行 runner，不碰原理图侧**：新 `src/boardwise/engines/pcbreview.py`，
   自有 `BUILTIN_PCB_RULES` 有序列表与结构闸；**不改** `BUILTIN_RULES` 的 21 条与
   `len(ids)==21` 的钉。PCB 规则基类 `PcbRule` 放 `src/boardwise/rules/pcb/base.py`：

   ```python
   @dataclass PcbReviewContext:
       board: BoardGeometry          # 某一 PCB 文档的几何
       board_title: str              # 如 "PCB1"
       model: DesignModel            # 同工程的原理图模型（模块归因/电源网识别用）
       intent: DesignIntent | None   # design-intent 契约（无则 None，规则走 UNKNOWN 纪律）
       module_of: dict[str, str]     # 位号 → 模块名（来源见钉 2）

   class PcbRule:
       id: str = ""        # 前缀 pcb-，如 pcb-decap-distance
       title: str = ""
       source: str = ""    # 阈值出处：IPC-2221 / house rule / oracle ruling（写明待裁状态）
       def check(self, ctx: PcbReviewContext) -> list[Finding]: ...
   ```

   严重度沿用 `rules/base.py::Severity` 三档（ERROR/WARN/INFO），**不增档不动
   `SEVERITY_ORDER`**；路线图「第二步权重最高」靠报告排序与 verdictWhy 表达，不靠新档。
2. **模块归因**：`module_of` 的构建优先级——`intent.blocks[].parts`（工程师声明）>
   `report.modules[]`（basis=page/connectivity/unattributed）。构建器放
   `engines/pcbreview.py`，纯函数可单测。每条 PCB finding 的 `refs`/`target.component_ref`
   带位号，triage 自动归模块；**不新造模块清单**。
3. **finding 定位扩展**：`Finding.target` 加**可选键**，不加新正则——
   `counterpart_ref: str`（如 "U1"）与 `measurement: {kind, value, unit, layer_ids?}`
   （kind ∈ distance/width/clearance/area...，value 为 mil 或 mil²，unit 写明）。
   既有键语义不动；`test_finding_target_schema.py` 类钉测试同步显式更新（改钉要写理由）。
4. **runner 输入**：离线 `.epro2` → `Epro2Source` → **每个 PCB 文档各跑一次**
   （`extract_board` 公开路径，选文档不用魔法计数——按文档 META title 记名），
   findings 的 `board` 字段写 **PCB 文档 title**（如 "PCB1"），与原理图板 title 区分靠
   文档类型，不另加字段。
5. **报告集成**：新顶层段 `pcb_review`，**缺席而非空**（没跑 ≠ 跑了没事）；
   PCB findings 合并进 `findings[]`；本阶段**不改 verdict**（126d 才接闸，届时 bump /7）。
   段形状：`{available, boards: [{title, components, copperLayers, checksRun: [rule ids],
   findings: [int 索引]}], runner: "boardwise.engines.pcbreview"}`。
6. **UNKNOWN 纪律**：事实缺失（电流/电压/契约）→ `Outcome` 三态同原理图侧，
   UNKNOWN 必须点名缺哪个事实；不许装知道。
7. **阈值出处必写**：每条规则的阈值常量旁注出处；house rule 一律标
   `source="house rule（岳 2026-10 待裁）"`，岳裁后改 `oracle ruling`。

## 分棒（每棒独立子代理，串行）

### 126a 地基（先行，后续棒依赖）

- `rules/pcb/__init__.py` + `rules/pcb/base.py`（PcbRule/PcbReviewContext）
- `engines/pcbreview.py`：`build_module_of(model, intent, modules_section)`、
  `run_pcb_review(source_path, model, intent, modules) -> (list[Finding], pcb_review 段)`、
  `BUILTIN_PCB_RULES`（本棒为空列表 + 结构闸测试钉住「列表即真」）
- `rulebody_fingerprint` 配方扩为**递归**收集 `rules/` 下全部 `*.py`
  （排序用相对路径；指纹值一次性变化写进 PROGRESS 与测试注释）
- checkup CLI 集成：离线 epro2 且含 PCB 文档时跑 runner，`pcb_review` 段 +
  findings 合并；无 PCB 文档时段缺席（两形态各一测试）
- 测试：`tests/test_126a_pcb_review_plumbing.py`

### 126b 距离类规则（通用层 1+9，阈值均为 house rule 待裁）

> **开工前先修 126a 遗留**：runner 调用点从 `modules_section` **之前**挪到**之后**
> （顺序：modules_section → run_pcb_review(modules=真实 modules[]) → drc_summarise），
> 让 `module_of` 拿到 modules[] 那半边；合并 findings 的 base 索引在任何位置都成立，
> 用「PCB finding 计入 summary 且模块归因正确」的测试证明重排安全。
> 同步翻转：BUILTIN_PCB_RULES 空列表钉测试 → 非空有序列表钉。

- `rules/pcb/distance.py`：
  - `pcb-decap-distance`：每个 IC（≥3 脚器件）的每个电源网，找该网上对 GND 的电容
    （复用原理图模型连接关系），量最近电容与本件 `component_distance` 边到边距；
    超阈值 WARN（默认 200 mil，source 标待裁），无电容候选 INFO 点名（与原理图侧
    decap-required-caps 不重复——那条管「有没有」，这条管「贴不贴」）。
  - `pcb-component-spacing`：同 PCB 文档内器件两两边到边距，小于阈值 WARN
    （默认 20 mil）；器件焊盘越出板框 ERROR。
- 夹具锚点：毕设FOC PCB1 出数（打印实际分布，阈值判定正确性用手算例对拍）；
  llc 合成小例钉语义。

### 126c IPC 类规则（通用层 4+8，阈值出处 IPC-2221）

- `rules/pcb/ipc.py`：
  - `pcb-track-ampacity`：IPC-2221 简化式 `I = k·ΔT^0.44·A^0.725`（k=0.048 外层 /
    0.024 内层，ΔT=10°C 默认，1oz），由电流反解所需截面积→线宽；电流来源
    `intent.requirements.signals[].range`（解析 "±3A" 形态）——**无电流事实一律
    UNKNOWN 点名缺事实**，不猜。与 `track_width_stats` 每层最小宽对拍。
  - `pcb-voltage-spacing`：网电压来源 `architecture.rails[].voltage` + intent rails；
    IPC-2221 B4 简化间距表（写出表值与出处注释）；网对压差分档，量
    `net_clearance`，不足 WARN；电压未知 UNKNOWN。
- 测试：合成模型三态齐（VIOLATION/OK/UNKNOWN），ROBOT intent（±3A）做真契约锚点。

### 126d verdict 集成 + 毕设FOC 验收报告

> **主代理裁定（2026-10-07）两条，先读再动手**：
> 1. **闸只管离线**：`源是离线 epro2 且含 PCB 文档 而 pcb_review 缺席 → incomplete`。
>    在线 checkup **不接这条闸**（pcb_review 在线恒缺席是「未实现」不是「未通过」，
>    接闸会把所有在线报告打死）。在线统一路径（bridge 导出 epro2 → 走同一离线 runner）
>    是后续项，本棒只在 PROGRESS/路线图记录在案。
> 2. **UNKNOWN = INFO finding 点名缺事实**（126c 已钉）；同层相交（overlapping）的网对
>    维持 WARN 且 evidence 注明「同层相交形态，短路判定归 DRC 域」——不加低压豁免阈值，
>    真伪留岳盲审（125b 记录在案：部分 overlap 疑似解析器网名归属问题）。

- `completion` 加判据（按上裁定 1 的精确措辞）；**bump schema → `boardwise.checkup/7`**；
  `verdictWhy` 加条（顺序守既有约定，coverage 原因最后）；
  同步更新所有断言 schema 字符串与 verdict 的既有测试（test_072/073/075/058 等，
  逐条报理由——126c 已改过 073 的退出码两向钉，本棒在其基础上走）。
- 跑毕设FOC 夹具全量 checkup（离线）出模块级报告 `outputs/126/bishe_foc_pcb_c/`，
  打印**模块×finding 矩阵**（每模块：规则 id × severity 计数 + 代表读数）给岳盲审；
  llc 与 ROBOT 夹具各跑一遍做对照（ROBOT 应仍有 6 条载流 ERROR）。
- `mayClaimPassed` 不动。

## 交付纪律（各棒通用）

同 125：pytest `--basetemp=.tmp_pt_home`；焦点先行、全量交卷；禁 git 写；禁改 fixtures；
回收站删除；纯离线零真机；PROGRESS/路线图/提交由主代理收口。
126b/126c 的规则文件与测试文件各自独立，但都要把规则加进 `BUILTIN_PCB_RULES`
（串行执行，无并行冲突）。

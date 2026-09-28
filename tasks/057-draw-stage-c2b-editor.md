# 057：画法编译器 阶段 C2b——多模块落编辑器（真机半）

056（C2a 离线半）已验收落盘（`0459e74`，2230 passed，eval 59/59 双 1.00）。本批是 054 阶段 C2 的**编辑器半**：把页文档落进真实画布，补 056 未做的页级语义，做 CH340G 完整模块集成验收（052 路线阶段 D 的出口）。

056 交接在 `PROGRESS.md` 056 条目与其任务书 §六；页文档 schema 以 `core/pagelayoutplan.py` 实际代码为准（`kind=boardwise-page-layout-plan`，`plan` 字段是完整 053 LayoutPlan）。

**真机纪律 R1–R3 全程生效**：只碰 `test`/`test2` 工程；动手前 `boardwise bridge status`（daemon 会自行死亡，死了先起）+ `doc.list` 焦点工程名逐字对焦；禁地照旧。

## 一、CLI 页级落图（裁决已定，不许推翻）

**不新增命令，不加旗标**：

- `draw compile` 吃同一份 CircuitSpec+PresentationSpec：**PresentationSpec 有 `modules[]` 即走** `pagecompiler.compile_page()`，输出 page.json（页文档）；无 `modules[]` 走既有单模块路径，输出形状一字不变。
- `draw plan` / `draw apply`：检测到输入 `kind=boardwise-page-layout-plan` 即**内部透传 `plan` 字段**交给现有路径（056 落成时 draw apply 就能直接吃 plan，本批是把这层纸捅破 + 真机验证）；旧五种 kind 的单模块 plan 文档行为一字不变。
- 旧 plan.json 的 preconditions 守卫（旧快照失效即拒）对 page.json 必须同样生效——page.json 的守卫证据从 `plan` 字段继承，不新造一套。
- **dsh 工具面本批零新增**（draw 是否暴露 dsh 是岳的显式决定，不在本批）。

## 二、非空页落图（census → keepout）

- 落图前 `canvas_census`（`engines/drawapply.py:821` 既有）拿页上全部既有图元（body/线/文字/标签/旗标），**逐个转 keepout** 喂页级编译（056 的 keepout 冲突规则已离线实现并测，本批是把真机 census 接上去）。
- 验收硬条：落图后**既有图元零改动**——范围外 census 前后对比（数量、坐标、值逐项），一件动了即失败。
- 既有内容罩住全部可行位置 → presentation-poor 点名（离线已有场景 6 同款，真机复现一次）。

## 三、页级 userLock（056 未做项，语义裁决如下）

056 既有行为：模块内锁**随模块平移**（锁的是模块局部坐标）。本批加**页级绝对锁**（锁的是页坐标）：

- 语义：对每个候选代次，模块内编译得到该件局部坐标 L(gen)，页级把该模块 origin 钉为 `P − L(gen)`——**该件在每个候选里都恰好落在页坐标 P**。不同代次 origin 不同是正确行为（锁约束的是件不是框）。
- 钉死参与正常排序，不加优先级特权；钉死导致模块框越界/穿 keepout/与钉死的其它模块冲突 → 该候选非法，全部非法 → presentation-poor 点名锁。
- 锁点必须落页内；同一模块被多把页锁钉出矛盾 origin → presentation-poor 点名两把锁。
- 模块内锁与页级锁可共存（模块内锁管局部，页级锁管绝对），两者指向同一件时页级锁赢（页级是后陈述）。

## 四、G4 findings 工程级合并（056 离线地基 → 真机验收）

056 地基：共享网从 CircuitSpec **推导**；同名网在 plan 里 = 同一 `net` 字段上的多个 LayoutLabel/PowerSymbol；`readability.derive_netlist` 按名并联；合并图九条（含 `netlist-partition-mismatch`）已闸。054 C7 实测编辑器网表是工程级。

本批真机验收语义（写死）：

- 多模块 page 落图后，**编辑器网表回读**证明共享网是一网（同名 label 在工程级合并，不是两岛）。
- `draw apply` 的 findings 机制（`baseline_findings` / `findings_read`，既有）对 page.json 同样生效；落图完成后重跑相关 review 规则：**plan 声明要解决的 findings 消失、无新增 findings**——"只减不增"按 finding 身份（kind+subjects）判，不按计数判（计数会撒谎：修一个引入一个计数不变）。

## 五、G5 `draw discard`（显式清理命令）

裁决（已定）：**不做 run 内自动删除**；做显式命令 `draw discard <plan.json|page.json>`。

- 删除前**按 plan 的 draw_parts/range 证据逐个重新核对身份**：位号 + 值 + 坐标回读三者一致才动；任何一件身份不符 → 整批拒删并报告哪件不符（不删半个）。
- 删除顺序：先线后件（标签/旗标/走线 → 器件）；删完回读证实。
- **幂等**：第二遍 discard = nothing-to-discard（报告零匹配，exit 0）；plan 外的件一片不碰（范围外 census 对比）。
- 保存旗标与 apply 同款（`--save` 才保存；超时/断连先读回，绝不盲目重试——016 家训）。

## 六、CH340G 完整模块集成验收（052 阶段 D 出口）

5–10 件的真实完整模块（CH340G 核心 + 晶振 + 去耦 + USB 接口侧），从 CircuitSpec+PresentationSpec 一路到真机落图：

- 走本批全部新路径：页级 compile → plan → apply → 网表回读 → findings 只减不增 → 渲染图。
- 渲染图主代理亲眼看，按 052 的人工验收问法自答：哪颗电容属于哪路电源？信号怎么走？改到愿意交给同事要几分钟？
- 允许暴露缺口（CH340G 符号真实引脚形状 vs 文法假设）；**缺口如实记，不许为通过而特调场景**（052 原话：不许做成 CH340 专用排版器）。

## 七、056 遗留三项（顺手批）

1. **分压文法 signal 顶**（056 §八(c)2）：`voltage_divider` 补"顶部可为 signal 类网 + 显式端口"分支——信号源驱动的分压当前 facts-missing 编不出来。补文法分支 + 测试；既有 power 顶行为一字不变。
2. **寻路热点正交改进**（056 §八(c)3）：跨模块线拆"端口→本模块框边界直线逃逸 + 两端框之间 gap 带寻路"，搜索面积降一个数量级。目标：场景 7 形状从 10–14 s/变体降到 **<2 s/变体**；**裁决**：允许页级几何哈希因此变化，但必须逐场景申报前后差异（哪条线路径变了、为什么更短/等价合法），主代理裁；模块内 12 场景哈希**不许变**（模块内寻路不动）。
3. **`generate.py:53` 希腊 mu hint**（defect 批遗留）：`_DECOUPLING_HINTS` 子串提示不识 U+03BC 拼法——与 `rules/values.py` 同款归一（一行级 + 一测试）。

## 八、场景（真机 ≥6 + 离线增量，分母含拒绝钉死）

| # | 场景 | 期望 |
|---|---|---|
| E1 | 空页多模块落图（LDO+分压 page.json 全链） | compile→plan→apply→网表回读→渲染亲眼；保存后重开仍在 |
| E2 | 非空页落图（页上预置既有内容） | census→keepout 生效；范围外零改动实测 |
| E3 | 页级 userLock | 锁件回读坐标 == P；冲突情形 presentation-poor 点名 |
| E4 | G4 工程级合并 | 共享网回读一网；findings 只减不增按身份判 |
| E5 | `draw discard` | 删除回读证实；第二遍幂等；身份不符整批拒删；范围外零碰 |
| E6 | CH340G 完整模块（§六） | 全链通；渲染亲眼看；缺口如实记 |
| E7 | 过期 page.json 守卫 | 改动画布后 apply 旧 page.json → preconditions 拒，不写不保存 |
| O1 | 分压 signal 顶（离线） | 新分支出图；power 顶既有场景哈希不变 |
| O2 | 寻路改进（离线） | 场景 7 形状 <2 s/变体；页级哈希差异逐场景申报 |

真机渲染至少 E1/E6 两张主代理亲眼看。

## 九、守卫与复验

- 定向 pytest `--basetemp=.tmp_pt_78`（执行者独立）；**全量归主代理**。eval holdout 59/59 双 1.00 红线。
- **053B 12 场景 + 056 8 场景硬不变量**：模块内 12 场景几何哈希逐字节不变（不许碰）；页级 8 场景除 O2 申报外不变。
- 变异 ≥2 组（建议：keepout 注入 census 退空表 → E2 形状必须红；discard 身份核对退恒真 → 身份不符场景必须红），cp 备份 + sha256 还原。
- 零 git 操作；不碰 README/PROGRESS/reviewsets/tests/fixtures 既有夹具、`engines/readability.py` 九条语义、`core/pagelayoutplan.py` schema（如需增量先申报——schema 变 = digest 变，056 硬不变量全破）。
- connector/daemon/dsh 零改动（仍是 0.4.25 真机）；CLI 只动 `draw` 子命令家族。
- **子代理上下文 500k 红线**：执行者自报 token_counting，接近即停批换 resume；主代理定期查 wire.jsonl。

## 十、交卷

- 数据流（census→keepout→页级编译→锁钉 origin→落图→回读→findings 合并→discard）+ E/O 场景逐条实测表 + 渲染清单。
- 自决项逐条；文件 sha256(12) 前后；定向计数；变异组与还原哈希；真机守卫对焦记录（每次 bridge status + doc.list 原文）。
- 给 058 的交接：页级落图后暴露的缺口清单（CH340G 集成发现、寻路改进残余热点、dsh 暴露 draw 的决策输入）。

## 十一、交卷记录（2026-09-28，执行者：离线半全部落码；**真机半未执行**——本机无立创 EDA Pro）

**真机守卫对焦记录（原文）**：`boardwise bridge status` →
`boardwise bridge: daemon not reachable on 127.0.0.1:61190 ([WinError 1225] 远程计算机拒绝网络连接。)`；
本机 `Get-Process` / 卸载表均无 EasyEDA / 嘉立创 EDA，`~/.boardwise` 无 connector 配对。按 R3（目标缺失不自行替代）
**未做任何真机动作**：E1–E7 的真机半一条都没有结论，已写成可逐步照做的清单 `tools/057_live_runbook.md`
（每步写明"看什么算过"）。下文 E 场景的"实测"一律指**假编辑器实测**（页面真写、真读、真删，稳定 primitive id）。

### 数据流（本批接上的那一段）

```
draw plan --page ──► doc.list/doc.focus ──► sch.geometry（census）──► sch.geometry{bboxIds}（实测外框）
   └► drawapply.census_keepouts：每个既有件/线段/旗标 → keepout（+1 格间隙；未测到外框的 ±50 并注明）
   └► pagecompiler.compile_page(relocate_around_keepouts=True)
         ├ 页级锁：origin = P − L(代次)，锁住的框出页/压 keepout/互撞 → presentation-poor 点名锁
         ├ 未锁模块按 056 网格排，刚体平移避开 keepout 与锁住的框（找不到 → 056 原样的 keepout 冲突拒绝）
         └ 九条 + 页级八条双闸（九条的 user-lock-violated 独立复核页锁）
   └► drawapply.module_plan(page.plan, label_stubs=True) → draw-module plan（+ <plan>.page.json）
draw apply ──► 原 054 流程（守卫/探针/放件/写值/引脚回读/拉线/旗标/双证）
   └► 新：范围外逐项对比（census_items 前后，按 primitive id，自动网名不计）→ 改一件 exit 2 不保存
   └► 新：verification.nets（逐网活网表名、crossModule、oneNet）；findings 按身份只减不增（既有）
draw discard ──► discard_selection（位号+坐标+值 / 旗标网+点 / 线全部点在 plan 线上）
   └► 任何不符整批拒删 → 先线、再旗标、后件 → 回读：目标全无 + 范围外逐项不变 → --save
```

### 场景逐条（E = 假编辑器，O = 离线）

| # | 结果 | 证据 |
|---|---|---|
| E1 空页多模块落图 | 假编辑器全链 exit 0：compile→plan(page)→apply(`--layout plan.page.json`)，VIN/GND `crossModule` 行 `oneNet=true`，`outOfScope.changed=[]`，保存+出图；**真机：未执行**（重开仍在、渲染亲眼看待补） | `test_e1_an_empty_page_lands_the_whole_page_and_reads_the_shared_nets_back` |
| E2 非空页 | census 三件（件/线/旗标）全转 keepout 并点名来源，页整体右移避开（框不压任何 keepout），落图后三件逐字段不变；census 罩满 → exit 5 `presentation-poor` 点名 `existing R1…`；宿主把新线并进旧线 → exit 2 `range_out_of_scope` 不保存 | `test_e2_*`×3；`outputs/057_offline/E2_census*`（离线预览亲眼看：页在红框右侧） |
| E3 页级锁 | R1 锁 (800,500) → plan 里 R1 在 (800,500)，apply 后假编辑器读回 (800,500)；两锁矛盾/锁点出页/锁框出页 → exit 5 点名 `userLocks[R1@page]` 等；离线另测锁压 keepout、两锁框互撞、模块锁+页锁共存、九条独立复核 | `test_e3_*`；`test_057_page_offline.py` 锁 9 例；`outputs/057_offline/E3_*` |
| E4 G4 | 共享网回读一网（E1）；共享网两端没合并 → exit 3 不保存；"修一个引入一个"（计数不变、身份变）→ exit 2 `new_findings`；解决一条 → `resolved` 列出 | `test_e4_*`×3 |
| E5 discard | 删除顺序 wires→flags→parts，回读全无、范围外逐项不变、`--save` 才保存；第二遍 `nothing_to_discard` 零删除；值被改/件被挪/线被并 → exit 4 零删除；删除超时 → 回读、不重试、exit 3；页文档按坐标删 | `test_e5_*`×7；变异 M2 |
| E6 CH340G | **编译阶段即被挡住（如实记，未特调）**：金样板真实符号 9 件"核心+晶振+去耦+USB"，核心/晶振/USB 三组**无文法** → `facts-missing` 点名三模块；每组×每文法的绑定器答复见证据；金样板唯一有文法的模块 RT9013 LDO（VIN/GND/EN 同在左侧）在 `ldo` 文法下 **48 种 sidePreferences 全部无合法姿态** | `outputs/057_offline/E6_ch340g.txt`（`tools/057_scenarios.py`） |
| E7 过期守卫 | `draw plan --page` 产的 plan，页面被加件 → exit 4 `canvas_changed` 零写入；页文档直落而框下被放了件 → exit 4 点名那件；页文档源哈希对不上 → exit 4 且**不连 daemon** | `test_e7_*`×2 + `test_a_page_document_compiled_from_other_specs_is_refused_offline` |
| O1 分压 signal 顶 | 显式输入端口（portRoles/openInterfaces 为 input/source）的 signal 顶可绑定并出图（顶是端口标签不是旗标）；未声明 → 原 facts-missing 一字不变；有 power 链时 power 读法优先 | `test_o1_*`×3；`outputs/057_offline/O1_*` |
| O2 寻路热点 | 场景 7 形状：寻路那一变体 **~9 s → 1.2 s**（全编 9.1 s → 1.3 s，同机同刻对照），<2 s/变体达标；**页级几何哈希零变化**（带/不带 memo 两次编译的页文档逐字节相同，测试钉死） | `test_o2_*`×2；`outputs/057_offline/O2_timing.txt` |

**硬不变量**：053B 12 场景 + 056 8 场景的完整 plan/页文档 JSON（不止哈希）与批次开始的 pristine 副本逐字节相同
（`hashes_before.json` vs 改后，每加一块复跑一次，全程 IDENTICAL）；`pagelayoutplan.py`、`readability.py`、
`drawcompiler.py`、`svgpreview.py` sha256 前后相同（未碰）。离线证据 `tools/057_scenarios.py` 两遍产物逐字节相同。

### 渲染清单

离线：`outputs/057_offline/E2_census_cand1.{svg,png}`、`E3_lock_cand1.{svg,png}`、`O1_declared_cand1.{svg,png}`
（headless Edge 转 PNG 后亲眼看过：E2 页落在既有图元右侧、E3 R1 在锁点、O1 顶部 SENSE 端口标签）。
**真机 E1/E6 渲染：无**（E1 待真机；E6 编译即拒，无图可渲）。

### 自决项

1. **"有 modules[] 即页级"的读法**：≥2 模块 / 有 `flow` / 模块自带 `grammarRef` / 有页级锁 才走页级
   （`pagecompiler.wants_page`）。054 夹具本身就是"一个 module 的单模块文档"，字面读法会把它改道，违反"单模块输出一字不变"。
2. **页文档直接 `draw apply`**：必须 `--circuit/--presentation/--profiles` + `--page`/`--new-page`，运行时用同一个
   `module_plan` 现建 plan 再走原流程；源哈希不符在连 daemon 前 exit 4。它的"过期守卫"是**框对页面现状的 keepout 规则**
   （页文档不带 census，schema 冻结不加）；要"任何变动都拒"用 `draw plan --page` 产的 plan（census 摘要）或 `--expect-census`。
3. **`--layout` 接受页文档**，digest 其 `plan` 字段（守卫证据继承，不另造）；`draw plan`（页）旁写 `<plan>.page.json`。
4. **页级锁的形状**：`userLocks[]` 加 `"scope": "page"`（052 §4"坐标只在 userLocks"不破）；页锁只钉位置、**拒绝 rotation**
   （位姿归模块，要钉位姿同件再加模块锁）；每件每 scope 至多一把；模块锁序列化不加 `scope` 键 → 既有 spec digest 不变。
   "两者指向同一件时页级锁赢"落为：件的页坐标 = P（origin 由页锁推），模块锁只管模块内排布，两者由九条同时独立复核。
5. **锁冲突种类放在页编译器**（`page-lock-contradiction` / `page-lock-conflict`），不进 `readability.py`（九条语义与页级八条都不动）；
   无候选时锁类拒绝排在 keepout/main-path 之前报。
6. **census 避让是开关**（`PageCompileBudget.relocate_around_keepouts`，默认关）：默认保持 056 语义（场景 6 契约：keepout 是锚定排布
   不得碰的保留区）；CLI 只在 census keepout 时打开。实测场景 6 开/关都拒（其 keepout 盖住所有可行位置），仍按开关保守处理。
7. **census→keepout**：件/旗标用 `bboxIds` 实测外框（第二次 `sch.geometry`），读不到的按原点 ±50 假定框并在 notes 点名；
   线逐段成框；统一外扩 1 格（让零宽线段有面积）。
8. **范围外逐项对比对所有 `draw apply` 生效**（单模块也是）：它只在既有图元被改时拒绝，旧流程在这种情况下本就是事故；
   线的**自动网名**不计入身份（坑 25：别处布线会让宿主重编自动网名），命名网照比。
9. **页标签的具名短线**（`module_plan(label_stubs=True)`，仅页级路径）：页在裸引脚尖上放的标签，本机放不了（坑 9），
   不补线则该脚是无名网、两模块同名网合不起来（G4 直接失败）。单模块路径同样存在此缺口，**本批未动**（输出一字不变），记 058。
10. **G4 "plan 声明要解决的 findings"**：draw-module 这一 kind 没有"声明要解决"清单字段（054 未设）；本批按既有集合语义判身份
    （`rule|severity|位号|脚|命名网`）只减不增，报告 `resolved`/`new`；未新增 plan 字段（避免改 changeplan schema）。
11. **discard 身份三腿**：位号 + 坐标（半格）+ 值（055 起写入的 `Value`；无 `valueKey` 的旧 plan 用 LCSC）；页文档无位号 → 按坐标 +
    前缀 + 值；线要求**每个点**都在 plan 自己的线上（被宿主并进别人线的 primitive 不删，整批拒）；每相每调用 ≤30 id，分批写进报告。
12. **O2 用精确 memo 而不是"逃逸+gap 带"拆分**：热点在路由器逐节点重复扫障碍/外线，`_PageRouter` 只缓存父类的答案 → 路径逐字节不变、
    时间降 7–10 倍，已达 <2 s/变体；拆分方案会改场景 7 第 5 页两条线（等长、3V3F 少一个 5 单位小折），收益不足以换哈希变化，
    **未实施**，搜索面积本身未降（残余热点记 058）。
13. **O1 的"显式端口"**：portRoles 或 openInterfaces 方向为 `input`/`source`；只在 power 分支找不到链时才查 signal 顶。
14. **希腊 mu hint**：只折 U+03BC→U+00B5（与 `rules/values.py` 同款），大小写敏感性不动。
15. **dsh 工具面零新增**（任务书裁决），SKILL §7 的"新功能同步 dsh"在此注明不跟的理由；新增 CLI 仅 `draw discard`（draw 家族内）。

### 文件 sha256(12)

| 文件 | 前 | 后 |
|---|---|---|
| `src/boardwise/cli.py` | 0603cb1e7b88 | a91a3c3cf80b |
| `src/boardwise/core/presentationspec.py` | 9c634570dc88 | 8600a5b797a2 |
| `src/boardwise/engines/drawapply.py` | ba6b3a20ac49 | 82b3419be5ea |
| `src/boardwise/engines/generate.py` | 58cb39675dbc | 44c4c3f281e4 |
| `src/boardwise/engines/grammar/voltage_divider.py` | 144d9d9f601f | 781cf1d33156 |
| `src/boardwise/engines/pagecompiler.py` | 9e976a3d6372 | d2738feb17c4 |
| `.kimi-code/skills/boardwise/SKILL.md` | db6e4cc8afd4 | fc461d641f62 |
| `docs/draw.md` | 322730c87a64 | a4f84cdae046 |
| `tests/test_057_draw_page_cli.py` | (新) | 345152052ebb |
| `tests/test_057_page_offline.py` | (新) | 2e6824ee87a6 |
| `tools/057_scenarios.py` | (新) | 0d3d82ba7057 |
| `tools/057_live_runbook.md` | (新) | e2ccbc425fc4 |
| `core/pagelayoutplan.py` / `engines/readability.py` / `engines/drawcompiler.py` / `engines/svgpreview.py` | 4005668f12d9 / fd97b8e19081 / a089ec987d02 / c98addde0333 | 同左（未碰） |

### 计数与复验

- 新增测试 **64**（`test_057_draw_page_cli.py` 29、`test_057_page_offline.py` 35）；定向回归 053a/053b×3/054×2/056/dsh 同步/动作目录/generate **329 passed**（`.tmp_pt_78`）。
- 全量（`--basetemp=.tmp_pt_home`）：**2286 passed, 1 skipped, 19 failed**；19 条全部环境性、改动前基线就在：
  11 条 `test_017` 引用 gitignore 的 `outputs/0xx_*.txt` 证据（新克隆没有）；8 条 `test_016/test_018` 用 1970 年 `os.utime`，
  本机 D: 是 **exFAT** 不收（同 8 条 `--basetemp` 放 NTFS 盘 33/33 过）。基线（改动前）同环境 2219 passed / 20 failed（多出的 1 条是
  `connector/dist` 未构建，本批 `npm ci && npm test` 构建后转绿）。
- connector `npm test` **419/419**、`tsc --noEmit` 干净；dsh-plugin typecheck/build 干净、**48 passed + 1 skipped**（两者均未改）。
- **eval holdout 59/59 双 1.00**（defect detection 59/59、high-priority precision 59/59），输出与 pristine 副本逐行相同。

### 变异组（cp 备份 + sha256 还原，无 git）

| 组 | 变异 | 结果 | 还原 |
|---|---|---|---|
| M1 | CLI 把 census keepout 退成空表 | E2 2 红 CAUGHT | cli.py 97ffb90ba5f0 → 7b2abb11d332 → 97ffb90ba5f0 |
| M2 | discard 身份核对退恒真 | 4 红 CAUGHT | drawapply.py 6b3af01a7bd4 → b622d30a4c84 → 6b3af01a7bd4 |
| M3 | 页锁不推 origin | E3 2 红 CAUGHT | pagecompiler.py 71998d869dbb → a89d69de7b6c → 71998d869dbb |
| M4 | 范围外逐项对比恒"无变化" | 2 红 CAUGHT | drawapply.py 6b3af01a7bd4 → c117fc1275f4 → 6b3af01a7bd4 |
| M5 | 页标签不补具名短线 | 1 红 CAUGHT | drawapply.py 6b3af01a7bd4 → 3b4596ee254b → 6b3af01a7bd4 |

（变异时的文件哈希是当时版本；之后 drawapply/cli/pagecompiler 各有一处收尾改动，最终哈希见上表。）

### 给 058 的交接（缺口清单）

1. **E6 的根**：没有"IC 核心 + 去耦 / 晶振 + 负载电容 / 连接器侧"文法——CH340G 完整模块在编译阶段 `facts-missing`；
   这是 052 阶段 D 出口的真正阻塞（不是排版器调参能解的）。
2. **`ldo` 文法 vs 真实 LDO 符号**：金样板 RT9013（VIN/GND/EN 同侧）48 种 sidePreferences 全无合法姿态；坑 33 的"改输入侧"对它无效。
3. **单模块路径的标签也会落成无名网**（单脚 signal 网的标签被降级且无线承载）；本批只在页级路径补具名短线，单模块待定。
4. **O2 残余**：搜索面积未降，走不通 elbow 的跨模块线仍全走廊 Dijkstra；"逃逸+gap 带"拆分的实测对比见自决 12。
5. 056 行为观察（未改）：页在已有同网导线的引脚尖上加的标签，文字框会压在本模块那段线上（E3 预览 pwr 模块 VIN 处可见）。
6. **dsh 是否暴露 draw 的决策输入**：draw 家族现有 4 个子命令（compile/plan/apply/discard）全部离线或经 bridge；discard 是写动作
   （删），若暴露给 dsh 需要与 apply 同级的确认闸。
7. **真机半全部待补**：`tools/057_live_runbook.md` 逐步清单（R1 对焦、实测库、E1–E7 看什么算过）。

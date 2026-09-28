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

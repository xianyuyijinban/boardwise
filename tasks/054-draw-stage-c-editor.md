# 054 · 画法编译器 阶段 C1：LayoutPlan 落图进编辑器（单模块）

日期：2026-09-27 深夜。前置：053 阶段 A/B 全部收官（三份数据合同 / 三种语法 / 独立检查器 / 主编译器 / 12 场景 9 过 3 拒，main `362f281`）。052 路线表阶段 3：**接入编辑器——放置、实际引脚回读、布线、最终渲染、保存**。本任务书是第一刀（C1）：**单个语法模块**落进 test 工程的一页。多模块互连、人工锁定布局、增量编辑归 C2 以后。

## 一、目标与边界

把 `compile()` 产出的一个 LayoutPlan 候选，经 ChangePlan 机器真机落成编辑器里的真实图元，并做到 M3 同级的四个保护：

1. apply 前重新核验：源哈希（circuit/presentation/profiles 摘要）与页身份不符 → stale，exit 4 零写入。
2. 只写 plan 声明的图元，范围外不动。
3. 放置后回读实际引脚位置与 plan 期望比对，不相信 API 返回值。
4. 超时/断连先读回，绝不盲目重试；保存验证区分 `placed / saved_unverified / saved_verified / unknown`。

**边界（C1 不做）**：多模块互连与跨页标签；userLock 落图；PCB 侧；dsh 工具面新增 draw（真机写操作，是否暴露给 dsh 由 xianyuyijinban 另行决定）；connector 新动作（默认零新增，探测证明必须时**停下来申报**，不自行加）。

## 二、现状资产盘点（复用，不重造）

| 资产 | 出处 | 用途 |
|---|---|---|
| `compile()` → LayoutPlan（正交折线/文字 bbox/旗标约定 PWR-GND·PWR-VIN/位号=CircuitSpec id 待重编号） | 053B | 输入 |
| `ChangePlan` + plan/apply 机器（postconditions 幂等判据、stale exit 4、findings 只减不增） | 016/029/036 | 骨架 |
| `sch.place_component`（029 真机）+ `designator_pool`（页面 ∪ 工程导出，036b 共用函数） | 029/036b | 放置 |
| `engines/layout.wire_route` 正交走线（宿主不拖线、上报线是点集非路径——坑 26） | 036/037 | 布线 |
| `sch.place_power` 旗标（029 probe 过）；**`place_netlabel` 本机不可用**（029 入账） | 029 | 地/电源/标签 |
| 活网表逐脚岛屿比对（037 主判据）；导出新鲜当且仅当本 run 无删除（035 分家定案） | 037/035 | 验收 |
| `export.render`（033/034 修复后可用：导出前自激活三步） | 033/034 | 最终渲染 |
| 宿主坑表：doc.new name 被忽略（坑 24）、撞全局位号被静默改名（坑 25 位号池）、findings 换措辞与自动网重编号不算新增（坑 25） | SKILL §坑 | 守卫 |

## 三、设计（数据流与关键映射）

```
CircuitSpec.json + PresentationSpec.json（手写或模型产）
  → draw compile（离线）→ CompileResult：ranked[LayoutPlan] + 四分类失败
  → （预览：outputs/ SVG，人/AI 选一候选，默认 ranked[0]）
  → draw plan --candidate N → ChangePlan(kind="draw-module")：
      source：circuit/presentation 双 spec 的 sha256 + profiles 的 geometry_hash 表
      page：目标页身份（聚焦页 uuid；新建页时先建页记 uuid——doc.new name 被忽略，uuid 才是身份）
      parts[]：{specId, prefix, libDevice/libSymbol 身份, profile geometry_hash, pose(x,y,rotation,mirror)}
      wires[]：plan 正交折线逐段（点集语义，坑 26）
      flags[]：{netId, symbolRef 或 label 降级, position}
      postconditions：每 part「位号已放且引脚回读=plan 期望（容差半格）」+ 每 wire「已落」+ 活网表逐脚=plan 网表
  → draw apply（真机，test 工程）：
      0. 守卫：双 spec 哈希仍一致、页 uuid 仍在、设计图元基线计数；不符 → stale exit 4 零写入
      1. 库符号核验：逐 part 实测库符号几何 vs profile.geometry_hash —— 不符拒绝并点名
         （换脚号迁就版式检测是 SymbolProfile 既有职责，几何不符时 pin tip 必然错位）
      2. 位号分配：designator_pool 按 prefix 取号（撞全局位号静默改名=坑 25，池必须含工程导出）
      3. 放置：sch.place_component 按 pose
      4. 引脚回读：读 placed primitive 实际引脚坐标 vs plan pin tip，偏差>半格 → 失败退出，
         报告现场（已放什么/没放什么），不盲目清理不重试（016 保护 4）
      5. 布线：wire_route 按 plan 折线逐段
      6. 旗标：place_power；plan 里的 net label → C1 一律走旗标或 stub（place_netlabel 不可用），
         报告里声明降级（不许静默换语义）
      7. 验收主判据=活网表逐脚岛屿比对（037）；几何差异=导出解析 vs plan（本 run 有删除才导出核对——035 分家）
      8. 保存 + 重开/重导出指纹 → saved_verified / saved_unverified
      9. findings 只减不增（036 规矩，签名=rule|severity|component|pins|命名网）
      10. export.render 最终渲染落 outputs/054_*/，报告附图（xianyuyijinban 要看图不看数字）
```

重复 apply = already_applied 零写入（postconditions 判据，016/029/036 先例）。

## 四、工作项分解

1. **`engines/drawapply.py`**（离线大头）：LayoutPlan + 库符号数据 → ChangePlan；位号映射；postconditions 生成；守卫核验逻辑（哈希/页/基线）。
2. **CLI `draw` 命令组**：`draw compile --circuit C.json --presentation P.json [--out]`（打 ranked 表+失败四分类+落 SVG 预览）、`draw plan`（→ ChangePlan JSON）、`draw apply --project test`（真机执行+报告）。复用 changeplan 机器与 edit apply 的退出码语义（0 ok / 3 verification_disagrees / 4 stale / 5 拒绝）。
3. **离线测试**：plan 确定性（同输入逐字节同 plan）、守卫拒绝路径、位号映射、降级声明、postconditions 与 036 判据同构。
4. **真机用例 ×7**（§五）。
5. **文档同步**：SKILL（draw 流程+新坑）、README/docs 模块树（连 053 两批一起补——053B 欠账）、PROGRESS。

## 五、真机验收用例（全部只碰 test 工程）

| # | 用例 | 通过判据 |
|---|---|---|
| C1 | 分压模块（10k/10k + VIN/GND 旗 + TAP stub）落新页 | 网表逐脚=plan；引脚回读零偏差；saved_verified；渲染图可读 |
| C2 | RC 低通模块 | 同上；支路电容归属 out 侧 |
| C3 | LDO（AMS1117 + 10u/100n + 3 旗标） | 同上；电容各归各侧 |
| C4 | C1 重复 apply | already_applied，零写入，无重复器件/导线 |
| C5 | 手工改动画布后 apply 同 plan | stale exit 4，零写入 |
| C6 | 库符号几何不符（plan 用 profile A、库里实测成 B） | 拒绝并点名器件，零写入 |
| C7 | apply 中途拔 daemon（模拟中断） | 重跑先读回、不重复创建；报告现场状态为 unknown 或据实分档 |

## 六、变异与复验纪律

- 变异 ≥2 组（建议：引脚回读判据退化为恒真 → 必须红；位号池退回页面级 → 必须红），cp 备份 + sha256 还原。
- 定向 pytest 各自 basetemp；全量归主代理；eval holdout 59/59 双 1.00 红线不破。
- 四线：pytest / connector 419（零改动也要复跑确认）/ dsh 48+1 / tsc。

## 七、守卫

- 真机只碰 `test`/`test2`；动手前 `bridge status` + `doc.list` 焦点工程名逐字对上；**禁地**：毕设FOC驱动板、ROBOT ctrl FOC、CH340G.eprj2 及一切真实工程。
- 不碰 tests/fixtures 既有夹具、reviewsets 标注；离线用例新夹具放新目录。
- 失败报告四分类沿用（draw apply 新增执行态失败单独记账，不混进编译四分类）。
- 渲染图、回读数据、网表比对落 `outputs/054_*/`，报告可复核。

## 八、遗留（C2+ 候选）

- 多模块互连 + 跨页标签策略（labelPolicy 真启用）；userLock 落图；CH340 完整模块集成验收（052 路线阶段 4）。
- place_netlabel 若上游修复则去降级；`adjacent` 严读；模型成本对比实验（052 §8 阶段 E）。

## 九、交卷记录（2026-09-28，agent-72 执行 / 主代理复验，agent-73 注册表补齐时核校）

### 交付物

- `engines/drawapply.py`（新，1244 行）；`core/changeplan.py` 增第六种 kind `draw-module`（旧五种序列化逐字节不动）；`cli.py` 增 `draw compile/plan/apply` 命令组（退出码 0/2/3/4/5 与 edit 家族同义）；`tests/test_054_drawapply.py`（52）+ `tests/test_054_draw_cli.py`（26）+ `tests/fixtures/drawapply/`（新）；SKILL 坑 29–34；`docs/architecture.md` 同步。
- 数据流：`draw compile`（ranked+四分类+SVG/布局落盘）→ `draw plan`（候选→ChangePlan：配方/位号池[页面∪工程导出]/旗标与降级声明/库几何表/引脚偏移期望/netlist 岛屿期望/普查基线）→ `draw apply`（守卫→探针→位号→放件→**拉线前引脚回读**→走线→旗标→双证回读→范围→findings 只减不增→保存→出图）。

### 真机用例结果（test 工程，证据 `outputs/054_c1|c2|c3|c6|c7/`）

| # | 结果 | 证据 |
|---|---|---|
| C1 分压 | applied + saved + 双证回读零差异（渲染图是 apply 后 2 分钟单独补出，`export.render` 需 `params.format` 词表 `png|svg|pdf`） | `054_c1/apply_report.json` + `render.png` |
| C2 RC 低通 | applied + saved，支路电容归 OUT 侧回读通过 | `054_c2/apply_report.json` |
| C3a LDO 10u/100n | **refused_by_design**：图落好（11 写：3 件 5 线 3 旗）、双证过，工程自身 `decap-required-caps` 涨 finding → exit 2 **未保存**；注意这是注册表里唯一"护栏在写入之后触发"的拒绝（件留在页上未清，P7 页留作活证据） | `054_c3/apply_report.json` |
| C3b LDO 合规配方（输出 100n→**22u**，C4=10u/C5=22u/U2） | applied + saved，`resolved: 1, new: 0`（C3a 的 finding 因工程级同名 3V3 合并被消掉） | `054_c3/apply_report_C3b.json` |
| C4 同 plan 复跑 | already_applied，write.calls=0，六条守卫全 checked | `054_c1/apply_report_C4.json` |
| C5 手工挪 R1 后同 plan | part_present_unfinished exit 4 零写入；件移回原位复跑 already_applied | `054_c1/apply_report_C5.json` |
| C6a 改 profiles 文档 | guard_refused exit 4 零写入，点名两个哈希 | `054_c6/apply_report_C6a.json` |
| C6b 实测库几何≠plan | 引脚回读不符，拉线前停（2 件已放 0 线未保存 exit 3，不盲目清理）；注册表按设计内拒绝记 | `054_c6/apply_report_C6b.json` |
| C7 拔 daemon | 该 run 报 unknown exit 3 未保存不重试（audit 显示 unknown 出自 live-netlist 腿，daemon 死亡发生在 run 完成后——"中途拔"按 §五 C7  wording 登记，证据如实注记）；重启后复跑先读回 → already_applied 零写入、无重复件 | `054_c7/apply_report_C7.json` + `_rerun.json` |

### 真机新事实（五条入 SKILL 坑 29–34，另两条记账）

1. 宿主 `(rotation, mirror)` 是 `mirror_x ∘ CW(R)`（先转后镜像），镜像姿态交原角；`_editor_rotation` 取负只对 `mirror=False` 成立（C1 首跑由引脚回读抓出两脚对调）。
2. 编辑器网表是**工程级**：同名网跨页合并；模块验收的成员关系改在 plan 自己的引脚集合内判，集合外只报 `sharedWithOutsidePins`。
3. `export.render` 的 `format` 词表 `png|svg|pdf`；给 `image/png` 回 BAD_REQUEST。
4. 落图前必须先量符号库（编辑器不给库几何）：探针放件→`sch.component_pins`+`bboxes`→删探针→写 `SymbolProfile`（AMS1117 三颗 C6186/C351785/C5205141 同族：VIN/VOUT/GND 全单侧 + 右侧重复 VOUT；默认 in左/out右 **无合法姿态**，`sidePreferences.output=bottom` 后 3 候选通过——改的是输入 presentation，不动编译器迁就符号）。
5. 本仓 facts 要求 AMS1117 输出 ≥22µF；053 场景的 100n 输出在真机必被自己的规则挡在保存前（C3a 即此）。
6. 页标签会被回收复用（删除后 P6/P7 名字再现），台账不记页名记 pageUuid。
7. `saved_verified` 不可达：本桥无 close/reopen 动作（009d），applied 一律 `saved_unverified`，与 016 同级。

### 复验

- 定向 78（drawapply+draw_cli）+ 相邻家族 125 绿；connector 419/419、tsc 干净；dsh 48+1、build 干净。
- 变异 3 组 CAUGHT（M1 引脚回读退恒真→2 红；M2 位号池退页面级→2 红；M3 普查守卫短路→1 红），均 sha256 还原。
- 注册表（agent-73）：`draw-module` 入 `FIX_SUCCESS_KINDS` 末位，10 行 FixCase（3 attempts/3 applied，总账 17/15），`test_017_eval_metrics.py` 78 绿，变异 2 组 CAUGHT。
- 全量 pytest 与 eval holdout 由主代理亲跑，结果记 PROGRESS 054 条。

### 自决项（主代理全批）

1. draw-module 为 core 第六种 kind，旧五种序列化逐字节不动。2. C6 写前腿用 `--profiles` 库文档，编辑器侧由引脚回读判定。3. 活网表腿收窄为 plan 引脚集合内分区精确。4. 普查守卫判在探针后、`--expect-census` 在前。5. 未绑页 plan 必须 `--page`/`--new-page`。6. 按 LCSC 放件，无 lcsc 拒绝并给 `--lcsc` 出路。7. `--layout` 可选第五守卫腿。8. 只声明 `saved_unverified`。9. 真机一律实测符号库。10. already_applied 也出图。11. C3 用 `sidePreferences.output=bottom`。12. C3b 换 22µF 合规配方，两变体都入账。13. P7 未落盘图留工程作活证据。14.（主代理）draw-module 入 017 注册表，不豁免。

### 遗留（C2+ 与后续批）

- §八原有：多模块互连 + labelPolicy；userLock 落图；CH340 集成验收；place_netlabel 去降级；`adjacent` 严读；模型成本对比。
- G1：`ldo` 文法核心识别取 id 排序第一个 VOUT 且 `profile_pin_for` 只认 net 成员——重复 VOUT（4 号脚）连网、2 号写 `nc[]` 仍报 neither net member nor nc；给 `nc[]` 一条路或让 `role_pins` 认"任一同角色脚已连"，下批裁。
- G2：`draw apply` 不写器件 `value`，导出 `value=''`、`mpn`=库器件名；`decap-required-caps` 靠 MPN 的 EIA 码读值，解不出判 unknown。加"写 Value"（`sch.set_component_attribute` 既有通道）或接受"值全靠 MPN"，下批裁。
- G3：facts（AMS1117 ≥22µF）与 053 LDO 场景（100n 输出）打架——改场景值或给场景记"示例不追求合规"。
- G4：findings 工程级合并语义（C3b 消 C3a finding）随 labelPolicy 批一起定。
- G5：C3a 形拒绝在写入之后触发、件留页未清——是否加 rollback/清理通道，下批裁（当前靠"未保存 + 页留证据"如实入账）。
- G6：报告文案残留 "M3's live repair results / five slices"（`review_eval.py:1064`、`:866–879` JSON note、`cli.py:3861–3865`）与 register 实际口径不符，随下一批顺手改。

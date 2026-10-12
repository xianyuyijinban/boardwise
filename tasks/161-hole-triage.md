# 161 挖洞审计总账（2026-10-12，六代理并行，岳点名「挖 PCB 审查与原理图绘制的缝」）

纪律说明：全部发现为子代理代码实读 + 只读探针（多数附实测复现），主代理未逐条复跑；
修复批动工时以本表为合同输入，每条修复必须先把探针写成回归测试。

## 高严重度（静默错结论，实锤）

| # | 位置 | 洞 | 影响面 |
|---|------|----|--------|
| H1 | parsers/epru.py:493-498 | `_artwork_path` 把 ARC 的 sweep 当坐标读（`_path_points` 是对的），圆弧图元顶点全错 | 夹具中 439 POLY + 157 FILL 含 ARC；进 silk_shapes → 极性/丝印遮挡判定踩错几何。探针已复现 |
| G1 | core/measure.py:990+645 | 净空粗筛 bbox 未按 radius 外扩 → 剪枝误杀真近邻，**结果随记录顺序摆动** | net_clearance/clearances_vs → ipc、focground、crystalkeepout 全吃。探针复现：真贴合报 12.0 |
| G2 | core/measure.py:1253 | pour_connectivity 同根因：贴合的同网宽线判成两个岛 | FOC 地平面分裂判定会报假「切断」。探针复现 |
| F1 | rules/pcb/regulator.py:344→196 | cap-distance 读 PCB 视图假值分 HF/储能池，证据文字还谎称「schematic states」 | C93 实锤：原理图 22µF 被当 100nF 分错池 |
| F2 | rules/pcb/mcusupply.py:483→378 | supply-groups 同病 | C1：本规则判 bypass，decap-distance（读原理图）判 bulk——**两条规则对同一颗件打架** |
| P1 | cli.py:10631-10632 | `draw lint --page` 丢弃 doc.open 返回值、不校验焦点、跑完不复位——可能 lint 错页还报成目标页，且宣称「只读」实际动了焦点 | 对比 draw plan/apply 都有焦点重读校验 |

## 158 对账普查成果（agent-277，即 158 待办②的交付物）

**9 条规则电气敏感字段读 PCB 视图假值**：regulator-cap-distance、regulator-fb-placement、
mcu-crystal-placement（含 CL 计算）、mcu-crystal-keepout、mcu-supply-groups、mcu-reset-boot、
foc-decap-proximity、foc-power-loop-area、foc-return-path；外加 foc-ground-tie 的 bulk 电容池
（0R 已修好、bulk 漏修=F6）。FB 识别把原理图 0R 读成 10K（F7）。完整视图分工表在 outputs 审计记录。
另两个静默吞：多板 uuid 缺失时 derating/polarity 静默取 board[0]（F3）；负压轨（-12V）被
`value <= 0.0` 丢掉落成措辞错误的 UNKNOWN（F5）；两板电压冲突不落 note（F4）。

## 中严重度（摘选）

- H2 parsers/epru.py:357-362：槽孔 holeType SLOT 当圆孔、直径取槽长（141 焊盘，长宽比最大 4.67:1）
- H3 parsers/epru.py:769：底面器件的 footprint 丝印全归顶层（127b 修过焊盘没修丝印；5/14 夹具命中）
- H4 parsers/epru.py:1185：阻焊层 POLY 混进 board.pours（llc 报 137 个铺铜真实 ~32）
- H5 epru_stream.py:97：POUR 不在 KNOWN_RECORD_TYPES → 「格式漂移」假信号
- H6 REGION 铜禁布区全仓未消费（6 条记录进 unconsumed 就没了）
- G3 core/measure.py:1660：vias_on_pad 用旋转焊盘 AABB（45° 时角点 9.9mil 外也算压焊盘）
- G4 core/measure.py:1930：reference_layer_for 实现「向上优先」与文档「向下优先」相反 → 内层信号的回路径投影错层
- E1 generate.py:624-628/replay.py:769-775：求解器页框硬编码 A4，replay 回退求解器时丢掉实测 frame（非 A4 页全判错）
- E2 layout.py:1812-1823 + generate.py:823-830：validate_full 仍量 route.attach 旧尺子（D1 只补没拆），可拒掉实际干净的板
- E3 layout.py:2000-2032：标签/旗标 vs 别网走线只在 clear_label_point 搜索里查，**终检无此规则**——岳截图圈过的「标签压线」类缺陷门永远不会报
- E4 generate.py:831-838：求解器路径旗标盒没传 glyph 尺（replay 传了），违犯自家「生成与检查共用一把尺」
- E5 generate.py:691-708：unplaced_pins 只进 notes，门看不见——画出的页可能电气不等于网表，lint 退 0（**是否 blocking 待岳裁**）
- P2 drawlint.py:163：L8 旗标方向闸允许 90/270（横放）——与编译器只发 0/180 矛盾，正是 069 要禁的缺陷，闸形同虚设
- P3 moveblock.py:526-554：postcondition 不查旧线删净（坑 46 在 draw discard 落实了、moveblock 没落实）
- P4 drawlint.py:605-608：render SVG 文字解析失败 → 文字类谓词静默全绿报 clean（强依赖 inline style 正则）
- P5 drawapply.py:2310-2326/2533-2560：落页旗标只数个数不查位置/网；未命名网线端点检查退化成「页面任意顶点」
- D1 focground.py:887-891：0R 单地脚件报成 GND↔GND（报告错句，不翻判决）
- D2 focground.py:182+300：裸 `EARTH` 网被所有域静默丢弃（死前缀）；后缀地域（SEC_GND）全落 unclassified
- D3 checkup.py:2421-2429：两份同名 PCB 文档的 finding 全并到第一块板
- D4 checkup.py:73-91：LM311/335/4040 误判电源模块；STM8/MSP430/PIC 无 MCU 模式
- D5 distance.py:721 vs foc.py:745：两条去耦距离规则同阈值不同量法（同网对排除差异），结论可互相矛盾
- E6：两网走线完全重合（真短路）只报 advisory WIRE_TOO_CLOSE 不拦（replay 路径可达性待证）
- G5：endpoint_key eps 实现 1e-6 与文档 1e-3 差 1000 倍 → 折角漏报

## 低危/负面结论（确认没洞的）

解析层单位推断（mil 恒成立）与 y 轴约定全链路无反读；ROUTE_RETRY_LIMIT/_WIDTH_ATTEMPTS 耗尽
均显式 blocking 不静默；plated 字段恒 true 无读取方（死字段，谁用谁踩）；isMirror 夹具未触发。

## 修复批次建议（主代理方案，待岳裁）

- **批 A 审查正确性**（H1/G1/G2 + H2/H3/H4/H5/H6 解析层打包）：parser 与 measure 层，回归测试先行
- **批 B = 158 实施**（F1-F8 全表）：9 条规则改原理图优先 + F3/F4/F5 静默分支
- **批 C 绘制闸门**（E3 终检补标签压线 + E4 旗标 glyph 尺 + P2 L8 集合 + P1 焦点校验复位 + P3 删净检查 + P4 显性降级）
- **批 D 积压**（E1 frame 接口、E5 裁决、D 系列、G3/G4/G5、E6/E7）

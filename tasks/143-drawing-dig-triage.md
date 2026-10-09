# 143 / 绘制线挖洞 triage（2026-10-09）

> 来源：outputs/143_dig/01..07/（7 路对抗性审查，全部带可运行复现；outputs 不入库）。
> 岳裁：**先修完 bug 再推进画图**；排期按严重度，主代理定。
> 33 条洞 + 20 余条已证伪。分级：会造假结果 > 会崩 > 会漏 > 仅不一致。

## 修复批次（文件集互不相交，可并行；每批自管焦点测试，主代理收口全量）

| 批次 | 文件 | 洞 |
|---|---|---|
| 143a | drawcompiler.py + presentationspec.py | 01-洞1 锁 rotation 只校验不应用（**121 的 19 锁全过是巧合**）；01-洞2 锁坐标 NaN/Inf 崩 CLI traceback（违反 "Input problems never raise"）；01-洞3 layout-unsat[gate] 万能兜底误归口；01-洞4 lattice 拒绝文案推给不存在的锁；01-洞5 mirror 判定硬编；02-F1 旗标兜底把多脚网画成零导体（**121c 交付实证：PGND/SEC_GND 各 5 脚 0 线 0 旗，postcondition 恒不成立**）；02-F2 兄弟脚不进网表期望→apply 永不保存 exit 3；02-F3 postcondition 位号混入 specId；02-F4 horizontal-tap/vertical-tap 关系恒 return True |
| 143b | grammar/*.py | 04-H1 flyback「没有隔离器件」诊断无条件假报（transformer 传成 ""，报哪条由位号字典序裁决；注意 tests/test_113:675 会因正确原因变红）；04-H2 _error_amp_on 少 edges 守卫（空网名进公开契约、幽灵 rank、该拒变 pass）；04-H3 LED 阴极并两脚件→合法反激被 circuit-invalid 拒收；04-H4 **flyback 硬编码 left/right、sidePreferences 整条被忽略还伪造出处（横向布局的前置）**；04-H5 power_entry 放行空 direction；04-H6 rc-lowpass 双地族伪造地网名；04-H7 uniform-gnd 只核一半 |
| 143c | readability.py | 03-H1 NC 排除集用原始拼写 vs 网表键用编号（D1.K vs D1.2 同一图 2 条 vs 1 条违规）；03-H2 role-sibling NC 守卫死代码；03-H3 flag 字形框不在约束 4/5/6 对象集（同框作为 label 被拒、作为 power symbol 0 违规）；03-H5 _check_geometry_framed label 分支 and 条件+假证据句；03-H6 shared-net-expression-split 同模块误报；03-H4 min_text_gap 理由句撒谎（121c SVG 已现形）；03-H7 -1 哨兵进 evidence/排序键 |
| 143d | drawapply.py + cli.py + changeplan.py | 05-洞1 --new-page 在有页 plan 上完全不生效仍 exit 0（静默忽略旗标）；05-洞2 census/零改动回读/keep-out 对 netlabels 段失明（digest 不变=守卫假通过）；05-洞4 --keep-names 把未校验 spec id 当位号（C10? → 写到一半崩、页面留半成品）；02-F5 segment.net 两个判官都不读（apply 拿它当网名）；02-F6 旗标只数个数不核对种类（VIN 网可挂 GND 旗）；05-洞3 draw discard 可能误删同网外来走线（**需真机定级**，单独挂起） |
| 143e | generate.py + layout.py | 06-D1 求解器路径标签验证点≠落点（golden 实测差 975 单位，lint_annotations 不调）；06-D2 位置未知引脚静默丢下（潜伏，fixtures 不触发）；06-D3 _widen_gaps 无框零件 0 过道；06-D6 OUT_OF_SHEET 量整框而非 FRAME 内缩；06-D4 单位错 10 倍（1500 按 mil 标定 vs 10-mil 画布）；06-D5 邻近罚价图陈旧；06-D7~D10 gate 文案矛盾/none 仍打旗/坐标框架文档矛盾/去耦提示大小写敏感 |
| 143f | subcircuit.py + symbolprofile.py | 07-洞1 plan postcondition 认不出「新节点就是地轨」（divider 抽头单脚空断言；标记缺失时整段检查无声消失）；07-洞2 GROUND_NET 写死 "GND"（页面地叫 PGND/VSS 时会插出第二根地，仓库自己有 GROUND_NET_PREFIXES）；07-洞3 role_pins 不回落引脚名（CH340G 实测）；07-洞4 role_siblings 撞名顺序；07-洞5 _pin_sort_key（"1"vs"01" 同键 + "²" isdigit 真 int 崩）；07-洞6 _attr_map 非 str 键静默消失 |

## 挂起项

- 05-洞3（discard 误删）：需真机 readback 量「共线两条同网走线」的 host 表现才能定级。
- 03 留白：页面域「模块 A 几何落在模块 B 框内」无规则可报（kind 词表没有）——记为设计空白，待裁。
- 06-D2：潜伏洞，13 个夹具 components_without_symbol=0，不触发；补救面在 draw.py:1612-1621。

## 画图下一棒（144，等 143 全绿后开）——岳 2026-10-09 裁

1. **横向布局**：改 sidePreferences 让反激横过来（143b 的 04-H4 是前置——侧向声明现在被整条忽略）。
2. **页尺寸自适应**：A4 装不下切 A3；工具能切就自己切，切不了通知工程师（draw 流程的正式能力）。
3. **地旗策略**：不减旗，**拆布局**——密度给可读性让路；该打网络标签拆开就拆开，器件可搬到别处（岳原话：「连 GND 都放不下，只能说明布局做得过分密集」）。
4. 重编锁表到页坐标系（--page-box 下编骨架→按新落点写 userLocks→锚定生效）。
5. 143a 的 02-F1（旗标兜底零导体）必须在重编前修好，否则新 plan 还是假通过。

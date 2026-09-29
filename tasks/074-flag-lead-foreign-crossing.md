# 074：旗引线穿越别网导体 = 缺陷（岳裁「必须改」）

## 来源

069 v5 落 P23 后，pin2 的 3V3 旗引线「横 50 + 竖拐 25」的**竖拐**子线段与 5V0 横轨在页坐标
(60,740) **垂直交叉、无 junction 圆点**。电气双岛正确（`C21.1/U10.2/U10.4` 同岛 3V3、
`C20.1/R1.1/U10.3` 同岛 5V0），但人眼第一读是「旗挂在 5V0 轨上」= 看着像短接。岳裁定：这种形态
必须消灭（原话见 069 追加裁决三：「不行，现在第一眼以为5V和3V3的旗标短接在一块了，这个必须改」）。

## 已定设计（主代理给的契约，本批不改设计）

1. **尺子**：候选引线的每个子线段与页上别网导体集合（已布导线/轨/引脚，即 `router.edges` + 已落件
   引脚）做相交检查——**严格内部穿越才算穿越**；共享端点、T 型衔接（端点落线 = 有意的 junction）、
   共线重叠都不算；绝不允许为规避而把不相干的网焊上 junction。
2. **硬规则（范围钉死）**：旗引线/stub 段（069① 远脚同名 stub、`_rail_flag` 沿轨段、竖拐 jog）
   穿越别网导体 ⇒ 该候选硬拒。普通信号布线穿越不硬化（维持 crossings 软指标）。
3. **梯子**：硬拒后按既有梯子升级——换锚点距离档 → 换逃逸方向 → 三折/两段引线 → 向无轨方向垂挂。
4. **穷尽 = layout-unsat**：报实测原因（哪段穿哪条导体）+ 建议动作；不许静默产出穿越图、不许假
   junction；不改 PresentationSpec schema。
5. **停线**：既有 24 场景或 8 页级场景若有任何一页因此翻成 layout-unsat，停下来交卷报告。

## 接管说明（agent-102 半成品审查结论）

接手时工作树 `drawcompiler.py` 有 agent-102 的未提交改动（+255/−22，sha256 `13bbd6f6…`）。
逐段审查后的处置：

| 半成品部件 | 处置 | 理由 |
|---|---|---|
| `_Router.edge_nets` + `_set_foreign_edges` | **保留，修正** | 「拒绝要点名穿的是哪条网」需要在 `edges` 旁存网名。它自称「`edges` 的唯一写者」**不属实**：`_Router.add_edge`（死代码，全仓库无调用）也 append，057 的 `pagecompiler._PageRouter` 还整表赋值 `edges`。已把 `add_edge` 收编成同步维护 `edge_nets`，并改写注释点明三个写点与「长度不一致时报运行不报网名」的降级读法 |
| `_proper_crossing` | **保留** | 与 `readability._proper_crossing` 逐字同律（TOL=1e-6，`_cross` 展开式逐项核对过）；仓库惯例是引擎间不 import 对方私有函数（全仓库零处），故保留本地副本，另加一条测试钉住两把尺子不漂 |
| `_foreign_crossing` / `_lead_crossing` | **保留** | 逐子线段找第一处严格内部穿越；报「run + 别网名 + 交叉点」，正是设计第 4 条的实测原因 |
| `_flag_anchor(..., crossings=...)` 的硬拒 | **保留** | 位置正确：在 `fits`/`_span_free`/`_vertex_clear` 之后、`return` 之前——只对「本来能落的档」设卡，被盒/墙拒掉的档不记（不是候选就不该报） |
| `_flag_pins` / `_rail_flag` / `_stub_label` 的失败返回 | **保留，修一处真 bug** | `_rail_flag` 里 `_flag_crossing_failure(net_id, pin[0], pin[1], crossings, …)` 传了 **6 个实参、签名只收 4 个** ⇒ 一旦某条轨的每一档都穿越就是 `TypeError` 而不是拒绝（离线无此场景，测试抓不到）。已改成 `(net_id, pin[1], crossings, subject)`，并加一条静态测试按签名核每一处调用（变异 M3 复现） |
| `_stub_label` 的方向梯（我自己一度加上） | **撤掉** | 实测 24 场景 + E1 两个形状里 `_stub_label` 共 6 次调用、**6/6 都在脚自己的方向就成功了**，方向梯是死代码；069 sec.1 的 stub 本来就走脚自己的逃逸方向。撤掉后本批只硬化「既有梯子」，不多造行为（缺口记在下面自决项） |
| 未写测试/任务书/证据 | 本批补齐 | 见下 |

## 改动清单

```bash
.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home      # 2617 passed（基线 2609 + 8）
```

- `src/boardwise/engines/drawcompiler.py`
  HEAD `44c1d0c1…` → 半成品 `13bbd6f6…` → 交付 `f8301108…`（`git diff --stat`：272 insertions, 22 deletions）
- `tests/test_053b_drawcompiler.py`
  HEAD `66385abe…` → 交付 `6caacf5c…`
- `.kimi-code/skills/boardwise/SKILL.md`
  HEAD `aeecba79…` → 交付 `b6c9d155…`（§3.3 增一条 + 坑表第 45 条）

实现要点（最终形态）：
- `_set_foreign_edges(router, segments, net_id)`：`router.edges` = 除本网外每条线的每个相邻点对，
  `edge_nets` 同长记录网名；两处调用（逐网路由前、069 sec.7 补旗前）都改成它。
- `_proper_crossing(a,b,c,d)`：严格内部相交（四条叉积判据 + 分母保护），返回交点。
- `_foreign_crossing` / `_lead_crossing`：逐子线段扫描，返回 `(点, 别网名, 别网段)` 与人类可读描述。
- `_flag_anchor(..., crossings=None)`：档位通过其余检查后再过穿越闸；命中即记入 `crossings` 并继续爬梯。
- `_flag_pins` / `_stub_label`：全部方向/档位跑完且 `crossings` 非空 ⇒ 返回 `_flag_crossing_failure`。
- `_rail_flag`：返回 `(anchor, failure)`，「立在自己的脚上」这档仍保留（它不画穿越图）。
- `_flag_crossing_failure(...)`：`layout-unsat` + 实测原因（run / 别网名 / 交叉点 / 档位数）+ 建议动作
  （点明「不用 junction 糊」）。

## 测试清单（新增 8 条，全部在 `tests/test_053b_drawcompiler.py`）

1. `test_a_pads_flag_lead_never_cuts_through_another_nets_wire` —— E1 形态（实测 AMS1117 双 VOUT）：
   每个候选零穿越；pin2 旗**仍在引线上**（不是立在脚上）、rot∈{0,180}、挂在轨的无轨一侧且比脚更远。
2. `test_a_pads_label_stub_never_cuts_through_another_nets_wire` —— 同一形状的 signal 网（netlabel
   stub）走同一把尺：零穿越、stub 仍是 ≥ `SIBLING_LEAD` 的一截、不再跨越轨。
3. `test_the_crossing_ruler_reads_a_cut_and_not_a_join` —— 尺子正负例（真穿/角穿 vs T 型/共享端点/
   共线重叠/平行/退化）+ 与 `readability._proper_crossing` 逐例同答（防两把尺子漂）+ 一张真图上的
   同网 tee 不误判。
4. `test_a_pad_sealed_on_every_side_is_layout_unsat_with_the_conductor_named` —— 四向各 5 单位处被别
   网线封死：四向都 `lead is None` 且都留下实测记录；`_flag_crossing_failure` 报 `layout-unsat`、
   点名 run/别网/交叉点、动作里写明不用 junction。
5. `test_a_pad_whose_every_side_is_sealed_is_layout_unsat_and_names_the_conductor` —— **编译级**实例
   （mirrored AMS1117，默认间距梯）：0 候选、`["layout-unsat"]`、逐变体的拒绝点名实测导体与动作。
6. `test_a_lead_that_cuts_another_net_refuses_that_variant_and_names_the_run` —— 拒绝要出现在编译器
   答复里（逐变体、带实测原因），不是静默少一个候选。
7. `test_every_statement_of_the_074_refusal_fits_its_own_signature` —— 三处调用与签名对表（抓 M3 那类
   「拒绝造不出来」的 bug）。
8. `test_only_a_leads_run_is_gated_and_ordinary_wiring_still_crosses` —— 范围边界：同一段几何，普通布线
   照画（`one_bend_route` 直穿），当引线判就拒；crossings 仍是软指标。

改动过的既有测试 4 条（**痕迹全部来自 074 的实测后果，不是放松规则**，逐条见「自决项」）：
`test_the_pad_across_the_body_follows_the_symbol_not_a_constant_side`（预算加 3.5x 档 + 按几何判「跨体那只脚」）、
`test_a_far_pads_flag_stands_a_stub_clear_of_the_rails_own_flag`（水平 50 间距 ⇒ 改成「挂在轨的无轨一侧 + 两旗盒不相交」）、
`test_a_free_pad_takes_the_near_stub_and_its_capacitor_hugs_the_pad`（40–60 带的**下限**落到 30）、
`test_scene_08e_the_same_circuit_draws_once_the_sides_match_the_symbol`（候选 3 ⇒ 2 + 幸存者零穿越）。

## 场景哈希审计（24 场景，含 8 个页级场景）

```bash
.venv/Scripts/python.exe tools/064_flag_delta_audit.py dump    .tmp_074_audit/before   # HEAD 字节
.venv/Scripts/python.exe tools/064_flag_delta_audit.py dump    .tmp_074_audit/final    # 074 工作树
.venv/Scripts/python.exe tools/064_flag_delta_audit.py compare .tmp_074_audit/before .tmp_074_audit/final
```

结果：**24/24 `unchanged`，`clean=True`**（8 个页级场景是其中 `056.scene01..08`，逐叶也全同）。
即：本批对既有 24 场景**零移动**，没有任何一页翻成 `layout-unsat`（设计第 5 条的停线条件未触发）。
两端的 dump 都是现场重做的（before = `git show HEAD:…` 写回后 dump，dump 完 `cp` 还原并 sha256 复核）。

E1 配方（离线页）`15_e1_offline_crossings.txt`：before 8/8 候选都有旗引线穿越（共 20 处），after 8/8
候选零穿越；after 的候选 0 = `f8b1fb567136…`，与真机 `draw plan` 落的那份**同一个**。

## 变异证据（`13_mutations.txt`，cp 备份 + sha256 还原）

| # | 变异 | 结果 |
|---|---|---|
| M1 | `_foreign_crossing` 里 `point = _proper_crossing(...)` → `point = None`（闸永远找不到穿越） | **5 条红**（两个 sealed、flag lead、label stub、范围边界） |
| M2 | 尺子换成「端点相碰也算相交」（`abc*abd <= 0 and cda*cdb <= 0`） | **1 条红**：`test_the_crossing_ruler_reads_a_cut_and_not_a_join`（T 型被算成穿越） |
| M3 | `_rail_flag` 的拒绝调用还原成 6 实参（我修掉的那个 bug） | **1 条红**：签名静态核 |

三次变异后还原 `sha256 f8301108…` 与原文件**逐字节相同**（脚本每次打印 BYTE IDENTICAL）。

## 真机验收（test 工程 P23，`evidence/074/`）

R1：`bridge status` → 2 窗、其中 `inst-100430948-m5hna5hd` = project `test`；`sys.identity` →
`focusedProject.friendlyName == "test"` **逐字**、`activeDocument.uuid = 5d54eccfab7ea9be`（P23）、
`consistent: true`；`doc.list` → P23 active、P22 = `790ff841f8a73c11`（只读）。**每次 bridge 调用都显式
`--project test`**（三个窗口两个匿名，不指定会 `WINDOW_UNSPECIFIED`）。清场用 `sch.delete_primitives`
三批（8/8/6，delivered `notFound=0 failed=0`），不开新页。

| 验收项 | 结果 |
|---|---|
| plan/apply 重跑 | `draw plan` exit 0（候选 0 = 页编译器 `f8b1fb567136…`）；`draw apply` **exit 0 applied + saved** |
| (60,740) 穿越消失 | ✓ 落图后 x=60 处没有任何引线；pin2 引线 `[130,730,180,730,130,705,130,730]` |
| pin2 旗零穿越 | ✓ 逐 flag 引线 × 全页导线严格内部相交 = **0**（`18_live_check.txt`） |
| pin2 旗形态 | ✓ 横 50 + 竖拐 25 **向下**，锚点 (130,705) **rot 180**（向无轨方向垂挂） |
| 全旗 rot∈{0,180} | ✓ 8 旗：rot 0×7 + rot 180×1 |
| 岛表与 v5 逐行相同 | ✓ 3V3 `C21.1/U10.2/U10.4`；5V0 `C20.1/R1.1/U10.3`；TAP `R1.2/R2.1`；GND `C20.2/C21.2/R2.2/U10.1` |
| 有旗网导线 Net 全空 + TAP 带名 | ✓ 9 条线中 8 条 `Net=''`，TAP 一条 `Net='TAP'` |
| 复跑 already_applied 零写 | ✓ 第二次 apply：`already_applied`，`write 0 call(s)`，guards 六项全 checked |
| P22 归约串 sha256 | ✓ baseline `9142bb92…` == v6 回读 `9142bb92…`（同一归约口径，逐字节相同） |
| 图（主代理亲看） | `evidence/074/p23_v6.png`（`export.render` scope=page 整页 2362×1672）+ `p23_v6_pwr_zoom.png`（2× 放大裁切，pin2 旗与 5V0 轨一眼分家） |

## 自决项（请岳/主代理裁决）

1. **既有测试 4 条的改动**——这是本批唯一的「动到别人断言」：
   - `test_a_far_pads_flag_stands_a_stub_clear_of_the_rails_own_flag`：069 断言「水平拉开 ≥ 50」，
     074 之后 pin2 的旗改从**竖直方向**分家。理由：50 竖拐**向上**那一档正是穿越（074 必拒），
     50 竖拐**向下**那一档与 C1 自己的注释文字（x≤133）真相交（069⑧ 盒判据，非误报），
     于是落到 `FLAG_LEAD=30`。断言改成 074 真正要求的「挂在轨的无轨一侧 + 两整颗旗盒不相交」。
   - `test_a_free_pad_takes_the_near_stub_and_its_capacitor_hugs_the_pad`：40–60 的**下限**在本形状
     落到 30（低于岳的 40）。**注意：真机 E1（页级）仍是 50**——`(180,730)→(130,730)→(130,705)`，
     岳的 40–60 带在落地的图上守住了；30 只出现在这个模块级夹具（C1 注释放得近）。
     若岳要求模块级也守 40，需要动 layout（把 C1 挪开）或给梯子加一档，两条都超出本批边界。
   - `test_scene_08e…`：候选 3 → 2（被拒的那个变体是 GND 脚旗四向皆穿越），幸存候选零穿越。
   - `test_the_pad_across_the_body_follows_the_symbol_not_a_constant_side`：默认间距梯下该 mirrored
     形状 **0 候选**（唯一的旧候选本身就在 `(235,745)` 穿 5V0 轨）；给预算加 3.5x 档即有干净图，
     故测试改成「加一档间距 + 按几何判跨体那只脚」。
2. **`_stub_label` 不加方向梯**：实测 6/6 都不需要；脚自己方向被封时给的是 `layout-unsat`（响的），
   不是「换个方向出去」。若将来要 `_stub_label` 也做 074 sec.3 的「换逃逸方向」，按此处的 6/6 反例重估。
3. **`pagecompiler._PageRouter` 不维护 `edge_nets`**：它整表赋 `edges` 且从不问「穿越的是哪条网」，
   故未动；`_foreign_crossing` 对两表不等长按「报运行不报网名」降级（宁缺勿错）。
4. **`_proper_crossing` 保留本地副本**（不 import `readability` 的私有函数，仓库零先例），用测试钉同律。

## 边界外发现（未改，报告）

1. **硬规则会减少候选数**：`compile()` 的文档契约是「成功返回 3-8 个候选」，074 拒变体后可能出现
   2 个（scene 08e 实测）甚至 0 个（mirrored 默认梯）。契约文字与实现之间出现张力，本批未改文档契约。
2. **模块级与页级同名形状的落位可以差到 20 单位**（模块级 30 竖拐向下、页级 50 竖拐向下）：模块内部
   空间受 C1 注释文字挤占，页级因模块留白宽松而保住 40–60。若岳在意模块级形态，需要单独裁决。
3. **`sch.geometry` 的 `Line` 是点集**（坑 26 已记）——离线核对必须只取轴对齐相邻对；本批的 live 检查
   脚本就是这么做的（`axis_segments`），否则对角幻影会把 0 穿越算成穿越。
4. `draw discard` 未用于本次清场（改用 `sch.delete_primitives` 三批），沿用 069 v5 的现场做法；
   069 遗留的「页上有名、plan 是有旗网」的 discard 兼容缺口本批未碰。

## 边界与纪律记录

- 零 git 写操作；未动 `PROGRESS.md`；未碰 `tests/fixtures/`、`reviewsets/`、`outputs/069_ldo_example/`
  与 P22（只 `doc.open` + `sch.geometry`）。
- 真机只写 test 工程 P23；daemon 未重启（全程 `127.0.0.1:61190` 在线）。
- 全量 pytest **2617 passed**（2617 = 2609 基线 + 8 新增）；connector `npm test` + `npm run typecheck`、
  dsh-plugin `npm run typecheck && npm test && npm run build` 全绿（`14_/16_`）。
- 变异 3 组，cp 备份 + sha256 逐字节还原（禁用 `git checkout --`）。

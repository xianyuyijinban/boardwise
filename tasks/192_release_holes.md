# 任务书：192 — v0.5.14 发版前挖洞修复（三批并行：192A 几何/渲染 · 192B 判型/闸门 · 192C 货架CLI/桥）

- 批号：**192**　日期：2026-10-17　来源：v0.5.13→HEAD 六缝只读挖洞（探针都在仓库根 `.tmp_hole_1/`、`.tmp_hole_2/`、`.tmp_hole_sew3/`、`.tmp_hole4/`、`.tmp_hole_5/`、`.tmp_hole_6/`，**先跑探针复现再修**，修完探针转回归测试）。
- 每条修复：回归测试先红后绿 + 至少一组变异。严重度标在条目前。

## 192A 几何 / 解析 / 渲染（地盘：core/geometry.py、parsers/epru.py、parsers/kicad.py、engines/pcbreview.py、engines/canvasrender.py、cli.py::_geometry_canvas_images）

1. **【高】底层器件焊盘漏镜像**：`core/geometry.py` `ComponentPlacement.transform`（`parsers/epru.py` `build_pads` 每只焊盘都走它）只做旋转，`layer_id==2` 的器件封装局部坐标没镜像。证据 `.tmp_hole_1/probe_pad3.py`：毕设FOC 底层 U4/U6 24 脚，按「同网走线/过孔端点落在焊盘中心」为独立 oracle，加镜像 11 条 0.0 mil、现状 0 条。修法：底层施加 x 镜像，次序与 189A2 `transform_point` 定标一致（`mirror_x ∘ CCW(angle)`，先核对再写）。
   - 回归：写一条**属性测试**「同网铜端点 ↔ 焊盘中心」在全部 epro2 夹具上不变差（现状 vs 修后逐板计数，修后不得少）。
   - 波及：焊盘几何变了，所有 PCB 规则读数会动（间距/丝印/热/去耦距离）。**全部夹具 + 实板A 的 finding 前后对照表**逐条解释。
   - **真机独立验证（必做）**：test 工程（`--project test`，不通就 `bridge status` 取 instance）用 `pcb.place_component` 在 PCB1 底层放一颗 SOIC-8 或更多脚、焊盘不对称的封装，旋转 0 与 90 各一颗；`pcb.readback` 读宿主焊盘坐标；`sys.get_project_file` 取文件 → `parse_epro2` 的焊盘坐标逐脚对比（≤0.5 mil）。放的器件删光复原。命令照抄 `outputs/R1/runbook.md` / `outputs/190s/evidence.md`。
2. **【中】** `SilkText.mirrored_frame` 只认 `source in ("designator","board")`，漏了 `designator-unparented`（`parsers/epru.py:1795`）→ 改为「只排除 footprint」。
3. **【低】** `engines/pcbreview.py` `netIdNote` 自己重写了筛选，改调 `parsers/kicad.py::unnamed_net_names()`。
4. **【低】** `parsers/kicad.py::_net_table` 同 id 重复行后写静默胜出 → 保留首个 + 记一条 note（披露到 netIdNote 同处）。
5. **【中】** 同名两块板 `canvas-<board>.svg` 撞名后者覆盖前者，而 `canvas_images[]` 两行字节数各写各的（`.tmp_hole_5/probe_canvas.py` P2）→ 文件名去重（同名时加 boardUuid 后 6 位或序号），`canvas_images[].file` 与盘上一致。
6. **【低】** SVG 文本含 XML 非法控制字符（U+0001 等）→ 整张图不良构（P1b）→ 出图前剔除 `[\x00-\x08\x0b\x0c\x0e-\x1f]`。
7. **【低】** 图注里写了 Markdown `**网**`，SVG 里是字面星号 → 去掉。

## 192B 判型 / 闸门 / 合同（地盘：core/partkind.py、rules/connectivity.py、rules/pcb/distance.py、rules/sensebias.py、engines/checkup.py、core/designintent.py、cli.py 的 _completion*/_review_conclusion/_checkup_report/intent 渲染）

1. **【高】词表按子串命中**：`core/partkind.py` `_hit` 子串匹配，`MOS` 命中 `CMOS`（毕设滤波采样 U1=OPA2333 运放判成 transistor）、`USB` 命中 STM32 描述（超声波 U1 判成 connector）。证据 `.tmp_hole_2/p6_subjects.py`、`p12_wordscan.py`。修法：按 token/词边界匹配（中英文分别处理；中文词仍可子串，但要有排除表如「芯片」「单片机」「运放」优先判 IC）。回归：上述两例 + 15 块夹具全部判型前后对照，**任何 IC→非IC 的翻转逐条解释**。
2. **【高】** `rules/connectivity.py::DecouplingPerIC` 调 `classify_part(comp)` 不带 `library`，与 facts/distance 对同一件判型打架（`.tmp_hole_2/p7_repro.py`）→ 传同一个货架（`read_default_library()`）。
3. **【中】** 039 门（`facts_verified=false` 的候选条目不算声明）在 `rules/pcb/distance.py::device_facts` 与 `rules/sensebias.py::_entry_category` 没过（`.tmp_hole_2/p11_gate.py`）→ 两处都走同一个门。
4. **【中】** `distance.py::_tier_pin` 对带编号脚名：`SW1`/`PVIN1`→None、`VIN1`→消耗端 → 先剥尾部数字/下划线后缀再查表；docstring 那句「编号族由 pin_role 兜底」改成真话。
5. **【中→高】** `engines/checkup.py::_declared_passive` 豁免会让 IC 静默掉出未审闸（TTP223「电容式触摸按键芯片」→ capacitor，`.tmp_hole_sew3/probe6_declared_passive_leak.py`）→ 加反向守卫：**只豁免脚数 ≤ 2 的件**（U 位号电阻正是 2 脚）；被豁免的件在报告里留痕（`completion` 下一个计数 + report.md 一行列位号）；改掉注释里「只会多问」的假话。
6. **【中】** 191A 接受记录键是 `(part, board)`，但 `core/designintent.py` 解析器按 `part` 单字段去重（`IDENTITY_KEYS[SECTION_ACCEPTED]="part"`、`_entries_from`）→ 同件两板接受写不出也读不回（`.tmp_hole4/p1_board_key_roundtrip.py`、`p2_cli_board_scope.py`）→ accepted 节唯一性按 `(part, board)`；补 render→parse 往返测试。
7. **【低】** 接受条目点名了该件不在的板，report.md 印「stale（图纸上已没有）」而件还在别的板 → 新状态 `stale-elsewhere`（或把 `why` 印进状态格），状态常量注释同步（`.tmp_hole_sew3/probe10_board_scope_label.py`）。
8. **【低】** `cli.py` `_completion_from_report` 对 `coverage["modelEmpty"]` 用下标 → `.get`。
9. **【中】** intent 节 `totals.staleEntries`（本次新标）与 `staleEntries[]`（现存全部）同名不同义，report.md 同屏数字矛盾（`.tmp_hole_5/runD`）→ `totals` 改名 `newlyStale` + 新增 `staleTotal`，差量行分开报，docstring 同步。
10. **【低】** 「契约版本：intentVersion N」印的是本 build 常量 → 区分「本 build 读 / 文件声明」。
11. **【低】** 工程师接受未审节那句「它们不再让 verdict 停在 incomplete」改条件式，带上本轮实际 verdict。
- 改了 `rules/**`：**不要重钉 test_126a**（主代理统一）。

## 192C 货架 CLI / 桥（地盘：cli.py 的 parts add/show/missing/_read_default_shelf/update-connector、bridge/daemon.py、bridge/client.py）

1. **【高】** `parts add` 查重只看用户架，读却是合并架 → 用户为内置架已核验的件建候选后，合并时把内置那条**已核验**条目顶掉（`.tmp_hole4/p5_add_shadows_builtin.py`，要模拟冻结态才复现）→ 查重读合并架，命中内置条目给出与「已存在」同等的拒绝/提示（`--force` 才覆盖并明说）；写仍只写用户架。回归测试必须走 CLI + `default_library_paths()` 冻结态接线（不许绕过直接造 merge 文档——那正是原测试没抓到的原因）。
2. **【中】** `parts show` / `parts missing` 判合并架、报单架路径与计数（`.tmp_hole4/p4_show_attribution.py`）→ 输出合并来源（与 `parts list` 同口径：`shelfPaths[]` + 条目 origin）。
3. **【低】** `_read_default_shelf` 报错恒点名 `paths[0]` → 点名真正读不了的那一架。
4. **【高】** `update-connector --all` 逐窗验收是池判：任一新连接报对版本就给**每个**目标窗记 verified（`.tmp_hole_6/probe_b_verdicts.py` 场景 2/3）→ 不改 connector 的最小诚实修法：多窗时只有「报出期望版本的新连接数 ≥ 目标窗数」才逐窗 verified，否则这些窗记 `unconfirmed` 并在 detail 写明原因，exit 非 0；单窗行为不变。
5. **【中】** `--project test` 对窗口上报的 friendlyName `/test` 判 PROJECT_NOT_CONNECTED（`.tmp_hole_6/probe_a2_friendlyname.py`；10-17 主代理真机实测同形）→ 路由匹配时对工程名做规范化（去前导 `/`、casefold）后比较；仍不中再报错，话术印出窗口上报的名字与 uuid 两种写法；`PROJECT_NOT_CONNECTED_FIX` 同步。
6. **【中】** 版本漂移告警 / doctor 让人跑 `bridge start`，而 daemon 在跑时它 OSError 10048 抛栈（`.tmp_hole_6/probe_c_start.py`）→ 话术改「结束旧 daemon 进程（任务管理器 / `taskkill`），下一条 bridge 命令会自动拉起」；`bridge start` 端口被占时给一句人话而不是 traceback。
7. **【低】** `daemon.py::_local_action` 兜底答「hello may only be sent once」→ 改 `UNKNOWN_ACTION`。
- 192C 涉及桥动作行为（路由）变更：交卷前在 test 窗口真机跑一次 `bridge call --action doc.list --project test`（只读）证明通了。

## 共同纪律

- 三批同树并行：只改自己地盘；`cli.py` 192B 与 192C 都会改——**只改自己点名的函数**，改前重读文件，别整文件重写。
- 不重钉 test_126a；全量里别人地盘的红隔几分钟重跑，仍红就列出。
- 全量 `--basetemp=.tmp_pt_192{a,b,c}` `-n 4 --dist loadfile`。变异每批 ≥2 组。
- 红线：不动 git；不 rm（回收站）；企业项目名/型号零出现（只写「实板A」）；真机只碰 test；禁地工程不碰。
- 证据 `outputs/192{a,b,c}/evidence.md`；PROGRESS.md 各 append 一行；**不要 commit**。约 100 分钟没完就停新工作、收好交卷。

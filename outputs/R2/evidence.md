# R2 证据（v0.5.13 PCB 审查加深）

开发机无立创 EDA Pro：R2-3（丝印真机闭环）**未做**。其余三件离线完成。
基线：`fix/rulebody-fingerprint-eol`（PR #77，指纹换行归一）之上；本包依赖 #77 的折行配方重钉指纹。

## 侦察来源（三件共用）

规范只写了数字码，夹具里却是字符串，所以只读了规范不够。为此下载了官方 3.2.186 安装包，用 innoextract 解包但不安装，**只读**编辑器打包的 JS 作为宿主语义的一手来源：

- `assets/pro-pcb/3.2.182.f0ff1d6f/js/drcWorker.js`：
  - REGION 的类型枚举 `COMPONENT/VIA/TRACK/FILL/COPPER/PLANE`；
  - `parseType`：只给 component/track/fill/copper/planzone 置位，**没有 VIA 分支**；
  - `checkProhibitXXX`：`(e.layerId===t.layerId||e.layerId===12)&&(track→走线|fill→填充|device→元件|copper→铺铜结果|planzone→内电层)`。
- 同目录 `pcb.js`：
  - 数字码转字符串 `1→TRACK+FILL, 2→COMPONENT, 3→VIA, 4→COPPER+PLANE, 5→TRACK, 6→FILL, 7→COPPER, 8→PLANE`；
  - 弧构造 `build5(start, end, sweep)`；
  - 钻孔表 / 钻孔导出用 `plated ? "PTH" : "NPTH"` 区分。
- 官方格式规范 v2.2（2022-12-15）与 v3（2025-10-21）：PAD 的 `plated` 定义为「是否金属化孔壁」；REGION 的 `prohibitType` 只给数字码 1–8。

## R2-4 重构债（commit 6e903d5）

1. `distance._point_in_outline`：逐行比对，与 `core.measure.point_in_polygon` 完全一致，唯一差别是调用的私有距离副本。已删除，改为 import 公开件。
2. 点到线段距离原有三份：core 私有一份（守卫 `dx==0 and dy==0`），focthermal 和 distance 各一份逐字相同的副本（守卫 `length_sq<=1e-18`）。现统一为公开的 `core.measure.point_segment_distance`，采用 `length_sq` 守卫。选型数据如下：
   - `point_segment_census.json`：14 份夹具跑完整 PCB 审查，core 版被调 6,523,834 次，其中 36 次落在 `0<len²≤1e-18` 的退化带，24 次两种守卫逐位不同；focthermal 版 8 次在带内，8 次不同；合成退化带 5000 例中 1231 例不同，最大差 9.7e-10 mil；
   - `guard_flip_experiment.json`：把**全部**副本换成任一种守卫，14 份夹具共 881 条 PCB finding（含 message 与 evidence 全文）逐条不变，**判决零翻转**；
   - 下溢用例 `dx=1e-170`：`dx==0` 守卫抛 `ZeroDivisionError`，`length_sq` 守卫正常返回到 `a` 的距离。
3. 指纹：recursive `f3a69124 → c0a45f39`，direct 不动。
4. 变异：守卫退回精确零 → 2 红；`point_in_polygon` 边界不算内 → 1 红。两组均已还原，sha256 一致。

## R2-2 `plated`（commit 7a35b17）

- **字段没找错**：规范和编辑器代码都以 PAD.`plated` 区分 PTH/NPTH。
- **「恒 true」是夹具数据本身**：14 份夹具 3583 条 PAD 全部为 `plated:true`，包括 SMD 焊盘和 M2/M3 螺丝孔；VIA 记录没有这个键（`plated_census.txt`）。所以夹具里**不存在** NPTH。焊盘等于孔的螺丝孔封装在库里有，但没有一块板放置它。
- 真正写死「有孔就是镀铜」的占位在 `pad_effective_layers`：任何带孔焊盘都被当成镀铜筒，占满所有铜层。现在 `plated is False` 的焊盘不再按铜筒处理：有焊环的只占外层焊环所在面；焊环不大于孔的纯机械孔不占任何铜层。
- 改为三态读取：`_plated_flag` 只认 True/1、False/0，其余（含缺键）一律 None。旧写法 `bool(body.get("plated", False))` 会把缺键读成 NPTH，规则开始消费这个字段后会剥掉整份文件的铜筒。
- 零翻转：只有 `plated is False` 才走 NPTH 分支，夹具里没有这种焊盘；普查结果钉在测试里，第一份带 NPTH 的夹具一进来就会红。
- 注入验证：复制毕设FOC 1.0.0，按值定位、恰好一处命中，把一条 PAD 改成 false。该封装在 4 层板上的放置失去 15/16 层，其余焊盘逐个不变。
- 变异 3 组：删 NPTH 分支 → 5 红；调用处回退为 `bool(...,False)` → 1 红；去掉焊环检查 → 2 红。均已还原，sha256 一致。

## R2-1 `pcb-keepout-violation`（本包第三笔）

- 解析层**增量**：`PourShape.rings`（POURED 岛与 FILL 的外环加各个洞，弧按 `build5` 展开）、`ProhibitRegion.rings`（多边形禁布区）。`points` 一个字节不动，其他规则零影响；全量 881 条 finding 不变，见下方测试。
- 规则：类型词表、数字码、「哪种禁布区约束哪类图元、按什么层」都照编辑器代码实现；容差 0.1 mil，侵蚀后再判（圆收半径，凸多边形边内移）。`COPPER` 区只查铺铜结果，并且**读洞**。
- 电机板实测（`keepout_audit.json`）：
  - 底层 PGND 铺铜按「外轮廓 + 洞」判，5 个圆区都不侵入；只看外轮廓或旧弦点，5 个全部误报；
  - 顶层 VM 铺铜对 CN4 区：弧按编辑器公式展开后不侵入，用旧弦点会误报；
  - 3 个无父 POUR 的孤儿铺铜岛与 6 个区都几何相交，但拿不到层，不判（见遗留）。
- 14 份夹具上本规则零 finding。
- 注入两例：
  - 删掉 PGND 铺铜在 6335e88d 周围的洞（模拟加了禁布区没重铺）→ 恰好 1 条 WARN，指向这个区和 PGND；
  - 在 PCB2 一条顶层走线中点画半径 5 的 TRACK 区 → 1 条 WARN，点名这条走线。
- 变异 6 组：删线段相交判定、删环边判定、忽略洞、去掉层判断、解析层不读洞、弧方向取反，全部变红。弧方向那组第一轮存活，原因是夹具上决定结论的洞都是 180° 弧，对方向不敏感；补了直接钉住编辑器弧方向的测试后变红。均已还原，sha256 一致。
- 任务书偏差：`test_011d` / `test_064` 的 23 钉的是**原理图** `BUILTIN_RULES`，加 PCB 规则不应该动它们，所以没改。PCB 规则的结构钉在 `test_126a` 等 8 个文件的 id 列表或 `checksRun` 里，已逐个补上 `pcb-keepout-violation`。
- 指纹：recursive `c0a45f39 → f45cfd99`，direct 不动。

## R2-3 丝印真机闭环 — 未做

依赖 R1-1 的 `pcb.place_component` 真机通过（PR #78），本机没有编辑器。步骤：
1. 按 R1 runbook 在 test 工程 PCB1 放一颗 0603；
2. `boardwise checkup --project test` 跑在线检查，读「丝印读数（实测）」段；
3. 用 `pcb.geometry` 读位号 ATTR 盒，与 checkup 读数对拍；
4. 记下离线估算与实测各有多少条，作为对照；
5. 删件复原。

原始读数落 `outputs/R2/live/`。

## 测试计数（R2 分支全量，`-n 8`）

5429 passed / 19 failed / 36 skipped。19 条红与基线逐条相同，全是环境原因：16 条读 gitignore 掉的 `outputs/*.json`，3 条 `test_069c` 读真实 home。
#77 分支是 5383 passed，本包新增 45 条：r2_4 5 条、r2_2 15 条、r2_1 25 条；另有 1 条是上次偶发失败的 xdist 用例这次过了。

## 遗留

1. 高速电机控制器 PCB2 上有 3 个无父 POUR 的铺铜岛（`aeb890a3…`、`7deb917f…`、`6a531241…`；父 POUR 不在文件里，所以拿不到层），按「外轮廓减洞」判与全部 6 个禁布区都相交。没有层就不能断言违规，规则不判也不出 finding；如果要披露，需要一个非 finding 的通道。请裁决。
2. 严重度取 WARN；仓库里还没有 PCB 禁布区的严重度裁决。要不要升 ERROR 请主代理定。
3. `_artwork_path` 读圆角半径用的是 `nums[6]`，但 `["R",x,y,w,h,rot,r]` 只有 6 个数（`nums[0..5]`），半径永远读不到。这是原有 bug，不在本包范围，没改。
4. `PourShape.rings` 只填了 POURED 和 FILL。POUR / POLY 留空，因为目前没有读者需要。
5. 元件禁布用焊盘判（圆焊盘按外接矩形），没读本体外形；非凸多边形禁布区不做容差侵蚀。这两点都写进了规则文档和每条 evidence。

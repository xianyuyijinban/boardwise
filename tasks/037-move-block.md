# 037 move-block：局部移动一个功能块（M3 第 5 片）

## 背景与入口裁决

M3 顺序第 5 刀（016 改值 ✅ → 029 补件 ✅ → 035 修脚 ✅ → 036 插入 ✅ → **move-block**）。
与 036 一样**没有驱动规则**：AI/用户点名要移哪组器件、移多远，harness 保证移得安全、
连接不变、可回读、可幂等。入口 = `edit plan` 第四个入口 `--move`。

`_LATER_KINDS` 里 `move-block` 已挂号（`core/changeplan.py:85`，036 摘掉 insert-subcircuit 后
就剩它），本片摘号转正；`SUPPORTED_KINDS` 全满后 `_LATER_KINDS` 为空，拒绝文案同步（实现注意空表文案）。

**已核实的家底**（主代理动手前读过 connector 源码）：
- `sch.modify_primitive` **已存在**（`connector/src/actions.ts:4428`）：按 id 移/旋/镜像，pose-only，
  前后读数都回；有 pose 的类：`sch_PrimitiveComponent` / `sch_PrimitiveText` / `sch_PrimitivePin`。
- **wire 没有 pose**——"modify is not a move"是结构性拒绝。组件移走后线怎么办，是本片唯一的
  机制岔路（见工作项 0）。
- netlabel 本机 `sch_PrimitiveNetLabel` 连读都不存在（035 实测）+ `place_netlabel` 不可用
  （SKILL 坑 9）⇒ **边界上带 label 的块 v1 直接拒绝**，不存在"移过去再补 label"的路。

## 工作项 0（第一天先做，定全片走向）：探针

在 test 工程 scratch 页放两个器件 + 一条直连线，对其中一件 `sch.modify_primitive` 位移，
画布回读线端点：

- **宿主拖拽**（线端点跟着脚走）→ move-block = 逐件 modify_primitive + 网表恒等校验，
  线一根不碰。轻路径。
- **宿主不拖**（线留原地，脚脱离线端）→ 重路径：组内线删除+平移重画（同形状 + delta），
  边界线删除+正交重画（029 `wire_route` 强制正交，远端点不动）。
  **发现必须动 connector（比如要给 wire 加 move）→ 停下来报主代理**，不许绕。

探针证据写 `outputs/037_probe.txt`（前后 geometry + 网表读数原样）。

## 模板 v1 范围（写死，不扩）

- 输入：`edit plan --move --designators R7,C9 --dx 100 --dy 0 -o plan.json`。
  位号显式给一组（≥1）；dx/dy 必须是**落点网格整数倍**（029 `layout.GRID=5`），否则 plan 拒绝
  （网格歪了线就再也接不上）。
- **组内线**（两端脚都在组内器件上）：随动——拖拽路径不管，重画路径删除+平移重画。
- **边界线**（一端在组内、一端在组外）：拖拽路径由宿主处理；重画路径删除+从移动脚正交重画
  到**原远端点**。
- **拒绝并点名**（v1 一律不猜）：
  - 边界附着是 label / netflag / 总线 / 任何认不出的图元（035 附着物判定同源：只认画布实证的 wire）；
  - 组内含 sheet 边框等非器件图元；
  - 目标位压既有图元 / 压组外走线（geometry bbox 干涉检查）；
  - 位号找不到 / 一个位号对多件；
  - dx/dy 非网格整数倍。
- **验收主判据 = 网表恒等**：移动不改连接——活网表逐脚岛屿比对（自动网双名按 035 同岛规则，
  比岛屿不比名），移动前后**每个脚的岛屿成员完全一致**。任何一脚变了 → exit 2。
- 范围核对：重画路径含删除 → 画布身份级（消失的线恰为 plan 授权的那批，逐 id 点名）+ 活网表；
  拖拽路径无删除 → 导出核对。判据一句话照旧（SKILL 坑 24）。

## 工作项 1：ChangePlan（`core/changeplan.py`）

- `SUPPORTED_KINDS` += `move-block`；`_LATER_KINDS` 清空。
- payload（字段名实现定，必须覆盖）：
  - `moves: [{designator, primitive_id, from:(x,y,rotation), to:(x,y)}]`——逐件记录原 pose，
    这是 stale 判据（被人手挪过 ≠ 计划时的位置 → exit 4）。
  - `wire_ops`（重画路径非空）：每条 `{primitive_id, kind: redraw, points_before, points_after}`，
    人签 plan 时能看到哪些线会被怎么动。
  - postconditions：逐件目标坐标 + 网表恒等断言。
- `from_jsonable` 不变量：moves 非空；from/to 坐标都是网格整数倍；位号两两不同；
  wire_ops 每条 primitive_id 非空。**016/029/035/036 JSON 一字不变**（round-trip 回归钉）。

## 工作项 2：离线 plan/preview + apply 编排（`cli.py` 第五条 edit apply 流程）

- plan 构建看活页（同 029/036）：位号→图元 id 与脚坐标、组内/边界线分类（附着物判定同源 035）、
  目标位干涉检查、网格校验。
- preview：逐件 from→to、wire_ops 逐条、前置条件核对；**永不写**。
- apply：
  - **幂等探测先于 stale**：所有 move 的 to 坐标已达成且网表恒等 → `already_applied` 零写入。
  - stale（exit 4 零写入）：任一件当前 pose ≠ plan 的 from，或授权线按 id 不在板上。
  - 写序：先移器件（modify_primitive 逐件），重画路径再删线+画线；写调用逐条记 `write.calls`。
  - 回读 = postconditions（逐件坐标 + **网表恒等**），双证缺一 exit 3 `verification_disagrees`；
    断连/超时 unknown exit 3 读回不重试。
  - save + 状态分层沿用；**findings 只许减不许增**（036 立的规矩，全规则重跑比对）。

## 工作项 3：测试与验收

- 离线（pytest）：plan/preview/apply 编排（活工程 export→parse 实证幂等）、五种拒绝各配用例、
  组内/边界线分类、网表恒等判据（含自动网同岛）、off-grid 拒绝、round-trip 回归。
  **测试用例与实现同步交付**。
- 变异 ≥2：网表恒等漏判方向 + 范围核对（误拦 / 幻影放行）方向。
- 真机（**只碰 test/test2** 显式寻址；禁地全程只读）：单器件移动 + 多器件块移动各一次真成功
  （坐标回读 + 网表恒等 + 幂等重放 already_applied + stale exit 4 零写入 + 保存分层）；
  边界带 label 的形状造一个，确认**拒绝并点名**。
- 零残留：scratch 页全删、焦点复位、identity consistent。
- 证据 `outputs/037_*.txt`，交卷文本 `outputs/037_summary.txt`。

## 工作项 4：文档

SKILL.md 动作说明区补 move-block 一条、坑表踩新坑再加——**归主代理**，子代理不碰
SKILL.md / PROGRESS.md / git。

## 守卫

照旧：pytest 必带 `--basetemp=.tmp_pt_home`；变异 cp 备份 + sha256/cmp 还原；三线全绿才交卷；
connector 预期**零改动**（探针若证必须动，停下来报主代理）；不碰 git 与 PROGRESS。

## 交卷记录

（子代理交卷全文：`outputs/037_summary.txt`；探针原件 `outputs/037_probe.txt`；真机原件 `outputs/037_live.txt`。）

### 子代理交卷浓缩（agent-43，2026-09-25）

- **探针定论（工作项 0）**：**宿主不拖线**——器件移走（U4 pin1 (555,320)→(680,320)），线的上报端点
  留在原地，连接实际断开 ⇒ 走**重路径**（组内线删除+重画、边界线删除+正交重画到原远端点），
  **connector 零改动即可**（modify_primitive / delete_primitives / place_wire 三件现成）。
  附带实测：`modify_primitive` 间歇抛宿主 `cmdKey` TypeError（改动前抛，器件没动）；
  上报的线是**点集不是路径**（相邻对里有没画过的对角线）。
- **交付**：`engines/moveblock.py`（新——resolve_group 三种拒绝、网格检查、组内/边界线分类与重画、
  目标位干涉、岛屿读法、`postcondition_problems` 一个函数两用、`netlist_differences` 逐脚点名）；
  `changeplan.py`（move-block 转正，`_LATER_KINDS` 清空；PlanMove/PlanWireOp/PlanIsland；
  **016/029/035/036 JSON 一字不变**回归钉）；`cli.py`（第四入口 `edit plan --move`、preview move 分支、
  第五条 apply 流程）；`tests/test_037_moveblock.py`（38 条）。
- **真机（只碰 test 窗）**：多器件块 (U1,U2) by (100,0) applied + saved——写序 modify×2/删线/正交重画/save，
  回读姿态 ok、线端点 ok、**网表恒等 12 脚零差异**、范围 `wiresVanished=[原线]`、findings 无新增、
  幂等 already_applied 零写入、stale（手挪 U1 五格）exit 4 `stale_pose` 零写入；单器件 (U1) by (50,50)
  applied + saved（0 线需重画，恒等判据如实报"没变"）。边界带 label 形状**本机造不出**
  （place_netlabel 不可用，环境限制非没测），拒绝有离线用例。零残留、禁地未寻址。
- **三线/变异**：pytest **1611**（+38）；connector 419 / tsc 干净；变异 3/3 CAUGHT
  （网表恒等漏判 / 幻影放行 / 误拦三方向）。

### 主代理裁决（三处待裁全部批）

1. **偏离 1 批准（线段判 T → 点集成员判定）**：仪器只能说什么就说什么——点集相邻对可能是幻影对角线，
   线段判 T 既漏又假；新判据「脚在上报点集里 = 线画到了脚」，漏判由网表恒等兜底（exit 2 按脚点名），
   比误拒诚实。回退会让单器件移动真机不可用，不回退。
2. **偏离 2 批准（组内线不做同形状平移）**：点集不是路径，照抄必画对角线挂死宿主（029-c）；
   改在移动脚间正交重画，电气结果一致、形状不保证原样——结构限制，不是偷懒。
3. **有条件重试批准**：`modify_primitive` 报错 + 回读证明没落地 → 重试一次并写进报告。
   「读回不重试」禁的是盲目重试；举证重试门控严格（宿主 cmdKey 错误发生在改动前），可以留。

### 主代理复验（2026-09-25）

- sha256 抽核 5 件全对：cli.py `e74904f9…`、changeplan.py `70a91539…`、moveblock.py `d2e8c465…`、
  test_037_moveblock.py `88d81d56…`、test_016_edit_cli.py `565a2bfb…`。
- 三线复跑：pytest **1611 passed** / connector **419 passed** / `tsc --noEmit` 干净。
- `git status` 仅 5 件预期改动（017 草稿未跟踪、不混入）；connector/daemon 零改动，仍 0.4.23。
- SKILL.md 动作说明区补 `--move` 一条，坑表补第 26 条（宿主不拖线 / 点集不是路径 / cmdKey 举证重试）。

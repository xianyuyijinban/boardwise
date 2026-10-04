# 112 — 避障布线：addcomponent.wire_route 升级为正交绕盒搜索

**来源**：岳 2026-10-04 裁定（111 增补批后的工具线硬活之一）。110 反激页
压线/重叠严重的工具侧根因之一：交互画线级的 `wire_route` 只会直线/L 形，
而编译器里早已有一个真正的避障路由器——两边能力断层。

## 现状（已核实，别重新普查）

- `src/boardwise/engines/drawcompiler.py:3466-3654` 的 `_Router`：
  编译格点上的正交 Dijkstra——障碍盒（器件体+文字框+keepout）切盒即拒、
  异网阻塞点（脚尖/标注/旗/线顶点）、异网边（可垂直穿过、不可顺跑不可
  在交叉点转弯）、代价=步 1 + 转弯 TURN_COST + 穿越 CROSS_COST。
  模块级助手：`_segment_hits_box`/`_collinear_overlap`/`_close`/`_key`/
  `_rounded`/`_compress`、`Box` 类型、`TURN_COST`/`CROSS_COST` 常量。
- `src/boardwise/engines/addcomponent.py:268` 的 `wire_route(anchor, target)`
  只会直线/L（029-c 的教训：对角线段挂死宿主，正交是硬约束）。
- 真实消费点（要吃到升级的四个）：
  - `cli.py:17126` 与 `cli.py:17939`（draw 落线流，手上有 `geometry` 快照）；
  - `cli.py:18732`（subcircuit 节点接线，有 pins dict 与 geometry）；
  - `engines/moveblock.py:311,343`（037 移动后删线重画）。
  - `cli.py:19307` 只是对角线护栏（用既有计划点），**不改行为**。
- geometry 快照（sch.geometry 载荷）里有：组件原点、bboxes（调用方传
  bboxIds 才有 per-part 框）、wires 的 points+net、旗。文字框**没有**
  （坑 9），本批不许编造文字几何。

## 架构裁定（主代理已定，照做）

1. **抽出共享路由器**：`_Router` 及其几何助手从 drawcompiler.py 搬到新模块
   `src/boardwise/engines/router.py`，drawcompiler 改为 import。**纯搬家**，
   行为一字不许变——drawcompiler 侧的零移动对账就是证据。搬运范围仔细
   界定：只搬路由器真正用的助手；`_compress` 这类编译器自用但路由器不用
   的不搬（自己判断归属，注释里写明谁还用）。
2. `addcomponent.wire_route` 签名扩为
   `wire_route(anchor, target, *, avoid=None, grid=…, bounds=…)`：
   - `avoid=None` → **行为与今天逐字节相同**（直线/L），既有测试全绿不动；
   - `avoid` 携带 boxes（器件体框，bboxes 缺席就不造——只把原点当阻塞点）、
     blocked（异网脚尖/旗锚/线顶点）、edges（异网既有线段）、start/goal 的
     合法归属（起点是自家引脚、终点是目标网上的点，路由器不得把它们当墙）。
   - 找不到通路 → **返回 None**，调用点诚实上报「无净通路」并按该流程既有
     的失败语义退出（exit 2 风格，notes 点名哪条网哪个引脚），**绝不静默
     穿盒**（那是比 L 形更坏的谎）。
   - 格点：起点/终点未必在格上——residue 由 anchor 推导，goal 不在格上时
     末段处理要想清楚写进注释（不允许产生对角线）。
3. 四个消费点逐个接上（传 avoid），每个的「无可避数据」降级路径明确：
   geometry 没 bboxes 时 boxes 为空、原点/线顶点/异网边照常参与。
4. cli.py 只许在既有函数体内改，既有命令的默认输出一字不动（零移动）。

## 交付纪律（111 同款）

1. 红测先行：合成障碍场（两点隔一颗器件 → L 形会穿体、搜索会绕）、
   终点被围死 → None 的诚实失败、无 avoid 的旧行为钉。先跑红再实现。
2. 变异 ≥2 组（cp+sha256 还原）：例：墙判定摘除 → 穿体测试红；
   CROSS_COST 归零 → 少穿越断言红。
3. 零移动对账：五族预览 83 张 + 15 夹具容器 review 读数，前后 sha256
   全同（方法照 outputs/111/SUMMARY.md §五/§六）。**drawcompiler 搬家后
   编译器输出必须逐字节不变**——这是本批最硬的闸。
4. 全量 pytest：`.venv/Scripts/python.exe -m pytest tests/ -q
   --basetemp=.tmp_pt_home`（基线 **3531 passed**，约 8 分钟），
   跑全量期间不许改代码。connector/dsh-plugin 本批不经过，不用跑。
5. 证据落 `outputs/112/`：合成场路由前后对照（点数/弯数/穿越数）、
   变异 sha、零移动对账、SUMMARY.md（含如实申报节）。
6. `PROGRESS.md` 单行追加（grep -c "112" 必须 =1）。
7. 禁 git 写操作；禁碰真机/daemon；删除走回收站 PowerShell 通道
   （禁 rm/unlink，含自建临时文件）。
8. 不碰 `engines/grammar/`（113 反激语法是另一棒）；不碰 drawlint.py。
9. 真机验证不在本棒（重跑反激时一体验收）。

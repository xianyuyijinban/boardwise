# 任务书：515A — v0.5.15 发版前绘制引擎修洞（挖洞闸缝1/缝2 的高危与中危）

- 批号：**515A**　日期：2026-10-17　来源：挖洞 swarm 缝1/缝2 报告（探针在 `.tmp_hole515_s1/`、`.tmp_hole515_2/`——**先复现再修**，探针转回归测试）。
- 前置：201C 已落账（它动 router.py/drawcompiler.py 布线段；先重读现状）。

## 必修（高危）

1. **多模块页双地同符号**（缝1#2，probe_page_domains.py）：`_ground_domains`（drawcompiler.py:5594 一带）按**模块本地**电路数域，多模块页每模块只看到自己那颗地网 → 域数恒 1 → PGND 和 SEC_GND 都画成 PWR-GND，违反「绝不并地」。修：域判定改读**整页**（pagecompiler 把全页电路的地网域下发给模块编译，或页级 `_flag_profile` 用整页输入）。回归：双模块页（a=PGND、b=SEC_GND，库里有 PWR-PGND/PWR-SEC_GND）→ 两颗不同的字。
2. **拓扑轮没有关系闸**（缝2#1，pb4_e2e.py / pb3_gate.py）：`_topology_placement` 把关系当软代价，带着 miss 也返回，compile 照样 ok=True。修：返回前跑一次关系闸（用合一后的 `placement.relation_holds` 那把尺），miss 非空 → 该档按 GrammarFailure 拒绝（与阶梯同口径）。回归：注入互斥关系的 power_entry 探针，拓扑轮必须拒。
3. **拓扑轮不读 userLocks 坐标**（缝2#2，pc2_locks.py）：PlacementPart 没有坐标字段，锁定件被搜索挪走 → 必然 user-lock-violated。修：锁坐标作为硬锚进 PlacementInput（钉死原点、豁免吸附/平移/旋转），readability 的锁校验仍逐字比。

## 必修（中危，都是小改）

4. **路由失败降级 label 时不写回 expressions**（缝1#1，probe_gnd_label_forced.py）：地网降级后旗标 pass 仍当它是 wire，挂了唯一地符号还写下「pads are joined by the rail」的假话。修：写回 `expressions[net_id]`；note 改成由实际绘制结果推出（有轨道才写 joined by the rail）。同函数 12 行外 `_flag_wire_fallback` 有同类修正先例。
5. **关系尺边界不一致**（缝2#3，pa_boundary.py）：`relation_miss`（<=）与 `relation_holds`（<）在边界上答案不同。修：四个严格序 + adjacent 改成严格同号式；补边界参数化用例。
6. **旗位预留与实际落旗脚不是一把尺**（缝1#4/缝2#4）：`_flag_seats` 的 gnd 分支改调 `_flag_seat_pins` 取首档；预留框把引脚坐标算进去（别只围元件原点）。
7. **stall 计数在 continue 路径不累计**（缝2#5）：全锁件输入时 6000 次空转。修：continue 也计 stall，或全锁短路返回种子。
8. **页级框归属盲区**（缝1#3，probe_page_crossmodule.py）：`geometry-outside-frames` 只问「在某个框里」不问「在自己的框里」。修：readability 页级补 membership 判定（对象 ∈ 自己模块的框）。

## 纪律

- 地盘：engines/drawcompiler.py、engines/placement.py、engines/readability.py、engines/pagecompiler.py（如需）、grammar/flyback.py。不碰 router.py（201C 刚动完，除非必读）。不碰 tools/、packaging/、.githooks/、dsh-plugin/（515B 在做）。
- 改了 rules/** 才重钉指纹（本批大概率不碰）。
- 零移动闸动了就前后对比重钉（201A/B 同流程）。
- 全量绿 `--basetemp=.tmp_pt_515a -n 4 --dist loadfile`（test_193 槽位红单跑确认）。变异 ≥2 组。
- 企业名零出现；不动 git；不 rm（回收站）；不碰真机/bridge。
- 证据 outputs/515a/evidence.md；PROGRESS.md append 一行；不要 commit。约 100 分钟。

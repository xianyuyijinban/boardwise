# 任务书：201C — 布线协商：让反激的直连走廊走得通（rip-up & reroute）

- 批号：**201C**　日期：2026-10-17　来源：201B 阶段二收尾后反激的唯一死因——`net 'SW' has a direct-wire obligation … could not be joined inside the searched corridor`。侦察 200a 与 201B 实测共同定位：布线层缺「网间协商」。
- 现状（都已读代码核实过，先复核再动）：
  - `engines/router.py::_Router.route`：A* over (node, arrival direction)，步 1 + 拐弯 0.6 + 穿越 120。这个内核**留着不动**（112 抽出来时就定了「一把尺」）。
  - `engines/drawcompiler.py`：`_net_order:6440` 一次定死（直连主干优先，其余按脚数）；`_connect_net:6207` 失败就降级成网标签（`DOWNGRADE_NOTE_PREFIX`），**不回头**；`_elbow_route:6281` 的 L 形捷径**绕开 A\* 定价**（不付 CROSS_COST，175 的教训就是它推不动）；直连义务（`direct-wire`）找不到走廊即整档判死。
  - 201B 试过「走廊几何代理代价项」：要么慢（141 s）要么只把死因从 SW 挪到 SRC——**几何代理项此路不通**，别再走。

## 要做的（按序，每一步有独立验收）

1. **L 形捷径并入定价**：`_elbow_route` 的候选也要付与 A* 相同的穿越/贴边代价（可以仍是捷径——先算它，但代价不对就交给 A*）。验收：175 那条 COMP 线场景（找既有测试）在抬高 CROSS_COST 下不再抄近路穿干线。
2. **失败后的协商**：`_connect_net` 失败 → 不立刻降级标签，而是：
   a. 记录阻塞它的异网导体（哪些线段/端点挡了路——router 的障碍读数里就有）；
   b. **rip-up 一条**挡路网（优先：非直连义务、脚数少、绕行代价低），重布当前网，再重布被拆的那条；
   c. 一轮仍失败才降级标签，且降级理由里写明「被谁挡、拆了谁、仍不通」。
   循环上限（比如 2 轮）+ 全程确定性（同输入同输出，种子固定）。
3. **直连走廊的路由期保护**：`direct-wire` 义务的网在布其它网**之前**先布（`_net_order` 已做）——本批补一条：义务网布完后，把它的走廊（两脚间最小包围盒膨胀 N 格）登记为「软预留」，后来的网穿越付高价（不是禁行，别再造死局）。N 取 2 格起步，写常量 + docstring。

## 验收锚

- **反激 `draw compile` 出 ≥1 个 `ok=True` 候选**（readability 硬闸不放宽），SVG 落 `outputs/201c/previews/` 主代理亲眼看。
- 若仍不出，给出**路由层的逐网读数**：每条直连义务网「走廊里有什么、拆了什么、还差几格」——不许只报一句失败。
- divider 三件套 + 五模板编译仍过；**已能出图的页不许被换掉**（201B 的口径延续：协商只在原路径失败时才介入）。
- 降级标签的总数在全部夹具上不增加（对照表）。
- 性能：反激单档编译 < 60s。
- 零移动闸动了就前后对比重钉（同前两批流程）。

## 纪律

- 地盘：`engines/router.py`（只在不改动价语义前提下加读数/接口）、`engines/drawcompiler.py` 布线段、新测试 `tests/test_201c_routing.py`。**不碰** `placement.py`、`grammar/`、旗标函数。
- 全量绿 `--basetemp=.tmp_pt_201c -n 4 --dist loadfile`（test_193 槽位红就单跑确认）；变异 ≥2 组（关 rip-up、L 捷径不付代价）。
- 企业名零出现；不动 git；不 rm（回收站）；不碰真机（主代理在 test/test2 窗做实验，**不许动 bridge**）。
- 证据 `outputs/201c/evidence.md`；PROGRESS.md append 一行；**不要 commit**。约 100 分钟没完就停手收尾。

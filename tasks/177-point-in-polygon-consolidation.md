# 177 多边形包含判定收编（point_in_polygon 三副本 → core 一件公共件）

任务编号 177。类型：**零行为变化的纯重构** + 注释钉界。主代理裁决已下，本文件是唯一权威任务书。

## 背景（主代理已查证，直接采信）

仓库里有三份「点在多边形内」的私有实现：

1. `src/boardwise/core/measure.py:764` — `_point_in_polygon(point: Point, polygon: list[Point])`。
   even-odd + 「压边算在内」（`_point_segment_distance <= 1e-9` 即 True）。
2. `src/boardwise/rules/pcb/focthermal.py:791` — 同名同签名。docstring 自述：照抄 measure.py，
   因为「仓库分层规矩禁止跨层 import `_` 前缀名」。
3. `src/boardwise/rules/pcb/silk.py:295` — **算法故意不同**：纯 even-odd，**没有压边规则**，
   签名也不同（`(x: float, y: float, points: list[tuple])`，服务本文件 `_as_xy` 管线）。
   丝印盒边恰好压焊盘角时，它的读数是 0（不算压上），而前两份会报「在内」（负间隙）。

另外 `focthermal.py:815` 的 `_point_segment_distance` 与 `core/measure.py` 里的同名实现
疑似同一份数学（主代理未逐行 diff，**由你核验**）。

## 目标

1. `core/measure.py`：把 `_point_in_polygon` 提升为**公开** `point_in_polygon`（docstring 保留并
   补一句「177 提升为公开：rules 层可以合法 import，副本消灭」）。本文件内部调用点同步改名。
2. `focthermal.py`：删掉私有副本，改为 `from ...core.measure import point_in_polygon`
   （相对 import 层级按该文件现有 import 写法）。删之前**逐行 diff 两份实现**（含压边阈值），
   不完全一致就停下来报告，不许合并。
3. `_point_segment_distance`：同样先 diff measure 与 focthermal 两份；完全一致才按同法收编
   （公开 `point_segment_distance`），不一致就只收编 polygon 那件并在证据里说明。
4. `silk.py`：**不动算法**。只在它的 `_point_in_polygon` docstring 上补一段钉界：这是纯
   even-odd、压边不算在内，与 core 公开件的差异是**故意的**（丝印盒贴边 ≠ 压上），别后来人
   又提「三份副本」的 bug。
5. 全仓 grep `_point_in_polygon` / `_point_segment_distance`（含 tests/、evidence/ 之外的所有
   `.py`）：tests 若有 import 私有名的，同步改到公开名。evidence/ 目录一律不碰。

## 红线（仓库 AGENTS.md + 主代理纪律，逐条有效）

- 禁 git 一切动词；禁 `rm`/`unlink`——任何删除走回收站 PowerShell 通道（SKILL.md §7 写法）。
- pytest 必带 `--basetemp=.tmp_pt_home`（Windows 否则汇总行被吞）。
- 分层规矩先找到出处（AGENTS.md / SKILL.md / 某条测试），确认「公开名跨层 import 合法」再动手。
- 零行为变化是验收锚：**变异验证 ≥2**——改动前后各跑一次受影响测试文件之外，再从
  `cp` 备份还原（sha256 校验）后跑一次全绿，证明改动本身可逆且行为不动。

## 验收

- `tests/` 下与 measure / focthermal / silk 相关的测试文件全绿（自己定位，至少包括
  test_040b 系、silk 系、focthermal 系；用 grep 找引用）。
- 全量快版：`.venv/Scripts/python.exe -m pytest tests/ -q -n auto --dist loadfile --basetemp=.tmp_pt_home`
  跑一次，总数与基线 **5402 passed + 23 skipped** 对得上（补钉 4bddc12 后应是
  5402 passed；若基线已变以你跑前的 git HEAD 全量为准——不必真跑两遍，受影响文件全绿 +
  一次全量即可）。
- 证据落 `outputs/177/evidence.md`（append，落盘后 `grep -c` 防双写）：diff 结论、
  改了哪些文件、测试计数、变异验证记录。

## 交卷格式

回给主代理：改了哪些文件（路径清单）、diff 核验结论、测试计数（受影响文件 + 全量）、
变异验证记录位置、遗留风险。不要贴大段代码。

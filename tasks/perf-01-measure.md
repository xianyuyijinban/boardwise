# perf-01：性能热力图（只测量，不修）

岳 2026-10-13 立：优化 boardwise 的时间 + CPU + 内存。**本包只测量出图，不许改任何
生产代码**（测量脚本落 outputs/perf/）。

## 背景

- 全量 5568 条测试：串行 ~19 min，`-n auto` ~5-6 min（但把核打满，今天被岳叫停），
  `-n 4` ~8 min。
- 生产侧：checkup/review 对大板（3MB epro2）秒级；daemon 常驻 61190；exe 是
  PyInstaller  frozen。
- 已知线索：绘制编译器黄金场景族（053b/069/099/147/148 系）每条都真跑
  「布局约束 + Dijkstra + 可读性闸 + 多候选」；159 加了 golden 求解 session 缓存
  （tests/_golden.py）；xdist 下每个 worker 是否各建缓存待查。

## 测量清单（全部跑在 `-n 4` 或更少，别打满机器）

1. **测试时间热力图**：全量 `-n 4 --durations=40` 跑一遍，落 top40 慢测试；
   再对 top5 慢**文件**单独 `--durations=0` 拆到单条。cProfile 最慢的 3 个模块
   （`-m cProfile -o`，pandas 不要，pstats 排序 cumulative 取前 20 函数）。
2. **xdist 缓存复用核查**：golden 缓存在 worker 间是否各建一遍（数 logs/文件计数，
   或给 _golden.py 加临时计数探针——探针只许落在 outputs/perf/，不许进 tests/）。
3. **生产侧**：`checkup --file` 最大夹具（毕设FOC v1.0.0 或 ROBOT）计时 + 峰值内存
   （`tracemalloc` 或 `psutil` 进程 RSS 采样）；`review` 同理；CLI `--version` 冷启动
   计时（src 形态与 frozen exe 形态各 5 次取中位）。
4. **daemon 常驻开销**：61190 的 daemon 进程空闲 RSS + CPU（PowerShell
   `Get-Process` 采样 3 次取均值）；connector 不在本包（编辑器侧，另算）。
5. **exe 冷启动**：`packaging/out/boardwise.exe --version` 计时 5 次。

## 产出

`outputs/perf/heatmap.md`：top 慢测试表 + cProfile 热点函数表 + 各进程 CPU/内存读数
+ **候选优化清单**（每条：是什么、预期省多少、依据、风险）。证据全落 outputs/perf/。
不许改 src/tests/connector；探针脚本放 outputs/perf/。pytest 一律 `--basetemp=.tmp_pt_perf`。
禁 git、禁 rm。机器是岳在用的主力机：**总并发线程 ≤4**，宁可慢。

## 交卷

热力图要点 + 候选清单（按预期收益排序）+ 全部原始读数路径。

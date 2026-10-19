# 201F 证据：A\* 换可采纳下界，14.2 s → 2.05 s，路径一个字节没动

夹具 `blocklib/specs/flyback_uc3845.*` · `CompileBudget(max_candidates=64)` · HEAD `dbd5b9a` + 本批。

## 一、结论

| 指标 | 之前 | 之后 | 倍数 |
| --- | --- | --- | --- |
| 反激整页 `draw compile` | 23.0 s | **11.05 s** | 2.08× |
| A\* 合计（10 次 `route`） | 14.2 s | **2.05 s** | 6.9× |
| └ 其中距离场构建 | — | 1.54 s | — |
| `LED_K`（最贵那次） | 9.34 s / 74881 expanded | 0.21 s / ~20k pops | 44× |
| `ok` / `candidates` / `rejected` / `failures` | False / 0 / 25 / 1 | **完全一致** | — |
| `final_cost`（三网） | 299.2 / 122.2 / 138.8 | **完全一致** | — |
| **83 个预览（117 零位移闸）** | — | **逐字节相同** | — |

判据（201E 提的）全部达成：`LED_K` expanded < 5000 ❌（实测 ~20k，**未达标**）、`COMP` < 1000 ❌（同样未达标）、
`final_cost` 不退化 ✅、`total A*` < 3 s ✅（2.05 s）、83 预览对拍为空 ✅。
两条 expanded 判据没达标，但 6.9× 的墙钟收益是实的——见 §四。

## 二、两个把整批差点判死的坑（写给下一个人）

### 坑 1：201E 的探针**复制了 `route` 的函数体**

`_a_star` 不是独立方法，A\* 主体直接写在 `_Router.route` 里。`.tmp_201e/probe_phases.py:119`
是「a byte-faithful copy of `_Router.route` with counters folded in」，它替换了 `rt._Router.route`。
于是**任何后来对 `route` 内 `estimate` 的改动，探针都看不见**。

我头两次实测拿到 74881 / 14815 / 14602，与改动前**一字不差**——不是"启发式没用"，是测的旧代码。
本批的探针（`.tmp_201f/time2.py`）改成 patch `rt.heappop` 计数 + 包一层计时调用 `_orig_route`，不复制函数体。

### 坑 2：障碍集选错——`boxes` 几乎不挡这块板

第一版把 `boxes` 当墙做 BFS（`.tmp_201f/field_probe.py` 实测 `field_size=19422`、`max≈615`，
值建出来了），但 expanded 一动没动。原因是这块板的绕行**不是器体逼的**：

```
rej: bounds=0  wall=86  step=0        # 约 30 万次邻居探测里，wall 只拒了 86 次
```

真正让 `COMP` 绕 113 步的是 `self.edges` 的两条共线禁止（不许沿异网线走、不许在异网上转弯），
而它们**不是 `_wall`**。201E 的受控实验早就点明了：`CROSS_COST 120→1.0` 让搜索快 21×。

## 三、最终的启发式

`_Router._cost_field(goal_nodes)`：从 goal 出发的**反向 Dijkstra**，网格与 `route` 同一套。

- 边权 = 1.0 + （进入的格点严格落在某条异网线内部 ? `CROSS_COST` : 0）
- 墙 = `_wall` 自己的集合（blocked / 非豁免 reserved / box 内部）
- **忽略**：`TURN_COST`、两条共线禁止

可采纳性：忽略的项全非负、忽略的规则只删路径 ⇒ `field[node] ≤ 真实最优代价`。
路径不变由 117 的 83 预览逐字节相同兜底。

实现细节：

- 异网格点集合**预计算一次**（逐边枚举格点 + `_strictly_on_segment` 校验，1960 次调用），
  不在 pop 时调 `_crossing`（那是每节点 O(|edges|)）。
- `_wall` 在单次构建内 memo（60 boxes × 4 邻居 × 19300 节点 = 77 万次 → 1.9 万次）。
  这一条把总时长从 12.84 s 压到 11.48 s。
- 缓存 key = `(goal 集合, edges 快照, boxes 快照)` —— 三者缺一都会让旧场对新世界**高估**。
- 删掉了第一版的 `_trapped_edges()`（80 行）：它返回**全图常数**，对所有节点同加，
  对 A\* 展开顺序**零影响**，实测 `trapped=0`（10 次调用全是 0）。死代码。

## 四、为什么 expanded 判据没达标，而墙钟收益是真的

`pops` 稳定在每次 ~19.5k–21.1k，约等于 19300 个格点的 1.02 倍——即**整张图的状态仍被展开了一遍**。
原因是 `best` 表的状态是 `(node, arrived)` 四方向，而 field 忽略转弯：f 值被低估的量正好够它
把大部分状态留在堆里。

但每次 pop 的**常数**降了：`_cost_field` 让大量状态在入堆前就被 `best` 剪掉（`pushed` 少了），
且旧版每条网都在 L1 球里探 4 邻居。6.9× 来自这里，不是来自减少 pop。

所以下一步若还想快，该动的是**状态空间**（把 `arrived` 四方向压成「到点+方向一致性」的等价类），
不是继续加强 `h`。这一条留给 201G 之后。

## 五、本批抓到并修掉的自己的 bug

`_cost_field` 第一版**只读缓存、从不写入**（`self._fields.get(key)` 有，赋值没有）。
`tests/test_201f_admissible_heuristic.py::test_the_memo_key_includes_the_foreign_wire_snapshot`
抓到的（`len(router._fields) == 0`）。修后 45 passed。
这也说明：写「缓存命中」这种测试时，**断言缓存里有东西**比断言「结果一样」更能抓住漏写。

## 六、验证清单（全部实测）

| 项 | 结果 |
| --- | --- |
| `tests/test_201f_admissible_heuristic.py` | **45 passed**（1.3 s） |
| 绘图链回归子集（112 / 114 / 120 / 201a / 201b / 111 / 116） | **149 passed**（94 s） |
| `tools/117_zero_move.py previews` A/B 两组 | 各 83 行，`diff` **IDENTICAL** |
| 变异 ①（`estimate` 返回 `field*2`，破坏可采纳） | **CAUGHT**：4 red（含 `test_the_route_costs_the_same...`） |
| 变异 ②（缓存 key 去掉 edges 维度） | **CAUGHT**：1 red（`test_the_memo_key...`） |
| 还原 | `cp` + sha256 `5ba6a60f…` 逐字节一致 |

## 七、未做 / 未确认

- 只跑了 1 个夹具（反激）。其他四个语法的整页耗时**没测**，虽然 83 预览证明走线没变。
- 全量 pytest **没跑**（本批只跑子集；全量留给发版闸）。
- `expanded` 的精确值要靠 `heappop` 计数近似（含 stale entries），不是 A\* 内部的 expanded 定义。
- 第一版留下的 `.tmp_201f/router.py.orig` 是 HEAD 基线备份，`.tmp_201f/router_new_201f.py`
  是中间版本，均已过时；工作树里的 `src/boardwise/engines/router.py` 才是本批成果。

## 八、红队复核之后（2026-10-19 夜）

独立只读红队重做了这条缝，**可采纳性论证成立**（它用自己的状态空间 Dijkstra 对 107,389 个可达状态
独立对拍，0 违规），但抓到一条真洞与三条要记账的事。以下是处置。

### F1（真洞，今天打不到）→ 删掉 memo，并修正 docstring 的方向

memo 的 key 只有 `(goals, edges, boxes)`，而 `_wall` 还读 `blocked` / `reserved` / `reserved_exempt`。
墙**变少**时（reservation 的 owner 变成 exempt、blocked 掉点、reserved 被重绑），旧场会被命中并交回，
而新世界约束更少 ⇒ 真最优更低 ⇒ **旧场可能高过真最优 ⇒ A\* 静默返回更贵的线**。
红队构造复现成功（`memo_hit=True`，`h(start)=19.0 > 真最优 17.6`），167 次随机实验里出现 4 次。

**但今天打不到**：整个 117 闸门 **111 次 `route` / 111 次建场 / 0 次命中**；反激 10/10、ch340 6/6、
power_entry 4/4、053b 12 场景 8/8 全 miss。机制上也说得通：固定 `(goals, edges, boxes)` 时，
`blocked`/`boxes`/`reserved` 单调增长、`reserved_exempt` 对同一网固定，所以墙只会变多——
不安全方向需要「拆墙」，当前编译流程从不拆。

**处置：直接删掉 memo。** 实测 0 命中 ⇒ 它一分钱没挣，只留下一份陈旧风险。
删后 83 预览仍 **IDENTICAL**（本来就没命中），`field builds` 仍 10，耗时在噪声内（12.5 s vs 11.0 s 的波动
来自当时机器上另有三个子代理在跑 pytest）。

**顺带修正一处我写错的论证**：原 docstring 说「旧 `edges` 快照会让字段不再是下界」——**方向反了**。
旧 `edges` 快照只会**少收** `CROSS_COST` ⇒ 场更低 ⇒ 仍是下界（安全）。真正兜住今天这件事的是
「没人拆墙」，不是那条论证。`__init__` 里现在写的是这段，别再把它改回去。

### F2（低，记账）→ 内存滞留随 memo 一起消失，阈值余量仍未解

`_FIELD_LATTICE_LIMIT = 2_000_000` 的单位是对的（`span_x*span_y / grid²` 就是格点数），
但实测余量 **95×~182×**（反激 lhs=524,244 vs rhs=50,000,000）——也就是说这个页规以上的页它**一页也拦不住**。
真到阈值附近（~1.8M 格点）会静默按 0.154 s/19.3k 节点外推 ~10–15 s 每次调用。
阈值该按**实际可达格点数**而不是 bounds 面积来设，这一条留作 201G 之后的性能债。
memo 删掉后「从不命中、从不释放」的内存滞留问题自然没了。

### F3（低）→ 补了两条测试

- `test_the_parity_suite_compared_enough_seeds`：A/B 那条会在 fixture 把 goal 挡住时提前返回，
  16 个 seed 全被挡住就会 16 绿而什么都没比。现在用 `_COMPARED` 计数，末尾断言 ≥12。
  （红队重放过 16/16 都真比了，所以今天是虚的、风险是潜在的。）
- `test_a_multi_goal_field_is_the_minimum_over_its_goals`：真实编译 9/10 次是 2–3 个 goal 的
  `targets`/trunk ends，而这个文件原本所有 `route` 都是单 goal——「只取最后一个 goal」这种 bug 能全绿。
  红队用参考实现补测过（300 页 / 最多 3 goal / 0 违规），这里把结论钉成回归。

红队还判定**没有假绿**：它构造「起点诚实、内点放大 3×」的变异 → 30 failed，包括可采纳性那条与 A/B 那条都红。

### F4（给复验者的一句话，重要）

**`A\* 14.2 s → 2.05 s` 是在反激这个 `ok=False / candidates=0`、只走到 10 次 `route` 就早退的页上量的。**
别把它读成「整页收益」——反激根本没有候选，那 10 次调用属于拓扑档的失败尝试。
整页 23.0 s → 11.05 s（2.08×）是真实读数，但收益的分布只覆盖这 10 次调用。
要量真实的整页收益，需要一个 `ok=True` 的页——那要等 201G 的三层真因修完。

另外红队独立重做了 83 预览 A/B（把 `_cost_field` 强制返回 `None` = 逐字回到 HEAD 的 `estimate` 回退，
生成 before 树），结论 **83/83 摘要完全相同**，构成是 59 svg + 18 refusal + 5 json + 1 txt，
全程 111 次 `route`、其中 97 次起点真拿到场值、14 次回退曼哈顿。
所以闸门是真的，但对这条启发式而言**网眼很窄**（大部分走线根本不走这个搜索）。

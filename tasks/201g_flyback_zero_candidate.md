# 201G —— 反激整页 0 候选的两个真因（先诊断，不许动手改）

> 立项 2026-10-19 夜，由 201E 的实测倒逼出来。201E 的唯一任务是"量清楚 A\* 贵在哪"，
> 它顺手交回一条更要紧的结论：**整页 0 候选跟 A\* 快不快没关系**。
> 本文只发诊断单，改法等诊断回来再裁。

## 一、现象（201E 实测，HEAD `dbd5b9a` / 0.5.18）

夹具 `blocklib/specs/flyback_uc3845.{circuit,presentation,library}.json`，
`CompileBudget(max_candidates=64)`，单次编译 **23.2 s**：

```
ok=False candidates=0 rejected=25 failures=1
```

25 个变体档的死亡分布：

| 档 | 数量 | 死因 |
| --- | --- | --- |
| 构造阶梯 `_place_chain_and_shelf` | 24 | 关系检查：`same-column(Q1, R5)` / `near(R15, R3)` |
| 拓扑搜索 `_topology_placement` | 1 | **旗标席位**：`SEC_12V` 无处可挂 |

可读性闸 `readability.check` **一次都没被调用**（没有任何变体活到评分那一步）。

## 二、两个疑点，要分开查

### 疑点 A：`same-column(Q1, R5)` 为什么在全部 42 个变体里都不成立？

notes 原文（201E 日志）：

> no candidate from the 6 base variant(s); every one of them was refused by the same
> relation (same-column(Q1, R5)), so the pose ladder was widened to the 18 variant(s)
> its accepted poses still hold
> no candidate from the 24 constructive variant(s) (near(R15, R3)), so the topology
> search was run …

即：6 个基线档 + 18 个 pose 变体档，**全部**死在同一条关系上；扩到 24 个构造档，
又**全部**死在另一条关系上。这不像"间距放不下"，更像下面三种之一：

1. **关系本身在几何上无解**（presentation spec 写了一条这块板永远满足不了的关系）；
2. **求解器的关系判据过严**（比如按引脚端点判而不是按器件中心，或容差小于格点步长 5）；
3. **关系互相冲突**（A 要求 Q1 与 R5 同列，B 要求 R5 在 R3 附近，而 Q1 与 R3 的席位又互斥）。

**要回答的**：逐条打印这两条关系的 `left`/`right`/容差/判据用的是哪个坐标（中心 vs 引脚端点 vs
包围盒边），以及它们与其它关系的冲突图。**结论必须是三者之一，并给出证据**（不要"可能是"）。

> 相关的已知教训：`docs/drawing-algorithm-brief.md` 里记过「把关系权重从 10 提到 50，
> 坐标完全不变」——那次的诊断是"按引脚端点坐标判，而不是器件中心"。本条要确认是不是同一形态。

### 疑点 B：`SEC_12V` 的旗标在 `D3.1` 为什么无处可挂？

failure 原文（201E 日志，**被截断**，本批第一件事就是拿全文）：

> net 'SEC_12V' is a rail drawn as a wire and every power flag on it must be stated
> (069 sec.7), but no legal place to hang one was found at the pin that supplies it,
> D3.1 at (90, 150): every reach every ladder tries — a s…

代码位置：`src/boardwise/engines/drawcompiler.py`

- `_rail_flag_room_failure()` :8655（`blocked_by` 就是被截断的那段）
- `_rail_flag_seat()` :8728（ladder 主体）
- `_flag_seat_pins()` :8629（候选 pin 的顺序）
- `_wire_flag_seats()` :8569（席位遍历入口）
- `_flag_seats()` :2692（布局阶段预留，`FlagReservation`）

**要回答的**：把 ladder 的每一个方向/每一档逐个打印出来，每条给出"被什么挡住"的**具体对象**
（哪个器体、哪条文字的包围盒、哪条异网走线、还是页边），做成一张表：

| ladder 档 | anchor | rotation | lead | 失败原因（具体对象 id + 坐标） |
| --- | --- | --- | --- | --- |

以及：`D3.1 at (90,150)` 周围的可用空白到底有多少（用格点数量化），以及**是布局把器件堆到了
没地方插旗的程度，还是席位求解器的 clearance/文字盒估算过保守**。

## 三、判据：能不能靠"挪一下"解决？

诊断要顺手回答一个问题，答案决定后面走哪条路：

- **如果疑点 A 是「关系无解」** → 那是 presentation spec 的数据问题，不是算法问题。
  要给出这块板**哪条关系必须删/放宽**，以及删了之后 24 档里会有几档活下来（跑一遍实测）。
- **如果疑点 B 是「布局太挤」** → 那是 052 拓扑搜索的目标函数缺项（没把旗标席位当约束），
  属于大改，要给出改动面与代价。
- **如果疑点 B 是「求解器过保守」** → 那是小改，给出具体哪个 clearance/哪个文字盒估算，
  以及放宽后会不会重新出现 148 拒绝过的那个形状（旗标压线，`outputs/147/FINDINGS.md` §0.3）。

## 四、纪律

- **不改 `src/`**。本批只要诊断报告。要跑实验就 monkeypatch（照 `.tmp_201e/probe_phases.py`
  的做法），临时脚本只写 `.tmp_201g/`，结论写 `outputs/201g/evidence.md`。
- **等 201F 落地后再跑**：201F 正在改 `src/boardwise/engines/router.py` 的 `estimate()`，
  它的读数会污染你的编译耗时。开始前先 `git status --short src/` 看清楚，若 `router.py` 还是 M
  就先只读代码、不跑编译。
- pytest 带 `--basetemp=.tmp_pt_201g`，单进程，不跑全量。
- 零 git 操作；删除走回收站（PowerShell `SendToRecycleBin`），禁 `rm`；源码 CRLF。
- 单次编译 > 180 s 就杀掉换更小的 max_candidates。
- 报告里**每一句结论都要有可复现的命令或日志行号**。不确定就写"未确认"。

## 五、交付

1. 疑点 A 的结论（三者之一）+ 证据 + "删了哪条关系后能活几档"的实测数字。
2. 疑点 B 的 ladder 失败表（逐档，具体对象）+ 空白量化 + 三种归因的判定。
3. 一句总判断：**先修 A 还是先修 B**，理由一句话。

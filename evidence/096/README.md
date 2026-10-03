# evidence/096 —— 页级两缺陷修复（088 §七.a/b 钉案）

任务书：`tasks/096-page-two-defects.md`。**纯离线**：不碰 bridge / 真机 / connector / dsh
（三处 JS 一键未跑也要说明，见交卷报告）；**不动 git**；**零删除**（本目录下没有任何
产物被删，脚本也不 `rm`）。

## 一、这份证据里有什么

| 文件 | 是什么 |
|---|---|
| `defect_probe.py` | 两处缺陷的同一套实测探针，参数是要测的树：`defect_probe.py <tree-root>`。只读、不写源文件 |
| `pre_fix_measurements.txt` | 上面这支探针在 **HEAD 树（修复前）** 与 **工作树（修复后）** 上各跑一次的完整输出 |
| `scene_hash_check.sh` | 四个预览生成器（053b/056/088/088b）在 HEAD 树与工作树上的逐文件哈希对比（本脚本不删任何东西，重跑前需先把 `.tmp_096/hash` 挪走） |
| `scene_declaration.md` | **逐张申报表**：动了哪一张、为什么、原锚点是否越界 |
| `.tmp_096/hash/scene_hashes.txt` | 71 个预览文件的 sha256 前后清单（142 行；工作区外，gitignore 的构建产物） |
| `full_suite.txt` | 最终冻结树上的四线结果（pytest 3144 passed / connector 419 pass / connector tsc / dsh-plugin 三件套） |
| `mutation_M1.txt` | 变异①：③a 修回双判据 → 0 候选复现（+ 变异期间的 sha256） |
| `mutation_M2.txt` | 变异②：③b 吸附改回最近 → 1170×825 复现（+ 三种吸附策略的对照表） |
| `hashes.txt` | 本批五个改动文件的 sha256（修复前 / 修复后）+ 还原复核 + 两轮变异期间的异常哈希 |

## 二、两处缺陷的修复前/后实测（数字都来自 `defect_probe.py`）

**③a 4 成员电源轨标 mainPath（页级）**

| | 修复前（HEAD） | 修复后（工作树） |
|---|---|---|
| 页级候选 | **0**（8 个变体全落选） | **8** |
| 模块自身 | inlet/sense 都 ok | inlet/sense 都 ok |
| 失败原文 | `the presentation marks this edge main-path, but no wire joins the two modules (the nets they share are all buses, which are always expressed by name (+24V, GND))` | 无失败 |
| rail 的 port 种类 | —（没有页） | `wire` |
| GND 的 port 种类 | —（没有页） | `flag` |

**「rail 仍一条实体线」的实测**（同一张页，探针 `.tmp_096/probe4.py` 的输出）：

```
+24V: 2 个段，port kinds ['wire']
      [(125, 775), (245, 775)]                          ← 模块内部那一节
      [(245, 775), (490, 775), (490, 785)]              ← 跨模块那一节（一个折角）
GND : 3 个段（两节模块内部引线 + 两个旗），port kinds ['flag']
```

两段在 `(245, 775)` 首尾相接，端点分别落在 inlet 的 port `(245, 775)` 与 sense 的
port `(490, 785)` 上——**一条导体、一个折角、两端都是 port**，页级一致性检查
（`shared-net-expression-split`：一个网要么整条线要么全名）也是在这条页上放行的。
033a 改写后的钉子测试就钉这一条（`wire_for` + `touches` 两个既有 helper）。
GND 全程走旗、没有跨模块线——069 v3 不回归。

**③b 岳样板声明在 1170×825 上**

| | 修复前（HEAD） | 修复后（工作树） |
|---|---|---|
| 声明页面的候选 | **0**（6 个变体全落选） | **3** |
| 不声明页面（对照） | 3 | 3 |
| 失败原文 | `[layout-unsat] the smallest legal layout of this circuit is 416 x 171 canvas units, and the stated region is 1170 x 825 with a 20-unit margin on each side …` | 无失败 |
| 锚点位移 | `dx` 原始 331 → 落 **330**（往左 1，向外）；`dy` 原始 699 → 落 **700**（往上 1，向外） | `dx` 331 → **335**（往右 4，向内）；`dy` 699 → **695**（往下 4，向内） |
| 图形实测 bbox | `(15, 612, 431, 783)`（由自由图 `(-315,-88,101,83)` + 位移 `(330,700)` 得到；`_overflow` 的实测也是这一组） | `(20.0, 607.0, 436.0, 778.0)` 起，**左边贴住页边 20，excess = 0** |
| 判定 | `box[0] = 15 < 20` → 拒 | 全部落回页边内 |

**关于 088 docstring 里那句「box[0] = 18 < 20」**：096 在 HEAD 树上复测到的是 **15 < 20**
（短 5 单位），不是 18。机制与 088 记的一致（先留 `PAGE_MARGIN` 再吸格点，容差 1e-6），
数值差多半来自 088 记的是另一次插桩的点位。**096 保留原 docstring 原文不动**（历史价值），
只补一行「096 已修」。

## 三、一个必须写下来的发现：内吸只解决了一半，另一半是估算

> **097 已修（2026-10-03，本批）。** 下表的最后一格（"完全不动 → 仍被拒"）是 096
> 留的遗留：`_annotation_allowance` 横向只数**网名**（`stub + 最宽网名 + TEXT_GAP`
> = 66），没有数器件自己的位号/值文字——岳样板上那颗 `SMCJ28CA`（宽 62）画在器件
> 左侧，实际外伸 **70**，差的正是 4 单位。097 把文字分量按同一套字形表量进去
> （两项取较大者，见 `src/boardwise/engines/drawcompiler.py::_annotation_allowance`），
> 于是"位移取精确值"这一格现在是**通过**：`tests/test_097_annotation_allowance.py`
> 把吸附关掉（`_snap_inside` 置为恒等）仍然有候选、左边正好贴住页边。下面这段
> 096 的实测记录原样保留（历史价值）。

`_anchor_to_page` 的横坐标不是只有吸附一处误差。096 实测（`mutation_M2.txt` 末段，
探针按三种策略各跑一次同一张场面）：

| 吸附策略 | 结果 |
|---|---|
| 朝页内 ceil/floor（本批修法） | ok，3 候选，左边实测 20.0 |
| **完全不动**（位移取精确值，仍在格点之外） | **仍被拒**——`_annotation_allowance` 对这张图横向估短 **4** 单位（**097 已修**：现在不吸附也有 2 候选、左边正好 20.0） |
| 最近格点（旧行为） | 被拒 |

也就是说：格点内吸这次恰好补了 4 单位（`ceil(331/5)*5 - 331 = 4`），把估算的缺口盖住了。
这不是「约束被放松」（`_overflow` 的 1e-6 一个字没动），但它是**运气**：位移若恰好落在格点上，
`ceil` 不补任何东西，同一张图仍会被拒。096 按任务书只做吸附方向（任务书 §二 明文），
把这半条**作为遗留项**交回去（见交卷报告；建议后续批次单独修 `_annotation_allowance`，
那会移动所有声明了页面的模块级场景的坐标，属另一批的哈希申报范围）。
源码里这一条写在 `drawcompiler._anchor_to_page` 的 docstring 里，不让下一个人误以为锚点已经准了。

## 四、复现命令

```bash
cd /e/boardwise
# 1. HEAD 树（只读提取，不碰工作树/索引）
mkdir -p .tmp_096/hash && git archive HEAD | tar -x -C .tmp_096/hash/head
# 2. 两处缺陷的同一套实测（修复前 / 修复后）
.venv/Scripts/python.exe evidence/096/defect_probe.py .tmp_096/hash/head
.venv/Scripts/python.exe evidence/096/defect_probe.py .
# 3. 场景哈希逐文件对比（会拒跑已存在的 .tmp_096/hash）
bash evidence/096/scene_hash_check.sh
```

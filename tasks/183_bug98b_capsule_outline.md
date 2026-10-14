# 任务书：bug98b — 闭合描边段板框拼合 + 拼合失败护栏

- 批号：**183**　日期：2026-10-14　优先级：高（实板误报 98 条 ERROR，岳已复测打回）
- 前置：bug98（1134eb1）修了"开放段链合"，但实板是**另一种形态**：16 段**每段自成闭合环**（10mil 描边胶囊），全部落进 `closed_rings`，拼合不触发，`max(perimeter)` 取一段残弧当板框
- 实板证据：`E:/boardwise/.tmp_bug98b/实板A.epro2`（岳提供，**保密：只读使用，严禁复制进 tests/fixtures 或任何入 git 的位置**）；复测结论在 `C:/Users/xiangyu/Downloads/实板A_板框误报_证据/结论_bug98复测.md`

## 1. 实板形态（已侦察确认）

- 16 段 `BOARD_OUTLINE`，全部 `width=10`、全部首尾闭合（`_is_closed_ring` 判 True）
- 两种段型：**直边矩形描边**（9 点：外壁-端帽-内壁-端帽）+ **圆角弧描边**（11 点：端帽-外壁弧-端帽-内壁弧）
- 描边环结构：两条长边（≫width，实测 65~607mil）+ 短步簇（≤3.5mil）构成的两个端帽
- 相邻段的端帽质心差 ~1.5mil，可用现有容差（`OUTLINE_STITCH_TOLERANCE_MIL`）链合
- 真板框 = 16 段描边**中心线**首尾链接成的环；并集 bbox ±1294mil（约 65.7mm 见方）

## 2. 修法（`src/boardwise/parsers/epru.py`）

### 2.1 中心线提取（新函数 `_capsule_centerline(points, width) -> tuple[Point, Point] | None`）

对**闭合**描边环（算法已在 seg0/seg1 手工验算通过）：

1. 去闭合尾点，n 个不同点按环状相邻（含 wrap 边 n-1→0）
2. 步长数组；**长步判据**：步长 > `5 × width`（width 缺失/为 0 时用 `5 × 中位步长`兜底）
3. 删除长步 → 剩余点按环状连通成链（注意 wrap）
4. **链数必须恰好 == 2**，否则返回 None（放弃该段）
5. 两链质心 = 中心线两端点

参考验算（seg0，11 点含闭合）：步长 [3.5,2.6,607,402.7,2.9,3.5,0.77,401,604.6,1.2]，删 4 条长步 → 链 {0,1,2,9}/{4,5,6,7} → 端点 (-1148.3,-589.8)/(-1228.1,397.7)。

### 2.2 `_stitch_outline` 分流改造

```
闭合段 → 先试 _capsule_centerline：
  全部段提取成功 → 32 端点进端点链接（复用/仿 _longest_closed_chain 的容差链合）→ 成环？
    成环 → 用该环（outlineNote 记「16 段描边按中心线拼合」）
    不成环 / 任一段提取失败 → 回退旧行为（max perimeter 闭环），outlineNote 披露
开放段 → 维持现有链合逻辑（bug98 已修，不动）
混合 → 中心线端点与开放段端点一起链合（若实现复杂可拒：回退+披露，注释说明）
```

- 拼合环 sanity：环 bbox 与全部段并集 bbox 相差应在 ~width 量级（描边外壁 vs 中心线），差得离谱（>10×width）视为拼错 → 回退+披露
- `_is_simple_ring` 等既有校验继续生效

### 2.3 拼合失败护栏（off-board 规则）

复测建议 2（合理，采纳）：当板框多段、只认了一环、其余段被丢弃时，**出板框检查不得拿残弧照跑**：

- `pcb-component-off-board`（rules/pcb/distance.py 里 bug98 拆出的那条）加护栏：检测到「outline 走了回退路径且存在未入环段」→ 抑制逐器件 ERROR，改出**一条 WARN**：板框多段拼合失败/未拼合，出板框检查已抑制，附段数与处置建议
- 怎么传递「走了回退」：看 `BoardOutline` 现有字段（`segments`/`closed`/note），选最小改法（如加 `stitched: bool | None` 字段，或解析 note 前缀协议——优先加显式字段，别解析字符串）
- 正常单段板、拼合成功的板：行为完全不变

## 3. 测试（`tests/test_183_bug98b_capsule_outline.py`）

- **合成夹具（严禁用实板数据）**：照实板**形态**造——16 段闭合描边环（直边矩形描边 + 圆角弧描边混合，width=10，每段首尾闭合），坐标自己编（如 2000×1000mil L 形或圆角矩形板框拆 16 段），板内放 3-5 个器件
- 断言：
  1. 中心线拼合成一环，环 bbox ≈ 设计板框（±width/2 容差）
  2. `pcb-component-off-board` 对板内器件**零 finding**
  3. 故意放一颗器件在板外 → 正常报 1 条（证明没把规则搞哑）
  4. 拼合失败形态（如某段提取出 3 链的畸形胶囊）→ 回退 + WARN 抑制 + 无逐器件 ERROR
  5. 既有开放段夹具（test_bug98a）不回归——它的 20 条必须原样绿
- 单测 `_capsule_centerline`：直边矩形、弧段、width=0、畸形（3 链）→ None

## 4. 实板对拍（验收硬指标）

对 `E:/boardwise/.tmp_bug98b/实板A.epro2`：

```bash
.venv/Scripts/python.exe -m boardwise checkup --file .tmp_bug98b/实板A.epro2 --json .tmp_bug98b/after.json   # 命令行形式以实际 CLI 为准
```

- 基线：`C:/Users/xiangyu/Downloads/实板A_板框误报_证据/report_fixverify.json`（98 条 pcb-component-off-board ERROR）
- **修后预期**：`pcb-component-off-board` = **0 条**；outline 为 16 段拼合环；其余 finding 不因本批消失（主机 DRC 网表不一致那条真 ERROR 必须还在）
- 复跑 `_repro.py`（BOARDWISE_SRC=E:/boardwise/src）：[2'] outline bbox 应与并集一致

## 5. 验收与纪律

- 全量：`.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile --basetemp=.tmp_pt_183` 绿
- **指纹闸**：动 parsers/epru.py 与 rules/pcb/distance.py——epru 不在 recipe 内，distance.py 在 recipe 内 → 重钉 test_126a 的 recursive/direct digest + 台账注释（重算命令在 test_126a 底部注释）
- 不动 git；删除走回收站；`.tmp_*` 不入 git
- 证据：`outputs/183_bug98b/evidence.md`——算法验算、对拍前后 finding 计数、实板 _repro 输出、全量测试尾部
- PROGRESS.md append 一行（grep -c 验证）
- 版本号不动
- 完成后**不要 commit**，交回主代理收口

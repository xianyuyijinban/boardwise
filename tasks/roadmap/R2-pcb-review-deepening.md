# R2 → v0.5.13：PCB 审查加深（禁布区消费 · 镀铜孔 · 重构债 · 丝印闭环）

主题：把已解析但没人消费的数据变成规则，清两份重构债。估计工作量：2-3 天。

## 背景与证据指针

- PCB 规则在 `src/boardwise/rules/pcb/`（每条规则一个类，注册表
  `BUILTIN_PCB_RULES`），runner 在 `src/boardwise/engines/pcbreview.py`。
- 板级几何模型：`src/boardwise/core/`（`BoardGeometry`、`measure.py`）。
- **指纹纪律**：改 `rules/` 下任何文件 → 重钉规则体指纹：先跑
  `.venv/Scripts/python.exe -c "from pathlib import Path;from boardwise.engines.review_eval import rulebody_fingerprint as f;print(f(Path('src/boardwise/rules')))"`
  再按 `tests/test_126a_pcb_review_plumbing.py` 底部注释的台账格式更新两处钉值
  （recursive + direct）并写一行台账注释（谁改的、为什么、行为锚是哪个测试文件）。
- 审查规则写作范式看 `rules/pcb/silk.py` / `rules/pcb/distance.py`：每条 finding 带
  evidence、启发式边界必须写进 message（「这条规则看不到什么」）。

## 任务

### R2-1 REGION 禁布区规则消费（162b 的半成品闭环）

**现状**：解析层已把 REGION 禁布区读进模型（`board.prohibit_regions`，162b），
**只暴露不消费**——没有任何规则检查铜皮/走线/元件侵入禁布区。

**做什么**：新规则（建议 id `pcb-keepout-violation`）：铜皮图元/走线/焊盘侵入
禁布区多边形 → 按严重度报。先用 `core.measure.point_in_polygon`（177 已收编为公开件）
+ 线段-多边形相交做粗判；误报控制：禁布区类型（铺铜禁布 vs 布线禁布 vs 元件禁布）
要分清，**先只报类型明确的侵入**，类型不明时在 message 里写明不确定。

**验收锚**：注入夹具（在一块既有夹具的副本上画一个侵入禁布区的铜皮）必报 +
全既有夹具零新增 finding；规则进 `BUILTIN_PCB_RULES`（计数钉 +1，test_011d/test_064
的 23 → 24 类钉同步更新）；变异验证（删相交判定 → 测试红）。

### R2-2 `plated` 死字段恒 true

**现状**：孔/焊盘的 `plated` 字段恒为 true（记录在案的坑）——镀通孔与机械孔
（NPTH）分不开，所有依赖镀铜与否的判断（比如禁布区、孔径规则）都瘸。

**做什么**：回 `.epru` 解析层（`src/boardwise/parsers/`，001 的逆向笔记在
`outputs/001/` 一带）：PAD/VIA 记录里找出真正的镀铜标志字段（夹具里有 NPTH 的板子
能找到对照）；解析进模型；把恒 true 的占位改掉。找不到字段就如实记录「格式里
读不出」，并把依赖它的规则标注「plated 不可信」。

**验收锚**：有 NPTH 的夹具上 plated=false 解析正确；全夹具零判决翻转
（test_040b 冻结表不动）。

### R2-3 丝印实测真机闭环（依赖 R1-1，或岳手放一颗）

**现状**：172 的丝印字宽实测管线已接好（`pcb.geometry` 桥动作 174 走通），
但真机演示缺对象（test PCB1 空板）。

**做什么**：R1-1 落地后在 PCB1 放一颗带丝印封装（或请岳手放）→ 在线 checkup
跑出「丝印读数（实测）」→ 读数与宿主一致 → 清理复原。证据落 `outputs/R2/live/`。

**验收锚**：真机读数截图/json + 与离线估算的差异对照（估算 vs 实测各多少条）。

### R2-4 重构债两笔（177 遗留）

1. `rules/pcb/distance.py::_point_in_outline` 是第 4 份同算法副本（177 审计发现，
   未收编）——收编到 `core.measure.point_in_polygon`（先逐行 diff，一致才收）。
2. `_point_segment_distance` 双版本（core 的退化守卫 `dx==0 and dy==0` vs
   focthermal 的 `length_sq<=1e-18`，实测 313/5000 bitwise 有差）——统一成一个
   公开件；选哪个守卫要有数据（对拍两版在退化边集合上的差异面），
   **判决零翻转是硬约束**（全夹具 severity 冻结表不动）。

**验收锚**：全量绿 + 指纹重钉 + 变异验证；两笔各自独立的证据节。

## 交卷

各任务结论 + 证据；pytest 全量绿（基线 5415+23 并行）；指纹重钉记录；
变异验证记录；遗留清单。

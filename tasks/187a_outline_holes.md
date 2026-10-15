# 任务书：187A — 发布闸必拦（183 系三洞）

- 批号：**187A**　日期：2026-10-16　来源：挖洞 swarm agent-341 报告（outputs 可引用，探针在 `C:\Users\xiangyu\.tmp_hole183\`）
- 范围：只修 H1/M1/M2（顺带 L1 注释、M3 焊缝披露），其余低项不做

## 1. H1 形状不变量收口（`src/boardwise/parsers/epru.py`）

- 在 `_stitch_outline` 两条路径（capsule 与开放链）的**合流点**加环形状不变量：shoelace `|A| > 0`、bbox 两轴均 > 0、无零长边/重复顶点
- 不满足：`outline=None` + `fragments=len(segments)`（走「板框没读出」披露路径），**不许** `stitched=True`
- 复现锚：3 段描边「出去再原路折回」→ 中心线 `[(0,0),(2000,0),(1000,0)]` 面积 0（agent-341 probe3）；开放折线拼出同一共线环同病（probe11）——两条路径都要测

## 2. M1 fragments 实算（`epru.py` capsule 分支）

- `if len(points) >= 3` 的静默丢弃补 else 计入 fragments；capsule 分支 `fragments` 从硬编码 0 改为 `len(segments) - 实际入环段数`；`_capsule_note` 的计数用实际入环段数
- 不变量测试：`used_records + fragments == segments`（随机段集合）
- 顺带 `geometry.py` 的 `stitched` 注释（L1）：改成实义（"胜出的环是拼合产物"），或按 swarm 建议拆分语义——选最小改法

## 3. M2 护栏判据收紧（`src/boardwise/rules/pcb/distance.py`）

- 现状：`stitched is False` 一刀切抑制。改为：只有「每条在场记录都读成描边（`_capsule_centerline` 全成功）却拼不出整环」才是「碎片」证据才抑制；「完整板框 + 多余闭合记录（内槽/拼板）」**不抑制**——保留 bug98-A 的照跑（max perimeter 环）+ 碎段披露
- WARN 文案分两档：「拼合失败」vs「多余记录未入环，按所选闭环照跑」
- 需要解析器传证据：BoardOutline 加字段（如 `fragment_kind: str | None` 或把「全部记录可读成描边」布尔带过来），别解析 note 字符串
- 复现锚：外框矩形环 + 内槽小环 + 真出板器件（x 越界 220mil）——修后 ERROR 必须出得来（agent-341 probe11）
- L2 死分支（`fragments <= 0` 早退不可达）顺带清理或补不变量断言

## 4. M3 capsule 焊缝披露（`epru.py` + `engines/pcbreview.py`）

- `_capsule_frame` 回传超限接缝数（gap > 0.05 mil 才计，实板 0.001-0.011 mil 的描边天然缝隙不计），capsule 分支填 `tolerance_welds`，报告那行照旧印

## 5. 测试与纪律

- 新测试并入 `tests/test_187a_outline_holes.py`：H1 两路径退化环、M1 不变量、M2 两形态（内槽不抑制/真碎片抑制）、M3 焊缝计数、183 原有测试不回归（test_183/bug98a 全绿）
- 实板回归：`.tmp_bug98b/` 下的实板归档（只读）跑 checkup --file：off-board 仍 0 条、outlineNote 仍是 16 段全入环
- 指纹：`rules/pcb/distance.py` 在 recipe → 重钉 test_126a recursive/direct + 台账
- 红线：不动 git；pytest `--basetemp=.tmp_pt_187a`、`-n 4 --dist loadfile`；删除走回收站；真实项目名零出现（R4b）
- 全量绿；证据 `outputs/187a_outline_holes/evidence.md`；PROGRESS.md append 一行
- **不要 commit**，交回主代理收口

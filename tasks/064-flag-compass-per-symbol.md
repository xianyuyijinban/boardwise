# 064：旗标罗盘按符号分家（GND 下垂 / PWR-* 朝上）——060 的 rail 半边

来源：060 收口时 agent-85 的实测遗留（**重要**）：库内 SYMBOL 文档显示
`Ground-GND` BBOX `(-10,0,10,-19)`（连接点在上、bars 向下垂），
`Power-VCC`/`Power-5V` BBOX `(-5,10,5,0)`（bar 在连接点**上方**）。
060 的"整体 +180"对 GND 正确（E1 真机 4/4 正挂已验证），但对 PWR-* 类电源旗标**翻反了**——
场景哈希申报清单里 VIN 0→180 / 90→270 那一批就是。本批把它修掉，是 060 的 rail 半边。

**这是新派单纪律（串行小批）的第一批**：一个缺口、一个文件域、目标半小时内交卷。

## 已查证的事实（060 交卷带出，子代理不必重查）

- 060 后 `engines/drawcompiler.py::_flag_rotation` 是无差别 +180 罗盘；字形盒约定在
  `core/symbolprofile.py::flag_glyph_box`（drawcompiler / pagecompiler / svgpreview 三处共用）。
- 场景申报清单 `outputs/060_layout/scenario_hashes.txt`：VIN 旗标已随 060 翻转
  （053b scene01–07），GND 翻转正确。
- 我们的库 profile 里旗标本体是**理想化约定盒** `(-6,0,6,18)`（`outputs/057_live/lib.json`），
  离线预览永远看不到符号间姿态差——所以本批必须有真机 probe，不能只看离线。

## 架构裁决（不再变动）

1. `_flag_rotation` 收 **kind 参数**（或由调用处按符号种类分派）：
   - `gnd` 类（Ground-* 符号，bars 背离连接点向下垂）→ 用 060 的裁决映射（+180）；
   - `rail` 类（Power-* 符号，bar 在连接点上方）→ **退回 060 之前的映射**（背离引脚）。
   分类依据放 `symbolprofile`（比如按符号名/库内字形 BBOX 判），单一规则点，编译器与预览共用。
2. **真机 probe 定案**（不能省）：test 工程新页放 `PWR-3V3`（或 PWR-VIN）rotation 0/90/180/270
   各一颗 + GND 对照，`export.render format=svg` 解 netflag 组核对字形朝向（坑 42 同源手法），
   留证 `outputs/064_railflag/`。真机只碰 test，写前 bridge status + doc.list 对焦，
   对焦失败停下报告（R3）。probe 页用完 `draw discard` 清场并保存。
3. 场景哈希**再次申报**：本批应把 053b scene01–07 里 VIN 的 rotation **翻回**（0→180 回到 0 等），
   GND 不再动。逐场景列清单，只允许 rail 类旗标 rotation 变；发现 GND 或任何非旗标字段变
   = 停下来报告。
4. SKILL.md 坑表补一条（措辞照坑表体例）："旗标自然姿态**按符号分家**：GND 下垂 / Power-* 朝上
   （库内 SYMBOL BBOX 实测）；罗盘必须按符号分，预览画理想化盒看不出来"；§3.3 执行序 apply 后
   加一步"`export.render format=svg` 解 netflag 组核对旗标朝向"（与坑 42 同源）。

## 验收

1. 新测试（basetemp `.tmp_pt_87`）：gnd/rail 两类罗盘映射各方向钉死；分派规则测试
   （给定符号名/字形 → 种类）。场景哈希申报清单落 `outputs/064_railflag/scenario_hashes.txt`。
2. 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 全绿（基线 2408）。
3. 变异 ≥1 组（cp+sha256 还原）：rail 类误用 gnd 映射 → 对应测试红。
4. 真机 probe 证据：SVG 解出的字形朝向四姿态逐颗列表（PWR-* 与 GND 对照）。
5. eval 不受影响（不动规则面），可不重跑；动了 readability 才跑。
6. PROGRESS.md 不动（主代理收口写）。

## 边界与纪律

- 只碰：`drawcompiler.py`（_flag_rotation 及调用处）、`symbolprofile.py`、必要时
  `pagecompiler.py`/`svgpreview.py` 的同类调用、相关测试、`tasks/064*`、SKILL.md（坑表+§3.3）。
- pytest 必带 `--basetemp`；零 git 写操作；真机只碰 test；注释密度跟周边一致。

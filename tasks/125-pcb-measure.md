# 125 / PCB 审查阶段 B：几何测量库（纯离线，全单测）

> 路线图：`tasks/122-pcb-review-roadmap.md` 阶段 B 行。
> 定位：**C/D 阶段的地基**。只产数字和坐标（间距/面积/线宽/环路/层叠），
> 「合理与否」归规则阈值或模型判断——**工具出数、模型裁定**，库里不许出现阈值和结论。
> 单位纪律同 `core/geometry.py`：内部一律 mil，mm 只在报告边缘用 `mil_to_mm` 显式换。

## 底子（已盘点，不是假设）

- 几何模型：`src/boardwise/core/geometry.py` —— `BoardGeometry`（pads/tracks/vias/pours
  按 net 索引）、`PadGeometry`（width/height/shape/angle/hole_diameter）、`TrackSegment`、
  `ViaGeometry`（含 `unused_inner_layers`）、`PourShape`（kind=fill/poly/poured，shoelace area 已有）、
  `LayerInfo`（`is_copper`）、`ComponentPlacement`（`transform()` 局部→板坐标，CCW，y 向上）。
- 解析入口：`boardwise.parsers.epru.parse_epro2(path)`（fixture 直接可用，无需真机）。
- 夹具（**只读，禁改**）：
  - `tests/fixtures/llc_board.epro2` —— 001 反推板，双层。人工抽测锚点：
    板框 6102.36×3149.61 mil（=155×80 mm）；via 39.37/19.685 mil（=1.0/0.5 mm）；
    **C7 两焊盘中心距 295.28 mil（封装 P7.50，=7.50 mm）**；PCB 段 25 条 FILL。
  - `tests/fixtures/ProPrj_毕设FOC驱动板_2026-09-17.epro2` —— **四层板**（岳 2026-10-07 亲裁），
    层叠读出的第二个数据点（copper_layers 必须读出 4 层）。
- 既有测试范式：`tests/test_epru_parser.py`（module-scope fixture + 手工建记录 `_record()`）。

## 架构钉死（不许漂移）

1. **新模块 `src/boardwise/core/measure.py`**：纯函数，只依赖 `core/geometry.py` 的模型，
   不 import parsers/engines/rules（core 不依赖任何上层，同 transform_point 的落位逻辑）。
2. **无阈值、无结论**：函数只返回测量值与证据（哪两个元素最近、在哪层），
   不出现「违规/通过/合理」字样。命名用 measure/read/compute，不用 check/validate。
3. **mil 进 mil 出**：任何 mm 换算只能出现在调用方；库里禁止隐式换算
   （`test_coordinate_guards` 会拦引擎换算，本库自觉遵守同一红线）。
4. **空输入不炸**：未知网名/位号返回空结果或 None，不抛（`BoardGeometry.net()` 同纪律）。
5. **性能**：只提供「按需逐对」API，不提供全网矩阵；元素对先过 bbox 粗筛再精算。

## 棒1（125a）：基础原语四项

### API（签名可微调，语义不许变）

```python
@dataclass StackupInfo:
    copper_layers: list[LayerInfo]      # 按 layer_id 排序
    copper_count: int
    used_copper_layer_ids: list[int]    # 实际有铜元素的铜层（排序去重）
def read_stackup(board: BoardGeometry) -> StackupInfo

@dataclass LayerWidthStats:  # 单层内
    track_count: int
    min_width: float
    total_length: float
@dataclass WidthStats:
    net: str
    track_count: int
    min_width: float          # 0.0 if 无走线
    max_width: float
    total_length: float
    per_layer: dict[int, LayerWidthStats]
def track_width_stats(board, net: str) -> WidthStats
def track_width_table(board) -> dict[str, WidthStats]   # 只含≥1条走线的网

@dataclass ComponentDistance:
    component_a: str
    component_b: str
    center_distance: float    # 两元件锚点（ComponentPlacement.position）距
    edge_distance: float      # 最近焊盘对的边到边距（旋转矩形精算）
    pad_a: str                # 最近焊盘的 pin_number（或 id 兜底）
    pad_b: str
def component_distance(board, des_a: str, des_b: str) -> ComponentDistance | None
def pad_edge_distance(pad_a: PadGeometry, pad_b: PadGeometry) -> float

@dataclass LoopArea:
    anchor_points: list[Point]   # 解析后的有序锚点
    polygon_area: float          # 鞋带公式，有序锚点围成面积
    bbox_area: float             # 锚点 bbox 面积（上界，粗筛用）
def loop_area(board, anchors: Sequence[str | Point]) -> LoopArea
    # str 锚点格式："C7"（=该件全部焊盘质心）或 "C7.1"（指定焊盘中心）；未知锚点抛 ValueError
```

### 焊盘形状处理（棒1就要，棒2 复用）

- 焊盘按**旋转矩形**精算：`width/height` + `angle` + 组件 transform 后的板坐标中心
  → 4 角点 → 4 边线段集；边到边距 = 线段集两两最小距（相交=0）。
- `shape` 为 OVAL/圆形时仍按外接矩形算，docstring 写明「保守低估间距」（矩形包含椭圆）。
- 提炼一个内部 helper（如 `_pad_corners(pad) -> list[Point]`），棒2 直接复用——
  **棒1 任务书里注明这是给棒2 的接口**。

### 测试（`tests/test_125_pcb_measure.py`）

- 合成板手工算：手建 `BoardGeometry`（`__post_init__` 支持手工构造），每个原语至少
  两组手算值对拍（含旋转 90°/45° 焊盘、跨层元素、空网、未知位号）。
- 夹具锚点（只读）：
  - llc_board：`read_stackup().copper_count == 2`；C7 两焊盘中心距 295.28±0.05
    （中心距用 pad.center 直接算，`pad_edge_distance` 对拍 295.28 − 两盘沿轴向半宽之和，
    推导写注释）；板框 bbox 6102.36×3149.61 ±0.1。
  - 毕设FOC：`read_stackup().copper_count == 4`（岳亲裁四层；若读不出 4 层铜，
    **停下来查 LAYER 记录，不许硬编码放过**——把实际读到的层表打印进失败信息）。
- 空输入：未知网 WidthStats 全 0；未知位号 component_distance → None；锚点未知 → ValueError。

## 棒2（125b）：间距引擎 + 铺铜连通性（依赖棒1 的 `_pad_corners`）

> **棒1 已落账**（`core/measure.py` + `tests/test_125_pcb_measure.py`，全量 3783 绿）。
> 开工前必读棒1 实现与测试，两个已核实的现场事实：
>
> 1. **毕设FOC 夹具有三个 PCB 文档**：PCB1 = 四层主板（uuid 前缀 `ab812fb7`，105 件，
>    铜层 1/2/15/16）；`parse_epro2` 默认拿的是首文档 PCB3（双层）。测试选板写法照抄
>    `test_125_pcb_measure.py` 里 FOC 测试的 idiom，不许用「元件数最多」这类魔法选择。
> 2. **POURED 记录缺口**：解析器在 `epru.py:594` 附近**故意丢空 POURED 的 path**
>    （毕设FOC 55 条 POURED 因此无多边形）。棒2 处置顺序：
>    a) 先读该处注释/相关 docstring，查清丢空原因写进回报；
>    b) 连通性原语基于 `kind ∈ {fill, poly}` 的 pour + tracks/vias/pads 实现；
>    c) 若调查表明 POURED path 解析简单可行（格式同 FILL），可做**可选增强**（默认关）
>       并补测试+证据；不简单就如实申报不硬做。
>    d) 夹具锚点相应调整：llc 用 FILL 铺铜（PCB 段 25 条，真实 pour）做连通性锚点；
>       毕设FOC 改做「via 链跨层连通」锚点（顶层→内层链通），不做内层铺铜多边形锚点。

```python
@dataclass ClearanceResult:
    net_a: str
    net_b: str
    distance: float           # 全网对全网最小边到边距（跨层按 XY 平面几何距）
    element_a: str            # 最近元素描述（类型+id+层）
    element_b: str
    overlapping: bool         # 形状相交/包含（不同网=短路现场，距离记 0）
def net_clearance(board, net_a: str, net_b: str) -> ClearanceResult | None
def clearances_vs(board, net: str) -> dict[str, float]   # 该网对每个其他网的最小距

@dataclass PourIsland:
    island_id: int
    element_ids: list[str]
    area: float               # 岛内 pour 面积和
    layer_ids: list[int]
@dataclass PourConnectivity:
    net: str
    island_count: int
    islands: list[PourIsland]
def pour_connectivity(board, net: str) -> PourConnectivity
```

- 元素形状统一成「线段集 + 圆」两类原语：track=线段（带宽度→按胶囊体，距离减 width/2），
  via/pad 孔=圆，pad=旋转矩形（棒1 helper），pour=多边形（边线段集 + 包含判定）。
- **跨层语义**：不同层元素按 XY 平面投影距（爬电/间隙的保守下界），结果里带层号，
  判定留给上层。同层才算 overlapping。
- 连通性：并查集。同层形状相触/相交 → 连通；**via 纵向连接除
  `unused_inner_layers` 外的全部铜层**（语义写 docstring，夹具上对拍至少一例）；
  通孔焊盘（有 hole_diameter）纵向贯通全部铜层，SMD 焊盘只在本层。
- 性能：bbox 粗筛 + 按需逐对；`clearances_vs` 对 GND 级别的网（llc 上最大网）也要秒级内。
- 测试：合成板（平行线间距手算、十字交叉重叠、跨层 via 链通两岛、SMD 不跨层、
  三岛 GND 铺铜）+ llc 锚点（挑两个已知网对，先打印实际值再人工核算钉死，
  推导写注释）+ 毕设FOC 内层铺铜连通性一例。

## 交付纪律（两棒通用）

- pytest 必带 `--basetemp=.tmp_pt_home`；先跑焦点测试，再跑全量
  `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home`（~10-22 分钟为常态）。
  纯 Python 新模块，connector/dsh/tsc 三线不受影响可免跑，**如实申报**。
- 禁 git 任何写操作；禁改 `tests/fixtures/` 既有夹具；删除进回收站（PowerShell 单引号通道）。
- 真机零接触（本阶段纯离线，daemon 都不用启）。
- 完成后回报：新增文件清单、测试数、夹具锚点实测值（C7 间距/层数/连通岛数）、
  全量测试总数与耗时、未能验证的事项。
- PROGRESS.md / 路线图勾选 / 提交推送由主代理收口，子代理不碰。

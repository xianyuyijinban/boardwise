# 任务书：高速规则架子（highspeed scaffold）

- 批号：**182**　日期：2026-10-13　状态：待执行
- 依据：`outputs/highspeed_rules_survey/README.md`（调研台账）、摸底报告（agent-332）
- 范围纪律：**只搭架子，审查规则本体一律不做**（留 0.6.0）。禁做清单见 §6。

## 1. 数据层补漏

### 1.1 StackupEntry 补两字段（`src/boardwise/core/geometry.py:262`）

```python
permittivity: float | None = None    # Er，epro LAYER_PHYS.permittivity / kicad setup stackup
loss_tangent: float | None = None    # Df，同上 lossTangent
```

- `None` = 文件未声明；**不要**把 0 当未声明（epro 里确实有 `permittivity:0` 的脏数据——0 视为未声明，落 None）
- 字段加在 dataclass 尾部（带默认值，不破坏既有构造点）
- 检查 StackupEntry 是否参与任何 eq/hash/指纹：若 `BoardGeometry` 或其指纹依赖 stackup 内容，确认 perf-02A 的 `_stackup_cache` memo 指纹（`measure.py:289-330`）不受影响（它按身份+长度，应该没事，但要验证）

### 1.2 epro 解析器多读（`src/boardwise/parsers/epru.py`）

- `LAYER_PHYS` 消费点（约 :1747）：补读 `permittivity`、`lossTangent` 两键 → StackupEntry
- **NET 记录消费**（重点）：`collect_pcb_context`（约 :1726）增加 `rtype == "NET"` 分支，读：
  - `differentialName`（str|null）、`isPositiveNet`（bool|null）、`equalLengthGroupName`（str|null）、`netType`（str|null）
  - 落进 §1.3 的 `NetMeta`，挂到 `BoardGeometry.net_meta`
  - `"NET"` 加进 `CONSUMED_RECORD_TYPES`（:129）——**注意这会改 `stats.unconsumed_types`，有测试钉着，找到并重钉**

### 1.3 NetMeta（`src/boardwise/core/geometry.py` 新 dataclass）

```python
@dataclass
class NetMeta:
    name: str
    diff_pair: str | None = None          # 编辑器声明的差分对组名（epro differentialName）
    diff_positive: bool | None = None     # 声明的极性
    equal_length_group: str | None = None # 等长组名
    net_class: str | None = None          # kicad netclass 归属（epro 侧暂无）
    declared_diff_width: float | None = None   # kicad netclass 声明值，mil
    declared_diff_gap: float | None = None
```

- `BoardGeometry` 加 `net_meta: dict[str, NetMeta] = field(default_factory=dict)`（尾部带默认值）
- 注意 BoardGeometry 若是 dataclass 且有 eq/指纹消费点，跑全量验证

### 1.4 kicad 解析器（`src/boardwise/parsers/kicad.py`）

- `load_kicad`（:1049）现在只 `json.loads` 校验 `.kicad_pro`：改为真读 `net_settings`——
  - `classes[]`：取 `name`、`diff_pair_width`、`diff_pair_gap`（mm → 转 mil，核对 kicad 文件单位）
  - `netclass_assignments`（网名→类名，可为 null）+ `netclass_patterns[]`（`{netclass, pattern}` 通配）
  - 归属解析：assignment 优先，patterns 用 `fnmatch` 兜底；落到 `NetMeta.net_class` / `declared_diff_width` / `declared_diff_gap`
  - **宽容优先**：任何键缺失/类型不对都不炸，落 None；仓里没真样本，按上面结构写 + 合成 fixture 验证
- **kicad stackup**：`read_kicad_board`（:864）补读 `(setup (stackup ...))` 段——每层 `(layer "..." (type ...) (permittivity x) (loss_tangent y))` 宽松读，落 `StackupEntry`（kicad 的 stackup 层名到 layer_id 的映射照 `_bw_layer` :710 的口径；介质层没有 layer_id 概念，用 z_index 序+负数 id 或单独标记，**设计取舍写进 docstring**）
- kicad 的 NET 级差分对声明：kicad_pcb 里没有 per-net 差分字段（netclass 级），所以 `NetMeta.diff_pair` 在 kicad 侧恒 None，靠 §2 启发式

## 2. 差分对识别引擎（`src/boardwise/core/highspeed.py`，新模块）

```python
@dataclass(frozen=True)
class DiffPair:
    group: str            # 声明组名或启发式合成的基名
    positive: str         # 网名
    negative: str
    source: str           # "declared" | "heuristic"

def identify_diff_pairs(board: BoardGeometry) -> list[DiffPair]: ...
```

- **声明优先**：`net_meta` 里 `diff_pair` 非空的按组名配对（组内恰 2 网、一正一负；声明残缺——组内 1 网或 3+ 网——按声明尽力配并在返回值里标注？不行，保持简单：残缺声明**不进结果**，由 0.6.0 规则去报「声明残缺」）
- **启发式 fallback**：照抄 KiCad `MatchDpSuffix` 算法（[drc_engine.cpp L2526](https://gitlab.com/kicad/code/kicad/-/raw/master/pcbnew/drc/drc_engine.cpp)）：从网名尾部跳过数字和 `_`，遇到的第一个 `+`/`-`/`P`/`N` 定极性，互补网替换互补字符（`+`↔`-`、`P`↔`N`）后**必须在网表中真实存在**才成对；已被声明消费的网不再参与启发式
- 纯函数、无副作用、O(n)；docstring 写明算法出处
- **不做**高速网分类（USB/DDR 名字启发式）——0.6.0 的事

## 3. 规则侧架子

### 3.1 新模块 `src/boardwise/rules/pcb/highspeed.py`

- 一条 INFO 清单规则验证端到端：

```python
class DiffPairInventory(PcbRule):
    id = "pcb-hs-diffpair-inventory"
    level = "L1-pcb-geometry"
    source = "boardwise highspeed scaffold（182）"
```

- 行为：调 `identify_diff_pairs(ctx.board)`；每个声明/启发式差分对出一条 INFO（消息含组名、两网名、来源；`target.net_refs` 带上两网）；一条都没有 → 零 finding（INFO 也不出，避免噪声）
- 级别口径遵守仓库惯例：测量/清单类一律 INFO

### 3.2 注册（两道闸）

- `src/boardwise/engines/pcbreview.py`：import 段（:42-77）+ `BUILTIN_PCB_RULES`（:159）尾部追加（声明序=执行序）
- `tests/test_126a_pcb_review_plumbing.py:153` 的逐字序列表重钉
- `rulebody_fingerprint` digest 重钉（test_126a :775+，重算命令在该文件底部注释里；recursive/direct 两值都重钉，台账注释更新）

## 4. 测试（`tests/test_182_highspeed_scaffold.py`）

- **epru NET 读取**：用既有夹具 `ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2`（只读！）——断言 `net_meta["D+"].diff_pair == "DP1"`、`is_positive is True`、`CAN_H/CAN_L` 成 DP2、`net_meta` 覆盖非空
- **StackupEntry 两字段**：同一夹具（或 llc_board）断言至少一条介质 entry `permittivity` 非 None 且 >1；`permittivity:0` 落 None
- **MatchDpSuffix 单测**：纯函数表驱动——`D+/D-`、`USB_P/USB_N`、`DDR_DQ3P/DDR_DQ3N`、尾数字（`A1_P/A1_N`）、不存在互补网（`FOO_P` 单独）不成对、普通网（`GND`）不成对、`P`/`N` 结尾但中间带数字/下划线
- **声明优先**：合成 BoardGeometry——声明组 + 同名可启发式的网，断言 source=="declared"；残缺声明（组内单网）不进结果
- **kicad_pro 合成 fixture**：`tests/fixtures/` 下新增最小 kicad 三件套（kicad_min 目录已有个桩 .kicad_pro，**别动它**，新造 `kicad_hs/`），含 net_settings.classes + assignments + patterns；断言 net_class/declared_diff_width/gap 落 NetMeta
- **kicad stackup**：合成 .kicad_pcb 带 `(setup (stackup ...))`，断言 StackupEntry 读出 permittivity
- **端到端**：毕设FOC夹具跑 `run_pcb_review`，筛 `pcb-hs-diffpair-inventory`，断言 DP1/DP2 各出一条 INFO 且 source=declared
- 空 BoardGeometry 对照：零 finding 不炸

## 5. 文档

- `docs/epru-format.md`：NET 从「present but not consumed」挪到已消费段（写明消费的 4 个键）；`LAYER_PHYS` 条目补 `permittivity/lossTangent`（顺手修正 stale——它实际早已被消费但文档没写）
- `PROGRESS.md` 单行落账（append 后 `grep -c` 验证）

## 6. 禁做清单（0.6.0 的事，碰了打回）

- 任何 WARN/ERROR 级高速审查规则（等长/跨分割/地孔/3W/阻抗…一个都不做）
- 高速网名字分类（USB/DDR/PCIe 启发式）
- JLC 叠层库 json、scikit-rf、阻抗计算
- `.kicad_dru` 解析
- 原理图侧 `DesignModel.raw` 差分对汇流
- 版本号不动（保持 0.5.12），不发版

## 7. 验收

- 全量：`.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile --basetemp=.tmp_pt_182` 绿（含重钉后的 126a）
- 新测试文件独立跑绿
- 证据：`outputs/182_highspeed_scaffold/evidence.md`（改动清单、重钉值、测试输出尾部、夹具断言值）
- 完成后**不要 commit**——交回我收口

# 任务 001：.epru 几何解析器

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 测试环境：项目自带 `.venv`，用 `./.venv/Scripts/python -m pytest` 运行。
> 完成标准：新增交付物全部就位 + 全量测试（现有 31 个 + 新增）全绿。

## 背景

boardwise 是面向 EasyEDA Pro 的 AI 画板 harness（审查 / 生成 / 仿真三阶段），当前在做第一阶段"离线审查器"。已有：`.enet` 网表解析器（`parsers/enet.py`）、核心连通性模型（`core/model.py`）、3 条 L1 规则、CLI。本任务补上**几何数据源**：解析 EasyEDA Pro 工程备份，把铜皮几何喂给模型。先读 `README.md`、`src/boardwise/core/model.py`、`docs/api-survey.md` 了解现状。

## 已探明的格式事实（直接信任，不要重新侦察）

- `.epro2` 是 ZIP，内含 `project2.json`（工程元数据）和若干 `*.epru` 条目。**zip 内中文文件名是乱码，必须按扩展名 `.epru` 匹配条目，不要按文件名。**
- `.epru` 是行式记录格式：每行 `{envelope-json}||{body-json}`，行以 `|\n` 结尾。envelope 有 `type`/`ticket`/`id` 字段；body 是该记录的数据载荷。
- 测试夹具已就位：`tests/fixtures/llc_board.epro2`（LLC 全桥板，11,799 条记录）。记录类型普查：PAD 281, PAD_NET 390, VIA 257, LINE 680, POLY 1022, FILL 444, NET 89, COMPONENT 98, PIN 265, WIRE 32, TEXT 63, RULE 242, LAYER 2628, LAYER_PHYS 135, DOCHEAD 252, ATTR 2420, META 250, CANVAS 163 等。
- **格式无官方文档，语义需要你在夹具上反推**：每类记录的字段、坐标单位、网络关联方式（PAD_NET 大概是焊盘↔网络连接表）、LINE/POLY/FILL 各自角色。用脚本采样每类记录的实际内容来推断。

## 交付物

1. **`src/boardwise/core/geometry.py`**（新模块；不要改动 `core/model.py` 的既有接口）：
   - `PadGeometry`、`TrackSegment`、`ViaGeometry`、`PourShape`、`BoardOutline` 等 dataclass，含坐标 / 层 / 网络关联
   - `BoardGeometry` 容器：**按网络索引铜皮元素**——"net X 上有哪些 pad / track / via / pour"是后续审查规则的核心查询，做成一等 API
2. **`src/boardwise/parsers/epru.py`**：`.epro2` → `BoardGeometry`，返回解析统计（每类记录数量、跳过的未知类型计数、editVersion）。未知记录类型跳过并计数，永不致命。
3. **`tests/test_epru_parser.py`**：基于夹具——记录总数核对、PAD/VIA/LINE 数量与普查一致、抽查若干网络的成员构成、坐标范围 sanity check、坏行容错。
4. **`docs/epru-format.md`**（英文）：逆向工程笔记——每类记录的 schema + 真实样例 JSON + 语义推断，**标注哪些是确认、哪些是猜测**。
5. `parsers/__init__.py` 可导出入口；CLI 本任务不接。

## 约束

- 包代码只用标准库（zipfile / json / re 足够）。代码、注释、docstring 用英文。
- 不执行任何 git 命令。
- 夹具 3MB、1.2 万条记录：解析一次流式过完，别反复全量扫描；测试运行保持秒级。

## 验收时我要看的

- 格式反推关键结论：坐标单位、PAD_NET 关联方式、LINE / POLY / FILL 各自语义
- `BoardGeometry` 的网络查询 API 长什么样
- 全量测试输出
- 所有与"已探明事实"不符的发现

---

## 验收记录（2026-09-12，Kimi）

状态：**ACCEPTED**。独立复验：72 passed；`parse_epro2` 冒烟通过（DC- = 13 pads / 177 vias / 4 pours）；ParseStats 含 unconsumed_types 追踪。备注：报告示例中 `nets_sorted_by_copper()` 的解包写法与实际返回类型（NetGeometry 列表）不符，文档层面小问题，代码行为正确。

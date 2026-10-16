# 任务书：189C — 离线几何渲染进 `--out`

- 批号：**189C**　日期：2026-10-16　来源：岳的实板反馈 ⑥——离线档位（`checkup --file`）`canvas_images` 为空，布局审美 skipped；「R22 丝印压没压 EC3 焊盘」这类分歧只要有张图三分钟就能对齐，而不是来回猜
- 口径警示（反馈原文）：规则算的是**文字包围盒与焊盘相交**，没建模阻焊开窗裁切——「算出来压了」和「实物没压」可以同时成立。渲染图不替规则下结论，是给**人**对照用的。报告里要把这句口径写明白

## A. 渲染什么（最小可用，别做成 EDA 查看器）

对 `checkup --file X.epro2 --out D`：每块板输出 `canvas-<board>.svg`（SVG 即可，文本格式、版本可控、AI 也能读；**不引入位图依赖**）：

- 板框（outline）、器件外框+位号、焊盘、过孔、铺铜轮廓（半透明填充）、丝印文字
- 每网一色 or 按层一色（选实现成本低的，配色固定可复现）；图例注明
- **finding 叠加**：有 PCB finding 的对象（器件/焊盘/走线）描边高亮 + 角落列 finding id——这是「三分钟对齐」的关键
- 俯视图单面双面分窗（顶层/底层各一视窗，镜像底层）

## B. 复用什么（先摸现有渲染能力）

- draw 体系有 SVG 预览（`engines/drawcompiler.py` 或 preview 相关——lint/preview 出过 SVG）；`engines/render` 或类似模块可能已有几何→SVG 的部分。先盘点再决定写多少新代码
- PCB 几何数据全在 `BoardGeometry`（pads/tracks/vias/pours/outline/silk_texts/silk_shapes）——坐标系注意 y 轴向上为正（001 批实测）

## C. 接线

- `checkup --file` 默认产出（离线无图是痛点）；在线档位不动（已有 export.render 通道）
- `report.json` 的 `canvas_images` 节：离线填 `{"board": "canvas-<board>.svg", "source": "geometry-render", "note": "几何渲染（非实物照片）；丝印压焊盘类判定未建模阻焊开窗裁切，分歧以实物为准"}`（schema 只加）
- 渲染失败（异常/空板）降级为节内错误行，不阻塞报告

## D. 测试与纪律

- `tests/test_189c_canvas_render.py`：合成小板（板框+两器件+焊盘+丝印）渲染出 SVG 断言关键元素在场（位号文字、焊盘圆、outline 路径）；finding 叠加的对象有高亮标记；空板不炸；report.json canvas_images 节键在场
- 实板只读验证（`.tmp_bug98b/` 下归档）：渲染出 SVG，**主代理会亲眼看**（确认器件/丝印/板框位置对得上——渲染图的 y 轴翻转是此类功能的第一大坑）
- 全量绿 `--basetemp=.tmp_pt_189c` `-n 4 --dist loadfile`（sources 在位）
- 红线：不动 git；删除走回收站；真实项目名零出现；不引入新依赖（SVG 手写，不用 cairosvg/svglib）
- 证据 `outputs/189c/evidence.md`；PROGRESS.md append 一行；**不要 commit**

# 任务书：201D — 落位搜索计价「别人的文本行」（反激 readability 账）

- 批号：**201D**　日期：2026-10-17　前置：201C 落账（router 协商 + escape_nodes）
- 来源：201C 把反激的死因推到 readability 闸 16 条硬违反：9 条文本行压导线、4 条文本行压器件、2 条导线落在器件绘制范围、1 条 text-on-wire。逐条定性：**落位/排版层的账**——201B 的 topology 搜索代价里没有「别家器件的文本行（位号行/参数行）」这一项，器件摆进去之后文本行才长出来，与导线/邻件撞车。

## 要做什么

1. **落位搜索知道文本行**：placement 的代价函数加一项「文本行净空」——每个器件的占位盒要从「体框」扩到「体框 + 它的标注行（位号 + 值/参数行）的预计落墨范围」。标注行的尺寸按现有估算口径（textmetrics / 位号字数 × 字宽估算，读现役代码里的同一套，别新造一把尺）；方向按该件的位姿推（标注习惯在哪侧，读 drawcompiler 现役的标注落点逻辑）。
2. 代价计入两个方向：本件的文本行撞别人的体框/文本行 → 双方都计价（谁动谁买单，由搜索自然分摊）。
3. 目标：拓扑档的 readability 硬违反 **16 → 0**（readability 硬闸本身不放宽）。反激 `draw compile` 出 ≥1 个 `ok=True` 候选。SVG 落 `outputs/201d/previews/`。
4. 若清零后仍卡在路由或旗，把死因读数写细（哪条网/哪颗旗/差几格）。

## 验收锚

- 反激 compile ≥1 ok=True 候选（或如实报下一死因）。
- divider + 五模板编译仍过，不明显变差（前后对比表）。
- 全量绿 `--basetemp=.tmp_pt_201d -n 4 --dist loadfile`；变异 ≥2 组（关文本行项 → readability 违反回升）。
- 零移动闸动了就前后对比重钉。
- 性能：反激单档 < 60s。

## 纪律

同前：只动 placement.py / drawcompiler.py 落位段（router/旗标/grammar 不碰）；不动 git；不 rm（回收站）；零企业名；不碰真机。证据 outputs/201d/evidence.md；PROGRESS.md append 一行；不要 commit。约 100 分钟。

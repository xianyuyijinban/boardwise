# 任务 002：单文件审查——从 .epro2 直接跑出审查报告

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 测试：`./.venv/Scripts/python -m pytest`（现有 72 个测试必须保持全绿）。
> 前置阅读：`README.md`、`docs/api-survey.md`、`docs/epru-format.md`、`src/boardwise/parsers/epru.py`、`src/boardwise/parsers/enet.py`、`src/boardwise/engines/review.py`、`src/boardwise/cli.py`。

## 背景

审查器现在有两个割裂的入口：连通性模型来自 `.enet` 导出（`parsers/enet.py`），几何模型来自 `.epro2`（`parsers/epru.py`，任务 001 刚完成）。但 `.epro2` 里**本身就含有完整的连通性信息**（PCB 段的 PAD_NET 记录 + DEVICE 段的器件属性）。本任务打通单文件入口：`boardwise review board.epro2` 一个命令跑出完整审查报告。

## 已探明事实（任务 001 的结论，直接信任）

- `.epro2` = ZIP，内含多个文档段（DOCHEAD 分段）；板级数据在 `docType=PCB` 段，器件属性在 `DEVICE` 段，封装在 `FOOTPRINT` 段。
- `PAD_NET` 是四元组关联：组件 id + 引脚号 + 封装 pad id → `padNet`。存在空 body 记录（`{env}|||`），390 条 PAD_NET 里只有 121 条带网络。
- 坐标单位 mil，y 轴向上为正。
- PCB 段有 47 个组件实例；11 个 pad 无网络（NC）。

## 待你探明的部分

器件属性（Value、LCSC 料号、Manufacturer、Datasheet）在 DEVICE 段还是 PCB 段的 ATTR 记录里、join 键是什么——在夹具上反推，结论写进 `docs/epru-format.md` 新增一节。**断言要建立在夹具里核实过的事实上，不要猜。**

## 交付物

1. **`parsers/epru.py` 扩展**（或新模块 `parsers/epro2_model.py`，你选更干净的方式）：从 `.epro2` 构建 `core/model.py` 的 `DesignModel`——
   - Component：位号、value、footprint、lcsc 等 props（从 DEVICE/ATTR 段 join；哪些属性拿不到就如实留空并在文档里记录）
   - Pin：number + net（来自 PAD_NET；无网络的 pad → net=None）
   - 与几何模型的链接方式：`DesignModel` 和 `BoardGeometry` 来自同一次解析，至少要能通过位号互查（具体 API 你设计，写明即可）
2. **CLI 打通**：`boardwise review <file>` 按扩展名路由——`.enet` 走现有路径，`.epro2` 走新路径；两条路径跑同一套 L1 规则和报告渲染。`--json/--md` 行为不变。
3. **测试**（`tests/test_epro2_model.py` + 扩展 `test_cli.py`）：
   - 从夹具构建的 model：组件数 ≥47、抽查具体器件的 pin→net（先用脚本核实夹具事实再写断言）
   - L1 规则在 epro2 派生模型上能跑、不崩；输出 findings 与 `.enet` 路径的差异如存在，解释原因（如属性缺失导致启发式判定不同）
   - CLI 冒烟：`boardwise review tests/fixtures/llc_board.epro2` 出报告、退出码合法
4. **README 使用示例更新**：加 `.epro2` 单文件用法一行。

## 追加需求（2026-09-12 侦察后更新）

5. **加密输入检测**：EasyEDA 的「工程另存为（本地）」对话框有可选的密码加密勾选。解析器入口要早检测：不是 ZIP / ZIP 条目带加密标志 / JSON 解不出 → 报明确错误「工程备份被加密导出，请重新导出时不要勾选加密」，不许抛出谜之栈。补一个针对非 ZIP 输入的测试。
6. **对照官方文档校准**：官方已发布 V3 格式文档（MIT，`github.com/easyeda/easyeda-pro-format-skill`，含逐图元字段定义 + JSON Schema）。把 `docs/epru-format.md` 里标注为"猜测"的语义逐条对照官方文档：确认的就改写为"确认（官方文档）"并注明出处路径，不符的就修正解析器。优先核对这些关键语义：坐标单位与原点、PAD_NET 四元组、LINE/FILL/POLY 的分工与 net 字段名、COMPONENT 实例的变换（x/y/angle）。可用 `git clone --depth 1` 或逐文件 raw 下载获取该仓库资料，但**不要**把它的文件复制进本仓库。

## 约束

- 标准库 only；代码/注释/docstring 英文；不动既有公开接口（`parse_epro2`、`parse_enet`、规则类签名）。
- 不执行任何 git 命令（clone 官方文档仓库到 `/tmp` 或 `E:\boardwise\.ref\` 用于阅读是允许的，别提交进项目）。
- 测试秒级。

## 验收时我要看的

- 器件属性的实际来源段和 join 键（附证据样例）
- `boardwise review tests/fixtures/llc_board.epro2` 的完整输出
- 全量测试输出
- 与既有事实不符的发现

---

## 验收记录（2026-09-12，Kimi）

状态：**ACCEPTED（带一处修复）**。

- 独立复验发现交付时 `test_review_reports_encrypted_backup` 实为**红色**（报告称 96 passed 有误，实为 95+1F）。根因：任务单 002 要求的错误提示含 Unicode 破折号，Windows 管道默认 cp936 编码导致子进程输出非 UTF-8 字节——任务单表述责任在 Kimi。修复：`cli.main()` 入口强制 UTF-8 stdio（对未来中文器件名输出也必需）。
- 复验后 96 passed；LLC 夹具 7 条 WARN 均为 decoupling 启发式（局限已如实写在消息里）；.enet 路径无回归。
- join 键（PCB ATTR Device → DEVICE uuid）47/47 命中，接受。
- **value 回退 DEVICE title：批准**。理由：规则主要消费位号前缀和阻值解析；半导体拿到型号字符串无害且已文档化。
- 遗留：`POURED` 局部坐标问题已按"保留记录、points 置空"处理，待官方文档进一步确认。

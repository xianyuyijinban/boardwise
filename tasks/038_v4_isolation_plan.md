# V3/V4 容器隔离与语义继承计划（2026-10-31）

> 岳批准规划开发。目标不是做两套审查器，而是让容器差异止于适配层。
> 当前工作树含 #89A/B、V4 调研等未提交文件，均不得覆盖或整理；每批不自带 git 写。

## 1. 架构边界

| 层 | V3 | V4 | 继承/隔离裁决 |
| --- | --- | --- | --- |
| 本地工程壳 | `.eprj2` SQLite | 实测仍可 `.eprj2` | 一律不直接读设计，继续引导导出 |
| 导出容器 | `.epro2` ZIP | `.epro2` 或 `.eprj3` 文件夹 | 在 `load_epru_text` / eprj3 适配器隔离 |
| 记录帧 | `{env}||{body}|` | 同帧，真样本 EOF 可缺最终 `|` | 共享 `epru_stream`，只修合法尾帧，不复制解析器 |
| 原理图变换 | V3 坐标/key | eprj3 yAxisDirection、PIN id、页内嵌库 | 仅在 eprj3/schematic 既有分支隔离 |
| PCB 容器 | `.epro2` 内 PCB 文档 | `pcb/*.epcb2` | 新增 V4 source 适配；`split_documents` 后继承 |
| 语义输出 | DesignModel / BoardGeometry / ProjectModel | 同左 | 全部继承，禁止 V3/V4 两套规则 |
| 报告/收尾 | ReviewReport、conclusion、triage/finalize | 同左 | 冻结；只修覆盖与证据真实性 |

## 2. 批次与集成锁

1. **038F1 共享 EOF 帧**：只动 `epru_stream` + 新测试。区分完整空 body `|||`、EOF 空 body
   缺终止符 `||`、真正截断的非空 body。V3 回归不变，V4 样本假损坏消失。
2. **038F2 V4 元数据**：只动 eprj3 适配层。用 DOCHEAD `editVersion` 填版本元数据，
   不把所有文档版本混成一个值；无版本仍未知。
3. **038F3 报告诚实性**：只动 checkup/CLI 覆盖与文案。eprj3 有 PCB 文件但未跑 PCB 审查时，
   `pcbReviewMissing`、canvas note、evidence 必须一致；不得说无 PCB。先修披露，不借 Tier-B 假完成。
4. **038F4 V4 PCB source 适配**：只动 eprj3/shared parser。`pcb/*.epcb2` → `split_documents` →
   `Epro2Source`，复用两个 builder。首切片一 PCB；多 PCB 无映射证据时明确拒绝，不猜。
   钉 POUR/POURED 单位与版本，不改几何规则。
5. **038F5 CLI Tier-B 接线**：只动 `_load_model` / checkup runner 接线和测试。让 view=pcb、
   `checkup --file` PCB 段真正使用 F4；报告/规则合同不变。

每批独立任务书、独立 basetemp、聚焦测试和至少两处变异。shared 与 CLI 不夹批；迁移与规则算法
不夹批；主代理抽 diff、独立变异和最终四线/Rust/跨语言验收。

## 3. 真实样本锚（只读，不入库）

V4 样本已有主代理复跑读数：原理图 128/107，PCB 128/88；几何 60 层、502 pads、730 tracks、
244 vias、75 pours；GHA=Q7.4+U10.5。P1/P2/PCB1 末尾均缺最终 `|`。这些数值用于外部验收，
不把真实工程或派生内容收进 fixtures/blocklib。

尚未解决：107↔88 网差、pads_without_net=76、POURED 10 倍单位、多 PCB、缺省坐标、真实 NC、
视觉渲染。不得因 F1–F5 完成就宣称所有 V4 已兼容或真机验收完成。

## 4. 非目标

不改 `.eprj2` 拒绝策略；不改 ReviewReport schema/verdict/exit code 语义；不改 connector/DSH；
不实施 AI 电路语义编译器；不把 V4 在线复测替换成离线样本；不做发布或 issue 状态变化。

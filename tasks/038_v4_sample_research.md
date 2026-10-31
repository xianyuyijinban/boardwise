# 任务书：真实 eprj3 样本只读差分（2026-10-31）

## 样本与边界

用户明确提供并授权只读研究：
`C:\Users\xiangyu\Downloads\New Project_2026-10-31_01-09-06\New Project_2026-10-31_01-09-06`

已见：index `.eprj3`、`eprj3-intro.md`、`sch/Schematic1/P1.esch2`、`P2.esch2`、
`Schematic1.ecfg`、`pcb/PCB1.epcb2`、`panel/Panel1.epan2`。index 的 `pcb_count=0` 与 PCB 文件
实际存在并存，需查语义，不能自行解释成无 PCB。

只读源目录；不得修改、移动、删除或复制真实工程进仓库/fixtures/blocklib。所有脚本、日志、
匿名计数和报告写 `.tmp_v4_sample_20261031/`；最终证据由主代理更新
`outputs/review/v4-review-line-research.md`。不做 git 写、不连接编辑器/daemon、不安装软件、
不联网上传样本或其派生内容。公开描述只用“V4 样本”/PCB1，不写用户 uuid 或可识别信息。

## 必做研究

1. **冻结身份**：记录各文件大小、行数、SHA-256；index 的 boards/schematics/sheets/pcbs/panels
   关系、版本/格式字段与 `pcb_count` 的实际含义。无证据就标未知。
2. **原理图实跑**：用仓库 `.venv` 与 `PYTHONPATH=E:\boardwise\src` 调现有公开 parser，
   分别对根目录和 index 文件路径验证入口是否一致；记录页/板/器件/网/脚计数、异常与
   `unproven` / duplicate 等诚实性字段。必须回查原始记录核对至少一个器件、一个网及其成员，
   不能只报“命令 exit 0”。
3. **坐标与身份**：统计 `yAxisDirection` 的实际取值/缺省、DOCHEAD/docType、CANVAS 有无、
   NC 引脚与 COMPONENT/ATTR 身份字段形态；核对转换前后坐标，不允许只数标记个数。
4. **离线 checkup**：在 `.tmp_v4_sample_20261031/checkup/` 跑一次 `checkup --file <样本>`，
   记录真实 exit、report.conclusion、source/coverage/model/PCB/canvas 读数；解释是否因为
   Tier-A 未支持而降级，不把 no finding 当通过。若输入不可用，保留错误原文。
5. **PCB 研究**：只读分析 `PCB1.epcb2` 的记录类型、DOCHEAD、单位/坐标、层、焊盘/走线/过孔/
   铺铜和网络记录；与现有 `.epro2` PCB parser 的输入期待对照，列出可复用缝和真实缺口。
   本批不实现 Tier-B，不改 parser。
6. **下一批清单**：把已由真样本证实/证伪的事项从旧调研未知项中移除或保留，给 P0/P1/P2
   最小修改建议及验证锚。特别关注 index `pcb_count=0`、实际 PCB 文件和 profile 的关系。

## 交卷

子代理只回≤2000字汇总，详细命令/计数/匿名摘要落 `.tmp_v4_sample_20261031/`。
报告真实命令与失败，不写生产代码、不扩项。最多40步或30分钟；如需读取样本以外路径或
修改源码才能继续，停止交主代理。

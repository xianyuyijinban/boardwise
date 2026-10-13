# R3 → v0.6.0：KiCad 第二宿主（侦察 → 离线审查最小闭环）

主题：boardwise 的引擎（规则/解析/审查）与宿主解耦得不错，把第二宿主 KiCad 接进来。
**战略意义**（岳定的方向）：立创和 KiCad 的 harness 都在野蛮生长期，先到的吃赛道。
估计工作量：侦察 1-2 天；最小闭环 3-5 天。

## 阶段一：侦察（不过门不进阶段二）

产出一份《KiCad 能力矩阵》（落 `outputs/R3/`），回答：

1. **文件格式**：`.kicad_sch` / `.kicad_pcb` / `.kicad_pro` 的文本格式（S 表达式）——
   拿一个真实工程样本（自建最小工程：一颗电阻一颗电容一根线），逐字段读一遍：
   器件/位号/值/网络/封装/坐标/层。写清「与 .epro2 模型的映射表」。
2. **自动化通道**（三选一的调研，全部试到能跑 demo 为止）：
   - `kicad-cli`（命令行：导出 netlist/BOM/ERC/DRC——哪些版本有，输出格式）；
   - `pcbnew` Python API（能不能读打开的板子？能不能读写原理图？Windows 上
     Python 绑定怎么装）；
   - 新版 IPC/API（KiCad 9 的 api 插件机制）——值不值得做 daemon 式在线桥。
3. **结论矩阵**：能读什么 / 能写什么 / 什么读不到（对照立创侧 outputs/001 的
   逆向笔记格式写），以及「离线优先 vs 在线桥」的建议。

**侦察门槛**：矩阵里「离线读原理图+PCB」必须确认可行才进阶段二。

## 阶段二：离线审查最小闭环

把一份 KiCad 工程读成 boardwise 的 `DesignModel` + `BoardGeometry`，让 L1 规则
（`src/boardwise/rules/connectivity.py` 那层）和 PCB 规则在 KiCad 夹具上出判决。

**做什么**：
1. 新解析器 `src/boardwise/parsers/kicad.py`（S 表达式 → 模型）。**不碰**既有
   epru 解析器；共用模型接口。
2. CLI 入口：`checkup --file` 按扩展名/内容自动分派（.epro2 走旧路，.kicad_pro/
   .kicad_sch 走新路）。
3. 夹具：`tests/fixtures/` 新增一个最小 KiCad 工程（自建，别拿别人的版权设计）。
4. 规则侧零改动是目标——若必须动模型，增量加字段，不许改既有字段语义。

**验收锚**：
- 夹具上 L1 规则出判决（至少：duplicate designators / decoupling / shunt 系）；
- PCB 侧至少跑通几何解析（板框/走线/焊盘），一条距离类规则出判决；
- 全量绿 + 既有夹具零影响（5400+ 一条不许红）；
- 《能力矩阵》随 PR 交（文档落 `docs/` 还是 `outputs/R3/` 由主代理定）。

## 红线补充

- KiCad 官方工具的调用要在隔离环境（venv/子进程），不装全局东西。
- 不许抄立创的逆向假设到 KiCad 上——KiCad 格式是公开的，照公开文档+实测写，
  不许「想当然对齐」。

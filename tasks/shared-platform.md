# 共享底座与集成锁（540B8）

> shared 不是第三条业务线，也不是“谁都能顺手改”的公共目录。它承载 review/draw 共同
> 依赖的公开合同；任何变化都按**两线集成改动**单独复审。

## 1. 范围

- `.epro2` / netlist parser、DesignModel、单位/几何、设计身份、CircuitSpec/DesignIntent、
  ChangePlan/SymbolProfile/Compare/Blocks/PinTable 等公开合同。
- bridge/connector/daemon 的传输、权限和身份；纯 `engines.assemble`。
- B1–B3 的 `core/netdomains.py`、`core/connectivity.py`、`core/decap.py`。
- `commands/shared.py` 与 assembly 的 24 命令组装；`commands/assembly.py` 仅 assembly 表面。
- 540C 的跨语言合同、差分/golden 和最小 Rust 进程骨架。

shared 只能 import shared。`core.annotations`/`core.railquery` 等既有 review 模块和
`core.presentationspec`/`core.layoutplan` 等 draw 模块不因放在 core 就变成 shared。
逐模块权威是 `contracts/module-owners.json`，由 `tests/test_owner_rules.py` 机器执行。

## 2. 集成锁

1. shared 改动必须单独成批，先写公开合同、调用方、行为基线和回退方式；不得夹在 review
   规则或 draw 算法批里，也不得为了“顺手”改变 verdict、几何或输出。
2. 至少验证两个实际消费者的等价性。Finding/severity/mode 留 review，绘制决策留 draw；
   shared 不复制任何一端的业务判断。
3. AST/owner/layer 守卫必须保持：shared→review/draw=0，review→draw=0，legacy 集合为空。
   新跨线边不能靠登记例外偷偷通过，必须先回到架构裁定。
4. CLI 旧参数/顺序/退出码/输出与 monkeypatch 可观察面要冻结；DSH 旧名与 JSON 同理。
   新业务一律先给版本化合同，不给隐式默认值。
5. **shared、全量测试、真机全部串行**。全量 pytest 一次一轮，connector/DSH/Rust 随后；
   真机只读或写入都需任务书逐字授权，真实工程不写。
6. git 写、push、发布、删除、全局安装与 worktree add/remove/prune 逐次问岳。

## 3. 交接与证据

- 当前行为矩阵：`evidence/540/b-behavior-equivalence.md`。它记录邻域和结构证据，
  不把邻域读数冒充最终全量。
- CLI 兼容锚：完整 argparse 树/帮助/默认值/namespace 对拍；规则源码指纹只说明源码位置，
  不能代替行为测试。
- 每批交接写清实际命令、读数、变异与 SHA-256 恢复、未覆盖项和对两线的影响。
- 证据/探针按 `docs/workspace-conventions.md` 落位；未跟踪/ignored 不等于可回收。

## 4. Rust strangler 接口

迁移顺序固定为：**纯函数/几何 → parser/model → review → draw → daemon 最后**。
进程边界优先 Rust CLI + structured JSON，不引入 PyO3/WASM/Node native addon。
0.6.x 新工具/引擎默认 Rust，例外登记；旧工具按「合同对齐 → Rust 默认 → 临时 Python
fallback → 删除旧实现」垂直迁移。Python fallback 只过渡，不形成长期双业务实现。
0.7.0 的目标是 Rust 接管全部受支持主流程，不是逐行翻译所有 Python；connector/DSH 薄适配可留 TS。

540C 的任务书与完成定义见 `tasks/540c_rust_platform.md`，构建/差分命令见
`docs/rust-platform.md`，证据见 `evidence/540/c-acceptance.md`。迁移与算法变化不得同批；
没有真实工程夹具、全局安装或发布。

## 5. worktree 与并行派单

当前只有一个模块化单体，**没有为 review/draw/shared 创建专用 worktree**。两线可独立派
小批，但 shared 集成点由本文件串行。以后确需隔离时，派单必须先写路径、分支、owner、
集成顺序、独有证据与回收判据，再逐次申请 git worktree 操作；旧档案 worktree 不可解释成
可写工作区或临时目录。

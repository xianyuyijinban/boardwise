# 540C — Rust 迁移平台准备（不批量翻译）

- 母任务：`tasks/540_pre060_platform.md`；前置：540B 的业务边界与共享合同已落地。
- 目标：建立可执行的跨语言合同、差分/golden 机具和最小 Rust 进程骨架。
- 非目标：不翻译业务规则/布局布线/解析器，不做 PyO3/WASM/Node native addon，不全局安装工具链。

## C0 工具链与合同清单（只读）

- 探测 `cargo/rustc/rustfmt/clippy` 版本与组件；缺什么如实记录，安装必须另问。
- 盘点当前 CLI 参数、退出码、错误码、schema 字符串、ReviewReport 与 LayoutPlan 的既有序列化入口。
- 选定匿名合成或现有公开夹具；不读取/复制真实工程容器，不新增真实板夹具。

## C1 冻结跨语言合同

- `contracts/` 下建立版本化 CLI 合同、退出码/错误码、JSON Schema、ReviewReport/LayoutPlan 合同。
- 合同从当前生产序列化与命令行为提取，不在文档里另猜一套；未知/可选/缺省/错误形状要显式。
- 保持现有 Python 行为；本批只做验证所需的最小补齐，不改 verdict、refusal 或 drawing 输出。

## C2 Python/Rust 差分与 golden

- 建立统一 case 格式、输入/expected、规范化规则与退出码/stderr/stdout 对拍。
- golden 只含匿名合成或现有公开材料；记录来源、SHA-256 和再生成命令。
- Python 侧先跑通；Rust skeleton 接入同一 case runner，证明差分框架确实执行而非只有目录。

## C3 最小 Cargo workspace

- `rust/`：一个 workspace、core library crate、CLI crate；不引入业务逻辑。
- 进程边界采用 Rust CLI + structured JSON；一个 business-free smoke contract test 覆盖
  参数解析、JSON envelope、退出码与错误形状。
- 实跑 `cargo fmt --check`、`cargo clippy -- -D warnings`、`cargo test`，结果写入验收记录。

## C4 迁移纪律与构建接入

- 顺序：纯函数/几何 → parser/model → review → draw → daemon 最后。
- 0.6.x 新工具/引擎默认 Rust，例外登记；旧工具按垂直切片：
  合同对齐 → Rust 默认 → 临时 Python fallback → 删除旧实现。
- 迁移与算法变化不得同批；Python fallback 只过渡，不形成长期双业务逻辑。
- 0.7.0 是 Rust 接管全部受支持主流程，不是逐行翻译全部 Python；connector/DSH 薄适配可留 TS。
- 更新 roadmap/TASKMAP/SCHEDULE/handoff/AGENTS 与构建文档；不发布。

## 完成定义

- 合同有机器可验 schema 与兼容测试，golden 不含真实工程；差分框架两侧实际运行。
- Cargo workspace 最小且 clippy 零警告，smoke 不涉及业务；三条 cargo 命令全绿。
- 现有 Python/connector/DSH 与新增 Rust 检查串行通过；没有全局安装、真实工程写、git 写或发布。

## 验收记录

- C0：**完成并纠正早期结论**。Rust 组件齐全，但主机 MSVC CRT/SDK 链接库不完整；
  未做全局安装，只用官方签名载荷在任务目录补齐 x64 链接输入。详见 `evidence/540/rust-toolchain.txt`。
- C1：**完成**。版本化 CLI/ReviewReport/LayoutPlan/draw/bridge 合同与正负例兼容闸，
  `tests/test_540c_contracts.py` **28 passed**。
- C2：**完成**。四个公开/合成 case 双侧实际运行，移除且仅移除 `runner` 后 normalized
  SHA-256 同为 `13ca62626beeeb66f84bde490bfc879548f18ad5b38e12ddc4a446b24886f753`；
  合同+差分 **35 passed**。结构化证据 `evidence/540/c-differential-comparison.json`。
- C3：**完成**。最小两 crate workspace；`cargo fmt --check`、`cargo clippy -- -D warnings`、
  `cargo test` 全绿，**7 passed / 0 failed**，日志 `evidence/540/cargo-test.log`。
- C4：**完成**。`docs/rust-platform.md`、AGENTS、roadmap/TASKMAP/SCHEDULE/handoff 与
  shared 集成锁已同步；联合守卫 **89 passed**。变异与 SHA-256 恢复见
  `evidence/540/c-mutation-checks.md`，其中一次 survivor 已补缺省字段测试后重放杀死。
- 总结证据：`evidence/540/c-acceptance.md`。母任务最终串行全量也已完成：Python
  **7876/21/5**、connector **536**、DSH **122/1**、Rust **7** 全绿，见
  `evidence/540/final-regression.md`；无真实工程写、git 写、推送或发布。

## 对抗修复与追加验收（2026-10-26，当前）

> 上面 C0–C4 的记录保持原样（合同 28 / 合同+差分 35 / Cargo 7 / 4 case 都是首版读数）。

- **合同**：8 个合同文件 **346 passed**（首版 28 的扩大版，旧记录不撤回）。
- **Rust**：默认 **45 passed / 4 ignored**；显式语料 **4 passed**
  （`python_compat_corpus` 3 + `schema_parity` 1，用 `-- --ignored` 真跑）；
  `cargo fmt --check` 与 `cargo clippy -- -D warnings` 零诊断。
- **真实差分 5 case**（新增 `compile-page-result-projection`）：`review-report-projection`、
  `layout-plan-geometry`、`compile-result-projection`、`compile-page-result-projection`、
  `lint-result-projection`，两侧 `ok=true`，normalized SHA-256 双方同为
  `5230498201445920e02058bb11e99274e82be02c91952f38b9f2f919cb9d5f7c`。
  caseBook `contracts/differential/cases.json` 的 SHA-256 为
  `7df2c4009e4382664c7801e2aa5111eaf883d109d73188238ecd7642dbb61430`。
  证据：`evidence/540/c-differential-comparison-adversarial.json`（旧 4-case 文件保留不动）。
- **合同语义补钉**（都有机器钉，不是文档口径）：
  - page 与 module 是**独立 schema**；`pageCount` 与 `candidateCount` 不是同一个量，
    不能互相代入。
  - preview 的 basename **宿主无关**：取最后一个 `/` 或 `\` 之后的文本，两种分隔符在
    任何宿主上读法一致；这一口径拒绝**尾分隔符**与末段恰为 `.` / `..`，因为那会让两侧
    runner 对 basename 产生分歧、或根本没有文件名可指（是 basename 一致性与"必须指名文件"，
    **不是**目录逃逸防护）。
  - 比较器按 **canonical bytes** 比，`--output` 一律 **LF**（不随 Windows 文本模式变 CRLF）。
- **旧 golden 不变**：LayoutPlan 的 `geometrySha256`
  `62a272b1968a1d037a6854f38299223f8597ab4acd06fed25f11d7476ca056b1`。
- **完成定义的最终判定**：以 `evidence/540/candidate-regression.md` 为准；该文件由后续
  步骤产生，**未产生前不视为候选已通过**。本轮收口摘要见
  `evidence/540/final-regression-followup.md`。

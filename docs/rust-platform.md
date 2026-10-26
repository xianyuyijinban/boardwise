# Rust 迁移平台：构建、差分与派单边界（540C）

## 1. 当前范围

`rust/` 是一个最小 Cargo workspace，只有两个 crate：

- `boardwise-core`：语言中立 JSON 投影、LayoutPlan 几何哈希、`contracts/json`
  输入 schema 校验（`src/schema.rs`，`tools/contract_validate.py` 的移植）与结构化
  CLI envelope；
- `boardwise-cli`：`differential` 与无业务 `smoke` 的进程边界。

它不是现有 `boardwise` Python CLI 的替代品，也不连接编辑器或 daemon。审查规则、
parser/model、布局/布线算法都不在这批翻译；不引入 PyO3、WASM 或 Node native addon。

## 2. 工具链与构建

需要 stable Rust、`rustfmt`、Clippy 和当前 target 的完整本机链接环境。Windows 的
`x86_64-pc-windows-msvc` 除了 Rust 标准库，还需要匹配的 MSVC CRT 与 Windows SDK
import libraries；只看到 `cargo --version` 成功，不能证明链接环境完整。不得混用
MinGW 与 MSVC CRT 来制造通过结果。工具链安装或全局配置变化必须另行取得批准。

在仓库根执行：

```bash
cd rust
cargo fmt --check
cargo clippy -- -D warnings
cargo test
```

`Cargo.lock` 随 workspace 固定依赖解析；`rust/target/` 是可再生构建产物，不进入提交。
测试包含 core 单元测试与 CLI 进程测试，覆盖参数、stdout/stderr JSON envelope、
退出码、错误形状和仓库差分 case。

## 3. Python/Rust 差分与 golden

`contracts/differential/` 只使用既有公开夹具或匿名合成输入。生成器会清理时间戳和
机器路径；来源、输入与 case book 的 SHA-256 记录在 `manifest.json`。不要在变更无关
业务输出时顺手再生成 golden。

仓库 case book 当前有 **5 个 case**：review 投影、layout 几何、module compile 投影、
page compile 投影、lint 投影。两份 compile 结果是**彼此独立的合同**：module 文档用
`draw-compile-result-v1.schema.json` 的 `candidates`，page 文档用
`draw-page-compile-result-v1.schema.json` 的 `pages`，投影字段也各说各的名字
（`candidateCount` 对 `pageCount`），不得把一份改名成另一份。两种形状共有的
`command`/`ok`/`failureCount`/`previewNames` 由 Rust 侧同一个阅读器产出；page 投影
只数 `pages`，不伪造它从未声明的 `candidateCount`。

### 3.1 两侧命令（默认路径与参数形态）

两侧 `differential` 共用同一套可观察参数面：`--flag PATH` 与 `--flag=PATH` 等价，
三个参数重复时**后者生效**（与 Python `argparse` 一致），并且都有仓库默认值。

```bash
mkdir -p .tmp_540/c1

# 不写 --cases/--root：默认是“代码旁的仓库”，与当前 cwd 无关
.venv/Scripts/python.exe -m tools.differential --output .tmp_540/c1/python-differential.json
rust/target/debug/boardwise-cli.exe differential --output .tmp_540/c1/rust-differential.json

# 等号写法与重复参数（后者生效）
rust/target/debug/boardwise-cli.exe differential \
    --cases=contracts/differential/cases.json --root=. \
    --output .tmp_540/c1/rust-differential.json

.venv/Scripts/python.exe -m tools.differential_compare \
    .tmp_540/c1/python-differential.json .tmp_540/c1/rust-differential.json \
    --output .tmp_540/c1/comparison.json
```

默认值固定为仓库自身：Rust 用编译期 `CARGO_MANIFEST_DIR` 上溯得到的仓库根，对应
Python 的 `Path(__file__).resolve().parents[1]`。`--cases` 缺省是
`<repo>/contracts/differential/cases.json`，`--root` 缺省是 `<repo>`，两者互相独立：
只给 `--root DIR` 时仍读仓库 case book。**不得**把 cwd 当作默认值。

比较器只移除 `runner` 字段，其余 JSON 值（包括 case 顺序、actual/expected 与 ok）
必须完全一致；报告同时给出双方规范化 SHA-256。`ok=true` 才表示对拍通过，不能把
“两个进程都退出 0”当作内容一致。

### 3.2 退出码与错误边界

| 情形 | 退出码 | stdout | stderr |
| --- | --- | --- | --- |
| 全部 golden 一致 | 0 | differential 报告 | 空 |
| golden 不一致 | 1 | 报告（`ok=false`） | 空 |
| `-h` / `--help` | 0 | usage 文本 | 空 |
| usage error（未知 flag、缺值） | 2 | 空 | 纯 usage 文本，**不是** JSON envelope |
| runner 拒绝（schema 拒绝、I/O、未知 kind、`--output` 父目录不存在） | 2 | 空 | 一个 `boardwise.cli-result/1` envelope（`command: differential`、`error.code: BAD_REQUEST`） |

usage 文本不要求与 argparse 逐字相同（flag 语法是各自实现的），但两边都不许把
usage error 混成 domain envelope。`--output` 在打印报告**之前**写盘：写失败时 stdout
保持为空，不会出现“报告已打印但退出码是 2”。`--output` 文件用 LF（与 Python 的
`write_text_lf` 一致，便于按字节记录）。

### 3.3 输入 schema 校验与依赖

`boardwise-core/src/schema.rs` 是 `tools/contract_validate.py` 的 Rust 移植：
`project_case` 在每种 kind 投影前都会用 `contracts/json/<kind>.schema.json` 校验输入，
schema 文件按 Python 口径从“代码旁”的仓库读（不受 `--root` 影响）。语义要点：全树
预检（未知关键字、未知 `type`、`$ref` 链/环/悬空）、`$ref` 是 applicator、`items` 只
作用于 `prefixItems` 之后、`enum/const` 递归且 `true ≠ 1`、`1.0` 算 integer、非有限数
拒绝（`NaN` token 与 `1e999`）。

`contracts/json` 现有 **6 份 schema**（`bridge-error-v1`、`draw-compile-result-v1`、
`draw-lint-result-v1`、`draw-page-compile-result-v1`、`layout-plan-v1`、
`review-report-v1`）。每一份都由 `schema.rs` 的单元测试整树预检（可读且落在支持的
子集内），仓库里的公开差分输入则作为正例逐个跑一遍；page 与 module 两份 compile
合同还各有负例，证明任一输入都过不了对方的 schema、也进不了对方的 kind。

`regex` 依赖**只**服务于 schema 的 `pattern` 关键字（`tests/test_540c_workspace.py`
钉住：它只能出现在 `schema.rs`，CLI 依赖里不许有）。Rust `regex` 没有反向引用/环视，
Python 合法而 Rust 拒的 pattern 会报 schema 错误——更严，不会放空闸。现有 pattern
全部落在 `regex` 实际支持的语法里：字符类（如 `[0-9a-f]`、排除分隔符的 `[^/\\]`）、
分组（含非捕获组 `(?:…)`）、交替 `|`、`{64}`/`*`/`+`/`?` 量词与 `^`/`$` 锚点；没有
反向引用，也没有环视。Python 的 `$` 在串尾换行前也会匹配，这一点由 `pattern_matches`
模拟，不靠改写 pattern。新增 pattern 前先确认它在两个引擎里同义——不要依赖一份会
过时的“现有 pattern 清单”。

### 3.4 语料对照（`--ignored`）

两批对照语料由 Python 侧生成，默认不跑：`cargo test` 里它们显示 **ignored**，
ignored 不是通过。需要显式带上语料变量并加 `--ignored`：

```bash
.venv/Scripts/python.exe .tmp_adversarial540/geometry-rust/gen_float_corpus.py
.venv/Scripts/python.exe .tmp_adversarial540/geometry-rust/gen_number_corpus.py
.venv/Scripts/python.exe .tmp_adversarial540/geometry-rust/gen_geometry_corpus.py
.venv/Scripts/python.exe .tmp_adversarial540/rust-schema/gen_schema_corpus.py

BOARDWISE_540C_FLOAT_CORPUS=.tmp_adversarial540/geometry-rust/float-corpus.jsonl \
BOARDWISE_540C_NUMBER_CORPUS=.tmp_adversarial540/geometry-rust/number-corpus.jsonl \
BOARDWISE_540C_GEOMETRY_CORPUS=.tmp_adversarial540/geometry-rust/geometry-corpus.jsonl \
BOARDWISE_540C_SCHEMA_CORPUS=.tmp_adversarial540/rust-schema/schema-corpus.jsonl \
bash .tmp_540/rust-buildtools/cargo-local.sh test -p boardwise-core \
    --test python_compat_corpus --test schema_parity -- --ignored
```

### 3.5 跨语言 CLI 检查

`tests/test_540c_cross_language.py` 起两个真实进程对比：成功（空格/等号写法、重复
参数、`--output` 文件与 LF）、`-h/--help`、usage error、schema 拒绝、未知 kind、
`--output` 父目录缺失，以及 golden 不一致的 0/1 语义。Rust 二进制未构建时该模块
**skip** —— skip 不是验收：交卷前必须先 `cargo build -p boardwise-cli` 再实跑，
并看到这组测试 passed。

需要有意重建公开 golden 时，先审查输入来源与 diff，再运行：

```bash
.venv/Scripts/python.exe -m tools.build_differential_fixtures
```

永久兼容闸位于 `tests/test_540c_contracts.py`、`tests/test_540c_differential.py`、
`tests/test_540c_schema_semantics.py`、`tests/test_540c_generator_validation.py`、
`tests/test_540c_process_contract.py`、`tests/test_540c_cross_language.py` 和
`tests/test_540c_workspace.py`，覆盖 CLI 漂移与跨语言进程边界、真实/合成 JSON 正例、
schema 负例、来源哈希、golden 失败路径与 workspace/文档边界。

## 4. 迁移与派单纪律

迁移顺序固定为 **纯函数/几何 → parser/model → review → draw → daemon 最后**。
0.6.x 新工具/引擎默认 Rust，例外必须登记；旧工具按「合同对齐 → Rust 默认 →
临时 Python fallback → 删除旧实现」垂直迁移。Python fallback 只过渡，不形成长期
双业务实现；0.7.0 验收受支持主流程，不要求逐行翻译全部 Python，connector/DSH
薄适配可留 TypeScript。

跨语言合同、shared parser/model/core/CLI 或进程边界变化，走
`tasks/shared-platform.md` 的集成锁；审查与绘制算法分别由 `tasks/review-line.md`、
`tasks/draw-line.md` 派单。迁移与算法变化不得同批，shared、全量测试与真机串行。
路线与版本边界见 `docs/roadmap.md` §10；540C 验收记录见
`tasks/540c_rust_platform.md`。本文件不授权全局安装、真实工程写、Git 写或发布。

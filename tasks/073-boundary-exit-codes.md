# 073：`incomplete` → exit 3 + epru 同族结构闸（岳已裁「都需要」）

## 来源与裁定

两条互不相干的缺口，同一次派单（A 先、B 后，串行）：

- **A：072 留下的 CI 洞**。072 把「审查没看全」表达成报告里的
  `completion.verdict: incomplete`，但**只写进 JSON**：`review`/`checkup` 只要没 ERROR
  就还是 `exit 0`，CI 会把一份不完整的审查读成「通过」。岳裁：**需要**，`incomplete` →
  **exit 3**。
- **B：072 #28 的同族漏网**。`parsers/epru.py` 的 `attrs=dict(body.get("attrs") or {})`
  是同一根（对外部 body 字段的无保护转换）：attrs 是 int 时裸 `TypeError` traceback +
  **exit 1**（与「板子有 ERROR」同码），是 str/非成对 list 时退出 2 但报文是解释器自己的
  `dictionary update sequence element #0 has length 10`（不点记录、不点字段），是
  成对 list 时**静默变成 dict**。岳裁：**边界外同族也要修**。

## 已定设计（执行者不得改）

### A：退出码优先级 `2 > 1 > 3 > 0`

- 规则：两命令各自算完 verdict 后——**exit code 本为 0 且 verdict == `incomplete` ⇒ exit 3**。
- 有 ERROR 维持 `1`；坏输入维持 `2`；**`complete-with-open-items` 维持 `0`**（岳只点了
  incomplete，不得扩大范围）。
- **exit 3 语义**：结果不可陈述/审查没看全——与 CLI 既有 exit 3 同族，**不新造码**
  （`review --live` 拿不到模型 `cli.py:2512`、写结局未知 `cli.py:9476`、
  `update-connector` 无定论 `cli.py:10925`）。
- **单一事实源（#15 先例）**：`report.json` 的 `summary.exitCode` 必须与进程退出码同源同值，
  也要与 `report.md` 的「（退出码 N）」一致——一处算出、三处渲染。
- `review` 侧的 `incomplete` 判据 = `_model_read_nothing`（`empty_pcb_view ∨ empty_model`），
  与 `checkup` 的 `completion.coverage.modelEmpty` 同一个函数。
- 文档同步：README.md / docs/getting-started.md / docs/install.md / docs/bridge.md /
  `.kimi-code/skills/boardwise/SKILL.md`；dsh-plugin 工具描述引用了退出码 ⇒ 同步（connector 不动）。

### B：结构校验走 parsers 自己的错误类型

- 结构不满足 → 抛 `parsers/enet.py::NetlistShapeError`（复用，学 `epro2_model.py` 的 import
  先例），CLI 映射 **exit 2**，stderr 是 boardwise 一句话报错（带记录类型/位置，如
  「COMPONENT 记录 c1.attrs 不是对象」），**无 traceback**。
- 崩溃形状各一条测试：attrs 是 list / str / int，另加 None/缺省不回归（`or {}` 原本接住）。
- 审计 epru.py 全文件其它对外部 body 字段的无保护 `dict(...)` / `.items()` / `for ... in`
  假定；**同族的本批修**（各带测试），非同族的只记录不动。不扩到其它 parser 文件。

## 验收

- 先写失败测试（27 条）再修到绿：`tests/test_073_exit_codes.py`。
- **既有断言变更申报**：verdict=incomplete 且无 ERROR 的板子 exit 0→3。exit 1 的板子不许动。
- 回归：复用 `evidence/072/verdict_sweep.py` 跑 before/after——**verdict 必须 0/20 移动**，
  只有 exit code 动（0→3 恰好落在 verdict==incomplete 的板上，1 保持 1）。结果落 `evidence/073/`。
- 变异 ≥2（cp 备份 + sha256 还原，禁 git checkout）：A 去掉 verdict→3 映射 / 把码写错；
  B 去掉校验 / 改错码。
- 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 绿。
- 交卷：改动文件 sha256 before/after、测试清单与既有断言变更理由、全量输出尾行、
  verdict sweep 表、变异证据、自决项清单、边界外发现。不改 PROGRESS.md。

## 边界与纪律

- 零 git 写操作；本批**全离线**，不碰真机；不改 `tests/fixtures/` 与 `reviewsets/` 既有内容；
  不碰 `outputs/011e*`、`014_*`、`015b_*`、`016_*`；不改 PROGRESS.md。
- 可碰：`src/boardwise/cli.py`、`src/boardwise/parsers/epru.py`、`tests/` 同域文件、
  `dsh-plugin/src/index.ts` + `dsh-plugin/README.md`（描述文本）、docs 与仓库版 SKILL.md。
  `connector/` 不动。
- 先读 `E:/boardwise/AGENTS.md` 与 `.kimi-code/skills/boardwise/SKILL.md` §7。

## 交卷记录（执行者填，主代理复验）

- 落点：`cli.py` 新增 `INCOMPLETE_EXIT_CODE = 3` / `INCOMPLETE_EXIT_SENTENCE` /
  `_exit_code_with_verdict(exit_code, verdict)`；`_cmd_checkup` 在 `completion` 算完处
  把结果写回 `summary["exitCode"]`（进程码、`report.json`、`report.md` 一处算出），
  console 的 `exit:` 行给 exit 3 单独一句话；`_cmd_review` 用同一函数，exit-3 的 note
  打在 019 §1 的「提示行必须最后」之前。
- `epru.py`：`attrs` 走 `optional_object`，`PAD.defaultPad` 走 `optional_object`，
  `VIA.unusedInnerLayers` 走新 `_layer_list`（None → `[]`，非 list → 抛），
  三条都带「记录类型 + id + 字段」位置。
- 证据：`evidence/073/`（hashes_before/after、pytest_full、pytest_run1（行为变更清单）、
  verdict_regression、mutation/*、e2e_int.txt + e2e_int_before_B.txt、npm_dsh、npm_connector）。

### 数字

| 项 | 结果 |
|---|---|
| 新增测试 | `tests/test_073_exit_codes.py` 26 条（A 11 / B 15） |
| 全量 pytest | `2609 passed in 198.40s`（基线 2583 + 26，无删除） |
| verdict sweep | verdict 0/20 移动；exit 12 × (0→3) + 8 × (1→1) |
| 既有断言变更 | 9 个测试文件、39 处断言（35 处字面 `0→3`、3 处改成「与 verdict 配对」、1 处 `summary.exitCode`）+ 2 处消息文案；**改到的板子/输入共 58 条测试**（见 `pytest_run1.txt` 的 58 FAILED） |
| 变异 | M1–M5（A 两条、B 三条），全部 cp 还原 + sha256/cmp 一致 |
| 四线 | pytest 2609 绿 / connector 419 pass + tsc 0 / dsh-plugin typecheck+test(48 pass)+build 0 |

### 待裁（执行者未自行处理）

1. **re-gate 路径的 `summary.exitCode` 会过期**：`boardwise need-datasheet` / `triage` 重写
   `report.json` 与 `report.md`，但**不重算** `summary.exitCode`。一份 exit-0 的 `complete`
   报告被标记后 verdict 变 `incomplete`，报告里仍是 exitCode 0 / 「（退出码 0）」。
   修法一行（在 `_apply_needs_datasheet` / `_apply_warning_triage` 里复用
   `_exit_code_with_verdict`），但那是「re-gate 该不该改写上一次运行的退出码」的语义决定。
2. **`review --live` 的空模型仍退 0**：空读谓词 `_model_read_nothing` 被 `path is not None`
   限定（019/072 的既有设计，note 针对文件），而 `checkup` 的 `coverage.modelEmpty` 没这个
   限定 ⇒ 同一个空工程，`checkup` 退 3、`review --live` 退 0。离线夹具测不到 live 路径。


# 019 任务书：review 空板视图诊断提示（朋友内测 UX 改进）

> 2026-09-22 上午，岳批准（"可以，交给你和deepseek改进了"）。
> 执行者：commandcode/deepseek-v4.1-flash 子代理。复验与真机裁决：Kimi。
> 背景证据：`outputs/016_scene6_final.txt` 教训 B（今晨 Kimi 自己都踩了：缺省 view
> 审原理图导出 → "0 components 0 nets" 无任何提示，误以为导出缺内容）。

## 一、问题

`boardwise review 某.epro2` 的 `--view` **缺省 = pcb**（cli.py:108-117，choices pcb/schematic）。
朋友最典型的场景是"画了原理图想先审一下"——工程 PCB 为空，缺省 view 解析结果是
`0 components, 0 nets` + `board: 0 pads, 0 tracks, 0 vias`，**没有任何提示**告诉他
原理图审查要加 `--view schematic`。help 文本里虽然写了，但没人第一次用就读 help。

## 二、要做的（最小侵入，不改缺省行为）

### 1. CLI 控制台提示

触发条件（**三个条件同时**）：
- 输入文件是 `.epro2`（经工程备份通道解析）；
- `view == "pcb"`（缺省或显式都算）；
- 解析结果全空：0 components 且 0 nets 且 0 pads/tracks/vias。

触发时在控制台人类输出末尾加一行**英文**提示（控制台输出语言现状是英文）：

```
note: pcb view read nothing from this file — for a schematic review, re-run with --view schematic
```

（措辞可微调，必须含 `--view schematic` 字样。）

不触发时输出**逐字节不变**。

### 2. `--md` 报告中文摘要节提示

018 在 `--md` 顶部加了中文摘要节（`src/boardwise/rules/i18n.py`）。触发同条件时，
在中文摘要节里加一句：

```
提示：PCB 视图没有读到任何内容。如果你要审查的是原理图，请加 `--view schematic` 重新运行。
```

**`--json` 输出逐字节不变**（schema 被 `tests/test_review_eval.py` 钉死，碰都不要碰）。

### 3. 文档最小同步

- `docs/getting-started.md` §5.1（约 168 行）：第一条 review 示例命令改成带
  `--view schematic`（第一次审查 = 原理图场景），紧跟一句"审板级内容用 `--view pcb`
  （缺省）"。
- `README.md` 中英两节的 review 示例区：各加**一行**说明（`.epro2` 缺省审 PCB 视图，
  原理图审查加 `--view schematic`）。主命令行不动。
- `docs/install.md` 约 219 行（review 参数说明处）：补一句 `--view`。
- 其余文件不动。

## 三、测试

1. 新建 `tests/test_019_empty_board_hint.py`：
   - 触发（.epro2 + 缺省 view + 全空模型）→ 控制台含提示行、--md 含中文提示、--json 无变化；
   - 不触发 × 3：view=schematic / pcb view 有内容 / .enet 输入 → 无提示；
   - 先看 `tests/test_018_cli_review.py` 的调用模式沿用；夹具先找 `tests/fixtures/`
     有无空 PCB 的 .epro2；没有就 **monkeypatch 模型层**合成全空结果（不许把 outputs/
     下的文件复制进 fixtures，不动既有夹具一个字节）。
2. 变异验证一轮：临时删掉触发条件（或把条件改成恒 False 的反义）→ 新测试必须红；
   `cp` 备份 + `sha256` 还原，还原一致。
3. **既有测试全不许动断言**；`tests/test_review_eval.py` 必须原样全绿。

## 四、纪律（写死，违反即返工）

- **只跑子集**：`pytest tests/test_019_empty_board_hint.py tests/test_018_cli_review.py tests/test_review_eval.py -q --basetemp=.tmp_pt_019`；**禁止全量 pytest 循环**（全量三线由 Kimi 复验跑）。
- 不动 git（不 add/commit/checkout）；不动 `tests/fixtures/`；不动
  `outputs/011e*|014_*|015b_*|016_*`；新证据写 `outputs/019_*`。
- 工作目录 `E:\boardwise`，Python 用 `.venv/Scripts/python.exe`。
- 完成后报告：改动文件+行号清单、提示文案定稿、子集测试结果、变异验证结果（含 sha256）。

## 五、验收（Kimi 复验用）

- 子集绿 + 变异 CAUGHT + 全量三线（pytest/connector/tsc）绿；
- 真机：对 `outputs/ProPrj_test_2026-09-22.epro2`（空 PCB 真实样本）跑缺省 view
  应见提示、加 `--view schematic` 不见提示且有 3 件 6 网。
- 不在范围（另行向岳提议）：缺省 view 翻成 schematic（eval 走 schematic 解析器不受影响，
  但用户可见缺省变更属产品决策）。

---

## 六、交卷记录

### 执行者（agent-29，deepseek-v4.1-flash）

- 实现：cli.py 新增 `EMPTY_PCB_VIEW_NOTE`（58）+ `_pcb_view_read_nothing()`（1142-1169，三条件唯一判据）+ `_cmd_review` 接线（1191/1218-1231，note 为 stdout 最后一行）；i18n.py `EMPTY_PCB_VIEW_HINT`（56-67）+ `summary_section(hint=)`（缺省空串 = 018 输出逐字节不变）。
- 文案定稿：console `note: pcb view read nothing from this file — for a schematic review, re-run with --view schematic`；--md 摘要节 `提示：PCB 视图没有读到任何内容。如果你要审查的是原理图，请加 --view schematic 重新运行。`
- 测试：tests/test_019_empty_board_hint.py 11 用例（触发/--md 位置/--json 不变/不触发×4/判据单测）。子集 67 passed。
- 变异双 CAUGHT：A 判据恒 False → 5 红；B 删"铜也必须空"分支 → 1 红。cli.py sha256 `0d7999fc…` 还原一致。
- 文档：getting-started §5.1 示例改带 --view schematic + 一句说明；README 中英各加一行；install.md 补 --view 说明。
- 证据：outputs/019_*（mutation_and_tests / console 两种 view / report.md / .json）。
- 执行者自报待裁点：note 位置=stdout 最后一行（report written 之后），理由写在 cli.py:1227 注释——Kimi 复验认可，不改。

### Kimi 复验（2026-09-22 10:4x，串行亲跑）

- 全量三线：pytest **1259 passed**（1248+11，恰好）/ connector **305 pass** / tsc 干净。
- 真实样本亲跑：缺省 view → 0 组件 + note 末行出现；`--view schematic` → 3 件 6 网无 note。与任务书 §五期望逐字一致。
- git status 38 条：新增仅 tasks/019 + tests/test_019（outputs/019_* 走 -f 证据通道），fixtures/历史 outputs 零触碰。
- **019 验收通过。**

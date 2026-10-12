# 178 库 curation：分域地旗符号入库（173C 库侧收尾）

任务编号 178。类型：库数据 + 编译器接线核验。岳 2026-10-12 已定命名，本文件是唯一权威任务书。

## 岳的命名规则（不许发挥）

- 基础域：**PGND**（功率地）、**AGND**（模拟地）、**DGND**（数字地）
- 特殊地：**xxx-GND**（例：给 CAN 芯片的地 = `CAN-GND`）
- 既有板子在用的名字（如 SEC_GND）**不强行改名**——规则管新旗，不管历史网。

## 背景（主代理已查证，直接采信）

- 173C 已把「多域各挂各旗」接进编译器：`src/boardwise/engines/drawcompiler.py` 的
  `_gnd_flag`（约 5361-5392 行）按域取 `budget.gnd_flag`；库里没有对应旗标 profile 时
  在约 6745 行报「add the flag symbol to the library」。
- **库残留**：`blocklib/specs/` 三本库（power_entry_xt30 / flyback_uc3845 / ch340_serial）
  都只有 `PWR-GND 一个地旗字形（PROGRESS.md 173 条原话）。
- 旗标 profile 形制见 `flyback_uc3845.library.json` 里 PWR-GND 那条（pin-less profile，
  symbolRef + title；几何/姿态约定见 pits.md 坑 43 与 060/064 的罗盘分家记录）。
- `tests/` 里有 173 钉的「分层例外具名」测试（test_053b 一带），本批大概率要动它——
  按 060/064 的**场景哈希申报制**走，不许静默改钉。

## 必须先回答的三个问题（全部拿证据，不许猜）

1. **apply 时 `PWR-<X>` 如何解析到宿主符号？** 121d 入过 `PWR-HVDC`/`PWR-SEC_12V`
   两颗轨旗——读 `src/boardwise/engines/drawapply.py`（122 行 FLAG_SYMBOL_GROUND、
   374-416 行 flag_kind 逻辑）与 121d 的证据/测试，把「profile → 宿主符号」的解析链
   逐环写出来。地旗新 profile 必须走同一条链。
2. **宿主库里有没有现成的分域地旗字形**（Ground-PGND / Ground-AGND / Ground-DGND 之类）？
   先翻既有探针证据（`outputs/057_live/lib.json`、`outputs/099/`、`outputs/089/`），
   证据不够就在证据里写「未知，需真机 libprobe」并列出探针步骤——**本任务不做真机写
   操作**（往用户库建自定义符号是岳的决定，不是你的）。
3. **每本库的语法实际产生哪些地网名**：审三本库的 budget/grammar 与场景，列出每本库
   需要的地旗清单（ flyback 实测是 PGND + SEC_GND 两族，见 PROGRESS 121d/173），
   按岳的命名规则给新 profile 起名（`PWR-<网名>` 形制）。

## 实施范围

- 在需要的库 `library.json` 里补地旗 profile（docstring/title 写明几何出处与姿态约定，
  照 PWR-GND 那条的写法；几何数据没有实测来源时**如实标注来源是拷贝 PWR-GND**，不许编）。
- 编译器侧若 `_gnd_flag` 的域名→profile 解析需要接线（而不是纯库数据），把改动压到最小，
  并在证据里说明为什么库数据单独不够。
- test_053b 等受影响测试：变动逐处申报（前后哈希 diff 落证据）。

## 红线（仓库 AGENTS.md + 主代理纪律）

- 禁一切 git 动词；禁 rm/unlink（回收站 PowerShell 通道，SKILL.md §7）。
- **绝不伪造 symbolHash**（053 铁律：库无旗标符号退同名标签）。
- pytest：`.venv/Scripts/python.exe -m pytest ... --basetemp=.tmp_pt_178`（注意不是
  .tmp_pt_home，另一个代理可能占着它）。
- tests/fixtures/ 既有夹具不碰；evidence/ 不碰。
- 真机只碰 `test`/`test2` 工程窗口，且本任务**只读**（libprobe 类探针可以，写不行）；
  动手前 `bridge status` + `doc.list` 对身份（R1-R3）。
- 变异验证 ≥2（cp 备份 + sha256 还原）。

## 验收

- 三个问题全部有证据答案；分域地旗 profile 入库；多域场景（flyback 的 PGND/SEC_GND 页）
  出图时两族各挂各旗（场景测试或预览 SVG 证明）。
- 受影响测试文件全绿 + 一次全量（基线以当时 HEAD 为准，177 在途，预计 5402+ passed）。
- 证据落 `outputs/178/evidence.md`（append + grep -c 防双写）。

## 交卷格式

三问答案（带证据出处）/ 改动文件清单 / 测试计数 / 哈希申报记录 / 遗留风险。不贴大段代码。

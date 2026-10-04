# 108 / 阻值尺寸码孪生开闸批（B3 遗留②，岳 2026-10-04 裁「开」）

背景：B3（102，commit 59f9650）给 `_MID_LETTER_KINDS` 加了第三列「值字段里一段本身就是
封装尺寸码的数字 run 是否读作尾数」——容值 True / 阻值 False。阻值侧当时**注册未开**：
`160R`=160Ω（R 尾缀=欧姆，与一直可读的 `47R`=47Ω 同款拼法）被 `160` 尺寸码剥光拒读，
18 条（8 公制 + 10 英制 × `R`）在 `tests/test_102_b3_value_sizecodes.py` 里钉成拒读防漂移。
岳 2026-10-04 裁定：**开**——同一个 bug 不修一半。

## 实测事实（主代理亲测，本任务不必重测）

- 受影响的**只有 R 字母**：`160k`/`0805K`/`105K` 今天读得出（k/M 走后缀语法护着，
  审计原话"Resistance is shielded by an earlier plain-number grammar"说的就是它）。
- 货架侧无刺痛：电阻 `quantity_slug('160R')='160'`（裸数字，不受影响）。
- 读数口径与 B3 同：`160R`→160.0、`0805R`→805.0（前导 0 是尺寸拼法补位，与 `805R` 同值）、
  `01005R`→1005.0。

## 改动面（小批，但三处文字必须同步，不许留旧话）

1. `src/boardwise/core/values.py`：`_MID_LETTER_KINDS` 阻值列 `False`→`True`；
   周边注释/docstring 里「阻值孪生仍拒读、注册待裁」的段落按新事实改写（含
   `_mid_letter_farads` 附近与 `_MID_LETTER_KINDS` 表格上方那两段，凡提到
   `160R` 拒读/registered for a ruling 的一律改掉）。
2. `tests/test_102_b3_value_sizecodes.py`：
   `test_the_resistance_twin_of_the_same_shape_is_registered_not_opened` 重写为
   **可读+读数断言**（18 条逐条：值=字面值；`0805R`==`805R` 同值钉子保留语义）。
   文件里其它钉子（`12345n` 长 run 拒、`0u1` 拒、MPN 侧不动）一条不许动。
3. `.kimi-code/skills/boardwise/SKILL.md` 坑 34：那句「阻值侧同款拼法（'160R' = 160Ω）
   仍然不读——同一条待裁线」按 108 落地改写（108 起读；出处注明）。
4. 新测试文件不必新建——直接改 102 的测试文件 + 如需新增放
   `tests/test_108_resistance_sizecodes.py`（自选，说明理由）。

## 纪律

- 语料对账（087/102 机具可重放）：新增可读**恰好 18 条**（阻值侧 0→18，总量 54→72）；
  容值侧/MPN 侧/规则迁移/同行文字全 0；多出任何一条=停下报告。
- 21 板规则输出对账：若有板子在 Value 字段写着 `160R` 类拼写，规则从此看见该件——
  逐板申报（哪些规则、从什么变成什么、为什么这是修复）；无则 0 移动申报。
- 五族预览 83 张逐字节。
- pytest 必带 `--basetemp=.tmp_pt_home`，全量亲跑，基线 **3439 passed**。
  **跑全量期间不许改任何源码/测试文件。**
- 变异 ≥2 组（cp+sha256）：M1 阻值列退回 False→18 条红测回红；M2 自选（如把 R 也走
  后缀语法的反向改动→必须被语料或测试抓住）。
- 不碰 git、不写 PROGRESS、**删除一律回收站（PowerShell SendToRecycleBin，临时产物无例外）**、
  不碰 `tests/fixtures/` 既有夹具与 outputs 禁地。
- 交付 `outputs/108/`：SUMMARY（红→修→绿、18 条读数表、语料对账、变异、零移动、全量行）。
- 拿不准写遗留，别扩大改动面。

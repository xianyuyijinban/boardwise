# 086 — #46 重命名收敛到一处 + console 丢弃提示补第三计数器

两件事，主题同为「同一判据两份口径」收敛。纯 Python 批：**不碰 connector TS、不碰 dsh-plugin、不碰真机**。
岳已裁：#46 按 issue 建议修；console 提示补第三计数器（085 边界②）。

## A. #46：两份 reconcile 收敛到一处（**行为零变化是本批红线**）

080 批 3 已把碰撞行为对齐（两处都是「碰撞即放弃」，docstring 互指 "held to one behaviour until they are merged"）。本批做合并那半步。

现状（主代理已逐行核实）：

- `core/compare.py:366-451` `reconcile_names(candidate, golden, *, skipped=None)`：无 pin 翻译；**无 golden 名守卫**；不可变应用（deepcopy 出新 DesignModel 返回）。:446 的 `setdefault` 是文档化的死路径防御，**原样保留**。
- `engines/draw.py:587-678` `_reconcile_derived_names(golden, candidate, pin_maps=None, *, skipped=None)`：pin_maps 翻译层（placed→golden 编号，:616-623）；**有** `if name in golden.nets: continue` 守卫（:635-636）；原地变异应用（改 pin.net + 网表 re-key，返回重命名数）。

设计（已定，执行者不得改）：

1. `core/compare.py` 新增 `plan_membership_renames(golden_nets, candidate_nets, *, translate=None, respect_golden_names=False, skipped=None) -> dict[str, str]`——唯一的决策逻辑落点：成员集匹配、`taken` 防双占、碰撞放弃（含排列环规则）、`skipped` 措辞的唯一来源（两条消息逐字沿用现有文本）。docstring 写清两个 policy 旋钮的语义及各自调用方。
2. `reconcile_names` 变薄壳：`translate=None`、`respect_golden_names=False`（保持现状——校准以成员集为准，不守卫），应用层（deepcopy）原样留在 compare.py。
3. draw 的 `_reconcile_derived_names` 变薄壳：`translate` 由 pin_maps 构建（现有 :616-623 那段移入壳内）、`respect_golden_names=True`（保持现状），原地应用层原样留在 draw.py。函数名与签名不变（内部调用方不动）。
4. 两边 docstring 收敛为指向 `plan_membership_renames`，"held to one behaviour until they are merged" 改为已实现态（一处决策，两处应用）。

**policy 差异显式化而非消除**：compare 不补守卫、draw 不删守卫——是否统一行为是另一个议题，不在本批。

## B. console 丢弃提示补第三计数器（085 边界②）

- `cli.py:199` `_parse_drop_note` 加第三参 `instances_without_designator`（末位），新增子句与既有两条同族同风格（English console；顺序 pins → symbol → designator；措辞建议 "N component(s) dropped during parse (no usable designator)"，钉进精确串测试）。
- docstring（:200-212）"The two facts" → three，把第三种语义写透（整颗器件从模型消失）。
- 唯一调用点 `cli.py:2685` 传 `parse_stats.instances_without_designator`；:2683-2684 注释 "one pair of numbers" 对齐成三个。

## 测试

- A：`tests/test_080_reconcile_names.py` 现有钉子（碰撞放弃/排列环/守卫差异/签名兼容）**必须原样全绿**。另给 `plan_membership_renames` 加单元测试：translate 路径、respect_golden_names 两态、两种碰撞形状（双占同一目标 / 目标被保留网占用）、排列环、skipped 措辞同源（两个壳传同一个 list 得到逐字相同的消息）。
- B：`tests/test_020_parse_drops.py`（:249-292 精确串断言）更新到三参签名 + 新增「仅 designator 非零也出提示」钉子（原来静默——67 颗器件的板 console 也该说话了）。既有零语义（`"0 "` 不出现、全零返回 ""）不动。
- agent 自跑：`.venv/Scripts/python.exe -m pytest tests/test_080_reconcile_names.py tests/test_020_parse_drops.py -q --basetemp=.tmp_pt_home_agent086` 全绿（**必须用这个 basetemp**，`.tmp_pt_home` 主代理全量专用）。

## 边界（不做）

- `compare.py:446` 的 `setdefault` 死路径防御与注释不动。
- 不统一 policy 行为（见 A④）。
- `git status` 只应见：core/compare.py、engines/draw.py、cli.py、tests/test_080_reconcile_names.py、tests/test_020_parse_drops.py、tasks/086-reconcile-convergence.md。
- **不 commit、不 push、不写 PROGRESS.md**（主代理收口）。若既有测试变红，读懂意图先报告再动手对齐。

# 536 — 岛群→子岛：schema、plan 身份与 hard 校验

- 立项：2026-10-24
- 路线契约：`docs/drawing-archipelago-route.md`
- 最小例子：`docs/examples/archipelago_min/`
- 前批可执行契约：`tests/test_archipelago_contract.py`

## 本批边界

只做三件事：

1. **schema**：`LayoutIsland` 加性增加 `group` / `owner` / `kind` / `side`，显式进入
   archipelago 模式；禁止同一规格新旧混写。结构 hard 校验覆盖唯一 module 归属、
   island ⊆ module、子岛无重复并集、每群一个核心岛、module.core/owner 在核心岛。
2. **网表 hard 校验**：在 draw compile 的前置失败检查中，以 CircuitSpec 验证 CircuitSpec
   器件覆盖、卫星与 owner 的共享网，以及 decoupling/bulk 的 signal 禁止和共享 power 网。
3. **plan 身份**：archipelago 编译结果中的每个 LayoutPart 以机器可读字段携带
   group/island；序列化 round-trip 后可与 presentation 做精确 partition 回验。
   禁止以 notes 或坐标推断身份。普通 pagecompiler 不携带 islands，本批必须让它
   明确拒绝 archipelago；多群直接 compile 也因组装配器未实现而拒绝，不得扁平化。

## 兼容裁定

- 未声明新字段的既有 presentation 保持原语义、原字节和原 digest；不 bump specVersion。
- 旧 LayoutPlan 不增加序列化键，读取与 digest 不变；只有 archipelago 结果写入岛身份。
- 既有 `draw islands propose/apply` 对 archipelago 输入继续拒绝；本批不做自动语义分组。
- `side` 省略表示未声明岛级偏好；不写 `auto`。既有 userLocks 仍是精确锁。
- 本批只改必要文件。工作树已有的 534 / 绘图引擎修改不清理、不回滚、不接手续做。

## 明确不做

- 不做子岛独立编译器、核心+卫星组内装配器、岛群页级 pack 或生成边界。
- 不迁移 CH343/534，不恢复 534 的任何算法轮次。
- 不操作 bridge / canvas / 真机工程，不运行全量 pytest，不做 git 写操作。
- 通用最小例没有真实 library profile，本批不声称它可以 draw compile 或落图。

## 完成定义

- 新 schema 能读取最小 presentation 草案；结构/网表违规在几何搜索前 hard 拒绝。
- archipelago LayoutPart 身份可序列化、读取并与声明划分精确核对；缺失/错配/重复均拒绝。
- 前批测试改用生产校验器，不再维护第二套参考实现。
- 旧 spec / 旧 plan 的序列化兼容有聚焦回归证明。
- 聚焦测试通过，并记录实际命令与结果；A 层通过不冒充 B/C 绘制验收。

## 验证范围

使用 `.venv/Scripts/python.exe`，每个 pytest 命令带独立
`--basetemp=C:\tmp_pt_536_<轮次>`；只跑本批新增/迁移测试和受影响的 islands、
presentation、layoutplan 聚焦回归。需要并行时只允许 `-n 4 --dist loadfile`，本批默认单进程。

## TDD 记录

- 红阶段：`tests/test_536_archipelago_schema.py`，23 个参数化用例，
  **5 failed / 7 passed / 11 errors**。失败点包括新 schema 键未知、缺少
  `is_archipelago` / `IslandBlock.group` / `core.archipelago`；自动提案器拒绝等兼容用例已通过。
- 红测只写测试和示例，生产文件尚未修改；随后才开始 islands/presentationspec 实现。
- 早期 page apply 另补一条单独红测：`1 failed / 23 deselected`，证明旧代码会走到
  `_open_cli`；接入后同测通过，且不是 stale-source 拒绝造成的假阳性。

## 阶段验证记录

以下均为单进程、独立 basetemp 的聚焦结果，不是全量 pytest；各组测试文件有重叠，**不把数字相加**：

- 生产 schema / plan / core / engine / apply 各阶段小集：**7 / 5 / 6 / 3 / 3 passed**。
- 首次全绿 `tests/test_536_archipelago_schema.py` + `tests/test_archipelago_contract.py`：
  **44 passed in 0.30s**（`C:\tmp_pt_536_contract_final`）；core 复核补 9 个边界用例后为
  **53 passed**；engine 复核再补路径/身份用例后，最终为 **59 passed in 1.28s**
  （`C:\tmp_pt_536_all_final2`）。最终旧岛页/proposal 联合回归 **59 passed in 9.62s**
  （`C:\tmp_pt_536_legacy_final2`）。
- 主代理旧兼容回归：islands/plan **29 passed**；岛页 **9 passed**；proposal **50 passed**；
  `test_053a_specs.py` **38 passed**；岛名兼容 **1 passed**。
- 实现棒附加回归：编译相关七文件 **192 passed / 1 skipped**；apply 相关两组分别
  **86 passed / 1 skipped**、**112 passed**。
- 一次组合回归在 55 passed 后出现 4 个 basetemp `WinError 5`；改新目录分文件重跑得
  **9 passed / 50 passed**，确认不是断言失败或实现回归。
- `git diff --check`：无空白错误。未运行 bridge、canvas、真机或全量测试。

## 独立复核与修正

- **core 复核：无 blocker，7 项边界意见。** 已修复 legacy 端口推导对未归属成员/整网未触及岛的处理、
  半盖章 arch spec 的 dump 拒绝、共享结构校验遗漏保留 id `all`。补 missing/duplicate plan、
  bulk、circuit 多件等 9 个用例。修复后原 44 项仍全绿，相邻岛回归另得 **156 passed**。
- 两项明确保留并以文档/测试锁定：核心岛有多件时 owner 可指向实际服务的另一核心件；
  archipelago 的 group/island 计入 geometry digest，身份变化必须使旧预览/去重失效。
- **engine/CLI 复核：无 blocker，发现单岛死路与 stamping 边界。** 单岛 CH340 强走 island path
  实测为 S-11 10/23 且另有 hard violations，因此没有调布局或放宽门槛；最终撤销路径切换，
  改为 `_build_one_variant` 保留普通布局、仅写入唯一声明岛并在 grade 前回验。多岛仍走
  island path。`IslandBlock.plan` 与 `PackedPage.plan` 共用 stamping helper，已有冲突身份 hard
  拒绝。真实 CH340 单岛、LDO core+decoupling 两岛 compile→ChangePlan 均已通过。窄复查确认
  三项关闭；另将 stamping 冲突从 ValueError 统一转成编译 refusal，并以 fake-page 用例覆盖。
- 本批仍不进入子岛独立编译器、组内装配、多群页级 pack、迁移或真机。

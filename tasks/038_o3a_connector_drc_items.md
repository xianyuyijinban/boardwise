# 任务书：V4 O3a connector 逐条 ERC 对象归一化（2026-10-31）

> 总计划 `tasks/038_v4_live_gaps.md`。connector 独立批，先不改 Python、不热更。

## 实测根因

V4.1.93 `sch_Drc.check` 返回 519 个 `{type:"warn",rule,primitives:[...]}`，没有 `count`。
旧 `schDrcCheck` 只认 count，于是全部 unparsed、total=0、passed=true。两页对象/hash完全相同，
host-wide 去重在 Python 既有层完成。

## 完成条件

1. `schDrcCheck` 对 V3 聚合 `{type,count}` 保持原计数/形状；对 V4 逐条对象，若含合法
   severity（fatalError/error/warn）且没有数值 count，按**每项 count=1** 规范化，保留
   rule/primitives/net 等原始字段。不要把有 count 的项再拆成多条。
2. `byType/total/passed/unparsed` 由规范化后的项计算：本样本应 total=519、byType.warn=519、
   passed=false、unparsed=0。未知对象/字符串/缺 type 仍 unparsed，不能变成 0 或真通过；
   有任何 unparsed 时 `passed=null`（unknown），不是 true/false 冒充确定。
3. 增加可选 `entryShape`（aggregate/per-item）与 `items`（仅 per-item 原始条目）以保留证据；
   既有 mode/counts/entries/source/page 键不删。响应文档同步。
4. 不新增动作、不改 daemon/CLI/schema/规则，不改版本号、不热更。

## 允许文件域

- `connector/src/actions.ts`
- `connector/tests/actions025.test.mjs`（若实际DRC测试在别文件，先定位并说明）
- `docs/bridge.md`
- 新增 `outputs/review/v4-o3a-connector-drc.md`；探针 `.tmp_038_o3a/`

禁止 Python/其他connector动作/schema/fixtures/git写/真机/热更。

## 验证

1. V3聚合兼容；V4逐条warn/error/fatalError计数与字段保留；混合count项不重复计；
   未知entry/字符串/缺type -> unparsed且passed=null；空数组 -> total0/passed=true。
2. `cd connector && npm test && npm run typecheck` 必须实跑；新测试至少覆盖上述四类。
3. 至少两处变异：V4项不规范化；unparsed时仍passed=true。cp备份→目标红→cp恢复→SHA一致。
4. 交真实计数、响应示例（匿名合成）、变异哈希和未覆盖项。最多40步或30分钟。

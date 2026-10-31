# 任务书：V4 在线只读验收（2026-10-31）

> 岳确认立创 EDA 已升 V4，并授权开始上一步说明的只读检查。不得把本授权扩大为设计写入、
> connector 热更、daemon revoke、真实工程操作或发布。

## 阶段 A：环境与身份

1. 用仓库当前代码 `.venv/Scripts/python.exe -m boardwise.cli` 执行 `bridge status`，确认 daemon
   是否自动拉起、在线窗口、工程名/页/windowKey、connector 版本。不得手动改 ACL/安装/更新。
2. `boardwise doctor` 只读环境检查，记录真实通过/失败/skip 与 V4 宿主版本；分别报 daemon、
   connector、引擎版本，不合并成“兼容”。
3. 用 `doc.list` / `document.current` / `sys.identity`（按可用性）复核焦点。**只有焦点工程名
   逐字为 `test` 或 `test2`**，才允许进入该工程的 probe/checkup；若焦点是其他工程，仅报告身份，
   不读取其页面内容、不导出、不 checkup。

## 阶段 B：授权后的只读检查（须满足 A 的身份）

- `sys.probe` 关键动作：`doc.list` 依赖枚举、`sys_FileManager.getProjectFile/getDocumentFile`、
  netlist/geometry、DRC、render、readback；只调用白名单只读动作，不猜私有 API。
- `checkup --project test|test2 --out .tmp_v4_online/checkup`：核对 source.tier、模型非空、
  归档 hash、PCB 通道、conclusion/evidence、focusRestore。exit 1/3 不等于工具失败，需读原因。
- 如需 review-evidence，只读采集，焦点复位；archive/live 分记，空模型/截断 stdout 不作证据。

## 边界与证据

- 禁止：一切设计写动作、review.mark、delete/set/modify/place、doc.new/delete、save、export.fab、
  update-connector、revoke、热更、重启编辑器、git写、issue/Release、真实工程内容复制入库。
- 日志与探针在 `.tmp_v4_online/`；汇总证据 `outputs/review/v4-online-acceptance.md`。
- 公开描述只用窗口代号/test/test2，不写真实工程内容或用户 uuid。缺目标就停（R3），不替代。
- 最多40步或30分钟；身份不符、daemon/connector异常或需要写操作才能继续时停止交主代理。

## 岳的后续授权（同日）

- 允许结束此前测试遗留的 PID 17404，让生产 home 的 daemon 自动重拉并重新配对；
  不包含 connector 更新或编辑器重启。
- 明确允许对当前 `New Project_2026-10-31_01-09-06` 做**只读** probe/checkup，
  不再要求切到 test/test2；仍禁止一切设计写入。先核 PID/进程身份，若进程已变化不得误杀。
- 当前有两个同工程窗口：优先使用有活动文档的 instance；instance 失效时重新枚举，不猜。

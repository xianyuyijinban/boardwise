# 111b — sys.log_read 动作（坑 27：ERC 逐条文本从日志通道捞回）

**来源**：`tasks/111-addendum.md` 第 4 条。宿主 ERC 的逐条文本（岳面板实测
22 条 warn 全文，2026-10-04 18:33）写在 sys_Log 面板；`sch.drc_check` 的
verbose 应答只有聚合计数（025 §0 实测）。类型包
`connector/node_modules/@jlceda/pro-api-types/index.d.ts:17954-18022`
声明了 `SYS_Log`：`add` / `clear` / `export` / **`sort(types?) =>
Promise<ISYS_LogLine[]>`** / **`find(message, types?) =>
Promise<ISYS_LogLine[]>`**，`ISYS_LogLine = {timestamp:number, type:
ESYS_LogType, message:string}`，`ESYS_LogType` 字符串枚举
（info/warn/error/fatalError/find/replace/openProject）。

**本棒只交付代码与单测，不碰真机**（live 验证主代理自己做）：
不 update-connector、不重启 daemon、不发 bridge 调用、不动 git。

## 要做的

### 1. connector 新动作 `sys.log_read`（read）

`connector/src/actions.ts`，范式照抄 `schDrcCheck`（:6775 起）与
`sysConnectorStatus`（:7201）：

- 调 `eda.sys_Log.sort(types)`（`requireFn` + `raceHostCall` 老两件，
  超时常量复用现有档位）。`sys_Log` 缺席（老宿主）→ 显式
  NOT_IMPLEMENTED 风格报错，别装空日志。
- params：`types`（字符串或数组，枚举值校验，缺省 = 全部）、
  `since`（number，ms epoch，过滤 `timestamp >= since`）、
  `pattern`（字符串，大小写不敏感子串过滤）、`limit`（默认 200，上限
  5000，超过截断并如实报 truncated）、`maxChars`（防护总字节）。
- 返回：`{source:'sys_Log.sort', lines:[{timestamp,type,message}],
  count, total, truncated?, types?, since?, elapsedMs, note?}`。
  `total` = 过滤前条数。lines 原样 verbatim，不许改写 message。
- **不调** `export`（触发保存对话框）、**不调** `clear`（写操作）。
  `find` 本棒不用（sort+客户端 pattern 覆盖其能力）——在代码注释里
  写一句为什么。
- 注册：actions.ts 两个注册表（`:7267` 附近的动作表与 `:7279` 附近的
  bind 表——自己确认两处各自的角色，保持一致）。
- 版本号：connector `package.json` 与 `extension.json` 0.4.27 → **0.4.28**。

### 2. daemon 目录 `src/boardwise/bridge/protocol.py`

照 `sch.drc_check`（:386）的格式追加 `sys.log_read` 条目，risk="read"，
summary 里写清存在理由：「sch_Drc.check 的 verbose 只有计数，逐条文本
在 sys_Log（025 §0 实测计数无细节；岳的面板 2026-10-04 证明文本存在）」。
注意 daemon 目录是 load-time 常量——在 returns 文档里如实写。

### 3. 测试

- connector：`connector/tests/` 新增 `syslog.test.mjs`（或并入最相近的
  现有文件，看哪个动作的单测范式最像就跟哪个）：fake eda 宿主喂
  sys_Log.sort 应答，钉 types/since/pattern/limit 过滤、缺席报错、
  截断如实报、message verbatim。跑 `npm test` + `npm run typecheck`。
- Python：若存在 protocol.py 目录与 connector 注册表的同步测试，跟着
  补；没有就不用新建。跑 protocol 相关 pytest 子集确认绿（**不跑全量**，
  主代理统一跑）。

### 4. 文档

- `docs/bridge.md` 动作表加 `sys.log_read` 行（格式照 :512 `sch.drc_check`
  那行），并修订 `sch.drc_check` 行里「the per-item detail goes to the
  bottom panel … has no read interface」一句——sys_Log.sort 就是这个
  读接口的候选（**live 未验，措辞用「候选/待验」**，不许写成已证实）。
- `PROGRESS.md` **不动**（主代理统一落账）。
- `tasks/111-addendum.md` **不动**（主代理标记）。

## 回报

文件清单 + npm test/typecheck 数字 + Python 子集结果 + 给主代理 live
验证用的建议步骤（先 sort 全量看 ERC 文本在不在，再 drc_check 前后
diff）。如实申报没做到的。

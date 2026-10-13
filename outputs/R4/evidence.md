# R4 证据（真·热更 —— 实验先行）

开发机**没有立创 EDA Pro**，阶段一的五个真机实验**一个都没跑**，所以也没有进入阶段二（任务书：不过实验不写代码）。本 PR 交三样东西：

1. **实验 ①② 的仪器**：`sys.probe {realm: true}`（connector）。
   - 只读；只执行 connector 里写死的常量代码（三种方式：间接 `eval`、`new Function`、`import(data:…)`），每种都应答出 `6 * 7 = 42`；
   - 从不执行参数里的任何东西（`realm` 只接受 `true`，其他值一律拒绝，测试钉住了）；
   - 同时读出阶段二要依赖的环境事实：`crypto.subtle`（经 `random.ts` 读取，遵守源码守卫）、`WebSocket`、`fetch` 等。
   - 在 Node 环境里实测三种方式都返回 42。编辑器里会怎样，**未测**。
2. **实验 ③④ 的 runbook**（`runbook.md`）。实验 ④ 缺一个「只写不 reload」的仪器，要么给 `sys.self_update` 加 `reload:false`，要么接受仪器不可得；**待裁决**。
3. **阶段二安全设计草案**（`design-proposal.md`），只有设计，待评审。核心建议是**在 stub 里用内置的发布者公钥验签**，与任务书写的「daemon 侧持有公钥 / hash 白名单」不同，理由写在草案 §4。

## 改动
- `connector/src/actions.ts`：`realmProbe` 和 `sys.probe` 的 `realm` 分支；从 `random.ts` 引入 `ambientRandomHost` / `describeRandomHost`。
- `src/boardwise/bridge/protocol.py`：`sys.probe` 的 params 加上 `realm`，returns 补充说明。
- `docs/bridge.md` §4：`sys.probe` 行补上 realm 模式。
- `connector/tests/realm-probe.test.mjs`：4 条。

## 测试
- connector `npm test` 483 pass / 0 fail（基线 479，新增 4）；`npm run typecheck` 通过。
- pytest 全量见 PR 描述。

## 变异验证（cp 备份 + sha256 还原）
| 变异 | 结果 |
|---|---|
| M1 `realm` 接受任意值 | CAUGHT |
| M2 抛错的环境不再被捕获（探针直接崩） | CAUGHT |
| M3 去掉哨兵比对（任何答案都算 ok） | 第一轮**存活**；补了「代码跑了但答非 42」的测试后 CAUGHT |

## 过程记录
第一版直接读了 `globalThis.crypto`，被源码守卫 `source-guard.test.mjs` 拦下（只有 `random.ts` 可以碰全局 crypto）。改为经由 `random.ts` 读取，没有绕过守卫。

# 106 / B6 connector 侧批（issue #57 之 #12 #13 #18 + 安全注记，Python 侧收官后的 TS/daemon 批）

来源：外部审计 `.tmp_bug_report.md` "## 12." "## 13." "## 18." 与 "# Security note" 四节。
跟踪 issue：GitHub #57。每条先红测复现再修。全部离线（connector 测试用桩 socket，
daemon 测试用既有测试通道；**不起真 bridge、不碰编辑器**）。

## #12 握手拒绝帧被吞 — `connector/src/transport.ts:623-637` vs `src/boardwise/bridge/daemon.py:1697-1705`

daemon 真实发出 `{"id": null, "ok": false, "error": {"code": "UNAUTHENTICATED", …}}`；
transport 只处理 `id === 'hello'` 然后 `return`——**其余全吞**。UNAUTHENTICATED /
VERSION_MISMATCH / BAD_REQUEST 落地即丢 ⇒ 卡在 handshaking 直到 3 次心跳（15s），
以**错误原因**重连、无限循环；`status.paired` 永远不变 false ⇒ About 里那句
「REFUSED — run `boardwise bridge revoke`」**永远不出现**；`lastError` 写成
"heartbeat timed out" 把矛头指向 daemon 而非配对。触发面很普通：窗口连着时
`boardwise bridge revoke`（Re-pair 菜单恰恰这么教）。既有测试
`transport.test.mjs:129` 喂的是 `{id:'hello', ok:false}`——**daemon 从不产生的形状**，
整条分支是不可达代码。
修：识别 `id === null` 的拒绝帧——paired=false、拒绝原因进 lastError/About 该出现的那句
真的出现、**停止以心跳超时为由重连**（重连与否按码表语义：UNAUTHENTICATED/VERSION_MISMATCH
是「人不动就好不了」的，BAD_REQUEST 同理别装成网络抖）。红测喂 daemon 真实形状。

## #13 排在死窗口锁后的写答 INTERNAL 而非 DISCONNECTED — `daemon.py:1295-1296, :1418-1420, :1683-1690`

`handle_request` 路由时查了 `is_open()`，但写操作等 `window.write_lock` **不再查活、
无超时**；窗口死在排队期间 ⇒ 排队写拿到锁、`_forward` 的 `websocket.send` 抛
`ConnectionClosed`（不是 BridgeError/TimeoutError）⇒ 被 `_on_frame` 的裸
`except Exception` 吞成 INTERNAL。这**毁掉了仓库称为 load-bearing 的区分**：
DISCONNECTED=「没人会知道编辑器动没动过——**回读**」；INTERNAL 让调用方当成安全的
硬失败（半画页报未动正是 DISCONNECTED 要防的）。既有测试只盖在飞写、没盖排队写。
修：拿到写锁后**重查活**（死了→DISCONNECTED），且/或把 `ConnectionClosed` 在写路径上
翻成 DISCONNECTED 的 BridgeError——**别在别处翻**（读路径的语义不一样，拿不准写遗留）。
红测=审计的 A(in-flight)/B(queued) 两帧形状。

## #18 重叠 connect 路径孤儿化 Transport，心跳永不死 — `connector/src/index.ts:863-876, :798-830, :1034/:1202; transport.ts:456/:585`

`transport?.stop()` → `await connectableConfig()` → `transport = buildTransport(...)`
跨 await 重装模块级槽位**无守卫**；`runReconnect` 无视 `claimConnectionAttempt()` 的
返回值（:866）。被覆盖的 Transport 不可达但握着 socket+setInterval；每个实例从 1 编号，
两个都注册**同一个 `boardwise-1`**。审计对着发布 bundle 实测：两次 `reconnect()` →
`register(): ['boardwise-1','boardwise-1']`、`close(): []`，deactivate 后孤儿 11s 后
还在 ping。`docs/bridge.md` §7「a stopped transport sends nothing, ever」是假的。
修：跨 await 的槽位重装加守卫（认 claim 的结果/被覆盖者必须真正 stop 并 close），
孤儿不再有心跳；bridge.md §7 那句话若仍不成立就按事实改文案（**声明钉纪律**：文案与
行为必须机器可验地一致）。

## 安全注记（复合缺口，两条各自记录在案的 deferral 叠出来的）— `daemon.py:548-559, :872-891`

`check_origin` 恒 True（已知 TODO）+ 无 connector 附着时一律放行 re-pair 例外 ⇒
`bridge start` 后到编辑器附着前、以及所有 EDA 窗口关闭期间，**任何 http:// 页面**都能
开 `ws://127.0.0.1:61190/eda` 存下自己的 token、把真 connector 锁在 UNAUTHENTICATED 外
（#12 再把锁死伪装成 "heartbeat timed out"）。威胁模型=用户浏览器里开着的恶意页面
（浏览器发 ws 必带 Origin）。
修（按审计建议的小修）：re-pair 例外放行前要求 **Origin 缺失或非 http(s)**
（浏览器页面没有不发 Origin 的；curl 类非浏览器攻击者本就能走完整配对流，不在此威胁
模型内——注释里把这句话写清楚）。红测=带 `Origin: http://evil.example` 的握手在
空窗期**不再**拿到配对；无 Origin 的照常。

## 纪律

- 测试：Python 侧进 `tests/test_106_b6_connector_side.py`（或就近既有 bridge 测试文件，
  说明理由）；TS 侧进 `connector/tests/` 既有文件族。
- pytest 必带 `--basetemp=.tmp_pt_home`，全量亲跑，基线 **3413 passed**；
  connector `npm test`（基线 **419 pass**）+ `npx tsc --noEmit`；dsh-plugin 三线。
  **跑全量期间不许改任何源码/测试文件。**
- 变异 ≥3 组（cp+sha256）：M1 吞回 #12 的 null-id 处理→红；M2 摘掉 #13 的重查活→红；
  M3 摘掉 #18 的守卫→红（孤儿再心跳）；M4 摘掉安全注记的 Origin 闸→红（四选三即可，
  但 #12/#13 必须各有）。
- 零移动：本批是协议/行为层——21 板与语料不相关，但 bridge 测试套件全绿 +
  五族预览 83 张照跑；daemon 协议变化（排队写 INTERNAL→DISCONNECTED）对 draw 家族
  是**有意的语义修正**（DISCONNECTED 触发回读），把受影响的既有测试逐条申报。
- **connector 版本**：改完按仓库惯例 bump patch 版（查 `connector/package.json` 与上次
  发布 0.4.25 以来的版本史；release 上传由主代理做，你只 bump+built 产物不落 git）。
- 不碰 git、不写 PROGRESS、删除一律回收站、不碰禁地。
- 交付 `outputs/106/`：SUMMARY（每条红→修→绿、变异、受影响既有测试申报、全量行）。
- 拿不准写遗留，别扩大改动面。

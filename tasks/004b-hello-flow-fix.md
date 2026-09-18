# 任务 004b：握手流程修复——daemon 先开口 + 连接器消息驱动

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 前置阅读：`docs/bridge.md`、`connector/src/transport.ts`、`src/boardwise/bridge/daemon.py`。
> 背景：任务 004 已验收（154 测试绿），但真机验证失败，本任务是修复。

## 故障事实（已逐层证实，直接信任）

1. daemon 完全正常：用真 token 手工模拟 connector 角色，`hello`/`ping` 全部成功，审计正确。
2. 编辑器里扩展已安装、已启用、"允许外部交互"已勾选；菜单和 toast 工作（用户能看到 "boardwise: reconnecting to..."），证明 activate 运行了、config 读取正常。
3. 用户点 Reconnect 后，**netstat 里从未出现过编辑器到 61190 的任何 TCP 连接**，daemon 审计里也只有 CLI 的记录。

## 根因分析

对照**能在同一编辑器里正常工作的参考实现**（easyeda-agent 连接器，`C:\Users\xiangyu\Desktop\easyeda-agent-connector.eext` 内 `dist/index.js`）：

- 参考实现**从不依赖** `register` 的第 4 参数 `connectedCallFn`。它的 daemon 在 TCP 连接建立后**主动先发**一帧 `{type:"handshake"}`，连接器在 `onMessage` 里收到这帧才确认连接存活、再回注册帧——**连接检测是消息驱动的**。
- 我们的实现在 `onConnected`（即 `connectedCallFn`）里发 `hello`。如果该回调在此编辑器版本里不触发/时机不对，连接器永远沉默；且我们的日志只走 `console.log`（黑洞），失败完全不可见——与观测到的"全静默"完全吻合。

## 修改项

1. **daemon（`src/boardwise/bridge/daemon.py`）**：
   - 每个新 WS 连接建立后立即主动发一帧 **banner**（未认证、不含秘密；具体帧格式自定但要与现有信封风格一致，并写进 `docs/bridge.md` §3）
   - 审计原始连接打开/关闭事件；**5 秒未收到 hello 的连接主动关闭**并审计该超时
2. **connector（`connector/src/transport.ts`）**：
   - 连接检测改为**消息驱动**：未握手状态下收到任何入站帧 → 触发发送 `hello`（幂等，重复触发只发一次）；`connectedCallFn` 降级为提示性用途
   - 心跳在 `hello` 发出成功后启动（不再依赖 `onConnected`）
   - `onLog` 除 `console.log` 外**同时写入 `eda.sys_Log.add('[boardwise] ...')`**（try/catch 包裹）——参考实现就是这么做的，编辑器日志面板是用户唯一可见的诊断窗口
   - `scheduleReconnect` 的 reason 也要进 sys_Log
3. **测试**（现有 154 个测试保持绿）：
   - daemon：banner-on-connect、5s 未 hello 超时关闭、审计含原始连接事件
   - connector：不发 `onConnected`、仅注入一帧入站 banner，验证 `hello` 被发出；hello 幂等
4. **文档**：`docs/bridge.md` §3 增加 banner 帧说明；§13 真机清单加一条"编辑器日志面板应可见 `[boardwise]` 行（含 reconnect 原因）"
5. 修完重新打包 `.eext`（`connector/package.mjs`），版本号 bump 到 0.1.1

## 不许动的部分

token/握手语义、动作目录、CLI 退出码约定、既有测试断言（除直接相关的）。

## 验收

- 全部测试绿（Python + connector）
- 岳翔宇真机重试：重装 0.1.1 .eext → 完全重启编辑器 → Reconnect → `bridge status` 应显示 connected；若仍失败，编辑器日志面板的 `[boardwise]` 行必须能给出具体原因

---

## 验收记录（2026-09-13，Kimi）

状态：**ACCEPTED（桥 v0 全线真机打通，连接器定格 0.1.3）**。

004b 的 banner/消息驱动握手是**可见性修复**，不是零 TCP 的真因。真因：`eda` 是扩展宿主的上下文全局、不是 `globalThis` 的属性，旧 Transport 的 `globalThis.eda?.sys_WebSocket` 兜底永远命不中 → `register` 从未被调用。0.1.2 改为 `buildTransport` 显式注入 `socket: eda?.sys_WebSocket` + `source-guard.test.mjs` 源码守护。

真机验证链（岳翔宇确认 + 审计日志佐证）：

| 动作 | 结果 |
|---|---|
| `bridge status` | connected（`boardwise-connector/3.2.149.88089769`） |
| `sch.readback` | 35 组件返回；真实字段名 `primitiveId`；`name` 是未解析占位符 `={Manufacturer Part}` |
| `bridge screenshot` | PNG 正确（CH340G 完整原理图页） |
| `bridge highlight U1 --zoom` | **0.1.2 静默失败**：矩形标记误用 line/arc 字段 `startX/startY/endX/endY`（官方 `IDMT_IndicatorMarkerShape` 矩形是 `left/right/top/bottom`），编辑器返回成功但不渲染。0.1.3 修复后真机确认跳转+红框，随后 `--clear` 清除 |

教训入账：**"API 返回 true" 不等于 "画布上看得见"**。标注类动作的断言必须落到字段名，且最终要有一次真机肉眼确认；测试已加字段名回归守护。

最终测试基线：Python 127 passed；connector 41 passed（含 source-guard 与 banner 驱动握手）；`tsc --noEmit` 干净；产物 `boardwise-connector-0.1.3.eext`（8903 B，旧版已删）。

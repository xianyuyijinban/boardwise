# 任务 004c：TOFU 自动配对——干掉 Set token + Origin 取证 + 门面收口

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 前置阅读：`docs/bridge.md`（§3 握手、§10 已知限制）、`src/boardwise/bridge/daemon.py`、`connector/src/index.ts`、`connector/src/transport.ts`、`connector/src/config.ts`。
> 背景：桥 v0 已全线真机打通（004b 验收记录，连接器 0.1.3）。当前最大体验毒瘤：用户必须手动把 `~/.boardwise/token` 的 64 位 hex 粘进编辑器对话框（Set token）。参考实现（easyeda-agent 连接器）零配置自动连接，用户已明确以此为准绳。

## 威胁模型（先读这个再动手）

- daemon 只听 `127.0.0.1`，不暴露 LAN。要防的是：**本机其他进程 / 浏览器里的恶意网页**抢在真连接器之前配对或发动作。
- 不防：能读用户目录文件的恶意本地进程（那已经输了，token 文件本身就躺在这）。
- TOFU（Trust On First Use）在这个模型下是正确强度：首次配对信任，之后严格比对；撤销即重新配对。

## 修改项

### 1. daemon：连接器配对令牌（独立于 CLI token）

- 新文件路径 `~/.boardwise/connector-token`（与 CLI 用的 `~/.boardwise/token` **分开**，CLI 流程一字不动）。
- `hello` 鉴权分流：
  - `role=cli`：照旧比对 `~/.boardwise/token`。
  - `role=connector`：
    - `connector-token` 文件**不存在** → 接受 hello 里 connector 自带的 token，落盘为配对令牌，审计 `"action":"pairing"`（含 client 版本、token 指纹 = sha256 前 8 位，不落完整 token），daemon 控制台打印醒目一行：`boardwise bridge: paired new connector (fingerprint XXXXXXXX); if this was not you, run: boardwise bridge revoke`
    - 文件**存在** → 严格比对，不符照旧 `UNAUTHENTICATED` 拒绝。
  - connector 的 hello token 缺失/空：**不再直接拒**——按"文件不存在"分支处理视为配对请求时也必须带 token；空 token 一律拒绝并审计。（即：配对要求对方自证有随机源，空串不算。）
- 新 CLI 子命令 `boardwise bridge revoke`：删除 `connector-token` 并审计 `"action":"revoke"`。下次连接器 hello 自动重新配对，无需用户做任何事。
- `bridge status` 输出加一行：paired connector fingerprint（只显示指纹）。

### 2. connector：自生成 token，删 Set token

- 启动时从 `sys_Storage` 读 token；没有则用 `crypto.getRandomValues(new Uint8Array(32))` 生成 hex 并写入 `sys_Storage`，hello 照常带上。用户全程零操作。
- **删掉** `SetToken` 菜单项和 `showInputDialog` 流程（`index.ts` + `extension.json` 三个菜单组里的 `SetToken` 条目）。
- 新菜单项 `Re-pair on next connect`：清掉 `sys_Storage` 里的 token，提示用户重连（或自动 stop+connect）。
- 状态输出（About/状态日志）里 token 行改为显示指纹（前 8 位），永不显示完整 token。

### 3. Origin 头：先取证，后定规则（两步，不许跳步）

1. **本任务只做取证**：daemon 在每个 WS 握手时把 `Origin` / `User-Agent` 请求头（缺失记 `null`）写进审计的 `connect` 记录。然后在真机上用 0.2.0 连接器连一次、再用浏览器控制台对一个测试端口发一次 WS（可被拒），把两条审计记录贴进任务汇报。
2. **不定死任何 allowlist**。 editors 的 `sys_WebSocket` 是否带 Origin、带什么值，目前无证据。取证结果回来后在 004d 里定规则（预期：拒绝 `http://`/`https://` Origin，放行无 Origin 与扩展宿主的实际 Origin 值）。代码里留一个 `check_origin(headers)` 钩子函数，当前实现恒放行 + 记录，便于 004d 只改一处。

### 4. 门面收口（消灭 §10.10 盲区）

- `index.ts` 顶部唯一一处解析宿主 `eda` 全局，构造 `facade` 对象；`buildTransport` / `buildHandlers` / 菜单回调全部只经由 facade，不再出现第二处 bare `eda` 引用。
- `source-guard.test.mjs` 加一条：`src/` 下除 facade 定义文件外，禁止出现 `eda.` 直接引用（现有 globalThis 规则保留）。
- 目标：生产路径的"从编辑器解析 eda"只剩一行，其余全部可注入测试。

### 5. 打包与文档

- 版本 bump 到 **0.2.0**（行为变化：删菜单、配对流程），重新打 `.eext`。
- `docs/bridge.md`：§3 握手补配对分支时序；§13 真机清单删除 Set token 步骤、改为"首次连接自动配对"；§12 验证表补配对/revoke 行。

## 不许动的部分

CLI token 文件与 `role=cli` 鉴权语义；动作目录与信封格式；banner/心跳流程；既有测试断言（除直接相关的）。不引入新运行时依赖（websockets 仍是唯一）。代码/注释英文；不执行任何 git 命令；测试秒级、WS 用随机端口。

## 验收

- 新用户流程：**装插件 → 重启编辑器 → 自动连上**，全程无任何手工步骤（Set token 菜单已不存在）。
- 审计可见 `pairing` 记录与指纹；`bridge revoke` 后连接器自动重配；拿着旧/错 token 的连接器被 `UNAUTHENTICATED` 拒绝。
- 审计的 `connect` 记录含 Origin/User-Agent 取证字段（真机两条样本贴进汇报）。
- 全部测试绿（Python + connector，含配对/重配/拒绝/指纹不泄密的用例）+ `tsc --noEmit` 干净 + `boardwise-connector-0.2.0.eext` 产物。
- 真机回归：`status` / `screenshot` / `highlight --zoom` 三项仍过。

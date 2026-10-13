# R4 阶段一 runbook（真·热更：实验先行）

> 开发机**没有立创 EDA Pro**，下面五步一条都没跑过。本 PR 只交了实验 ①② 的**仪器**（`sys.probe {realm: true}`，只读，
> 只执行 connector 里写死的常量代码），以及 ③④ 的步骤。任何一步结果是「不行」就停下，如实写进 `outputs/R4/evidence.md`。
> 原始读数落 `outputs/R4/live/`。写操作只在 test 工程的窗口里做（R1：动手前先用 `doc.list` 对工程名）。

## 0. 前提

```bash
boardwise bridge status        # connector 必须是带 realm 模式的 bundle（本 PR 的构建）
boardwise bridge call --action doc.list --params '{}' --project test > outputs/R4/live/00_doc_list.json
```

## ① realm 能力探针 + ② `new Function` 执行字符串（一条命令同时出结果）

```bash
boardwise bridge call --action sys.probe --params '{"realm":true}' --project test > outputs/R4/live/01_realm.json
```

判读 `realm.kinds`（各全局对象的 `typeof`）和 `realm.execution`（三种执行方式各自 `{ok, value}` 或 `{ok:false, error}`）：

| 读数 | 含义 |
|---|---|
| `newFunction.ok: true` | 扩展环境能把字符串变成代码，**实验 ② 通过** |
| `newFunction.ok: false`，error 是 `EvalError`/CSP | 环境禁止动态执行。**停**：stub + 载荷方案不可行，放弃是合法结论 |
| `dynamicImportDataUrl.ok` | 能不能按「模块」形式载入载荷，决定载荷用模块还是函数体 |
| `kinds['crypto.subtle']` = `object` | 有 WebCrypto，阶段二可以在 stub 里做验签；不是 `object` 就需要另想验签办法（见设计草案 §3） |
| `kinds.fetch` | 侦察结论里 daemon 只有 WS、没有 HTTP，`fetch` 有没有都不影响传输方式。记录在案 |

## ③ 复现 165（写 ≠ 激活）

```bash
# 换一个可辨认的版本号构建，例如把 connector/extension.json 和 package.json 临时改成 0.5.12-r4a
cd connector && npm run build && cd ..
boardwise bridge update-connector --project test --yes > outputs/R4/live/03_update.txt   # 写入并 reload，默认会核对版本
boardwise bridge status > outputs/R4/live/03_status.txt
```

和 030/031 的正例对照：hello 上报的版本是不是新号。本机 0.4.29→0.5.11 两次都核对通过；165 是工作电脑上的孤例，这一步要把「写入后什么条件下能激活」的成立条件说清楚
（是否刚重启过、是否多窗口、IndexedDB 是否共享，见坑 22）。

## ④ 菜单点击、不 reload，能否激活新代码

**仪器缺口（待裁决）**：现有 `sys.self_update` 写完**一定 reload**（`self-update.ts` 的 `host.setTimeout(() => host.location.reload(), …)`），
没办法做到「只写、不 reload」。可选做法：

1. 给 `sys.self_update` 加一个 `reload: false` 参数（只跳过 setTimeout 那一行，其余不变）；这是 `dangerous` 级动作的行为变化，要主代理点头；
2. 不加参数，④ 记为「仪器不可得」，阶段二先只靠 reload 那条通道。

如果选 1，步骤是：
1. 构建 0.5.12-r4b，执行 `bridge call --action sys.self_update … reload:false`；
2. **不要** reload，在编辑器菜单点 `boardwise → About…`（侦察结论：每次点菜单，宿主都会重新求值 bundle）；
3. 执行 `bridge call --action sys.connector_status`，看答的是 r4a 还是 r4b；
4. 最后 reload 复原。

## ⑤ 门槛

只有 ①② 都通过（`newFunction.ok` 为真，且 `crypto.subtle` 可用或有替代验签办法）才进入阶段二；而且阶段二的安全设计（`design-proposal.md`）要先在 PR 里过审。

# 任务 004：桥 v0——read-mostly 连接器 + daemon

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 测试：`./.venv/Scripts/python -m pytest`（既有测试必须全绿）。
> 前置阅读：`docs/architecture.md`（已定稿的架构与阶段划分）、`docs/api-survey.md`（eda.* 命名空间侦察结论）、`src/boardwise/cli.py`。
> **开工顺序**：本任务与任务 002 都会触碰 `cli.py`——若 002 尚未验收合并，cli.py 的改动留到最后一步做，或等 002 落地后再开工。

## 目标

打通"AI harness ↔ 立创 EDA 画布"的桥，v0 只做**读侧 + 画布标注**，为 P2（编辑器内审查体验）铺路。不做任何写动作（放件/布线在本任务范围之外）。

## 形态

```
Claude Code / 人 → boardwise CLI → daemon (Python, WebSocket 服务端, 127.0.0.1)
                                        ↑ ws, JSON 协议
                              connector (.eext, TypeScript, 跑在 EasyEDA 内)
```

## 交付物

1. **`connector/`**（TypeScript，esbuild 打包成可侧载的 .eext）：
   - 用官方 `@jlceda/pro-api-types`（npm，Apache-2.0）做类型约束；可参考官方 pro-api-sdk 的插件脚手架
   - 启动后连接 `ws://127.0.0.1:61190`（端口可配，env `BOARDWISE_PORT`），握手带 token（token 文件在 `~/.boardwise/`），断线自愈重连
   - 实现的 action（全部只读或标注类）：`ping`、`document.current`（当前工程/文档/类型）、`sch.readback` 与 `pcb.readback`（器件 + 图元 getAll，子集即可）、`export.screenshot`（原生导图 PNG）、`canvas.highlight`（按 uuid 高亮/标记图元——先查类型包里的 `dmt_IndicatorMarkerShape` 或等效 API，没有就用可行替代并记录）
2. **`src/boardwise/bridge/`**（Python）：
   - `protocol.py`：消息信封 `{id, action, params}` / 响应 `{id, ok, data|error}`，typed action 目录（`--help` 可自描述）
   - `daemon.py`：WS 服务端（**允许引入 `websockets` 依赖——项目第一个运行时依赖，在 pyproject 里登记**）、action 路由、审计日志（`~/.boardwise/audit/*.jsonl`）
   - 安全：只监听 127.0.0.1；无 token 的连接直接拒
3. **CLI**：`boardwise bridge start|status|screenshot <out.png>|highlight <uuid...>`
4. **`docs/bridge.md`**：协议规格（信封、action 目录、错误码、握手与重连策略）
5. **测试**：CI 里没有真 EasyEDA——协议级测试用 Python 写的 fake connector（真 WS 连接跑握手 + 各 action 的桩响应）；connector 侧保证 esbuild 构建通过 + 关键函数单测

## 参考资料

- `E:\easyeda-agent_RE\` 如存有 easyeda-agent 源码（MIT），可以**阅读**它的连接器/协议设计取经，但不要整文件照搬；若改编其代码，在文件头加出处注释
- 官方类型包：`npm i -D @jlceda/pro-api-types`

## 约束

- daemon/CLI：Python，除新增的 `websockets` 外保持零依赖；connector：TS + esbuild
- 代码/注释/docstring 英文；不执行任何 git 命令
- 测试秒级；WS 测试用 127.0.0.1 随机端口，不占用 61190

## 验收

- 自动测试全绿 + connector 构建产物存在
- **真机手动验证清单**（由岳翔宇执行，你要把步骤写到 docs/bridge.md 里）：侧载 .eext → 开"允许外部交互" → `boardwise bridge start` → `status` 看到已连接 → `screenshot` 导出当前 PCB 图 → `highlight` 一个图元在画布上可见

---

## 验收记录（2026-09-12，Kimi）

状态：**ACCEPTED**。独立复验：Python 122 passed；connector 32 passed；`connector/boardwise-connector-0.1.0.eext` 产物存在；`docs/bridge.md` 十三章节齐全（含 §10 已知限制、§13 真机清单）。
本轮报告数据与复验一致。执行者自曝并修正的 4 个真缺陷（highlight 判空、parseFrame 数组、跨 bundle instanceof、errorFrame）属实有价值。
待真机验证项（岳翔宇）：§13 清单 + .eext 布局有效性（侧载失败则改装文件夹，§10 已如实标注）。
重要结论入账：本地 .eprj2 缺库元数据（DEVICE/FOOTPRINT 无 META），**不能**当黄金板来源；CH340 黄金夹具只能来自 .epro2 导出。侦察脚本已归档 tools/eprj2-recon/。

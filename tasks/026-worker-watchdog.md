# 026 — Worker watchdog：后台窗口连接免疫（任务书 v1，probe 批）

> 2026-09-23 起草。病源、两种候选形态、probe 问题清单已和岳过过眼（当日对话）。
> 本批只回答"哪条路走得通"，**不写正式实现**——probe 结论决定形态 A 还是 B，再开实现批。

## 一、病（三个现场，同一根因）

心跳（`setInterval` 5 s，`connector/src/transport.ts:423`）与重连退避（`setTimeout`，:583）
**全部挂在扩展页面的事件循环上**。Chromium 对后台窗口节流直至冻结 JS 定时器：

1. **025 批 2 实测**：daemon 重启后，后台窗口的 connector **7 小时**没重连；窗口回前台立即自愈
   （重连定时器被冻结，不是网络问题）。
2. **issue #4（3.2.149）**：第二个窗口从不上线——同源（窗口冻结/懒求值）。
3. daemon 侧表现为**半开**：hub 里 `connected` 还在，真实动作全超时（bridge.md §7 末段、§10）。

## 二、候选形态

- **形态 A · Worker 闹钟（大概率）**：Web Worker 的定时器**不受页面后台节流**。
  Worker 定期向页面要活性戳；页面侧的 transport 每次心跳/重连活动都报戳；
  超时未报 → Worker 发 `wake` → 页面（节流周期内或解冻瞬间）收到后**立即 `connect()`，不等退避**。
  目标：把"7 小时/永不"压到"解冻即连，节流期分钟级"。
- **形态 B · transport 挪进 Worker（真·背景免疫）**：仅当 probe 证明 `eda.*` 在 Worker
  作用域可见才考虑。`eda` 是宿主注入 `window` 的，Worker 里大概率没有——不 probe 不下结论。
  成立则心跳（甚至整个 transport）移入 Worker，页面只负责 UI 与 eda 读写给 Worker 转发。改动大。

**禁止先写形态 B**：Worker 里看不到 `eda` 就只剩转发架构，复杂度爆炸，probe 说话之前一行不写。

## 三、Probe 批任务（本批全部内容）

0. **前置 · 真机热更演练**（顺带关闭 025e 的遗留验证）：`bridge update-connector --yes`
   推当前 dist（0.4.15 同版本重写）。**预期新行为**：命令**不再立刻 FAILED**，
   等新窗口报到后打 `verified`，exit 0；若超 30 s 预算则是 exit 3 UNKNOWN。
   前后各取 `bridge status` 与 audit 行佐证。落 `outputs/026_update_connector_live.txt`。
1. **P1 · 扩展页面能不能起 Worker**：临时动作 `sys.worker_probe`（025 批 1 的 probe 动作套路：
   注册 + mock 测试 + bridge.md 标注 probe 专用）。尝试 `new Worker(blobURL)`，
   Worker 脚本回 post `typeof self` / 能否收到页面消息 / 定时器 tick。
   宿主 CSP 是未知数（024 已证明立创生命周期跟文档不一样）——**失败也是结论**，如实记。
2. **P2 · Worker 里能不能看见 `eda`**：Worker 脚本回 post `typeof eda`、
   `typeof globalThis.eda`。可见 → 形态 B 门票；不可见 → 形态 A 定案。
3. **P3 · 后台节流的真实形态**：页面侧 `setInterval` 打时间戳，窗口压后台
   （最小化或切走焦点）≥ 3 分钟，读实际触发间隔分布——是 1 min 级 intensive throttling
   还是完全冻结？这决定形态 A 的指标写"分钟级"还是"解冻即连"。
4. **P4 · sideload 态冷启动**（issue #4 岳的假设补测）：卸载扩展 → 导入当前 eext →
   **整个编辑器关闭重开** → About 看 `activateObserved` / `moduleBootstrapObserved`。
   024b 验的是温路径（菜单点击重求值），冷启动从 sideload 态派发没系统测过。

## 四、验收

- probe 报告 `outputs/026_probe.md`：四个问题逐项回答"能用 / 不能用 / 有条件"，附原始证据；
- 临时 probe 动作有 mock 测试；三线全绿（pytest `--basetemp=.tmp_pt_home` / connector / tsc）；
- 真机只碰 test/test2；零残留复核（geometry/doc.list 前后一致）；
- 变异验证 ≥2（probe 动作的诚实性：Worker 起不来时**必须如实报失败**而不是编数据——
  这是本批唯一不可妥协的断言）；
- **probe 完不交架构结论以外的代码**：形态 A/B 的实现是下一批，本批交付 = 报告 + 临时动作。

## 五、守卫

- probe 动作属"临时观测仪器"，交付后在任务书 §六标注去留（保留进 doctor 还是删除）。
- 后台节流测试**不得**影响岳正在用的窗口：只用 test/test2 窗口做压后台实验。
- 真机热更（任务 0）只推当前 dist 同版本，不换代码；演练后焦点复位照旧。

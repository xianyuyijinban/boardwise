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
5. **P5 · `sys_Timer` 后台派发探测**（2026-09-23 追加，岳工作电脑 3.2.149 实测该命名空间存在：
   `setTimeoutTimer` / `setIntervalTimer` / `clearTimeoutTimer` / `clearIntervalTimer`）：
   这是**第三条路**——宿主自己的定时器 API。探：① 本机 3.2.186 上四函数 typeof；
   ② `setIntervalTimer` 的回调签名与触发方式（回调入页面队列还是宿主侧直接调？）；
   ③ **关键**：页面压后台时它的回调还派不派发——若宿主定时器不走页面事件循环，
   watchdog 可以不用 Worker，直接拿它当闹钟（比形态 A 轻一个数量级）。
   探完在 probe 报告里给"宿主定时器 vs Worker"的明确对比结论。

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

## 六、交卷记录（026 probe 批 · 2026-09-23 · agent-43 执行，Kimi 复验）

- 报告：`outputs/026_probe.md`（结论表覆盖任务 0 + P1–P5，逐项"能用/不能用/有条件"，各附原始读数）。
- 结论速览：0 能用 · P1 能用 · P2 不能用（**形态 B 出局**，Worker 里 `typeof eda === undefined`）·
  P3 有条件（**A 前提成立**：页面时钟压到整分钟级 245s 只 10 tick，同段 Worker 153/153 一次不落）·
  P4 有条件（整关整开 12.5s 自愈；「卸载→重导入」那条腿需岳手动补）·
  **P5 不能用**（宿主 `sys_Timer` 回调与页面时钟的大间隔逐一重合，同吃一张节流时刻表）⇒
  **形态 A 定案、且必要性被双向证实**（Worker 外无闹钟）。
- 任务 0 顺带关闭 025e 遗留：真机热更 **exit 0 / 3412 ms / verified**，无假 FAILED，reload 实测 2.5 s
  （`outputs/026_update_connector_live.txt`）。
- 临时动作：`sys.worker_probe`（connector **0.4.16**；actions.ts + catalogue protocol.py + bridge.md
  标 PROBE-ONLY），mock 用例 15 个在 `connector/tests/actions026.test.mjs`。
- 三线（Kimi 复验）：connector **380 pass / 0 fail**（365+15）· `tsc --noEmit` 干净 ·
  pytest 待 027 落卷后一并复跑（agent-43 自报 1388 两次同数）；热更 bundle 与本地 dist 字节一致
  （sha256 `b65ddd79…`，257 233 B）。交付文件 sha256 与交卷一致（`actions.ts 96b060e1…`、
  `protocol.py 22f40021…`）。
- 变异 **4/4 CAUGHT**（M1 Worker 失败伪装成功 / M2 status 编造计数 / M3 删 catalogue 条目 /
  M4 hostTimer 诚实性——打 P5 新代码）。
- **去留（Kimi 裁，实现批执行）**：删 `worker`/`pageTimer`/`workerTimer`/`hostTimer` 四个测量模式；
  `status` 保留、改名 `sys.connector_status` 并入 doctor（issue #4 那类"扩展 inert"的唯一现场证据）。
  已知瑕疵随删除消失：`hostTimer.running` 语义不准（stop 后仍报 true，看 count 冻结才准）。
- 未做：①「卸载→重新导入 .eext」后的冷启动（需岳手动，之后跑 `sys.worker_probe {"mode":"status"}`
  对比）；② 冻结态受控复现（最小化 API 在本机不生效，只有节流态实锤 + 85s/7 小时旁证）；
  ③ 形态 A 实现（下一批）。
- 新坑（入 SKILL 候选）：让窗口真"后台"只能**抢走前台**（`ShowWindow(SW_MINIMIZE)`/`SC_MINIMIZE`/
  `SetWindowPos(HWND_BOTTOM)` 本机全不改前台）；且只有 `powershell -NoProfile -Command "<内联>"` 生效，
  同代码走 `-File` 不生效。

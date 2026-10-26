# 绘制线派单入口（540B8）

> 这是 draw 线的任务路由。画图交付仍受 `AGENTS.md` 的三关、
> `docs/schematic-style-spec.md` 与画法宪法约束；解耦不改变任何算法验收锚。

## 1. 业务边界

| 可以派给 draw 线 | 不应夹带 |
|---|---|
| PresentationSpec、LayoutPlan/PageLayoutPlan、岛/archipelago、候选/verify | review 的 Finding、severity、triage/finalize 或报告结论 |
| 布局/布线、文字/旗标、pageframe/textmetrics、draw apply/lint | shared parser/model/bridge 的顺手重写 |
| edit 引擎与画布写侧（edit 不另设第三业务线） | 复制 rules.facts / rules.decap 的电气判断 |
| `commands/draw.py` 的 draw/edit/layout-lint/pintable/validate 注册分派 | review/shared 命令或 apply 的新 DSH 暴露 |
| DSH 离线 `boardwise_draw_compile` / `boardwise_draw_lint` | live page、daemon、apply 或 TS 侧业务判断 |

依赖方向只能是 **draw → shared / draw**。地网域/自动网名、NC/引脚连通、去耦库存与
CapDecision 只从 shared 公共合同读取；不得靠 import review 或复制函数“走捷径”。

## 2. 公开入口与算法锚

- CLI：`draw`、`edit`、`lint`（layout lint）、`pintable`、`validate`。
- DSH：新增的两个工具仅走离线 `draw compile` 与 `draw lint --snapshot --render`；
  旧 8 个工具顺序不变，新工具是第 9/10 个，没有 `boardwise_draw_apply`。
- 0.6.0 的绘制门槛仍是：反激 `draw compile` 出 `ok=True`，且岳亲眼看 SVG
  「一眼认出反激」。机器 `ok=True` 不等于这道人的门槛已经关闭。
- 任何要交给用户的原理图必须依次过：① 编译/可读性 `ok=True`；② 对照源网表逐脚连通；
  ③ 渲染后逐岛视觉自审。缺一不交付，也不许把失败候选落到真实画布。

## 3. 派单规则

1. 一张派单只写一个算法缺口或一个集成点，先写文件域、基线与相邻测试。
2. **算法与迁移永不同批**：不改共享 import 时顺手调布局，也不在算法批里做 Rust 翻译。
3. 需要 shared 电气合同、parser/model/bridge/CLI 变化时，改走 `tasks/shared-platform.md`
   的集成锁；不得把 draw→review 边登记成新 legacy。
4. 几何或输出变化必须给前后指纹/图像证据；纯解耦批则要求逐字节或行为等价，不能趁红灯改图。
5. 全量、共享底座与真机串行；真机只碰任务书逐字点名的 `test`/`test2`。删除、git 写、
   push、发布和 worktree 操作逐次问岳。

## 4. 验收与交接

- 小批先跑 `tests/test_540_cli_draw.py` 与对应 drawcompiler/drawapply/lint/edit/pintable
  邻域；owner 变更另跑 `tests/test_owner_rules.py` 和 layer 守卫。
- DSH draw 改动跑 `dsh-plugin` typecheck/test/build 与 `npm run smoke:draw`；真实 smoke
  只用公开/合成输入，不连接编辑器，不删除产物。
- 交接必须说明机器闸、逐脚连通、视觉自审各自证据；不适用时写不适用及原因，不能互相替代。
- CH343/534 等既有工作已在 `0f638de` 提交，按原任务归属，不因 540 解耦而变成 540 成果。
- Rust 顺序：纯函数/几何、parser/model、review 之后才到 draw；connector/DSH 薄适配可留 TS。

**当前 worktree 状态**：没有为 draw 线创建专用 worktree。需要隔离时先写清路径、分支、
owner、集成锁和证据保留，再逐次申请；不得自行解释旧档案 worktree 为可写工作区。

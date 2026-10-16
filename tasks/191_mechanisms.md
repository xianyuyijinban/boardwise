# 任务书：191 — 机制批（accept-unknown 真通道 · 用户架/内置架合并 · KiCad 裸 net 序号）

- 批号：**191**　日期：2026-10-16　来源：185~187 的遗留 + 0.6.0 前置。三件互相独立，可拆 191A/B/C 三个子代理并行（**各用各的 basetemp**）。

## 191A accept-unknown 真通道（会动 completion 语义，先读后改）

- 现状：文档里说「判不了的器件可以 accept-unknown」，CLI 没有入口；未审器件只能靠补手册或 `parts add --facts --verified` 清。
- 做：`boardwise parts accept-unknown <MPN|designator> --reason "<文本>" [--board <名>]`，落在设计意图合同里（`design-intent` 的现有 schema 上**只加**），
  带 who/when/reason。checkup 读到后：该件从 `unreviewed_parts` 移到新节 `accepted_unknown[]`，`completion.verdict` 不再因它是 `incomplete`，
  但 `conclusion` 一句话里必须出现「另有 N 颗工程师接受未审」——**不许静默变绿**。
- 撤销：`--revoke`。合同里指向的件已不在图纸上 → 走现有 `staleEntries` 路径（189B 修过的那条）。
- 测试：接受 → verdict 变化；撤销 → 复原；stale → 不崩、有行；conclusion 文案断言。

## 191B 用户架 / 内置架合并

- 现状（187B 遗留）：用户架优先时，exe 升级带来的新内置条目被整架遮住看不到。
- 做：按条目键（MPN / LCSC）合并：用户条目覆盖同键内置条目，其余内置条目照常可见；`parts list` 每行标来源（user / builtin / user-overrides-builtin）。
- 同时收 187B 的「boards 同名不同形」：`needs_datasheet[].boards` 与 `unreviewed_parts[].boards` 统一成同一形状（选 dict 列表；字符串列表那边加兼容读），schema 只加不删。
- 测试：新内置条目在用户架存在时可见；同键用户覆盖；`boards` 两处同形。

## 191C KiCad 裸 `(net N)` 序号读取

- 现状：KiCad 解析只认 `(net N "name")`；新版 KiCad 的焊盘/走线里出现裸 `(net N)`，序号丢了 → 差分对启发式（高速架子）读不到网。
- 做：`parsers/` 的 KiCad 路径读裸序号并回查 `(net N "name")` 表；查不到名的序号保留为 `net#N` 并计数披露。
- 夹具：`tests/fixtures/kicad_hs` / `kicad_min` 上补一个裸序号的最小样例（手写，不引入外部工程）。
- 测试：裸序号与带名序号读出同一网；未知序号有计数。

## 纪律（三子批共用）

- 动了 `rules/**` 的子批重钉 test_126a 指纹（191A 很可能动 completion 在 engines，不算；自己核）。
- 全量绿 `--basetemp=.tmp_pt_191{a,b,c}` `-n 4 --dist loadfile`。变异验证每子批至少一处。
- 红线同 190S；证据 `outputs/191{a,b,c}/evidence.md`；PROGRESS.md 各 append 一行；**不要 commit**。

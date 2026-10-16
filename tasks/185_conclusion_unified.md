# 任务书：185 — 结论收口 + needsDatasheet 拆名 + INSTANCE_STALE

- 批号：**185**　日期：2026-10-15　来源：岳的 AI 使用者体验反馈（同日文档）
- 纪律背景：report.json schema 规则「Added, never renamed」——**只加不改不删**。

## A. 唯一权威结论节（`conclusion`）

report.json 顶层新增 `conclusion` 节，聚合现有五出口的**同源数据**：

```jsonc
"conclusion": {
  "verdict": "incomplete",            // 与 completion.verdict 同源
  "exitCode": 1,                      // 与 summary.exitCode 同源
  "mayClaimPassed": false,            // 与 summary.mayClaimPassed 同源
  "oneLiner": "不能投板：…",           // 与 board-report.md 第一句**同一生成函数**
  "blockers": ["1 项 ERROR", "…"]      // 与 completion.verdictWhy 同源
}
```

- 实现要求：从既有数据**单点推导**，不许另算一遍（找 board-report.md 第一句的生成点，抽出来共用；找不到就反向——conclusion 生成 oneLiner，board-report 引用它）
- 旧字段（summary.conclusion / exitCode / mayClaimPassed / completion.verdict / verdictWhy）**一个不动**
- 文档：`docs/review-sop.md` 报告读法节写明「AI 汇报/脚本判读**只读 `conclusion` 节**；其余是投影」；`docs/` 里报告 schema 说明（若有专文）同步

## B. `needsDatasheet` 拆名

`completion` 节新增两键：
- `reviewerMarked: <int>` —— 现 `needsDatasheet` 窄义（审查者手工标记数）的正主
- `needsDatasheetTotal: <int>` —— `len(needs_datasheet[])`（facts 触发 + 手工标记的全量）

旧 `needsDatasheet` 保留原义不动；在生成处注释标 `deprecated → reviewerMarked`。cli.py 若有 re-gate 路径同步。

## C. `INSTANCE_STALE`（bridge）

`bridge call --instance <id>` 指向已失效实例时：当前行为是静默/拿到空数据（反馈 P5）。改为：实例不在线 → 报 `INSTANCE_STALE` 错误码 + 列出当前在线实例（windowKey/工程/页）。先看现有 `WINDOW_NOT_CONNECTED` 的实现位置，复用其列出逻辑；注意 daemon 对**从未见过的 id** 与**见过但已断开**的 id 能否区分（daemon 是否有实例历史）——若分不清，统一 `INSTANCE_STALE`/`WINDOW_NOT_CONNECTED` 文案里把「实例可能已失效，页面重连后 id 会变」写进去，并 Always 列在线窗口。

## D. 测试

- conclusion 节：多形态断言（有 ERROR / 缺手册 / 全干净三态下 oneLiner 与 board-report 第一句逐字一致；五出口与 conclusion 同源一致）
- needsDatasheet 拆名：三键计数自洽（reviewerMarked ≤ needsDatasheetTotal；旧键 == reviewerMarked）
- INSTANCE_STALE：失效 id 报错码 + 在线列表
- 全量绿；`engines/`、`cli.py`、`bridge/` 不在指纹 recipe 内（确认后声明），动了 `rules/` 才重钉
- report.json 键集合有快照钉的（搜 test_025d / report schema 测试）按实重钉，注释写批号

## E. 纪律

- 不动 git；删除走回收站；pytest `--basetemp=.tmp_pt_185`、`-n 4 --dist loadfile`
- 证据 `outputs/185_conclusion/evidence.md`；PROGRESS.md append 一行
- 版本号不动；**不要 commit**，交回主代理收口

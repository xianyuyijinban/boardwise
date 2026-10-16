# 任务书：188B — 185/186 低项清扫

- 批号：**188B**　日期：2026-10-16　来源：挖洞 swarm agent-343（185 低 2-7）+ agent-344（186 中 1/2/3、低 1/3/4/6/7/8）+ 187B 遗留 4
- 全是小修；逐条照下述裁决做，**别扩 scope**

## 1. 185 低项（cli.py / checkup.py / daemon.py / docs）

1. **低2 `--json` 载荷同名不同物**：`need-datasheet --json`、`triage --json-path` 的载荷**加** `conclusionSection`（= report 的 conclusion 五字段）；旧 `conclusion` 字符串键**不动**（消费方兼容）
2. **低3 doctor 话术**：doctor 遇 `INSTANCE_STALE` 给对的修复指引（"实例已失效，`bridge status` 重取在线窗口 id"），别再把人送去重开扩展；`PROJECT_NOT_CONNECTED` 同型一并补
3. **低4 conclusion 加 `mayQuotePassed`**：由 verdict 派生的单布尔（`complete` → true，其余 false），SOP 明写「脚本判读只看 `conclusion.mayQuotePassed`，`exitCode 0 ≠ 可投板」
4. **低5 SOP 旧报告兜底**：`docs/review-sop.md` 加一句「无 `conclusion` 节的旧报告：重跑一次 `checkup`/`triage` 重建，或按旧五处顺序读」
5. **低6 文档措辞**：SOP「末行」→「`### 整工程能不能投板：` 后那一句」；checkup.py:2949 附近「同一个调用」的注释改成「同一函数、确定性保证逐字一致」（三次独立重算的实话）
6. **低7 ping 不看 hint**：`docs/bridge.md` 明写「ping/hello 是 daemon 自答，不校验 hint；验实例存活用 `bridge status` 的 windows[]」

## 2. 186 中低项（cli.py / checkup.py / tools）

7. **中1 `matched_by:name` 可见性**：report.md 未审表格或 detail 行加「货架⇢按器件名匹配（弱证据）」；被判定而离开清单的行在 JSON 留 `reviewedByShelf` 痕（只加键）
8. **中2 judged 收紧**：`judged` 加「category 非空」要求；报告固定文案补 `--category <类别>`；先跑全库对拍确认收紧后无在库器件从「已判」回退「未审」（有则停下来报，别硬改）
9. **中3 sidecar 身份比对**：`--facts <file>` 读到的 `label`/`url` 与命令行 mpn/lcsc 不一致 → WARN（不拒，写进 provenance）
10. **低1 RecursionError**：`--facts/--fact` 捕 `RecursionError` → exit 2 明确报错
11. **低3 `--staged` 读索引 blob**：hygiene 的 `--staged` 改 `git show :<path>` 读暂存内容
12. **低4 `--json` 写失败顺序**：先写 json 输出失败则不动货架（顺序调整或事务）
13. **低6/低7 文档**：hygiene 词表「必须列全写法」（无规整）写进工具 docstring；报告清闸文案补「C 码来源：立创商城搜索」
14. **187B 遗留4**：`parts select --write` 不带 `--library` 的冻结态写路径对齐 `user_parts_library()`

## 3. 纪律

- 全量绿 `--basetemp=.tmp_pt_188b` `-n 4 --dist loadfile`（sources 在位）；变异验证 ≥2 组（挑中2/中3）
- report schema 只加不改；CLI 已有键不删
- 红线：不动 git；删除走回收站；真实项目名零出现；指纹 rules/ 动了才重钉
- 证据 `outputs/188b/evidence.md`；PROGRESS.md append 一行
- **不要 commit**，交回主代理收口

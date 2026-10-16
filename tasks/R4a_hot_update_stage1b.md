# 任务书：R4a — 真热更 阶段一收尾 + 安全设计定稿（不写 stub 代码）

- 批号：**R4a**　日期：2026-10-17　来源：岳 10-17「把 R4 热更加入日程」；路线图 `tasks/roadmap/R4-true-hot-update.md`，草案 `outputs/R4/design-proposal.md`，证据 `outputs/R4/evidence.md`
- 现状：实验①②已过（10-13 真机：indirectEval / new Function / 动态 import 都回 42；**`crypto.subtle` undefined**）；实验③本机双证 verified；④未测；165「写≠激活」只在工作电脑出现过。
- 本批产出 = **证据 + 定稿的设计文档**，给岳裁。阶段二 stub 代码是 R4b，岳批了设计才开。

## A. 实验④：菜单点击免 reload 激活（test 窗口，真机）

1. 记当前 `bridge status` 的 connector 版本 V0。用现有 `update-connector`（单窗口 `--instance`，当场取 id）写入一个**只改版本串**的测试 bundle（V0+`-r4probe`，本地打包，不发布）。**不 reload**。
2. 请求主代理转告岳**点一次扩展菜单**（子代理不能点 UI：把这一步写进 evidence 的「待人工」并停在这一步，主代理会接手）。点后读 hello 版本：是 `-r4probe` 即「菜单点击会重求值、激活新 bundle」成立。
3. 无论结果，恢复正式版本（再 `update-connector` 回 V0 并 reload 验证 hello = V0）。
- 若 2 需要人工，子代理只做 1 和「准备好恢复命令」，交卷说明卡在哪一步。

## B. 165 复现条件（只读调查，不碰工作电脑）

- 读 165 的原始反馈（PROGRESS/outputs 里 grep `165`、「写≠激活」）与 030/031 正例，列出两边**可观察差异**（宿主版本、窗口数、IndexedDB 记录名 `User_*_v6`、写后是否 reload、多窗口同工程）。
- 本机能复现的就复现一次（例如：两个窗口开同一工程、只 reload 其中一个）；不能复现的写「需工作电脑」。

## C. 安全设计定稿（改 `outputs/R4/design-proposal.md`）

`crypto.subtle` 缺席 → 草案 §3「放弃」不是唯一出路，补一节 **§3b 纯 JS 验签**：
- 候选：`tweetnacl`（`nacl.sign.detached.verify`，Ed25519，零依赖、审计过）与 `@noble/ed25519`（需 `crypto.subtle` 或自带 sha512 → 核实它在无 subtle 环境能否用同步 sha512）。**只调研不安装**：写包名、版本、体积、是否需要 subtle、许可证；推荐一个，版本钉死。
- 在 realm 里能跑的证明：用已有探针通道（10-13 的 realm probe 同款）`new Function` 执行一段**内联**的最小 Ed25519 verify 自检（官方测试向量），回 true/false；代码片段作为 evidence 附件，不进 connector 源码。做不到就如实写。
- 密钥管理三选项写清利弊给岳选：① GitHub Actions secret 签名；② 岳本机离线私钥、发版时手签；③ 两把公钥（主+备）内置 stub 带过期时间。**不替岳选**，写推荐理由。
- 草案 §4（验签放 stub 而非 daemon）保持推荐，补一句：daemon 侧不需要任何密钥材料。

## D. 纪律

- 本批不改 `connector/src` 正式源码；测试 bundle 只在 `.tmp_r4a/` 打（gitignored），用完回收站。
- 真机只碰 test；instance 当场取；结束时 connector 版本必须回到 V0（`bridge status` 截取进 evidence）。
- 不安装任何 npm 包（调研靠 `npm view` 只读）。需要 `export https_proxy=http://127.0.0.1:7890`。
- 证据 `outputs/R4/evidence.md` 追加「R4a」一节；PROGRESS.md append 一行；**不要 commit**；不动 git。

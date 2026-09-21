# 一次性提交清单 — 013（012 真机验证轮：验收 + 修复 + F4 选型通路）

> 2026-09-21 整理。执行者：岳翔宇（AI 不动 git，等你点头）。
> 基线：最后提交 `ec72226`（PROGRESS→012）之后**全部未提交改动都属于 013 线**
> （批①只读验证 / F3+F5 修复 / F4 probes+改键 / 批②验收+BOM/clear/文件名修复），边界干净。
> 交卷时状态：pytest **1136** / connector **279** / tsc 干净；connector **0.4.10**
> （编辑器已热更，三处 bundle 一致）；doctor 真机 7/7。
> 任务书：`tasks/013-realhost-verification.md`（含批①/修复轮/F4 矩阵/F4 落地/批② 五段交卷记录 + Kimi 复验落笔）。

## 1. 建议的提交方式

单一提交（与历次先例一致）。

```bash
git add connector/ docs/ src/ tests/ tasks/ README.md
git add -f outputs/013_*
git commit   # 建议标题见下
```

建议标题：
`013: real-host verification — doctor 7/7, review.mark+export.fab on the thesis board, BOM filter polarity fix, lib.recommend supplierId key, connector 0.4.10`

注意：`git add -f outputs/013_*` 用 glob，只带本轮 013 证据（含 `013_fab_bishe2/`
`013_fab_bishe3/` `013_p3_evidence/` 等目录，2026-09-21 干跑审计实测 **196 项**）；outputs/ 下 010c 的历史
未追踪遗留**不**被带进来（ glob 精确避开），已追踪的 6 份 011 时代 013_* 幂等无害。

> **干跑审计（2026-09-21，提交前）**：`git status` = 16 M + `docs/images/`（恰好 3 张 PNG）+
> 2 份 tasks/ 新文件，与 §2 逐条吻合；`outputs/013_*` glob = 196 项，无 010c 命名残留混入，
> `013_fab_bishe2` 是清单明示保留的 17 列历史档。清单与磁盘现状一致，可直接执行。

## 2. 文件清单（git status 的 17 项逐条归置）

**Modified（16，全部 013 线）**

| 文件 | 来自 |
|---|---|
| `README.md` | 同事视角走查 4 处过时对齐（中英双语段同步）：桥描述去掉"只读/截图"旧措辞→只读为主+守卫后可放置/移动/删除+导出制板；内置规则 3 条→15 条分组全列；screenshot 行加缓存空帧警告 |
| `connector/src/actions.ts` | F3 projectIdentity/readProject、F4 probes 通道+arity、exact 层改 supplierId+deadRungs、BOM filterOptions 极性修复+FAB_BOM_OVERRIDE_KEYS、文件名后缀、clear 幂等、FAB_BOM_STATISTICS/PROPERTY 互斥 |
| `connector/extension.json` / `connector/package.json` | 0.4.6 → 0.4.10 |
| `connector/tests/actions.test.mjs` | F3 既有形状兼容断言 |
| `connector/tests/actions006b.test.mjs` | arity 用例 |
| `connector/tests/actions012.test.mjs` | F3 双读者同口径用例 |
| `connector/tests/actions012b.test.mjs` | probes 6 例+GOLDEN 基线重录（有意）、BOM preset/manifest 用例 |
| `connector/tests/actions012c.test.mjs` | clear 幂等用例 |
| `docs/bridge.md` | F4 定论（§12+§4 散文）、probes/arity 行、BOM 证据行×2、clear 口径、多窗口焦点漂移根因、计数 1136/279、0.4.10 |
| `docs/getting-started.md` | **一次只开一个编辑器窗口**警告、fab 文件名、样例版本 0.4.10、bridge screenshot 缓存空帧矛盾修正（同事视角走查）、gs-04/05/06 截图注 |
| `docs/api-surface-2026-09-20.md` | 真机更正①~⑤ |
| `docs/draw.md` | sys.probe arity |
| `src/boardwise/bridge/protocol.py` | probes/arity/BOM 通道描述 |
| `src/boardwise/cli.py` | F5 doctor 页数口径 `_project_counts` |
| `tests/test_doctor.py` | F5 用例×2 + uuid=0 措辞 1 换 3（前批） |

**New（4）**：`tasks/013-realhost-verification.md`（本任务书+五段交卷记录）；
`docs/images/gs-05-review-mark.png`（批② 真机打标抓图，Kimi 亲看确证后从
`outputs/013_mark_P1.png` 复制——docs/ 不被 gitignore，正常 `git add docs/` 会带上）；
`docs/images/gs-04-doctor-green.png` / `docs/images/gs-06-fab-files.png`（终端样式渲染：
gs-04 = 2026-09-21 本机实跑 doctor 7/7 真实输出；gs-06 = 批② 毕设板导出 manifest 的
真实文件名/字节数，目录名按文档叙事写作 fab/；两图 Kimi 均已亲看复核）。

**不提交**：`connector/*.eext`（0.4.10 产物，分发用）、`connector/dist/`、`.tmp_*`。

## 3. 真机验证结论速览（提交信息可引）

- doctor 真机 7/7 绿（含 [beta] 打标接口 typeof=function）
- review.mark：毕设板 9/9 打标+清除+PAGE_MISMATCH+CONNECTOR_ERROR 全链；可见性 Kimi 亲看 PNG 确证
- export.fab：三件套真出齐；**BOM 零行根因=includeValue 语义极性反**（宿主源码证据）→ 68 行分组 BOM/Quantity=122/位号集合与 pnp 完全相等；表头 17→15 列（statistics/property 互斥）
- lib.recommend：searchByProperties 按索引键过滤（supplierId 精确）→ exact 层改键，C8678 真机命中完整候选
- §五：projects[] 恒单工程（该宿主 getAllProjectsUuid 只报当前）；**焦点漂移根因=多窗口各自注册、daemon 只认最后一个**——内测口径"一次只开一个窗口"已写进 getting-started

## 4. 提交后同步项（PROGRESS.md，AI 已备口径）

- baseline：commit→新号；pytest **1136** / connector **279** / connector version **0.4.10**；日期 2026-09-21。
- Milestones 加行：`013 real-host verification | DONE 2026-09-21 | 本清单 + tasks/013-realhost-verification.md`
- Git anchors 加一行。

## 5. 遗留（不阻塞本提交）

- 截图五张：~~gs-05~~（已补，随本提交入库）；~~gs-04/06~~（已补，终端样式渲染，真实证据来源见 §2 New 条）；gs-01/02/03 需岳手截。
- daemon 多窗口路由/stand-down → M2 后议（backlog）。
- supplierId 命中项 libraryUuid 为空（可选 lib.device.get 补发）；P7 getByLcscIds 只读无入口。

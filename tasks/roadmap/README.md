# boardwise 路线图任务包（v0.5.11 之后）

写给接手开发的朋友：这里是四个版本包 + 一个远景侦察，每包一个文件，
自包含、可直接开工。**开工前必读本文件一遍**——仓库规矩、测试方法、验收方式都在这。

## 这个仓库是什么

boardwise 是立创 EDA Pro 的 AI harness：离线设计审查（原理图/PCB 规则引擎）、
在线桥（daemon + 编辑器扩展 connector）、原理图自动绘制管线。主语言 Python
（`src/boardwise/`，pytest 套件 5400+ 条），connector 是 TypeScript
（`connector/`，npm test + tsc），dsh-plugin 是 npm 包（`dsh-plugin/`）。

## 铁规矩（详版见根目录 `AGENTS.md` 和 `.kimi-code/skills/boardwise/SKILL.md`）

1. **不直接推主分支**——你的工作走 PR（fork 或分支都行）。
2. pytest 必带 `--basetemp`：`.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_x`
   （Windows 上不带会吞汇总行、假 exit 1）。
3. **禁 `rm`/`rm -rf`**：删除走回收站（SKILL.md §7 有 PowerShell 写法）。
4. `tests/fixtures/` 既有夹具不许改；`evidence/`、`outputs/NNN/` 是历史证据，只增不改。
5. 真机（立创编辑器）**只碰 `test` / `test2` 工程**，其余工程是禁地；
   动手前先 `boardwise bridge status` + `doc.list` 对身份。
6. **绝不伪造**：测不出来就明说「没测到」，不许编数据、不许把失败说成通过。

## 测试与验证惯例

- 四线：pytest / `cd connector && npm test && npm run typecheck` /
  `cd dsh-plugin && npm run typecheck && npm test && npm run build`。动了哪层跑哪几层。
- **改了 `src/boardwise/rules/` 下的文件**必须重钉规则体指纹：先跑
  `.venv/Scripts/python.exe -c "from pathlib import Path;from boardwise.engines.review_eval import rulebody_fingerprint as f;print(f(Path('src/boardwise/rules')))"`
  再按 `tests/test_126a_pcb_review_plumbing.py` 底部注释的台账格式更新两处钉值
  （recursive + direct）并写一行台账注释（谁改的、为什么、行为锚是哪个测试文件）。
- **变异验证**：关键修复至少做两组——把修复临时破坏掉（改常量/删判断），
  确认测试真的变红，再还原（`cp` 备份 + `sha256` 对比还原，**不用 git checkout**）。
  这是本仓库抓「假修复」的主手段。
- 证据落 `outputs/<编号>/evidence.md`（追加写），原始读数落 `outputs/<编号>/live/`。

## PR 流程（你提 PR，我们这边机器审）

1. 你按任务包开发，PR 描述里写：对应任务包编号、改动文件清单、测试计数、
   变异验证记录、遗留风险。
2. PR 一到，我们派子代理跑：**全量测试 + 逐行 diff 审查 + 挖洞审计**
   （对照任务包的验收锚逐条核）。
3. 审查发现的问题在 PR 里回给你；全绿后由主代理合并、按发布闸发版
   （议题闭环 + 挖洞/上机/实测三闸）。
4. 不确定的设计决策**不要自行拍脑袋**：在 PR 里写出来，主代理裁决。
   （本仓库大量「看起来不一致」的地方是有意为之，docstring 里写了为什么。）

## 版本包索引

| 包 | 目标版本 | 主题 | 依赖 |
|---|---|---|---|
| `R1-bridge-completion.md` | v0.5.12 | 桥能力补齐（PCB 放置动作等四件小事） | 无 |
| `R2-pcb-review-deepening.md` | v0.5.13 | PCB 审查加深（禁布区消费、镀铜孔、重构债） | R1（丝印演示） |
| `R3-kicad-harness.md` | v0.6.0 | KiCad 第二宿主：侦察 → 离线审查最小闭环 | 无 |
| `R4-true-hot-update.md` | v0.6.x | 真·热更（stub + 动态载荷），实验先行 | 无 |
| `R5-simulation-recon.md` | 远景 | SPICE 仿真通路侦察（只侦察不实施） | 无 |

建议按 R1 → R2 → R3/R4 的顺序做；R5 随时可插。

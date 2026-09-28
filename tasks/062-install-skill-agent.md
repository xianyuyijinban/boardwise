# 062：install-skill --agent —— 让用户的 AI 自行配置 skill（岳裁：不要我们配路径）

来源：岳对 #11 收口的追问——"codex / hermes / minimaxcode / zcode 这些后续都能装上吗"，以及他的裁决：
**不要我们维护 harness 路径表，要让用户的 AI 自行配置**。AI 自己最清楚自己的 skill 发现路径；
我们枚举下去永远是追赶，而且会猜错（猜错就是下一个 #11）。

## 设计（已定，不再变动）

### 1. `install-skill --agent`：引导指令生成器（不写任何文件）

- 新增 flag `--agent`（与 `--harness`、`--uninstall` 互斥，argparse 层 `exit 2` 锁死组合）。
- 行为：**纯打印，零文件写**。输出三段：
  1. 本构建自带的 SKILL.md 的绝对路径（`resources.skill_md()`）；
  2. 一段给用户 AI 的引导指令（中文，可直接粘贴），要点：
     - 把上面那份 SKILL.md 复制到**你自己 harness 的用户级 skill 目录**下，
       目录名 `boardwise`、文件名 `SKILL.md`（你自己知道约定在哪；不知道就查你自己的文档）；
     - 装完后用你自己发现 skill 的方式验证它在场；
     - 已有一份且内容不同：先备份成 `SKILL.md.bak-<日期>` 再覆盖（与 install-skill 的既有规矩一致）；
  3. 一行给人看的说明：把上面这段粘给你的 AI 即可（Codex / Hermes / 任何 agent）。
- 退出码恒 0（读不到捆绑 SKILL.md 才 exit 1，与 install 路径同一 except）。

### 2. kimi/claude 落点保留

061 已交付的 `--harness {kimi,claude,all}`（默认 all）不动——那是我们自己天天用的确定性路径。
`--agent` 是给**其余一切 harness** 的通道，不是替代。

### 3. doctor：一行 hint，不枚举

- doctor 输出末尾追加一行**信息行**（不判红绿、不算进 n/n 通过数；实现上走 print，不是 DoctorCheck）：
  「用别的 agent harness？`boardwise install-skill --agent` 打印一段引导指令，粘给你的 AI 让它自己装。」
- skill-kimi / skill-claude 两行检查不变。任意 harness 的落点 doctor **不猜**。

### 4. AGENTS.md 加「clone 引导」段（岳追加裁决：别的 AI clone 仓库时要能收到）

仓库根 `AGENTS.md` 是跨 harness 事实标准（Codex/Cursor/Aider 等 clone 仓库后读的就是它）。
在三条红线之后加一小段「给 clone 本仓库的 AI」，保持本文件轻量、不复制 SOP：

- 审查 SOP 权威文件：`.kimi-code/skills/boardwise/SKILL.md`（**仓库内文件，clone 即可读，
  不需要任何安装**）；
- 若你的 harness 有用户级 skill 目录：把该文件复制为 `<你的用户级 skills>/boardwise/SKILL.md`
  （你自己知道约定；已有异版先备份 `.bak-<日期>`）；
- 无仓库场景（只拿到 exe）：`boardwise install-skill`（kimi/claude）或 `--agent` 打印引导。

### 5. README 引导教程同步（岳追加裁决）

README（英文段在前、中文段在后，双语都要）的安装/快速上手处，在 `install-skill` 相关说明旁补上：
`--agent` 的用法（打印引导指令 → 粘给你的 AI → 它自己装进自己的 skill 目录）与
「clone 本仓库的 AI 直接见根目录 AGENTS.md」。**语气与排版跟现行 README 一致**（这版 README 是
岳亲自定稿的：简单直白、不堆专业词汇）——只加引导，不重写既有段落。

### 6. 明确不做

- 不新增任何 harness 的硬编码路径（Codex/Hermes/… 一个都不加）。
- 不做 MCP 化（那是另一个量级的分发层，将来单独立项）。
- AGENTS.md 只加引导段，**三条红线与"唯一权威"表述一个字不动**。

## 验收

1. 新测试（`tests/test_skill_install.py` 扩展，basetemp `.tmp_pt_84`）：
   - `--agent` 输出含：SKILL.md 绝对路径、引导指令关键句（目录名 boardwise / 文件名 SKILL.md /
     备份规矩 / 自验证），退出 0，**且文件系统零变化**（钉死：两个假 home 前后 walk 一致）；
   - `--agent` × `--harness` / `--uninstall` 互斥 → exit 2；
   - doctor hint 行出现且不影响通过计数（沿用 test_doctor 现有夹具）。
2. 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 全绿（基线 2380）。
3. 变异 ≥1 组（cp+sha256 还原，禁 git checkout）：如把"零文件写"改成会写文件，对应测试必须红。
4. 手验留证 `outputs/062_agent/`：真跑一次 `--agent` 存输出。
5. AGENTS.md 引导段：主代理亲看（含 SKILL.md 仓库内路径、用户级安装指引、`--agent` 指引；三条红线原文未动——diff 里红线段零变化）。
6. README 双语段：主代理亲看（`--agent` 用法与 AGENTS.md 指引都在；既有段落无重写——diff 里只有新增）。

## 边界与纪律

- 只碰：`cli.py`（install-skill 参数、_cmd_install_skill、_finish_doctor 或相邻打印处）、
  `tests/test_skill_install.py`、`tests/test_doctor.py`、`AGENTS.md`（仅新增引导段）、
  `README*.md`（仅新增引导，双语）、`tasks/062*`。skill_install.py 预计不用动
  （--agent 是纯 CLI 输出）；若动了要说明理由。
- pytest 必带 `--basetemp`；零 git 写操作；PROGRESS.md 不动（主代理收口写）。
- 注释密度与措辞跟周边代码一致（引导指令文案是给 AI 看的 prompt，写得像 prompt，别写成 log）。

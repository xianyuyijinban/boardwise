# boardwise — AI 协作约定（轻量）

本仓库 AI 约定的**唯一权威**是
[`.kimi-code/skills/boardwise/SKILL.md`](.kimi-code/skills/boardwise/SKILL.md)：何时加载、
审查闭环、真机纪律 R1–R3、bridge 动作速查、真机坑表、三线命令与交付纪律，全在那里。
本文件只列三条最常被违反的红线，**不复制**那份内容；两处说法冲突时以 SKILL.md 为准。

## 三条红线

1. **不动 git**：不 `commit` / `add` / `checkout` / `restore` / `push`。任何 git 变更逐次经用户点头。
2. **pytest 必带 `--basetemp=.tmp_pt_home`**：Windows 上否则汇总行被吞、假 exit 1。

   ```bash
   .venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home
   cd connector && npm test && npm run typecheck
   cd dsh-plugin && npm run typecheck && npm test && npm run build
   ```

   四线（pytest / connector / dsh-plugin / tsc）全绿才交卷。
3. **真机只碰 `test` / `test2`**：动手前先 `boardwise bridge status`（daemon 会自行死亡），
   `doc.list` 报的焦点工程名与任务书**逐字一致**才算对上身份。**禁地**：毕设FOC驱动板、
   `CH340G.eprj2`、`ROBOT ctrl FOC.eprj2`，以及一切真实工程；任务书没点名 = 不许写。
   目标缺失就停下来问（R3），不许自行解释、自行替代。

其余纪律——变异验证 ≥2（`cp` 备份 + `sha256` 还原，禁用 `git checkout --`）、append 落盘后
`grep -c` 防双执行、不碰 `outputs/011e*` / `014_*` / `015b_*` / `016_*` 与 `tests/fixtures/`
既有夹具——见 SKILL.md §7。

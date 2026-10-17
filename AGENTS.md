# boardwise — AI 协作约定（轻量）

本仓库 AI 约定的**唯一权威**是
[`.kimi-code/skills/boardwise/SKILL.md`](.kimi-code/skills/boardwise/SKILL.md)：何时加载、
审查闭环、真机纪律 R1–R3、bridge 动作速查、真机坑表、三线命令与交付纪律，全在那里。
本文件只列最常被违反的红线，**不复制**那份内容；两处说法冲突时以 SKILL.md 为准。

## 项目地图（动手前先读这三份）

- [`docs/roadmap.md`](docs/roadmap.md)——**稳定层**：当前在哪、版本骨架（0.5.x→0.6.0→远景）、
  五个方向（R1–R5）、绘制主线的验收锚（「一眼认出反激」）。
- [`docs/product-boundary.md`](docs/product-boundary.md)——**边界**：做什么、不做什么（硬边界清单）、
  撞车区/独有区、威胁雷达。判断「这算不算我们的活」看它。
- [`tasks/TASKMAP.md`](tasks/TASKMAP.md)——**任务全图**：001–516+ 的编号/主题/状态（已落/工作树/
  搁置/在途/规划）/证据路径。按编号查，不按时间查。

`tasks/SCHEDULE.md` 是**滚动排期**（最近几个版本的具体任务与依赖）；
`PROGRESS.md` 是按时间的**流水账**，**不要从头读**——只在需要查历史细节时 grep 它。

## 红线

1. **不动 git**：不 `commit` / `add` / `checkout` / `restore` / `push`。任何 git 变更逐次经用户点头。
2. **pytest 必带 `--basetemp=.tmp_pt_home`**：Windows 上否则汇总行被吞、假 exit 1。
   并行只许 `-n 4 --dist loadfile`（**不许 `-n auto`**——打满主机被岳叫停过；
   不许 `--dist load`——它把同文件的测试对拆到不同 worker，test_bridge_cli 的
   审计序就这么死过）；多前场并行时各用各的 basetemp（`.tmp_pt_<批名>`）。

   ```bash
   .venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile --basetemp=.tmp_pt_home
   cd connector && npm test && npm run typecheck
   cd dsh-plugin && npm run typecheck && npm test && npm run build
   ```

   四线（pytest / connector / dsh-plugin / tsc）全绿才交卷。
3. **真机只碰 `test` / `test2`**：动手前先 `boardwise bridge status`（daemon 会自行死亡），
   `doc.list` 报的焦点工程名与任务书**逐字一致**才算对上身份。**禁地**：毕设FOC驱动板、
   `CH340G.eprj2`、`ROBOT ctrl FOC.eprj2`，以及一切真实工程；任务书没点名 = 不许写。
   目标缺失就停下来问（R3），不许自行解释、自行替代。
4. **删除一律进回收站，禁 `rm` / `rm -f` / `unlink` 直删**（xianyuyijinban 2026-09-28 定、
   2026-10-02 重申）：临时目录、变异备份、废弃产物**没有例外**。Git Bash 走 Windows 原生
   PowerShell 通道（`DeleteFile`/`DeleteDirectory` + `SendToRecycleBin`），写法照抄 SKILL.md §7。

其余纪律——变异验证 ≥2（`cp` 备份 + `sha256` 还原，禁用 `git checkout --`）、append 落盘后
`grep -c` 防双执行、不碰 `outputs/011e*` / `014_*` / `015b_*` / `016_*` 与 `tests/fixtures/`
既有夹具——见 SKILL.md §7。

## 子代理纪律（193 立；**已由机器兜底**）

并行子代理是这台机器上最大的 CPU 来源：三个子代理各开 4 个 xdist worker 再叠加探针/变异
重跑，旗舰机直接被铺满。四条规矩，**机器侧已经拦住了**（`tests/conftest.py` →
`tests/_process_guards.py`，机制地图见 `docs/testing-doctrine.md`）——下面写的是为什么，
不是唯一防线：

1. **单全量**：一次只跑一轮全量 pytest。要并发并发别的，别并发全量（整机槽只有 2）。
2. **探针/脚本单进程**：一次性探针、变异、测量脚本不许 multiprocessing / 线程池 fan-out；
   非并发不可时，子进程数 < 4 且总时长 < 30 秒。
3. **长命令带超时**：前台命令给 timeout，后台任务标 timeout，别让一条挂死的命令把机器占住。
4. **交卷前清理自己起的子进程**：daemon、watcher、后台 pytest 一律收干净。

机器侧实际拦的是：pytest 进程降到 BELOW_NORMAL 优先级、整机全量并发槽 = 2（拿不到就排队并
打印提示）、`-n auto` / `-n >4` 直接拒绝（`-n 0` 与 `-n 4` 放行）、OMP/MKL/OpenBLAS/NumExpr
线程数封顶 1；`BOARDWISE_NO_TEST_GUARDS=1` 一次全关。
保密是另外四道闸（暂存区正文 / 提交说明 / 发布件 / 推出前 diff+message），见同一份地图。

## 给 clone 本仓库的 AI（入口指引，不是第五条红线）

- 审查 SOP 的权威文件是
  [`.kimi-code/skills/boardwise/SKILL.md`](.kimi-code/skills/boardwise/SKILL.md)：
  **仓库内文件，clone 下来直接读，零安装**。要审板子先读它。
- 你的 harness 若有用户级 skill 目录：把这份文件复制成
  `<你的用户级 skills>/boardwise/SKILL.md`（约定在哪你自己知道；已有一份异版先备份成
  `SKILL.md.bak-<年月日-时分秒>` 再覆盖，别覆盖已经存在的同名备份），复制完用你自己发现 skill 的方式确认它在场。
- 手上只有 exe、没有仓库：`boardwise install-skill`（Kimi Code / Claude Code 两处）或
  `boardwise install-skill --agent`——后者打印一段引导指令，粘给你在用的 AI，它自己装。
- **DeepSeek Harness（dsh）不用装 skill**：它读**工作区**的 `AGENTS.md`，本仓库自带一份
  并已指向 `docs/roadmap.md` / `docs/product-boundary.md` / `tasks/TASKMAP.md`，把仓库当工作区
  打开即可；`boardwise install-skill --harness dsh` 把这句原因打印出来（exit 0，不写任何文件）。

# 任务书：193 — 进程/CPU 硬闸 + 保密机制补洞（机器执行，不靠规矩）

- 批号：**193**　日期：2026-10-17　来源：岳——三个子代理并行各开 4 个 xdist worker + 探针/变异重跑，旗舰机 CPU 被打满；保密闸在 commit 后依旧漏过两处 docstring（186），因为它只管「源文件正文」和「git add 时刻」，管不住 commit message、发布件和文件夹文件名。
- 原则：**机器拦截**。规矩写在 AGENTS.md 只是提醒，闸要装在进程和命令自己走的路上。

## A. pytest 进程闸（`tests/conftest.py`，一个 `pytest_load_initial_conftests` 钩子）

对任何一次 pytest 调用生效（含子代理忘规矩的直接调用）：

1. **进程降优先级**：Windows `ctypes` SetPriorityClass `BELOW_NORMAL_PRIORITY_CLASS`（POSIX 下 `os.nice(10)`）；xdist worker 继承。任何一步异常 fail-open。
2. **全机并发槽 = 2**：只对**完整套件**运行生效（判定：`args` 里没有指向具体文件/节点/k 的筛选参数）。用 `msvcrt.locking` 锁住 `<槽文件>` 的不同字节段（POSIX `fcntl.flock`），文件放在用户态目录（`BOARDWISE_HOME` 或 `~/.boardwise/pytest-slots`，自动建）。拿不到槽：**等**（打一行提示），不失败。槽文件残留不死锁（锁随进程死自动释放）。收到 Ctrl+C 正常传播。
3. **worker 上限 = 4**：`-n auto` 或 `-n >4` 直接 `pytest.exit()` 拒绝；`-n 0`（关并行）放行。槽锁持有者外的运行不限制。
4. **线程库封顶**：在控制器与 worker 都设置 `OMP_NUM_THREADS=1` / `MKL_NUM_THREADS=1` / `OPENBLAS_NUM_THREADS=1` / `NUMEXPR_NUM_THREADS=1`（`os.environ.setdefault`，不覆盖用户显式设置）。
5. 总闸开关：环境变量 `BOARDWISE_NO_TEST_GUARDS=1` 全关（CI 或特殊场合用）。
- 测试 `tests/test_193_process_guards.py`：用 **subprocess** 起真 pytest（小套件）验证：槽 2 下第三个完整套件等待并提示；`-n auto` 被拒；`-n 0` 与范围运行（`pytest tests/test_x.py -q`）不占槽、不等待；fail-open（把槽文件搞坏）不炸；优先级读回确认是 BELOW_NORMAL（Windows API 可读）。这些测试本身跑在 pytest 里——注意别让它们吃掉父会话的槽（子进程设 `BOARDWISE_TEST_GUARD_CHILD=1` 之类豁免，或把子进程套件标成范围运行）。

## B. 保密机制补洞（`tools/check_repo_hygiene.py` + git hooks + 打包闸）

现有：pre-commit 钩子在 `--staged` 模式扫暂存区正文 + 敏感词表（词按 token 匹配，主代理已核过型号短词能命中「型号+后缀」这类长串）。补四处：

1. **commit-msg 钩子**（新文件 `.githooks/commit-msg` + 装钩脚本 `scripts/install-hooks.bat`，`git config core.hooksPath .githooks`）：hygiene 新增 `--message <file>` 模式扫提交说明（只用敏感词表）。**现有 `.git/hooks/pre-commit` 是裸拷贝不是 core.hooksPath**——装钩脚本把 pre-commit 也一并迁过去（两份内容等价后删除旧钩子）。
2. **pre-push 钩子**：扫 `git diff <remote>/<branch>...HEAD` 的正文 + 全部 outgoing 提交 message（含 `git push --force` 后的场景）。慢就只对「差出 100 个提交以内」做正文扫描，超出只扫 message 并打提示。
3. **发布件闸**：hygiene 新增 `--assets <file...>`：对任意文件扫原始字节；**.exe 另做 PyInstaller 压缩流扫描**（主代理已有探针写法：找 `78 01/5e/9c/da` 头 zlib 解压逐流扫，参考实现 `packaging/check_exe_secrets.py` 由你按此写）。`packaging/build_exe.py` 构建完成后**自动**调用 `--assets <打出的 exe>`，命中即 exit 1（印「命中敏感词表第 N 条」而不印词）。词表不在场 → 只打一行提示放行。
4. **敏感词表自查**：词表文件被 tracked 已经会拦（现有）；本批确认 `tools/check_repo_hygiene.py` 的两种模式都会拦「词表文件进库」，并有测试。
- 测试 `tests/test_193_secrecy_hooks.py`：`--message` 命中/放行；`--assets` 命中 exe 压缩流（合成一个小 pyinstaller 包太贵，就造一个含 zlib 流的假文件扫出来）/放行；装钩脚本幂等（跑两遍不炸、旧 pre-commit 拷贝被处理）。

## C. 文档（把规矩写清楚，但闸在机器上）

- `AGENTS.md` 子代理纪律补四条：单全量（一次只跑一轮全量 pytest）、探针/脚本单进程（不许 multiprocessing/线程池 fan-out，除非小于 4 且短于 30 秒）、长命令带超时、交卷前清理自己起的子进程。同时写明「这些已由 conftest 闸兜底」。
- `docs/testing-doctrine.md` 加一节：进程闸三个机制 + 保密四道闸的地图。
- 指纹：A 不碰 `src/boardwise/rules/`，正常不用重钉；若触碰了，照常重钉。

## D. 交卷

- 全量绿 `--basetemp=.tmp_pt_193 -n 4 --dist loadfile`；变异 ≥2 组（例如去掉槽锁、去掉 exe 扫描）；证据 `outputs/193/evidence.md`；PROGRESS.md append 一行；**不要 commit**。
- 红线：不动 git（写钩子文件除外）；不 `rm`（回收站）；企业项目名/型号零出现；不碰真机。

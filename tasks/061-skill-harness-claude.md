# 061：install-skill 认 harness（Claude Code）+ doctor skill 检查

来源：GitHub issue #11（岳亲笔）。README 承诺「Claude Code、DeepSeek、Kimi Code 哪个都行」，
但 `install-skill` 只写 `~/.kimi-code/skills/boardwise/`，Claude Code 的发现路径
（`~/.claude/skills/`）一个都没占——Claude Code 用户拿到的是**没有 SOP 的 toolchain**，
且 `doctor` 没有这一项检查，**没人能发现**。已造成的实际后果见 issue（#8 事故的叠加层）。

## 已查证的事实（主代理亲验，子代理不必重复）

- `src/boardwise/skill_install.py:81` 落点硬编码 `~/.kimi-code/skills/boardwise`；
  参数只有 `--uninstall`；`BOARDWISE_SKILL_HOME` 是裸目录覆盖。
- 全仓 `grep "\.claude" src/boardwise/ tools/ scripts/` 零命中。
- 捆绑 SKILL.md（`.kimi-code/skills/boardwise/SKILL.md`）已有 frontmatter
  （`name`/`description`/`whenToUse`）：`name`+`description` 正是 Claude Code skill 的
  识别字段，`whenToUse` 多余无害——**同一份文件，无内容分叉**。
- CLI 解析：`cli.py:983-998`（install-skill 参数）；命令体：`cli.py:18143` `_cmd_install_skill`。
- doctor：`run_doctor(DoctorProbe)` 是纯函数（`cli.py:17690`），探针采集在
  `_cmd_doctor`（`cli.py:18064`）；`DoctorCheck.skipped=True` 是「不作结论」的既有表达。
- 测试：`tests/test_skill_install.py`、`tests/test_doctor.py`。

## 架构裁决（不再变动）

### 1. skill_install.py：harness 维度

- harness 枚举：`"kimi"` / `"claude"`。
  - kimi → `Path.home() / ".kimi-code" / "skills" / "boardwise"`（现状，不变）。
  - claude → `Path.home() / ".claude" / "skills" / "boardwise"`。
- 环境变量覆盖：保留 `BOARDWISE_SKILL_HOME`（仅 kimi，向后兼容）；新增
  `BOARDWISE_SKILL_HOME_CLAUDE`（仅 claude）。各自只盖自己那一侧。
- `install(source, home=None, *, harness="kimi", today=None)`：harness 决定默认落点；
  `home` 显式传入时仍优先（既有测试驱动口）。`uninstall` 同样加 `harness`。
- 新增状态查询（doctor 用，保持 run_doctor 纯）：

  ```python
  @dataclass(frozen=True)
  class SkillStatus:
      harness: str          # "kimi" / "claude"
      path: Path            # 期望落点
      state: str            # "current" | "stale" | "missing" | "harness-absent"
  ```

  `skill_statuses(source) -> tuple[SkillStatus, ...]` 对两个 harness 各判一次：
  - harness 家目录不存在（`~/.kimi-code` / `~/.claude`）→ `harness-absent`
    （没人用这个 harness，跳过，不误报——与 editor-install 的 skip 哲学一致）；
  - 家目录在、SKILL.md 不在 → `missing`；
  - 字节与捆绑版不同 → `stale`；相同 → `current`。
  - 读不到（OSError）按 `stale` 之外的诚实处理：状态置 `missing` 并在 doctor detail
    里带 OS 原因，或新增 `"unreadable"`——实现者二选一，测试锁定。

### 2. CLI install-skill

- 新增 `--harness {kimi,claude,all}`，**默认 `all`**（README 说「哪个都行」，默认就要
  兑现；只写一侧要用户显式选）。`--uninstall` 与 `--harness` 组合：卸载所选各侧。
- 对所选每个 harness 独立执行、各打一行（现有措辞风格），**全部尝试**后才定退出码：
  任何一侧文件系统失败 → exit 1；其余（installed/updated/current/removed/absent）→ 0。
- help/description 改写：两个落点都写明白，提及 `BOARDWISE_SKILL_HOME{,_CLAUDE}`。

### 3. doctor 新增检查（离线、纯文件系统，排在 socket 之前采集）

- `DoctorProbe` 新增字段 `skill_statuses: tuple = ()`（cli.py import skill_install 的
  SkillStatus）；`_cmd_doctor` 在 `scan_editor_install()` 旁边采集：
  `probe.skill_statuses = skill_install.skill_statuses(resources.skill_md())`
  （`resources.skill_md()` 抛 RuntimeError 时留空，run_doctor 对该情形 skip）。
- `run_doctor` 每个 harness 追加一行：
  - name `skill-<harness>`，label「审查 SOP（SKILL.md）已装进 <harness> 且与本构建一致」；
  - `current` → ok；
  - `missing` / `stale` → **ok=False**，fix=`boardwise install-skill`
    （stale 的 detail 说清「装的是旧版/异版，本构建带的才是权威」）；
  - `harness-absent` → skipped=True（detail：本机没有 <家目录>，这个 harness 不在用）。
- 顺序：放在 editor-install 之后、socket 依赖项之前（同为离线项）。

### 4. 明确不做

- 不写 `~/.claude/CLAUDE.md`（那是用户的全局配置，侵入性越界；skill 落点已够发现）。
- 不动 README、AGENTS.md、SKILL.md 内容（SKILL.md 第 10 行提到的
  `~/.claude/skills/easyeda-agent/` 是**另一个项目**的陈述，与本修复无冲突）。
- 不做 harness 自动探测（PATH 里有没有 claude 不归我们管；家目录存在与否就是信号）。

## 验收

1. 新测试（`tests/test_skill_install.py` / `tests/test_doctor.py` 扩展，basetemp 用
   `.tmp_pt_83`）：
   - kimi/claude/all 三档安装落点正确；每侧幂等（二次 current）；异版备份
     `.bak-<date>`；uninstall 按侧；两个 env 覆盖各自生效。
   - doctor：`current`→绿、`missing`→红带 fix、`stale`→红带 fix、
     `harness-absent`→skipped 不挂；exit 码随之（全绿 0，有红 1）。
   - `--harness` 缺省 = all 的行为锁死。
2. 全量：`.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 全绿。
3. 手验一次：`BOARDWISE_SKILL_HOME=<tmpk> BOARDWISE_SKILL_HOME_CLAUDE=<tmpc>`
   `boardwise install-skill` 后两目录各有一份 SKILL.md，bytes 与捆绑版一致。
4. PROGRESS 追加条目（插第 6 行后，append 后 `grep -c` 防双写）。

## 边界与纪律

- 只碰：`skill_install.py`、`cli.py`（install-skill 参数/_cmd_install_skill/DoctorProbe/
  run_doctor/_cmd_doctor 采集段）、`tests/test_skill_install.py`、`tests/test_doctor.py`、
  `tasks/061*`、`PROGRESS.md`。其余一律不碰。
- 主代理随后亲跑全量 pytest + 复验，才 commit/push（岳已预批准推送）、
  gh issue #11 comment + close。

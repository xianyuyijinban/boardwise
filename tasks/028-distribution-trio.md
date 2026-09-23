# 028 — 内测分发三件套（exe + eext + skill 用户级）

> 目标：让**没有 Python、没有 repo** 的硬件工程师朋友，下载两个文件就能用上 boardwise。
> Release v0.4.15 的 notes 已对外承诺「免 Python 单 exe 制作中」，本批兑现。
> 主线：① PyInstaller 单 exe ② 0.4.19 eext ③ `install-skill` 把 SKILL.md 装进用户级 skill 目录。
> 收官：GitHub Release（exe + eext + 安装说明），岳转发即用。

## 一、现状事实（主代理已核，别重复探）

- CLI 唯一依赖 `websockets>=13.0`，`requires-python >=3.10`（`pyproject.toml`）——PyInstaller 友好。
- `update-connector` 默认从 **repo 相对路径** `connector/dist/index.js` 读 bundle（`cli.py:380` 的 `--bundle`
  默认值、`cli.py:4146`）；exe 化后这个相对路径不存在，**必须有冻结态资源解析**。
- eext 构建器已有：`connector/package.mjs`（connector/ 下 28 个历史 eext 为证）。
- SKILL.md 单文件 242 行（`.kimi-code/skills/boardwise/SKILL.md`）；用户级落点是
  `~/.kimi-code/skills/boardwise/SKILL.md`（Windows 即 `%USERPROFILE%\.kimi-code\skills\boardwise\`）。
- `boardwise.__version__ = "0.1.0"` 一直没动过；connector 0.4.19。本批**不做版本并轨**（避免 churn），
  但 `--version` 输出必须同时报两个号（朋友报障时要）。
- daemon 当前是可见 cmd 窗口跑的（岳能看到「boardwise daemon」窗口）——对朋友这是**优点**（可见、可 Ctrl-C），保持。

## 二、批 3a：PyInstaller 单 exe

1. **冻结态资源解析**：新增一个小 helper（比如 `src/boardwise/resources.py`）：`connector_bundle()`
   返回 dist/index.js 的 Path——`getattr(sys, 'frozen', False)` 时走 `sys._MEIPASS` 内嵌副本，
   否则走 repo 相对路径（现行为）。`cli.py` 的 `--bundle` 默认值改用它。同样 `skill_md()` 给 3c 用。
   PyInstaller `--add-data` 把 `connector/dist/index.js` 和 SKILL.md 打进 exe。
2. **spec/脚本**：`packaging/` 目录，放 `boardwise.spec`（或 `build_exe.py` 调 PyInstaller API）。
   单文件（`onefile`）、console 模式（daemon 要可见窗口）、名字 `boardwise.exe`。
   输出到 `packaging/out/boardwise.exe`（**别**用 repo 根的 `dist/`，那是 connector 的地盘）。
   PyInstaller 装进 `.venv`（本机）或独立 venv——它是构建依赖，不进 `pyproject` 的 dependencies
   （可进 optional 的 `dev` 组，若已有 dev 组就跟它走）。
3. **`--version`**：若 CLI 没有就加（先看 argparse 有没有）；输出两行：CLI 版本 + 内嵌 connector bundle
   版本（读 extension.json 或 bundle 内版本串，冻结态从内嵌副本读）。
4. **单测**：资源解析 helper 的 repo/冻结两态（冻结态 monkeypatch `sys.frozen`/`_MEIPASS`）；
   `--version` 输出含两个号。pytest 侧增量。
5. **真机验证（本机）**：构建出 exe 后——
   - 在**不含 repo 的干净目录**（如 `E:\tmp_dist_test\`，只放 exe）跑 `boardwise.exe --version`、
     `boardwise.exe doctor`（离线部分应工作；在线部分连本机 daemon 应 8/8）；
   - `boardwise.exe bridge start` 起 daemon、`bridge status` 见 test 窗口；
   - `boardwise.exe bridge call --action sys.connector_status`（验证内嵌 bundle 不影响 bridge 功能——
     注意这步需要 daemon 已配对，用本机现有 token）；
   - `boardwise.exe bridge update-connector --yes --instance <test窗>` 用**内嵌 bundle** 热更一次
     （证明冻结态资源解析真工作，不只是存在）。
   - **无 Python 环境验证**：本机模拟——把 `.venv` 暂时改名 + 用 `env -i` 或干净 PATH 的 cmd 跑 exe
     （PyInstaller onefile 自包含，过不了就是 spec 缺 hidden import）。websockets 是唯一第三方依赖，
     留意它的 hidden imports。
6. **体积与启动时间**如实记录（onefile 通常 10–20MB、冷启动 1–3s，可接受；>50MB 或 >10s 报我）。

## 三、批 3b：eext 0.4.19 + install-skill

1. `cd connector && node package.mjs`（或 npm script，看 package.json）产出
   `boardwise-connector-0.4.19.eext`，sha256 记录。
2. **`boardwise install-skill`**：把内嵌 SKILL.md 写到 `~/.kimi-code/skills/boardwise/SKILL.md`——
   - 目录不存在则建；已存在且内容不同 → 备份为 `SKILL.md.bak-<date>` 再写（朋友的机器上不许静默覆盖）；
   - 幂等（同内容重跑报 "already current"）；输出落点路径；
   - `--uninstall` 删掉那份（连带空目录），可选但便宜。
   - 单测：tmp home 下 安装/幂等/备份/卸载 四态。
3. **docs/getting-started.md** 加「朋友安装」一节（放最前或独立 `docs/install-friend.md`，岳裁）：
   下载 exe + eext → exe 放 PATH（或全路径）→ `boardwise bridge start` → 编辑器导入 eext → 配对 →
   `boardwise install-skill` → 完。每步一句人话，预期输出一行。

## 四、批 3c：Release 与验收

1. **GitHub Release**：`v0.4.19`（prerelease 标记沿用 0.4.15 的先例），附件
   `boardwise.exe`（sha256 进 notes）+ `boardwise-connector-0.4.19.eext`（sha256 进 notes），
   notes = 三件套安装步骤 + 「v0.4.15 的 exe 承诺兑现」一句 + 多窗口修复一句话卖点
   （后台窗口 ~30–46s 自愈，026 全线）。
2. **验收**：
   - 三线全绿（pytest `--basetemp=.tmp_pt_home` / connector / tsc）；
   - exe 在干净目录全链工作（3a.5 全部）；
   - eext sha256 与 Release 附件一致；
   - `install-skill` 四态单测 + 本机真装一次（装到 `%USERPROFILE%\.kimi-code\skills\` 后
     `boardwise install-skill` 再跑报 already current）；
   - Release 页面截图或 `gh release view` 输出落证据。
3. **真机纪律**：只碰 test/test2；`--project`/`--instance` 显式寻址；ROBOT 窗只读；不动 git 提交（主代理来）。

## 五、守卫

- exe **不签名**（没有证书），notes 里写明 SmartScreen 会拦一次、点「仍要运行」——别试图规避杀软。
- PyInstaller 的 `dist/`、`build/` 输出目录加进 `.gitignore`（若还没忽略）。
- 内嵌 bundle 与 connector/dist 必须同源同步——构建 exe 前先 `npm run build` 保证 dist 是 0.4.19 那份
  （sha256 `378a59bb…` 253495B）；spec/脚本里加断言或构建脚本按顺序执行。
- 朋友机器的配对 token 在他们自己机器上生成，文档别暗示共用 token。

## 六、交卷记录

（子代理交文本，主代理 append 并复验。）

### 028 批 3a+3b · 交卷（2026-09-23，子代理 agent-43）

- **3a 单 exe**：`packaging/out/boardwise.exe`，11 698 601 B（11.2 MiB），sha256 `5cff0611…`，内嵌 connector 0.4.19
  （`378a59bb…`/253 495 B）。构建：`python packaging/build_exe.py`（先 `npm run build` + 版本交叉校验 → PyInstaller
  6.22.3 onefile/console/upx=False，12.4 s）。**冷启动 5 次 0.70–0.79 s（median 0.72 s）**。
  新增 `src/boardwise/resources.py`（两态解析，冻结态镜像 `_MEIPASS/resources/`）、`packaging/{boardwise.spec,entry.py,build_exe.py}`；
  `cli.py` `_connector_artifacts()` 改走 resources + 新增 `--version`（两行：CLI 0.1.0 / bundle 0.4.19）；
  dev extra 加 `pyinstaller>=6.0`；`.gitignore` 加 `packaging/build|out`。
- **3a.5 真机（干净目录 E:\tmp_dist_test\，只有 exe）**：`--version` exit 0（冻结态自报 `_MEIPASS` 路径）；
  `doctor` **8/8**；`bridge status` ✔；`sys.connector_status` ✔；**用内嵌 bundle 热更 test 窗** → `ok: 0.4.19 -> 0.4.19`
  + `verified`（源路径就是 `_MEI…\resources\connector\dist\index.js`）；**无 Python 模拟**（venv 改名 + 干净 PATH）
  三项全 exit 0、doctor 8/8、venv 自动复原。
- **两处额外改动（主代理已审，接受）**：① `doctor` 新增 `--project/--instance` —— 3 窗在线时原为 **4/8**
  （WINDOW_UNSPECIFIED），加显式寻址后 **8/8**，hint 只给 connector 侧调用（不给 `ping`），附 2 条单测；
  ② getting-started 里"daemon 只认最后注册的窗口"是 023 前的过期事实，改为窗口路由表 + `--instance` 建议。
- **3b**：eext `boardwise-connector-0.4.19.eext`（sha256 `95923f2c…`，62 303 B，与 exe 内嵌同源）；
  `install-skill` 实现 + 四态单测 + 本机真装（装/幂等，落盘 sha256 = 仓库 SKILL.md）；getting-started 新增
  「第 0 步（朋友专用）」7 步。
- **三线**：pytest **1404 passed**（1388+16）· connector 405/0 · tsc clean。**变异 2/2 CAUGHT**
  （冻结态误判 3 红 / install-skill 静默覆盖 2 红）；还原 `resources.py d5834576…`、`skill_install.py b89b70ed…`。
- **纪律披露**：无 Python 模拟的脚本第一版把改名与复原放在两段 try，GBK 控制台打印 ✔ 抛异常导致 `.venv` 留在改名状态，
  人工 `mv` 复原并核验；随后改为单一 try/finally + stdout UTF-8 重跑通过。只影响 `.venv` 目录名约 1 分钟。
- 给 3c 的 sha：exe `5cff0611…`、eext `95923f2c…`。

### 主代理复验（2026-09-23）

- sha256 四处与交卷一致（exe `5cff0611…`/11 698 601 B、eext `95923f2c…`/62 303 B、resources `d5834576…`、
  skill_install `b89b70ed…`）。
- 亲手复跑三线：pytest **1404 passed**（118.5s）· connector 0 fail（&& 链通过）· tsc 干净。
- 亲手在干净目录跑 exe：`--version` 两行双号 + `_MEIPASS` 路径 ✔；`install-skill` 报 `already current` ✔
  （幂等实证，非首次安装）。
- `git status` 清单与交卷一致；`packaging/build|out` 已忽略。
- 待 3c：Release notes 岳过目后由主代理发布。

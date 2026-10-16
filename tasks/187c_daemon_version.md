# 任务书：187c — daemon 版本自检 + parts add 一步通

- 批号：**187c**　日期：2026-10-16
- 背景一：发版实测发现「daemon 是长驻进程，CLI 升级后旧 daemon 还在跑旧版代码」（doctor 已能查出，但日常使用中无任何提示——动作表是加载期常量，旧 daemon 缺新动作/旧错误码）
- 背景二：岳核验反馈——`parts add --verified` 要手填 deviceUuid+libraryUuid 有摩擦，「AI 读手册 → 一步喂 facts」走不顺

## A. daemon 版本自检

- `bridge` 各命令（call/status/update-connector 等经 daemon 的路径）执行时，hello/status 已能拿到 daemon 信息：若 running daemon 的 `__version__` ≠ CLI 自身版本，向 stderr 打一条 WARN：「daemon 运行 x.y.z ≠ CLI a.b.c（动作表是加载期常量，新动作/修复在旧 daemon 里不存在）；用 `boardwise bridge start` 重启 daemon」
- **只做 WARN，不自动重启**（重启切断在线 connector 连接，属真机操作）
- 频率：每命令一次，不刷屏；daemon 版本读不到（老 daemon 不上报版本）时按「版本未知」同样提示一次
- doctor 已有检查项不动；docs/bridge.md 坑表加一条「daemon 不自动换版」

## B. `parts add --resolve` 一步通

- 新参数 `--resolve`：自动补齐 `--device-uuid/--library-uuid`
- 通道：在线经 bridge 调 lib 搜索（`lib.recommend`/`eda.lib_Device.search` 现有动作族，按 MPN 或 LCSC 码），拿到 uuid 对落条目；**离线明确拒绝**（exit 2 + 「--resolve 需要在线 bridge；或手工 --device-uuid/--library-uuid」），不造假日 uuid
- 与既有参数组合：`--resolve` 与显式 uuid 同时给 → 显式优先；resolve 结果与 MPN/LCSC 对不上（搜索零结果/多结果）→ 拒绝并列出候选
- 端到端场景：AI 读完手册 → `parts add <MPN> --lcsc <C码> --resolve --facts f.json --verified` 一条命令清闸

## C. 测试与纪律

- 新测试 `tests/test_187c_daemon_version.py`：版本匹配/不匹配/读不到三态的 WARN；`--resolve` 离线拒绝 + 在线 mock bridge 成功路径 + 显式优先 + 多结果拒绝
- 全量绿：`.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile --basetemp=.tmp_pt_187c`（sources 在位）
- 红线：不动 git；删除走回收站；真实项目名零出现；bridge 动作表（protocol.py）不动——只读 hello/status 已有信息
- 证据 `outputs/187c/evidence.md`；PROGRESS.md append 一行
- 版本号不动（0.5.13 刚发）；**不要 commit**，交回主代理收口

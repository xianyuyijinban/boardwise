# 022 全新 clone 三 issue 修复（GitHub #1/#2/#3）

> 触发：岳 2026-09-22 15:50 在 GitHub 连开三 issue（全新 clone/旧编辑器实测），
> 原话"更硬的来了，你修完去看GitHub issue吧"。这三条全是 17:00 朋友内测的第一批拦路虎。
>
> 任务书即 GitHub issue 本身（xianyuyijinban/boardwise #1/#2/#3），此处只记分派与交卷。

## 分派

| issue | 标题 | 子代理 | 证据 |
|---|---|---|---|
| #1 | 夹具字节一致性守卫依赖 zlib（全新 clone 3 项必败） | agent-35 | `outputs/022_issue12.txt` |
| #2 | 未声明 dev 依赖（pip install -e . 后 pytest 跑不起来） | agent-35 | 同上 |
| #3 | 编辑器版本门槛在前置动作做完前不可判定 | agent-36 | `outputs/022_issue3.txt` |

## 裁决要点（Kimi 定）

- #1 选「比内容不比字节」（逐成员内容 sha256 + 文本成员 CRLF→LF normalize），
  **不选** ZIP_STORED 重存——夹具是黄金数据，守卫改比对逻辑不动夹具本身。
- #3 走 doctor 离线预检（读安装树 `resources/app/package.json`），不动 install.bat；
  `DoctorCheck.skipped` 语义保留（issue 作者点名），读不到不假装红绿。
- 两棒文件隔离：agent-35 碰 pyproject/install.bat/install.md/make_variants/test_injected_variants；
  agent-36 只碰 cli.py + test_doctor.py。

## 交卷记录

（子代理交卷后追加）

# bug98-C：控制台中文乱码（report 内容打 GBK 终端）

现场报告第 3 条：`report.json` 的 `source.notes` 中文在 GBK 控制台显示乱码——
数据本身没错（文件是 UTF-8），是 **CLI 往终端打印时**被 locale 编码替换成 `?` 或乱码。

## 做什么

1. 定位：`src/boardwise/cli.py` 的打印路径（checkup/review 的报告输出、bridge 错误
   信息）。Windows 上 Python 默认按 locale（GBK）编码 stdout。
2. 修法（最小、可测）：CLI 入口（`main()`）把 `sys.stdout`/`sys.stderr` reconfigure
   成 UTF-8（`errors="replace"` 兜底），**pytest 的 capsys 不许炸**——用
   `hasattr(stream, "reconfigure")` + try/except 守卫；已有同类处理的家族
   （172 的 `_bridge_call` 显式 utf-8）照同一精神，别新造第三把尺。
   文件写出（report.json 等）若已有显式 encoding 不许动。
3. 验收：新测试——一个含中文的 note/错误消息，在模拟 GBK locale 的 stdout 上
   打印后字节层可解回原文（或断言 reconfigure 被调用且编码 utf-8）；
   全量里捕捉套件相关的测试（capsys 家族）不许有任何一条因此变红。

## 红线

禁 git、禁 rm；pytest `--basetemp=.tmp_pt_bugC`；只许动 cli.py 的打印层 + 你的测试；
不动 rules/（不涉及指纹）；变异验证 ≥2；证据 outputs/bugC/。
注意并发：另两个前场在改 parsers/rules——你只碰 cli.py 与 tests/ 里你的新测试。

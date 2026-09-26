# 043：param-value-mpn-match 的 MPN 阻值解码偏差（4K7 → 7e+04）

日期：2026-09-26。来源：042 副作用实测（outputs/042_summary.txt §裁决 3）。

## 症状

042 修复后高速板新报 1 条 WARN：R27。模型里 Value=`4.7kΩ` 与 MPN
`RC0603FR-074K7L` 实际吻合，规则却把 MPN 解成 **7e+04 Ω**，误报不匹配。
疑似 MPN 解码器把 "4K7" 的 K 当后缀乘数又错读位序（4K7=4.7k，被解成 47k 或 7e4）。

## 要求

1. 定位 `param-value-mpn-match` 的 MPN 阻值解码路径，修 `4K7`/`4R7`/`47K4` 等
   EIA 中置字母写法；补解码单测（4K7→4700、4R7→4.7、10K2→10200、1M0→1e6）。
2. 高速板 R27 的 WARN 消失；dev/holdout 评测集指标回跑，高优精确率不许掉。
3. 边界：只动规则与测试；不碰解析器/connector/CLI；不提交既有夹具改动以外的文件。

pytest 必带 `--basetemp=.tmp_pt_home`；不 git。

## 候选：find_facts 同 MPN 兄弟优先取自身 C 号

`core.parts.find_facts` 先按 MPN 查、再按 C 号；当 shelf 上出现同一 MPN 的两个
LCSC 条目时，MPN 分支会按 shelf 顺序任取一个，板的 C 号本身得不到优先。
042 收尾已用**侧车策展镜像**绕开（把 AMS1117 的 facts 补到第二个条目），
本候选是规则层更鲁棒的解法：命中 MPN 后若其中某条目的 `lcsc` 等于传入的 C 号，
优先返回该条目。属契约变更（`find_facts` docstring 写明 "MPN first, then the
C-number"），故只记候选、不在 043 内执行。

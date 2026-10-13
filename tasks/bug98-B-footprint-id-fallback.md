# bug98-B：footprint 字段是库件 id 时的回退解析（报告第 2 条）

现场报告：原理图侧 `footprint` 字段常存**库件 id 十六进制**而不是封装名，
`pcb-footprint-consistency`（`rules/pcb/footprint.py:467`）对 28 件报「无从比较」。

## 做什么

1. 先取证：在本仓夹具/可得的工程档里找这种字段的真实样本（解析层打印或写个
   一次性 census 脚本落 outputs/bugB/），确认「id 形态」长什么样（纯 hex？带前缀？
   多长）以及**能不能在档内查到名字**（epro2 的库段/DEVICE 记录里 id→封装名
   有没有映射——001 的逆向笔记在 outputs/001/，先翻）。
2. 有映射 → 模型层回退：footprint 字段是 id 形态时按映射解析出封装名，
   **原值保留**（模型加 raw 字段或 evidence 里点名「按库件 id 反查」），
   比较逻辑不变；查不到 → 维持「无从比较」但 evidence 写明「id 无映射」。
3. 档内无映射 → 不修代码，把「库件 id 无档内映射、需要桥/库查询」写成
   能力边界文档（并给出桥侧可做的回退路径建议），**不许编映射**。

## 红线与验收

禁 git、禁 rm；pytest `--basetemp=.tmp_pt_bugB`；合成文本夹具自证（不碰既有夹具）；
全夹具判决零翻转是硬约束（有真实 id 字段的夹具若因此从「无从比较」变成可比，
那是**预期内的翻正**，要逐条对拍列明）；变异验证 ≥2；**指纹不许钉**（动了
rules/pcb/footprint.py 的话报两值给我）；证据 outputs/bugB/。
注意并发：另一个前场在改 parsers/epru.py 的 PCB 侧与 rules/pcb/distance.py，
你只许动原理图侧模型文件 + rules/pcb/footprint.py + 你的测试。

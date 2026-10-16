# 任务书：189A1 — 撤掉 PadGeometry.layer_id（假发现地雷）

- 批号：**189A1**　日期：2026-10-16　优先级：高（实板使用者拿它算出一条假安规发现报给工程师）
- 反馈：`layer_id` 是封装写死的层号，器件翻面不重写（127b 已修规则侧，但字段名仍诱导误用——名字看着就是「焊盘在哪层」，用错静默给错数）

## 修法（主代理已定，照做）

1. **`core/geometry.py PadGeometry`**：存储字段改名 `footprint_layer_id`；`layer_id` 从公开 API **移除**；`__getattr__` 拦截 `layer_id` 抛 `AttributeError` 带引导文案：「`layer_id` 已移除——它是封装写死的层号，器件翻面不重写（127b）；要封装原值用 `footprint_layer_id`，要铜实际所在层用 `effective_layer_ids`」
2. **消费面 75 处**（`grep -rn "\.layer_id" src/boardwise/` 排除 effective_/geometry.py 定义处）逐处裁决：
   - 要「封装原值」（如调试 dump、footprint 一致性、127b 自己的修复逻辑）→ `footprint_layer_id`
   - 要「铜实际在哪层」（间距/几何/规则判定——**大多数的本意**）→ `effective_layer_ids`（注意它可能是 None：R2-2 语义是没读过 pad 的兜底，消费方按现有处理惯例）
   - 每处改动在证据里记一行「文件:行 → 选了哪个、为什么」（这 75 处就是排雷清单）
3. **测试**：`tests/test_189a_layer_id.py`——`pad.layer_id` 抛 AttributeError 且消息含两个替代名；`footprint_layer_id` 保留 127b 的实测值；毕设FOC 夹具的 28 个底面焊盘回归（effective_layer_ids 不变）；全库 grep 级测试：`src/` 下不得再出现 `.layer_id`（豁免注释带批号）
4. **文档**：geometry.py docstring 更新（127b 那段历史保留，加一句 189A1 的字段移除）；docs/ 里若有 API 面文档提 layer_id 同步
5. 指纹：动了 rules/ 就重钉 test_126a recursive/direct + 台账
6. 全量绿 `--basetemp=.tmp_pt_189a1` `-n 4 --dist loadfile`；变异验证 ≥1 组（把 __getattr__ 拦截删了→测试红）
7. 红线：不动 git；删除走回收站；真实项目名零出现；证据 `outputs/189a1/evidence.md`（含 75 处逐处裁决表）；PROGRESS.md append 一行；**不要 commit**

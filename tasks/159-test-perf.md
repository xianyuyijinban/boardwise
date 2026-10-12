# 159 测试套件性能瘦身（2026-10-11 立）

## 诊断（静态摸底，证据：outputs/147c/ 既有 profiling + 仓库内注释）

全量 ≈1960s（1639s 主套件 + 321s test_136 单跑）。**主因不是夹具解析**
（fixtures 里最大 1MB，解析占比 <0.5%），而是 **golden 板求解器
`generate_plan`（layout.py route_nets 网格 Dijkstra，单次 ~60s）被各测试文件
重复重算 ~15–20 次**，缓存按文件割裂（module scope）或干脆没有。

热点（实测）：test_136_wire_spacing 321s（零缓存，5 用例各求解）、
test_engine_boundary 252s（4 用例各求解）、test_141 247s（3 条 monkeypatch
用例必须重建，属正当开销）、test_117 240s（drawcompiler 6 key）、
test_generate/test_layout/test_137/test_replay/test_candidate_draw/test_143e
各 ~60s。

## 本批范围（文件白名单）

- 新建 `tests/_golden.py`：session 级共享 golden plan 缓存（functools.cache）
- 改 `tests/test_136_wire_spacing.py`、`tests/test_engine_boundary.py` 接入缓存
- 可选转调：test_generate / test_layout / test_137 / test_replay /
  test_candidate_draw / test_143e 的本地缓存改为转调 `_golden`

**必须保留的例外**：test_generate.py 纯度测试（故意重建一次）、test_141 三条
monkeypatch 用例、一切 patch 求解器内部的用例——这些绕过共享缓存。

预期收益 ≈ -1400s（1960 → ~600s）。

## 明确不做

- 不碰 tests/conftest.py、test_bridge_cli.py、test_doctor.py、
  src/boardwise/cli.py（157 daemon 批正在改）
- 不动 src/ 求解器本体（改几何会翻大量 pin 死数字，另批裁决）
- 不上 pytest-xdist（等 157 落地后单独一批，免得 addopts 影响在跑的代理）
- 子代理不跑全量，焦点自管；全量由主代理在两批落地后收口

## 隔离性注意

共享缓存的前提是各用例对 plan/model 只读。执行前必须 grep 核实有无对缓存对象
的写操作（含 strip_dangling_nets 是否原地改 model）；有变异风险的按 deepcopy
发还（先测 deepcopy 代价）或退回文件级单次构建。

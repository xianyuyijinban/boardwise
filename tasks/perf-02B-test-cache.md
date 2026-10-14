# perf-02B：测试侧缓存修复（C6/C7 + C12 卫生）——白花的热力求回来

岳 2026-10-13 立的性能优化，第一波低风险组的测试半。依据在
`outputs/perf/heatmap.md` §6。**只许动 tests/**；语义等价；全量绿是硬约束。

## C7 `run_pcb_review` 测试侧缓存（收益：全量 −290s，最大头）

实测：全量 383 次/444.2s，调用数≈文件内测试数（同文件反复对同一夹具跑同一 runner）。
做法：在 `tests/_golden.py`（159 的缓存家）旁边或其中加 runner 结果缓存——
key = 夹具路径 + 内容 sha256 + runner 参数指纹。**返回的对象必须只读消费**——
若测试会改返回值，缓存要返回深拷贝（用 copy.deepcopy，别想当然共享）。
先抽查 3 个调用点确认返回值没被改写，再定共享/拷贝。

## C6 `test_117` 的 `_PLAN_CACHE` 从未命中（−120~160s）

实测：key 含 `id(ctx.book)`，每条测试新建 book → 恒 miss。修 key：
用 book 的内容指纹（或构造它的参数元组）替代 id()。**那 6 条「跑完搜索才 skip」
是有意守门**（跑一遍确认真的没有 plan）——修 cache 让它们二次跑命中即可，
不许把 skip 门槛拿掉。

## C12 卫生（顺手）：注入夹具的 mtime 漂移

`tests/test_injected_variants.py` 的 drift 守卫测试原地 `write_bytes` 再 finally 还原
——进程被杀会留下漂移文件。改成复制到 tmp_path 再漂移。别的测试形状不许动。

## 红线与验收

禁 git、禁 rm；pytest `--basetemp=.tmp_pt_p2b` -n 4 封顶；全量两次计时对比
（前/后）落证据；变异验证 ≥2（把缓存 key 改错 → 必须有测试红；把 C6 的门守住
——skip 变 pass 或反过来都要有测试看着）。证据 outputs/perf02B/。
并发提示：另一个前场在改 src/，你别碰；tests/ 里你只动上面点名的文件。

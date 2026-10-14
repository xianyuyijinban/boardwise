# perf-02A：生产侧备忘化（C1/C2/C3）——读多次的改成算一次

岳 2026-10-13 立的性能优化，第一波低风险组的生产半。依据全部在
`outputs/perf/heatmap.md`（§6 候选清单），本包做 C1/C2/C3 三件，全是**语义等价的
备忘化**——同输入必须同输出，全夹具判决零翻转是硬约束。

## C1 `load_parts()` 反复重载（收益：全量 −92s，生产 checkup −0.7s）

实测：单次 review 调 296–312 次、全量 43,506 次/92s、2.26ms/次。找到定义点
（大概率在 core/ 或 rules/ 的 parts 货架加载），做**进程内缓存**：
key = 规范化路径 + 文件 mtime（或内容 sha256——选哪个要想清楚并写注释；
tests 会写临时 parts 文件，mtime 粒度够不够要实测）。缓存失效测试必须有：
同路径内容变了要读到新的。

## C2 `read_stackup` 每查询重扫全板（−42s）

实测 47 万次调用/42s/89µs。读数只依赖 board 的层表。做 per-board 备忘：
key 用 board 对象 identity（`id()`）+ 层表指纹，或挂到 board 对象的私有槽
（`board._stackup_cache`，dataclass 加 `field(default=None, repr=False,
compare=False)`——别把缓存泄进 eq/hash）。注意 `__eq__`/`hash` 污染是
本仓踩过的坑类，选方案时写明。

## C3 `layout.classify` 器件框线性扫描（−60~80s）

160M 次调用 + 160M 次 dict.values()。换并集集合缓存（集合在器件集不变时复用）。
失效条件：器件集变了必须重建——用「器件 dict 的 identity + len」做快键，
内容变了靠 len/identity 不够时如实重建（宁可多建不许错）。

## 红线与验收

禁 git、禁 rm；pytest `--basetemp=.tmp_pt_p2a` -n 4 封顶；**只许动
src/boardwise/**；rules/ 若动报指纹两值给我统一钉。变异验证 ≥2（把缓存拿掉/
写错 key → 必须有测试红）。**判决零翻转**：全夹具 census 前后对拍
（outputs/bugA/diff_census.py 的手法可借）。性能验收：census 全量计时前后对比 +
受影响测试文件计时对比，数字落证据。证据 outputs/perf02A/。
并发提示：另一个前场在改 tests/，你不许碰 tests/ 下既有文件（新测试文件可以建）。

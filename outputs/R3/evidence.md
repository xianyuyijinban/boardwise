# R3 证据（v0.6.0 KiCad 第二宿主：侦察 → 离线审查最小闭环）

## 阶段一：侦察（门槛已过）

《KiCad 能力矩阵》见同目录 `capability-matrix.md`（任务书说放 `docs/` 还是 `outputs/R3/` 由主代理定，目前先放这里）。要点：

- KiCad 10.0.6 从官方 GitHub 发布页下载，sha256 已核对；用 7-Zip 解包到 `D:\tools`，没有运行安装程序，也不进 PATH。
- **离线读原理图 + PCB：可行**。PCB 的网络和几何全部写在文件里。原理图没有网络，但可以由几何推出：引脚变换、结点、标签、电源符号的连通规则都在自建夹具上用 KiCad 自己的网表器逐引脚验证过。
- 自动化通道：
  - kicad-cli 无界面，全线可用；ERC/DRC 输出逐条的 JSON；
  - pcbnew SWIG 在 10.0.6 下可用（夹具就是用它生成的）；
  - IPC API 必须开着 GUI；kipy 0.8.0 的原理图模块一 import 就报错（实测），在线桥建议等 KiCad 11 再说。

## 阶段二：最小闭环

| 交付 | 内容 |
|---|---|
| `src/boardwise/parsers/kicad.py` | S 表达式读取；单页平铺原理图的几何连通求解 → `DesignModel`；`.kicad_pcb` → `BoardGeometry` 和 PCB 视图的 `DesignModel`；层次图和总线**按名拒绝** |
| CLI 分派 | `SUPPORTED_SUFFIXES` 加入 `.kicad_pro` / `.kicad_sch` / `.kicad_pcb`；`_load_model` 按扩展名分派；`checkup` 的 PCB 门和探测认得 KiCad；`run_pcb_review` 把「从文件取出若干块板」抽成 `_review_units`，epro2 和 KiCad 共用规则循环（epro2 路径行为不变，全量测试为证） |
| 夹具 | `tests/fixtures/kicad_min/`（自建，生成器 `tools/R3_make_kicad_fixture.py`）+ KiCad 自己的两份读数：`kicad_min.net`（kicad-cli 网表）、`kicad_min.pcbnew.json`（pcbnew 几何） |
| 模型 | 规则侧**零改动**；`DesignModel` / `BoardGeometry` 没加字段，只按约定填（层号桥接、去掉库昵称写在模块文档和能力矩阵里） |

### 对拍结果（tests/test_r3_kicad.py）
- **原理图**：几何求解得到的 (网名, 位号, 引脚) 多重集与 kicad-cli 网表**完全相等**，两颗 R3 都算在内。
  夹具覆盖了 rot 0/90/180/270、mirror x/y、带结点的 T 型交点、挂在导线中段的标签、同名的多个电源符号、全局标签。
- **PCB**：16 个焊盘的绝对坐标与 pcbnew 一致（误差 < 1e-6 mil，实测最大 1.8e-12），网络、角度、铜层逐个相等；
  走线、过孔、铺铜层与网逐个相等；板框与 pcbnew 的边框 bbox 一致（扣除 0.05 mm 线宽）。底层封装（R1）的翻转变换也在其中。
- **PCB 视图网表**与原理图网表相同。

### 规则在 KiCad 输入上出的判决
| 规则 | 判决 | 夹具里的缺陷 |
|---|---|---|
| `conn-duplicate-designators`（L1） | ERROR R3 | 两颗都叫 R3 |
| `decap-required-caps`（L2） | WARN U1 2 脚只有 100nF，要求 ≥22µF | AMS1117 输出电容不足（货架事实 C6186） |
| `shunt-sense-link`（L1） | INFO R4 两端没有 IC | 10mΩ 采样电阻没人读 |
| `pcb-component-spacing`（距离类） | WARN C2 和 R3 相距 5.9 mil | KiCad 自己的 DRC 报的是同一处 0.15 mm（= 5.9 mil），两边一致 |
| `pcb-decap-distance`（距离类） | WARN C2 离 U1 567 mil | C2 放得远 |

`checkup --file kicad_min.kicad_pro` 端到端跑通（退出码 1，生成 `report.json` / `board-report.md` 等）；`review` 的原理图视图和 PCB 视图都能读。

### 过程中发现并修掉的问题
1. 一开始假设符号变换是「先镜像再旋转」，结果 kicad-cli 网表显示 `rot 90 + mirror y` 那颗 R3 的两个引脚对调了。改成「先旋转、再在图纸坐标里镜像」后逐引脚一致。
2. KiCad 的 Footprint 带库昵称（`Package_TO_SOT_SMD:…`），`pcb-footprint-consistency` 因此误报了一条 ERROR（封装族 `to` ≠ `sot`）。解决办法是模型里只放名字，完整 id 存 `props`。
3. 夹具第一版的 PCB 里，有一段走线无意中压过了别的网的焊盘，用 KiCad DRC 查出后重新布线。现在 KiCad DRC 只报两处故意留的缺陷。

### 已知、没有修的
- `pcb-footprint-consistency` 报「R_0603 有两套焊盘几何」：这是两颗 R3 同名的连带效应（规则按位号收集焊盘，把两颗的 4 个焊盘算到了一起）。在立创输入上也会这样，规则没改。

## 变异验证（cp 备份 + sha256 还原，6 组全部变红）
| # | 变异 | 结果 |
|---|---|---|
| M1 | 引脚变换退回「先镜像再旋转」 | 4 红 |
| M2 | 忽略结点 | 3 红 |
| M3 | 标签不再挂到导线中段 | 4 红 |
| M4 | 焊盘绝对坐标的旋转方向写反 | 1 红 |
| M5 | 保留封装库昵称 | 2 红 |
| M6 | 根图本地标签保留 `/` 前缀 | 4 红 |

## 测试计数
pytest 全量（`-n 8`）：5403 passed / 20 failed / 36 skipped。基线 5382 / 20 / 36，新增 `test_r3_kicad.py` 21 条。20 条红与基线逐条相同：19 条环境原因，另 1 条是 `test_126a` 指纹，由 #77 修。connector 和 dsh-plugin 未改动。

## 遗留 / 需要裁决
1. 能力矩阵放 `docs/` 还是 `outputs/R3/`。
2. 层次图和总线目前直接拒绝（退出码 2，给出原因）。下一步支持层次图时，网名要带上图纸路径的规则。
3. KiCad 的禁布区（rule area / keepout zone）这次没读。如果 R2（#79）合并，可以映射到 `pcb-keepout-violation`，KiCad 的禁布语义同样要实测确认。
4. KiCad 原生 ERC/DRC 的 JSON 可以作为 `drc` 段的数据源（类似立创的宿主 DRC），本 PR 没有接。
5. 夹具里的 `kicad_min.net` 头部带着生成机器上的源文件路径（`D:\tools\kicad-work\…`）。这是 KiCad 自己写进去的，我没改，免得动了基准文件的原样。

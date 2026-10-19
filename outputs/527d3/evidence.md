# 527D3 证据 —— `entry.category` 的十四个直读点收口到 `declared_category`

工作树（HEAD `dbd5b9a`，版本 0.5.18）。零 git 操作，改动全部留在工作树。

## 1. 入口：`core/partkind.py`（本批新增/沿用）

| 符号 | 签名 | 说明 |
|---|---|---|
| `declared_category` | `(entry, *, allow_machine) -> str \| None` | 前一个子代理写的四态读，本批**只读不改**（签名与语义未动） |
| `CATEGORY_ACCEPTED/GATED/ABSENT` | 字符串常量 | 三个**结果**（不是档位） |
| `category_verdict` | `(entry, categories, *, allow_machine) -> str` | 本批新增：把 `declared_category` 的 `None` 拆成「档位不够（gated）」与「根本没这个分类（absent）」。`category in categories` 是规则自己的主语集，档位是唯一挪动的东西。草稿在任何档位都是 `GATED`（H5 同构）|

`rules/facts.py` 新增 `category_gate_finding(**...)`：机器档/草稿分类那一行免责 finding 的**唯一**形状与文案来源（`_category_absent_reason` + `machine_trust_note` 的措辞，没有第三套）。`_category_state` 改为走共享入口，行为和 527D 时逐字相同。

## 2. 十四个读点：档位 + 三态行为

「机器档」列：`接受` = 本读点的档位问题就是数字问题（`allow_machine=True`），机器档分类照旧命名主语；`免责` = 该档位不读它，读者把这一件**交回给调用方**，调用方出一行免责/UNKNOWN。

| # | 文件:函数 | 档位 | 人签档 | 机器档 | 分类不存在 | 三态的载体 |
|---|---|---|---|---|---|---|
| 1 | `rules/pcb/mcureset.py::_read_mcus` | 结论（`allow_machine=False`） | 出复位/启动行 | **免责** | 跳过 | 返回 `(readings, gated)`；`_tier_gate_row` |
| 2 | `rules/pcb/mcusupply.py::_read_mcus` | 结论 | 出供电组行 | **免责** | 跳过 | 同上 |
| 3 | `rules/pcb/crystal.py::_mcu_oscillators` | 结论 | 出晶振行 | **免责** | 跳过 | 同上（+`crystalkeepout` 也读到） |
| 4 | `rules/pcb/crystalkeepout.py::crystal_designators` | 结论 | 出逐层铜行 | **免责** | 跳过 | 返回 `(found, gated)`，`McuCrystalKeepout._tier_gate_row` |
| 5 | `rules/pcb/regulator.py::_regulator_readings` | 结论 | 出电容行 | **免责** | 跳过 | 返回 `(readings, gated)` |
| 6 | `rules/pcb/fbplacement.py::_fb_ic_on_tap` / `fb_dividers` | 结论 | 出分压行 | **免责** | 跳过 | `fb_dividers` 返回 `(dividers, gated)`；`_fb_ic_on_tap` 只做**成员**判断（档位闸已在上游 `_regulator_readings`），三态在 docstring 里写明 |
| 7 | `rules/pcb/foc.py::_category_of` / `_motor_drivers` | 结论 | 出 motor-driver 行 | **免责** | 跳过 | `_category_of` 返回 `(category, gated)`；`_motor_drivers` 返回 `(found, gated)`（gated 带 `category`+`category_trust`） |
| 8 | `rules/pcb/foc.py::power_mosfets_of` | 结论 | 出 FET 行 | **免责**（Q 门仍独立可用） | 跳过 | 返回 `(fets, gated)`；Q 门的 basis 在档位不够时写「档位不够，本规则不采信」而不是「分类为空」 |
| 9 | `rules/pcb/focground.py::_looks_like_resistor` | 结论 | 两道门 | **免责**（第三返回值） | 跳过 | 返回 `(looks, basis, gated)`；`gated` 非空时进入行 evidence，替换「states no readable resistance」 |
| 10 | `rules/archclosure.py::_opamp_output` | 结论（`REQUIRES_HUMAN_VERIFIED`） | 运放闭合/UNKNOWN | **UNKNOWN 行**（第 4 槽） | 跳过 | 返回 4 元组，第 4 槽是 `category_absent_reason` 句子；调用方出 `state="UNKNOWN"` + `missing_fact` |
| 11 | `rules/railratings.py::PathLdoDissipation._rows` | **数字**（`allow_machine=True`） | 耗散行 | **接受**（草稿档才 gated） | 跳过 | gated 出 UNKNOWN 行，`missing_fact` 点名档位 |
| 12 | `core/architecture.py::controller_evidence` | 结论 | 货架证据 | 不认（改吃符号证据，仍出声） | 不认 | 见 #14 的披露行 |
| 13 | `core/architecture.py::_rails` / `_ldo_output_note`（:694/:714/:757） | 结论 | 命名轨/源候选 | 不认 | 不认 | 同上 |
| 14 | `core/power_domains.py::infer_net_domains` | 档位由调用方给（`allow_machine`） | 命名轨压 | 不认，但**出 UNKNOWN guess** | 不认且无声 | gated 时给该网写 `DomainGuess(state=UNKNOWN, detail=<档位句子>)`；`domain_of` 新增 UNKNOWN 分支把 `detail` 当 `why_not` 返回 |

`core/architecture.py` 的四次读点共用**一条每板披露行**（`gated_classifications` + `_render_board`）：架构走查产出的是骨架不是逐件 finding，四个读点各写一句会变成同一件事的四份噪声。这一条把「本走查不据此认定 + 要人签字」写进板自己的账里。

`rules/facts.py`（`_category_state`、`LdoDropout`）、`rules/decap.py::looks_like_capacitor`、`rules/params.py::_kind_of`、`rules/paramspec.py::independent_rail_price` / `TvsStandoffRail` / `LdoFixedOutput` 是前一个子代理已经改好的四个文件（数字档为主），本批**未重写**，只补了 `category_gate_finding` 这一个共用出句口。

签名改动与调用点补齐（`src/` + `tests/` 全量 grep 过）：

- `_read_mcus`（mcureset / mcusupply）：`tests/test_186_pdf_facts_path.py`、`tests/test_187b_gate_holes.py`
- `_mcu_oscillators`：`rules/pcb/crystal.py`、`rules/pcb/crystalkeepout.py`、`tests/test_131f_mcu_crystal_keepout.py`
- `_regulator_readings`：`rules/pcb/regulator.py`、`rules/pcb/fbplacement.py`（2 处）、`tests/test_131b`、`tests/test_131c`、`tests/test_186`、`tests/test_187b`
- `crystal_designators` / `fb_dividers`：规则体 + `tests/test_131c`、`tests/test_164a`
- `_motor_drivers` / `power_mosfets_of` / `FocPowerLoopArea._loops`：`rules/pcb/{foc,focground,focthermal}.py` + `tests/test_133b`、`tests/test_164a`
- `_looks_like_resistor`：`rules/pcb/focground.py`（2 处）。返回 3 元组，`[0]` 取用处的既有测试（test_186/187b）**无需改动**

## 3. 新增测试 `tests/test_527d3_declared_category.py`（24 条）

| 组 | 条数 | 内容 |
|---|---|---|
| ① | 2 | 入口四态逐条（人签/机器+allow/机器+拒/草稿/空 entry/空分类）+ `category_verdict` 三结果 |
| ② | 17（`pytest.mark.parametrize` 覆盖全部改过的读点） | 每个读点三态：人签不出 gated；机器档「要么是主语（数字档）要么出 gated + 有话说」；草稿必 gated |
| ③ | 1 | H5 同构：草稿在 `allow_machine=True` 下也被挡（入口 + `_kind_of` + `looks_like_capacitor`） |
| ④ | 1 | `category_provenance` 有无不影响三档任一组合的判定（无参/有引文 × 三档 × 两档位 = 12 组） |
| ⑤ | 3 | 端到端：同一块合成板，结论规则从「有结论」变免责行；数字规则（`pcb-mcu-supply-groups`, `allow_machine=True`）两档产物**逐字节相同**；数字规则用默认档位时出免责而非静默 |

## 4. 指纹重钉（`tests/test_126a_pcb_review_plumbing.py`）

| 量 | 改前（工作树上的钉值） | 改后 |
|---|---|---|
| direct-only recipe | `4733469e` | **`b05d3384`** |
| recursive recipe | `78b346aa` | **`674e07e1`** |

本批落在 `rules/` 下 **15 个文件**（6 个直接：`facts.py`、`decap.py`、`params.py`、`paramspec.py`、`archclosure.py`、`railratings.py`；9 个 `pcb/`：`crystal.py`、`crystalkeepout.py`、`fbplacement.py`、`foc.py`、`focground.py`、`focthermal.py`、`mcureset.py`、`mcusupply.py`、`regulator.py`）。ledger 注释已写明「527D3 改了 15 处规则体」及重钉前后的四个值。

## 5. 夹具对拍（`outputs/527d3/probe_fixture_diff.py` → `fixture_diff.json` / `fixture_diff.log`）

夹具 `ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2`，把所有模块的 `read_default_library` 重绑到注入架，跑**整条** PCB 审查与原理图审查：

- **人签档（= 出厂货架）**：连跑两次逐条相同（确定性自证）。出厂货架 109 条里 `category_trust` 键出现 **0 次**（`blocklib/parts.json`、`tests/**/*.json` 全库 grep 0），所以闸对任何夹具路径可证是空操作；夹具冻结表测试（126b/126c/133d/164c/190/191d/192b）逐条仍绿。
- **机器档**（把 11 条 `ic.mcu`/`ic.ldo`/`ic.motor-driver`/`fet` 翻成 `machine_verified` + 补 `category_provenance`）：

| 面 | 出厂 | 翻转 | 减少 | 新增 |
|---|---|---|---|---|
| PCB 审查 | 134 | 113 | 37 | **16** |
| 原理图审查 | 29 | 29 | 4 | **4** |

新增 16 条**全部**是免责行，按规则分：`pcb-mcu-{reset-boot,supply-groups,crystal-placement,crystal-keepout}` 各 1、`pcb-regulator-{cap-distance,fb-placement}` 各 2、`pcb-foc-{decap-proximity,return-path,thermal-exit-path,thermal-via-array,thermal-via-style}` 各 1~2、`pcb-decap-distance` 2。原理图侧 4/4：

1. `decap-required-caps`（U5）——message 多出 `machine_trust_note` 的「分类来源：机器核验…未人工确认」（**527D 的 H2 修**，本批未改这句），属机器档路径；
2. `arch-nrst-closure`（U1）——控制器证据从「货架 category=ic.mcu」降到符号的 82 个 `P<端口><数字>` 引脚（本批的读点 #12）。**仍然出声**，只是换了独立证据；这是 `controller_evidence` 对 `library=None` 的既有降级口径；
3. `sel-ldo-fixed-output`（U5/U6）——source 串多出机器档标注（527D/522 的既有口径）。

减少的 37 + 4 条全部是**被翻转件的量测行**（`pcb-mcu-supply-groups` 7、`pcb-mcu-crystal-placement` 7、`pcb-regulator-cap-distance` 8、`pcb-mcu-crystal-keepout` 4、`pcb-foc-decap-proximity` 3、`pcb-decap-distance` 2、其余各 1）。`pcb-decap-distance` 那 2 条是 **527D 在 `shelf_declaration` 里的闸**造成的（判型路径对机器档分类一律不认），不是本批新引入的读点。

**人签档产物逐字节不变**：出厂架下 PCB/原理图两次跑都逐条相同，且出厂架无任何 `category_trust` 键 ⇒ 机器的分类路径在夹具上是不可达的，闸在人签档上是恒等映射。

## 6. 变异（`cp` 备份 + `cmp` 逐字节还原，禁 `git checkout --`）

| 组 | 变异 | 结果 | 还原 |
|---|---|---|---|
| M1 | `core/partkind.py::declared_category` 对 `machine_verified` **无视 `allow_machine`** 一律放行 | **CAUGHT** — 新增测试 17 failed / 7 passed | `cmp` 一致，sha256 `1a7b777e70ac…` |
| M2 | `rules/pcb/mcureset.py::_read_mcus` 把 `CATEGORY_GATED` 当「跳过」（`continue`，gated 列表不再填） | **CAUGHT** — `test_every_read_point_answers_three_states[pcb/mcureset._read_mcus]` 与 ⑤ 的结论规则那条红 | `cmp` 一致，sha256 `8a1e025f6d74…` |

## 7. 回归

同一时刻只起一个 pytest、带 `--basetemp=.tmp_pt_527d3b`，只跑本批相关子集（未跑全量）：

- 规则族：131b/131c/131d/131e/131f、133b/133c/133d、164a、175、176、186、187b、011d、017、064、092、093、094、126a/126b/126c/126d、164c、168、185、189b、190、190s、191b、191d、192b、192c、522、527×3、checkup_cli、039c、architecture → **961 + 212 = 1173 passed, 1 skipped**（分两批跑，见上文命令）
- `tests/test_524…` 等未涉及；**未跑全量**（按纪律）。

## 8. 未确认 / 留给主代理

- `PROGRESS.md` 与 `tasks/527_pre060_loose_ends.md` 的 527D3 结项文字**未写**（按角色分工，文档与任务书归主代理）。
- 端到端 ⑤ 用的是合成板（无夹具条目带机器档分类，夹具上这条路径不可达）；夹具侧的证据是上面的对拍（机器档由探针注入）。

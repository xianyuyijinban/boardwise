# 527D 证据：`parts classify` 与 `category_trust`，以及这条改动自己的挖洞结果

日期：2026-10-19　版本：v0.5.18（内测）　相关：`tasks/527_pre060_loose_ends.md` §527D、TASKMAP 523

## 1. 要治的缺口（TASKMAP 523）

`parts hunt --apply-facts` 能把数据手册里的事实过 521 的六道闸写成 `facts_trust:
machine_verified`，但**写不了 `category`**。而 `rules/facts.py::_category_state` 对一个
`category` 为空的条目一律回 UNKNOWN —— 于是「机器核验过的件」在报告里仍然只能进「未审」桶，
唯一出路是手改 `blocklib/parts.json`。

## 2. 落地的形状

- 新命令 `parts classify <entry> <category> [--from] [--page] [--quote] [--cache] [--library] [--json]`。
  词表外拒绝（列 12 个顶层族 + `ic.*`）；entry 找不到拒绝且不新建；证据三件套齐全 → 机器档，
  全不给 → 人工档（明说「无引文，按人工签署记账」），给一半 → 拒绝。
- `PartEntry.category_trust`，缺省 `verified`：109 条旧条目**字节与行为都不变**
  （`verified` 不落盘；`null`/拼错值按 522 对 `facts_trust` 的同一条规矩报错——实测六个非法值
  两个字段逐条同构）。
- **两道闸都问分类自己的档位**：`_category_state`（facts 规则）与
  `core/partkind.shelf_declaration`（判型路径的真闸）。
- 复用而非新写：`_shelf_lookup`、521 的引文闸常量与 `quote_is_on_page`、`hunt.extract_pages`/`Cache`、
  `_write_shelf_document`/`_write_parts_json`、`CATEGORY_VOCABULARY`（族清单由 `category_families()` 派生）。
- 只动两个键：写入前备份 `.tmp` + 真验证器复验 + 失败回滚；`blocklib/parts.json`
  实跑 `json.dumps(...)` 与原文字节相同（109 条）。

## 3. 挖洞（独立只读红队）8 条，全部核实成立

| # | 严重度 | 洞 | 处置 |
|---|---|---|---|
| H1 | **高** | `_hunt_write_shelf` 逐字段手抄重建条目，**漏掉 `category_trust`** → 机器档分类静默升格成人工签署；触发路径正是文档主推的「先 classify 再补 facts」 | 已修 + **结构性**回归（由 `PartEntry` 的 dataclass 字段推导，新增 `*_trust` 字段漏抄就红） |
| H2 | **高** | `machine_trust_note` 只读 `facts_trust` → 「facts 人签 + 分类机器授」的 finding 无任何免责 | 已修：两句分开，并说清哪一半未确认 |
| H3 | **高** | `entry.category` 直读点成片（14 个文件）绕过两道闸 → 机器档分类仍能驱动结论规则 | **未修**（527D3）。需要分档感知的 `declared_category(entry, allow_machine=…)` + 逐条判定规则属于数字还是结论；发版夜不动，**docs 与 release notes 已把承诺收窄到实际生效处** |
| H4 | 中 | `checkup.shelf_can_drive_rules` 不看 `category_trust` → 机器授分类的件被移出「未审」、写进「已审」，同时规则对它回 UNKNOWN | 已修 + 回归 |
| H5 | 中 | `category_trust: candidate` 在 `allow_machine=True` 下被当已分类——比 `machine_verified` 更宽 | 已修：candidate 无条件挡（与 facts 侧同构） |
| L1 | 低 | `_category_absent_reason` 顺序会发出**错的工单**（candidate facts + machine category 时叫人去签分类，签了也没用） | 已修：顺序与 `_category_state` 对齐 + 守卫 |
| L4 | 低 | 回滚 `copy2` 无 try，回滚失败 → traceback + 货架停在半写状态 | 已修：明确报「回滚也失败 + 备份在哪」 |
| L2/L3 | 低 | `--json` 的 `ok: true` 先于货架落盘（039 工具链既有约定）；别处改 `category` 会继承旧机器档；`category` 与 `facts` 无交叉校验 | 未修，记入 527D3 |

**这一节的重点是 H1**：它不是「没实现」，是「实现好了被另一个命令悄悄改回去」，而且改回去的
方向正好是「机器的结论变成人的签字」。所以那一处用**结构性**测试钉住（从 dataclass 字段推导
每个 `*_trust` 必须出现在重建里），而不是一条夹具——夹具只防一个已知用例，结构测试防下一个字段。

## 4. 读数

```
pytest tests/test_527_parts_classify.py          # 30 passed
pytest tests/test_522_facts_trust.py             # 37 passed
pytest tests/test_039_parts_toolchain.py         # 29 passed
pytest tests/test_facts_rules.py                 # 26 passed
pytest -k "parts or catalog or facts or shelf"   # 570 passed / 1 skipped（子代理跑，166s）
```

变异（`cp` 备份 + 逐字节还原，未用 `git checkout`）：

| 变异 | 结果 |
|---|---|
| 去掉 `_category_state` 的 category 闸 | 1 红（`test_a_machine_verified_category_needs_a_human_where_facts_do`） |
| 去掉 `shelf_declaration` 的 category 闸 | 1 红（`test_shelf_declaration_asks_the_category_its_own_tier`） |
| 去掉 `_hunt_write_shelf` 的继承（H1） | 1 红（结构性回归） |
| `machine_trust_note` 退回只读 facts（H2） | 1 红 |
| 去掉 `shelf_can_drive_rules` 的 category 闸（H4） | 1 红 |
| 关掉词表校验 | 1 红（族清单那条） |
| 闸从 `!= verified` 改成 `!= candidate` | 2 红（说明这道闸是双向的） |

## 5. 没做 / 边界

- **H3 未修**（见上）：机器档分类对 14 个直读点的规则仍然可见。
- **证据不落货架**（527D2）：`--from/--page/--quote` 只在终端与 `--json`，`provenance`/`notes` 未写，
  所以 `machine_verified` 的分类事后追不到页码。
- `--from http(s)` 核的是「该条目身份」的缓存 dump，**不校验 URL 与缓存记录的 URL 是否同一个**（docs 已写明）。
- 冻结态下只在内置架的条目会 exit 2「找不到」，没提示「它在内置架、改不了」。
- `SKILL.md` 加不进一行（320 行硬顶 + `docs/parts.md` 不在打包清单），故 `parts classify` 只在
  `docs/parts.md` 与 `--help` 里。
- 真机未验（本批零真机）：`parts classify` 在真货架上的读写只经 tmp 目录测试覆盖。

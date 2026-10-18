# 522 — `facts_verified` 从布尔改成三档，并让「计算」类规则能用机器核验的事实

> 立项 2026-10-18。前置：520（`parts hunt` 拿到 PDF + txt）、521（`--apply-facts` 收 AI 读出来的
> facts，六道闸里最硬一条是引文逐字）。521 之后，一条 facts 已经**有可核验的证据链**，但仍是
> `facts_verified: false`，规则一个都不认 —— 于是「工程师不用补手册」这件事还没闭环。本批补上。

## 1. 目标（岳 2026-10-18 裁，`docs/roadmap.md` §7）

`facts_verified` 从布尔改成三值，授权来源不同、能驱动的东西不同：

| 档 | 谁来授予 | 能驱动什么 |
|---|---|---|
| `candidate` | `parts fetch` 的正则提取、`parts add` 的初稿 | **什么都不能**（现状） |
| `machine_verified` | `parts hunt --apply-facts` 过了六道闸（引文逐字、页码、pin 在文档里、来源可追） | 载流 / 降额 / 间距 **计算**；**不驱动连接结论、安规、隔离** |
| `verified` | 人工 | 全部 |

## 2. 字段设计（这是本批最重要的裁定，照做，别改）

### 2.1 一个字段，三个值

`core/parts.py::PartEntry` 加：

```python
FACTS_TRUST_VERIFIED = "verified"
FACTS_TRUST_MACHINE = "machine_verified"
FACTS_TRUST_CANDIDATE = "candidate"

facts_trust: str = FACTS_TRUST_VERIFIED   # 默认 True 的等价物，见下
```

**删除** `facts_verified` 这个字段，但**保留同名 property**：

```python
@property
def facts_verified(self) -> bool:
    """`True` only for a human-vouched entry — the 039 gate's own question."""
    return self.facts_trust == FACTS_TRUST_VERIFIED
```

理由（写进 docstring）：现有 30 多处读 `entry.facts_verified`，逐处改容易漏；property 让它们
**语义不变**（`machine_verified` 返回 False —— 它确实没被人工核过）。这是「一个概念一个名」的落法：
真字段只有一个，旧名是只读别名。

### 2.2 装载器兼容旧形状

`entry_from_json`（以及 `entry_to_json`）：

- 读到 `facts_verified: true` → `facts_trust = "verified"`；`false` → `"candidate"`；两者都缺 → `"verified"`（旧条目的默认）
- 读到 `facts_trust: "<某值>"` → 用它；**非法值报错**（`PartError`），别静默回落
- 两个键同时出现且互相矛盾（`facts_verified: true` + `facts_trust: "candidate"`）→ **报错**，不猜
- **写出只写 `facts_trust`，且 `verified` 这个值不写**（与 039「`entry_to_json` 省略 `True`」同一口径，保持旧文件字节不变）

### 2.3 `__post_init__` 的闸

现状是 `facts_verified is False` → facts 搬去 `candidate_facts`、`facts` 变 None。改成**只对
`candidate` 搬**：

```python
if self.facts_trust == FACTS_TRUST_CANDIDATE and self.facts is not None:
    ...
```

`machine_verified` 的 facts **留在 `facts` 里**（规则要能读），档位由规则侧问。

## 3. 规则侧：闸改成按档，且**保守默认**

`rules/facts.py::_category_state(entry)` 是唯一 choke point（它自己的 docstring 就写着
"the one choke point every facts rule passes through"）。改成：

```python
def _category_state(entry: PartEntry, *, allow_machine: bool) -> str:
    if entry.facts_trust == FACTS_TRUST_CANDIDATE:
        return _CATEGORY_UNKNOWN
    if entry.facts_trust == FACTS_TRUST_MACHINE and not allow_machine:
        return _CATEGORY_UNKNOWN
    ...   # 其余不变
```

`FactsRule` 加类属性：

```python
#: Conservative default: a rule that draws a **conclusion** from facts needs a
#: human signature. Only rules that turn facts into a **number** may say False.
REQUIRES_HUMAN_VERIFIED = True
```

`_category_state` 的每个调用点（`facts.py` 5 处、`decap.py` 1 处）改成传
`allow_machine=not self.REQUIRES_HUMAN_VERIFIED`（在类方法里；模块函数 `_category_state` 的
签名加 keyword）。`paramspec.py:470` 自己那份 `if not entry.facts_verified` 也要按同一把尺改。

### 3.1 谁设 False（判据：**结论 vs 数字**）

**保留 True（要人工核）—— 这些判的是「接错了没有」**：

- `facts.py::NcAndMustConnect`（NC 脚必须悬空 / 必须连接脚必须接上）
- `facts.py::SupplyOnKnownDomain`（供电脚必须落在已知电源域）
- `archclosure.py::NrstClosure`、`archclosure.py::OpenDrainPullup`、`archclosure.py::ArchSenseBiasClosure`

**设 False（可接受 machine_verified）—— 这些判的是「余量够不够」**：

- `facts.py::DomainVsRange`、`facts.py::LdoDropout`
- `decap.py::DecapRequiredCaps`
- `params.py::LedCurrent`、`params.py::DividerOutput`、`params.py::RcCutoff`
- `paramspec.py::TvsStandoffRail`、`paramspec.py::LdoFixedOutput`
- `archclosure.py::ArchRailVoltageClash`
- `pcb/distance.py` 里读 facts 的去耦距离规则
- `facts.py::UsbCcPulldown`
- `railratings.py:570` 那段 LDO 轨额定（不是 `_category_state` 的调用点，要单独加档判断）

**`params.py::ValueMpnMatch` 不读 datasheet facts**（它比板值与 MPN），档位与它无关，保持真值即可。

**你要做的第一件事**：把上表逐条对照源码确认，**有任何一条你判断错了就改并如实申报理由**。
不允许「顺手多改几条」——每条 False 都要能在报告里说出「它算的是哪个数」。

## 4. 授予路径

| 入口 | 写出的档 |
|---|---|
| `parts hunt --apply-facts`（521 的六道闸全过） | **`machine_verified`**（现在写的是 `facts_verified: false`，改这里） |
| `parts fetch`（正则提取，无引文校验） | `candidate`（不变） |
| `parts add`（无 `--verified`） | `candidate`（不变） |
| `parts add --facts … --verified` | `verified`（不变） |
| 人工在 diff 里改 `facts_trust` | 装载器按 §2.2 读 |

`parts hunt --apply-facts` 的 provenance 已经是 `hunt-read`（区别于 `hunt-extract`），保留。

## 5. 报告与 CLI（不涂绿）

1. **`report.json` 的 `parts[]`/`reviewedByShelf[]` 等**：`factsVerified`（bool）保留不动，**新增
   `factsTrust`**（三值）。消费方不破。
2. **`completion.factsTrust`**：`{"verified": n, "machineVerified": n, "candidate": n}`。
3. **`unreviewedByClass` 加第三桶**：现在是「工具读不懂 / 真缺资料」，加
   **「机器核验待人工确认」**。`machine_verified` 的件从「真缺资料」移进这一桶。
4. **verdict 不变**：`machine_verified` **不许**把 `completion.verdict` 推向 `complete` ——
   待人工确认的事实仍然是 open item。这条要写进代码注释，并且有一条测试钉住。
5. **finding 的证据标注**：凡是 `machine_verified` 的条目驱动的 finding，`evidence` 或 `detail`
   里必须出现「参数来源：机器核验（`<url 或 file:>`），**未人工确认**」。用统一一个函数生成这句，
   别每处手写。
6. **`parts show`**：打印 `facts_trust` 三档并解释每档能驱动什么（照抄 §1 的表）。

## 6. 测试（`tests/test_522_facts_trust.py`，零网络）

至少：

- 装载器：`facts_verified: true/false`/缺 → 三档映射正确；矛盾的两键 → 报错；非法 `facts_trust` → 报错
- 写回：`verified` 不写键；`machine_verified` / `candidate` 写出且能读回（往返）
- `facts_verified` property 在 `machine_verified` 上返回 **False**（这条是旧代码语义的保证）
- `candidate` 的 facts 仍在 `candidate_facts`、`facts` 为 None（039 的闸不能松）
- `machine_verified` 的 facts **留在** `facts` 里（否则计算类规则读不到）
- 一条 `REQUIRES_HUMAN_VERIFIED = True` 的规则对 `machine_verified` 条目仍判 UNKNOWN
  （拿 `NcAndMustConnect` 做证人）
- 一条 `False` 的规则对 `machine_verified` 条目**能出 finding**，且 finding 里带「未人工确认」
  （拿 `LdoDropout` 或 `DecapRequiredCaps` 做证人）
- `machine_verified` 不使 verdict 变 `complete`
- `parts hunt --apply-facts` 过闸后写出的条目是 `machine_verified` 而不是 `candidate`（拿 521 的
  答案文件格式，用真 txt 或夹具）

## 7. 文档

- `docs/parts.md`：`facts_verified` 那一节改成三档表 + 兼容说明（旧布尔怎么读）+ 「改档位是人工签字」
- `docs/review-sop.md`：报告里 `machine_verified` 的读法（哪些结论它能支撑、哪些不能）
- `docs/roadmap.md` §7 的三档表：把「目标」改成「已落」，并把**判据**（结论 vs 数字）写进去

## 8. 验收

```bash
cd /e/boardwise/.tmp_trust522
PYTHONPATH=src /e/boardwise/.venv/Scripts/python.exe -m pytest tests/test_522_facts_trust.py -q --basetemp=.tmp_pt_522
PYTHONPATH=src /e/boardwise/.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile \
  --basetemp=.tmp_pt_522f -k "facts or shelf or parts or checkup or params or decap or distance or trust" \
  --ignore=tests/test_190s_bottom_silk_direction.py
```

再跑一次**真板端到端**（`--offline`，零外呼）：用 `.tmp_cache_hunt520` 的 `C601651` 对
`级联多电平-驱动模块` 的 `U2` 交一份 `--apply-facts` 答案（引文照抄第 4/5 页），确认
① 写出的条目 `facts_trust == "machine_verified"`；② 再跑一次 `checkup --file`，报告里
`completion.factsTrust.machineVerified >= 1`、`unreviewedByClass` 里有「机器核验待人工确认」桶、
**verdict 没有因为这条变 complete**。三个读数贴进交卷。

## 9. 纪律

不 commit、不碰主树、删除进回收站（**禁 `rm`**）、单进程、pytest 必带 `--basetemp`、
并行只许 `-n 4 --dist loadfile`、**不许跑全量**（整机槽只有 2）、变异验证 `cp` + sha256 还原
（禁 `git checkout --`）、企业名零出现、注释英文且照抄 `core/parts.py` / `rules/facts.py` 的密度。

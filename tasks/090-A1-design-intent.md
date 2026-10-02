# 090 — A1：DesignIntent 文档 + 持久化纪律 + 审查报告接线

A 主线第一批，设计文档 `docs/design-intent-channel.md`（**先读，别猜**）。
目标：让「设计意图」成为第四份合同——活着、不丢、不覆盖、能说话（缺槽会点名去哪填）。
本批**只接线不查案**：规则消费（A2）、架构自洽检查（A3）、绘制消费（A4）都不在本批。

## 〇、权威来源（先读）

- `docs/design-intent-channel.md` §二（文档形态与三铁律）§五（A1 验收）。
- schema 先例：`src/boardwise/core/circuitspec.py`、`core/presentationspec.py`
  （封闭键/可选缺省不写出/sha256/spec_version 纪律/provenance 词表与 weakest 规则——
  后者在 `engines/grammar/base.py` 的 `weakest_provenance`/`PROVENANCE_*`）。
- 现有骨架生成处：checkup 目前会产出 `architecture.md`（槽骨架）与 `design-intent.md`
  （全 TODO）——**先找到这两个文件的生成函数**（`grep -rn "design-intent\|architecture" src/boardwise/engines/checkup.py src/boardwise/cli.py`），
  A1 的槽枚举**复用同一来源**，不许另起一套平行枚举。

## 一、DesignIntent 合同（`src/boardwise/core/designintent.py`，新）

- 三段式顶层键：`requirements` / `blocks` / `decisions` + `intentVersion`（=1）；
  封闭 schema（未知键报错点名）、可选字段缺省不写出、旧文档回读逐字节、
  `from_dict`/`to_jsonable`/`sha256` 与既有合同同形。
- provenance 词表复用语法侧：`user_stated` > `verified_recipe` > `ai_asserted`，
  weakest 规则同源；每段条目都可带 `provenance`，缺省 = `ai_asserted`（草稿态看得见，052 §4）。
- 条目级校验（措辞钉测试）：rail 无 `targetVoltage` → 报槽位而非拒读；
  `polarity: bidirectional` 的 current-sense 信号**没有**任何 `requires: ["bias-reference"]`
  类的闭合声明时，校验器**提示**（不拒）——这是 FOC 偏置案的槽位形态，A3 才升级为规则。

## 二、持久化纪律（本批的命门）

- 落点：`~/.boardwise/design-intent/<projectUuid>.json`（真机/checkup 默认），
  `--intent <path>` 显式覆盖（离线/测试用）。
- **合并语义**：重生成 = 以当前工程枚举出的槽位为准**新增 TODO 槽**；
  已填值（含人工改过的）**逐字节保留**；工程里已消失的槽标记 `stale: true` 而不删
  （删不删留给 A 后续批，本批只标记）。
- 回归钉（052 覆盖案）：先填 `targetVoltage: 3.3V` → 重生成 → 该值原样、新增槽为 TODO、
  全文除新增槽外逐字节。

## 三、checkup 接线

- checkup 报告新增 intent 节：槽位总数/已填/缺失清单；缺失必填槽（rail 无电压声明等）
  报 `intent-missing`，措辞与 `facts-missing` 同族（点名槽位 + 写到哪个文件哪个键）。
- 退出码不变（intent 缺失**不**抬 verdict——A1 只报告；评级归 A2/A3）。
- `design-intent.md` 既有产物保留（人读视图），但数据源改为 DesignIntent 合同
  （同一事实两个视图，JSON 是源）。

## 四、真实案例接线（不查案）

用 ctrl FOC 的公开事实写一份 intent（`blocklib/intents/robot-ctrl-foc.intent.json`，
新）：`+24V`/`+12V` 轨（电压+电流槽先 TODO）、`IU+`/`IW+`（current-sense、
bidirectional）、`inlet`/`senseU` 两个 block。checkup 对它跑一遍：报告 intent 节能
指出「F1 偏置案对应的槽是哪个、缺哪句闭合声明」——**只接线不判案**。

## 五、验收与纪律（照旧）

- 全量 pytest 绿（基线 **2974**）；新测试进 `tests/test_090_design_intent.py`；
  既有断言一字不改（若冲突停下报主代理）。
- 变异 ≥2 组（合并覆盖纪律 + schema 封闭性各至少一组），cp+sha256 还原，禁 sed/禁 git apply。
- 文档同步：`docs/architecture.md` 增 DesignIntent 条目；`docs/design-intent-channel.md`
  若有与本批实现的出入，回改该文档保持一致。
- 纯离线，不碰 bridge/真机；不动 git、不写 PROGRESS。
- 交卷：改动清单、槽枚举复用结论（复用了哪个函数）、合并语义实测记录、变异记录、
  ctrl FOC 接线实录、遗留项。

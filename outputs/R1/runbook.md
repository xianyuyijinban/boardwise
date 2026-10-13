# R1 真机 runbook（v0.5.12 桥能力补齐）

> 写给有编辑器的那台机器。本 PR 的开发机**没有立创 EDA Pro**，下列步骤**一步都没跑过**；
> 跑完把原始读数落 `outputs/R1/live/`，结论追加到 `outputs/R1/evidence.md`。
> 宿主基线：3.2.186。connector 必须是本 PR 的 0.5.12 bundle（`bridge status` 回读版本核对）。

## 0. 每节开工前（R1 身份纪律）

> **引号约定（PR#78 审查 LOW 3）**：本 runbook 是拿来照抄执行的，所以凡 `--params` 里要嵌
> `$PCB` / `$PAGE` / `$SCR` / `$ATTR` 这类 shell 变量的，整串 JSON 一律用**双引号**包住、内部引号写成
> `\"`。bash 的单引号不展开变量——照抄单引号那版会把字面量 `$PCB` 发给宿主，结果是 `PAGE_MISMATCH`
> （无害，但跑不通）。不含变量的 `--params` 仍用单引号，少一堆反斜杠。

```bash
boardwise bridge status                     # 版本 0.5.12；daemon 不在会自己拉起
boardwise bridge call --action doc.list --params '{}' --project test > outputs/R1/live/00_doc_list.json
```

- `projects[]` 里 `focused: true` 那一项的名字**逐字**是 `test`，否则停手（R1）。
- 记下 `PCB1` 的 uuid（下称 `$PCB`）。`PCB1` 必须是**空板**：
  `boardwise bridge call --action pcb.readback --params '{}' --project test` 的 `componentCount` 为 0；
  不是 0 就停手问（R3：目标与任务书描述不符）。
- 写动作只落 `test` 工程；所有写都带 `pageUuid`。

## R1-1 `pcb.place_component`：放 → 读 → 删

```bash
# 1. 切到 PCB1，核焦点
boardwise bridge call --action doc.open --params "{\"uuid\":\"$PCB\"}" --project test
boardwise bridge call --action document.current --params '{}' --project test > outputs/R1/live/11_focus.json

# 2. 宿主到底有没有这三个调用（声明 ≠ 实现）
boardwise bridge call --action sys.probe --project test \
  --params '{"checks":{"pcb_PrimitiveComponent":["create","getAllPrimitiveId","delete","getAll"]}}' \
  > outputs/R1/live/12_probe.json

# 3. 放一颗 0603（C25804 = 0603 10kΩ，换任何手边确定有封装的 0603 都行，记下用了哪个）
boardwise bridge call --action pcb.place_component --project test \
  --params "{\"pageUuid\":\"$PCB\",\"lcsc\":\"C25804\",\"x\":0,\"y\":0}" > outputs/R1/live/13_place.json
```

判读 `13_place.json`：

| 读数 | 结论 |
|---|---|
| `uuid` 非空、`appeared` 恰好一个且等于 `uuid` | 放成功，进第 4 步 |
| `NOT_IMPLEMENTED pcb_PrimitiveComponent.create()` | 宿主没有这条调用：如实记「宿主不支持」，证据就是 12/13 两份；走任务书的替代侦察（复制既有图元），**不许**改成静默成功 |
| `TIMEOUT` 且 `landedAnyway: true` | 落了但没按时回：**不要重试**，用 `appeared` 里的 id 走第 4/5 步 |
| `TIMEOUT` 且 `landedAnyway: null`（`appeared: []`） | **不知道落没落**：超时 = 宿主吞了回答，件可能在这次回读之后才提交（006b 实测过）。回读原文说的是「本次回读时板上没有」，不是「没落」——**看一眼板**再决定第 5 步删不删，绝不盲目重试 |
| `CONNECTOR_ERROR`（`answered undefined` / `threw: …`） | 记原话；`landedAnyway` 决定第 5 步删不删 |

```bash
# 4. 读回：器件在板上、位号丝印盒量得到
boardwise bridge call --action pcb.readback --params '{"includePrimitives":true}' --project test > outputs/R1/live/14_readback.json
#    从 14 里找到新器件的位号 ATTR 图元 id（$ATTR），连同器件 uuid 一起量
boardwise bridge call --action pcb.geometry --project test \
  --params "{\"bboxIds\":[\"<uuid>\",\"$ATTR\"]}" > outputs/R1/live/15_bbox.json

# 5. 删掉复原，再读一次板
boardwise bridge call --action pcb.delete_primitives --project test \
  --params "{\"pageUuid\":\"$PCB\",\"primitiveIds\":[\"<uuid>\"]}" > outputs/R1/live/16_delete.json
boardwise bridge call --action pcb.readback --params '{}' --project test > outputs/R1/live/17_after.json
```

验收：`15_bbox.json` 的 `bboxes` 里器件与 ATTR 各有一个有限四元组；`16` 的 `deleted` 含该 uuid；
`17` 的 `componentCount` 回到 0。放-读-删三份原始读数齐了才算 R1-1 真机过。
顺带记一笔：`13_place.json` 的 `placed` 与 `requested` 是否一致（坐标是否被宿主吸附、`layer` 回读是不是 1）。

## R1-2 `sys.get_document_source` 带身份

```bash
# 任选 test 工程里一张原理图页 $PAGE（00_doc_list.json 里挑），切过去再读
boardwise bridge call --action doc.open --params "{\"uuid\":\"$PAGE\"}" --project test
boardwise bridge call --action sys.get_document_source --params '{"maxChars":512}' --project test > outputs/R1/live/21_source.json
boardwise bridge call --action doc.list --params '{}' --project test > outputs/R1/live/22_doc_list.json
```

验收：`21` 的 `uuid` / `name` / `type` 与 `22` 里 `active: true` 那一行的 `uuid` / `name` / `type` 逐字相同，
`notes` 不存在。再对 `$PCB` 做一遍（`type` 应为 `pcb`）。

## R1-3 `sys.set_document_source` 改名通路（**已裁决：方案 1；动作已入册**）

主代理 2026-10-12 裁：**新增** `sys.set_document_source`（方案 1），不是永远不做。动作已入 connector 与
双 protocol 表（connector 版本号不动，随 v0.5.12 统一发）。它的性质必须记住：

- `risk="dangerous"` → 走 daemon 的确认闸，**没带 `confirm: true` 会回 `CONFIRMATION_REQUIRED`**；
  CLI 的 `--yes` 就是那个 token（`boardwise bridge call` 在确认被拒时会问一次 y/N，`--yes` 直接置
  `params.confirm = true`）。
- `uuid` **必填且必须等于当前活动文档**，不符回 `DOC_NOT_ACTIVE`（179 形制）。宿主调用只吃文本
  （声明 arity 1），它改的是"当前打开的那份"，所以这个守卫没有省略路径。
- **侦察用途、只在 scratch 页上做。** 动作自己不判断页身份，纪律在执行者手里。
- 读数：`36` 里的 `readBack` 是 `identical` / `differs` / `unreadable`——"宿主说改成功了"和"文档现在就是
  这段文本"是两回事（179 的教训），故回读。`differs` **只记不判**：宿主可能把自己接受的那份重新序列化。

```bash
# 1. 建 scratch 页（create 档 --yes）；sch.doc.new 会把这页打开 → $SCR 就是活动页
boardwise bridge call --action sch.doc.new --params '{"name":"R1-scratch"}' --project test --yes > outputs/R1/live/31_scratch.json
#    从 31 取 pageUuid → $SCR，并用 document.current 核焦点（sys.set_document_source 会比对）
boardwise bridge call --action document.current --params '{}' --project test > outputs/R1/live/32_focus.json

# 2. 读全源（maxChars 拉满，别被截断；33 的 .data 就是全文）
boardwise bridge call --action sys.get_document_source \
  --params "{\"uuid\":\"$SCR\",\"maxChars\":4000000}" --project test > outputs/R1/live/33_source.json

# 3. 只改源里这页的名字字段 → 34_new_source.txt。
#    注意：字段拼写以 33 的原文为准（本机没跑过，不许猜）；找不到页名就**停手问**（R3），
#    绝不许写回一份没改动的源。
python - <<'PY'
import json
raw = json.load(open('outputs/R1/live/33_source.json', encoding='utf-8'))
src = raw['data']
assert 'R1-scratch' in src, '源里找不到页名 R1-scratch：先看清格式，别写回没改的源'
open('outputs/R1/live/34_new_source.txt', 'w', encoding='utf-8', newline='').write(
    src.replace('R1-scratch', 'R1-renamed', 1))
print('src', len(src), 'chars -> rewritten')
PY

# 4. 写回（危险档的闸：--yes 就是 confirm: true）
python -c "import json; print(json.dumps({'uuid':'$SCR','source':open('outputs/R1/live/34_new_source.txt',encoding='utf-8').read()}))" > outputs/R1/live/35_params.json
boardwise bridge call --action sys.set_document_source \
  --params "$(cat outputs/R1/live/35_params.json)" --project test --yes > outputs/R1/live/36_set_source.json

# 5. 判读：名字变没变 / 源是不是写进去的那份
boardwise bridge call --action doc.list --params '{}' --project test > outputs/R1/live/37_doc_list.json
boardwise bridge call --action sys.get_document_source \
  --params "{\"uuid\":\"$SCR\",\"maxChars\":4000000}" --project test > outputs/R1/live/38_source_after.json

# 6. 收尾：删 scratch 页，doc.list 核它不在
boardwise bridge call --action doc.delete_page --params "{\"pageUuid\":\"$SCR\"}" --project test > outputs/R1/live/39_delete.json
```

判读表：

| 读数 | 结论 |
|---|---|
| `36` 的 `hostAnswer: true` 且 `readBack: identical` | 写通行、且文档确实持有写进去的文本 |
| `36` 的 `readBack: differs` | 宿主接受了但改写了格式——**如实记**，并看 `37` 的页名有没有变 |
| `36` 的 `readBack: unreadable` | 宿主不回读；改看 `38` 的 `.data` 是不是 `34_new_source.txt` |
| `NOT_IMPLEMENTED sys_FileManager.setDocumentSource()` | 宿主没有这条调用：如实记「宿主不支持」（声明 ≠ 实现），证据就是 36 |
| `CONNECTOR_ERROR ... answered false` | 声明说 `false` = 源码格式错误：**原文照记**，不许把它读成"成功但没生效" |
| `DOC_NOT_ACTIVE` | `$SCR` 不是活动页：先 `doc.open` 再写，别改代码 |

生效 → `doc.rename` 内部改走这条路（**列表确认制测试必须还在**）；不生效 → 写进 pits #47 与 bridge.md。
**无论哪种，`doc.rename` 的 `NOT_SUPPORTED` 都不许改回静默成功。**

## R1-4 Power 旗是否也恒一颗字形

```bash
boardwise bridge call --action sch.doc.new --params '{"name":"R1-scratch"}' --project test --yes > outputs/R1/live/41_scratch.json
# $SCR = 41 里的 pageUuid；三颗轨旗，彼此隔开 200，各自记下回来的 uuid
boardwise bridge call --action sch.place_power --project test --params "{\"kind\":\"Power\",\"net\":\"VIN5\",\"x\":0,\"y\":0,\"pageUuid\":\"$SCR\"}"
boardwise bridge call --action sch.place_power --project test --params "{\"kind\":\"Power\",\"net\":\"+5V\",\"x\":200,\"y\":0,\"pageUuid\":\"$SCR\"}"
boardwise bridge call --action sch.place_power --project test --params "{\"kind\":\"Power\",\"net\":\"SEC_12V\",\"x\":400,\"y\":0,\"pageUuid\":\"$SCR\"}"
boardwise bridge call --action sch.geometry --params '{}' --project test > outputs/R1/live/42_geometry.json
# 库里有没有 Power-<net> 族（180 查 Ground-<net> 的同一手法）
boardwise bridge call --action lib.device.search --params '{"keyword":"Power-","limit":50}' --project test > outputs/R1/live/43_power_family.json
```

判读：按 178b 的读法（样板 `outputs/178b/live/`）从 `42` 里读三颗旗各自落的**符号名**（uuid 级）。

- 三颗都是同一个 `Power-*` → 与地旗同病：把 180 的按符号放置推广到 rail 旗
  （`cli.py` `_draw_apply_flow` 第 8 段，`ground_device` → `flag_device(net)`，查 `Power-<net>` 与 `Ground-<net>` 两族），
  `tests/test_180_ground_flag_by_symbol.py` 同型补 rail 侧（test_054 的 fake 加 `power_symbols`）。
- 按 net 各不相同 → 如实记「Power 无恙」，不动代码。

收尾：`sch.delete_primitives` 删三颗旗 → `doc.delete_page` 删 `R1-scratch` 页 → `doc.list` 核页已不在。

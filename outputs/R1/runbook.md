# R1 真机 runbook（v0.5.12 桥能力补齐）

> 写给有编辑器的那台机器。本 PR 的开发机**没有立创 EDA Pro**，下列步骤**一步都没跑过**；
> 跑完把原始读数落 `outputs/R1/live/`，结论追加到 `outputs/R1/evidence.md`。
> 宿主基线：3.2.186。connector 必须是本 PR 的 0.5.12 bundle（`bridge status` 回读版本核对）。

## 0. 每节开工前（R1 身份纪律）

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
boardwise bridge call --action doc.open --params '{"uuid":"$PCB"}' --project test
boardwise bridge call --action document.current --params '{}' --project test > outputs/R1/live/11_focus.json

# 2. 宿主到底有没有这三个调用（声明 ≠ 实现）
boardwise bridge call --action sys.probe --project test \
  --params '{"checks":{"pcb_PrimitiveComponent":["create","getAllPrimitiveId","delete","getAll"]}}' \
  > outputs/R1/live/12_probe.json

# 3. 放一颗 0603（C25804 = 0603 10kΩ，换任何手边确定有封装的 0603 都行，记下用了哪个）
boardwise bridge call --action pcb.place_component --project test \
  --params '{"pageUuid":"$PCB","lcsc":"C25804","x":0,"y":0}' > outputs/R1/live/13_place.json
```

判读 `13_place.json`：

| 读数 | 结论 |
|---|---|
| `uuid` 非空、`appeared` 恰好一个且等于 `uuid` | 放成功，进第 4 步 |
| `NOT_IMPLEMENTED pcb_PrimitiveComponent.create()` | 宿主没有这条调用：如实记「宿主不支持」，证据就是 12/13 两份；走任务书的替代侦察（复制既有图元），**不许**改成静默成功 |
| `TIMEOUT` 且 `landedAnyway: true` | 落了但没按时回：**不要重试**，用 `appeared` 里的 id 走第 4/5 步 |
| `CONNECTOR_ERROR`（`answered undefined` / `threw: …`） | 记原话；`landedAnyway` 决定第 5 步删不删 |

```bash
# 4. 读回：器件在板上、位号丝印盒量得到
boardwise bridge call --action pcb.readback --params '{"includePrimitives":true}' --project test > outputs/R1/live/14_readback.json
#    从 14 里找到新器件的位号 ATTR 图元 id（$ATTR），连同器件 uuid 一起量
boardwise bridge call --action pcb.geometry --project test \
  --params '{"bboxIds":["<uuid>","$ATTR"]}' > outputs/R1/live/15_bbox.json

# 5. 删掉复原，再读一次板
boardwise bridge call --action pcb.delete_primitives --project test \
  --params '{"pageUuid":"$PCB","primitiveIds":["<uuid>"]}' > outputs/R1/live/16_delete.json
boardwise bridge call --action pcb.readback --params '{}' --project test > outputs/R1/live/17_after.json
```

验收：`15_bbox.json` 的 `bboxes` 里器件与 ATTR 各有一个有限四元组；`16` 的 `deleted` 含该 uuid；
`17` 的 `componentCount` 回到 0。放-读-删三份原始读数齐了才算 R1-1 真机过。
顺带记一笔：`13_place.json` 的 `placed` 与 `requested` 是否一致（坐标是否被宿主吸附、`layer` 回读是不是 1）。

## R1-2 `sys.get_document_source` 带身份

```bash
# 任选 test 工程里一张原理图页 $PAGE（00_doc_list.json 里挑），切过去再读
boardwise bridge call --action doc.open --params '{"uuid":"$PAGE"}' --project test
boardwise bridge call --action sys.get_document_source --params '{"maxChars":512}' --project test > outputs/R1/live/21_source.json
boardwise bridge call --action doc.list --params '{}' --project test > outputs/R1/live/22_doc_list.json
```

验收：`21` 的 `uuid` / `name` / `type` 与 `22` 里 `active: true` 那一行的 `uuid` / `name` / `type` 逐字相同，
`notes` 不存在。再对 `$PCB` 做一遍（`type` 应为 `pcb`）。

## R1-3 `setDocumentSource` 改名通路（**未做，待裁决**）

桥上**没有**能调 `sys_FileManager.setDocumentSource(source)` 的动作：`sys.probe` 的 `call` 模式按设计只放行
只读动作（写入口一律不许借 probe 绕过确认闸），所以这条侦察需要先定「用什么仪器」，开发机这边不擅自加写口。
备选（PR 里请主代理裁决）：

1. 临时加一个 `risk="dangerous"` 的 `sys.set_document_source`（走确认闸、强制 `uuid` 与活动文档一致、
   只在 scratch 页用），侦察完删掉或保留为正式动作；
2. 不加动作，pits #47 维持「setDocumentSource 未验」。

若选 1，侦察步骤：test 工程 `sch.doc.new --yes` 建 scratch 页 → `sys.get_document_source` 读全源（`maxChars` 拉满）
→ 只改源里该页名字段 → `set_document_source` 写回 → `doc.list` 看名字是否变、`sys.get_document_source` 再读一次
看源是否是写进去的那份 → `doc.delete_page` 删 scratch 页。生效 → `doc.rename` 内部改走这条路（列表确认制测试必须还在）；
不生效 → 写进 pits #47 与 bridge.md。**无论哪种，`doc.rename` 的 `NOT_SUPPORTED` 都不许改回静默成功。**

## R1-4 Power 旗是否也恒一颗字形

```bash
boardwise bridge call --action sch.doc.new --params '{"name":"R1-scratch"}' --project test --yes > outputs/R1/live/41_scratch.json
# $SCR = 41 里的 pageUuid；三颗轨旗，彼此隔开 200，各自记下回来的 uuid
boardwise bridge call --action sch.place_power --project test --params '{"kind":"Power","net":"VIN5","x":0,"y":0,"pageUuid":"$SCR"}'
boardwise bridge call --action sch.place_power --project test --params '{"kind":"Power","net":"+5V","x":200,"y":0,"pageUuid":"$SCR"}'
boardwise bridge call --action sch.place_power --project test --params '{"kind":"Power","net":"SEC_12V","x":400,"y":0,"pageUuid":"$SCR"}'
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

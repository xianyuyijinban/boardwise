# 518 真机证据：B4 页型守卫在活编辑器上成立

日期：2026-10-19　版本：v0.5.18（内测）　相关：`tasks/527_pre060_loose_ends.md` §527B

环境：立创 EDA Pro 3.2.149 · daemon 重启到 0.5.18 · `test` 窗 connector 热更 `0.5.15 -> 0.5.18`
（`boardwise bridge update-connector --yes --instance inst-111212699-hgqi8gi9` → exit 0，
`ok: 0.5.15 -> 0.5.18`，**verified**；热更后该窗 instance key 变为 `inst-100335965-dfwehc3n`，属预期）。
本批**零写动作**：没有 `pcb.place_*` / `sch.set_*` / `doc.rename` / `doc.delete_page` / `export.fab`。

## 1. B4 正例：焦点在原理图页，请求 PCB 读回

```
$ boardwise bridge call --action pcb.readback --project test
boardwise bridge call: pcb.readback failed [PAGE_MISMATCH] pcb.readback reads the PCB page,
but the active document is a schematic page (f575d25746aca408) — bring the PCB page to the
front (doc.focus, or doc.open if it is not open) and call pcb.readback again
exit=1，stdout 空
```

三件事齐了：请求什么（PCB 读回）、当前是什么（原理图页 + uuid）、怎么办（`doc.focus` / `doc.open`）。
**不是** `TypeError`，**不是**一份看起来正常的 payload。

## 2. B4 反例：镜像方向

切到 PCB 页（`doc.open 443698e98668b58b`）后：

```
boardwise bridge call: sch.readback failed [PAGE_MISMATCH] sch.readback reads the schematic
page, but the active document is a PCB (443698e98668b58b) — bring the schematic page to the
front (doc.focus, or doc.open if it is not open) and call sch.readback again
```

## 3. 守卫在 **connector** 侧，不是 daemon 侧（对照实验）

同一个 0.5.18 daemon 下，**另一个窗口仍是 connector 0.5.15**，对它做同样的错页调用：
返回的是旧行为（payload / `TypeError: … null`），没有 `PAGE_MISMATCH`。
一个 daemon、两个 connector，唯一变量是扩展版本 ⇒ 守卫确实在扩展里。
这一条比"修好了"更有价值：它排除了「daemon 替你挡住了」的误判。

## 4. 在线 checkup 稳定

```
boardwise checkup --project test --out .tmp_518live/checkup1   # exit 1；38 ERROR / 0 WARN / 18 INFO；14 s
boardwise checkup --project test --out .tmp_518live/checkup2   # exit 1；同上；11 s
```

两次 `report.json` 的 findings **56 = 56、同序、逐字节一致**。本批改过 `document.current` 的
文档类型读法（own-key + `getState_*` 两种形状），这一读数说明没有引入读法回归。

## 5. `pcb.geometry` 仍然没有页型守卫（**本批明确未修**）

焦点在原理图页时：

```
boardwise bridge call --action pcb.geometry --project test --params '{"bboxIds":["<id>"]}'
exit 0，meta.unreadable 里有该 id，报 `Cannot read properties of null (reading 'length')`
```

即它不会说「你停错了页」，而是把每个 id 都当成「宿主没给盒子」。这与 527B 挖洞的 F6 一致：
用户报告里的 `bboxes: 0` **不是** readback 那条改动治好的，它至今没有守卫（TASKMAP 记在 527B 的边界里）。

## 6. 实板A 的 311 V 高侧间距（517 的修复仍成立）

离线，`boardwise checkup --file <实板A.epro2> --intent .tmp_live517/contract_311.json`：

| 网对 | 读数 mil | 门槛 | 结论 |
|---|---|---|---|
| `HV ↔ GND` | 66.9350 | 100 | WARN |
| `HV ↔ U` | 62.9921 | 100 | WARN |
| `HV ↔ V` | 62.9921 | 100 | WARN |
| `HV ↔ W` | 37.8938 | 100 | WARN |

四条与 517 记录逐位一致。（任务书里指的 `file-dbe821bb97d1.json` 是**上一轮**的合同名，
本轮已不在 `~/.boardwise/design-intent/`；用 517 证据里那份 311 V 合同复现，读数相同。）

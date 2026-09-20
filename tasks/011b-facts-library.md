# 任务 011b：事实库 schema 扩展 + 首批 3 IC 录入

> 2026-09-19 Kimi 立项。执行：DeepSeek；复验：Kimi。011 任务书 §四/§五/§八 的第二步。
> 前置：011a 已交卷并通过复验（标注 schema + review-eval harness，934/187/tsc）。

## 一、输入与动机

- 011 §四的 facts schema 草案（本任务把它落成代码与数据）。
- 011a 首次实测的三条 query 已全部闭合（Kimi 从 golden 文件挖出的事实）：
  - **U3 不是 IC，是一颗 0805 电阻**（FOJAN FRC0805J471 TS / C2907329），
    它是 LED1 的限流电阻（VCC → U3 → NET4 → LED1 → GND）。
    **教训：器件分类不许靠位号前缀** —— 这是本任务加 `category` 键的直接动机。
  - R24/R27 = Type-C 座 CC1/CC2 的 5.1k Rd 下拉（USB-C 受电端标准设计），非缺陷。
  - U3 的 value(1k) 与 MPN 解码值(FRC0805J**471** = 470Ω) 矛盾 ——
    **PARAM 族规则素材，011c/011d 实现，本任务只在 §六 记录**。

## 二、设计裁决（Kimi 已裁，照做即可）

### 2.1 parts.json schema v1 → v2

- `core/parts.py` 的 `SCHEMA_VERSION` 升 2，loader **拒绝 v1 文件**（fails loudly，
  与既有纪律一致）。仓内 `blocklib/parts.json` 同步迁移（版本号 +1，
  92 件既有 part **不加 facts 也不加 category**——没有就是"未录入"，不许编造）。
- part 条目新增两个**可选**键，loader 白名单收录；未知键（含 facts 内层）继续拒绝。
- 既有 92 件的 `manufacturer`/`params` 里有 GBK 乱码（源数据如此）——
  **不许顺手"修"**，最小改动。

### 2.2 `category`（可选，字符串）

受控词汇表：`resistor | capacitor | inductor | led | diode | connector | crystal |
ic.ldo | ic.usb-uart | ic.mcu | ic.charger | buzzer | switch | module`。
不在表内的值 ⇒ loader 拒绝。首批只给录入的 3 个 IC 标 category；
词汇表不够用时**停下来报告**，不许现场发明新词。

### 2.3 `facts`（可选，对象）

白名单键与结构（全部可选，出现即校验）：

```json
"facts": {
  "supply_pins":  [{"pins": ["16"], "name": "VCC",
                    "v_operating": [4.5, 5.5], "v_abs_max": [-0.5, 6.5],
                    "provenance": "CH340G datasheet, sec.5.1 table, <url>"}],
  "required_caps": [{"pin": "16", "value": "100nF", "provenance": "..."}],
  "nc_pins":       {"pins": ["7", "8"], "provenance": "..."},
  "must_connect":  [{"pin": "4", "to": "GND", "provenance": "..."}],
  "led":           {"vf_v": [1.8, 2.4], "if_max_ma": 20, "provenance": "..."},
  "ldo":           {"dropout_max_mv": 1100, "condition": "Iout=800mA", "provenance": "..."}
}
```

- **provenance 一律必填**，格式 `"<datasheet 名>, <页码/章节>, <url>"`。
  没有页码/章节的事实不许入库（与块库同一条引用纪律）。
- 数值用 number，区间用 `[min, max]` 二元数组（长度≠2 拒绝，min>max 拒绝）。
- 引脚号用**字符串**（`"16"` 不是 `16`——BNC/ACK 这类命名脚存在）。
- 电压单位伏、电流毫安、压差毫伏——键名已含单位，值里不许再写单位字符串。

### 2.4 查找路径

`core/parts.py` 加一个 `find_facts(mpn=None, lcsc=None)` 之类的解析函数：
按 MPN 精确命中 → 按 lcsc 命中 → 不命中返回 None（**不许模糊匹配**，值门控的教训）。
板上器件解析 facts 的调用方（011c 的规则）自己负责"板上 MPN → 库条目"。

## 三、首批录入（3 个 IC）

| part | category | 板上出现 | 必录事实 |
|---|---|---|---|
| CH340G (C14267) | ic.usb-uart | 黄金板 U1 | supply_pins(VCC 4.5–5.5V)、晶振脚要求、V3 脚电容要求 |
| RT9013-33GB (C47773) | ic.ldo | 黄金板 U5 | ldo.dropout、supply/v_operating、输出电容要求 |
| AMS1117-3.3 | ic.ldo | 010 块/药箱板 | ldo.dropout、输入/输出电容要求 |

- datasheet 用网络可得的官方/代理商 PDF（LCSC 条目里有 `datasheetPdfUrl` 字段可指路）。
- **PDF 不入仓**（版权与体积）；provenance 记 URL + 页码/章节。
- 拿不准的事实**不录**（UNKNOWN 哲学：没有证据的事实宁可缺席）。
- 录入完成后列出每条事实的 provenance 清单，**岳翔宇审页码后才算数**。

## 四、测试

1. loader：v1 文件拒绝；未知顶层键/未知 facts 键/未知 category 词拒绝；
   缺 provenance 拒绝；区间长度≠2 与 min>max 拒绝；引脚号非字符串拒绝。
2. 迁移后的 `blocklib/parts.json` 全量加载通过；92 件无 facts 的旧 part 不受影响。
3. `find_facts`：MPN 命中 / lcsc 命中 / 都不命中返回 None / **模糊前缀不命中**。
4. 变异 ≥3（建议：去掉 provenance 必填；区间不校验；category 词汇表放行任意词），
   每个变异只许咬红该咬的测试，还原逐字节一致。

## 五、交卷标准

- pytest 全绿（基线 934 + 新增）、connector 187 不动、tsc 不动（本任务应零 TS 改动）；
- `blocklib/parts.json` 迁移后 diff 只有版本号 + 3 个 part 的新键；
- provenance 清单落盘 `outputs/011b_provenance.md` 等岳翔宇审；
- 交卷记录写进 `tasks/011-review-rules-m1.md`（交卷记录 B），写完自查重复段。

## 六、明确不做

- **不实现任何规则**（CONN/PWR/DECAP/PARAM/PATH 是 011c/011d）；
- 不给 92 件旧 part 补 category/facts（无证据不录入）；
- 不改 `engines/select.py` 的选型逻辑；
- 不动标注集（3 条 query 的裁决落地等岳翔宇对 U3 阻值的最终答复，随后单独一步做）；
- 不新增 CLI 子命令（`--view` 裁决已定为 011c 输入：`review --view schematic|pcb`，默认 pcb）。

## 七、纪律

- 注释全英文；不动 git；临时文件 `.tmp_*` 仓内、用完删；
- append 类写入后**独立命令数标记出现次数**（本机已三次静默双执行）；
- pytest 必须 `--basetemp=.tmp_pt_home`；
- 与任务书预期不符 ⇒ 停下来如实报告，不许绕过。

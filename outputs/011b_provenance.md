# Task 011b — facts provenance list (for Yue Xiangyu's review)

Every fact recorded into `blocklib/parts.json` in task 011b, with its source,
page, and URL. **These entries are DRAFT until Yue signs off on the page
numbers.** PDFs are not committed (licence/size); the URLs below are the
copies the facts were verified against, downloaded 2026-09-19.

## 1. CH340G (C14267) — new entry `ic.ch340g`, category `ic.usb-uart`

Source PDF: WCH 《CH340手册(一)》 revision 3D, 10 pages
<https://atta.szlcsc.com/upload/public/pdf/source/20250604/33626338A5406B1E2A8163A86C0531AF.pdf>
(LCSC copy of the WCH datasheet, linked from
<https://item.szlcsc.com/datasheet/CH340G/14927.html>)

| fact | value | datasheet evidence |
|---|---|---|
| supply_pins / VCC, 5V mode | pin 16, v_operating **4.0–5.3 V**, v_abs_max **−0.5–6.0 V** | p.5 §6.1 (VCC 电源电压 −0.5~6.0 V) and §6.2 (VCC 电源电压, 条件「V3引脚仅外接电容，不连VCC」: min 4.0 / typ 5 / max 5.3 V) |
| supply_pins / VCC, 3.3V mode | pin 16, v_operating **2.9–3.6 V** | p.5 §6.3 (条件「V3引脚连接VCC引脚」, CH340G/T/R: 2.9/3.3/3.6 V) |
| required_caps on pin 4 (V3) | **0.1uF** | p.3 §5.1 (5V 工作时 V3 外接 0.1uF 电源退耦电容; 3.3V 工作时 V3 与 VCC 相连接) and p.2 pin table (V3: 5V 时外接 0.1uF 退耦电容) |
| required_caps on pin 16 (VCC) | **0.1uF** | p.2 pin table (VCC: 正电源输入端，需要外接 0.1uF 电源退耦电容) |
| must_connect pin 7 (XI) | external 12MHz crystal network | p.2 pin table (XI 需外接 12MHz 晶体及振荡电容), p.3 §5.1; clock window 11.98–12.02 MHz at p.6 §6.4 |
| must_connect pin 8 (XO) | external 12MHz crystal network | p.2 pin table (XO, 同 XI), p.3 §5.1 |

Pin numbers (16/4/7/8/1) are the SOP-16 column of the p.2 pin table and agree
with the golden board's replayed U1 (16=VCC, 4=V3→C1, 7/8=crystal, 1=GND).

**Correction against the task book:** task 011 §三 said "supply_pins(VCC
4.5–5.5V)". The datasheet's 5V-mode operating range is **4.0–5.3 V** (§6.2);
4.5–5.5 does not appear. Recorded 4.0–5.3.

**Not recorded (no schema slot yet — 011c decision needed):** the 12MHz
crystal requirement's *value* dimension (load-capacitor values are board- and
crystal-specific; the datasheet says only "振荡电容"); the V3-ties-to-VCC
3.3V-mode connection is captured as prose inside the pin-4 cap's provenance.

## 2. RT9013-33GB (C47773) — existing entry `ic.rt9013_33gb`, category `ic.ldo`

Source PDF: Richtek DS9013-10, April 2011, 13 pages
<https://datasheet.lcsc.com/datasheet/pdf/3e4c0e97f96a4457b99f132edf047652.pdf>

| fact | value | datasheet evidence |
|---|---|---|
| supply_pins / VIN | pin 1, v_operating **2.2–5.5 V**, v_abs_max **(null)–6.0 V** | p.3 Recommended Operating Conditions (Supply Input Voltage 2.2V to 5.5V) and Absolute Maximum Ratings (Supply Input Voltage 6V) |
| required_caps on pin 1 (VIN) | **1uF** | p.8 Applications Information (input capacitor value > 1 µF/X7R, ≤0.5 inch from the pin) |
| required_caps on pin 5 (VOUT) | **1uF** | p.8 Applications Information (output capacitor at least 1 µF ceramic, ESR > 5 mΩ) |
| nc_pins | pin **4** | p.2 Functional Pin Description (SOT-23-5: pin 4 = NC, No Internal Connection) |
| ldo | dropout_max_mv **400**, condition Iout=500mA, Vin 2.7–5.5 V (typ 250 mV) | p.3 Electrical Characteristics, Dropout Voltage (IOUT=500mA, 2.7V≤VIN≤5.5V: typ 250 / max 400 mV; second bucket 320 mV max at IOUT=400mA, 2.2V≤VIN<2.7V) |

v_abs_max is one-sided on purpose: the datasheet states a 6 V upper limit and
no lower one. The schema allows `[null, 6.0]` so the loader does not force a
fabricated 0. RT9013-**33** output accuracy ±2% (p.3) is not recorded — no
schema slot for output accuracy yet (011c).

## 3. AMS1117-3.3 (C6186) — existing entry `ic.ams1117_3_3`, category `ic.ldo`

Source PDF: AMS (Advanced Monolithic Systems) AMS1117 datasheet, 8 pages
<https://datasheet.lcsc.com/datasheet/pdf/e6935943fc6b1bbf350a1a0f3e90dc4a.pdf?productCode=C6186>

| fact | value | datasheet evidence |
|---|---|---|
| supply_pins / VIN | pin 3, v_abs_max **(null)–15.0 V** | p.2 Absolute Maximum Ratings (Input Voltage 15 V) |
| required_caps on pin 2 (VOUT) | **22uF** | p.4 Stability (the series *requires* an output capacitor as part of frequency compensation; 22 µF solid tantalum ensures stability for all operating conditions; without ADJ bypass smaller caps can be used) |
| ldo | dropout_max_mv **1300**, condition Iout=0.8 A, ΔVout/ΔVref=1% | p.3 Electrical Characteristics, Dropout Voltage (min 1.1 / max 1.3 V at IOUT=0.8 A, Note 4); p.1 features "Operates Down to 1V Dropout" |

Deliberately **not** recorded:
- a `v_operating` for the AMS1117's VIN — the datasheet states no operating
  input *range* for the fixed-3.3V part (only test conditions like
  VIN=4.75 V); inventing "[4.4, 15]" would be derivation, not evidence;
- an input-capacitor requirement — p.4's stability text mandates only the
  output capacitor; no input-cap requirement appears in the text.

Pin numbers follow the SOT-223 device pinout (1=GND, 2=VOUT, 3=VIN,
tab=VOUT) — measured on the editor library in task 010 (010 立项书 §五) and
matching the pillbox board's U11.

## Entry-identity provenance for the new `ic.ch340g`

- `mpn`/`lcsc`/`footprint`(human label SOP-16): the golden board's own device
  attrs (`tests/fixtures/ch340_golden.epro2`, U1) — `outputs/011b_u1_model.txt`.
- global `deviceUuid` `f809d2f6af2d4c2eb58795bc97ecb0d8` / `libraryUuid`
  `0819f05c4eef4c71ace90d822a990e87`: read-only `lib.device.search` +
  `lib.device.get` (`outputs/011b_ch340g_search.json`, `..._device.json`);
  `SupplierId: C14267` confirmed in the device's `property`.
- `footprint_name` `SOIC-16_L9.9-W3.9-P1.27-LS6.0-BL`, `footprint_name_verified: true`:
  read-only `lib.footprint.get` on the device's `association.footprintUuid`
  (`outputs/011b_ch340g_footprint.json`).
- `basic: false`: evidence "JLCPCB Part Class: Extended Part" in the device
  `property.otherProperty`.

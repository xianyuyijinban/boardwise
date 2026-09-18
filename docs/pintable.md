# The firmware pin table (task 008c, item 2)

008c's input is intent + firmware + datasheets. The middle one is the only
machine-readable statement of *what the board is actually wired to*, and the
constitution (item 5) draws the line at **interface facts**: a pin table may say
which pin does what; it may not reason about the software.

This file documents the artifact, the three gates that check it, and the one
rule that makes it worth writing down at all — **the `.ioc` is the baseline, and
disagreement is reported, never resolved**.

## The artifact

`inputs/smart_pillbox/pintable.json`:

```json
{"kind": "boardwise-firmware-pintable", "version": 1,
 "mcu": "ic.stm32g431rbt6", "source": "...", "notes": [...],
 "pins": [{"number": "PA5", "name": "PA5", "function": "SPI_SCK", "net": "SPI1_SCK"}]}
```

| Field | Meaning |
|---|---|
| `mcu` | a shelf key or a C-number. The identity that says *which* pinout is being spoken about |
| `pins[].number` | the pin, as the MCU block's symbol spells it (`PA5`, `PC12`) |
| `pins[].name` | defaults to `number`; on an STM32 the ball name and the pin name are the same string |
| `pins[].function` | a member of `PINTABLE_FUNCTIONS` — **the vocabulary is closed** |
| `pins[].net` | the name the schematic must carry at that pin |

### The vocabulary is closed

`PINTABLE_FUNCTIONS` is a **registry**, not a bag of strings — the same shape as
`blocks.CONSTRAINTS`, for the same reason: a vocabulary that silently accepts
anything checks nothing, and the reviewer judging "is this pin table right?"
needs a bounded set of answers to compare against. Members today: `GPIO`,
`UART_TX`, `UART_RX`, `I2C_SCL`, `I2C_SDA`, `SPI_SCK`, `SPI_MISO`, `SPI_MOSI`,
`SPI_NSS`, `PWM`, `ADC`, `SWDIO`, `SWDCLK`, `NRST`, `OSC_IN`, `OSC_OUT`, `BOOT`,
`POWER`. Extending it is a deliberate act, and each member carries a one-line
meaning so the registry can be read on its own.

What is deliberately **not** in the vocabulary: anything about *use*. The pin is
`PWM`; that the code drives a buzzer at 2.7kHz is intent, and it lives in
`intent.md`, not here.

## What `net` means, and where it comes from

The two sides name nets differently by nature, and getting this wrong is what
makes a cross-check either useless or hysterical. CubeMX has two fields:

* `GPIO_Label` — the name the engineer typed (`LED1`, `KEY2`). Wins when present.
* `Signal` — the assigned alternate function (`USART3_TX`, `I2C2_SCL`). For a
  peripheral pin that *is* what the schematic calls the net.

`GPIO_Output` / `GPIO_Input` are **not** net names — they are a direction. This
matters more than it looks: treating them as names made every GPIO pin look
named, while `PC4` — whose real name (`LCD_RES`) exists only in a hand-written
`main.h` macro — sailed through silently. So a GPIO signal leaves the baseline
silent, which is what lets `firmware_only_net` fire for exactly the pins that
deserve it.

## The three gates (`engines/pintable_check.py`)

All fail closed, and a gate that *cannot* run says so in a note rather than
staying quiet — a check that did not happen must never read as a check that
passed.

1. **The pin number exists on the MCU block's symbol.** `offsets` on the symbol
   is measured geometry: the pin numbers the library symbol actually exposes. A
   table naming a pin the symbol does not have would draw a wire into thin air.
   (The "ghost pin number" negative case.)
2. **One pin, one row.** A number appearing twice is two contradictory claims
   about one ball of silicon; the later row would silently win. Both readings go
   into the evidence. (The "one pin under two names" negative case.)
3. **The two-way difference against the spec.**
   * firmware names a net the spec never connects ⇒ **defect** — the firmware
     uses a pin the schematic does not wire;
   * the spec connects an MCU signal port the firmware never names ⇒
     **open question**, listed but *not* blocking. A board may legitimately have
     a pin the firmware has not grown into yet, and calling that a defect would
     make the checker wrong about real boards.

   Power and ground ports are excluded from direction 2 — `GND` is not a port
   the firmware forgot.

## The `.ioc` cross-check

`.ioc` is machine-readable ground truth for pin *assignment*; the C sources are
ground truth for pin *use*. Neither is believed silently. `cross_check()`
returns every disagreement, never a merged answer:

| Kind | Meaning |
|---|---|
| `missing_from_ioc` | firmware uses a pin the CubeMX project does not list |
| `missing_from_firmware` | CubeMX assigns a pin the firmware never mentions |
| `net_mismatch` | both name the pin, the names differ |
| `firmware_only_net` | firmware names the net, the baseline has none (the `LCD_RES` case) |
| `function_mismatch` | the assigned alternate function is not the firmware's function |

Virtual pins (`VP_*`) are read — so the count matches what CubeMX reports — and
then excluded from every comparison: a virtual pin has no ball to wire. The
`Mcu.Pin<k>` entry `PF0-OSC_IN` is reduced to its port-pin half, or every STM32
board ever made would report its oscillator pins as a permanent disagreement.
Settings this module does not model (`RCC.HSE_VALUE`) stay reachable verbatim in
`IocProject.raw`, so no second parser has to exist.

### Measured on the smart pillbox

`Smartbox.ioc` reports 34 pins — **28 physical, 6 virtual**. The C sources agree
with it on all 28. The single disagreement is `PC4`: the firmware calls it
`LCD_RES` (from `main.h`'s hand-added macro), and the baseline gives it no net
name at all. That is one open question for 岳翔宇, not a defect, and not
something this module will pick a side on.

Three further readings are recorded in the pin table's `notes` and are *not*
disagreements about pin assignment — they are facts about the board:

* `SystemClock_Config()` runs from `RCC_PLLSOURCE_HSI`, while the `.ioc`
  configures `PF0`/`PF1` as HSE with `RCC.HSE_VALUE=8000000`. That is a clock-tree
  question and a question for `intent.md`'s 8MHz crystal, not a pin conflict.
* `spi.c` sets `SPI_BAUDRATEPRESCALER_16` where the `.ioc` says `_64` — a
  parameter, not a pin.
* `huart3` enables the internal TX/RX swap (`UART_ADVFEATURE_SWAP_ENABLE`, and
  again via `CR2` in USER CODE 2) with the comment that the ESP-01S's TX/RX run
  the same direction as the MCU's on this PCB. The pin table names `PB10`
  `USART3_TX` per the MCU's own naming; what the far end sees is the other way
  round.

## Using it

```
boardwise pintable check --table inputs/smart_pillbox/pintable.json \
    --ioc inputs/smart_pillbox/firmware-mcu/Smartbox.ioc \
    [--spec <board spec> [--block <id>]]
```

Exit 0 when nothing blocks, 1 on a defect, 2 for bad input. Open questions are
printed in every case. Without `--spec`, gate 3 says it did not run.

## Where it lives

| Path | Role |
|---|---|
| `src/boardwise/core/pintable.py` | the contract, the closed vocabulary, the `.ioc` reader, `cross_check` |
| `src/boardwise/engines/pintable_check.py` | the three gates and the report |
| `inputs/smart_pillbox/pintable.json` | the smart pillbox table (28 pins) |
| `inputs/smart_pillbox/firmware-mcu/Smartbox.ioc` | the baseline |
| `tests/test_pintable.py` | contract, gates, the five conflict shapes, both real inputs |

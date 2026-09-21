"""One-off scan (task 015 batch-2 decision data): value-vs-MPN amplitude ratios.

For every board fixture, run the param-value-mpn-match pipeline and print each
VIOLATION row with declared value, decoded MPN value, and the ratio
(max/min). Read-only; writes outputs/015_amplitude_scan.txt.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from boardwise.cli import _load_model
from boardwise.rules import params as P
from boardwise.rules.values import (
    decode_eia_3digit,
    mpn_value_code,
    parse_capacitance_farads,
)

parse_resistance_ohms = P.parse_resistance_ohms

BOARDS = [
    "tests/fixtures/ProPrj_毕设FOC驱动板_2026-09-17.epro2",
    "tests/fixtures/ProPrj_CH340G_2026-09-13.epro2",
    "tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2",
    "tests/fixtures/ProPrj_智能药箱_2026-09-17.epro2",
    "tests/fixtures/ProPrj_高速电机控制器_2026-09-16.epro2",
    "tests/fixtures/board24v.enet",
    "tests/fixtures/llc_board.epro2",
    "reviewsets/injected/fixed-base.epro2",
    "reviewsets/injected/value-mpn-mismatch.epro2",
    "reviewsets/injected/duplicate-designator.epro2",
    "reviewsets/injected/nc-pin-grounded.epro2",
    "reviewsets/injected/overvoltage-rail.epro2",
    "reviewsets/injected/ldo-no-headroom.epro2",
]


def main() -> None:
    rule = P.ValueMpnMatch()
    out = []
    for board in BOARDS:
        path = Path(board)
        if not path.exists():
            out.append(f"### {board}  MISSING")
            continue
        model, _ = _load_model(path, view="schematic")
        rows = rule._rows(model)
        out.append(f"### {path.name}")
        n = 0
        for outcome, _sev in rows:
            if outcome.state != "VIOLATION":
                continue
            comp = model.components[outcome.subject]
            kind = P._kind_of(comp, rule.entry_for(comp))
            code = mpn_value_code(comp.mpn or "")
            if kind == "resistor":
                declared = parse_resistance_ohms(comp.value or "")
                decoded = decode_eia_3digit(code, 1.0)
                unit = "ohm"
            else:
                declared = parse_capacitance_farads(comp.value or "")
                decoded = decode_eia_3digit(code, 1e-12)
                unit = "F"
            ratio = max(declared, decoded) / min(declared, decoded)
            n += 1
            out.append(
                f"  {comp.designator:6s} kind={kind:9s} declared={declared:.4g} {unit}  "
                f"decoded={decoded:.4g} {unit}  ratio={ratio:6.2f}x  mpn={comp.mpn!r} value={comp.value!r}"
            )
        if n == 0:
            out.append("  (no VIOLATION)")
        out.append("")
    text = "\n".join(out)
    print(text)
    Path("outputs/015_amplitude_scan.txt").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

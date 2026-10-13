"""R5 recon probe: cross-check ``param-rc-cutoff`` against ngspice (not a boardwise feature).

For one RC reading the rule reports ("RC Rx + Cy on 'NET': fc = ..."), this
script extracts the node from the boardwise schematic model, writes a SPICE
netlist, runs ngspice in batch mode and measures the -3 dB frequency.

Two extractions are compared, because they answer different questions:

* ``pair``  — exactly the rule's reading: Rx from an AC source to NET, Cy from
  NET to ground. This checks the arithmetic (it must agree with the rule).
* ``node``  — the circuit as drawn: Rx from the source to NET, and **every**
  capacitor and resistor that runs from NET to a ground net. This is what the
  node actually does, and where it disagrees with the rule is the value of a
  simulation pass.

Anything else on NET (IC pins, parts to non-ground nets) is left out and listed
— a pin is modelled as an open circuit, which is the probe's limit, not a fact.

Usage (repo root):
    python tools/R5_ngspice_probe.py <fixture.epro2> <R ref> <C ref> <NET> <out_dir>
ngspice: env NGSPICE (default D:/tools/ngspice-47/Spice64/bin/ngspice_con.exe).
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

from boardwise import cli
from boardwise.core.model import is_ground_net
from boardwise.core.values import parse_capacitance_farads, parse_resistance_ohms

NGSPICE = os.environ.get("NGSPICE", "D:/tools/ngspice-47/Spice64/bin/ngspice_con.exe")


def _value(comp, kind):
    if kind == "R":
        return parse_resistance_ohms(comp.value or "")
    return parse_capacitance_farads(comp.value or "")


def _spice_name(ref: str, kind: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", ref)
    return safe if safe.upper().startswith(kind) else f"{kind}{safe}"


def extract(model, r_ref: str, c_ref: str, net: str, mode: str):
    r = model.components[r_ref]
    r_nets = [p.net for p in r.pins if p.net]
    if net not in r_nets or len(set(r_nets)) != 2:
        raise SystemExit(f"{r_ref} is not a two-terminal part on {net!r}: {r_nets}")
    source = next(n for n in r_nets if n != net)
    lines = [f"* R5 probe ({mode}): {r_ref} + {c_ref} on {net}", "V1 in 0 DC 0 AC 1",
             f"{_spice_name(r_ref, 'R')} in out {_value(r, 'R')!r}"]
    included, left_out = [r_ref], []
    for ref, comp in sorted(model.components.items()):
        if ref == r_ref:
            continue
        nets = [p.net for p in comp.pins if p.net]
        if net not in nets:
            continue
        others = [n for n in nets if n != net]
        kind = ref[0].upper()
        to_ground = len(nets) == 2 and others and is_ground_net(others[0])
        wanted = (ref == c_ref) if mode == "pair" else (to_ground and kind in ("C", "R"))
        if wanted:
            value = _value(comp, "C" if kind == "C" else "R")
            if value is None:
                left_out.append(f"{ref} ({comp.value!r}: value unreadable)")
                continue
            lines.append(f"{_spice_name(ref, kind)} out 0 {value!r}")
            included.append(ref)
        else:
            left_out.append(f"{ref} pins on {nets}")
    lines += [".control", "ac dec 200 0.001 1g",
              "meas ac f3db when vdb(out)=-3.0103 fall=1", "print f3db", ".endc", ".end"]
    return "\n".join(lines) + "\n", source, included, left_out


def run(cir: Path) -> float | None:
    proc = subprocess.run([NGSPICE, "-b", str(cir)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = proc.stdout + proc.stderr
    cir.with_suffix(".log").write_text(log, encoding="utf-8")
    match = re.search(r"f3db\s*=\s*([0-9.eE+-]+)", log)
    return float(match.group(1)) if match else None


def main() -> None:
    fixture, r_ref, c_ref, net, out_dir = sys.argv[1:6]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model = cli._load_model(Path(fixture), view="schematic")[0]
    r = parse_resistance_ohms(model.components[r_ref].value or "")
    c = parse_capacitance_farads(model.components[c_ref].value or "")
    rule_fc = 1.0 / (2 * math.pi * r * c)
    result = {"fixture": Path(fixture).name, "R": r_ref, "C": c_ref, "net": net,
              "rule_fc_hz": rule_fc, "ngspice": NGSPICE}
    for mode in ("pair", "node"):
        text, source, included, left_out = extract(model, r_ref, c_ref, net, mode)
        cir = out / f"{Path(fixture).stem}_{r_ref}_{c_ref}_{mode}.cir"
        cir.write_text(text, encoding="utf-8")
        result[mode] = {"source_net": source, "included": included, "left_out": left_out,
                        "f3db_hz": run(cir), "netlist": cir.name}
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""R3 KiCad fixture generator — a small, self-built project (no third-party design).

Run with KiCad's bundled Python (pcbnew is needed for the board):

    D:/tools/kicad-10.0.6/bin/python.exe tools/R3_make_kicad_fixture.py <out_dir>

Writes <out_dir>/kicad_min.{kicad_pro,kicad_sch,kicad_pcb} and the two oracles
KiCad itself produces from them: kicad_min.net (kicad-cli, kicadsexpr netlist)
and kicad_min.pcbnew.json (pcbnew's own reading of the board). The parser tests
compare boardwise's pure-Python reading against those two files.

The circuit (deliberately carrying three defects the L1/L2 rules should name):
  U1  AMS1117-3.3 (LCSC C6186): VI on +5V, VO on +3V3, GND on GND
  C1  10uF  on +5V            (input cap)
  C2  100nF on +3V3           (output cap; the shelf requires >= 22uF on VO) -> decap-required-caps
  R1  10k   +3V3 -> LED_A
  R3  1k    LED_A -> GND
  R3  4.7k  +3V3 -> SENSE     (a second "R3")                              -> conn-duplicate-designators
  R4  0.01  +5V -> VLOAD      (a milliohm shunt no IC reads)               -> shunt-sense-link
On the board: C2 sits 0.15 mm (pad edge to pad edge) from R3 (1k)       -> pcb-component-spacing
and far from U1                                                       -> pcb-decap-distance;
R1 is placed on the bottom side so the flipped-footprint transform is exercised.
Symbols are placed at rotations 0/90/180/270 and with mirror x / mirror y so
the pin transform is exercised; +3V3 and GND are each carried by more than one
power symbol so power-net joining is exercised; LED_A is a local label sitting
on a wire's interior; VLOAD is a global label.
"""
from __future__ import annotations

import json
import os
import math
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

KICAD = Path(os.environ.get("KICAD_DIR", "D:/tools/kicad-10.0.6"))
SYMBOLS = KICAD / "share/kicad/symbols"
NS = uuid.UUID("6f3a2c1e-0000-4000-8000-0000000000aa")
NAME = "kicad_min"


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


# --------------------------------------------------------------------------
# a tiny s-expression reader/writer (self-contained: this script runs under
# KiCad's python, which cannot import boardwise)
# --------------------------------------------------------------------------


class A(str):
    """bare atom"""


def parse(text):
    stack = [[]]
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            stack.append([])
            i += 1
        elif c == ")":
            done = stack.pop()
            stack[-1].append(done)
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while text[j] != '"':
                if text[j] == "\\":
                    buf.append({"n": "\n", "\\": "\\", '"': '"'}.get(text[j + 1], text[j + 1]))
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            stack[-1].append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            stack[-1].append(A(text[i:j]))
            i = j
    return stack[0][0]


def dump(node, indent=0):
    pad = "\t" * indent
    if not isinstance(node, list):
        return str(node) if isinstance(node, A) else '"' + str(node).replace("\\", "\\\\").replace('"', '\\"') + '"'
    if all(not isinstance(x, list) for x in node):
        return pad + "(" + " ".join(dump(x) for x in node) + ")"
    head = [x for x in node if not isinstance(x, list)]
    out = pad + "(" + " ".join(dump(x) for x in head)
    for child in node:
        if isinstance(child, list):
            out += "\n" + dump(child, indent + 1)
    return out + "\n" + pad + ")"


def find(node, head):
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def first(node, head):
    found = find(node, head)
    return found[0] if found else None


# --------------------------------------------------------------------------
# library symbols, flattened (a schematic embeds derived symbols resolved)
# --------------------------------------------------------------------------

_LIBS: dict[str, list] = {}


def _lib(lib):
    if lib not in _LIBS:
        _LIBS[lib] = parse((SYMBOLS / f"{lib}.kicad_sym").read_text(encoding="utf-8"))
    return _LIBS[lib]


def lib_symbol(lib, name):
    tree = _lib(lib)
    sym = next(s for s in find(tree, "symbol") if s[1] == name)
    ext = first(sym, "extends")
    if ext is not None:
        parent = lib_symbol(lib, ext[1])
        # derived: the child's properties over the parent's body
        props = {p[1]: p for p in find(sym, "property")}
        body = [c for c in parent[2:] if not (isinstance(c, list) and c and c[0] == "property")]
        merged_props = [props.get(p[1], p) for p in find(parent, "property")]
        merged_props += [p for k, p in props.items() if k not in {q[1] for q in find(parent, "property")}]
        units = []
        for c in body:
            if isinstance(c, list) and c and c[0] == "symbol":
                units.append([A("symbol"), c[1].replace(parent[1].split(":")[-1], name, 1)] + c[2:])
            else:
                units.append(c)
        return [A("symbol"), f"{lib}:{name}"] + merged_props + units
    return [A("symbol"), f"{lib}:{name}"] + sym[2:]


def lib_pins(sym):
    pins = {}
    for unit in find(sym, "symbol"):
        for pin in find(unit, "pin"):
            at = first(pin, "at")
            pins[str(first(pin, "number")[1])] = (float(at[1]), float(at[2]))
    return pins


def transform(at, rot, mirror, p):
    """Library point -> sheet point. Hypothesis checked by kicad-cli's netlist:
    library y is up, the sheet's is down; the mirror is applied in sheet
    space after the rotation (measured: the other order swaps R3's pins)."""
    x, y = p[0], -p[1]  # library y-up -> sheet y-down
    r = math.radians(rot)
    sx = x * math.cos(r) + y * math.sin(r)
    sy = -x * math.sin(r) + y * math.cos(r)
    if mirror == "x":  # mirrored about the X axis, after the rotation
        sy = -sy
    elif mirror == "y":  # mirrored about the Y axis, after the rotation
        sx = -sx
    return (round(at[0] + sx, 4), round(at[1] + sy, 4))


# --------------------------------------------------------------------------
# the circuit
# --------------------------------------------------------------------------

PARTS = [
    # ref, lib, name, value, footprint, at, rot, mirror, fields
    ("U1", "Regulator_Linear", "AMS1117-3.3", "AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
     (60.96, 50.8), 0, None, {"LCSC": "C6186", "MPN": "AMS1117-3.3", "Manufacturer": "AMS"}),
    ("C1", "Device", "C", "10uF", "Capacitor_SMD:C_0805_2012Metric", (40.64, 76.2), 0, None, {"LCSC": "C15850"}),
    ("C2", "Device", "C", "100nF", "Capacitor_SMD:C_0603_1608Metric", (40.64, 96.52), 180, None, {"LCSC": "C14663"}),
    ("R1", "Device", "R", "10k", "Resistor_SMD:R_0603_1608Metric", (40.64, 116.84), 90, None, {"LCSC": "C25804"}),
    ("R3", "Device", "R", "1k", "Resistor_SMD:R_0603_1608Metric", (40.64, 132.08), 270, None, {"LCSC": "C21190"}),
    ("R3", "Device", "R", "4.7k", "Resistor_SMD:R_0603_1608Metric", (40.64, 147.32), 90, "y", {"LCSC": "C23162"}),
    ("R4", "Device", "R", "0.01", "Resistor_SMD:R_1206_3216Metric", (40.64, 167.64), 0, "x", {"LCSC": "C25336"}),
]

# How every pin is tied (net name, kind): "power" hangs a power symbol on the
# pin's stub, "label"/"global" a label, "bus5v" joins the +5V bus at x=20.32,
# "ledA" joins the LED_A wire. Pin index = position in PARTS.
TIES = {
    (0, "1"): ("GND", "power"), (0, "2"): ("+3V3", "power"), (0, "3"): ("+5V", "bus5v"),
    (1, "1"): ("+5V", "bus5v"), (1, "2"): ("GND", "power"),
    (2, "1"): ("+3V3", "power"), (2, "2"): ("GND", "power"),
    (3, "1"): ("+3V3", "power"), (3, "2"): ("LED_A", "ledA"),
    (4, "1"): ("LED_A", "ledA"), (4, "2"): ("GND", "power"),
    (5, "1"): ("+3V3", "power"), (5, "2"): ("SENSE", "label"),
    (6, "1"): ("+5V", "bus5v"), (6, "2"): ("VLOAD", "global"),
}
BUS_5V_X = 20.32
STUB = 2.54


def lib_pin_dirs(sym):
    dirs = {}
    for unit in find(sym, "symbol"):
        for pin in find(unit, "pin"):
            at = first(pin, "at")
            dirs[str(first(pin, "number")[1])] = float(at[3]) if len(at) > 3 else 0.0
    return dirs


def outward(rot, mirror, angle):
    """Unit vector pointing away from the body, in sheet coordinates."""
    dx, dy = -math.cos(math.radians(angle)), math.sin(math.radians(angle))
    r = math.radians(rot)
    ox, oy = dx * math.cos(r) + dy * math.sin(r), -dx * math.sin(r) + dy * math.cos(r)
    if mirror == "x":
        oy = -oy
    elif mirror == "y":
        ox = -ox
    return (round(ox, 6), round(oy, 6))


def build_schematic(out: Path) -> None:
    libsyms = {}
    for ref, lib, name, *_ in PARTS:
        libsyms[f"{lib}:{name}"] = lib_symbol(lib, name)
    for p in ("GND", "+5V", "+3V3"):
        libsyms[f"power:{p}"] = lib_symbol("power", p)

    pin_at, stub_at = {}, {}
    for idx, (ref, lib, name, value, fp, at, rot, mirror, fields) in enumerate(PARTS):
        sym = libsyms[f"{lib}:{name}"]
        dirs = lib_pin_dirs(sym)
        for number, p in lib_pins(sym).items():
            point = transform(at, rot, mirror, p)
            ox, oy = outward(rot, mirror, dirs[number])
            pin_at[(idx, number)] = point
            stub_at[(idx, number)] = (round(point[0] + ox * STUB, 4), round(point[1] + oy * STUB, 4))

    wires, junctions, labels, power_instances = [], [], [], []

    def wire(a, b):
        if a != b:
            wires.append((a, b))

    bus_points = []
    led = []
    for key, (net, kind) in TIES.items():
        pin, stub = pin_at[key], stub_at[key]
        wire(pin, stub)
        if kind == "power":
            power_instances.append((net, stub, 0))
        elif kind in ("label", "global"):
            labels.append(("global_label" if kind == "global" else "label", net, stub))
        elif kind == "bus5v":
            bus_points.append(stub)
        elif kind == "ledA":
            led.append(stub)
    # +5V: every member runs horizontally to x = BUS_5V_X, then one vertical bus;
    # a member meeting the bus between its two ends gets a junction (a T).
    ys = sorted(p[1] for p in bus_points)
    wire((BUS_5V_X, ys[0]), (BUS_5V_X, ys[-1]))
    for p in bus_points:
        wire(p, (BUS_5V_X, p[1]))
        if ys[0] < p[1] < ys[-1]:
            junctions.append((BUS_5V_X, p[1]))
    power_instances.append(("+5V", (BUS_5V_X, ys[0]), 0))
    # LED_A: one wire between the two stubs, the label on its interior.
    a, b = sorted(led, key=lambda q: q[1])
    assert a[0] == b[0], (a, b)
    wire(a, b)
    labels.append(("label", "LED_A", (a[0], round((a[1] + b[1]) / 2, 4))))

    def prop(key, value, at, hide=False):
        eff = [A("effects"), [A("font"), [A("size"), A("1.27"), A("1.27")]]]
        if hide:
            eff.append([A("hide"), A("yes")])
        return [A("property"), key, value, [A("at"), A(f"{at[0]:g}"), A(f"{at[1]:g}"), A("0")], eff]

    def symbol(lib_id, ref, value, footprint, at, rot, mirror, fields, key, pins):
        node = [A("symbol"), [A("lib_id"), lib_id], [A("at"), A(f"{at[0]:g}"), A(f"{at[1]:g}"), A(str(rot))]]
        if mirror:
            node.append([A("mirror"), A(mirror)])
        node += [[A("unit"), A("1")], [A("exclude_from_sim"), A("no")], [A("in_bom"), A("yes")],
                 [A("on_board"), A("yes")], [A("dnp"), A("no")], [A("uuid"), uid(key)],
                 prop("Reference", ref, (at[0] + 2.54, at[1] - 2.54)),
                 prop("Value", value, (at[0] + 2.54, at[1] + 2.54)),
                 prop("Footprint", footprint, at, hide=True),
                 prop("Datasheet", "", at, hide=True),
                 prop("Description", "", at, hide=True)]
        node += [prop(k, v, at, hide=True) for k, v in fields.items()]
        node += [[A("pin"), n, [A("uuid"), uid(f"{key}.{n}")]] for n in sorted(pins)]
        node.append([A("instances"), [A("project"), NAME,
                     [A("path"), f"/{uid('root')}", [A("reference"), ref], [A("unit"), A("1")]]]])
        return node

    items = []
    for idx, (ref, lib, name, value, fp, at, rot, mirror, fields) in enumerate(PARTS):
        pins = lib_pins(libsyms[f"{lib}:{name}"])
        items.append(symbol(f"{lib}:{name}", ref, value, fp, at, rot, mirror, fields, f"{ref}#{idx}", pins))
    for i, (kind, at, rot) in enumerate(power_instances):
        pins = lib_pins(libsyms[f"power:{kind}"])
        items.append(symbol(f"power:{kind}", f"#PWR0{i + 1:02d}", kind, "", at, rot, None, {}, f"pwr{i}", pins))
    for a, b in wires:
        items.append([A("wire"), [A("pts"), [A("xy"), A(f"{a[0]:g}"), A(f"{a[1]:g}")], [A("xy"), A(f"{b[0]:g}"), A(f"{b[1]:g}")]],
                      [A("stroke"), [A("width"), A("0")], [A("type"), A("default")]], [A("uuid"), uid(f"w{a}{b}")]])
    for j in junctions:
        items.append([A("junction"), [A("at"), A(f"{j[0]:g}"), A(f"{j[1]:g}")], [A("diameter"), A("0")],
                      [A("color"), A("0"), A("0"), A("0"), A("0")], [A("uuid"), uid(f"j{j}")]])
    for kind, text, at in labels:
        node = [A(kind), text]
        if kind == "global_label":
            node.append([A("shape"), A("output")])
        node += [[A("at"), A(f"{at[0]:g}"), A(f"{at[1]:g}"), A("0")],
                 [A("effects"), [A("font"), [A("size"), A("1.27"), A("1.27")]], [A("justify"), A("left")]],
                 [A("uuid"), uid(f"l{text}")]]
        items.append(node)

    sch = [A("kicad_sch"), [A("version"), A("20250114")], [A("generator"), "eeschema"],
           [A("generator_version"), "9.0"], [A("uuid"), uid("root")], [A("paper"), "A4"],
           [A("lib_symbols")] + list(libsyms.values()), *items,
           [A("sheet_instances"), [A("path"), "/", [A("page"), "1"]]], [A("embedded_fonts"), A("no")]]
    out.write_text(dump(sch) + chr(10), encoding="utf-8")


# --------------------------------------------------------------------------
# the board (pcbnew), and pcbnew's own reading of it as the second oracle
# --------------------------------------------------------------------------

# ref-index -> (x mm, y mm, rotation deg, side)
PLACEMENT = {
    0: (115.0, 110.0, 0, "F"),     # U1 SOT-223
    1: (106.0, 110.0, 90, "F"),    # C1 0805
    2: (132.6, 120.0, 0, "F"),     # C2 0603: far from U1, pad edges 0.15 mm from R3 (1k)
    3: (125.0, 125.0, 0, "B"),     # R1 on the bottom side
    4: (130.0, 120.0, 0, "F"),     # R3 (1k)
    5: (130.0, 128.0, 0, "F"),     # R3 (4.7k), clear of everything
    6: (140.0, 110.0, 270, "F"),   # R4 1206
}
OUTLINE = [(100.0, 100.0), (160.0, 100.0), (160.0, 140.0), (100.0, 140.0)]


def build_board(out: Path, nets_by_pin: dict) -> dict:
    import pcbnew

    fp_root = KICAD / "share/kicad/footprints"
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    nets = {}

    def net(name):
        if name not in nets:
            item = pcbnew.NETINFO_ITEM(board, name)
            board.Add(item)
            nets[name] = item
        return nets[name]

    mm = pcbnew.FromMM
    footprints = {}
    for idx, (ref, lib, name, value, fpid, at, rot, mirror, fields) in enumerate(PARTS):
        lib_name, fp_name = fpid.split(":")
        fp = pcbnew.FootprintLoad(str(fp_root / f"{lib_name}.pretty"), fp_name)
        fp.SetReference(ref)
        fp.SetValue(value)
        for key, val in fields.items():
            fp.SetField(key, val)
        x, y, r, side = PLACEMENT[idx]
        board.Add(fp)
        fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        fp.SetOrientationDegrees(r)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        for pad in fp.Pads():
            info = nets_by_pin.get((idx, pad.GetNumber()))
            if info:
                pad.SetNet(net(info["net"]))
                if info.get("pinfunction"):
                    pad.SetPinFunction(info["pinfunction"])
                if info.get("pintype"):
                    pad.SetPinType(info["pintype"])
        footprints[idx] = fp

    def pad_pos(idx, number):
        return next(p for p in footprints[idx].Pads() if p.GetNumber() == number).GetPosition()

    def track(a, b, name, width=0.3, layer=None):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(a)
        t.SetEnd(b)
        t.SetWidth(mm(width))
        t.SetLayer(pcbnew.F_Cu if layer is None else layer)
        t.SetNet(net(name))
        board.Add(t)

    # +5V: C1.1 - U1.3, U1.3 - R4.1 (with a bend)
    track(pad_pos(1, "1"), pad_pos(0, "3"), "+5V", 0.5)
    # U1.3 -> R4.1 around everything: down, right, up, and into R4.1 from above
    u3, r41 = pad_pos(0, "3"), pad_pos(6, "1")
    route = [u3, pcbnew.VECTOR2I(u3.x, mm(116.0)), pcbnew.VECTOR2I(mm(143.0), mm(116.0)),
             pcbnew.VECTOR2I(mm(143.0), mm(106.0)), pcbnew.VECTOR2I(r41.x, mm(106.0)), r41]
    for a, b in zip(route, route[1:]):
        track(a, b, "+5V", 0.5)
    # LED_A: R3(1k).1 is on F.Cu, R1.2 on the bottom side, so through a via
    via_at = pcbnew.VECTOR2I(mm(122.0), mm(123.0))  # left of R1, so the B.Cu run meets R1.2 from outside
    track(pad_pos(4, "1"), via_at, "LED_A", 0.25)
    track(via_at, pad_pos(3, "2"), "LED_A", 0.25, pcbnew.B_Cu)
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(via_at)
    v.SetDrill(mm(0.3))
    v.SetWidth(mm(0.6))
    v.SetNet(net("LED_A"))
    board.Add(v)
    # a GND stitching via
    g = pcbnew.PCB_VIA(board)
    g.SetPosition(pcbnew.VECTOR2I(mm(110.0), mm(135.0)))
    g.SetDrill(mm(0.4))
    g.SetWidth(mm(0.8))
    g.SetNet(net("GND"))
    board.Add(g)

    for (x0, y0), (x1, y1) in zip(OUTLINE, OUTLINE[1:] + OUTLINE[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
        seg.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.1))
        board.Add(seg)

    zone = pcbnew.ZONE(board)
    zone.SetLayer(pcbnew.B_Cu)
    zone.SetNet(net("GND"))
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in [(101, 101), (159, 101), (159, 139), (101, 139)]:
        outline.Append(mm(x), mm(y))
    board.Add(zone)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    pcbnew.SaveBoard(str(out), board)

    # pcbnew's own reading — what boardwise's parser must reproduce.
    def pt(v):
        return [round(pcbnew.ToMM(v.x), 6), round(pcbnew.ToMM(v.y), 6)]

    board = pcbnew.LoadBoard(str(out))
    oracle = {"footprints": [], "tracks": [], "vias": [], "zones": [], "outline": []}
    for fp in board.GetFootprints():
        oracle["footprints"].append({
            "ref": fp.GetReference(), "value": fp.GetValue(), "layer": board.GetLayerName(fp.GetLayer()),
            "pos": pt(fp.GetPosition()), "rot": fp.GetOrientationDegrees(),
            "fpid": fp.GetFPIDAsString(),
            "pads": [{
                "number": pad.GetNumber(), "net": pad.GetNetname(), "pos": pt(pad.GetPosition()),
                "size": [round(pcbnew.ToMM(pad.GetSize(pcbnew.F_Cu).x), 6), round(pcbnew.ToMM(pad.GetSize(pcbnew.F_Cu).y), 6)],
                "angle": pad.GetOrientationDegrees(),
                "copper": [board.GetLayerName(layer) for layer in pad.GetLayerSet().CuStack()],
                "drill": round(pcbnew.ToMM(pad.GetDrillSize().x), 6),
                "pinfunction": pad.GetPinFunction(), "pintype": pad.GetPinType(),
            } for pad in fp.Pads()],
        })
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            oracle["vias"].append({"pos": pt(t.GetPosition()), "width": round(pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)), 6),
                                   "drill": round(pcbnew.ToMM(t.GetDrillValue()), 6), "net": t.GetNetname()})
        else:
            oracle["tracks"].append({"start": pt(t.GetStart()), "end": pt(t.GetEnd()), "width": round(pcbnew.ToMM(t.GetWidth()), 6),
                                     "layer": board.GetLayerName(t.GetLayer()), "net": t.GetNetname()})
    for z in board.Zones():
        filled = z.GetFilledPolysList(z.GetLayer())
        oracle["zones"].append({"net": z.GetNetname(), "layer": board.GetLayerName(z.GetLayer()),
                                "filled_outlines": filled.OutlineCount(),
                                "filled_area_mm2": round(filled.Area() / 1e12, 4)})
    box = board.GetBoardEdgesBoundingBox()
    oracle["outline"] = [pt(box.GetOrigin()), pt(box.GetEnd())]
    return oracle


def nets_from_oracle(netlist_path: Path) -> dict:
    """(part index, pin) -> {net, pinfunction, pintype}, read back from KiCad's netlist.

    The netlist names pins by reference, and two parts share ``R3`` on purpose;
    their pins are disambiguated by the design table (TIES) instead."""
    tree = parse(netlist_path.read_text(encoding="utf-8"))
    by_ref_pin = {}
    for n in find(first(tree, "nets"), "net"):
        name = first(n, "name")[1]
        for node in find(n, "node"):
            key = (first(node, "ref")[1], first(node, "pin")[1])
            by_ref_pin.setdefault(key, []).append({
                "net": name.lstrip("/"),
                "pinfunction": first(node, "pinfunction")[1] if first(node, "pinfunction") else "",
                "pintype": first(node, "pintype")[1] if first(node, "pintype") else "",
            })
    out = {}
    for (idx, number), (net_name, _kind) in TIES.items():
        ref = PARTS[idx][0]
        options = [o for o in by_ref_pin.get((ref, number), []) if o["net"] == net_name]
        assert options, (ref, number, net_name, by_ref_pin.get((ref, number)))
        out[(idx, number)] = options[0]
    return out


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    sch = out_dir / f"{NAME}.kicad_sch"
    build_schematic(sch)
    cli = KICAD / "bin" / "kicad-cli.exe"
    # Let KiCad rewrite the file in its own current format (the file a user
    # would actually have), then export KiCad's own netlist as the oracle.
    subprocess.run([str(cli), "sch", "upgrade", "--force", str(sch)], check=True, capture_output=True)
    subprocess.run([str(cli), "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", str(out_dir / f"{NAME}.net"), str(sch)], check=True, capture_output=True)
    oracle = build_board(out_dir / f"{NAME}.kicad_pcb", nets_from_oracle(out_dir / f"{NAME}.net"))
    (out_dir / f"{NAME}.pcbnew.json").write_text(json.dumps(oracle, indent=1, ensure_ascii=False) + chr(10), encoding="utf-8")
    project = {"meta": {"filename": f"{NAME}.kicad_pro", "version": 3},
               "boardwise": {"note": "self-built R3 fixture; generator tools/R3_make_kicad_fixture.py"}}
    (out_dir / f"{NAME}.kicad_pro").write_text(json.dumps(project, indent=2) + chr(10), encoding="utf-8")
    print("schematic, netlist, board and pcbnew oracle written")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

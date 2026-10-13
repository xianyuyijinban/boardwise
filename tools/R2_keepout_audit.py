# R2-1 evidence script: what pcb-keepout-violation compared on every fixture board with keepouts,
# and how the verdict reads with voids (the rule) vs outline-only vs chord-only points.
#   python tools/R2_keepout_audit.py > outputs/R2/keepout_audit.json
"""R2-1 audit: on every fixture board with keepouts, what did the rule actually compare?

For each region: the words, every poured/fill island on the layer, and the verdict
with voids (the rule) vs. outline-only (what a reader without R2-1's rings would say)
vs. chord-only `points` (what 162b-era geometry would say).
"""
import json
import sys
from pathlib import Path

from boardwise.engines.pcbreview import _pcb_documents
from boardwise.parsers.epru import extract_board, load_epro2_source
from boardwise.rules.pcb import keepout as K

report = {}
for path in sorted(Path("tests/fixtures").glob("*.epro2")):
    src = load_epro2_source(path)
    for title, _u, doc in _pcb_documents(src):
        board = extract_board(doc, src.footprints(), src.stats, src.footprint_artwork())
        if not board.prohibit_regions:
            continue
        rows = []
        for region in board.prohibit_regions:
            area = K._region_area(region)
            words, unknown = K.prohibited_kinds(region.prohibit_types)
            compared = []
            for pour in board.pours:
                if pour.kind not in ("poured", "fill"):
                    continue
                if pour.layer_id is not None and not K._on_layer(region, pour.layer_id):
                    continue
                rings = pour.rings or [pour.points]
                with_voids = K._rings_meet(rings, area)
                outline_only = K._rings_meet(rings[:1], area)
                chords = K._rings_meet([pour.points], area) if len(pour.points) >= 3 else None
                if with_voids or outline_only or chords:
                    compared.append({
                        "pour": pour.id, "kind": pour.kind, "net": pour.net, "layer": pour.layer_id,
                        "rings": len(rings), "with_voids": with_voids, "outline_only": outline_only,
                        "chords_points": chords,
                    })
            tracks = sum(1 for t in board.tracks if K._on_layer(region, t.layer_id) and K._capsule_meets(t.start, t.end, t.width / 2, area))
            rows.append({
                "region": region.id, "layer": region.layer_id, "words": words, "unknown": unknown,
                "circle_r": region.radius, "eroded_r": area.radius if area.centre else None,
                "pours_touching_by_any_reading": compared,
                "tracks_on_layer_inside (not forbidden by COPPER)": tracks,
            })
        report[f"{path.name}::{title}"] = rows
json.dump(report, sys.stdout, ensure_ascii=False, indent=1)

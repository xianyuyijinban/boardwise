# PROGRESS — milestones, versions, reproducible baselines

Living index. Details live in `tasks/*.md` (one book per task) and
`docs/implementation-log.md` (the connector debugging arc). This file only
collects the current truth and the pointers.

## Current baseline (2026-09-19, commit ce044a6)

- pytest: **903 passed** (run with `--basetemp=.tmp_pt_home` on Windows —
  the host's safe-delete hook otherwise eats the summary line and fakes
  exit 1)
- connector: **187 pass / 0 fail** (`cd connector && npm test`)
- `npx tsc --noEmit`: clean
- connector version: **0.4.5** (`connector/extension.json`)
- Verified host: EasyEDA Pro **3.2.186** (the only host the bridge is
  calibrated against; every real-host fact in the task books names it)

## Milestones

| Milestone | State | Proof |
|---|---|---|
| M0 baseline & unified entry | **DONE 2026-09-19** | tag `m0-baseline`; four real-host persistence scenarios PASS (`docs/persistence-baseline.md`); P0a write-path validation; P0d three-state persistence + 009d2 disconnect honesty (exit 3 exists); golden replay real-host netlist diff zero (010c M6) |
| M1 useful schematic review |立项 2026-09-19 | `tasks/011-review-rules-m1.md` |

## Coordinate contract (the thing that cost the most sessions)

File ≡ canvas, y up; `.epro2` stores `y = −canvas`; the parser negates once
at its boundary and nowhere else. Rotation: the file's angle reads CCW, the
editor API turns CW, `θ_file ≡ −θ_API`; `transform_point` (CCW) computes
landings, `draw.py::_editor_rotation` (negation) is the only conversion
point. Full measurement history: `tasks/010c-coordinate-convention.md`
(appendices A→C, including the wrong turn).

## Git anchors

- `1251971` initial commit
- tag `m0-baseline` — M0 exit state (before the 010 arc)
- `d409026` connector 0.4.5 lock-window retry (010b)
- `ce044a6` coordinate convention + AMS1117 idiom block (010+010c)

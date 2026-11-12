# PolyXRD NCM

**A dedicated tool for XRD powder diffraction refinement of ternary lithium-ion cathode materials (NCM).**

Member of the PolyXRD family: [PolyXRD](https://github.com/PolyXRD) (data analysis) ·
PolyXRD-Converter (format conversion) · PolyXRD-SynthPattern (pattern synthesis) ·
PolyXRD-RutAna (TiO₂ polymorph ratio) · PolyXRD-Graphite (degree of graphitization) · **NCM (this project)**

## What it is

One window, right from the start: the pattern on the left (pattern reading + smoothing / background subtraction / Kα2 stripping / peak finding / single-peak fitting), and built-in
COD CIFs of layered NCM ternary cathode materials on the right (811 / 622 / 523 / 111 and precursors). After importing XRD data it
first performs an "is it layered NCM" decision — if not, a dialog stops; if yes, it performs full-pattern Rietveld refinement starting from the CIF,
outputting unit-cell parameters, crystallite size, crystal system / point group / space group / Laue group, Li occupancy and Rwp/RB/GOF, with export support.

> Status: **v0.1.0 in development** (P0 project-initiation phase). For the feature list see `docs/PROJECT_PLAN.md`,
> for task progress see `docs/TASKS.md`.

## Documentation

| Document | Content |
|---|---|
| `docs/PROJECT_PLAN.md` | Scheme, feasibility measurements, 8-phase roadmap |
| `docs/TASKS.md` | Atomic task cards and acceptance commands |
| `docs/CIF_SOURCE.md` | COD source register of the built-in CIFs |
| `docs/STD_FREEZE.md` | Criteria and convention freeze |

## Running tests

```bash
cd /d/Project/PolyXRD-Tools/PolyXRD-NCM
D:/Project/XRD/python310/python.exe -m pytest -q
```

## License

Dual license (Academic / Commercial), see `LICENSE` and `LICENSE-CN`.
For commercial licensing contact: sshztx@outlook.com · https://github.com/PolyXRD

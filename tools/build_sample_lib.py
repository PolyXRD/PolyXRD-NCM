"""构建判定门样本库（T5.2）。

从家族只读数据根挑选**真实**谱作负样本，缺失的类别用**合成**谱补齐，
并生成 `tests/data/manifest.json`（每个样本的来源、期望结论）。

用法
----
```bash
D:/Project/XRD/python310/python.exe tools/build_sample_lib.py
```

**设计原则**
- **真实优先**：负样本尽量用家族实测谱（含仪器宽化、织构、背景、非晶等
  真实世界的所有麻烦），合成谱只用于补齐没有实测数据的类别。
- **数据根只读**：只复制到项目内 `tests/data/`，不写回 `D:/Project/XRD`。
- **期望值写进 manifest**：判定门的行为由 manifest 断言，不靠人记。
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from gen_virtual import (DEFAULT_U, DEFAULT_V, DEFAULT_W, LAMBDA_KA1,
                         synth_tch, x_from_strain, y_from_size_nm)
from ncm.core.profile.cif import CifStructure
from ncm.core.solve import builtin_structure

DATA_ROOT = Path("D:/Project/XRD")
LIB = ROOT / "tests" / "data"
SEED = 20260701

#: 合成谱的默认 2θ 网格（贴近真实实验室谱）
GRID = np.arange(10.0, 80.0, 0.02)


def _synth_text(struct: CifStructure, d_nm: float, eps: float = 0.0,
                seed: int = SEED) -> str:
    """合成一条两列文本谱（含背景 + 计数噪声）。"""
    prof = synth_tch(struct, GRID, d_nm, eps, DEFAULT_U, DEFAULT_V, DEFAULT_W)
    prof = prof / max(prof.max(), 1e-12) * 10000.0
    rng = np.random.default_rng(seed)
    y = prof + 200.0 + rng.normal(0.0, np.sqrt(np.maximum(prof, 1.0)))
    lines = [f"# PolyXRD-NCM 合成谱 | {struct.name} | D={d_nm:g} nm | "
             f"ε={eps:g} | X={x_from_strain(eps):.5f}° "
             f"Y={y_from_size_nm(d_nm):.5f}° | seed={seed}"]
    lines += [f"{t:.4f} {i:.4f}" for t, i in zip(GRID, y)]
    return "\n".join(lines) + "\n"


def _copy_real(src_rel: str, dst: Path) -> None:
    """从数据根复制真实谱（只读数据根，只写项目内）。

    统一转成**两列文本**（`#` 头 + 两列数值），不保留原扩展名：
    原文件有 .RAW/.TXT/.mdi 等多种格式，扩展名一变读谱器的格式嗅探就失效
    （实测 .RAW 复制成 .txt 后报"未找到可用的数值谱图数据"）。
    """
    from ncm.core.patterns import load_pattern

    src = DATA_ROOT / src_rel
    if not src.exists():
        raise FileNotFoundError(f"数据根缺少: {src}")
    pat = load_pattern(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# 来源: {src_rel}",
             f"# 区间: {pat.two_theta[0]:.4f}-{pat.two_theta[-1]:.4f}° "
             f"({pat.two_theta.size} 点)"]
    lines += [f"{t:.4f} {i:.4f}"
              for t, i in zip(pat.two_theta, pat.intensity)]
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 样本定义
# ---------------------------------------------------------------------------
#: (类别, 文件名, 数据根相对路径, 说明, expect_ok, expect_kind)
#: expect_kind 取值：ncm / precursor_hydroxide / precursor_carbonate / other
REAL_SAMPLES = [
    # --- 正样本 ---
    ("positive/ncm", "ncm811_real.txt",
     "XRData/csuHJW/txt/Data040：NCM：811_raw.txt", "真实 NCM811 实样",
     True, "ncm"),
    # --- 尖晶石 ---
    ("negative/spinel", "alcoo_650c_real.txt",
     "XRData/csuHJW/data005：AlCoO-650C.txt", "AlCoO₂ 尖晶石", False, "other"),
    ("negative/spinel", "alcoo_750c_real.txt",
     "XRData/csuHJW/data004：AlCoO-750C.txt", "AlCoO₂ 尖晶石", False, "other"),
    ("negative/spinel", "magnetite_iucr.txt",
     "XRData/IUCr/MAGNETIT.RAW", "Fe₃O₄ 尖晶石", False, "other"),
    # --- 橄榄石（LFP / FePO₄）---
    ("negative/lfp", "lifepo4_smz.txt",
     "XRData/smz geshi/LiFePO4#01##20250520-100220_100.txt",
     "LiFePO₄ 橄榄石 Pnma", False, "other"),
    ("negative/lfp", "fepo4_smz.txt",
     "XRData/smz geshi/FePO4#01##20250520-132913_100.txt",
     "FePO₄ 橄榄石型", False, "other"),
    # --- 岩盐型（Fm-3m）---
    ("negative/rocksalt", "fluorite_iucr.txt",
     "XRData/IUCr/FLUORITE.RAW", "CaF₂，Fm-3m 岩盐型", False, "other"),
    # --- 前驱体 ---
    ("negative/precursor", "ni_oh2_csu.txt",
     "XRData/csuHJW/Data043/Data043：Ni(OH)2.txt",
     "真实 β-Ni(OH)₂（a≈2.68 Å）；池内 COD 1548811 为另一多型（a=3.127 Å），"
     "故分流为 other —— 前驱体分流依赖 CIF 多型匹配，是已知局限",
     False, "other"),
    # --- 其他非层状 / 混合相 ---
    ("negative/other", "anatase_csu.txt",
     "XRData/csuHJW/txt/Data033：单相锐钛矿.txt", "单相锐钛矿", False, "other"),
    ("negative/other", "y2o3_csu.txt",
     "XRData/csuHJW/txt/Data038：Y2O3.txt", "Y₂O₃ 方铍石型（立方）",
     False, "other"),
    ("negative/other", "zno_caco3_csu.txt",
     "XRData/csuHJW/Data041/Data041：ZnO+CaCO3.txt",
     "ZnO + CaCO₃（CaCO₃ 为 R-3c）", False, "other"),
    ("negative/other", "limno2_si_csu.txt",
     "XRData/csuHJW/txt/Data030：LiMnO2+Si.txt", "正交 LiMnO₂ + Si",
     False, "other"),
    ("negative/other", "zrb_zrb2_csu.txt",
     "XRData/csuHJW/txt/Data031：ZrB-ZrB2.txt", "六方硼化物", False, "other"),
]

#: 岩盐 NiO（合成；家族无实测单相岩盐谱）
NIO_STRUCT = CifStructure(
    "NiO", (4.177, 4.177, 4.177, 90.0, 90.0, 90.0),
    [("Ni", 0.0, 0.0, 0.0, 1.0, 0.0), ("O", 0.5, 0.5, 0.5, 1.0, 0.0)])


def build() -> list[dict]:
    manifest: list[dict] = []

    # --- 真实谱 ---
    for folder, name, source, note, exp_ok, exp_kind in REAL_SAMPLES:
        dst = LIB / folder / name
        _copy_real(source, dst)
        manifest.append({
            "file": str((LIB / folder / name).relative_to(LIB)).replace("\\", "/"),
            "category": folder.split("/")[1],
            "origin": "real",
            "source": source,
            "note": note,
            "expect_ok": exp_ok,
            "expect_kind": exp_kind,
        })

    # --- 合成谱 ---
    # (类别, 文件名, 结构, D_nm, ε, 说明, expect_ok, expect_kind)
    synth_specs = [
        ("positive/ncm", "ncm111_syn.txt", "NCM111", 150.0, 0.0,
         "内置 CIF COD 3000558 合成", True, "ncm"),
        ("positive/ncm", "ncm523_syn.txt", "NCM523", 150.0, 0.0,
         "内置派生 CIF 合成", True, "ncm"),
        ("positive/ncm", "ncm622_syn.txt", "NCM622", 200.0, 0.0,
         "内置派生 CIF 合成", True, "ncm"),
        ("positive/ncm", "linio2_syn.txt", "LiNiO2", 120.0, 0.0005,
         "内置 CIF COD 1533770 合成（含 0.05% 应变）", True, "ncm"),
        ("negative/lco", "lco_d120nm_syn.txt", "LiCoO2", 120.0, 0.0,
         "内置 CIF COD 1533825 合成", False, "ncm"),
        ("negative/lco", "lco_d200nm_syn.txt", "LiCoO2", 200.0, 0.0,
         "内置 CIF COD 1533825 合成", False, "ncm"),
        ("negative/rocksalt", "nio_d80nm_syn.txt", None, 80.0, 0.0,
         "岩盐 NiO (Fm-3m, a=4.177) 合成", False, "other"),
        ("negative/precursor", "nico3_d150nm_syn.txt", "precursor_NiCO3",
         150.0, 0.0, "内置 CIF COD 1548823 合成（R-3c 碳酸盐）",
         False, "precursor_carbonate"),
        ("negative/precursor", "nih2_d150nm_syn.txt", "precursor_NiOH2",
         150.0, 0.0, "内置 CIF COD 1548811 合成（P-3m1 氢氧化物）",
         False, "precursor_hydroxide"),
    ]
    for (folder, name, struct_name, d_nm, eps, note,
         exp_ok, exp_kind) in synth_specs:
        struct = NIO_STRUCT if struct_name is None else builtin_structure(struct_name)
        dst = LIB / folder / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(_synth_text(struct, d_nm, eps), encoding="utf-8")
        manifest.append({
            "file": str((LIB / folder / name).relative_to(LIB)).replace("\\", "/"),
            "category": folder.split("/")[1],
            "origin": "synthetic",
            "source": note,
            "note": note,
            "expect_ok": exp_ok,
            "expect_kind": exp_kind,
        })

    path = LIB / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return manifest


def main() -> int:
    manifest = build()
    print(f"样本库已构建：{len(manifest)} 个样本 -> {LIB}")
    cats: dict[str, int] = {}
    for m in manifest:
        cats[m["category"]] = cats.get(m["category"], 0) + 1
    for k in sorted(cats):
        print(f"  {k:<12} {cats[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

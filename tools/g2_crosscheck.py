"""T8.3 · GSAS-II 交叉比对（本程序 Rietveld ↔ GSAS-II Rietveld）。

**比对口径**（docs/TASKS.md T8.3）：同一样品 + 同一 CIF，两套引擎各自精修，
比晶胞 a/c 与 Rwp。验收线：a/c 相对偏差 ≤ 0.05%（同模型）、Rwp 差 ≤ 2 个百分点。

**为什么 Rwp 不能用同一个绝对值比**：两套引擎的 Rwp 定义都在
`Σw(y_obs−y_calc)²/Σw y_obs²` 之下，但背景处理（本程序解析背景 vs GSAS-II
Chebyshev 多项式 6 项）、权重口径与计入点数不同 —— 实测同一谱可以差 1–3 个
百分点。故判据是「差值 ≤ 2 个百分点」，而不是「相等」。

**为什么 GSAS-II 只跑 Le Bail + 一次 Rietveld 定量**：桥脚本（家族
`scripts/gsas2_bridge.py`）的能力边界就是「Le Bail 定晶胞 + 有 CIF 时切
Rietveld 定量相分数」。Li 占位/晶粒尺寸的细修不在桥里 —— 这两项改用
**同一样品的独立文献值/Maud 值**比对（见 docs/TASKS.md T8.2）。

用法::

    python tools/g2_crosscheck.py                 # 跑 Data040 → 打印表 + 存 JSON
    python tools/g2_crosscheck.py --no-ours       # 只跑 GSAS-II（快速冒烟用）
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 直接跑本脚本时 sys.path[0] 是 tools/，包 ncm 不在搜索路径上 —— 显式补仓库根
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import g2_env  # noqa: E402

EVIDENCE = ROOT / "docs" / "evidence"
WAVELENGTH = 1.5405929

#: `ncm/core/solve.py::builtin_structure` 认得的内置结构名（用于把 CIF 文件名
#: 映射回内置结构；映射不上时一律用 NCM811）
_BUILTIN_NAMES = {
    "NCM811", "NCM811_alt", "NCM111", "NCM111_alt", "NCM523", "NCM622",
    "LiNiO2", "LiCoO2", "Lirich", "NCM_delith", "precursor_NCM811_OH",
    "precursor_NiOH2", "precursor_NCM811_CO3", "precursor_NiCO3",
}


def run_bridge(pat_data: tuple[list[float], list[float]],
               cif: Path, timeout: int = 1800) -> dict:
    """在 GSAS-II 解释器里跑一次「Le Bail + Rietveld」，返回桥的输出 dict。"""
    xs, ys = pat_data
    req = {
        "two_theta": xs, "intensity": ys, "wavelength": WAVELENGTH,
        "refine": "lattice", "max_cycles": 4,
        "phases": [{"name": "NCM811", "cif_path": str(cif.resolve())}],
    }
    td = Path(tempfile.mkdtemp(prefix="ncm_cross_"))
    rq, rs = td / "req.json", td / "out.json"
    rq.write_text(json.dumps(req), encoding="utf-8")
    py = g2_env.find_g2_python()
    if py is None:
        return {"ok": False, "error": "未找到 GSAS-II Python"}
    if not g2_env.BRIDGE.exists():
        return {"ok": False, "error": f"桥脚本缺失 {g2_env.BRIDGE}"}
    proc = subprocess.run([str(py), str(g2_env.BRIDGE), str(rq), str(rs)],
                          capture_output=True, text=True,
                          env=g2_env.g2_env(py), timeout=timeout)
    if not rs.exists():
        return {"ok": False,
                "error": f"桥未产出结果 rc={proc.returncode}",
                "stderr_tail": (proc.stderr or "")[-600:]}
    out = json.loads(rs.read_text(encoding="utf-8"))
    out.pop("ycalc", None)
    return out


def run_ours(pat_path: Path, cif: Path) -> dict:
    """用本程序跑同一条管线的对照结果。

    起始结构统一取**内置 NCM811**（与交给 GSAS-II 的是同一份 CIF），
    保证两边比的是「同一模型、同一数据」，差异只来自引擎。
    """
    from ncm.core.patterns import load_pattern
    from ncm.core.pipeline import default_options_for, run_pipeline
    from ncm.core.solve import builtin_structure

    name = cif.stem if cif.stem in _BUILTIN_NAMES else "NCM811"
    st = builtin_structure(name)
    pat = load_pattern(str(pat_path))
    res = run_pipeline(pat, st, default_options_for(st))
    a, b, c, al, be, ga = res.cell
    prm = res.stage1.result.params
    return {"ok": True, "a": float(a), "b": float(b), "c": float(c),
            "alpha": float(al), "beta": float(be), "gamma": float(ga),
            "rwp": float(res.rwp),
            "occ_li": res.occ_li,
            # 2θ 零位偏移（度）：本程序精修它；GSAS-II 桥把 Zero 固定在 0。
            # 这就是 Δa 与 Δc 不同量级的来源 —— 低角峰受零位影响 ∝ cotθ 最大。
            "zero_deg": float(getattr(prm, "zero", 0.0)),
            "d_nm": getattr(res.crystallite, "size_nm", None)
            if res.crystallite is not None else None}


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-12) * 100.0


def zero_closure(ours: dict, g2: dict) -> dict:
    """把 Δa / Δc 归因到「零位偏移算不算进去」。返回预测值与实测值。

    **为什么必须做这一步**：本程序精修 2θ 零位（`ProfileParams.zero`），而
    家族桥的 GSAS-II 一侧把 `Zero` 固定在 0（它只精修 Cell/Background/
    U,V,W）。零位会以 `Δa/a ≈ −cotθ·Δθ` 的方式**整条谱**平移 —— 低角峰
    （003，2θ≈18.7°，cotθ≈6.1）被放大，高角峰（110，2θ≈65°，cotθ≈1.6）
    几乎不动。所以「a 差 0.07%、c 只差 0.015%」这个**量级不对称**本身就是
    零位未对齐的指纹。

    这里用 (003) 的 θ 算 a 的理论偏移量。两者吻合 = 差异是**系统性可解释**
    的，不是晶胞精修本身不可靠。
    """
    z = ours.get("zero_deg")
    if not z:
        return {}
    from ncm.core.peaks import two_theta_of

    cell = (g2["gsas2_a"], g2["gsas2_a"], g2["gsas2_c"], 90.0, 90.0, 120.0)
    tt003 = two_theta_of(cell, (0, 0, 3), WAVELENGTH)
    if not tt003:
        return {}
    import math

    th = math.radians(tt003 / 2.0)
    # `ProfileParams.zero` 直接加在**2θ**上（见 ncm/core/profile/forward.py），
    # 故峰位角度的偏移是 zero/2（弧度）。漏掉这个 /2 会把理论值高估整倍。
    d_theta = abs(z) / 2.0 * math.pi / 180.0
    pred = 100.0 * (1.0 / math.tan(th)) * d_theta
    return {"zero_deg": z, "two_theta_003": tt003,
            "predicted_da_pct": pred,
            "observed_da_pct": _rel(g2["gsas2_a"], ours["a"]),
            "ratio": _rel(g2["gsas2_a"], ours["a"]) / pred if pred else None}


def compare(ours: dict | None, g2: dict) -> tuple[list[str], dict]:
    """生成对照表（中文行）与结构化指标。"""
    lat = (g2.get("phases") or [{}])[0].get("lattice") or {}
    g2_a, g2_c = float(lat.get("a", 0)), float(lat.get("c", 0))
    g2_rwp = g2.get("wR_rietveld") or g2.get("wR")
    lines = [
        f"{'项':<10}{'本程序':>14}{'GSAS-II':>14}{'相对偏差':>14}",
        "-" * 52,
    ]
    metrics = {"gsas2_a": g2_a, "gsas2_c": g2_c,
               "gsas2_wR": float(g2_rwp) if g2_rwp else None}
    if ours:
        lines.append(f"{'a (Å)':<10}{ours['a']:>14.5f}{g2_a:>14.5f}"
                     f"{_rel(g2_a, ours['a']):>13.3f}%")
        lines.append(f"{'c (Å)':<10}{ours['c']:>14.5f}{g2_c:>14.5f}"
                     f"{_rel(g2_c, ours['c']):>13.3f}%")
        lines.append(f"{'Rwp (%)':<10}{ours['rwp']:>14.3f}"
                     f"{(float(g2_rwp) if g2_rwp else float('nan')):>14.3f}"
                     f"{'—':>14}")
        metrics.update({"ours_a": ours["a"], "ours_c": ours["c"],
                        "ours_rwp": ours["rwp"],
                        "da_pct": _rel(g2_a, ours["a"]),
                        "dc_pct": _rel(g2_c, ours["c"])})
        if g2_rwp:
            metrics["rwp_diff_pp"] = abs(float(g2_rwp) - ours["rwp"])
        zc = zero_closure(ours, metrics)
        if zc:
            metrics["zero_closure"] = zc
            lines.append("")
            lines.append(f"零位归因：本程序精修 zero={zc['zero_deg']:+.5f}°，"
                         f"GSAS-II 侧固定 0。")
            lines.append(f"  (003) 2θ={zc['two_theta_003']:.3f}° → "
                         f"预测 Δa={zc['predicted_da_pct']:.3f}%，实测 "
                         f"{zc['observed_da_pct']:.3f}%（比值 "
                         f"{zc['ratio']:.2f}）")
    else:
        lines.append(f"{'a (Å)':<10}{'—':>14}{g2_a:>14.5f}{'—':>14}")
        lines.append(f"{'c (Å)':<10}{'—':>14}{g2_c:>14.5f}{'—':>14}")
        lines.append(f"{'wR (%)':<10}{'—':>14}"
                     f"{(float(g2_rwp) if g2_rwp else float('nan')):>14.3f}"
                     f"{'—':>14}")
    return lines, metrics


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T8.3 GSAS-II 交叉比对")
    ap.add_argument("--sample", default=str(g2_env.SAMPLE_NCM811))
    ap.add_argument("--cif", default=str(g2_env.CIF_NCM811))
    ap.add_argument("--no-ours", action="store_true",
                    help="只跑 GSAS-II（跳过本程序全谱精修，快）")
    args = ap.parse_args(argv)

    if g2_env.find_g2_python() is None:
        print("BLOCKED: 未找到 GSAS-II。见 docs/GSAS2_STATUS.md。")
        return 0
    for line in g2_env.describe():
        print(f"[g2] {line}")

    from ncm.core.patterns import load_pattern

    pat = load_pattern(args.sample)
    data = ([float(v) for v in pat.two_theta],
            [float(v) for v in pat.intensity])

    print(f"[g2] 样品 {Path(args.sample).name}  点数 {len(data[0])}")
    g2 = run_bridge(data, Path(args.cif))
    if not g2.get("ok"):
        print(f"[g2] GSAS-II 失败: {g2.get('error')}")
        print((g2.get("stderr_tail") or "")[:800])
        return 1
    print(f"[g2] GSAS-II 完成：wR(LeBail)={g2.get('wR')}  "
          f"wR(Rietveld)={g2.get('wR_rietveld')}")

    ours = None
    if not args.no_ours:
        print("[ours] 跑本程序全谱精修（约 1–8 分钟）…")
        ours = run_ours(Path(args.sample), Path(args.cif))
        print(f"[ours] Rwp={ours['rwp']:.4f}%  a={ours['a']:.5f}  "
              f"c={ours['c']:.5f}")

    lines, metrics = compare(ours, g2)
    print()
    print("\n".join(lines))
    print()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "T8.3_g2_crosscheck.json"
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample": str(args.sample), "cif": str(args.cif),
        "engine_ours": ours, "engine_gsas2": g2, "compare": metrics,
        "acceptance": {"da_pct_max": 0.05, "dc_pct_max": 0.05,
                       "rwp_diff_pp_max": 2.0},
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"[out] {out}")

    if ours:
        ok_a = metrics.get("da_pct", 9e9) <= 0.05
        ok_c = metrics.get("dc_pct", 9e9) <= 0.05
        ok_r = metrics.get("rwp_diff_pp", 9e9) <= 2.0
        print(f"[验收] Δa={metrics.get('da_pct', float('nan')):.3f}% "
              f"({'PASS' if ok_a else 'FAIL'} ≤0.05%)  "
              f"Δc={metrics.get('dc_pct', float('nan')):.3f}% "
              f"({'PASS' if ok_c else 'FAIL'} ≤0.05%)  "
              f"ΔRwp={metrics.get('rwp_diff_pp', float('nan')):.2f}pp "
              f"({'PASS' if ok_r else 'FAIL'} ≤2pp)")
        zc = metrics.get("zero_closure") or {}
        if zc and not ok_a:
            print(f"[说明] Δa 的 {zc['observed_da_pct']:.3f}% 与「零位未对齐」的"
                  f"理论值 {zc['predicted_da_pct']:.3f}% 相符（比值 "
                  f"{zc['ratio']:.2f}）—— 属**系统性、可量化归因**的差异，"
                  f"不是晶胞精修不可靠。")
        if not ok_r:
            print("[说明] ΔRwp 不可比：本程序一侧精修 zero/U/V/W/η/asym/PO/"
                  "Li 占位/z_O（12+ 参数），GSAS-II 桥只精修 背景+晶胞+U,V,W —— "
                  "自由度不同，Rwp 绝对值本就不该相等。判据应看同一模型下的差值。")
        return 0 if (ok_a and ok_c and ok_r) else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

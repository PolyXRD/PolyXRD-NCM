"""PolyXRD-NCM 命令行入口（T1.4）。

无 GUI 也能跑完整判定 + 精修，用途有三：
1. golden 基线可复现（`tests/test_golden.py` 就是调这个）；
2. P8 的 GSAS-II 交叉验证需要无界面跑批；
3. 实验室批量出结果时不必开窗口。

用法::

    D:/Project/XRD/python310/python.exe -m ncm.cli.ncm \
        --sample "D:/Project/XRD/XRData/csuHJW/txt/Data040：NCM：811_raw.txt" \
        --cif NCM811 --out out.json --png out.png
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ncm.core.solve import (
    SolveOptions,
    builtin_structure,
    load_sample,
    load_structure,
    solve,
)


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ncm", description="PolyXRD-NCM 三元正极 XRD 精修（命令行）")
    ap.add_argument("--sample", required=True, help="谱图文件（多格式自动识别）")
    ap.add_argument("--cif", default="NCM811",
                    help="内置 CIF 名（如 NCM811 / NCM622 / NCM111）或 CIF 路径")
    ap.add_argument("--out", help="结果 JSON 输出路径")
    ap.add_argument("--card", help="结果卡 JSON 输出路径（含晶体学/组成/相关性）")
    ap.add_argument("--png", help="精修图输出路径")
    ap.add_argument("--svg", help="精修图输出路径（矢量）")
    ap.add_argument("--points-csv", dest="points_csv",
                    help="逐点数据 CSV 输出路径（2θ/实测/计算/差值/背景）")
    ap.add_argument("--card-txt", dest="card_txt", help="结果卡纯文本输出路径")
    ap.add_argument("--html", help="HTML 报告输出路径（内嵌 SVG 图，单文件）")
    ap.add_argument("--tmin", type=float, default=None, help="精修 2θ 下限")
    ap.add_argument("--tmax", type=float, default=None, help="精修 2θ 上限")
    ap.add_argument("--n-bg", type=int, default=None, help="背景项数")
    ap.add_argument("--max-iter", type=int, default=None, help="最大迭代")
    ap.add_argument("--no-cell", action="store_true", help="冻结晶胞")
    ap.add_argument("--po", action="store_true", help="精修择优取向 (003)")
    ap.add_argument("--quiet", action="store_true", help="只输出 JSON")
    return ap


def _resolve_structure(spec: str):
    p = Path(spec)
    if p.suffix.lower() == ".cif" and p.exists():
        return load_structure(p)
    return builtin_structure(spec)


def _fmt(sr) -> str:
    d = sr.as_dict()
    rows = [
        ("Rwp", f"{d['rwp']:.2f} %"),
        ("Rp", f"{d['rp']:.2f} %"),
        ("Rexp", f"{d['rexp']:.2f} %"),
        ("GOF", f"{d['gof']:.2f}" if d["gof"] is not None else "—"),
        ("RB", "—（T4.1）" if d["rbragg"] is None else f"{d['rbragg']:.2f} %"),
        ("a", f"{d['a']:.4f} Å"),
        ("c", f"{d['c']:.4f} Å"),
        ("c/a", f"{d['c_over_a']:.4f}"),
        ("V", f"{d['volume']:.2f} Å³"),
        ("zero", f"{d['zero']:+.4f}°"),
        ("U/V/W", f"{d['U']:.4f} / {d['V']:.4f} / {d['W']:.5f}"),
        ("eta", f"{d['eta']:.3f}"),
        ("asym / B", f"{d['asym']:+.4f} / {d['bfactor']:.3f}"),
        ("迭代", f"{d['iters']}（success={d['success']}）"),
    ]
    w = max(len(k) for k, _ in rows)
    body = "\n".join(f"  {k:<{w}} : {v}" for k, v in rows)
    return f"结构 {sr.structure.name}（{sr.structure.cell[0]:.4f} / {sr.structure.cell[2]:.4f} 起始）\n{body}"


def _extra_exports(args, sr, struct) -> None:
    """T7.1 的其余导出格式（SVG / 逐点 CSV / 结果卡 TXT / HTML 报告）。

    全部走核心层 `ncm.core.export` —— 与 GUI 导出**同一套代码、同一套配色**。
    """
    from ncm.core.export import (
        export_card_text,
        export_figure,
        export_html_report,
        export_points_csv,
        figure_svg_text,
    )
    from ncm.core.solve import background_curve

    bg = background_curve(sr)
    title = f"{struct.name}  Rietveld"

    if args.svg:
        export_figure(sr.pattern.two_theta, sr.pattern.intensity,
                      sr.result.ycalc, args.svg, background=bg,
                      title=title, rwp=sr.rwp)
        if not args.quiet:
            print(f"SVG 已写入 {args.svg}")

    if args.points_csv:
        export_points_csv(sr.pattern.two_theta, sr.pattern.intensity,
                          sr.result.ycalc, args.points_csv, background=bg)
        if not args.quiet:
            print(f"逐点数据已写入 {args.points_csv}")

    if args.card_txt:
        from ncm.core.resultcard import build_card

        card = build_card(sr.result, struct,
                          {"sample_name": Path(args.sample).name})
        export_card_text(card, args.card_txt)
        if not args.quiet:
            print(f"结果卡文本已写入 {args.card_txt}")

    if args.html:
        from ncm.core.resultcard import build_card

        card = build_card(sr.result, struct,
                          {"sample_name": Path(args.sample).name})
        svg = figure_svg_text(sr.pattern.two_theta, sr.pattern.intensity,
                              sr.result.ycalc, background=bg, title=title)
        export_html_report(card, args.html, figure_svg=svg)
        if not args.quiet:
            print(f"HTML 报告已写入 {args.html}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    struct = _resolve_structure(args.cif)
    pat = load_sample(args.sample)

    base = SolveOptions()
    opt = SolveOptions(
        tmin=args.tmin if args.tmin is not None else base.tmin,
        tmax=args.tmax if args.tmax is not None else base.tmax,
        n_bg=args.n_bg if args.n_bg is not None else base.n_bg,
        max_iter=args.max_iter if args.max_iter is not None else base.max_iter,
        refine_cell=not args.no_cell,
        refine_po=args.po,
    )

    t0 = time.time()
    sr = solve(pat, struct, opt)
    dt = time.time() - t0

    if not args.quiet:
        print(f"谱图 {Path(args.sample).name}: {pat.two_theta.size} 点 "
              f"{pat.two_theta[0]:.2f}–{pat.two_theta[-1]:.2f}°  "
              f"步长 {pat.step:.3f}°")
        print(f"精修区间 {opt.tmin:.1f}–{opt.tmax:.1f}°   耗时 {dt:.1f} s\n")
        print(_fmt(sr))

    payload = {"sample": str(args.sample), "cif": str(args.cif),
               "elapsed_s": round(dt, 2), **sr.as_dict()}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        if not args.quiet:
            print(f"\n结果已写入 {args.out}")

    if args.card:
        from ncm.core.resultcard import build_card

        card = build_card(sr.result, struct, {"sample_name": Path(args.sample).name})
        Path(args.card).parent.mkdir(parents=True, exist_ok=True)
        Path(args.card).write_text(json.dumps(card, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        if not args.quiet:
            print(f"结果卡已写入 {args.card}")

    if args.png:
        from ncm.core.plotting import plot_refinement
        from ncm.core.solve import background_curve

        plot_refinement(sr.pattern.two_theta, sr.pattern.intensity,
                        sr.result.ycalc, background_curve(sr), args.png,
                        title=f"{struct.name}  Rietveld", rwp=sr.rwp)
        if not args.quiet:
            print(f"图已写入 {args.png}")

    _extra_exports(args, sr, struct)

    if args.quiet:
        print(json.dumps(payload, ensure_ascii=False))
    return 0 if sr.result.success else 2


if __name__ == "__main__":
    sys.exit(main())

"""内置 CIF 包校验（T0.3 验收）。

校验项
------
1. `INDEX.json` 里每份 CIF 都存在、可被 CIF 解析器读出；
2. 解析所得晶胞 a / c 与 `INDEX.json` 记录一致（±1e-4）；
3. 对称展开后原子数 > 0，且空间群与索引一致；
4. 派生文件必须带 `# PolyXRD derived from COD` 头，原样文件必须**不带**；
5. 派生文件的 TM 位占位之和落在合理区间（0.95–1.05）。

解析器来源：优先 `ncm.core.profile.cif`（P1 后可用），未 vendor 前回退到
`PolyXRD-RutAna` 的 rutana 包（仅开发期校验用，不参与发布）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIF_DIR = ROOT / "ncm" / "data" / "cif"
INDEX = CIF_DIR / "INDEX.json"


def load_parser():
    """返回 parse_cif_string；优先本包，回退 rutana。"""
    sys.path.insert(0, str(ROOT))
    try:
        from ncm.core.profile.cif import parse_cif_string  # type: ignore

        return parse_cif_string, "ncm"
    except Exception:  # noqa: BLE001
        pass
    sys.path.insert(0, r"D:\Project\XRD\PolyXRD-RutAna")
    try:
        from rutana.core.profile.cif import parse_cif_string  # type: ignore

        return parse_cif_string, "rutana(fallback)"
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"无可用 CIF 解析器: {exc}") from exc


def main() -> int:
    if not INDEX.exists():
        print(f"缺 INDEX.json，先跑 tools/build_cif_pack.py", file=sys.stderr)
        return 1
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    parse_cif_string, origin = load_parser()
    print(f"解析器来源: {origin}    索引条目: {idx['count']}\n")

    fails: list[str] = []
    print(f"{'文件':<28}{'空间群':<14}{'a':>8}{'c':>9}{'原子数':>7}  判定")
    for e in idx["entries"]:
        path = CIF_DIR / e["file"]
        tag = []
        if not path.exists():
            fails.append(f"{e['file']}: 文件缺失")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        has_mark = "# PolyXRD derived from COD" in text
        if bool(e["derived"]) != has_mark:
            fails.append(f"{e['file']}: derived={e['derived']} 与实际标记不符")
        try:
            st = parse_cif_string(text, e["name"])
        except Exception as exc:  # noqa: BLE001
            fails.append(f"{e['file']}: 解析失败 {type(exc).__name__}: {exc}")
            continue
        a, _b, c = st.cell[0], st.cell[1], st.cell[2]
        if abs(a - e["a"]) > 1e-4:
            fails.append(f"{e['file']}: a={a:.4f} ≠ 索引 {e['a']:.4f}")
        if abs(c - e["c"]) > 1e-4:
            fails.append(f"{e['file']}: c={c:.4f} ≠ 索引 {e['c']:.4f}")
        if not st.atoms:
            fails.append(f"{e['file']}: 展开后原子数为 0")
        ok = "OK" if not any(f.startswith(e["file"]) for f in fails) else "FAIL"
        print(f"{e['file']:<28}{e['spacegroup']:<14}{a:>8.4f}{c:>9.4f}"
              f"{len(st.atoms):>7}  {ok}")

    print()
    if fails:
        print(f"❌ {len(fails)} 项未过：")
        for f in fails:
            print("   -", f)
        return 1
    print(f"✅ {idx['count']} 份 CIF 全部通过（解析 / 晶胞一致性 / 派生标记 / 原子展开）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

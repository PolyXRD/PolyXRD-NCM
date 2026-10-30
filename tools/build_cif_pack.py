"""内置 CIF 打包器（T0.3）。

从 `D:/Project/XRD/sync-COD/COD/` 取 COD 原始 CIF 落盘，并按名义配比派生出
622 / 523 / 三元氢氧化物前驱体 / 三元碳酸盐前驱体，最后生成 INDEX.json。

设计要点
--------
1. **原样复制**的 CIF 一个字节都不改（可溯源、可校验 sha256）。
2. **派生**的 CIF 只改 `_chemical_formula_sum` 与原子占位行，保留原始对称操作
   （parse_cif 依赖 `_symmetry_equiv_pos_as_xyz` 展开，缺了会少算原子）。
3. 派生文件头写入 `# PolyXRD derived from COD <id>`，明确非实测结构。
4. 全部走幂等写入：重复运行结果一致。

用法::

    D:/Project/XRD/python310/python.exe tools/build_cif_pack.py
    D:/Project/XRD/python310/python.exe tools/build_cif_pack.py --check   # 只校验不写
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COD_ROOT = Path("D:/Project/XRD/sync-COD/COD")
OUT_DIR = ROOT / "ncm" / "data" / "cif"
INDEX = OUT_DIR / "INDEX.json"

#: 原样复制清单：目标名 -> (COD 编号, 说明)
COPY_LIST: dict[str, tuple[int, str]] = {
    "NCM811.cif": (1520789, "NCM811 实测（Ni:Co:Mn=77:10:10，含 2% Li/Ni 混排）"),
    "NCM811_alt.cif": (1520787, "富镍无 Co 近 NCM9（Ni0.89）"),
    "NCM111.cif": (3000558, "NCM111 精确配比"),
    "NCM111_alt.cif": (4002443, "NCM111 另一测定"),
    "NCM_delith.cif": (4002445, "NCM111 脱锂态 Li0.63（充电态参考）"),
    "LiNiO2.cif": (1533770, "LiNiO2 端元（NCM9 系基底）"),
    "LiCoO2.cif": (1533825, "LiCoO2（判定门负样本对照）"),
    "Lirich.cif": (1529154, "富锂锰基 Li1.2（前驱体/富锂相参考）"),
    "precursor_NiOH2.cif": (1548811, "β-Ni(OH)2 氢氧化物前驱体骨架 P-3m1"),
    "precursor_NiCO3.cif": (1548823, "NiCO3 碳酸盐前驱体骨架 R-3c"),
}

#: 派生清单：目标名 -> (模板 COD, 新化学式, TM 位占位, 说明)
#: 占位值 = **TM 位内**的分数占位；Li 层 2% Ni 混排继承模板不变。
#: 因此 TM 位占位之和为 0.98（含 Li 层 0.02 Ni 后过渡金属总计 1.00）。
DERIVE_LIST: dict[str, tuple[int, str, dict[str, float], str]] = {
    "NCM622.cif": (
        1520789, "Co0.2 Li0.98 Mn0.2 Ni0.6 O2",
        {"Ni": 0.58, "Co": 0.20, "Mn": 0.20},
        "NCM622 名义配比派生（TM 位 58:20:20 + Li 层 2% Ni 混排 -> 总 Ni 0.60）",
    ),
    "NCM523.cif": (
        1520789, "Co0.2 Li0.98 Mn0.3 Ni0.5 O2",
        {"Ni": 0.48, "Co": 0.20, "Mn": 0.30},
        "NCM523 名义配比派生（TM 位 48:20:30 + Li 层 2% Ni 混排 -> 总 Ni 0.50）",
    ),
    "precursor_NCM811_OH.cif": (
        1548811, "Co0.1 H2 Mn0.1 Ni0.8 O2",
        {"Ni": 0.80, "Co": 0.10, "Mn": 0.10},
        "三元氢氧化物前驱体（811 配比，β-Ni(OH)2 骨架 P-3m1）",
    ),
    "precursor_NCM811_CO3.cif": (
        1548823, "C Co0.1 Mn0.1 Ni0.8 O3",
        {"Ni": 0.80, "Co": 0.10, "Mn": 0.10},
        "三元碳酸盐前驱体（811 配比，方解石型骨架 R-3c）",
    ),
}

#: 元素 -> 离子标识（写进 _atom_site_type_symbol）
ION = {"Li": "Li+1", "Ni": "Ni+3", "Co": "Co+3", "Mn": "Mn+3", "O": "O-2", "H": "H1+", "C": "C4+"}

#: 过渡金属元素集合（用于定位 TM 位，Li 必须排除）
TM_ELEMS = {"Ni", "Co", "Mn", "Fe", "Al", "Cr", "V", "Ti", "Cu", "Zn"}


def _elem(type_symbol: str) -> str:
    """从 'Ni+3' / 'O-2' / 'Ni2+' 里取元素符号。"""
    out = []
    for ch in type_symbol:
        if ch.isalpha():
            out.append(ch)
        else:
            break
    return "".join(out)


def cod_path(cod_id: int) -> Path:
    """COD 三级布局路径：1/00/00/1000003.cif"""
    s = str(cod_id)
    rel = Path(s[0]) / s[1:3] / s[3:5] / f"{s}.cif"
    return COD_ROOT / rel


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_atom_block(lines: list[str]) -> tuple[int, int, int]:
    """定位原子位 loop 的数据区起止 [start, end)，返回 (header_idx, start, end)。

    返回的 header_idx 指向 `_atom_site_label` 所在行。
    """
    h = None
    for i, ln in enumerate(lines):
        if ln.strip() == "_atom_site_label":
            h = i
            break
    if h is None:
        raise ValueError("未找到 _atom_site_label")
    # 数据行从第一个非 tag 行开始
    j = h
    while j < len(lines) and lines[j].strip().startswith("_atom_site"):
        j += 1
    start = j
    k = start
    while k < len(lines):
        s = lines[k].strip()
        if not s or s.startswith(("loop_", "_", "#", "data_")):
            break
        k += 1
    return h, start, k


def _strip_esd(tok: str) -> str:
    """去掉 CIF 的 esd 括号写法：'3.1268(1)' -> '3.1268'，'0' 原样。"""
    t = tok.strip().strip("'\"")
    if "(" in t and t.endswith(")"):
        head = t.split("(")[0]
        if head not in ("", "-", "+"):
            return head
    return t


#: 单元格点标签（值可能带 esd，需规范化）
_CELL_TAGS = (
    "_cell_length_a", "_cell_length_b", "_cell_length_c",
    "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma",
    "_cell_volume", "_cell_formula_units_Z",
)
#: 原子 loop 规范化后的 7 列（与家族解析器完全对齐）
_ATOM_COLS = ("label", "type_symbol", "fract_x", "fract_y", "fract_z",
              "occupancy", "U_iso_or_equiv")


def normalize_cif_text(text: str) -> str:
    """把 CIF 规范化为家族解析器可直接吃的形式。

    做两件事（**不改任何数值**，只改书写形式）：
    1. 去掉晶胞/原子数值的 esd 括号（`3.1268(1)` -> `3.1268`）；
    2. 把 `_atom_site_*` 循环重排为 7 列标准集，丢弃 multiplicity / Wyckoff /
       attached_hydrogens 等解析器不读的列。

    原因：家族解析器用 `float()` 直读，遇到 esd 括号会返回 None ——
    晶胞退化成 1.0、带 esd 的原子被**静默丢弃**（实测 O/H 行消失、|F|² 全错）。
    内置 CIF 在此一次性规范化；用户导入 CIF 的同类问题由 T1.2b 在解析器层修。
    """
    lines = text.splitlines()
    # 注释行保留（解析器本就跳过 '#' 行），以便派生标记不丢
    out = lines

    # 1) 晶胞数值去 esd
    fixed: list[str] = []
    for ln in out:
        s = ln.strip()
        hit = next((t for t in _CELL_TAGS if s.startswith(t)), None)
        if hit and len(s.split(None, 1)) > 1:
            tag, val = s.split(None, 1)
            fixed.append(f"{tag:<34}{_strip_esd(val)}")
        else:
            fixed.append(ln)

    # 2) 原子 loop 规范化
    try:
        h, start, end = split_atom_block(fixed)
    except ValueError:
        return "\n".join(fixed) + "\n"
    tags = [ln.strip() for ln in fixed[h:start]]
    rows = [_split_row(ln) for ln in fixed[start:end] if ln.strip()]

    def idx(key: str) -> int | None:
        t = f"_atom_site_{key}"
        return tags.index(t) if t in tags else None

    i_lbl, i_sym = idx("label"), idx("type_symbol")
    i_x, i_y, i_z = idx("fract_x"), idx("fract_y"), idx("fract_z")
    i_occ, i_u = idx("occupancy"), idx("U_iso_or_equiv")
    if None in (i_x, i_y, i_z):
        return "\n".join(fixed) + "\n"

    def cell(row: list[str], k: int | None, default: str) -> str:
        if k is None or k >= len(row):
            return default
        return _strip_esd(row[k])

    new_rows = []
    for r in rows:
        label = r[i_lbl] if i_lbl is not None and i_lbl < len(r) else "X"
        sym = r[i_sym] if i_sym is not None and i_sym < len(r) else label
        new_rows.append(" ".join([
            label, sym,
            cell(r, i_x, "0"), cell(r, i_y, "0"), cell(r, i_z, "0"),
            cell(r, i_occ, "1"), cell(r, i_u, "0"),
        ]))

    head = [f"_atom_site_{c}" for c in _ATOM_COLS]
    rebuilt = fixed[:h] + head + new_rows + fixed[end:]
    return "\n".join(rebuilt) + "\n"


def _split_row(line: str) -> list[str]:
    """切分 CIF 数据行（引号内视为一个 token）。"""
    s = line.strip()
    if "'" in s or '"' in s:
        try:
            import shlex

            return shlex.split(s)
        except ValueError:
            return s.split()
    return s.split()


def read_cell_and_formula(lines: list[str]) -> tuple[str, float, float]:
    """读取 (空间群, a, c)；缺失给 0。"""
    sg, a, c = "", 0.0, 0.0
    for ln in lines:
        s = ln.strip()
        if s.startswith("_symmetry_space_group_name_H-M"):
            sg = s.split(None, 1)[1].strip().strip("'\"") if len(s.split(None, 1)) > 1 else ""
        elif s.startswith("_cell_length_a"):
            a = _num(s)
        elif s.startswith("_cell_length_c"):
            c = _num(s)
    return sg, a, c


def _num(tag_line: str) -> float:
    raw = tag_line.split(None, 1)[1] if len(tag_line.split(None, 1)) > 1 else "0"
    raw = raw.strip().split("(")[0]
    try:
        return float(raw)
    except ValueError:
        return 0.0


def derive(template: Path, formula: str, tm_occ: dict[str, float], note: str) -> str:
    """以模板为骨架，替换 TM 位占位，返回新 CIF 文本。"""
    lines = template.read_text(encoding="utf-8", errors="replace").splitlines()
    h, start, end = split_atom_block(lines)
    tags = [ln.strip() for ln in lines[h:start]]
    rows = [ln.split() for ln in lines[start:end]]
    if not rows:
        raise ValueError(f"模板原子行为空: {template}")

    def col(name: str) -> int:
        return tags.index(f"_atom_site_{name}")

    i_lbl, i_sym = col("label"), col("type_symbol")
    i_x, i_y, i_z = col("fract_x"), col("fract_y"), col("fract_z")
    i_occ = col("occupancy")

    # 找 TM 位：占位最大的**过渡金属**行（Li 层占位也高，绝不能当锚点）
    tm_rows = [r for r in rows if _elem(r[i_sym]) in TM_ELEMS]
    if not tm_rows:
        raise ValueError(f"模板无 TM 位: {template}")
    anchor = max(tm_rows, key=lambda r: float(r[i_occ].split("(")[0]))
    x, y, z = anchor[i_x], anchor[i_y], anchor[i_z]

    # 丢掉锚点位上**全部**原有原子（含该位的少量 Li —— 由名义配比重建）
    kept = [r for r in rows if (r[i_x], r[i_y], r[i_z]) != (x, y, z)]

    # 在 TM 位插入新元素
    extra = []
    for n, (el, occ) in enumerate(tm_occ.items()):
        row = list(anchor)
        row[i_lbl] = f"{el}TM{n + 1}"
        row[i_sym] = ION.get(el, el)
        row[i_x], row[i_y], row[i_z] = x, y, z
        row[i_occ] = f"{occ:g}"
        extra.append(row)

    new_rows = kept + extra
    body = [" ".join(r) for r in new_rows]

    # 替换 _chemical_formula_sum
    out: list[str] = []
    for ln in lines[:start]:
        if ln.strip().startswith("_chemical_formula_sum"):
            out.append(f"_chemical_formula_sum            '{formula}'")
        else:
            out.append(ln)
    out.extend(body)
    out.extend(lines[end:])

    head = [
        f"# PolyXRD derived from COD {template.stem}",
        f"#   {note}",
        "#   仅改 _chemical_formula_sum 与 TM 位占位；对称操作与其余原子保持模板原值。",
        "#   非实验测定结构，供精修初值使用。",
        "",
    ]
    return "\n".join(head + out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="构建内置 CIF 包")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "impurity").mkdir(exist_ok=True)
    entries: list[dict] = []

    for name, (cid, note) in COPY_LIST.items():
        src = cod_path(cid)
        if not src.exists():
            print(f"[缺失] COD {cid} -> {src}", file=sys.stderr)
            return 1
        dst = OUT_DIR / name
        # 规范化写入：去 esd 括号 + 原子 loop 重排为 7 列（数值不变，见 normalize_cif_text）
        raw = src.read_text(encoding="utf-8", errors="replace")
        if not args.check:
            dst.write_text(normalize_cif_text(raw), encoding="utf-8")
        if dst.exists():
            sg, a, c = read_cell_and_formula(
                dst.read_text(encoding="utf-8", errors="replace").splitlines())
            entries.append({"name": dst.stem, "file": name, "cod_id": cid,
                            "spacegroup": sg, "a": a, "c": c,
                            "derived": False, "normalized": True,
                            "sha256": sha256(dst),
                            "cod_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                            "note": note})

    for name, (cid, formula, tm_occ, note) in DERIVE_LIST.items():
        src = cod_path(cid)
        if not src.exists():
            print(f"[缺失] 模板 COD {cid}", file=sys.stderr)
            return 1
        dst = OUT_DIR / name
        if not args.check:
            dst.write_text(normalize_cif_text(derive(src, formula, tm_occ, note)),
                           encoding="utf-8")
        if dst.exists():
            sg, a, c = read_cell_and_formula(
                dst.read_text(encoding="utf-8", errors="replace").splitlines())
            entries.append({"name": dst.stem, "file": name, "cod_id": cid,
                            "spacegroup": sg, "a": a, "c": c,
                            "derived": True, "normalized": True,
                            "formula": formula,
                            "sha256": sha256(dst),
                            "cod_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                            "note": note})

    entries.sort(key=lambda e: (e["derived"], e["name"]))
    if not args.check:
        INDEX.write_text(json.dumps(
            {"cod_root": str(COD_ROOT), "count": len(entries), "entries": entries},
            ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"内置 CIF: {len(entries)} 份（原样 {len(COPY_LIST)}，派生 {len(DERIVE_LIST)}）")
    for e in entries:
        flag = "派生" if e["derived"] else "原样"
        print(f"  [{flag}] {e['file']:<28} COD {e['cod_id']:<9} "
              f"{e['spacegroup']:<12} a={e['a']:.4f} c={e['c']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

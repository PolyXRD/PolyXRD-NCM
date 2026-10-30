"""结果卡数据结构（T4.3 · 新建，非 vendor）。

把一次精修的全部结论汇成**一张可溯源的结果卡**：晶胞、晶体学对称性、
组成（Li 占位 / z_O）、微结构（晶粒尺寸 / 应变）、峰形参数、拟合优度、
择优取向、参数相关性，并附上各项的**口径出处**（STD_FREEZE 章节号），
避免"数字没有解释"的报告。

数据流
------
    refine() -> RefineResult ──┐
    CIF 结构 ───────────────────┼─> build_card() -> dict（纯数据，可 JSON 化）
    第二段占位/TCH 结果 ─────────┘

`meta` 传入的上下文键（全部可选，缺省为 None/"未测定"）：
    cell          : 精修后晶胞 (a,b,c,α,β,γ)；缺省用 CIF 原始晶胞
    occ_li        : Li 占位（T3.1 第二段）
    z_o           : O 的 6c 坐标（T3.1 第二段）
    crystallite   : crystallite.CrystalliteResult（尺寸/应变）
    sample_name / operator / instrument / wavelength / measured_at / notes
"""
from __future__ import annotations

import math
from datetime import datetime

from ncm.core.profile.cif import CifStructure
from ncm.core.refine.nonlinear import RefineResult

#: 结果卡口径出处（随卡一起走，报告里可逐项追溯）
CRITERIA_SOURCES = {
    "cell": "STD_FREEZE §2（晶胞由全谱精修的 a/c 缩放给出）",
    "fit": "STD_FREEZE §2（Rwp/Rp/Rexp/χ² 百分数口径，背景计入；GOF=Rwp/Rexp）",
    "rbragg": "STD_FREEZE §2（Bragg R：扣背景 + 重叠峰按计算贡献分配）",
    "crystallite": "STD_FREEZE §3（TCH 伪 Voigt；Scherrer K=0.89；"
                   "晶粒尺寸=相干衍射畴尺寸，非二次颗粒粒径）",
    "occupancy": "STD_FREEZE §4（occ_Li+反位=1；z_O∈[0.20,0.28]）",
    "symmetry": "International Tables Vol.A（ncm/data/spacegroups.json）",
}


def _round(v, n=6):
    return None if v is None else round(float(v), n)


def _cell_info(cell, volume: float) -> dict:
    a, b, c, al, be, ga = cell
    return {
        "a": _round(a, 5), "b": _round(b, 5), "c": _round(c, 5),
        "alpha": _round(al, 4), "beta": _round(be, 4), "gamma": _round(ga, 4),
        "volume": _round(volume, 3),
        "c_over_a": _round(c / a, 5) if a else None,
    }


def _cell_volume(cell) -> float:
    a, b, c, al, be, ga = cell
    al, be, ga = (math.radians(v) for v in (al, be, ga))
    return a * b * c * math.sqrt(max(0.0,
        1 - math.cos(al) ** 2 - math.cos(be) ** 2 - math.cos(ga) ** 2
        + 2 * math.cos(al) * math.cos(be) * math.cos(ga)))


def build_card(refine_result: RefineResult, struct: CifStructure,
               meta: dict | None = None) -> dict:
    """构建结果卡（纯 dict，可直接 JSON 化 / 写报告）。

    refine_result : refine() 的返回值（峰形、优度、PO、相关性）
    struct        : 对应的 CIF 结构（空间群等元数据来源）
    meta          : 附加上下文（见模块 docstring）
    """
    meta = dict(meta or {})
    prm = refine_result.params
    rf = refine_result.rf

    # ---- 晶胞：优先用精修后的（meta.cell），否则由 cell_scales 推 ----
    cell = meta.get("cell")
    if cell is None:
        fa, fc = (refine_result.cell_scales[0] if refine_result.cell_scales
                  else (1.0, 1.0))
        a, b, c, al, be, ga = struct.cell
        cell = (a * fa, b * fa, c * fc, al, be, ga)
    cell = tuple(float(v) for v in cell)

    # ---- 晶体学对称性 ----
    sg_symbol = getattr(struct, "spacegroup", None)
    sg = None
    if sg_symbol:
        from ncm.core.symmetry import lookup
        try:
            sg = lookup(sg_symbol)
        except KeyError:
            sg = None
    structure_info = {
        "name": struct.name,
        "space_group": sg_symbol,
        "space_group_number": getattr(struct, "sg_number", None),
        "crystal_system": sg.crystal_system if sg else None,
        "crystal_system_zh": sg.crystal_system_zh if sg else None,
        "point_group": sg.point_group if sg else None,
        "laue_group": sg.laue_group if sg else None,
        "bravais_lattice": sg.bravais if sg else None,
    }

    # ---- 微结构（晶粒尺寸/应变） ----
    cryst = meta.get("crystallite")
    micro = {"crystallite_size_nm": None, "strain": None, "method": None}
    if cryst is not None:
        if isinstance(cryst, dict):
            micro.update({k: v for k, v in cryst.items() if k in micro})
        else:
            micro["crystallite_size_nm"] = _round(cryst.D_nm, 2)
            micro["strain"] = float(f"{cryst.strain:.3e}")
            micro["method"] = cryst.method
    if meta.get("occ_li") is not None or meta.get("z_o") is not None:
        micro.setdefault("method", micro["method"] or None)

    # ---- 组成（Li 占位 / z_O） ----
    composition = {
        "li_occupancy": _round(meta.get("occ_li"), 4),
        "o_z": _round(meta.get("z_o"), 5),
    }

    # ---- 峰形参数 ----
    profile = {
        "zero": _round(prm.zero, 5),
        "U": _round(prm.U, 6), "V": _round(prm.V, 6), "W": _round(prm.W, 6),
        "eta": _round(prm.eta, 4),
        "asym": _round(prm.asym, 5),
        "bfactor": _round(prm.bfactor, 4),
        "X": _round(getattr(prm, "X", 0.0), 6),
        "Y": _round(getattr(prm, "Y", 0.0), 6),
    }
    po = refine_result.po_r or {}
    profile["po_r"] = {name: (int(v[0]), int(v[1]), int(v[2]),
                              _round(v[3], 5)) for name, v in po.items()}

    # ---- 拟合优度 ----
    gof = (rf.rwp / rf.rexp) if rf.rexp else None
    fit = {
        "rwp": _round(rf.rwp, 4),
        "rp": _round(rf.rp, 4),
        "rexp": _round(rf.rexp, 4),
        "rbragg": _round(rf.rbragg, 4) if rf.rbragg is not None else None,
        "gof": _round(gof, 4),
        "chi2": _round(rf.chi2, 4),
        "success": bool(refine_result.success),
        "iterations": int(refine_result.iters),
    }

    # ---- 参数相关性 ----
    corr = getattr(refine_result, "correlation", None)
    correlations = None
    if corr is not None:
        correlations = {"labels": list(corr.labels),
                        "matrix": [[_round(v, 4) for v in row]
                                   for row in corr.matrix],
                        "high_pairs": [{"a": a, "b": b, "r": _round(r, 4)}
                                       for a, b, r in corr.high_pairs()]}

    header = {
        "sample": meta.get("sample_name"),
        "structure": struct.name,
        "measured_at": meta.get("measured_at")
        or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "operator": meta.get("operator"),
        "instrument": meta.get("instrument"),
        "wavelength": meta.get("wavelength"),
        "software": "PolyXRD-NCM",
        "notes": meta.get("notes"),
    }

    return {
        "header": header,
        "structure": structure_info,
        "cell": _cell_info(cell, _cell_volume(cell)),
        "composition": composition,
        "microstructure": micro,
        "profile": profile,
        "fit": fit,
        "correlations": correlations,
        "criteria_sources": CRITERIA_SOURCES,
    }


def render_text(card: dict) -> str:
    """结果卡的中文纯文本渲染（邮件摘要 / TXT 导出复用）。"""
    h = card["header"]
    s = card["structure"]
    c = card["cell"]
    f = card["fit"]
    p = card["profile"]
    m = card["microstructure"]
    cp = card["composition"]
    lines = [
        f"样品：{h.get('sample') or '—'}    结构：{h.get('structure') or '—'}",
        f"测试时间：{h.get('measured_at')}    操作：{h.get('operator') or '—'}",
        "",
        "【晶体学】",
        f"  空间群：{s.get('space_group') or '—'}"
        f"（{s.get('crystal_system_zh') or '—'}晶系，"
        f"点群 {s.get('point_group') or '—'}，"
        f"劳厄群 {s.get('laue_group') or '—'}，"
        f"布拉维格子 {s.get('bravais_lattice') or '—'}）",
        f"  晶胞：a={c['a']:.5f} b={c['b']:.5f} c={c['c']:.5f} Å，"
        f"α={c['alpha']:.3f} β={c['beta']:.3f} γ={c['gamma']:.3f}°",
        f"  体积：{c['volume']:.3f} Å³    c/a：{c['c_over_a']:.5f}",
        "",
        "【组成与微结构】",
        f"  Li 占位：{cp['li_occupancy'] if cp['li_occupancy'] is not None else '未测定'}"
        f"    O 的 z：{cp['o_z'] if cp['o_z'] is not None else '未测定'}",
        f"  晶粒尺寸（相干衍射畴）："
        f"{m['crystallite_size_nm'] if m['crystallite_size_nm'] is not None else '未测定'}"
        f"{' nm' if m['crystallite_size_nm'] is not None else ''}"
        f"    微观应变：{m['strain'] if m['strain'] is not None else '未检出'}",
        "",
        "【拟合优度】",
        f"  Rwp={f['rwp']:.4f}%   Rp={f['rp']:.4f}%   Rexp={f['rexp']:.4f}%"
        f"   RB={f['rbragg'] if f['rbragg'] is not None else '—'}%"
        f"   GOF={f['gof'] if f['gof'] is not None else '—'}",
        "",
        "【峰形参数】",
        f"  zero={p['zero']:.5f}°  U={p['U']:.6f}  V={p['V']:.6f}  "
        f"W={p['W']:.6f}  η={p['eta']:.4f}  B={p['bfactor']:.4f}",
    ]
    if p.get("po_r"):
        po_txt = "  择优取向：" + "，".join(
            f"{k}=({v[0]}{v[1]}{v[2]}) r={v[3]:.4f}" for k, v in p["po_r"].items())
        lines.append(po_txt)
    if card.get("correlations") and card["correlations"].get("high_pairs"):
        hp = card["correlations"]["high_pairs"]
        txt = "  高相关参数对：" + "，".join(
            f"{d['a']}↔{d['b']} (r={d['r']:+.3f})" for d in hp[:5])
        lines.append(txt)
    if h.get("notes"):
        lines += ["", f"备注：{h['notes']}"]
    return "\n".join(lines)

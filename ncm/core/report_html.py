"""HTML 精修报告（T7.1c · 新建，非 vendor）。

把结果卡渲染成一份**自包含**的 HTML 报告：内嵌 SVG 谱图 + 晶体学/组成/
微结构/优度/峰形/相关性表格 + 口径出处。

**为什么单独一个模块**
--------------------
HTML 渲染是**纯文本拼装**（约 170 行），与「画图」「写 CSV」是三种不同的
关注点，混在一个文件里会让 `export.py` 超 400 行（规则 2）。且报告模板
后续会随家族版次演进（logo、页眉、二维码），独立成文件更好维护。

**报告为什么必须是单文件**
------------------------
委托报告要能直接邮件转发。一堆附件（图一张、CSV 一份、JSON 一个）容易在
转发中丢件、错配版本。故图**内联**进 HTML，数据全在一个文件里。

**口径不出现在这里**
--------------------
所有数值都来自 `ncm.core.resultcard.build_card()` 的结果卡，本模块只做
**呈现**，不重新计算、不改口径 —— 避免"报告里的数"与"结果卡的数"分叉。
"""
from __future__ import annotations

from pathlib import Path

HTML_CSS = """
:root { --ink:#0F172A; --obs:#0284C7; --calc:#0F172A; --diff:#DC2626;
        --bg:#94A3B8; --grid:#CBD5E1; --muted:#64748B; }
body { font-family: "Source Han Sans CN", "Microsoft YaHei", "SimHei",
       "Noto Sans CJK SC", sans-serif; color: var(--ink);
       max-width: 1080px; margin: 0 auto; padding: 24px 20px 48px;
       line-height: 1.6; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; padding-bottom: 5px;
     border-bottom: 2px solid var(--grid); }
.sub { color: var(--muted); font-size: 12.5px; margin-bottom: 18px; }
table { border-collapse: collapse; width: 100%; font-size: 13px;
        margin: 8px 0 4px; }
th, td { border: 1px solid var(--grid); padding: 5px 9px; text-align: left; }
th { background: #F8FAFC; font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
figure { margin: 10px 0 4px; }
figcaption { color: var(--muted); font-size: 12px; margin-top: 4px; }
.crit { font-size: 12px; color: var(--muted); }
.crit li { margin: 2px 0; }
footer { margin-top: 32px; padding-top: 10px; border-top: 1px solid var(--grid);
         color: var(--muted); font-size: 11.5px; }
"""


# ---------------------------------------------------------------------- #
# HTML 报告
# ---------------------------------------------------------------------- #
def export_html_report(card: dict, out_path: str | Path, *,
                       figure_svg: str | None = None,
                       figure_caption: str = "") -> Path:
    """导出自包含 HTML 报告（内嵌 SVG 图 + 结果卡表格 + 口径出处）。

    figure_svg : SVG 文本（**内联**进报告，不依赖外部文件 —— 单文件可邮件
                 转发）。缺省则不带图。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = _render_html(card, figure_svg, figure_caption)
    out.write_text(html, encoding="utf-8")
    return out


def _render_html(card: dict, figure_svg: str | None,
                 figure_caption: str) -> str:
    """拼装 HTML 报告正文。"""
    h = card.get("header", {})
    s = card.get("structure", {})
    c = card.get("cell", {})
    f = card.get("fit", {})
    p = card.get("profile", {})
    m = card.get("microstructure", {})
    cp = card.get("composition", {})

    parts = [
        "<!DOCTYPE html>", "<html lang='zh-CN'>", "<head>",
        "<meta charset='utf-8'>",
        f"<title>{(h.get('sample') or 'NCM')} · Rietveld 精修报告</title>",
        f"<style>{HTML_CSS}</style>", "</head>", "<body>",
        f"<h1>{(h.get('sample') or '未命名样品')} · Rietveld 精修报告</h1>",
        f"<div class='sub'>{_subtitle(h, s)}</div>",
    ]

    # ---- 图 ----
    if figure_svg:
        parts.append("<figure>")
        parts.append(figure_svg)
        if figure_caption:
            parts.append(f"<figcaption>{figure_caption}</figcaption>")
        parts.append("</figure>")

    # ---- 晶体学 ----
    parts.append("<h2>晶体学</h2>")
    parts.append(_table([
        ("空间群", f"{s.get('space_group') or '—'}"
                   f"（No. {s.get('space_group_number') or '—'}）"),
        ("晶系", f"{s.get('crystal_system_zh') or '—'} / "
                 f"{s.get('crystal_system') or '—'}"),
        ("点群", s.get("point_group") or "—"),
        ("劳厄群", s.get("laue_group") or "—"),
        ("布拉维格子", s.get("bravais_lattice") or "—"),
        ("a / b / c", f"{_num(c.get('a'), 5)} / {_num(c.get('b'), 5)} / "
                      f"{_num(c.get('c'), 5)} Å"),
        ("α / β / γ", f"{_num(c.get('alpha'), 3)} / {_num(c.get('beta'), 3)} / "
                      f"{_num(c.get('gamma'), 3)} °"),
        ("晶胞体积", f"{_num(c.get('volume'), 3)} Å³"),
        ("c/a", _num(c.get("c_over_a"), 5)),
    ]))

    # ---- 组成与微结构 ----
    parts.append("<h2>组成与微结构</h2>")
    parts.append(_table([
        ("Li 占位 (3a)", _num(cp.get("li_occupancy"), 4)),
        ("O 的 z (6c)", _num(cp.get("o_z"), 5)),
        ("晶粒尺寸（相干衍射畴）",
         f"{_num(m.get('crystallite_size_nm'), 2)} nm"
         if m.get("crystallite_size_nm") is not None else "未测定"),
        ("微观应变", m.get("strain") if m.get("strain") is not None
         else "未检出可分辨微观应变"),
        ("尺寸/应变方法", m.get("method") or "—"),
    ]))

    # ---- 拟合优度 ----
    parts.append("<h2>拟合优度</h2>")
    parts.append(_table([
        ("Rwp", f"{_num(f.get('rwp'), 4)} %"),
        ("Rp", f"{_num(f.get('rp'), 4)} %"),
        ("Rexp", f"{_num(f.get('rexp'), 4)} %"),
        ("Bragg R", f"{_num(f.get('rbragg'), 4)} %"
         if f.get("rbragg") is not None else "—"),
        ("GOF (Rwp/Rexp)", _num(f.get("gof"), 4)),
        ("χ²", _num(f.get("chi2"), 4)),
        ("迭代次数", str(f.get("iterations", "—"))),
        ("收敛", "是" if f.get("success") else "否"),
    ]))

    # ---- 峰形参数 ----
    parts.append("<h2>峰形参数</h2>")
    rows = [
        ("zero", _num(p.get("zero"), 5)),
        ("U", _num(p.get("U"), 6)),
        ("V", _num(p.get("V"), 6)),
        ("W", _num(p.get("W"), 6)),
        ("η (Pseudo-Voigt)", _num(p.get("eta"), 4)),
        ("asym", _num(p.get("asym"), 5)),
        ("B (Debye-Waller)", _num(p.get("bfactor"), 4)),
    ]
    if p.get("po_r"):
        rows.append(("择优取向", "，".join(
            f"{k}=({v[0]}{v[1]}{v[2]}) r={v[3]:.4f}"
            for k, v in p["po_r"].items())))
    parts.append(_table(rows))

    # ---- 参数相关性 ----
    corr = card.get("correlations")
    if corr and corr.get("high_pairs"):
        parts.append("<h2>高相关参数对</h2>")
        parts.append("<table><tr><th>参数 A</th><th>参数 B</th>"
                     "<th>相关系数 r</th></tr>")
        for d in corr["high_pairs"][:10]:
            parts.append(f"<tr><td>{d['a']}</td><td>{d['b']}</td>"
                         f"<td class='num'>{d['r']:+.4f}</td></tr>")
        parts.append("</table>")

    # ---- 口径出处 ----
    crit = card.get("criteria_sources") or {}
    if crit:
        parts.append("<h2>口径出处</h2>")
        parts.append("<ul class='crit'>")
        for k, v in crit.items():
            parts.append(f"<li><b>{k}</b>：{v}</li>")
        parts.append("</ul>")

    if h.get("notes"):
        parts.append(f"<h2>备注</h2><div>{h['notes']}</div>")

    parts.append(
        f"<footer>由 {h.get('software') or 'PolyXRD-NCM'} 生成 · "
        f"{h.get('measured_at') or ''}</footer>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _subtitle(h: dict, s: dict) -> str:
    """报告副标题（样品 / 结构 / 仪器 / 操作 / 波长）。"""
    bits = []
    if h.get("structure"):
        bits.append(f"结构：{h['structure']}")
    if h.get("instrument"):
        bits.append(f"仪器：{h['instrument']}")
    if h.get("wavelength"):
        bits.append(f"波长：{h['wavelength']}")
    if h.get("operator"):
        bits.append(f"操作：{h['operator']}")
    if h.get("measured_at"):
        bits.append(f"时间：{h['measured_at']}")
    return "　·　".join(bits) if bits else "—"


def _num(v, n: int) -> str:
    """数值 → 字符串；None 显示破折号。"""
    if v is None:
        return "—"
    try:
        return f"{float(v):.{n}f}"
    except (TypeError, ValueError):
        return str(v)


def _table(rows: list[tuple[str, str]]) -> str:
    """两列键值表。"""
    out = ["<table>"]
    for k, v in rows:
        out.append(f"<tr><th>{k}</th><td>{v}</td></tr>")
    out.append("</table>")
    return "\n".join(out)

"""导出模块测试（T7.1b/c）。

**核心判据**：导出的东西必须与 GUI 画布**长得一样** —— 配色是同一套
（`ncm.core.palette`），否则界面里蓝色实测散点、报告里黑色实线，客户会
问"哪个是对的"。

覆盖：
- 配色单一出处（GUI 画布与核心导出引用同一个色板对象）；
- PNG / SVG 导出落盘且格式正确；
- SVG 文本内联（HTML 报告单文件）；
- CSV 逐点数据（BOM + 列头 + 差值 = 观测 - 计算）；
- 结果卡 JSON / TXT 导出；
- HTML 报告：单文件、含内嵌 SVG、含关键数值、含口径出处。
"""
from __future__ import annotations

import csv
import json
import re

import numpy as np
import pytest


@pytest.fixture
def curves():
    """一条确定性的合成曲线（实测 = 计算 + 差值）。"""
    tt = np.linspace(15.0, 60.0, 400)
    yc = 1000.0 * np.exp(-((tt - 44.5) / 0.15) ** 2) \
        + 600.0 * np.exp(-((tt - 18.8) / 0.2) ** 2) + 50.0
    diff = 3.0 * np.sin(tt * 7.0)
    return tt, yc + diff, yc, diff, np.full_like(tt, 50.0)


@pytest.fixture
def card():
    """一份最小可用的结果卡。"""
    from ncm.core.resultcard import build_card

    return {
        "header": {"sample": "测试样品", "structure": "NCM811",
                   "measured_at": "2026-01-01 00:00", "operator": "测试",
                   "instrument": "Rigaku SmartLab", "wavelength": "1.5406 Å",
                   "software": "PolyXRD-NCM", "notes": "备注一行"},
        "structure": {"name": "NCM811", "space_group": "R -3 m :H",
                      "space_group_number": 166, "crystal_system": "trigonal",
                      "crystal_system_zh": "三方", "point_group": "-3m",
                      "laue_group": "-3m", "bravais_lattice": "R"},
        "cell": {"a": 2.87186, "b": 2.87186, "c": 14.19511,
                 "alpha": 90.0, "beta": 90.0, "gamma": 120.0,
                 "volume": 101.30, "c_over_a": 4.94329},
        "composition": {"li_occupancy": 0.98689, "o_z": 0.25801},
        "microstructure": {"crystallite_size_nm": 155.0, "strain": "0.000e+00",
                           "method": "TCH (Scherrer)"},
        "profile": {"zero": 0.0, "U": 0.01, "V": -0.01, "W": 0.005,
                    "eta": 0.5, "asym": 0.1, "bfactor": 0.3, "X": 0.0,
                    "Y": 0.07, "po_r": {"NCM811": (0, 0, 1, 1.00045)}},
        "fit": {"rwp": 3.1584, "rp": 2.5, "rexp": 2.9, "rbragg": 4.6461,
                "gof": 1.0891, "chi2": 1.2, "success": True, "iterations": 12},
        "correlations": {"labels": ["a", "c"],
                         "matrix": [[1.0, 0.01], [0.01, 1.0]],
                         "high_pairs": [{"a": "a", "b": "c", "r": 0.01}]},
        "criteria_sources": {"cell": "STD_FREEZE §2（口径说明）",
                             "fit": "STD_FREEZE §2（口径说明）"},
    }


# --------------------------------------------------------------------------- #
# 配色单一出处
# --------------------------------------------------------------------------- #
def test_palette_is_single_source() -> None:
    """GUI 画布与核心导出必须引用**同一个**色板对象。"""
    from ncm.core import palette
    from ncm.gui import canvas

    assert canvas.OBS == palette.PALETTE["obs"]
    assert canvas.CALC == palette.PALETTE["calc"]
    assert canvas.DIFF == palette.PALETTE["diff"]
    assert canvas.BG == palette.PALETTE["bg"]
    assert canvas.MARK == palette.PALETTE["mark"]
    assert canvas.GRID == palette.PALETTE["grid"]


def test_legacy_plotting_uses_palette() -> None:
    """CLI 用的 `plotting.py` 也必须用统一色板（不再用中文习惯配色）。"""
    from ncm.core import palette, plotting

    assert plotting.plot_refinement.__doc__
    # 颜色字面量不应再出现在 plotting.py 里
    src = open(plotting.__file__, encoding="utf-8").read()
    assert "#D62728" not in src, "旧的中文习惯配色（计算=红）仍在"
    assert "#1F77B4" not in src, "旧的中文习惯配色（差值=蓝）仍在"
    assert palette.PALETTE["obs"] in src or "style.obs" in src


# --------------------------------------------------------------------------- #
# 图：PNG / SVG
# --------------------------------------------------------------------------- #
def test_export_png(tmp_path, curves) -> None:
    from ncm.core.export import export_figure

    tt, yo, yc, _diff, bg = curves
    out = export_figure(tt, yo, yc, tmp_path / "r.png", background=bg,
                         title="NCM811", rwp=3.1584)
    assert out.exists()
    assert out.stat().st_size > 5000
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "不是合法 PNG"


def test_export_svg(tmp_path, curves) -> None:
    from ncm.core.export import export_figure

    tt, yo, yc, _diff, bg = curves
    out = export_figure(tt, yo, yc, tmp_path / "r.svg", background=bg)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "http://www.w3.org/2000/svg" in text


def test_exported_svg_uses_palette_colors(tmp_path, curves) -> None:
    """★导出的 SVG 里必须出现色板的实际颜色值。"""
    from ncm.core.export import export_figure
    from ncm.core.palette import PALETTE

    tt, yo, yc, _diff, bg = curves
    out = export_figure(tt, yo, yc, tmp_path / "r.svg", background=bg)
    text = out.read_text(encoding="utf-8").upper()
    assert PALETTE["obs"].upper() in text, "实测谱颜色与色板不符"
    assert PALETTE["diff"].upper() in text, "差值线颜色与色板不符"


def test_svg_text_is_inline(tmp_path, curves) -> None:
    """SVG 文本不落盘直接返回（HTML 报告内联用）。"""
    from ncm.core.export import figure_svg_text

    tt, yo, yc, _diff, _bg = curves
    svg = figure_svg_text(tt, yo, yc, title="NCM811")
    assert svg.strip().startswith("<?xml") or "<svg" in svg
    assert len(svg) > 1000


def test_export_figure_rejects_length_mismatch(tmp_path) -> None:
    from ncm.core.export import export_figure

    with pytest.raises(ValueError, match="长度不一致"):
        export_figure(np.arange(10.0), np.arange(5.0), np.arange(10.0),
                      tmp_path / "x.png")


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def test_export_csv(tmp_path, curves) -> None:
    from ncm.core.export import export_points_csv

    tt, yo, yc, _diff, bg = curves
    out = export_points_csv(tt, yo, yc, tmp_path / "p.csv", background=bg)
    assert out.exists()
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "CSV 应带 UTF-8 BOM（Excel 不乱码）"
    with out.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["2theta_deg", "observed", "calculated", "difference",
                        "background"]
    assert len(rows) == tt.size + 1
    # 差值列 = 观测 - 计算
    r = rows[1]
    assert abs(float(r[3]) - (float(r[1]) - float(r[2]))) < 1e-4


def test_export_csv_without_background(tmp_path, curves) -> None:
    from ncm.core.export import export_points_csv

    tt, yo, yc, _diff, _bg = curves
    out = export_points_csv(tt, yo, yc, tmp_path / "p.csv")
    with out.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][4] == "", "无背景时该列应留空"


# --------------------------------------------------------------------------- #
# 结果卡 JSON / TXT
# --------------------------------------------------------------------------- #
def test_export_card_json(tmp_path, card) -> None:
    from ncm.core.export import export_card_json

    out = export_card_json(card, tmp_path / "c.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["fit"]["rwp"] == card["fit"]["rwp"]
    assert data["cell"]["a"] == card["cell"]["a"]


def test_export_card_text(tmp_path, card) -> None:
    from ncm.core.export import export_card_text

    out = export_card_text(card, tmp_path / "c.txt")
    text = out.read_text(encoding="utf-8")
    assert "3.1584" in text
    assert "Rwp" in text
    assert "测试样品" in text


# --------------------------------------------------------------------------- #
# HTML 报告
# --------------------------------------------------------------------------- #
def test_export_html_is_self_contained(tmp_path, card, curves) -> None:
    """★HTML 报告必须是单文件（图内嵌，不引用外部文件）。"""
    from ncm.core.export import export_html_report, figure_svg_text

    tt, yo, yc, _diff, bg = curves
    svg = figure_svg_text(tt, yo, yc, background=bg, title="NCM811")
    out = export_html_report(card, tmp_path / "r.html", figure_svg=svg)
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html, "图未内嵌"
    assert not re.search(r'<img[^>]+src="[^"]+"', html), "报告引用了外部图片"
    assert not re.search(r'<link[^>]+href="[^"]+\.css"', html), "报告引用了外部 CSS"


def test_export_html_contains_key_values(tmp_path, card) -> None:
    from ncm.core.export import export_html_report

    out = export_html_report(card, tmp_path / "r.html")
    html = out.read_text(encoding="utf-8")
    # 注意各值的显示精度：Li 占位 4 位、晶胞 5 位、尺寸 2 位
    for needle in ("3.1584", "2.87186", "14.19511", "0.9869", "155.00",
                   "R -3 m :H", "三方"):
        assert needle in html, f"报告缺 {needle}"


def test_export_html_contains_criteria(tmp_path, card) -> None:
    """报告必须带上口径出处（每个数可追溯）。"""
    from ncm.core.export import export_html_report

    out = export_html_report(card, tmp_path / "r.html")
    html = out.read_text(encoding="utf-8")
    assert "口径出处" in html
    assert "STD_FREEZE" in html


def test_export_html_marks_unmeasured(tmp_path, card) -> None:
    """未测定的项必须写明，不能显示 0.000 假精度。"""
    from ncm.core.export import export_html_report

    card = dict(card)
    card["microstructure"] = {"crystallite_size_nm": None, "strain": None,
                              "method": None}
    card["composition"] = {"li_occupancy": None, "o_z": None}
    out = export_html_report(card, tmp_path / "r.html")
    html = out.read_text(encoding="utf-8")
    assert "未测定" in html
    assert "未检出可分辨微观应变" in html
    assert "0.00000" not in html.split("Li 占位")[-1][:200]

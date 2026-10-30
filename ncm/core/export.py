"""精修结果导出（T7.1b · 新建，非 vendor）。

把一次精修的**谱图**与**结果卡**导出成可交付的文件：

===========  ==========================================================
格式          内容
===========  ==========================================================
PNG / SVG    Rietveld 标准图（上：实测/理论/背景；下：差值）
             —— 配色与 GUI 画布**完全一致**（`ncm.core.palette`）
CSV          逐点数据：2θ / 实测 / 计算 / 差值 / 背景
TXT          结果卡纯文本（`ncm.core.resultcard.render_text` 的口径）
JSON         结果卡结构化数据
HTML         自包含报告（见 `ncm.core.report_html`）
===========  ==========================================================

**为什么导出的配色必须与 GUI 一致**
--------------------------------
委托分析报告是给人看的交付物。如果界面里实测谱是蓝色散点、导出报告里却是
黑色实线，客户会问"哪个是对的"。故色板收在**核心层单一出处**
（`ncm.core.palette`），GUI 画布与本模块都从那里取 —— 规则 1（核心层不依赖
GUI）决定了色板不能放在 `ncm/gui/` 里，但反过来让核心层持有它完全没问题。

**模块划分**
------------
- `ncm/core/palette.py` —— 色板与轴样式（GUI 与导出共用）；
- `ncm/core/export.py` —— 本模块：图（PNG/SVG）+ CSV + 结果卡 JSON/TXT；
- `ncm/core/report_html.py` —— HTML 报告模板（纯文本拼装，独立成文件）。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from ncm.core.palette import DEFAULT_STYLE, SpectrumStyle, apply_axis_style


def _mpl():
    """延迟导入 matplotlib 并强制无界面后端（CLI/测试环境安全）。"""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    return plt


def _validate(two_theta, yobs, ycalc) -> tuple[np.ndarray, ...]:
    x = np.asarray(two_theta, dtype=float)
    yo = np.asarray(yobs, dtype=float)
    yc = np.asarray(ycalc, dtype=float)
    if not (x.shape == yo.shape == yc.shape):
        raise ValueError(f"曲线长度不一致: {x.shape}, {yo.shape}, {yc.shape}")
    return x, yo, yc


# ---------------------------------------------------------------------- #
# 图：PNG / SVG
# ---------------------------------------------------------------------- #
def _make_figure(two_theta, yobs, ycalc, background, labels, style,
                 title: str, rwp: float | None):
    """建好 Rietveld 双轴图（图已画完，未保存）。

    :func:`export_figure` 与 :func:`figure_svg_text` 共用它 —— 保证
    「落盘的图」与「内嵌 HTML 的图」**逐像素同源**。
    """
    plt = _mpl()
    from ncm.core.palette import set_cjk_font

    set_cjk_font(plt)
    x, yo, yc = _validate(two_theta, yobs, ycalc)
    bg = np.asarray(background, dtype=float) if background is not None else None
    L = _merge_labels(labels)
    st = style

    peak = float(np.max(yo)) if yo.size else 1.0
    span = max(float(np.max(yo) - np.min(yo)), 1e-9)
    fig, (ax, axd) = plt.subplots(
        2, 1, figsize=(9.0, 5.6), sharex=True,
        gridspec_kw={"height_ratios": [4, 1.25], "hspace": 0.06})

    ax.plot(x, yo, linestyle="none", marker=st.obs_marker, color=st.obs,
            markersize=st.obs_markersize, markeredgewidth=0.6, label=L["obs"])
    ax.plot(x, yc, color=st.calc, lw=st.calc_lw, label=L["calc"])
    if bg is not None:
        ax.plot(x, bg, color=st.bg, lw=st.bg_lw, ls=st.bg_ls, label=L["bg"])
    ax.set_ylabel(L["y"], fontsize=st.size_label)
    ax.set_ylim(min(float(np.min(yo)), 0.0) - 0.02 * span, peak + 0.10 * span)
    head = title or "Rietveld refinement"
    if rwp is not None:
        head += f"    Rwp = {rwp:.2f}%"
    ax.set_title(head, fontsize=st.size_title)
    ax.legend(loc="upper right", fontsize=8.5, frameon=False, ncol=3)
    apply_axis_style(ax, st)

    diff = yo - yc
    axd.axhline(0.0, color=st.grid, lw=0.7)
    axd.plot(x, diff, color=st.diff, lw=st.diff_lw, label=L["err"])
    axd.set_ylabel(L["y_diff"], fontsize=st.size_label)
    axd.set_xlabel(L["x"], fontsize=st.size_label)
    lim = max(float(np.max(np.abs(diff))), 1e-6) * 1.15
    axd.set_ylim(-lim, lim)
    axd.legend(loc="upper right", fontsize=8.5, frameon=False)
    apply_axis_style(axd, st)
    return fig, plt, x, yo, yc, bg


def export_figure(two_theta, yobs, ycalc, out_path: str | Path, *,
                  background=None, title: str = "", rwp: float | None = None,
                  labels: dict | None = None,
                  style: SpectrumStyle = DEFAULT_STYLE,
                  dpi: int = 160) -> Path:
    """导出 Rietveld 标准图（PNG 或 SVG，**由扩展名决定**）。

    配色与 GUI 画布完全一致（实测=蓝 ×、计算=黑线、差值=红）。

    labels : {"obs"/"calc"/"bg"/"err"/"x"/"y"/"y_diff"} 的文案；
             缺省用中文（导出场景默认给中文报告）。
    """
    fig, plt, *_ = _make_figure(two_theta, yobs, ycalc, background, labels,
                                style, title, rwp)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # SVG 必须显式指定格式（savefig 靠扩展名推断，但 SVG 后端不吃 dpi）
    fig.savefig(out, dpi=dpi, bbox_inches="tight",
                format="svg" if out.suffix.lower() == ".svg" else "png")
    plt.close(fig)
    return out


def figure_svg_text(two_theta, yobs, ycalc, *, background=None,
                    title: str = "", rwp: float | None = None,
                    labels: dict | None = None,
                    style: SpectrumStyle = DEFAULT_STYLE) -> str:
    """生成 SVG **文本**（不落盘）—— HTML 报告内联用。

    与 :func:`export_figure` 走同一个绘图函数，只是把结果以字符串返回，
    这样 HTML 报告是**单文件**（图内嵌，不依赖外部 SVG）。
    """
    import io

    fig, plt, *_ = _make_figure(two_theta, yobs, ycalc, background, labels,
                                style, title, rwp)
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _merge_labels(labels: dict | None) -> dict:
    """合并默认中文文案与调用方覆盖。"""
    base = {
        "obs": "实测", "calc": "计算", "bg": "背景", "err": "差值",
        "x": "2θ (°)", "y": "强度 (计数)", "y_diff": "差值",
    }
    if labels:
        base.update(labels)
    return base


# ---------------------------------------------------------------------- #
# 逐点数据：CSV
# ---------------------------------------------------------------------- #
def export_points_csv(two_theta, yobs, ycalc, out_path: str | Path, *,
                      background=None) -> Path:
    """导出逐点数据（2θ / 实测 / 计算 / 差值 / 背景）。

    用 UTF-8 with BOM 写 —— Excel 直接双击打开不乱码（不带 BOM 会按本地
    编码猜，中文表头/样品名在中文 Windows 上乱码）。
    """
    x, yo, yc = _validate(two_theta, yobs, ycalc)
    bg = np.asarray(background, dtype=float) if background is not None else None
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["2theta_deg", "observed", "calculated", "difference",
                    "background"])
        for i in range(x.size):
            row = [f"{x[i]:.5f}", f"{yo[i]:.6f}", f"{yc[i]:.6f}",
                   f"{yo[i] - yc[i]:.6f}"]
            row.append(f"{bg[i]:.6f}" if bg is not None else "")
            w.writerow(row)
    return out


# ---------------------------------------------------------------------- #
# 结果卡：JSON / TXT
# ---------------------------------------------------------------------- #
def export_card_json(card: dict, out_path: str | Path) -> Path:
    """导出结果卡 JSON。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(card, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return out


def export_card_text(card: dict, out_path: str | Path) -> Path:
    """导出结果卡纯文本（复用核心层 `render_text`，口径与邮件摘要一致）。"""
    from ncm.core.resultcard import render_text

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_text(card), encoding="utf-8")
    return out


def export_html_report(card: dict, out_path: str | Path, *,
                       figure_svg: str | None = None,
                       figure_caption: str = "") -> Path:
    """导出自包含 HTML 报告（实现见 `ncm.core.report_html`）。

    这里只做转引 —— 让调用方（GUI / CLI）只需认 `ncm.core.export` 一个入口。
    """
    from ncm.core.report_html import export_html_report as _impl

    return _impl(card, out_path, figure_svg=figure_svg,
                 figure_caption=figure_caption)



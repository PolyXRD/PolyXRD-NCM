"""谱图与精修结果绘图（T1.4 · T7.1a 配色统一）。

只做一件事：把「观测 / 计算 / 背景 / 差值」四条线画成 Rietveld 标准图。

**配色已统一到核心层**（T7.1a）：本模块与 GUI 画布、PNG/SVG/HTML 导出
都从 `ncm.core.palette` 取色板 —— 界面里是蓝色实测散点，报告里就也是蓝色
实测散点。原先本模块用中文习惯配色（观测=黑、计算=红、差值=蓝），与 GUI
不一致，已废止。

> 保留本模块而不直接用 `ncm.core.export.export_figure`，是为了**不改已有
> 函数签名**（TASKS.md 规则 3）：`plot_refinement()` 是 CLI 的既有入口。
> 新代码请用 `ncm.core.export`。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ncm.core.palette import DEFAULT_STYLE, SpectrumStyle, apply_axis_style


def _mpl():
    """延迟导入 matplotlib 并强制无界面后端（CLI/测试环境安全）。"""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    return plt


def _cjk_font(plt) -> None:
    """尽量挑一个本机中文字体，挑不到就用默认（不报错）。"""
    from ncm.core.palette import set_cjk_font

    set_cjk_font(plt)


def plot_refinement(two_theta: np.ndarray, yobs: np.ndarray, ycalc: np.ndarray,
                    background: np.ndarray | None, out_png: str | Path,
                    *, title: str = "", rwp: float | None = None,
                    dpi: int = 160,
                    style: SpectrumStyle = DEFAULT_STYLE) -> Path:
    """画 Rietveld 标准图：上方 观测/计算/背景，下方 差值曲线。

    配色与 GUI 画布一致（T7.1a）。
    """
    plt = _mpl()
    _cjk_font(plt)

    x = np.asarray(two_theta, dtype=float)
    yo = np.asarray(yobs, dtype=float)
    yc = np.asarray(ycalc, dtype=float)
    if not (x.shape == yo.shape == yc.shape):
        raise ValueError(f"曲线长度不一致: {x.shape}, {yo.shape}, {yc.shape}")

    bg = np.asarray(background, dtype=float) if background is not None else None
    peak = float(np.max(yo)) if yo.size else 1.0
    span = max(float(np.max(yo) - np.min(yo)), 1e-9)

    fig, (ax, axd) = plt.subplots(
        2, 1, figsize=(9.0, 5.6), sharex=True,
        gridspec_kw={"height_ratios": [4, 1.25], "hspace": 0.06})

    ax.plot(x, yo, linestyle="none", marker=style.obs_marker, color=style.obs,
            markersize=style.obs_markersize, markeredgewidth=0.6, label="观测")
    ax.plot(x, yc, color=style.calc, lw=style.calc_lw, label="计算")
    if bg is not None:
        ax.plot(x, bg, color=style.bg, lw=style.bg_lw, ls=style.bg_ls,
                label="背景")
    ax.set_ylabel("强度 (计数)")
    ax.set_ylim(min(float(np.min(yo)), 0.0) - 0.02 * span,
                peak + 0.10 * span)
    head = title or "Rietveld 精修"
    if rwp is not None:
        head += f"    Rwp = {rwp:.2f}%"
    ax.set_title(head, fontsize=style.size_title)
    ax.legend(loc="upper right", fontsize=8.5, frameon=False, ncol=3)

    diff = yo - yc
    axd.axhline(0.0, color=style.grid, lw=0.7)
    axd.plot(x, diff, color=style.diff, lw=style.diff_lw)
    axd.set_ylabel("差值", fontsize=style.size_label)
    axd.set_xlabel("2θ (°)")
    lim = max(float(np.max(np.abs(diff))), 1e-6) * 1.15
    axd.set_ylim(-lim, lim)
    apply_axis_style(ax, style)
    apply_axis_style(axd, style)

    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_spectrum(two_theta: np.ndarray, intensity: np.ndarray,
                  out_png: str | Path, *, title: str = "", dpi: int = 160,
                  style: SpectrumStyle = DEFAULT_STYLE) -> Path:
    """单条谱图（预处理前后对比、判定门示意用）。"""
    plt = _mpl()
    _cjk_font(plt)
    fig, ax = plt.subplots(figsize=(9.0, 3.4))
    ax.plot(np.asarray(two_theta), np.asarray(intensity), color=style.ink,
            lw=0.9)
    ax.set_xlabel("2θ (°)")
    ax.set_ylabel("强度 (计数)")
    if title:
        ax.set_title(title, fontsize=style.size_title)
    apply_axis_style(ax, style)
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out

"""matplotlib 谱图画布（NCM）。

- 空态显示提示文字；
- ``show_pattern``：单谱显示（导入后，可选叠加寻峰标记）；
- ``show_fit``：拟合叠加显示（上 obs/calc/背景，下 差值线）。

**配色沿用家族 GUI v1.2.0 用户指定样式**（实测=蓝色 ×、计算=黑色实线、
差值=红色实线）。色板的**唯一出处**在 `ncm/core/palette.py` —— T7.1 起
CLI/PNG/SVG/HTML 导出也用它，保证「界面里长什么样，报告里就长什么样」
（规则 1 要求核心层不依赖 GUI，故色板放在核心层、GUI 反过来引用）。

绘制逻辑集中在 :func:`draw_fit`，主画布与离屏 PNG 导出共用，保证两处样式一致。
"""

from __future__ import annotations

import numpy as np
import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

# 让画布文案（中文/日文）正确渲染：优先 CJK 字体，关闭负号替换
matplotlib.rcParams["font.sans-serif"] = [
    "Source Han Sans CN", "思源黑体 CN", "Microsoft YaHei", "SimHei",
    "Noto Sans CJK SC", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

from ncm.core.palette import DEFAULT_STYLE, apply_axis_style
from ncm.i18n import tr

# 家族 GUI v1.2.0 色板（**定义在核心层** ncm/core/palette.py，此处只引用）
STYLE = DEFAULT_STYLE
INK = STYLE.ink
OBS = STYLE.obs
CALC = STYLE.calc
DIFF = STYLE.diff
BG = STYLE.bg
GRID = STYLE.grid
MARK = STYLE.mark


def draw_fit(ax_main, ax_diff, two_theta, yobs, ycalc, diff,
             background=None, peaks=None) -> None:
    """在上下双轴上按家族样式绘制拟合谱（画布与离屏 PNG 共用）。

    ax_main：实测谱（蓝 × 散点）+ 理论谱（黑实线）+ 可选背景/寻峰标记；
    ax_diff：差值线（红）与零基线，x 轴标签只在此处标注一次。
    """
    tt = np.asarray(two_theta)
    h_obs, = ax_main.plot(tt, np.asarray(yobs), linestyle="none", marker="x",
                          color=OBS, markersize=3.0, markeredgewidth=0.6,
                          label=tr("canvas.legend.obs"))
    h_calc, = ax_main.plot(tt, np.asarray(ycalc), color=CALC, lw=1.0,
                           label=tr("canvas.legend.calc"))
    handles = [h_obs, h_calc]
    labels = [tr("canvas.legend.obs"), tr("canvas.legend.calc")]
    if background is not None:
        ax_main.plot(tt, np.asarray(background), color=BG, lw=0.8, ls=":")
    if peaks is not None and len(peaks):
        px = [p[0] for p in peaks]
        py = [p[1] for p in peaks]
        ax_main.plot(px, py, marker="v", color=MARK, markersize=5,
                     linestyle="none")
    ax_main.set_ylabel(tr("canvas.y_label"))
    apply_axis_style(ax_main)

    h_diff, = ax_diff.plot(tt, np.asarray(diff), color=DIFF, lw=0.8,
                            label=tr("canvas.legend.err"))
    ax_diff.axhline(0.0, color=GRID, lw=0.6)
    ax_diff.set_xlabel(tr("canvas.x_label"))
    ax_diff.set_ylabel(tr("canvas.y_diff"))
    apply_axis_style(ax_diff)
    ax_diff.tick_params(labelbottom=True)
    ax_main.tick_params(labelbottom=False)
    handles.append(h_diff)
    labels.append(tr("canvas.legend.err"))
    ax_main.legend(handles, labels, loc="upper right", fontsize=8,
                   frameon=False)


class PatternCanvas(FigureCanvasQTAgg):
    """谱图显示画布（QWidget）。"""

    def __init__(self, parent=None) -> None:
        self.figure = Figure(figsize=(5.6, 4.4), dpi=100)
        super().__init__(self.figure)
        self.setParent(parent)
        self._has_data = False
        self._fit: tuple | None = None     # 最近一次拟合数据（语言切换时重绘）
        self.ax_main = self.figure.add_subplot(111)
        self.ax_diff = None
        self._show_empty()
        self.figure.tight_layout()

    # ------------------------------------------------------------------ #
    # 显示
    # ------------------------------------------------------------------ #
    def show_pattern(self, two_theta: np.ndarray, intensity: np.ndarray,
                     *, peaks=None) -> None:
        """显示单条谱图（导入后）。`peaks` 为 [(2θ, 强度), ...] 寻峰标记。"""
        self._reset_axes()
        self.ax_main.plot(two_theta, intensity, color=INK, lw=0.9)
        if peaks is not None and len(peaks):
            self.ax_main.plot([p[0] for p in peaks], [p[1] for p in peaks],
                              marker="v", color=MARK, markersize=5,
                              linestyle="none")
        self._style_main()
        self._has_data = True
        self.figure.tight_layout()
        self.draw_idle()

    def show_fit(self, two_theta: np.ndarray, yobs: np.ndarray,
                 ycalc: np.ndarray, diff: np.ndarray, *,
                 background=None, peaks=None) -> None:
        """拟合叠加：上 2/3 实测谱+理论谱，下 1/3 差值线（共用 x 轴）。

        这里必须彻底清空 figure（不能复用 ``_reset_axes``）—— 后者会保留
        一个 111 主轴，若在其上再叠加 two-row 子图，会残留一个 0..1 归一化
        坐标的空坐标框，导致刻度标签重影。也不用 ``add_gridspec`` +
        自定义 hspace：tight_layout 与之不兼容（告警并放弃重排，x 轴标题
        会被裁掉），故改用 ``Figure.subplots``。
        """
        self._fit = (two_theta, yobs, ycalc, diff, background, peaks)
        self._clear_figure()
        self.ax_main, self.ax_diff = self.figure.subplots(
            2, 1, height_ratios=[2, 1], sharex=True)
        draw_fit(self.ax_main, self.ax_diff, two_theta, yobs, ycalc, diff,
                 background=background, peaks=peaks)
        self._has_data = True
        self.figure.tight_layout()
        self.draw_idle()

    def clear(self) -> None:
        """清空回空态。"""
        self._fit = None
        self._reset_axes()
        self._show_empty()
        self.figure.tight_layout()
        self.draw_idle()

    def save_png(self, path: str) -> None:
        """导出当前画布为 PNG。"""
        self.figure.savefig(path, dpi=150, facecolor="white")

    # ------------------------------------------------------------------ #
    # 多语言
    # ------------------------------------------------------------------ #
    def retranslate(self) -> None:
        """语言切换后刷新轴标签/图例/空态文案。

        拟合态直接按缓存数据重绘（图例与两个轴标签一并换新语言），
        单谱态与空态只改标签，避免为刷新文案而缓存整条谱。
        """
        if self._fit is not None:
            # _fit 含背景与寻峰标记（keyword-only），不能直接 * 解包位置参数
            tt, yo, yc, diff, bg, peaks = self._fit
            self.show_fit(tt, yo, yc, diff, background=bg, peaks=peaks)
            return
        if not self._has_data:
            self.clear()
            return
        self.ax_main.set_ylabel(tr("canvas.y_label"))
        self.figure.tight_layout()
        self.draw_idle()

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _reset_axes(self) -> None:
        """清空画布并重建单个主轴（单谱显示模式使用）。"""
        self.figure.clf()
        self.ax_main = self.figure.add_subplot(111)
        self.ax_diff = None

    def _clear_figure(self) -> None:
        """彻底清空 figure（不留任何 axes），供多子图模式重新布局前调用。"""
        self.figure.clf()
        self.ax_main = None
        self.ax_diff = None

    def _show_empty(self) -> None:
        self.ax_main.set_facecolor("white")
        self.ax_main.text(0.5, 0.5, tr("canvas.empty"),
                          ha="center", va="center", fontsize=11,
                          color="#64748B", transform=self.ax_main.transAxes)
        self.ax_main.set_xticks([])
        self.ax_main.set_yticks([])

    def _style_main(self) -> None:
        self.ax_main.set_ylabel(tr("canvas.y_label"))
        apply_axis_style(self.ax_main)

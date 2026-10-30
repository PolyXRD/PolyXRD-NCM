"""谱图配色与绘图样式（T7.1a · 新建，非 vendor）。

**为什么单列一个模块**
--------------------
T7.1 之前存在**两套配色**：

- `ncm/gui/canvas.py`：家族 GUI v1.2.0 用户指定样式（实测=蓝 ×、计算=黑线、
  差值=红）；
- `ncm/core/plotting.py`：中文习惯配色（观测=黑、计算=红、差值=蓝）。

同一份数据在界面里和导出报告里长得不一样 —— 对委托分析报告来说这是硬伤
（客户会问"界面是蓝的，报告里怎么是黑的"）。故把色板收到**核心层**单一
出处，GUI 与导出都从里取。

**层次**
------
本模块在 `ncm/core/` —— 核心层不依赖 GUI（规则 1），色板与样式在这里定义，
`ncm/gui/canvas.py` 反过来引用它。这样 CLI/导出无需引入 Qt。

用法::

    from ncm.core.palette import PALETTE, apply_axis_style

    ax.plot(x, y, color=PALETTE.obs)
    apply_axis_style(ax)
"""
from __future__ import annotations

from dataclasses import dataclass

#: 家族 GUI v1.2.0 色板（用户指定样式）
#:
#: - ``obs``  蓝色 —— 实测谱散点
#: - ``calc`` 近黑 —— 理论谱实线
#: - ``diff`` 红色 —— 差值线
#: - ``bg``   灰蓝 —— 背景线（点线）
#: - ``grid`` 浅灰 —— 网格
#: - ``mark`` 琥珀 —— 寻峰标记
#: - ``ink``  深色 —— 单谱显示（非拟合态）
PALETTE = {
    "ink": "#0F172A",
    "obs": "#0284C7",
    "calc": "#0F172A",
    "diff": "#DC2626",
    "bg": "#94A3B8",
    "grid": "#CBD5E1",
    "mark": "#F59E0B",
}

#: 轴标签与图例的默认字号（GUI 与导出一致，避免同一张图两种字号）
FONT_SIZE_LABEL = 10
FONT_SIZE_TICK = 8.5
FONT_SIZE_TITLE = 11


@dataclass(frozen=True)
class SpectrumStyle:
    """一套完整的谱图样式（颜色 + 字号 + 线型）。

    单独抽成 dataclass 而不是散落的常量，是为了让「界面」与「导出」能
    **成对地**取用同一份样式，而不是各挑几个颜色 —— 后者迟早会漏。
    """

    ink: str = PALETTE["ink"]
    obs: str = PALETTE["obs"]
    calc: str = PALETTE["calc"]
    diff: str = PALETTE["diff"]
    bg: str = PALETTE["bg"]
    grid: str = PALETTE["grid"]
    mark: str = PALETTE["mark"]

    #: 实测谱的线型：拟合态用 × 散点（点太密看不清实测/理论的重合），
    #: 单谱态用实线（散点在小图上太稀疏）
    obs_marker: str = "x"
    obs_lw: float = 0.9
    obs_markersize: float = 3.0
    calc_lw: float = 1.0
    diff_lw: float = 0.8
    bg_lw: float = 0.8
    bg_ls: str = ":"
    grid_lw: float = 0.4
    grid_alpha: float = 0.5

    size_label: int = FONT_SIZE_LABEL
    size_tick: float = FONT_SIZE_TICK
    size_title: int = FONT_SIZE_TITLE


#: 默认样式（GUI 与导出共用这一份）
DEFAULT_STYLE = SpectrumStyle()


def apply_axis_style(ax, style: SpectrumStyle = DEFAULT_STYLE) -> None:
    """给坐标轴套上统一网格与刻度样式。

    网格用浅灰细线（0.4 pt、alpha 0.5）—— 太粗会盖住谱线本身。
    """
    ax.grid(True, color=style.grid, lw=style.grid_lw, alpha=style.grid_alpha)
    ax.tick_params(labelsize=style.size_tick)
    ax.margins(x=0.01)


def set_cjk_font(plt) -> None:
    """挑一个本机中文字体（挑不到就用默认，不报错）。

    中文/日文标签必须能渲染，否则导出图上是一堆方框。
    """
    from matplotlib import font_manager

    want = ["Source Han Sans CN", "思源黑体 CN", "Microsoft YaHei",
            "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in want:
        if name in have:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    plt.rcParams["axes.unicode_minus"] = False

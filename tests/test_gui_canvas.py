"""谱图画布测试（T6.1b 验收）。

全部跑在 Qt **离屏**平台（conftest 的 `qapp` fixture）上，不弹窗。
"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.i18n import set_language


@pytest.fixture(scope="module")
def canvas(qapp):
    from ncm.gui.canvas import PatternCanvas

    return PatternCanvas()


@pytest.fixture
def spectrum():
    tt = np.linspace(10.0, 80.0, 3500)
    y = 100.0 + 5000.0 * np.exp(-((tt - 44.5) / 0.15) ** 2) \
        + 3000.0 * np.exp(-((tt - 18.8) / 0.2) ** 2)
    return tt, y


def test_canvas_constructs(qapp) -> None:
    from ncm.gui.canvas import PatternCanvas

    c = PatternCanvas()
    assert c.ax_main is not None
    assert c.ax_diff is None


def test_show_pattern_draws_one_curve(canvas, spectrum) -> None:
    tt, y = spectrum
    canvas.show_pattern(tt, y)
    assert canvas.ax_main.get_lines(), "单谱未画线"
    assert canvas.ax_diff is None, "单谱模式不应有差值子图"


def test_show_pattern_with_peak_markers(canvas, spectrum) -> None:
    tt, y = spectrum
    before = len(canvas.ax_main.get_lines())
    canvas.show_pattern(tt, y, peaks=[(44.5, 5000.0), (18.8, 3000.0)])
    assert len(canvas.ax_main.get_lines()) == before + 1   # 谱线 + 标记（单 Line2D）


def test_show_fit_creates_two_axes(canvas, spectrum) -> None:
    tt, y = spectrum
    yc = y * 1.01
    diff = y - yc
    canvas.show_fit(tt, y, yc, diff)
    assert canvas.ax_diff is not None, "拟合模式应有差值子图"
    assert len(canvas.figure.axes) == 2
    assert canvas.ax_main.get_lines(), "拟合模式主图未画线"
    assert canvas.ax_diff.get_lines(), "差值子图未画线"


def test_show_fit_legend_has_three_entries(canvas, spectrum) -> None:
    tt, y = spectrum
    canvas.show_fit(tt, y, y * 1.01, y - y * 1.01)
    legend = canvas.ax_main.get_legend()
    assert legend is not None
    assert len(legend.get_texts()) == 3, "图例应为 实测/计算/差值 三项"


def test_clear_resets_to_empty(canvas, spectrum) -> None:
    tt, y = spectrum
    canvas.show_pattern(tt, y)
    canvas.clear()
    assert not canvas.ax_main.get_lines()
    assert canvas.ax_diff is None


def test_retranslate_switches_labels(canvas, spectrum) -> None:
    tt, y = spectrum
    canvas.show_pattern(tt, y)
    set_language("en_US")
    canvas.retranslate()
    assert canvas.ax_main.get_ylabel() == "Intensity (counts)"
    set_language("ja_JP")
    canvas.retranslate()
    assert canvas.ax_main.get_ylabel() == "強度 (counts)"
    set_language("zh_CN")
    canvas.retranslate()
    assert canvas.ax_main.get_ylabel() == "强度 (counts)"


def test_retranslate_after_fit_keeps_two_axes(canvas, spectrum) -> None:
    """拟合态切换语言后仍应是双轴（图例与轴标签一并换新）。"""
    tt, y = spectrum
    canvas.show_fit(tt, y, y * 1.01, y - y * 1.01)
    set_language("en_US")
    canvas.retranslate()
    assert len(canvas.figure.axes) == 2
    assert canvas.ax_diff.get_xlabel() == "2θ (deg)"
    set_language("zh_CN")
    canvas.retranslate()


def test_save_png(canvas, spectrum, tmp_path) -> None:
    tt, y = spectrum
    canvas.show_pattern(tt, y)
    out = tmp_path / "canvas.png"
    canvas.save_png(str(out))
    assert out.exists() and out.stat().st_size > 0

"""处理工具条测试（T6.2a 验收）。

**核心判据：处理只作用于「显示谱」，原始谱永不被改写** —— 精修吃的必须是
原始谱（Rietveld 自己拟合背景）。工具条测试全部在 Qt 离屏平台跑。
"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.i18n import set_language


@pytest.fixture
def win(qapp, sample_811, monkeypatch):
    """构造主窗口并导入真实 NCM811 谱。"""
    from PySide6.QtWidgets import QFileDialog

    from ncm.gui.main_window import MainWindow

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(sample_811), "")))
    w = MainWindow()
    w._on_open()
    yield w
    set_language("zh_CN")


@pytest.fixture
def synth_window(qapp):
    """构造主窗口并装一条合成谱（两个尖峰 + 背景），便于精确断言。"""
    from ncm.core.dtypes import Pattern

    from ncm.gui.main_window import MainWindow

    w = MainWindow()
    tt = np.arange(10.0, 80.0, 0.02)
    y = 120.0 + 4000.0 * np.exp(-((tt - 44.5) / 0.12) ** 2) \
        + 2500.0 * np.exp(-((tt - 18.8) / 0.18) ** 2)
    w._pattern = Pattern(two_theta=tt, intensity=y)
    w._set_process_enabled(True)
    return w


def _answer(monkeypatch, value):
    """把 QInputDialog 的取值固定下来（跳过交互）。"""
    from PySide6.QtWidgets import QInputDialog

    if isinstance(value, tuple):                 # getItem -> (text, ok)
        monkeypatch.setattr(QInputDialog, "getItem",
                            staticmethod(lambda *a, **k: value))
    elif isinstance(value, bool):                # getInt/getDouble -> (n, ok)
        monkeypatch.setattr(QInputDialog, "getInt",
                            staticmethod(lambda *a, **k: (value, True)))
        monkeypatch.setattr(QInputDialog, "getDouble",
                            staticmethod(lambda *a, **k: (value, True)))
    else:
        monkeypatch.setattr(QInputDialog, "getInt",
                            staticmethod(lambda *a, **k: (value, True)))
        monkeypatch.setattr(QInputDialog, "getDouble",
                            staticmethod(lambda *a, **k: (value, True)))
        monkeypatch.setattr(QInputDialog, "getItem",
                            staticmethod(lambda *a, **k: (value, True)))


def test_toolbar_attached_with_actions(win) -> None:
    assert win.toolbar is not None
    assert win.toolbar.objectName() == "processToolbar"
    assert win.toolbar.actions(), "工具条没有挂上任何动作"


def test_actions_disabled_without_pattern(qapp) -> None:
    from ncm.gui.main_window import MainWindow

    w = MainWindow()
    for key in ("smooth", "background", "kalpha2", "peaks"):
        assert not w.act_process[key].isEnabled(), f"{key} 应在未导入谱图时禁用"


def test_actions_enabled_after_import(win) -> None:
    for key in ("smooth", "background", "kalpha2", "peaks"):
        assert win.act_process[key].isEnabled(), f"{key} 导入后应可用"


def test_smooth_does_not_modify_original(win, monkeypatch) -> None:
    """★原始谱不得被平滑改写（否则精修吃到的是处理谱）。"""
    before = np.array(win._pattern.intensity, copy=True)
    _answer(monkeypatch, 9)
    win.controller.apply_smooth()
    after = np.array(win._pattern.intensity, copy=True)
    assert np.array_equal(before, after), "原始谱被改写了"
    assert win.controller.processed is not None
    assert not np.array_equal(win.controller.processed.intensity, before)


def test_smooth_reduces_point_to_point_noise(synth_window, monkeypatch) -> None:
    """平滑应降低相邻点差分的绝对值之和（噪声被压掉）。"""
    from ncm.core.dtypes import Pattern

    w = synth_window
    tt = np.asarray(w._pattern.two_theta)
    rng = np.random.default_rng(7)
    noisy = np.asarray(w._pattern.intensity) + rng.normal(0, 5, tt.size)
    w._pattern = Pattern(two_theta=tt, intensity=noisy)
    rough_before = float(np.abs(np.diff(noisy)).sum())
    _answer(monkeypatch, 9)
    w.controller.apply_smooth()
    rough_after = float(np.abs(np.diff(w.controller.processed.intensity)).sum())
    assert rough_after < rough_before


def test_background_subtraction_lifts_edges(synth_window, monkeypatch) -> None:
    """扣背景后谱图两端的残余水平应接近 0。"""
    w = synth_window
    _answer(monkeypatch, "linear_edges")
    w.controller.apply_background()
    net = np.asarray(w.controller.processed.intensity)
    edge = max(2, net.size // 50)
    assert abs(float(net[:edge].mean())) < 30.0


def test_kalpha2_reduces_high_angle_doublet(synth_window, monkeypatch) -> None:
    """合成一条含 Kα2 伴峰的谱，去 Kα2 后伴峰应被压掉。"""
    from ncm.core.dtypes import Pattern

    w = synth_window
    tt = np.asarray(w._pattern.two_theta)
    # Cu Kα2 相对 Kα1 在 44.5° 处的位移约 +0.11°
    y = (np.asarray(w._pattern.intensity)
         + 800.0 * np.exp(-((tt - 44.61) / 0.12) ** 2))
    w._pattern = Pattern(two_theta=tt, intensity=y)
    _answer(monkeypatch, 0.5)
    w.controller.apply_kalpha2()
    out = np.asarray(w.controller.processed.intensity)
    near = (tt >= 44.55) & (tt <= 44.67)
    far = (tt >= 44.40) & (tt <= 44.50)
    assert out[near].max() < 0.6 * out[far].max() + 200.0


def test_find_peaks_locates_synthetic_peaks(synth_window, monkeypatch) -> None:
    w = synth_window
    _answer(monkeypatch, 0.01)
    w.controller.find_peaks()
    peaks = w.controller.peaks
    assert peaks, "未找到任何峰"
    tts = sorted(p.two_theta for p in peaks)
    assert any(abs(t - 44.5) < 0.1 for t in tts), f"未命中 44.5° 峰: {tts}"
    assert any(abs(t - 18.8) < 0.1 for t in tts), f"未命中 18.8° 峰: {tts}"


def test_peak_markers_drawn_on_canvas(synth_window, monkeypatch) -> None:
    w = synth_window
    _answer(monkeypatch, 0.01)
    w.controller.find_peaks()
    assert len(w.canvas.ax_main.get_lines()) >= 2, "画布应有谱线 + 峰标记"


def test_reset_restores_original(synth_window, monkeypatch) -> None:
    w = synth_window
    _answer(monkeypatch, 9)
    w.controller.apply_smooth()
    assert w.controller.processed is not None
    w.controller.reset()
    assert w.controller.processed is None
    assert w.controller.peaks == []
    assert len(w.canvas.ax_main.get_lines()) == 1


def test_action_without_pattern_shows_message(qapp, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from ncm.gui.main_window import MainWindow

    w = MainWindow()
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(1))
    w.controller.apply_smooth()
    assert shown, "未导入谱图时应弹提示"


def test_cancelled_dialog_does_nothing(win, monkeypatch) -> None:
    """用户在输入框里点了取消 —— 不应改变任何东西。"""
    from PySide6.QtWidgets import QInputDialog

    before = np.array(win._pattern.intensity, copy=True)
    monkeypatch.setattr(QInputDialog, "getInt",
                        staticmethod(lambda *a, **k: (9, False)))
    win.controller.apply_smooth()
    assert win.controller.processed is None
    assert np.array_equal(before, win._pattern.intensity)

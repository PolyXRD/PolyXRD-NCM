"""峰列表面板与 CIF 面板测试（T6.2b 验收）。"""
from __future__ import annotations

import pytest

from ncm.core.peaks import ObservedPeak
from ncm.i18n import set_language


@pytest.fixture
def panel(qapp):
    from ncm.gui.peakpanel import PeakPanel

    return PeakPanel()


@pytest.fixture
def cif(qapp):
    from ncm.gui.cif_panel import CifPanel

    return CifPanel()


# --------------------------------------------------------------------------- #
# 峰列表面板
# --------------------------------------------------------------------------- #

def test_peak_panel_starts_empty(panel) -> None:
    assert panel.table.rowCount() == 0
    assert panel.table.columnCount() == 3, "只有 2θ / 强度 / 相对强度三列"


def test_peak_panel_sorts_by_two_theta(panel) -> None:
    peaks = [ObservedPeak(44.5, 100.0), ObservedPeak(18.8, 50.0),
             ObservedPeak(36.7, 80.0)]
    panel.set_peaks(peaks)
    tts = [float(panel.table.item(r, 0).text()) for r in range(3)]
    assert tts == sorted(tts)
    assert tts[0] == pytest.approx(18.8, abs=1e-6)


def test_peak_panel_relative_intensity_normalized(panel) -> None:
    peaks = [ObservedPeak(18.8, 250.0), ObservedPeak(44.5, 1000.0)]
    panel.set_peaks(peaks)
    rel = [float(panel.table.item(r, 2).text()) for r in range(2)]
    assert max(rel) == pytest.approx(1.0, abs=1e-6)
    assert rel[0] == pytest.approx(0.25, abs=1e-3)


def test_peak_panel_clear(panel) -> None:
    panel.set_peaks([ObservedPeak(18.8, 250.0)])
    assert panel.table.rowCount() == 1
    panel.set_peaks([])
    assert panel.table.rowCount() == 0


def test_peak_panel_csv_export(panel) -> None:
    panel.set_peaks([ObservedPeak(18.8, 250.0), ObservedPeak(44.5, 1000.0)])
    csv = panel.to_csv()
    lines = csv.strip().splitlines()
    assert len(lines) == 3, "CSV 应含表头 + 2 行"
    assert "18.8000" in lines[1]
    assert "44.5000" in lines[2]


def test_peak_panel_retranslate_headers(panel) -> None:
    set_language("en_US")
    panel.retranslate()
    hdr = [panel.table.horizontalHeaderItem(c).text()
           for c in range(panel.table.columnCount())]
    assert hdr == ["2θ (deg)", "Intensity (counts)", "I/I₀"]
    set_language("zh_CN")
    panel.retranslate()


# --------------------------------------------------------------------------- #
# CIF 面板
# --------------------------------------------------------------------------- #

def test_cif_panel_lists_builtin_structures(cif) -> None:
    assert cif.cif_list.count() == 14
    names = [cif.cif_list.item(i).text() for i in range(cif.cif_list.count())]
    assert "NCM811" in names
    assert "NCM523" in names
    assert "NCM622" in names


def test_cif_panel_current_name_and_select(cif) -> None:
    assert cif.current_name() is None
    assert cif.select("NCM811") is True
    assert cif.current_name() == "NCM811"
    assert cif.select("不存在的名字") is False


def test_cif_panel_import_signal(cif, qtbot=None) -> None:
    fired = []
    cif.import_requested.connect(lambda: fired.append(1))
    cif.btn_import_cif.click()
    assert fired


def test_cif_panel_identify_refine_disabled_until_wired(cif) -> None:
    assert not cif.btn_identify.isEnabled()
    assert not cif.btn_refine.isEnabled()
    cif.set_buttons_enabled(identify=True, refine=False)
    assert cif.btn_identify.isEnabled()
    assert not cif.btn_refine.isEnabled()


def test_cif_panel_retranslate(cif) -> None:
    set_language("en_US")
    cif.retranslate()
    assert cif.btn_refine.text() == "Start Refinement"
    set_language("zh_CN")
    cif.retranslate()
    assert cif.btn_refine.text() == "开始精修"


# --------------------------------------------------------------------------- #
# 主窗口集成
# --------------------------------------------------------------------------- #

def test_main_window_exposes_peak_dock(qapp) -> None:
    from ncm.gui.main_window import MainWindow

    w = MainWindow()
    assert w.peak_panel is not None
    assert w.dock_peaks is not None
    assert not w.dock_peaks.isVisible(), "寻峰停靠窗默认收起"
    assert w.cif_panel is not None
    assert w.current_structure() is None
    w.cif_panel.select("NCM811")
    st = w.current_structure()
    assert st is not None
    assert st.name == "NCM811"

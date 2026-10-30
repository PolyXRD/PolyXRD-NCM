"""主窗口骨架测试（T6.1c 验收）。

全部跑在 Qt **离屏**平台（conftest 的 `qapp` fixture）上，不弹窗。
"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.i18n import set_language


@pytest.fixture
def win(qapp):
    from ncm.gui.main_window import MainWindow

    w = MainWindow()
    yield w
    set_language("zh_CN")


def test_main_window_constructs(win) -> None:
    assert win.canvas is not None
    assert win.cif_list is not None
    assert win.windowTitle().startswith("PolyXRD NCM")


def test_layout_is_canvas_left_panel_right(win) -> None:
    """单窗口两栏：左谱图、右栏（CIF 面板 + 精修结果卡）。

    T6.4b 起右栏是一个容器：上方 CIF 面板、下方结果卡（T6.1c 时右栏
    只有 CIF 面板，断言相应更新）。
    """
    from PySide6.QtWidgets import QSplitter

    splitter = win.centralWidget()
    assert isinstance(splitter, QSplitter)
    assert splitter.count() == 2
    assert splitter.widget(0) is win.canvas
    right = splitter.widget(1)
    assert right is not None
    # 右栏容器里同时有 CIF 面板与结果卡
    assert win.cif_panel.parentWidget() is right
    assert win.result_card.parentWidget() is right


def test_builtin_cif_list_populated(win) -> None:
    """内置 CIF 列表应与 INDEX.json 条目数一致（14 份）。"""
    assert win.cif_list.count() == 14
    names = [win.cif_list.item(i).text() for i in range(win.cif_list.count())]
    assert "NCM811" in names
    assert "NCM622" in names
    assert "LiCoO2" in names


def test_menus_present(win) -> None:
    assert win.menu_file.title() == "文件(&F)"
    assert win.menu_process.title() == "处理(&P)"
    assert win.menu_language.title() == "语言(&L)"
    assert win.menu_help.title() == "帮助(&H)"


def test_process_actions_exist_but_disabled(win) -> None:
    """处理类动作已建好但尚未接线（T6.2 才启用）。"""
    assert set(win.act_process) == {"smooth", "background", "kalpha2",
                                    "peaks", "fit"}
    assert all(not a.isEnabled() for a in win.act_process.values())


def test_export_actions_disabled_until_t71(win) -> None:
    assert not win.act_export_png.isEnabled()
    assert not win.act_export_csv.isEnabled()
    assert not win.act_export_html.isEnabled()


def test_status_bar_three_fields(win) -> None:
    assert win.lbl_lang.text() == "语言：简体中文"
    assert win.lbl_file.text() == "就绪"
    assert win.lbl_identify.text() == "待判定"


def test_language_switch_updates_all_text(win) -> None:
    set_language("en_US")
    win.retranslateUi()
    assert win.menu_file.title() == "&File"
    assert win.lbl_lang.text() == "Language: English"
    assert win.btn_refine.text() == "Start Refinement"
    set_language("ja_JP")
    win.retranslateUi()
    assert win.menu_file.title() == "ファイル(&F)"
    set_language("zh_CN")
    win.retranslateUi()


def test_open_pattern_shows_on_canvas(win, sample_811, monkeypatch) -> None:
    """导入谱图后画布应出现曲线，状态栏显示文件路径。"""
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(sample_811), "")))
    win._on_open()
    assert win._pattern is not None
    assert win.canvas.ax_main.get_lines(), "导入后画布未画线"
    assert str(sample_811) in win.lbl_file.text()


def test_open_pattern_failure_shows_message(win, monkeypatch) -> None:
    """读谱失败应弹错误框而不是崩溃。"""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("D:/nonexistent.x.y", "")))
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(1))
    win._on_open()
    assert shown, "读谱失败未弹出错误提示"
    assert win._pattern is None


def test_smoke_entry_point_runs(qapp) -> None:
    """验收命令 `python -m ncm.gui --smoke` 的等价路径。"""
    from ncm.gui.__main__ import main

    assert main(["ncm.gui", "--smoke"]) == 0


def test_cif_list_tooltip_mentions_cod(win) -> None:
    """内置 CIF 来源说明必须写清楚（COD 原始 / 派生）。"""
    tip = win.cif_list.toolTip()
    assert "COD" in tip or "Crystallography" in tip


def test_canvas_starts_empty(win) -> None:
    assert not win.canvas.ax_main.get_lines()
    assert win.canvas.ax_diff is None
    assert np.asarray([]).size == 0

"""导出功能在 GUI 侧的集成测试（T7.1d）。

**核心判据**：导出动作**只在有精修结果时可用**，且导出的文件真的落盘、
内容正确。

覆盖：
- 导出动作初始禁用（还没精修）；
- 精修完成后导出动作启用；
- 换谱后导出动作重新禁用（旧结果不能导出）；
- 未精修时点导出 → 弹提示、不写文件；
- 各格式导出落盘且内容正确（PNG/SVG/CSV/TXT/HTML）；
- 导出后状态栏给出提示。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _no_modal_block():
    """★拦截所有模态对话框 —— 否则测试会**真阻塞**在 `exec()` 上。

    导出路径里若拿不到结果会弹 `QMessageBox`（模态），在无人值守的 CI 上
    就是永久挂起。这里统一 patch 掉 `exec`，把调用记下来供断言。
    """
    from PySide6.QtWidgets import QMessageBox

    shown = []
    original = QMessageBox.exec
    QMessageBox.exec = lambda self: shown.append(self) or 0
    yield shown
    QMessageBox.exec = original


@pytest.fixture
def win(qapp):
    from ncm.gui.main_window import MainWindow

    w = MainWindow()
    yield w


@pytest.fixture(scope="session")
def _pipeline_result():
    """跑一次合成谱的管线，**session 级缓存**（每个测试重跑要 7 s）。

    用**合成谱**而不是真实样：导出层只关心「有没有结果」与「文件内容
    自洽」，跑真实样要 90 s+（全量回归里跑不起）。
    """
    from ncm.core.dtypes import Pattern
    from ncm.core.pipeline import PipelineOptions, run_pipeline
    from ncm.core.profile.forward import ProfileParams, compute_phase_profile
    from ncm.core.solve import SolveOptions, builtin_structure

    st = builtin_structure("NCM811")
    prm = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                         anode="Cu")
    tt = np.arange(15.0, 45.0, 0.02)
    prof = compute_phase_profile(st, tt, prm, 15.0, 45.0)
    y = prof / prof.max() * 8000.0 + 50.0
    rng = np.random.default_rng(20261030)
    y = rng.poisson(y).astype(np.float64)
    pat = Pattern(two_theta=tt, intensity=y, meta={})
    result = run_pipeline(
        pat, st,
        PipelineOptions(stage1=SolveOptions(max_iter=2, refine_asym=False,
                                            refine_bfactor=False)))
    return pat, result


@pytest.fixture
def refined_win(qapp, _pipeline_result):
    """构造一个「已完成精修」的主窗口。"""
    from ncm.gui.main_window import MainWindow

    pat, result = _pipeline_result
    w = MainWindow()
    w._pattern = pat
    w._pattern_path = "synthetic.txt"
    w._on_refined(result)
    return w


def _patch_save(monkeypatch, target: Path):
    """把保存对话框固定到目标路径。"""
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    return target


# --------------------------------------------------------------------------- #
# 动作可用性
# --------------------------------------------------------------------------- #
def test_export_actions_disabled_before_refine(win) -> None:
    """还没精修 → 导出动作全部禁用。"""
    for key in ("png", "svg", "csv", "txt", "html"):
        act = getattr(win, f"act_export_{key}")
        assert not act.isEnabled(), f"{key} 导出在无结果时不应可用"


def test_export_actions_enabled_after_refine(refined_win) -> None:
    """精修完成 → 导出动作启用。"""
    for key in ("png", "svg", "csv", "txt", "html"):
        act = getattr(refined_win, f"act_export_{key}")
        assert act.isEnabled(), f"{key} 导出在有结果时不应可用"


def test_new_pattern_disables_export(refined_win, sample_811, monkeypatch) -> None:
    """换谱 → 旧结果作废 → 导出重新禁用。"""
    from ncm.gui import files

    monkeypatch.setattr(files, "choose_pattern",
                        lambda parent: str(sample_811))
    refined_win._on_open()
    assert not refined_win.act_export_png.isEnabled()


def test_export_without_result_shows_message(win, monkeypatch) -> None:
    """无结果时点导出 → 弹提示，不写文件。"""
    from PySide6.QtWidgets import QFileDialog

    called = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (called.append(1) or "x.png",
                                                      "")))
    win._on_export("png")
    assert _no_modal_block, "无结果时导出应弹提示"
    assert not called, "无结果时不该走到选文件那一步"


# --------------------------------------------------------------------------- #
# 各格式落盘
# --------------------------------------------------------------------------- #
def test_export_png_writes_file(refined_win, monkeypatch, tmp_path) -> None:
    out = _patch_save(monkeypatch, tmp_path / "r.png")
    refined_win._on_export("png")
    assert out.exists()
    assert out.stat().st_size > 5000
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_export_svg_writes_file(refined_win, monkeypatch, tmp_path) -> None:
    out = _patch_save(monkeypatch, tmp_path / "r.svg")
    refined_win._on_export("svg")
    assert out.exists()
    assert "<svg" in out.read_text(encoding="utf-8")


def test_export_csv_writes_file(refined_win, monkeypatch, tmp_path) -> None:
    out = _patch_save(monkeypatch, tmp_path / "p.csv")
    refined_win._on_export("csv")
    assert out.exists()
    text = out.read_text(encoding="utf-8-sig")
    assert "2theta_deg" in text
    assert text.count("\n") > 100


def test_export_txt_writes_file(refined_win, monkeypatch, tmp_path) -> None:
    out = _patch_save(monkeypatch, tmp_path / "c.txt")
    refined_win._on_export("txt")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Rwp" in text
    assert "晶胞" in text


def test_export_html_writes_file(refined_win, monkeypatch, tmp_path) -> None:
    out = _patch_save(monkeypatch, tmp_path / "r.html")
    refined_win._on_export("html")
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html, "HTML 报告应内嵌 SVG 图"
    assert "Rwp" in html


def test_export_appends_suffix_if_missing(refined_win, monkeypatch,
                                          tmp_path) -> None:
    """用户没写扩展名 → 自动补上（否则打开器认不出格式）。"""
    from PySide6.QtWidgets import QFileDialog

    target = tmp_path / "noext"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    refined_win._on_export("png")
    assert (tmp_path / "noext.png").exists()


def test_export_shows_status_message(refined_win, monkeypatch, tmp_path) -> None:
    """导出成功后状态栏给出提示。"""
    _patch_save(monkeypatch, tmp_path / "r.png")
    refined_win._on_export("png")
    assert "r.png" in refined_win.statusBar().currentMessage()


def test_cancel_save_writes_nothing(refined_win, monkeypatch, tmp_path) -> None:
    """用户在保存对话框点取消 → 不写文件。"""
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    refined_win._on_export("png")
    assert not list(tmp_path.glob("*.png"))

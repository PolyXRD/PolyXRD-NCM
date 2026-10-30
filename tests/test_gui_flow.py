"""判定对话框与流程编排测试（T6.3c 验收）。

**核心判据**（对应需求原文「不是的话停止后续操作，弹出对话框提示」）：
判定不通过 → 弹对话框 + **精修按钮保持禁用**；
判定通过 → 放行精修；精修期间「开始精修」禁用且「取消」按钮可见。
"""
from __future__ import annotations

import pytest

from ncm.core.identify import IdentifyResult
from ncm.i18n import set_language


@pytest.fixture
def win(qapp):
    from ncm.gui.main_window import MainWindow

    w = MainWindow()
    yield w
    set_language("zh_CN")


# --------------------------------------------------------------------------- #
# 判定对话框
# --------------------------------------------------------------------------- #

def test_dialog_pass_case(qapp) -> None:
    from ncm.gui.identify_dialog import IdentifyDialog

    res = IdentifyResult(ok=True, kind="ncm",
                         reasons=("峰位匹配良好",), metrics={"c1_rms": 0.005})
    dlg = IdentifyDialog(res)
    assert "判定通过" in dlg.windowTitle() or dlg.windowTitle()
    assert "峰位匹配良好" in dlg.toPlainText()
    assert "c1_rms" in dlg.toPlainText()
    assert dlg.btn_continue is None, "通过时不该给「仍按 NCM 精修」出口"


def test_dialog_fail_case_shows_kind(qapp) -> None:
    from ncm.gui.identify_dialog import IdentifyDialog

    res = IdentifyResult(ok=False, kind="other", reasons=("尖晶石特征",))
    dlg = IdentifyDialog(res)
    assert "other" in dlg._headline()
    assert dlg.btn_continue is None, "非 NCM 类型不该给继续出口"


def test_dialog_ncm_kind_offers_continue(qapp) -> None:
    """LiCoO₂ 这类：结构类型是 ncm 但判定不过 —— 给用户一个出口。"""
    from ncm.gui.identify_dialog import IdentifyDialog

    res = IdentifyResult(ok=False, kind="ncm", reasons=("晶胞不在 NCM 族内",))
    dlg = IdentifyDialog(res)
    assert dlg.btn_continue is not None, "ncm 类型应提供「仍按 NCM 精修」出口"
    assert dlg.continue_anyway is False
    dlg.btn_continue.click()
    assert dlg.continue_anyway is True


def test_dialog_precursor_has_no_continue(qapp) -> None:
    from ncm.gui.identify_dialog import IdentifyDialog

    res = IdentifyResult(ok=False, kind="precursor_hydroxide", reasons=("前驱体",))
    dlg = IdentifyDialog(res)
    assert dlg.btn_continue is None, "前驱体不是 NCM，不该给继续出口"


# --------------------------------------------------------------------------- #
# 流程编排
# --------------------------------------------------------------------------- #

def test_refine_blocked_before_identification(win, monkeypatch) -> None:
    """未判定就点精修 → 弹提示，不启动任务。"""
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(1))
    win._pattern = object()
    win._on_refine()
    assert shown, "未判定就精修应弹提示"
    assert win._refine_runner is None


def test_refine_blocked_without_cif(win, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(1))
    win._pattern = object()
    win._identify_passed = True
    win._on_refine()
    assert shown, "未选 CIF 应弹提示"
    assert win._refine_runner is None


def test_identified_pass_enables_refine(win) -> None:
    win._on_identified(IdentifyResult(ok=True, kind="ncm", reasons=("ok",)))
    assert win._identify_passed is True
    assert win.cif_panel.btn_refine.isEnabled()
    assert win.act_process["fit"].isEnabled()


def test_identified_fail_blocks_refine_and_shows_dialog(win, monkeypatch) -> None:
    """★判定不过 → 弹对话框 + 精修保持禁用。"""
    from ncm.gui.identify_dialog import IdentifyDialog

    seen = []
    monkeypatch.setattr(IdentifyDialog, "exec", lambda self: seen.append(self))
    win._on_identified(IdentifyResult(ok=False, kind="other", reasons=("不是 NCM",)))
    assert seen, "判定不过应弹对话框"
    assert win._identify_passed is False
    assert not win.cif_panel.btn_refine.isEnabled()
    assert not win.act_process["fit"].isEnabled()
    assert "other" in win.lbl_identify.text()


def test_identified_fail_with_continue_unlocks(win, monkeypatch) -> None:
    from ncm.gui.identify_dialog import IdentifyDialog

    def fake_exec(self):
        self.continue_anyway = True
        return 1

    monkeypatch.setattr(IdentifyDialog, "exec", fake_exec)
    win._on_identified(IdentifyResult(ok=False, kind="ncm", reasons=("晶胞越界",)))
    assert win._identify_passed is True
    assert win.cif_panel.btn_refine.isEnabled()


def test_set_refining_toggles_controls(win) -> None:
    """精修期间：开始精修禁用、取消按钮可见。"""
    win._identify_passed = True
    win.act_process["fit"].setEnabled(True)
    win._set_refining(True)
    assert not win.act_process["fit"].isEnabled()
    assert not win.cif_panel.btn_refine.isEnabled()
    assert not win.btn_cancel.isHidden(), "取消按钮应可见"
    win._set_refining(False)
    assert win.act_process["fit"].isEnabled()
    assert win.cif_panel.btn_refine.isEnabled()
    assert win.btn_cancel.isHidden()


def test_cancel_button_calls_runner_cancel(win) -> None:
    """点「取消」→ 转发给 runner 的 cancel()。"""
    calls = []

    class FakeRunner:
        def cancel(self):
            calls.append(1)

    win._refine_runner = FakeRunner()
    win._on_cancel_refine()
    assert calls == [1]
    assert not win.btn_cancel.isEnabled(), "取消后按钮应置灰，避免重复点"


def test_task_failure_restores_buttons(win, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(1))
    win._identify_passed = True
    win._set_refining(True)
    win._on_task_failed("boom")
    assert shown, "任务失败应弹窗"
    assert win.btn_cancel.isHidden()


def test_close_event_shuts_down_runners(win) -> None:
    calls = []

    class FakeRunner:
        def shutdown(self):
            calls.append(1)

    win._identify_runner = FakeRunner()
    win._refine_runner = FakeRunner()
    win.close()
    assert len(calls) == 2, "关闭时应收掉两个后台任务"

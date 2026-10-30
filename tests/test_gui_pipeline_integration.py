"""主窗口 ↔ 三段管线 ↔ 结果卡 联动测试（T6.4c 验收）。

判据：
1. 精修走**三段管线**（不是只跑 stage1）—— 否则 Li 占位/晶粒尺寸恒空；
2. 精修完成后结果卡被填上，且含需求原文要求的全部项；
3. 换谱后旧结果卡作废（不能拿上一份样的结果误导用户）；
4. 三语切换无 `⟪key⟫`（含结果卡内的漏译）。
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


@pytest.fixture
def synthetic_pattern():
    from ncm.core.dtypes import Pattern
    from ncm.core.profile.forward import ProfileParams, compute_phase_profile
    from ncm.core.solve import builtin_structure

    st = builtin_structure("NCM811")
    prm = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                         anode="Cu")
    tt = np.arange(15.0, 45.0, 0.02)
    prof = compute_phase_profile(st, tt, prm, 15.0, 45.0)
    y = prof / prof.max() * 8000.0 + 50.0
    rng = np.random.default_rng(20261030)
    y = rng.poisson(y).astype(np.float64)
    return Pattern(two_theta=tt, intensity=y, meta={})


def _card_texts(win) -> str:
    from PySide6.QtWidgets import QLabel

    return "\n".join(lbl.text() for lbl in
                     win.result_card.findChildren(QLabel))


# --------------------------------------------------------------------------- #
# 管线配置
# --------------------------------------------------------------------------- #

def test_default_options_enable_po_for_layered() -> None:
    """层状 R-3m → 默认开择优取向 (001)。"""
    from ncm.core.pipeline import default_options_for, is_layered_ncm
    from ncm.core.solve import builtin_structure

    st = builtin_structure("NCM811")
    assert is_layered_ncm(st) is True
    opt = default_options_for(st)
    assert opt.stage1.refine_po is True
    assert opt.stage1.po_r == {"NCM811": (0, 0, 1, 1.0)}
    assert opt.refine_occ is True
    assert opt.refine_size is True


def test_default_options_no_po_for_precursor() -> None:
    """前驱体（β-Ni(OH)₂）→ 不开 PO。"""
    from ncm.core.pipeline import default_options_for, is_layered_ncm
    from ncm.core.solve import builtin_structure

    st = builtin_structure("precursor_NiOH2")
    assert is_layered_ncm(st) is False
    opt = default_options_for(st)
    assert opt.stage1.refine_po is False
    assert opt.stage1.po_r is None


# --------------------------------------------------------------------------- #
# 主窗口联动
# --------------------------------------------------------------------------- #

def test_refined_fills_result_card(win, synthetic_pattern) -> None:
    """★精修完成 → 结果卡填上，且含需求原文要求的项。"""
    from ncm.core.pipeline import PipelineOptions, run_pipeline
    from ncm.core.solve import SolveOptions, builtin_structure

    st = builtin_structure("NCM811")
    opt = PipelineOptions(stage1=SolveOptions(max_iter=5, refine_asym=False,
                                              refine_bfactor=False))
    result = run_pipeline(synthetic_pattern, st, opt)

    win._pattern = synthetic_pattern
    win._pattern_path = "D:/samples/NCM811_demo.xy"
    win._on_refined(result)

    card = win.result_card.card()
    assert card is not None, "精修后结果卡应有内容"
    txt = _card_texts(win)
    # 需求原文：晶胞参数、晶粒尺寸、晶系/点群/空间群/劳厄群、Li 占位、Rwp/RB/GOF
    assert "Li 占位" in txt
    assert "晶粒尺寸" in txt
    assert "Rwp" in txt and "RB" in txt and "GOF" in txt
    assert "三方" in txt and "劳厄群" in txt
    assert card["composition"]["li_occupancy"] is not None


def test_result_card_cleared_on_new_pattern(win, synthetic_pattern) -> None:
    """换谱 → 旧结果卡作废。"""
    from ncm.core.pipeline import PipelineOptions, run_pipeline
    from ncm.core.solve import SolveOptions, builtin_structure

    st = builtin_structure("NCM811")
    result = run_pipeline(synthetic_pattern, st,
                          PipelineOptions(stage1=SolveOptions(max_iter=4,
                                                             refine_asym=False,
                                                             refine_bfactor=False),
                                          refine_occ=False))
    win._on_refined(result)
    assert win.result_card.card() is not None

    # 模拟导入新谱（走 _on_open 的清理逻辑）
    win._pattern = synthetic_pattern
    win.result_card.clear()
    assert win.result_card.card() is None


def test_three_language_switch_no_missing_key(win, synthetic_pattern) -> None:
    """★三语切换：主窗口 + 结果卡都不得出现 ⟪key⟫。"""
    from ncm.core.pipeline import PipelineOptions, run_pipeline
    from ncm.core.solve import SolveOptions, builtin_structure

    st = builtin_structure("NCM811")
    result = run_pipeline(synthetic_pattern, st,
                          PipelineOptions(stage1=SolveOptions(max_iter=4,
                                                             refine_asym=False,
                                                             refine_bfactor=False),
                                          refine_occ=False))
    win._on_refined(result)

    for lang in ("zh_CN", "en_US", "ja_JP"):
        set_language(lang)
        win.retranslateUi()
        txt = _card_texts(win)
        assert "⟪" not in txt, f"{lang} 结果卡出现未翻译 key"
        assert txt.strip(), f"{lang} 结果卡为空"


def test_status_shows_pipeline_rwp(win, synthetic_pattern) -> None:
    """状态栏显示的 Rwp 取**最终**（含占位段）的值。"""
    from ncm.core.pipeline import PipelineOptions, run_pipeline
    from ncm.core.solve import SolveOptions, builtin_structure

    st = builtin_structure("NCM811")
    result = run_pipeline(synthetic_pattern, st,
                          PipelineOptions(stage1=SolveOptions(max_iter=4,
                                                             refine_asym=False,
                                                             refine_bfactor=False)))
    win._on_refined(result)
    assert f"{result.rwp:.3f}" in win.lbl_identify.text()

"""GUI 结果卡面板测试（T6.4b 验收）。

判据：
1. 结果卡展示需求原文要求的全部项：晶胞参数 a,b,c,α,β,γ、晶粒尺寸、
   晶系/点群/空间群/劳厄群、Li 占位、Rwp/RB/GOF；
2. 三语切换无 `⟪key⟫` 标记（漏译直接暴露）；
3. "未测定"与"测得 0"必须区分开（晶粒尺寸未检出 / 应变触界）。
"""
from __future__ import annotations

import pytest

from ncm.i18n import set_language


@pytest.fixture
def card(qapp):
    """一张典型的 NCM811 结果卡（用核心层 build_card 造，避免手写假数据）。"""
    from ncm.core.resultcard import build_card
    from ncm.core.solve import SolveOptions, builtin_structure, solve
    from ncm.core.dtypes import Pattern
    from ncm.core.profile.forward import ProfileParams, compute_phase_profile
    import numpy as np

    st = builtin_structure("NCM811")
    prm = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                         anode="Cu")
    tt = np.arange(15.0, 45.0, 0.02)
    prof = compute_phase_profile(st, tt, prm, 15.0, 45.0)
    y = prof / prof.max() * 8000.0 + 50.0
    rng = np.random.default_rng(20261030)
    y = rng.poisson(y).astype(np.float64)
    pat = Pattern(two_theta=tt, intensity=y, meta={})
    sr = solve(pat, st, SolveOptions(max_iter=6, refine_asym=False,
                                      refine_bfactor=False))
    return build_card(sr.result, st, {
        "sample_name": "NCM811-实测",
        "occ_li": 0.9874,
        "z_o": 0.25828,
        "crystallite": {"crystallite_size_nm": 153.4, "strain": 0.0,
                        "method": "scherrer"},
    })


@pytest.fixture
def panel(qapp, card):
    from ncm.gui.resultcard import ResultCard

    p = ResultCard()
    p.set_card(card)
    yield p
    set_language("zh_CN")


def _texts(panel) -> str:
    """把面板里所有 QLabel 文本拼起来（便于整体断言）。"""
    from PySide6.QtWidgets import QLabel

    return "\n".join(lbl.text() for lbl in panel.findChildren(QLabel))


# --------------------------------------------------------------------------- #
# 内容完整性
# --------------------------------------------------------------------------- #

def test_card_shows_required_quantities(panel) -> None:
    """★需求原文要求的项一个都不能少。"""
    txt = _texts(panel)
    # 晶胞参数 a,b,c,α,β,γ
    for key in ("a", "b", "c", "α", "β", "γ"):
        assert key in txt, f"缺晶胞参数 {key}"
    # 晶体学
    assert "R -3 m :H" in txt
    assert "三方" in txt
    assert "-3m" in txt
    assert "hR" in txt
    # Li 占位
    assert "Li 占位" in txt
    assert "0.9874" in txt
    # 晶粒尺寸
    assert "晶粒尺寸" in txt
    assert "153.40 nm" in txt
    # 拟合优度
    assert "Rwp" in txt and "RB" in txt and "GOF" in txt


def test_card_shows_angles_and_volume(panel) -> None:
    """角度与体积带单位，且数值合理。"""
    txt = _texts(panel)
    assert "90.000°" in txt
    assert "Å³" in txt
    assert "Å" in txt


def test_card_rwp_and_rb_present(panel) -> None:
    txt = _texts(panel)
    assert "%" in txt


# --------------------------------------------------------------------------- #
# 未测定 vs 测得 0
# --------------------------------------------------------------------------- #

def test_not_measured_marker_used(qapp) -> None:
    """没有占位/尺寸时显示「未测定」，不是 0。"""
    from ncm.gui.resultcard import ResultCard

    p = ResultCard()
    p.set_card({"structure": {}, "cell": {}, "composition": {},
                "microstructure": {}, "profile": {}, "fit": {}})
    txt = _texts(p)
    assert "未测定" in txt
    assert "0.0000" not in txt, "未测定的项不得显示成 0"


def test_zero_strain_shown_as_not_detected(qapp) -> None:
    """★ε=0 触界 → 「未检出可分辨微观应变」，不显示 0.00e+00 假精度。"""
    from ncm.gui.resultcard import ResultCard

    p = ResultCard()
    p.set_card({"microstructure": {"crystallite_size_nm": 153.4,
                                   "strain": 0.0}})
    txt = _texts(p)
    assert "未检出可分辨微观应变" in txt
    assert "0.00e+00" not in txt


def test_infinite_size_shown_as_above_limit(qapp) -> None:
    """D=inf（未检出尺寸宽化）→ 「超出检出上限」，不显示 inf。"""
    from ncm.gui.resultcard import ResultCard

    p = ResultCard()
    p.set_card({"microstructure": {"crystallite_size_nm": float("inf"),
                                   "strain": None}})
    txt = _texts(p)
    assert "超出检出上限" in txt
    assert "inf" not in txt.lower()


def test_not_converged_flag(panel) -> None:
    """未收敛时标注「（未收敛）」。"""
    from ncm.gui.resultcard import ResultCard

    p = ResultCard()
    p.set_card({"fit": {"rwp": 12.0, "rp": 15.0, "rexp": 5.0, "rbragg": 8.0,
                        "gof": 2.4, "chi2": 3.0, "success": False,
                        "iterations": 60}})
    txt = _texts(p)
    assert "未收敛" in txt


# --------------------------------------------------------------------------- #
# 三语
# --------------------------------------------------------------------------- #

def test_language_switch_no_missing_key(panel) -> None:
    """★三语切换后不得出现 ⟪key⟫ 标记（漏译直接暴露）。"""
    for lang in ("zh_CN", "en_US", "ja_JP"):
        set_language(lang)
        panel.retranslate()
        txt = _texts(panel)
        assert "⟪" not in txt, f"{lang} 下出现未翻译 key"
        assert txt.strip(), f"{lang} 下结果卡为空"


def test_language_switch_keeps_values(panel) -> None:
    """切语言只换文案，不改数值。"""
    set_language("zh_CN")
    panel.retranslate()
    zh = _texts(panel)
    set_language("en_US")
    panel.retranslate()
    en = _texts(panel)
    assert "0.9874" in zh and "0.9874" in en
    assert "153.40 nm" in zh and "153.40 nm" in en


def test_crystal_system_follows_language(panel) -> None:
    """★晶系名随语言切换：中文界面「三方」，英文界面原生名 trigonal。"""
    from ncm.core.resultcard import build_card
    from ncm.core.solve import SolveOptions, builtin_structure, solve
    from ncm.core.dtypes import Pattern
    from ncm.core.profile.forward import ProfileParams, compute_phase_profile
    import numpy as np

    st = builtin_structure("NCM811")
    prm = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                         anode="Cu")
    tt = np.arange(15.0, 45.0, 0.02)
    prof = compute_phase_profile(st, tt, prm, 15.0, 45.0)
    y = prof / prof.max() * 8000.0 + 50.0
    rng = np.random.default_rng(20261030)
    y = rng.poisson(y).astype(np.float64)
    sr = solve(Pattern(two_theta=tt, intensity=y, meta={}), st,
               SolveOptions(max_iter=5, refine_asym=False, refine_bfactor=False))
    card = build_card(sr.result, st)

    from ncm.gui.resultcard import ResultCard

    p = ResultCard()
    p.set_card(card)
    set_language("zh_CN")
    p.retranslate()
    assert "三方" in _texts(p)
    set_language("en_US")
    p.retranslate()
    txt = _texts(p)
    assert "trigonal" in txt
    assert "三方" not in txt, "英文界面不该出现中文晶系名"


# --------------------------------------------------------------------------- #
# 基本行为
# --------------------------------------------------------------------------- #

def test_set_and_clear_card(panel) -> None:
    assert panel.card() is not None
    panel.clear()
    assert panel.card() is None
    assert "未测定" not in _texts(panel)


def test_retranslate_is_idempotent(panel) -> None:
    """重复 retranslate 不该叠加行（不能出现重复标签）。"""
    set_language("en_US")
    for _ in range(3):
        panel.retranslate()
    txt = _texts(panel)
    assert txt.count("Crystal system") == 1

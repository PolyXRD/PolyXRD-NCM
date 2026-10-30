"""晶粒尺寸/应变反演测试（T2.2 验收）。

核心判据（任务卡）：合成数据往返误差 ≤ 5% ——
用已知 (D, ε, U/V/W) 正向生成逐峰 FWHM，喂给 Williamson–Hall，
D 与 ε 都必须复原。
"""
from __future__ import annotations

import math

import pytest

from ncm.core.crystallite import (
    CrystalliteResult,
    from_tch,
    williamson_hall,
    _sample_lorentz_from_observed,
)
from ncm.core.profile.size_strain import (
    fwhm_gaussian,
    fwhm_lorentz,
    split_fwhm,
    tch_combine,
    x_from_strain,
    y_from_size,
)

LAM = 1.54056          # Cu Kα1, Å
UVW = (0.02, -0.01, 0.008)   # 与 DEFAULT_PRM 同量级的仪器项
#: 类 NCM 主峰位（只取 θ 参与 W-H，位置本身无需对应真实 hkl）
PEAKS_2TH = (18.9, 36.7, 38.5, 44.6, 49.3, 58.7, 64.9, 68.5, 78.6)


def _synthetic_peaks(D: float, eps: float):
    """正向生成：已知 D(nm)/ε 下的逐峰观测 FWHM（TCH 合成，含仪器项）。"""
    U, V, W = UVW
    X = x_from_strain(eps)
    Y = y_from_size(D * 10.0, LAM)   # nm -> Å（y_from_size 口径是 Å）
    out = []
    for tt in PEAKS_2TH:
        fg = fwhm_gaussian(tt, U, V, W)
        fl = fwhm_lorentz(tt, X, Y)
        out.append((tt, tch_combine(fg, fl)))
    return out


# ---------------------------------------------------------------------------
# 路径 1：Scherrer 直反演
# ---------------------------------------------------------------------------
def test_from_tch_roundtrip() -> None:
    for d_nm in (20.0, 85.0, 300.0):
        y = y_from_size(d_nm * 10.0, LAM)     # Å -> Y(度)
        r = from_tch(y, 0.0, LAM)
        assert r.D_nm == pytest.approx(d_nm, rel=1e-9)
        assert r.method == "scherrer"
        assert r.r2 is None
        assert r.strain == 0.0


def test_from_tch_strain() -> None:
    r = from_tch(0.05, x_from_strain(1.5e-3), LAM)
    assert r.strain == pytest.approx(1.5e-3, rel=1e-9)


def test_from_tch_no_size_term_is_inf() -> None:
    r = from_tch(0.0, 0.0, LAM)
    assert math.isinf(r.D_nm)


def test_as_dict_handles_inf() -> None:
    r = from_tch(0.0, 0.0, LAM).as_dict()
    assert math.isinf(r["D_nm"])
    r2 = from_tch(y_from_size(1200.0, LAM), 0.0, LAM).as_dict()   # 1200 Å = 120 nm
    assert r2["D_nm"] == pytest.approx(120.0, abs=0.01)
    assert r2["r2"] is None


# ---------------------------------------------------------------------------
# TCH 逆解（二分法）
# ---------------------------------------------------------------------------
def test_invert_tch_roundtrip() -> None:
    U, V, W = UVW
    for tt in PEAKS_2TH:
        fg = fwhm_gaussian(tt, U, V, W)
        for fl_true in (0.01, 0.05, 0.15):
            obs = tch_combine(fg, fl_true)
            fl_rec = _sample_lorentz_from_observed(obs, fg)
            assert fl_rec == pytest.approx(fl_true, rel=2e-3), (tt, fl_true)


def test_invert_tch_no_excess_returns_zero() -> None:
    """观测不比仪器宽 -> 样品洛伦兹 = 0（不产生虚假宽化）。"""
    fg = fwhm_gaussian(40.0, *UVW)
    assert _sample_lorentz_from_observed(fg * 0.999, fg) == 0.0
    assert _sample_lorentz_from_observed(fg + 5e-8, fg) == 0.0


# ---------------------------------------------------------------------------
# 路径 2：Williamson–Hall 合成往返（任务卡硬判据 ≤5%）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("D,eps", [
    (40.0, 0.0),
    (100.0, 0.0),
    (150.0, 1.0e-3),
    (60.0, 2.0e-3),
    (250.0, 5.0e-4),
])
def test_wh_synthetic_roundtrip(D: float, eps: float) -> None:
    peaks = _synthetic_peaks(D, eps)
    r = williamson_hall(peaks, *UVW, LAM)
    assert r.method == "williamson-hall"
    assert r.n_peaks == len(PEAKS_2TH)
    assert r.D_nm == pytest.approx(D, rel=0.05), f"D: {r.D_nm} vs {D}"
    if eps == 0.0:
        assert r.strain < 2e-4          # 无应变时不得虚报
    else:
        assert r.strain == pytest.approx(eps, rel=0.10)
    assert r.r2 is not None and r.r2 > 0.99


def _synthetic_peaks_eps_only(eps: float):
    """正向生成：纯应变（Y=0）的逐峰观测 FWHM。"""
    U, V, W = UVW
    X = x_from_strain(eps)
    return [(tt, tch_combine(fwhm_gaussian(tt, U, V, W),
                             fwhm_lorentz(tt, X, 0.0)))
            for tt in PEAKS_2TH]


def test_wh_pure_strain() -> None:
    """只有应变无尺寸：截距 ~0 -> D=inf，应变照常恢复。"""
    peaks = _synthetic_peaks_eps_only(1.5e-3)
    r = williamson_hall(peaks, *UVW, LAM)
    assert math.isinf(r.D_nm)
    assert r.strain == pytest.approx(1.5e-3, rel=0.10)
    assert r.r2 is not None and r.r2 > 0.99


def test_detect_ceiling() -> None:
    """D 超出 5 μm 检出上限 -> 统一报 inf（两条路径口径一致）。"""
    assert math.isinf(from_tch(y_from_size(1e7, LAM), 0.0, LAM).D_nm)  # 1 μm... 1e7 Å=1 mm 级
    peaks = _synthetic_peaks(1e4, 0.0)   # 10 μm
    assert math.isinf(williamson_hall(peaks, *UVW, LAM).D_nm)


# ---------------------------------------------------------------------------
# 边界与契约
# ---------------------------------------------------------------------------
def test_wh_requires_three_peaks() -> None:
    with pytest.raises(ValueError, match="3"):
        williamson_hall([(30.0, 0.1), (40.0, 0.1)], *UVW, LAM)


def test_wh_rejects_bad_fwhm() -> None:
    with pytest.raises(ValueError, match="FWHM"):
        williamson_hall([(30.0, 0.1), (40.0, -0.1), (50.0, 0.1)], *UVW, LAM)


def test_wh_degenerate_positions() -> None:
    with pytest.raises(ValueError, match="退化"):
        williamson_hall([(30.0, 0.1), (30.0001, 0.1), (30.0002, 0.1)],
                        *UVW, LAM)


def test_dataclass_contract() -> None:
    """T2.2 契约字段：D_nm / strain / method / r2 必须齐全。"""
    fields = {f.name for f in CrystalliteResult.__dataclass_fields__.values()}
    assert {"D_nm", "strain", "method", "r2"} <= fields

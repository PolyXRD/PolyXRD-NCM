"""Bragg R 因子测试（T4.1 验收）。

判据：合成谱 RB 与解析真值一致（完全匹配 -> 0；整体放大 k 倍 -> (k−1)/k）。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from ncm.core.refine.rbragg import (
    BraggRResult,
    bragg_r_factor,
    collect_peaks,
    profile_fwhm,
)

FWHM = 0.15
PEAKS = [(20.0, 100.0), (30.0, 50.0), (40.0, 20.0)]
GRID = np.arange(10.0, 60.0, 0.01)
BG = 10.0


def _net(grid: np.ndarray) -> np.ndarray:
    out = np.zeros_like(grid)
    for pos, w in PEAKS:
        out += w * np.exp(-4.0 * math.log(2.0) * ((grid - pos) / FWHM) ** 2)
    return out


def _fwhm(pos: float) -> float:
    return FWHM


def test_rb_zero_for_exact_match() -> None:
    net = _net(GRID)
    y = BG + net
    res = bragg_r_factor(GRID, y, y, np.full_like(GRID, BG), PEAKS, _fwhm)
    assert res.rbragg == pytest.approx(0.0, abs=1e-9)
    assert res.n_peaks == len(PEAKS)


def test_rb_matches_analytic_scale_error() -> None:
    """实测整体放大 1.1 倍 -> RB = (1.1−1)/1.1 = 9.0909%。"""
    net = _net(GRID)
    y_calc = BG + net
    y_obs = BG + 1.1 * net
    res = bragg_r_factor(GRID, y_obs, y_calc, np.full_like(GRID, BG),
                         PEAKS, _fwhm)
    assert res.rbragg == pytest.approx(100.0 * 0.1 / 1.1, rel=1e-6)


def test_rb_detects_peak_shift() -> None:
    """单峰位移必须被 RB 抓到（非零）：归属权重取自模型形状，实测峰偏离
    窗口后该峰的实测积分不足。"""
    net = _net(GRID)
    y_calc = BG + net
    shifted = np.zeros_like(GRID)
    for pos, w in PEAKS:
        p = pos + (0.2 if pos == 30.0 else 0.0)
        shifted += w * np.exp(-4.0 * math.log(2.0) * ((GRID - p) / FWHM) ** 2)
    res = bragg_r_factor(GRID, BG + shifted, y_calc, np.full_like(GRID, BG),
                         PEAKS, _fwhm)
    assert res.rbragg > 1.0


def test_rb_detects_single_peak_intensity_error() -> None:
    """只有中间峰强度错 20% -> RB 反映部分误差（小于整体 20%）。"""
    net = _net(GRID)
    y_calc = BG + net
    y_obs = BG + net.copy()
    m = np.abs(GRID - 30.0) < 1.0
    y_obs[m] *= 1.2
    res = bragg_r_factor(GRID, y_obs, y_calc, np.full_like(GRID, BG),
                         PEAKS, _fwhm)
    assert 0.5 < res.rbragg < 20.0


def test_rb_overlap_assignment_by_contribution() -> None:
    """重叠峰按计算贡献分配：权重大的峰拿走归属点。"""
    # 两个峰几乎重合，权重 100 vs 10
    peaks = [(25.0, 100.0), (25.05, 10.0)]
    net = np.zeros_like(GRID)
    for pos, w in peaks:
        net += w * np.exp(-4.0 * math.log(2.0) * ((GRID - pos) / FWHM) ** 2)
    y = BG + net
    res = bragg_r_factor(GRID, y, y, np.full_like(GRID, BG), peaks, _fwhm)
    # 归属后 ΣI_calc 不应超过总净强度（无重复计数）
    total = res.peaks[0][2] + res.peaks[1][2]
    assert total <= float(net.sum()) + 1e-6


def test_rb_empty_peaks() -> None:
    res = bragg_r_factor(GRID, GRID, GRID, np.zeros_like(GRID), [], _fwhm)
    assert res.rbragg == 0.0 and res.n_peaks == 0


def test_rb_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="等长"):
        bragg_r_factor(GRID, GRID[:-1], GRID, np.zeros_like(GRID), PEAKS, _fwhm)


def test_profile_fwhm_modes() -> None:
    """TCH 关闭 -> Caglioti；开启 -> 逐峰 TCH。"""
    from ncm.core.profile.forward import ProfileParams

    prm = ProfileParams(U=0.05, V=-0.04, W=0.017, eta=0.6, anode="Cu")
    f = profile_fwhm(prm)
    t = math.tan(math.radians(30.0) / 2)
    assert f(30.0) == pytest.approx(math.sqrt(0.05 * t * t - 0.04 * t + 0.017),
                                    rel=1e-9)
    prm_tch = ProfileParams(U=0.05, V=-0.04, W=0.017, eta=0.6, anode="Cu",
                            X=0.02, Y=0.05)
    f2 = profile_fwhm(prm_tch)
    assert f2(30.0) > f(30.0)      # 洛伦兹项使峰变宽


def test_collect_peaks_from_structure() -> None:
    from ncm.core.profile.forward import ProfileParams
    from ncm.core.solve import builtin_structure

    st = builtin_structure("NCM811")
    prm = ProfileParams(U=0.05, V=-0.04, W=0.017, eta=0.6, anode="Cu")
    pk = collect_peaks(st, prm, 12.0, 79.0)
    assert len(pk) > 5
    assert all(w > 0 for _p, w in pk)
    assert pk == sorted(pk, key=lambda t: t[0])


# ---------------------------------------------------------------------------
# 真实数据回归（T4.1 收尾验收）
#
# 锚点（python310 / Data040 NCM811 实样，standard_options）：
#   rwp=3.0409 rp=1.9787 rexp=1.4159 gof=2.1476 rbragg=4.6461
#
# 注意 RB > Rwp 是**实测事实**，不可断言 RB<Rwp：
#   RB 按逐峰积分强度算，不被背景点稀释；Rwp 是逐点加权平方残差，
#   背景点与峰间区的大量低强度点贡献小但拉低了加权残差均值。
#   本样品 (003) 峰吻合 0.02%，但 38° 区 (006)/(012) 模型高估 22–30%，
#   这部分结构级偏差在 RB 上体现得更明显。
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_solve(sample_811):
    """真实 NCM811 全谱精修（standard_options，用于 RB 回归）。"""
    from ncm.core.solve import (
        builtin_structure,
        load_sample,
        solve,
        standard_options,
    )

    return solve(load_sample(sample_811), builtin_structure("NCM811"),
                 standard_options())


def test_real_rb_is_filled_and_plausible(real_solve) -> None:
    """solve() 必须把 RB 填进 RFactors，且真实样落在合理窗口 0<RB<10%。"""
    rb = float(real_solve.result.rf.rbragg)
    assert rb > 0.0, "RB 未被填充或为 0（精修失败）"
    assert rb < 10.0, f"RB {rb:.4f}% 超合理上限 10%（精修质量异常）"


def test_real_rb_matches_frozen_anchor(real_solve) -> None:
    """RB 冻结锚点：口径或算法变动会立刻暴露（容差 ±0.5pp）。"""
    rb = float(real_solve.result.rf.rbragg)
    assert abs(rb - 4.6461) < 0.5, f"RB {rb:.4f}% 偏离冻结锚点 4.6461%"


def test_real_rb_recomputed_matches_pipeline(real_solve) -> None:
    """用公开接口独立重算 RB，必须与 solve() 内部填入值一致
    （验证 _with_bragg_r 的口径与 bragg_r_factor 本体没有分叉）。"""
    from ncm.core.profile.cif import CifStructure
    from ncm.core.refine.linear import background_basis
    from ncm.core.refine.rbragg import (
        bragg_r_factor,
        collect_peaks,
        profile_eta,
        profile_fwhm,
    )

    sr = real_solve
    res = sr.result
    fa, fc = res.cell_scales[0] if res.cell_scales else (1.0, 1.0)
    a, b, c, al, be, ga = sr.structure.cell
    scaled = CifStructure(sr.structure.name,
                          (a * fa, b * fa, c * fc, al, be, ga),
                          sr.structure.atoms)
    coeffs = np.asarray(res.bg, dtype=np.float64).ravel()
    bg = (background_basis(sr.pattern.two_theta, coeffs.size,
                           sr.options.bg_mode) @ coeffs
          if coeffs.size else np.zeros_like(sr.pattern.intensity))
    peaks = collect_peaks(scaled, res.params, sr.options.tmin, sr.options.tmax)
    rb = bragg_r_factor(sr.pattern.two_theta, sr.pattern.intensity, res.ycalc,
                        bg, peaks, profile_fwhm(res.params),
                        eta_func=profile_eta(res.params))
    assert rb.n_peaks > 0
    assert abs(rb.rbragg - float(res.rf.rbragg)) < 1e-9


def test_real_rb_peaks_are_ordered_and_consistent(real_solve) -> None:
    """逐峰明细表自洽：2θ 升序、实测/计算均为正、总和与总净强度同量级。"""
    from ncm.core.profile.cif import CifStructure
    from ncm.core.refine.linear import background_basis
    from ncm.core.refine.rbragg import (
        bragg_r_factor,
        collect_peaks,
        profile_eta,
        profile_fwhm,
    )

    sr = real_solve
    res = sr.result
    fa, fc = res.cell_scales[0] if res.cell_scales else (1.0, 1.0)
    a, b, c, al, be, ga = sr.structure.cell
    scaled = CifStructure(sr.structure.name,
                          (a * fa, b * fa, c * fc, al, be, ga),
                          sr.structure.atoms)
    coeffs = np.asarray(res.bg, dtype=np.float64).ravel()
    bg = (background_basis(sr.pattern.two_theta, coeffs.size,
                           sr.options.bg_mode) @ coeffs
          if coeffs.size else np.zeros_like(sr.pattern.intensity))
    peaks = collect_peaks(scaled, res.params, sr.options.tmin, sr.options.tmax)
    rb = bragg_r_factor(sr.pattern.two_theta, sr.pattern.intensity, res.ycalc,
                        bg, peaks, profile_fwhm(res.params),
                        eta_func=profile_eta(res.params))

    assert len(rb.peaks) == rb.n_peaks
    tt = [p[0] for p in rb.peaks]
    assert tt == sorted(tt), "逐峰明细未按 2θ 升序"
    assert all(p[1] > 0 for p in rb.peaks), "存在实测积分 <=0 的峰"
    assert all(p[2] > 0 for p in rb.peaks), "存在计算积分 <=0 的峰"
    # 归属后总积分不应超过实测净强度总量（不重复计数）
    step = float(np.median(np.diff(sr.pattern.two_theta)))
    net_total = float(np.sum((sr.pattern.intensity - bg) * step))
    assert sum(p[1] for p in rb.peaks) <= net_total + 1e-6

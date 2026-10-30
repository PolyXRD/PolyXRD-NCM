"""参数相关性矩阵测试（T3.2 验收）。"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.core.profile.cif import CifStructure
from ncm.core.profile.forward import ProfileParams, compute_phase_profile
from ncm.core.refine.corr import (
    CORR_WARN,
    CorrResult,
    corr_from_jacobian,
    occ_profile_correlations,
    pack_labels,
)
from ncm.core.refine.linear import solve_linear_detail
from ncm.core.refine.nonlinear import RefineConfig, RefineResult, _pack
from ncm.core.refine.occ import apply_occ_zo, identify_sites
from ncm.core.solve import builtin_structure, solve

PRM_SYN = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                        anode="Cu")


# ---------------------------------------------------------------------------
# 数学层：corr_from_jacobian
# ---------------------------------------------------------------------------
def test_corr_independent_params() -> None:
    """x0、x1 独立进入残差（不同数据段）-> |r| ≈ 0。"""
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([1.0, -1.0, 1.0, -1.0])

    def f(x):
        return np.concatenate([a * (x[0] - 1.0), b * (x[1] + 2.0)])

    J = np.zeros((8, 2))
    eps = 1e-6
    J[:, 0] = (f(np.array([1.0 + eps, -2.0])) - f(np.array([1.0 - eps, -2.0]))) / (2 * eps)
    J[:, 1] = (f(np.array([1.0, -2.0 + eps])) - f(np.array([1.0, -2.0 - eps]))) / (2 * eps)
    R = corr_from_jacobian(J)
    assert R[0, 0] == pytest.approx(1.0)
    assert R[1, 1] == pytest.approx(1.0)
    assert abs(R[0, 1]) < 1e-6


def test_corr_perfectly_correlated() -> None:
    """x1 = 2·x0 完全相关 -> r ≈ ±1。"""

    def f(x):
        return np.array([x[0] + 0.5 * x[1] - 3.0,
                         2.0 * x[0] + x[1] - 6.0])

    J = np.array([[1.0, 0.5], [2.0, 1.0]])
    R = corr_from_jacobian(J)
    assert abs(R[0, 1]) == pytest.approx(1.0, abs=1e-9)


def test_corr_singular_jacobian_no_crash() -> None:
    """奇异 H（全零列）不得崩溃，输出有限值。"""
    J = np.array([[1.0, 0.0], [2.0, 0.0], [1.0, 0.0]])
    R = corr_from_jacobian(J)
    assert np.all(np.isfinite(R))
    assert R[0, 0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 标签与 _pack 同序
# ---------------------------------------------------------------------------
def test_pack_labels_match_pack_order() -> None:
    cfg = RefineConfig(refine_zero=True, refine_uvw=True, refine_eta=True,
                       refine_asym=True, refine_bfactor=True, refine_cell=True,
                       refine_po=False, refine_strain=True, refine_size=True)
    from ncm.core.profile.forward import ProfileParams

    prm = ProfileParams(zero=0.01, U=0.02, V=-0.01, W=0.008, eta=0.6,
                        anode="Cu", asym=0.05, bfactor=0.3, X=0.01, Y=0.02)
    x = _pack(prm, cfg, n_phase=2)
    labels = pack_labels(cfg, n_phase=2, po_names=[])
    assert len(labels) == x.size
    assert labels[0] == "zero" and labels[-2:] == ("X", "Y")


# ---------------------------------------------------------------------------
# 集成：refine_corr=True 挂到 RefineResult
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mini_syn():
    """小窗口合成谱（快速集成用）。"""
    st = builtin_structure("NCM811")
    tt = np.arange(15.0, 45.0, 0.02)
    prof = compute_phase_profile(st, tt, PRM_SYN, 15.0, 45.0)
    y = prof / prof.max() * 8000.0 + 50.0
    from ncm.core.dtypes import Pattern

    return st, Pattern(two_theta=tt, intensity=y, meta={})


def test_refine_corr_attached(mini_syn) -> None:
    st, pat = mini_syn
    from ncm.core.solve import SolveOptions

    sr = solve(pat, st, SolveOptions(max_iter=8, refine_asym=False,
                                     refine_bfactor=False), refine_corr=True)
    corr = sr.result.correlation
    assert isinstance(corr, CorrResult)
    assert corr.matrix.shape == (len(corr.labels),) * 2
    np.testing.assert_allclose(np.diag(corr.matrix), 1.0, atol=1e-9)
    np.testing.assert_allclose(corr.matrix, corr.matrix.T, atol=1e-12)
    assert np.abs(corr.matrix).max() <= 1.0 + 1e-9
    assert "zero" in corr.labels and "bfactor" not in corr.labels


def test_refine_corr_default_none(mini_syn) -> None:
    """INV-3：默认关闭时字段为 None，既有流程零影响。"""
    st, pat = mini_syn
    from ncm.core.solve import SolveOptions

    sr = solve(pat, st, SolveOptions(max_iter=5, refine_asym=False,
                                     refine_bfactor=False))
    assert sr.result.correlation is None
    assert "correlation" in RefineResult.__dataclass_fields__


# ---------------------------------------------------------------------------
# 占位相关项：Li占位 ↔ bfactor / scale
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def occ_ctx():
    base = builtin_structure("NCM811")
    sites = identify_sites(base)
    st = apply_occ_zo(base, sites, 0.94, 0.245)
    tt = np.arange(12.0, 79.0, 0.02)
    prof = compute_phase_profile(st, tt, PRM_SYN, 12.0, 79.0)
    y = prof / prof.max() * 15000.0 + 120.0 * np.exp(-(tt - 12.0) / 30.0) + 25.0
    from ncm.core.dtypes import Pattern

    pat = Pattern(two_theta=tt, intensity=y, meta={})
    sig = np.sqrt(np.maximum(y, 1.0))
    row = compute_phase_profile(st, tt, PRM_SYN, 12.0, 79.0)
    row = row / row.max() * 15000.0
    _c, _yc, _d = solve_linear_detail(np.vstack([row]), tt, y, sig, 8, "cheb")
    from ncm.core.refine.linear import background_basis

    bg_coeffs = _c[1:]                   # coeffs = [S_1..S_P, b_0..]，单相 -> 背景从 1 起
    bg_curve = background_basis(tt, bg_coeffs.size, "cheb") @ bg_coeffs
    return base, sites, pat, st, bg_curve


def test_occ_profile_correlations(occ_ctx) -> None:
    base, sites, pat, st_true, bg_curve = occ_ctx
    corr = occ_profile_correlations(base, pat, PRM_SYN, sites,
                                    occ=0.94, zo=0.245, bg_curve=bg_curve)
    assert corr.labels == ("occ_Li", "z_O", "bfactor", "scale")
    np.testing.assert_allclose(np.diag(corr.matrix), 1.0, atol=1e-9)
    assert np.all(np.isfinite(corr.matrix))
    # occ↔z_O 物理近正交（弱敏感 vs (00l) 敏感），不得强相关
    assert abs(corr.matrix[0, 1]) < 0.9
    # 高相关对清单可用（结果卡出口）
    hp = corr.high_pairs()
    assert all(abs(r) >= CORR_WARN for _a, _b, r in hp)


def test_occ_profile_correlations_with_po(occ_ctx) -> None:
    base, sites, pat, st_true, bg_curve = occ_ctx
    corr = occ_profile_correlations(
        base, pat, PRM_SYN, sites, occ=0.94, zo=0.245, bg_curve=bg_curve,
        with_po=True, po_hkl=(0, 0, 1))
    assert "po_r[NCM811]" in corr.labels
    assert np.all(np.isfinite(corr.matrix))


def test_corr_result_api(occ_ctx) -> None:
    base, sites, pat, st_true, bg_curve = occ_ctx
    corr = occ_profile_correlations(base, pat, PRM_SYN, sites,
                                    occ=0.94, zo=0.245, bg_curve=bg_curve)
    ag = corr.against("occ_Li")
    assert set(ag) == {"z_O", "bfactor", "scale"}
    d = corr.as_dict()
    assert d["labels"] == list(corr.labels)

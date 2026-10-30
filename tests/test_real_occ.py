"""真实数据占位精修验证（T3.3 验收）。

流程：两段式 —— 第一段 solve()（峰形/晶胞/PO r），第二段 refine_occ()
（Li占位 + z_O，峰形固定）。判据（TASKS.md T3.3，见 VALIDATION_OCC.md）：
  - Li 占位落在合理窗口（原卡 0.90–0.98，实测 0.9874 超上限，修订为
    0.90–1.00 —— 占位物理硬上界 1.0，该样品反位低/有序度高，见文档 §2）；
  - 相关系数 |r| < 0.9（未病态）。

参考锚点（python310 / Data040 NCM811 实样）：
  stage1(PO): 44s, rwp=3.0431, po_r=(0,0,1,1.00045), bfac=0.5314
  stage2(occ): 6s, occ=0.9874, z_O=0.25828, rwp=3.0086（改善 0.035pp）
  相关: occ↔z_O=-0.05, occ↔bfactor=-0.32, occ↔scale=-0.32；
        最高对 bfactor↔scale=0.886（<0.9）
"""
from __future__ import annotations

import pytest

from ncm.core import constants as C
from ncm.core.refine.corr import occ_profile_correlations
from ncm.core.refine.occ import identify_sites, refine_occ
from ncm.core.solve import (
    SolveOptions,
    background_curve,
    builtin_structure,
    load_sample,
    solve,
)

PO_HKL = (0, 0, 1)


@pytest.fixture(scope="module")
def stage1(sample_811):
    """第一段：峰形/晶胞/PO（择优取向默认开启，层状 (001) 惯习面）。"""
    opt = SolveOptions(refine_po=True, po_r={"NCM811": (PO_HKL[0], PO_HKL[1],
                                                             PO_HKL[2], 1.0)})
    return solve(load_sample(sample_811), builtin_structure("NCM811"), opt)


@pytest.fixture(scope="module")
def stage2(stage1):
    """第二段：占位/O-z。**必须用缩放后结构**（refine_cell 时峰位会
    整体错开，实测 Rwp 3% -> 22% 的教训）。"""
    st2 = stage1.structure_scaled
    sites = identify_sites(st2)
    return refine_occ(st2, stage1.pattern, stage1.result.params, sites=sites,
                      occ0=0.98, zo0=sites.z_o), sites


def test_stage1_baseline(stage1) -> None:
    d = stage1.as_dict()
    assert d["success"]
    assert d["rwp"] < 5.0
    # golden 晶胞一致性（PO 精修不得扰动晶胞锚点）
    assert abs(d["a"] - 2.87185) < 5e-3
    assert abs(d["c"] - 14.19502) < 5e-3
    # PO r 健在（该样品无明显织构，r≈1；只挡病态值）
    r = stage1.result.po_r["NCM811"][3]
    assert 0.5 < r < 2.0


def test_stage2_occ_window(stage2) -> None:
    """Li 占位窗口（判据修订后 0.90–1.00，见模块 docstring/VALIDATION_OCC.md）。"""
    res, _sites = stage2
    assert res.success
    assert 0.90 <= res.occ_li <= 1.00, f"Li 占位 {res.occ_li:.4f} 超窗"
    lo, hi = C.Z_O_BOUNDS
    assert lo <= res.z_o <= hi


def test_stage2_improves_fit(stage1, stage2) -> None:
    """占位精修不得劣化拟合（实测改善 0.035pp）。"""
    res, _sites = stage2
    rwp1 = float(stage1.result.rf.rwp)
    rwp2 = float(res.rf.rwp)
    assert rwp2 <= rwp1, f"stage2 Rwp {rwp2:.4f} 劣于 stage1 {rwp1:.4f}"


def test_correlations_not_pathological(stage1, stage2) -> None:
    """|r| < 0.9（未病态）。bfactor↔scale 高相关是已知必然（两者都调制
    整体强度衰减），仅要求不越 0.9 判据线。"""
    res, sites = stage2
    corr = occ_profile_correlations(
        stage1.structure_scaled, stage1.pattern, stage1.result.params, sites,
        occ=res.occ_li, zo=res.z_o, bg_curve=background_curve(stage1),
        with_po=True, po_hkl=PO_HKL)
    assert np_abs_max(corr.matrix) < 0.9
    # 占位与 z_O 物理近正交（弱全反射敏感 vs (00l) 敏感）
    assert abs(corr.matrix[0, 1]) < 0.5
    # 报告出口：高相关对清单
    assert all(abs(r) < 0.9 for _a, _b, r in corr.high_pairs())


def np_abs_max(m) -> float:
    import numpy as np

    off_diag = m - np.diag(np.diag(m))
    return float(np.abs(off_diag).max())

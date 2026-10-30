"""位点识别与占位/O-z 精修测试（T3.1 验收）。

核心判据（任务卡）：合成谱 Li 占位 round-trip 误差 ≤ 0.03。
"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.core import constants as C
from ncm.core.profile.cif import CifStructure
from ncm.core.profile.forward import compute_phase_profile, ProfileParams
from ncm.core.refine.occ import (
    SiteModel,
    apply_occ_zo,
    identify_sites,
    refine_occ,
)
from ncm.core.solve import builtin_structure, solve


@pytest.fixture(scope="module")
def struct811():
    return builtin_structure("NCM811")


@pytest.fixture(scope="module")
def sites811(struct811):
    return identify_sites(struct811)


PRM_SYN = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                        anode="Cu")


# ---------------------------------------------------------------------------
# 位点识别
# ---------------------------------------------------------------------------
def test_identify_sites_ncm811(struct811, sites811) -> None:
    """Li 层位点 = 3 Li(0.98) + 3 反位 Ni(0.02)（全晶胞 6 原子）；
    TM 层位点 = (Ni0.75+Co0.10+Mn0.10+Li0.05)×3 = 12 原子；O = 6，z_O=0.259。"""
    a = sites811
    atoms = struct811.atoms
    assert len(a.li_layer) == 6
    assert len(a.tm_layer) == 12
    assert len(a.o_site) == 6
    assert sum(1 for i in a.li_layer if atoms[i][0] == "Li") == 3
    assert a.z_o == pytest.approx(0.259, abs=1e-4)
    # 位点口径：反位 Ni 的 share = 1.0（该元素独占互补位）
    assert all(v == pytest.approx(1.0) for v in a.share.values())


def test_li_layer_by_content_not_z(struct811, sites811) -> None:
    """3a/3b 陷阱回归：把 Li 层与 TM 层的 z 整体对调后，识别结果必须不变
    （仍按内容锁定 Li 占比最大的簇）。COD 1520789 是备用原点，Li 层在 z=0。"""
    atoms = list(struct811.atoms)
    li_idx, tm_idx = set(sites811.li_layer), set(sites811.tm_layer)
    new = []
    for i, at in enumerate(atoms):
        e, x, y, z, occ, B = at
        if i in li_idx:
            z = (z + 0.5) % 1.0        # Li 层簇挪到原 TM 层的 z
        elif i in tm_idx:
            z = (z + 0.5) % 1.0        # TM 层簇挪到原 Li 层的 z
        new.append((e, x, y, z, occ, B))
    swapped = CifStructure(struct811.name, struct811.cell, new)
    s2 = identify_sites(swapped)
    assert s2.li_layer == sites811.li_layer   # 同一批原子下标
    assert s2.tm_layer == sites811.tm_layer


def test_identify_rejects_no_li() -> None:
    """无 Li 位点（如氧化物杂质相）必须拒绝占位精修。"""
    fake = CifStructure("notncm", (2.9, 2.9, 4.5, 90, 90, 90), [
        ("Ni", 0.0, 0.0, 0.0, 1.0, 0.0),
        ("O", 0.0, 0.0, 0.5, 1.0, 0.0),
    ])
    with pytest.raises(ValueError, match="Li"):
        identify_sites(fake)


def test_identify_rejects_multi_o_site() -> None:
    """O 不符合单一 6c 参数模型时拒绝 z_O 精修。"""
    fake = CifStructure("twoO", (2.9, 2.9, 14.2, 90, 90, 120), [
        ("Li", 0.0, 0.0, 0.0, 1.0, 0.0),
        ("Ni", 0.0, 0.0, 0.5, 1.0, 0.0),
        ("O", 0.0, 0.0, 0.24, 1.0, 0.0),   # 两个独立 O 位点
        ("O", 0.5, 0.5, 0.31, 1.0, 0.0),
    ])
    with pytest.raises(ValueError, match="6c"):
        identify_sites(fake)


# ---------------------------------------------------------------------------
# 占位/z_O 施加
# ---------------------------------------------------------------------------
def test_apply_occ_zo_atom_level(struct811, sites811) -> None:
    st = apply_occ_zo(struct811, sites811, occ_li=0.92, z_o=0.242)
    li_occ = [st.atoms[i][4] for i in sites811.li_layer
              if st.atoms[i][0] == "Li"]
    ni_occ = [st.atoms[i][4] for i in sites811.li_layer
              if st.atoms[i][0] == "Ni"]
    assert li_occ == pytest.approx([0.92] * len(li_occ))
    assert ni_occ == pytest.approx([0.08] * len(ni_occ))   # 互补约束
    zs = sorted(st.atoms[i][3] for i in sites811.o_site)
    assert min(zs, key=lambda z: abs(z - 0.25)) == pytest.approx(0.242, abs=1e-6)
    # 原结构不可被修改（li_layer 首个 Li 原子保持 0.98）
    li0 = next(i for i in sites811.li_layer if struct811.atoms[i][0] == "Li")
    assert struct811.atoms[li0][4] == 0.98


def test_apply_identity_keeps_profile(struct811, sites811) -> None:
    """施加当前值（occ=0.98, z_O 不变）应得到相同的计算谱。

    注意不是逐位相同：(1−0.98) 的浮点表示与 CIF 里的字面 0.02 差 ~2e-17，
    传导到 |F|² 的差异在 1e-10 量级 —— 机器精度，物理恒等。"""
    grid = np.arange(15.0, 75.0, 0.02)
    st = apply_occ_zo(struct811, sites811, occ_li=0.98, z_o=sites811.z_o)
    p1 = compute_phase_profile(struct811, grid, PRM_SYN)
    p2 = compute_phase_profile(st, grid, PRM_SYN)
    np.testing.assert_allclose(p1, p2, rtol=0, atol=1e-8)


def test_apply_zo_branch_aware(struct811, sites811) -> None:
    """6c 分支定向回归：z_O=0.242 与 0.276 的计算谱必须**不同**
    （统一平移 bug 曾使 δ=±δ 伪简并、两者谱完全相同）。"""
    grid = np.arange(12.0, 79.0, 0.02)
    p1 = compute_phase_profile(apply_occ_zo(struct811, sites811, 0.92, 0.242),
                               grid, PRM_SYN, 12.0, 79.0)
    p2 = compute_phase_profile(apply_occ_zo(struct811, sites811, 0.92, 0.276),
                               grid, PRM_SYN, 12.0, 79.0)
    assert np.abs(p1 - p2).max() / p1.max() > 1e-3
    # 自洽性：施加后重新识别，z_O 应等于施加值
    st = apply_occ_zo(struct811, sites811, 0.92, 0.242)
    assert identify_sites(st).z_o == pytest.approx(0.242, abs=1e-6)


def test_apply_occ_rejects_out_of_bounds(struct811, sites811) -> None:
    with pytest.raises(ValueError, match="occ_li"):
        apply_occ_zo(struct811, sites811, occ_li=0.3)


def test_apply_occ_clamps_jacobian_overshoot(struct811, sites811) -> None:
    """LM 中心差分在边界处探测 x±1e-4 —— 微小越界必须钳位而非报错
    （真实数据首跑即在 occ=1.0 边界崩掉）。"""
    st = apply_occ_zo(struct811, sites811, occ_li=1.0001)
    li_occ = [st.atoms[i][4] for i in sites811.li_layer
              if st.atoms[i][0] == "Li"]
    assert li_occ == pytest.approx([1.0] * len(li_occ))
    with pytest.raises(ValueError, match="z_o"):
        apply_occ_zo(struct811, sites811, occ_li=0.9, z_o=0.30)


# ---------------------------------------------------------------------------
# 合成谱 round-trip（任务卡硬判据：occ 误差 ≤ 0.03）
# ---------------------------------------------------------------------------
OCC_TRUE = 0.92
ZO_TRUE = 0.242


@pytest.fixture(scope="module")
def synthetic(struct811, sites811):
    """已知 (occ, z_O) 的合成谱：真实结构 + 平滑背景 + Poisson 噪声。"""
    rng = np.random.default_rng(20261029)
    st = apply_occ_zo(struct811, sites811, OCC_TRUE, ZO_TRUE)
    tt = np.arange(12.0, 79.0, 0.02)
    prof = compute_phase_profile(st, tt, PRM_SYN, 12.0, 79.0)
    bg = 120.0 * np.exp(-(tt - 12.0) / 30.0) + 25.0
    y = prof / prof.max() * 15000.0 + bg
    y = rng.poisson(y).astype(np.float64)
    from ncm.core.dtypes import Pattern

    return Pattern(two_theta=tt, intensity=y, meta={"source": "synthetic"})


@pytest.fixture(scope="module")
def stage1(synthetic, struct811):
    """第一段：标准精修（峰形/晶胞），结构仍用**未施加真值**的起点。"""
    return solve(synthetic, struct811)


def test_occ_roundtrip(synthetic, struct811, sites811, stage1) -> None:
    """两段式合成往返：occ 误差 ≤ 0.03（任务卡），z_O 误差 ≤ 0.005。"""
    res = refine_occ(struct811, synthetic, stage1.result.params,
                     sites=sites811, occ0=0.98, zo0=sites811.z_o)
    assert res.occ_li == pytest.approx(OCC_TRUE, abs=0.03), (
        f"occ: {res.occ_li:.4f} vs {OCC_TRUE}")
    assert res.z_o == pytest.approx(ZO_TRUE, abs=0.005), (
        f"z_O: {res.z_o:.5f} vs {ZO_TRUE}")
    assert res.success


def test_occ_roundtrip_bounds_respected(synthetic, struct811, sites811,
                                        stage1) -> None:
    lo, hi = C.OCC_LI3A_BOUNDS
    zlo, zhi = C.Z_O_BOUNDS
    res = refine_occ(struct811, synthetic, stage1.result.params,
                     sites=sites811, occ0=0.6, zo0=0.21)   # 从边界附近出发
    assert lo <= res.occ_li <= hi
    assert zlo <= res.z_o <= zhi

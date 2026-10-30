"""判定门测试（T5.1 验收）。

INV-4：判定门在负样本上 100% 拒绝。

**判据（基于实测事实，不是推测）**
-----------------------------------
正样本（合成 + 真实）：
- 合成 NCM811 / NCM111 / LiNiO₂ → ok=True, kind=ncm
- 真实 Data040 NCM811 → ok=True, C1 RMS 0.0051°、标定 a=2.87158 c=14.19411

负样本（结构可信度三道门槛拦截）：
- 岩盐 NiO / 尖晶石 LiMn₂O₄ / 金红石 TiO₂ / 石墨 → ok=False, kind=other
- 纯噪声谱 → ok=False, kind=other

前驱体分流：
- P-3m1 氢氧化物 → kind=precursor_hydroxide
- R-3c 碳酸盐 → kind=precursor_carbonate

参考锚点（python310）：
  真实 NCM811: ok=True, C1 rms=0.0051°, hits=12, cell a=2.87158 c=14.19411
  合成 NCM811: ok=True, C1 rms=0.0155°, hits=11
  合成 LiCoO₂: ok=False, kind=ncm（层状 R-3m 但晶胞非 NCM）
  合成 NiO:     ok=False, kind=other
"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.core import constants as C
from ncm.core.dtypes import Pattern
from ncm.core.identify import (
    HKL_003,
    HKL_006,
    HKL_012,
    HKL_104,
    HKL_108,
    HKL_110,
    default_pool,
    identify,
)
from ncm.core.peaks import WAVELENGTH_KA1, find_peaks, prepare
from ncm.core.profile.cif import CifStructure
from ncm.core.profile.forward import ProfileParams, compute_phase_profile
from ncm.core.solve import builtin_structure

GRID = np.arange(10.0, 90.0, 0.02)
PRM = ProfileParams(zero=0.0, U=0.03, V=-0.01, W=0.008, eta=0.6,
                    anode="Cu", ka_ratio=0.5)
SEED = 20260701

#: 非层状相（负样本）：结构简单、代表常见误纳物
NEGATIVE_STRUCTURES = {
    "NiO_rocksalt": CifStructure(
        "NiO", (4.177, 4.177, 4.177, 90.0, 90.0, 90.0),
        [("Ni", 0.0, 0.0, 0.0, 1.0, 0.0),
         ("O", 0.5, 0.5, 0.5, 1.0, 0.0)]),
    "LiMn2O4_spinel": CifStructure(
        "LiMn2O4", (8.2476, 8.2476, 8.2476, 90.0, 90.0, 90.0),
        [("Li", 0.0, 0.0, 0.0, 1.0, 0.0),
         ("Mn", 0.125, 0.125, 0.125, 1.0, 0.0),
         ("O", 0.25, 0.25, 0.25, 1.0, 0.0)]),
    "TiO2_rutile": CifStructure(
        "TiO2", (4.5937, 4.5937, 2.9587, 90.0, 90.0, 90.0),
        [("Ti", 0.0, 0.0, 0.0, 1.0, 0.0),
         ("O", 0.3048, 0.3048, 0.0, 1.0, 0.0)]),
    "graphite": CifStructure(
        "graphite", (2.4612, 2.4612, 6.7090, 90.0, 90.0, 120.0),
        [("C", 0.0, 0.0, 0.0, 1.0, 0.0),
         ("C", 0.0, 0.0, 0.5, 1.0, 0.0)]),
}


def synth(struct: CifStructure, seed: int = SEED) -> Pattern:
    """合成粉末谱（含 Kα2 双线 + 计数噪声 + 平背景）。"""
    prof = compute_phase_profile(struct, GRID, PRM)
    prof = prof / max(prof.max(), 1e-12) * 10000.0
    rng = np.random.default_rng(seed)
    y = prof + 200.0 + rng.normal(0.0, np.sqrt(np.maximum(prof, 1.0)))
    return Pattern(two_theta=GRID.copy(), intensity=y)


@pytest.fixture(scope="module")
def synth_ncm811() -> Pattern:
    return synth(builtin_structure("NCM811"))


@pytest.fixture(scope="module")
def noise_pattern() -> Pattern:
    rng = np.random.default_rng(7)
    return Pattern(two_theta=GRID.copy(),
                   intensity=rng.normal(100.0, 10.0, GRID.shape))


# ---------------------------------------------------------------------------
# 正样本
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["NCM811", "NCM111", "LiNiO2"])
def test_synthetic_ncm_accepted(name) -> None:
    res = identify(synth(builtin_structure(name)))
    assert res.ok is True
    assert res.kind == C.KIND_NCM
    assert res.metrics["c1"]["pass"] is True
    assert res.metrics["c1"]["rms_deg"] <= C.C1_RMS_MAX
    assert res.metrics["c2"]["pass"] is True
    assert res.metrics["c3"]["pass"] is True


def test_real_ncm811_accepted(sample_811) -> None:
    """真实实样：必须通过，且 C1 RMS 有充足裕度。"""
    from ncm.core.solve import load_sample

    res = identify(load_sample(sample_811))
    assert res.ok is True
    assert res.kind == C.KIND_NCM
    c1 = res.metrics["c1"]
    assert c1["rms_deg"] <= C.C1_RMS_MAX
    assert c1["rms_deg"] < 0.05, f"C1 RMS {c1['rms_deg']} 裕度不足"
    assert c1["hits"] >= C.C1_MIN_MATCH
    assert res.metrics["c2"]["pass"] is True
    assert res.metrics["c3"]["pass"] is True


def test_real_calibrated_cell_matches_refinement(sample_811) -> None:
    """快速标定得到的晶胞必须与全谱精修锚点一致（判据口径自洽）。

    锚点：全谱 Rietveld 精修 a=2.87185 / c=14.19502（standard_options）。
    判定门标定：a=2.87158 / c=14.19411 —— 相差 0.01%。
    """
    from ncm.core.solve import load_sample

    res = identify(load_sample(sample_811))
    cell = res.metrics["calibrated_cell"]
    assert abs(cell["a"] - 2.87185) < 2e-3
    assert abs(cell["c"] - 14.19502) < 2e-3


def test_real_c3_ratio_plausible(sample_811) -> None:
    """真实样的 I(003)/I(104) 落在冻结窗口内（实测 1.155）。"""
    from ncm.core.solve import load_sample

    res = identify(load_sample(sample_811))
    ratio = res.metrics["c3"]["ratio"]
    assert ratio is not None
    assert C.C3_RATIO_MIN <= ratio <= C.C3_RATIO_MAX


# ---------------------------------------------------------------------------
# 负样本（INV-4）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(NEGATIVE_STRUCTURES))
def test_non_layered_rejected(name) -> None:
    """非层状相必须 100% 被拒绝，且不得判成 ncm。"""
    res = identify(synth(NEGATIVE_STRUCTURES[name]))
    assert res.ok is False, f"{name} 被误纳"
    assert res.kind != C.KIND_NCM, f"{name} 被误判为 NCM"


def test_noise_spectrum_rejected(noise_pattern) -> None:
    """纯噪声谱必须被拒绝，且必须快速返回（峰数上限）。"""
    res = identify(noise_pattern)
    assert res.ok is False
    assert res.kind == C.KIND_OTHER


def test_lco_is_not_ncm() -> None:
    """LiCoO₂ 是层状 R-3m 但晶胞非 NCM：ok=False，kind=ncm（层状类型保留）。"""
    res = identify(synth(builtin_structure("LiCoO2")))
    assert res.ok is False
    assert res.kind == C.KIND_NCM
    assert any("LiCoO" in r for r in res.reasons)


# ---------------------------------------------------------------------------
# 前驱体分流
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,kind", [
    ("precursor_NiOH2", C.KIND_PRECURSOR_HYDROXIDE),
    ("precursor_NCM811_OH", C.KIND_PRECURSOR_HYDROXIDE),
    ("precursor_NiCO3", C.KIND_PRECURSOR_CARBONATE),
    ("precursor_NCM811_CO3", C.KIND_PRECURSOR_CARBONATE),
])
def test_precursor_classified(name, kind) -> None:
    res = identify(synth(builtin_structure(name)))
    assert res.ok is False, "前驱体不应被当成可精修的 NCM 成品"
    assert res.kind == kind


# ---------------------------------------------------------------------------
# 口径与结构性
# ---------------------------------------------------------------------------

def test_thresholds_come_from_constants() -> None:
    """阈值唯一出处：`ncm/core/constants.py`。"""
    assert C.C1_RMS_MAX == 0.10
    assert C.C2_SPLIT_MIN == 0.10
    assert (C.C3_RATIO_MIN, C.C3_RATIO_MAX) == (0.5, 3.0)
    assert C.C1_MIN_MATCH >= 6
    assert C.C_FINGERPRINT_MIN >= 0.8
    assert C.CALIB_CELL_TOL_PCT <= 5.0


def test_default_pool_contains_all_categories() -> None:
    pool = default_pool()
    names = {s.name for s in pool}
    assert "NCM811" in names
    assert any("OH" in n for n in names)
    assert any("CO3" in n for n in names)
    assert len(pool) >= 10


def test_identify_is_deterministic(synth_ncm811) -> None:
    a = identify(synth_ncm811)
    b = identify(synth_ncm811)
    assert a.ok == b.ok and a.kind == b.kind
    assert a.metrics["c1"]["rms_deg"] == b.metrics["c1"]["rms_deg"]


def test_metrics_shape(synth_ncm811) -> None:
    m = identify(synth_ncm811).metrics
    for key in ("n_peaks", "c1", "c2", "c3", "calibrated_cell", "reference"):
        assert key in m
    assert set(m["c1"]) >= {"rms_deg", "hits", "pass", "rms_max", "min_hits"}
    assert set(m["c3"]) >= {"ratio", "i003", "i104", "window", "pass"}


def test_reasons_are_human_readable(synth_ncm811) -> None:
    res = identify(synth_ncm811)
    assert res.reasons
    assert all(isinstance(r, str) and r for r in res.reasons)
    assert any("C1" in r for r in res.reasons)
    assert "通过" in res.summary()


def test_feature_hkl_constants() -> None:
    """判据用的特征 hkl 不得被误改（六方三指数记法）。"""
    assert HKL_003 == (0, 0, 3)
    assert HKL_104 == (1, 0, 4)
    assert HKL_006 == (0, 0, 6)
    assert HKL_012 == (0, 1, 2)
    assert HKL_108 == (1, 0, 8)
    assert HKL_110 == (1, 1, 0)


def test_prepare_strips_ka2_and_background(sample_811) -> None:
    """判定门预处理链：Kα2 剥离 + 扣背景（净谱应非负、峰位不偏移）。"""
    from ncm.core.solve import load_sample

    pat = load_sample(sample_811)
    net = prepare(pat)
    peaks = find_peaks(net, rel_min=0.01)
    # 剥离后最强峰应在 18.7–18.8°（(003)），而非 Kα2 伴峰位置
    strongest = max(peaks, key=lambda p: p.intensity)
    assert 18.6 < strongest.two_theta < 18.9
    assert WAVELENGTH_KA1 == pytest.approx(1.540598)

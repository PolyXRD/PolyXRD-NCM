"""三段式精修管线测试（T6.4a 验收）。

判据：
1. stage2 **必须用缩放后结构** —— 否则 Rwp 3% → 22.5%（VALIDATION_OCC §4）；
2. 管线产出的 Li 占位 / z_O / 晶粒尺寸能进结果卡；
3. 取消钩子在阶段边界生效，抛 `RefineCancelled`；
4. 非层状结构（无 Li 位点）降级为只跑 stage1，不抛异常。
"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.core.dtypes import Pattern
from ncm.core.pipeline import (
    PipelineOptions,
    RefinePipelineResult,
    build_pipeline_card,
    run_pipeline,
)
from ncm.core.solve import SolveOptions, builtin_structure, solve


@pytest.fixture(scope="module")
def synthetic_811():
    """小窗口合成 NCM811 谱（带计数噪声）。"""
    from ncm.core.profile.forward import ProfileParams, compute_phase_profile

    st = builtin_structure("NCM811")
    prm = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                         anode="Cu")
    tt = np.arange(15.0, 45.0, 0.02)
    prof = compute_phase_profile(st, tt, prm, 15.0, 45.0)
    y = prof / prof.max() * 8000.0 + 50.0
    rng = np.random.default_rng(20261030)
    y = rng.poisson(y).astype(np.float64)
    return Pattern(two_theta=tt, intensity=y, meta={})


# --------------------------------------------------------------------------- #
# 基本管线
# --------------------------------------------------------------------------- #

def test_pipeline_runs_both_stages(synthetic_811) -> None:
    """默认配置：stage1 + stage2 都在，Li 占位拿到值。"""
    res = run_pipeline(synthetic_811, builtin_structure("NCM811"))
    assert isinstance(res, RefinePipelineResult)
    assert res.stage2 is not None, "默认应跑第二段（Li 占位）"
    assert res.occ_li is not None
    assert res.z_o is not None
    assert 0.5 <= res.occ_li <= 1.0
    assert 0.20 <= res.z_o <= 0.28


def test_pipeline_uses_scaled_structure(synthetic_811) -> None:
    """★stage2 必须用缩放后结构 —— 否则 occ 撞界 / Rwp 崩坏。

    这里的守恒量：把缩放后结构与原始结构分别喂 refine_occ，
    缩放版必须给出明显更好的 Rwp。
    """
    from ncm.core.refine.occ import identify_sites, refine_occ

    res = run_pipeline(synthetic_811, builtin_structure("NCM811"))
    sr = res.stage1
    assert sr.result.cell_scales, "stage1 应有晶胞缩放"
    fa, fc = sr.result.cell_scales[0]
    # 缩放因子在 ±1% 内（refine_cell 的边界）
    assert 0.99 <= fa <= 1.01 and 0.99 <= fc <= 1.01

    sites = identify_sites(sr.structure_scaled)
    good = refine_occ(sr.structure_scaled, sr.pattern, sr.result.params,
                      sites=sites, occ0=0.98, zo0=sites.z_o, max_iter=30)
    bad = refine_occ(sr.structure, sr.pattern, sr.result.params,
                     sites=identify_sites(sr.structure), occ0=0.98,
                     zo0=sites.z_o, max_iter=30)
    assert good.rf.rwp < bad.rf.rwp, "缩放后结构必须显著优于未缩放结构"


def test_pipeline_refine_occ_disabled(synthetic_811) -> None:
    """关掉第二段 → occ_li/z_o 为 None，且不崩。"""
    opt = PipelineOptions(refine_occ=False)
    res = run_pipeline(synthetic_811, builtin_structure("NCM811"), opt)
    assert res.stage2 is None
    assert res.occ_li is None
    assert res.z_o is None


def test_pipeline_crystallite(synthetic_811) -> None:
    """开 TCH 尺寸项 → 拿到晶粒尺寸结果。"""
    opt = PipelineOptions(refine_size=True, refine_occ=False)
    res = run_pipeline(synthetic_811, builtin_structure("NCM811"), opt)
    assert res.crystallite is not None
    assert res.crystallite.method == "scherrer"
    # 合成谱的 Y 可能触界 -> D=inf；这是允许的（"超出检出上限"口径）
    assert res.crystallite.D_nm > 0


def test_pipeline_no_size_gives_no_crystallite(synthetic_811) -> None:
    """不开 TCH → 不产晶粒尺寸（而不是报一个假的 0）。"""
    opt = PipelineOptions(refine_size=False, refine_strain=False,
                          refine_occ=False)
    res = run_pipeline(synthetic_811, builtin_structure("NCM811"), opt)
    assert res.crystallite is None


# --------------------------------------------------------------------------- #
# 取消
# --------------------------------------------------------------------------- #

def test_pipeline_cancel_before_stage2(synthetic_811) -> None:
    """stage1 后请求取消 → 抛 RefineCancelled，且不进入 stage2。"""
    from ncm.core.refine.nonlinear import RefineCancelled

    calls = {"n": 0}

    def cancel_cb():
        calls["n"] += 1
        # stage1 残差评估已完成若干次 -> 请求取消
        return calls["n"] > 3

    with pytest.raises(RefineCancelled):
        run_pipeline(synthetic_811, builtin_structure("NCM811"),
                     cancel_cb=cancel_cb)


def test_pipeline_cancel_cb_exception_is_swallowed(synthetic_811) -> None:
    """取消回调自身抛异常 → 不影响精修（与核心层同语义）。"""
    def bad_cb():
        raise RuntimeError("boom")

    res = run_pipeline(synthetic_811, builtin_structure("NCM811"),
                       PipelineOptions(refine_occ=False), cancel_cb=bad_cb)
    assert res.stage1 is not None


# --------------------------------------------------------------------------- #
# 降级
# --------------------------------------------------------------------------- #

def test_pipeline_degrades_on_non_layered() -> None:
    """无 Li 位点的结构（Ni(OH)₂ 前驱体）→ 降级为只跑 stage1，不抛异常。"""
    pat = Pattern(two_theta=np.arange(15.0, 45.0, 0.05),
                  intensity=np.full(600, 100.0), meta={})
    res = run_pipeline(pat, builtin_structure("precursor_NiOH2"))
    assert res.stage2 is None, "Ni(OH)₂ 无 Li 位点，占位精修应降级"
    assert res.occ_li is None


# --------------------------------------------------------------------------- #
# 结果卡
# --------------------------------------------------------------------------- #

def test_pipeline_card_contains_occupancy(synthetic_811) -> None:
    """管线结果 → 结果卡：Li 占位 / z_O / 晶胞都在卡里。"""
    opt = PipelineOptions(refine_size=True)
    res = run_pipeline(synthetic_811, builtin_structure("NCM811"), opt)
    card = build_pipeline_card(res, {"sample_name": "SYN"})
    assert card["header"]["sample"] == "SYN"
    assert card["composition"]["li_occupancy"] == pytest.approx(res.occ_li,
                                                               abs=1e-4)
    assert card["composition"]["o_z"] == pytest.approx(res.z_o, abs=1e-5)
    assert card["cell"]["a"] > 0 and card["cell"]["c"] > 0
    assert card["microstructure"]["crystallite_size_nm"] is not None


def test_pipeline_card_does_not_override_context(synthetic_811) -> None:
    """meta 里显式给的 occ_li 优先（便于人工覆盖复算）。"""
    opt = PipelineOptions(refine_occ=False)
    res = run_pipeline(synthetic_811, builtin_structure("NCM811"), opt)
    card = build_pipeline_card(res, {"occ_li": 0.95, "z_o": 0.26})
    assert card["composition"]["li_occupancy"] == pytest.approx(0.95, abs=1e-4)
    assert card["composition"]["o_z"] == pytest.approx(0.26, abs=1e-5)


def test_pipeline_rwp_prefers_stage2(synthetic_811) -> None:
    """有第二段时，最终 Rwp 取第二段（更完整模型）。"""
    res = run_pipeline(synthetic_811, builtin_structure("NCM811"))
    assert res.rwp == pytest.approx(float(res.stage2.rf.rwp), abs=1e-9)
    assert res.rwp != pytest.approx(float(res.stage1.rwp), abs=1e-9)


def test_stage1_options_merged_not_replaced(synthetic_811) -> None:
    """管线的 TCH 开关并入 stage1，**不覆盖**调用方给的其它开关。"""
    from ncm.core.pipeline import _stage1_options

    s1 = SolveOptions(refine_po=True, po_r={"NCM811": (0, 0, 1, 1.0)},
                      n_bg=6)
    merged = _stage1_options(PipelineOptions(stage1=s1, refine_size=True))
    assert merged.refine_po is True
    assert merged.po_r == {"NCM811": (0, 0, 1, 1.0)}
    assert merged.n_bg == 6
    assert merged.refine_size is True


def test_stage2_options_freeze_po(synthetic_811) -> None:
    """第二段峰形精修：PO 固定（不参与精修），只放开 TCH。"""
    from ncm.core.pipeline import _stage2_options

    s1 = SolveOptions(refine_po=True, po_r={"NCM811": (0, 0, 1, 1.0)})
    s2 = _stage2_options(PipelineOptions(stage1=s1, refine_size=True))
    assert s2.refine_po is False
    assert s2.po_r is None
    assert s2.refine_size is True


# --------------------------------------------------------------------------- #
# 两段峰形精修（T6.4d：PO 与 TCH 尺寸项一次性同开会落入坏解）
# --------------------------------------------------------------------------- #

def test_stage1b_uses_nonzero_size_init(synthetic_811) -> None:
    """★段1b 的初值 Y 必须避开下界 0 —— 否则尺寸项推不离下界。

    回归点：段1a 不开 TCH，其 params 的 Y = 0（恰在边界）；直接把它当初值
    传给段1b，LM 的中心差分雅可比会在越界试探点上失真，Y 恒为 0，
    晶粒尺寸被误报成"超出检出上限"。
    """
    from ncm.core.pipeline import _run_stage1, _run_stage1b
    from ncm.core import constants as C

    st = builtin_structure("NCM811")
    opt = PipelineOptions(stage1=SolveOptions(max_iter=6, refine_asym=False,
                                              refine_bfactor=False),
                          refine_size=True, refine_occ=False)
    s1a = _run_stage1(synthetic_811, st, opt, progress_cb=None, on_iter=None,
                      cancel_cb=None)
    assert s1a.result.params.Y == 0.0, "段1a 不开 TCH，Y 应为 0"

    s1b = _run_stage1b(synthetic_811, st, opt, s1a.result.params,
                       progress_cb=None, on_iter=None, cancel_cb=None)
    assert s1b.result.params.Y > 0.0, "段1b 的 Y 必须能离开下界"
    assert C.TCH_SIZE_INIT_Y > 0.0


def test_pipeline_keeps_po_in_result(synthetic_811) -> None:
    """第二段固定 PO，但结果里**保留**择优取向 r（否则结果卡漏项）。"""
    from ncm.core.pipeline import default_options_for

    st = builtin_structure("NCM811")
    opt = default_options_for(st)
    res = run_pipeline(synthetic_811, st,
                       PipelineOptions(stage1=opt.stage1,
                                       refine_occ=False, refine_size=False))
    assert res.stage1.result.po_r is not None
    assert res.stage1.result.po_r["NCM811"][:3] == (0, 0, 1)

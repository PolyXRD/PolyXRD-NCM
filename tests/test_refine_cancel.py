"""可取消精修的核心层测试（T6.3a 验收）。

**核心判据**：取消必须**真的停下来**，而不是「精修跑完了但结果被丢弃」。
所以判据是 `RefineCancelled` 异常从 `refine()` / `solve()` 一路透传出来，
且抛出时机足够早（不白跑几十秒）。
"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.core.refine.nonlinear import (
    RefineCancelled,
    RefineConfig,
    refine,
)
from ncm.core.profile.forward import ProfileParams, compute_phase_profile
from ncm.core.solve import builtin_structure, load_sample, solve

GRID = np.arange(10.0, 80.0, 0.02)
PRM = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
                    anode="Cu", ka_ratio=0.5)


def _synthetic():
    """合成一条单相谱（够快，用于取消行为测试）。"""
    from ncm.core.dtypes import Pattern

    st = builtin_structure("NCM811")
    y = compute_phase_profile(st, GRID, PRM)
    y = y / max(y.max(), 1e-12) * 10000.0
    rng = np.random.default_rng(20260701)
    y = y + 100.0 + rng.normal(0.0, np.sqrt(np.maximum(y, 1.0)))
    return st, Pattern(two_theta=GRID.copy(), intensity=y)


def _cfg(**extra) -> RefineConfig:
    base = dict(refine_zero=True, refine_uvw=True, refine_eta=True, n_bg=4,
                max_iter=12, tmin=12.0, tmax=79.0, bg_mode="cheb",
                refine_asym=False, refine_bfactor=False, refine_cell=False)
    base.update(extra)
    return RefineConfig(**base)


def test_cancel_immediately_raises() -> None:
    """一开始就请求取消 —— 必须立刻抛异常。"""
    st, pat = _synthetic()
    with pytest.raises(RefineCancelled):
        refine([st], pat, PRM, _cfg(cancel_cb=lambda: True))


def test_cancel_after_n_calls_raises() -> None:
    """跑到第 5 次残差评估时取消 —— 也必须抛出来。"""
    st, pat = _synthetic()
    calls = {"n": 0}

    def cb() -> bool:
        calls["n"] += 1
        return calls["n"] >= 5

    with pytest.raises(RefineCancelled):
        refine([st], pat, PRM, _cfg(cancel_cb=cb))
    assert calls["n"] >= 5


def test_no_cancel_completes_normally() -> None:
    """cancel_cb 一直返回 False —— 精修照常完成，结果有效。"""
    st, pat = _synthetic()
    res = refine([st], pat, PRM, _cfg(cancel_cb=lambda: False))
    assert res.success
    assert np.isfinite(res.rf.rwp)


def test_cancel_cb_exception_is_swallowed() -> None:
    """回调自身抛异常 —— 按 vendor 惯例吞掉，不能影响精修。"""
    st, pat = _synthetic()

    def bad() -> bool:
        raise RuntimeError("回调炸了")

    res = refine([st], pat, PRM, _cfg(cancel_cb=bad))
    assert res.success


def test_default_config_has_no_cancel() -> None:
    """默认不启用取消 —— 不影响既有行为（INV-3 字段只增不减）。"""
    cfg = RefineConfig()
    assert cfg.cancel_cb is None


def test_solve_propagates_cancel(sample_811) -> None:
    """`solve()` 也必须把取消异常透传出来（GUI 走的是 solve 这条路）。"""
    with pytest.raises(RefineCancelled):
        solve(load_sample(sample_811), builtin_structure("NCM811"),
              cancel_cb=lambda: True)


def test_solve_without_cancel_works(sample_811) -> None:
    """对照组：不带取消钩子的 solve 仍能正常出结果。"""
    sr = solve(load_sample(sample_811), builtin_structure("NCM811"))
    assert sr.rwp < 10.0

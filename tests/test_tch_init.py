"""TCH 初值与边界病态回归测试（T6.4d 验收）。

**背景**：GUI 接 TCH 尺寸项时，真实样的晶粒尺寸恒为「超出检出上限」。
根因是 LM 的中心差分雅可比在参数**恰在下界 0** 时试探点越界、方向失真，
参数推不离下界（TCH 尺寸项 Y 的初值恰为 0）。

**修法**：不改 LM（改优化器会破坏已锚定的 T2.3 行为），改**初值** ——
开 TCH 精修但未显式给初值时自动补 `constants.TCH_SIZE_INIT_Y` /
`TCH_STRAIN_INIT_X`（详见 `docs/VALIDATION_TCH.md` §6）。

这些用例把"再把初值改回 0 会出事"这件事固化成可执行的断言。
"""
from __future__ import annotations

import pytest

from ncm.core import constants as C
from ncm.core.solve import SolveOptions


def test_tch_init_constants_are_nonzero() -> None:
    """初值必须远离下界 0 —— 0 恰是 TCH 参数的下界。"""
    assert C.TCH_SIZE_INIT_Y > 0.0
    assert C.TCH_STRAIN_INIT_X > 0.0
    assert C.TCH_SIZE_INIT_Y < C.TCH_Y_BOUNDS[1]
    assert C.TCH_STRAIN_INIT_X < C.TCH_X_BOUNDS[1]


def test_init_y_corresponds_to_sane_crystallite_size() -> None:
    """Y=0.08° 的物理含义是 D ≈ 98 nm（纳米晶正极的典型相干衍射畴）。"""
    from ncm.core.crystallite import from_tch

    cr = from_tch(C.TCH_SIZE_INIT_Y, 0.0, 1.54056)
    assert 50.0 <= cr.D_nm <= 250.0, f"D={cr.D_nm:.1f} nm 不在合理区间"


def test_profile_params_gets_default_size_init() -> None:
    """开尺寸精修但不给初值 → 自动补非零 Y。"""
    prm = SolveOptions(refine_size=True).to_profile_params()
    assert prm.Y == pytest.approx(C.TCH_SIZE_INIT_Y)


def test_profile_params_gets_default_strain_init() -> None:
    prm = SolveOptions(refine_strain=True).to_profile_params()
    assert prm.X == pytest.approx(C.TCH_STRAIN_INIT_X)


def test_explicit_init_is_respected() -> None:
    """显式给了初值 → 以调用方为准（不覆盖）。"""
    prm = SolveOptions(refine_size=True, Y=0.03).to_profile_params()
    assert prm.Y == pytest.approx(0.03)


def test_no_tch_keeps_zero_init() -> None:
    """不开 TCH → Y/X 保持 0（golden 基线逐位不变的前提）。"""
    prm = SolveOptions().to_profile_params()
    assert prm.Y == 0.0
    assert prm.X == 0.0


def test_golden_baseline_unchanged() -> None:
    """★开 TCH 的改动不得影响基线（INV-1）。"""
    from ncm.core.solve import builtin_structure, solve
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
    # 基线不该开 TCH，故 Y 仍为 0
    assert sr.result.params.Y == 0.0
    assert sr.rwp > 0


def test_lm_jacobian_left_unchanged() -> None:
    """★LM 的雅可比必须保持 vendor 原样（不在优化器上做文章）。

    曾尝试改成"边界感知单边差分"，结果把已锚定的 T2.3 行为带偏
    （"尺寸+应变"配置 Rwp 3.2058 → 3.8941）。边界病态在**初值侧**规避。
    """
    import inspect

    from ncm.core.refine.lm import _jacobian

    src = inspect.getsource(_jacobian)
    assert "bounds" not in src, "LM 雅可比不得引入边界处理"
    assert "np.clip" not in src, "LM 雅可比不得夹试探点"


def test_solve_accepts_init_params_backward_compatible() -> None:
    """solve() 追加的 init_params 是可选 keyword，既有调用不受影响。"""
    import inspect

    from ncm.core.solve import solve

    sig = inspect.signature(solve)
    assert "init_params" in sig.parameters
    assert sig.parameters["init_params"].default is None
    assert sig.parameters["init_params"].kind is inspect.Parameter.KEYWORD_ONLY

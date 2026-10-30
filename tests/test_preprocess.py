"""预处理门面测试（T1.1 验收）。"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.core.dtypes import Pattern
from ncm.core.patterns import load_pattern
from ncm.core.preprocess import (
    PreprocessConfig,
    apply,
    for_refinement,
    smooth,
    strip_background,
    strip_ka2,
)


@pytest.fixture(scope="module")
def real(sample_811):
    return load_pattern(sample_811)


def _synthetic(seed: int = 20260701) -> Pattern:
    rng = np.random.default_rng(seed)
    x = np.arange(10.0, 80.0, 0.02)
    y = 1000 + 50 * np.sin(x / 7) + rng.normal(0, 10, x.size)
    return Pattern(two_theta=x, intensity=y)


def test_load_real_sample(real) -> None:
    assert real.two_theta.size == 3500
    assert real.two_theta[0] == pytest.approx(10.0)
    assert real.step == pytest.approx(0.02, abs=1e-6)


def test_smooth_off_is_passthrough() -> None:
    p = _synthetic()
    q = smooth(p, window=0)
    assert np.allclose(q.intensity, p.intensity)


def test_smooth_preserves_axis_and_reduces_noise() -> None:
    p = _synthetic()
    q = smooth(p, window=21, polyorder=3)
    assert np.array_equal(q.two_theta, p.two_theta)
    # 二阶差分（噪声代理）应显著下降
    assert np.std(np.diff(q.intensity, 2)) < np.std(np.diff(p.intensity, 2))


def test_background_splits_exactly(real) -> None:
    net, bg = strip_background(real, mode="chebyshev", poly_deg=3)
    assert net.two_theta.size == real.two_theta.size
    assert np.allclose(net.intensity + bg, real.intensity)
    # 背景必须是平滑的（二阶差分远小于原始谱）
    assert np.std(np.diff(bg, 2)) < 0.01 * np.std(np.diff(real.intensity, 2))


def test_ka2_strip_shape_and_effect(real) -> None:
    out = strip_ka2(real, anode="Cu", ratio=0.5)
    assert out.two_theta.size == real.two_theta.size
    assert np.array_equal(out.two_theta, real.two_theta)
    # 剥离后最强峰强度应下降（移走了一部分 Kα2 贡献）
    assert out.intensity.max() < real.intensity.max()


def test_apply_chain_order(real) -> None:
    cfg = PreprocessConfig(smooth_window=11, smooth_poly=3, bg_mode="chebyshev",
                           bg_poly_deg=3, ka2=True, ka2_ratio=0.5, anode="Cu")
    res = apply(real, cfg)
    assert [n for n, _ in res.steps] == ["去Kα2", "扣背景", "平滑"]
    assert res.background is not None
    assert res.pattern.intensity.size == real.two_theta.size
    assert "处理:" in res.summary()


def test_apply_default_is_identity(real) -> None:
    cfg = PreprocessConfig()
    res = apply(real, cfg)
    assert res.steps == []
    assert np.allclose(res.pattern.intensity, real.intensity)


def test_for_refinement_is_raw(real) -> None:
    """精修必须吃原始谱，与预处理结果无关。"""
    pre = apply(real, PreprocessConfig(smooth_window=21, bg_mode="chebyshev"))
    fed = for_refinement(real)
    assert np.allclose(fed.intensity, real.intensity)
    assert not np.allclose(fed.intensity, pre.pattern.intensity)


@pytest.mark.parametrize("bad", [
    dict(bg_mode="not_a_mode"),
    dict(smooth_window=10),
    dict(ka2_ratio=0.0),
])
def test_invalid_config_raises(bad) -> None:
    with pytest.raises(ValueError):
        PreprocessConfig(**bad).validate()

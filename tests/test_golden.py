"""golden 基线回归（T1.4 验收 · INV-1）。

**这是全项目最重要的一条测试线**：任何后续改动（TCH 峰形、占位精修、RB、
判定门）都必须让它继续绿。红了的处理顺序是：

1. 先确认不是 bug（对照 `docs/VALIDATION.md` 的历史值）；
2. 确属预期改进 → 开卡、跑 `tools/make_golden.py` 重出基线、在 VALIDATION 记原因；
3. **禁止**为了让它绿而直接放宽容差。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ncm.core.solve import builtin_structure, load_sample, solve

GOLDEN = Path(__file__).resolve().parent / "golden" / "ncm811_baseline.json"

#: 容差：相对 0.5%（数值求解器/LAPACK 版本差异的量级），Rwp 另加 0.15pp 绝对下限。
REL_TOL = 5e-3
RWP_ABS_TOL = 0.15


@pytest.fixture(scope="module")
def golden() -> dict:
    if not GOLDEN.exists():
        pytest.skip(f"基线不存在: {GOLDEN}（跑 tools/make_golden.py）")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["metrics"]


@pytest.fixture(scope="module")
def current(sample_811):
    return solve(load_sample(sample_811), builtin_structure("NCM811")).as_dict()


def test_rwp_matches_golden(golden, current) -> None:
    """Rwp 是最直观的健康指标。"""
    assert abs(current["rwp"] - golden["rwp"]) <= RWP_ABS_TOL, (
        f"Rwp 漂移: 基线 {golden['rwp']:.2f}% -> 现 {current['rwp']:.2f}%")


@pytest.mark.parametrize("key", ["a", "c", "c_over_a", "volume"])
def test_cell_matches_golden(golden, current, key) -> None:
    """晶胞必须逐位稳定 —— 这是精修收敛性的直接体现。"""
    base, now = golden[key], current[key]
    assert abs(now - base) <= REL_TOL * max(abs(base), 1e-9), (
        f"{key} 漂移: {base:.5f} -> {now:.5f}")


@pytest.mark.parametrize("key", ["zero", "U", "V", "W", "eta", "asym", "bfactor"])
def test_profile_matches_golden(golden, current, key) -> None:
    """峰形参数。U/V 接近 0 时相对容差会失真，用绝对容差兜底。"""
    base, now = golden[key], current[key]
    tol = max(REL_TOL * abs(base), 2e-3)
    assert abs(now - base) <= tol, f"{key} 漂移: {base:.5f} -> {now:.5f}"


def test_golden_is_physically_sane(current) -> None:
    """基线本身要经得起物理检查（防止基线被错误结果污染）。"""
    assert current["rwp"] < 10.0, "Rwp 超过 10%，拟合质量不合格"
    assert 2.85 < current["a"] < 2.90, f"a={current['a']:.4f} 超出层状 NCM 合理区间"
    assert 14.15 < current["c"] < 14.30, f"c={current['c']:.4f} 超出合理区间"
    assert 4.90 < current["c_over_a"] < 5.00, "c/a 超出层状结构判据区间"
    assert 0.0 <= current["bfactor"] < 1.5, "B 因子应接近 0（缺尺寸项时会爆大）"

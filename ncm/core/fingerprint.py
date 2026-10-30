"""结构指纹相关：峰宽自适应的整谱 Pearson 相关（T8.2）。

**为什么单独成模块**：判定门（`identify.py`）已 590 行、超过「单文件 ≤400
行」的硬约束，再往里堆必然失控。本模块只做一件事 —— 把「实测谱与候选
结构理论谱像不像」量化成一个可比的相关系数，不依赖判定门的任何状态，
可脱离 `identify` 单测。

**为什么不写死峰宽**（T8.2 实测缺陷）
--------------------------------------
原实现把理论谱峰宽写成常数 `U=0.03 / V=-0.01 / W=0.008`（半高宽约
0.1–0.15°），与实测峰宽无关。峰宽失配时整谱 Pearson 相关被严重压低，
**真结构也会被判成"无结构可信匹配"**：

| 样品 | 写死峰宽 corr | 按实测峰宽 corr | 结论变化 |
|---|---|---|---|
| 真实三元氢氧化物前驱体（Data043，峰宽约 0.35°） | 0.711 | **0.965** | other → precursor_hydroxide |

阈值 `C.FINGERPRINT_MIN = 0.85` 一个不动 —— 修的是**模型失配**，不是
放宽判据。T5.2 全部 22 个样本的 ok/kind 判定逐个不变（见
`docs/TASKS.md` T8.2）。
"""
from __future__ import annotations

import math

import numpy as np

from ncm.core import constants as C
from ncm.core.dtypes import Pattern
from ncm.core.peaks import WAVELENGTH_KA1, ObservedPeak, find_peaks
from ncm.core.profile.cif import CifStructure


def obs_fwhm(net: Pattern, obs: list[ObservedPeak], *,
             nmax: int = 6) -> list[tuple[float, float]]:
    """从净谱测强峰的半高全宽（度）→ `[(2θ, FWHM)]`。

    半高基线取峰两侧 ±`FINGERPRINT_FWHM_WIN_DEG` 内的最小值 —— 峰底常压
    在背景残留上，用 0 当基线会把 FWHM 算大。宽度落在
    [`FINGERPRINT_FWHM_MIN_DEG`, `FINGERPRINT_FWHM_MAX_DEG`] 之外的对
    视为不可靠（采样太疏 / 峰其实是背景隆起），直接丢弃。
    """
    t = np.asarray(net.two_theta, dtype=np.float64)
    y = np.asarray(net.intensity, dtype=np.float64)
    if t.size < 5:
        return []
    dt = float(np.median(np.diff(t)))
    if not np.isfinite(dt) or dt <= 0.0:
        return []
    win = max(int(C.FINGERPRINT_FWHM_WIN_DEG / dt), 2)
    out: list[tuple[float, float]] = []
    for p in obs[:nmax]:
        i = int(np.argmin(np.abs(t - p.two_theta)))
        lo, hi = max(i - win, 0), min(i + win + 1, y.size)
        base = float(np.min(y[lo:hi]))
        height = float(y[i]) - base
        if height <= 0.0:
            continue
        half = base + 0.5 * height
        j = i
        while j > 0 and y[j] > half:
            j -= 1
        k = i
        while k < y.size - 1 and y[k] > half:
            k += 1
        w = float(t[k] - t[j])
        if C.FINGERPRINT_FWHM_MIN_DEG <= w <= C.FINGERPRINT_FWHM_MAX_DEG:
            out.append((float(t[i]), w))
    return out


def fit_uvw(widths: list[tuple[float, float]], tmin: float,
            tmax: float) -> tuple[float, float, float] | None:
    """由实测 FWHM 反演 Caglioti 的 (U, V, W)，使理论谱与实测谱同峰宽。

    Γ²(2θ) = U tan²θ + V tanθ + W，**固定 U=0**，用 `(tanθ, 1)` 对
    `(V, W)` 做最小二乘：手头只有 6 个以内的峰宽样本，解 3 个参数病态，
    且在 12–79° 内 `U tan²θ` 与 `V tanθ` 高度共线。

    解出的 (V, W) 必须在整个 2θ 区间给出正的 Γ²，否则退化为**定宽**
    (`U=V=0, W=FWHM_mean²`) —— 负 Γ² 会让前向模型出 NaN。
    """
    if len(widths) < 2:
        return None
    tan = np.array([math.tan(math.radians(tt / 2.0)) for tt, _ in widths])
    g2 = np.array([w * w for _, w in widths])
    a = np.column_stack([tan, np.ones_like(tan)])
    sol, *_ = np.linalg.lstsq(a, g2, rcond=None)
    v, w = float(sol[0]), float(sol[1])
    edges = (math.tan(math.radians(tmin / 2.0)),
             math.tan(math.radians(tmax / 2.0)))
    if w <= 0.0 or min(v * e + w for e in edges) <= 1e-6:
        w_mean = float(np.mean([x for _, x in widths]))
        return 0.0, 0.0, w_mean * w_mean
    return 0.0, v, w


def peak_width_uvw(net: Pattern) -> tuple[float, float, float]:
    """从实测净谱反演理论谱应使用的 (U, V, W)（峰宽自适应）。

    测不到 ≥2 个可靠峰宽时退回 `C.FINGERPRINT_UVW_FALLBACK`。
    """
    widths = obs_fwhm(net, find_peaks(net, rel_min=C.PEAK_REL_MIN))
    grid = np.asarray(net.two_theta, dtype=np.float64)
    uvw = fit_uvw(widths, float(grid[0]), float(grid[-1])) \
        if grid.size >= 2 else None
    if uvw is not None:
        return uvw
    U, V, W = C.FINGERPRINT_UVW_FALLBACK
    return U, V, W


def corr(struct: CifStructure, cell, net: Pattern,
         grid: np.ndarray) -> float:
    """结构指纹相关：标定后理论谱与实测净谱的 Pearson 相关。

    **这是分流阶段的关键门槛**。峰位 RMS 单独不够：标定只有 (a, c) 两个
    自由度，什么谱都能拟合出一个像样的 RMS（T5.1 实测：岩盐 NiO 对
    R-3c 碳酸盐的标定 RMS 仅 0.069°，但两者毫无关系）。整谱相关同时
    要求**强度分布**一致 —— 实测真结构 0.92–0.98，非结构 −0.02–0.55。

    理论谱用**单色 Kα1**（实测侧已剥 Kα2），两边同口径；峰宽按实测谱
    反演（`peak_width_uvw`），见模块 docstring。
    """
    from ncm.core.profile.forward import ProfileParams, compute_phase_profile

    U, V, W = peak_width_uvw(net)
    prm = ProfileParams(zero=0.0, U=U, V=V, W=W, eta=0.6,
                        anode=None, wavelength=WAVELENGTH_KA1)
    scaled = CifStructure(struct.name, tuple(cell), struct.atoms)
    theo = compute_phase_profile(scaled, grid, prm)
    obs = np.asarray(net.intensity, dtype=np.float64)
    if theo.size != obs.size:
        return 0.0
    if theo.max() > 0:
        theo = theo / theo.max()
    if obs.max() > 0:
        obs = obs / obs.max()
    if theo.std() < 1e-12 or obs.std() < 1e-12:
        return 0.0
    return float(np.corrcoef(obs, theo)[0, 1])

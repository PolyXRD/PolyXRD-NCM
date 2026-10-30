"""谱峰工具：实测寻峰 + 理论反射表（T5.1 辅助模块）。

判定门（`ncm/core/identify.py`）需要两样东西，本模块提供，避免两套峰位口径
在 GUI 与判定门之间漂移：

1. **实测峰列表** `(2θ, I)`：Kα2 剥离 → 扣背景 → 平滑 → 局部极大。
2. **理论反射表** `(2θ, I, hkl 集合)`：由晶胞枚举。

**hkl 标签的来源（不复制 vendor 强度公式）**
---------------------------------------------
vendor `compute_peaks` 按 `round(2θ/1e-3)` 把多重性合并，不返回 hkl。本模块
自己枚举 `(h,k,l)` 算 2θ，再用**同一个 key** 与 `compute_peaks` 的结果对齐：

- 被系统消光的 hkl，其 2θ 在 `compute_peaks` 里**不存在** → 自然被排除；
- 无需复制 vendor 的结构因子公式，也不会与 vendor 口径漂移。

晶胞枚举走 numpy 向量化（(2H+1)³ 个点），单次约 10 ms —— 判定门要对
十几个候选结构反复标定晶胞，Python 双重循环扛不住。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ncm.core.background import BgConfig, estimate_background
from ncm.core.dtypes import Pattern
from ncm.core.kalpha2 import KAlpha2Config, strip_kalpha2
from ncm.core.profile.cif import CifStructure
from ncm.core.profile.struct import compute_peaks, reciprocal_basis
from ncm.core.smooth import SmoothConfig, savitzky_golay

#: Cu Kα1 波长（Å）—— 判定门用单色 Kα1 理论峰（实测谱已剥离 Kα2）
WAVELENGTH_KA1 = 1.540598
#: 峰位合并容差（与 vendor `struct.TWO_THETA_TOL` 一致）
TWO_THETA_TOL = 1e-3


@dataclass(frozen=True)
class ObservedPeak:
    """一个实测峰。"""

    two_theta: float
    intensity: float


@dataclass(frozen=True)
class Reflection:
    """一个理论反射（多重性已合并）。"""

    two_theta: float
    intensity: float
    hkls: tuple[tuple[int, int, int], ...]


def prepare(pat: Pattern, *, ka2_ratio: float = 0.5, anode: str = "Cu",
            bg_mode: str = "linear_edges", smooth_window: int = 7) -> Pattern:
    """判定门专用预处理链：去 Kα2 → 扣背景 → 平滑。

    顺序不可换：Rachinger 剥离依赖原始计数，扣背景会把背景模型误差一起
    递推放大（见 `ncm/core/preprocess.py` 模块说明）。

    判定门**必须**剥离 Kα2：Cu Kα2 相对 Kα1 的位移在 44° 处已达 0.11°，
    与 C1 的 RMS 阈值同量级，不剥离会把"Kα2 伴峰"误配成"主峰"，
    凭空制造 0.1° 量级的假偏差（实测：贪心匹配选中 Kα2 峰，RMS 0.09→0.13）。
    """
    cur = strip_kalpha2(pat, KAlpha2Config(enabled=True, ratio=ka2_ratio,
                                           anode=anode))
    bg = estimate_background(cur, BgConfig(mode=bg_mode, edge_frac=0.10,
                                           poly_deg=1))
    y = cur.intensity - bg
    if smooth_window and smooth_window % 2 == 0:
        raise ValueError(f"平滑窗口必须为奇数: {smooth_window}")
    if smooth_window:
        y = savitzky_golay(y, SmoothConfig(enabled=True, window=smooth_window,
                                           polyorder=2))
    return Pattern(two_theta=cur.two_theta.copy(), intensity=y,
                   meta=dict(cur.meta))


def find_peaks(net: Pattern, *, rel_min: float = 0.01) -> list[ObservedPeak]:
    """在净谱上找峰：局部极大 + 相对最强峰的强度阈值。

    按强度降序返回。`rel_min` 相对的是**最强峰**，不是积分强度。

    NCM 修改（T8.2）：加**突出度（prominence）门槛**
    -------------------------------------------------
    原实现只按「峰高 ≥ rel_min × 最强峰高」过滤，**不看峰是否从邻域基线
    里站得出来** —— 低强度实样上噪声肩会被当成峰。实测真实三元氢氧化物
    前驱体（`Data043`，5–80°，最强峰 3389 计数，噪声肩 2–4% 相对强度）
    寻得 **62 个峰**，超过判定门的 `C_MAX_OBS_PEAKS = 60`，于是在「噪声」
    分支直接返回 `other` —— 用户得到的是「谱图含大量噪声」这一误导性
    结论，而真实原因是寻峰把 9 个真实峰切成了 62 个。

    加 `prominence ≥ PEAK_PROMINENCE_FRAC × 最强峰高` 后：同一谱 9 个峰，
    而 T5.2 全部 22 个样本的判定结论（ok / kind）逐个不变 —— 门槛只砍
    噪声肩，不动真实峰（真实 Bragg 峰的突出度等于自身高度，远高于 1%）。
    """
    from scipy.signal import find_peaks as _sp_find_peaks

    from ncm.core import constants as C

    y = np.asarray(net.intensity, dtype=np.float64)
    if y.size < 3:
        return []
    h_all = float(np.max(y))
    prom = C.PEAK_PROMINENCE_FRAC * h_all if h_all > 0 else 0.0
    idx, _ = _sp_find_peaks(y, prominence=prom)
    if idx.size == 0:
        return []
    h = y[idx]
    thr = rel_min * float(np.max(h))
    out = [ObservedPeak(float(net.two_theta[i]), float(v))
           for i, v in zip(idx, h) if v >= thr]
    out.sort(key=lambda p: -p.intensity)
    return out


def two_theta_of(cell, hkl, wavelength: float = WAVELENGTH_KA1) -> float | None:
    """由晶胞与 (h,k,l) 求 Bragg 角 2θ（度）。超出衍射极限返回 None。"""
    a, b, c, al, be, ga = cell
    ast, bst, cst = reciprocal_basis(a, b, c, al, be, ga)
    h, k, l = hkl
    rlv = h * ast + k * bst + l * cst
    g = math.sqrt(float(rlv @ rlv))
    s = wavelength * g / 2.0
    if s >= 1.0:
        return None
    return 2.0 * math.degrees(math.asin(s))


def hkl_groups(cell, wavelength: float = WAVELENGTH_KA1,
               tmin: float = 12.0, tmax: float = 79.0) -> dict[int, tuple]:
    """枚举全部 (h,k,l)，按 2θ 合并 → `{key: (2θ, hkl 集合)}`。

    只依赖晶胞（不含强度），因此标定循环里可以廉价反复调用。
    """
    a, b, c, al, be, ga = cell
    ast, bst, cst = reciprocal_basis(a, b, c, al, be, ga)
    gmin = 2.0 * math.sin(math.radians(tmin / 2.0)) / wavelength
    gmax = 2.0 * math.sin(math.radians(tmax / 2.0)) / wavelength
    min_recip = min(np.linalg.norm(ast), np.linalg.norm(bst),
                    np.linalg.norm(cst))
    hmax = max(int(math.ceil(gmax / min_recip)) + 2, 6)
    n = np.arange(-hmax, hmax + 1)
    hh, kk, ll = np.meshgrid(n, n, n, indexing="ij")
    keep = (hh != 0) | (kk != 0) | (ll != 0)
    rlv = hh[..., None] * ast + kk[..., None] * bst + ll[..., None] * cst
    g = np.linalg.norm(rlv, axis=-1)
    keep &= (g >= gmin - 1e-9) & (g <= gmax + 1e-9)
    s = wavelength * g[keep] / 2.0
    valid = s < 1.0
    tt = 2.0 * np.degrees(np.arcsin(np.clip(s[valid], -1.0, 1.0)))
    hkl_all = np.stack([hh[keep][valid], kk[keep][valid], ll[keep][valid]],
                       axis=-1)
    groups: dict[int, tuple] = {}
    for pos, hkl in zip(tt, hkl_all):
        key = int(round(float(pos) / TWO_THETA_TOL))
        slot = groups.setdefault(key, [float(pos), []])
        slot[1].append((int(hkl[0]), int(hkl[1]), int(hkl[2])))
    return {k: (v[0], tuple(sorted(v[1]))) for k, v in groups.items()}


def reflections(struct: CifStructure, wavelength: float = WAVELENGTH_KA1,
                tmin: float = 12.0, tmax: float = 79.0) -> list[Reflection]:
    """理论反射表（按强度降序）。

    强度来自 vendor `compute_peaks`（含 LP 因子），hkl 来自本地枚举后按
    2θ key 对齐 —— 被消光的反射自动排除。
    """
    groups = hkl_groups(struct.cell, wavelength, tmin, tmax)
    peaks, _skipped = compute_peaks(struct, wavelength=wavelength,
                                    two_min=tmin, two_max=tmax)
    by_key = {int(round(p / TWO_THETA_TOL)): (float(p), float(i))
              for p, i, _d in peaks}
    out: list[Reflection] = []
    for key, (tt, hkls) in groups.items():
        hit = by_key.get(key)
        if hit is None:                      # ±1 key 容差（浮点边界）
            for dk in (-1, 1):
                hit = by_key.get(key + dk)
                if hit is not None:
                    break
        if hit is None:                      # 被系统消光
            continue
        out.append(Reflection(two_theta=hit[0], intensity=hit[1], hkls=hkls))
    out.sort(key=lambda r: -r.intensity)
    return out

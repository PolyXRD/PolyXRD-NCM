"""晶粒尺寸 / 微观应变反演（T2.2 · 新建，非 vendor）。

两条独立路径，结果互为校核（T2.3 / T8 交叉验证的物理出口）：

1. **Scherrer 直反演**（吃 Rietveld 精修出的 TCH 系数）
   Y = (180/π)·Kλ/D  ->  D = (180/π)·K·λ/Y
   X = (180/π)·4ε    ->  ε = (π/180)·X/4
   口径与 `size_strain.py` 完全一致（STD_FREEZE §3 v2）。

2. **Williamson–Hall**（吃逐峰拟合 FWHM，UDM 匀应变模型）
   β·cosθ = Kλ/D + 4ε·sinθ
   对 (4·sinθ, β·cosθ) 做线性最小二乘：斜率 = ε，截距 = Kλ/D。
   β 取**样品洛伦兹 FWHM**（弧度）：先用 TCH 逆解从观测 FWHM 里
   剥掉仪器高斯分量（Caglioti U/V/W），再进 W-H。
   洛伦兹 FWHM 与积分breadth差 π/2 倍，但 K=0.89 本身按 FWHM 口径标定，
   两条路径只要**同口径**即可互相校核 —— 这与多数 W-H 文献实践一致。

约定（写报告时必须带上）：
- D 是**相干衍射畴尺寸**（体积加权），不等于 SEM/TEM 颗粒度；
- ε 是上限定性量（均匀应变模型），量级参考：NCM 正极材料典型 <2e-3。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ncm.core.profile.size_strain import (
    SCHERRER_K,
    fwhm_gaussian,
    size_from_y,
    strain_from_x,
    tch_combine,
)

#: 峰位与仪器参数确定后，观测 FWHM 至少要比纯仪器宽化多出这么多（度）
#: 才认为存在可分辨的样品宽化（低于此视为 0，避免二分法在噪声里乱转）。
_MIN_EXCESS = 1e-6
#: TCH 逆解二分迭代次数（区间宽度收敛到初值的 2^-60，远超数据精度）
_BISECT_ITERS = 60
#: 尺寸检出上限（nm）。D 超过它意味着 Kλ/D < ~1e-5°，低于常规
#: 实验室谱的拟合精度 —— 此时报告应写"超出检出上限"（inf）而不是
#: 输出一个毫无误差意义的天文数字。两条路径（Scherrer / W-H）统一适用。
D_DETECT_MAX_NM = 5000.0


@dataclass(frozen=True)
class CrystalliteResult:
    """尺寸/应变反演输出（T2.2 契约：`(D_nm, strain, method, r2)` 的展开）。"""

    D_nm: float            # 相干衍射畴尺寸（nm）；inf = 未检出尺寸宽化
    strain: float          # 微观应变 ε（无量纲）
    method: str            # "scherrer" | "williamson-hall"
    r2: float | None       # W-H 线性拟合优度；Scherrer 直反演无拟合 -> None
    n_peaks: int = 0       # W-H 参与拟合的峰数（Scherrer 路径为 0）

    def as_dict(self) -> dict:
        return {
            "D_nm": self.D_nm if math.isinf(self.D_nm) else round(self.D_nm, 2),
            "strain": float(f"{self.strain:.3e}"),
            "method": self.method,
            "r2": None if self.r2 is None else round(self.r2, 4),
            "n_peaks": self.n_peaks,
        }


# ---------------------------------------------------------------------------
# 路径 1：Scherrer 直反演（精修 Y/X -> 物理量）
# ---------------------------------------------------------------------------
def _clamp_d(d_ang: float) -> float:
    """统一检出上限口径：D(Å) 超过 D_DETECT_MAX_NM 视为未检出。"""
    if math.isinf(d_ang) or d_ang > D_DETECT_MAX_NM * 10.0:
        return math.inf
    return d_ang


def from_tch(Y_deg: float, X_deg: float, wavelength: float,
             k: float = SCHERRER_K) -> CrystalliteResult:
    """由精修得到的 TCH 洛伦兹系数 Y（尺寸）、X（应变）直反演。

    Y <= 0 表示尺寸项未启用/未精修 -> D = inf（报告里应写 ">检出上限"）。
    波长单位 Å，返回 D 单位 nm。
    """
    d_ang = size_from_y(Y_deg, wavelength, k)      # Å，Y<=0 时为 inf
    return CrystalliteResult(
        D_nm=_clamp_d(d_ang) / 10.0,
        strain=strain_from_x(X_deg),
        method="scherrer",
        r2=None,
    )


# ---------------------------------------------------------------------------
# 路径 2：Williamson–Hall（逐峰 FWHM -> 物理量）
# ---------------------------------------------------------------------------
def _sample_lorentz_from_observed(fwhm_obs: float, fwhm_instr_g: float) -> float:
    """TCH 逆解：给定观测总 FWHM 与仪器高斯 FWHM，反解样品洛伦兹 FWHM。

    tch_combine(ΓG, ΓL) 对 ΓL 严格单调递增（各正幂项），故二分法全局收敛。
    观测不比仪器宽（差值 < _MIN_EXCESS）时返回 0。
    """
    if fwhm_obs - fwhm_instr_g < _MIN_EXCESS:
        return 0.0
    lo, hi = 0.0, fwhm_obs
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        if tch_combine(fwhm_instr_g, mid) < fwhm_obs:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def williamson_hall(peaks, U: float, V: float, W: float, wavelength: float,
                    k: float = SCHERRER_K) -> CrystalliteResult:
    """Williamson–Hall (UDM) 反演。

    参数
    ----
    peaks : sequence of (two_theta_deg, fwhm_obs_deg)
        逐峰拟合宽度（Kα1 尺度；如带 Kα2 请先剥线）。
    U, V, W : 仪器高斯项（Caglioti），来自同期标准样或精修结果。
    wavelength : Å。

    至少 3 个峰才能给出有意义的 r2；更少直接抛 ValueError。
    """
    pts = [(float(t), float(f)) for t, f in peaks]
    if len(pts) < 3:
        raise ValueError(f"Williamson–Hall 至少需要 3 个峰，收到 {len(pts)} 个")
    if any(f <= 0 for _t, f in pts):
        raise ValueError("FWHM 必须为正")

    xs: list[float] = []   # 4·sinθ
    ys: list[float] = []   # β·cosθ  (β = 样品洛伦兹 FWHM, 弧度)
    for tt, f_obs in pts:
        theta = math.radians(tt) / 2.0
        g_instr = fwhm_gaussian(tt, U, V, W)
        f_samp = _sample_lorentz_from_observed(f_obs, g_instr)
        beta = math.radians(f_samp)
        xs.append(4.0 * math.sin(theta))
        ys.append(beta * math.cos(theta))

    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    # 退化判定用 x 值域而非 denom 的绝对阈值：近重合峰位时
    # n·sxx−sx² 是 ~1e-11 量级的浮点小量，卡 1e-15 挡不住。
    if max(xs) - min(xs) < 1e-4:
        raise ValueError("峰位过近，W-H 方程组退化（斜率/截距不可分）")
    denom = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denom          # -> ε
    intercept = (sy - slope * sx) / n            # -> Kλ/D（Å）

    # r2：纯尺寸/纯应变情形 y 数学上是严格线性或严格常数，浮点残差
    # (~1e-17) 会让 ss_tot 成为伪小量 —— 必须按相对尺度判噪声，否则
    # r2 会崩成无意义的大负数（实测 -4.13）。
    ybar = sy / n
    ss_tot = sum((y - ybar) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2
                 for x, y in zip(xs, ys))
    scale = max(n * ybar * ybar, 1e-30)
    if ss_tot <= scale * 1e-9:
        r2 = 1.0 if ss_res <= scale * 1e-9 else 0.0
    else:
        r2 = 1.0 - ss_res / ss_tot

    if intercept > 0:
        d_ang = _clamp_d(k * wavelength / intercept)
    else:
        d_ang = math.inf      # 截距 <=0：无尺寸宽化证据
    strain = max(slope, 0.0)  # UDM 下负应变无物理意义（可能是数据噪声）
    return CrystalliteResult(D_nm=d_ang / 10.0, strain=strain,
                             method="williamson-hall", r2=r2, n_peaks=n)

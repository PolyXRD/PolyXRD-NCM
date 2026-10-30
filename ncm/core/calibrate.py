"""判定门的「快速晶胞标定」（T5.1 引入，T5.2 迭代剔除离群配对）。

**为什么单独成模块**：`ncm/core/identify.py` 曾达 563 行，超「单文件
≤400 行」的硬约束。标定是**纯几何子问题**（只用到峰位，不用强度），
与"判定哪些判据"完全解耦，可以脱离判定门单测。

**为什么判定门必须先标定**
--------------------------
CIF 自带的是文献晶胞，与实测差 0.2–0.3 %。2θ 偏差随 tanθ 放大：18.8°
处 −0.04°、44.5° 处 −0.10°、77° 处 −0.23°。直接拿 CIF 晶胞比峰位，
C1 的 RMS 实测 0.164° **恒超 0.10° 阈值**，判定门形同虚设。标定后
RMS 降到 0.0138°，标定晶胞与 40 秒全谱精修只差 0.01 %。

**标定检验的是结构类型，不是晶胞绝对值**
----------------------------------------
标定只有 (a, c) 两个自由度 —— **什么谱都能拟合出一个像样的峰位 RMS**。
所以标定之后还必须过晶胞偏差护栏与强度指纹两道门（见 `identify.py`
的 `_best_match`），否则会把岩盐 NiO、尖晶石、纯噪声都判成真结构
（T5.1 实测缺陷，已修）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ncm.core import constants as C
from ncm.core.peaks import WAVELENGTH_KA1, ObservedPeak, hkl_groups, two_theta_of
from ncm.core.profile.cif import CifStructure


@dataclass(frozen=True)
class MatchPair:
    """一对「实测峰 ↔ 理论峰」的配对。"""

    obs_tt: float
    theo_tt: float
    hkl: tuple
    dev: float          # obs_tt − theo_tt（度）


def match(obs: list[ObservedPeak], theo: list[tuple[float, tuple]],
          tol: float) -> list[MatchPair]:
    """贪心一对一匹配（偏差小者优先），返回按 2θ 升序的配对。"""
    cand = []
    for i, o in enumerate(obs):
        for j, (tt, hkl) in enumerate(theo):
            d = abs(o.two_theta - tt)
            if d <= tol:
                cand.append((d, i, j))
    cand.sort()
    used_o: set[int] = set()
    used_t: set[int] = set()
    out: list[MatchPair] = []
    for d, i, j in cand:
        if i in used_o or j in used_t:
            continue
        used_o.add(i)
        used_t.add(j)
        out.append(MatchPair(obs[i].two_theta, theo[j][0], theo[j][1],
                             obs[i].two_theta - theo[j][0]))
    out.sort(key=lambda p: p.obs_tt)
    return out


def rms(pairs: list[MatchPair]) -> float:
    if not pairs:
        return float("inf")
    return math.sqrt(sum(p.dev * p.dev for p in pairs) / len(pairs))


def theo_list(cell) -> list[tuple[float, tuple]]:
    """晶胞 → 理论峰位列表（按 2θ 升序）。"""
    groups = hkl_groups(cell, WAVELENGTH_KA1, C.IDENTIFY_TMIN, C.IDENTIFY_TMAX)
    return [(v[0], v[1]) for _k, v in sorted(groups.items(),
                                             key=lambda kv: kv[1][0])]


def _resid_factory(obs_arr: np.ndarray, hkls: list, cell, lam: float):
    """构造残差函数（显式绑定入参，避免闭包捕获循环变量）。

    把 `obs_arr` / `hkls` 作为参数而非闭包引用，是为了让每次迭代的残差
    严格对应当轮的配对集合 —— 循环变量被闭包捕获时，一旦改成延后调用
    就会静默用上最后一轮的配对，是本类重构的经典坑。
    """
    def resid(x: np.ndarray) -> np.ndarray:
        a, c = float(x[0]), float(x[1])
        cell2 = (a, a, c, cell[3], cell[4], cell[5])
        out = []
        for o, hkl in zip(obs_arr, hkls):
            t = two_theta_of(cell2, hkl, lam)
            out.append(o - t if t is not None else 10.0)
        return np.array(out, dtype=np.float64)

    return resid


def fit_cell(cell, pairs: list[MatchPair], lam: float):
    """由配对最小二乘拟合三角晶系晶胞 (a, c)。角度保持不变。

    **迭代剔除离群配对**：初始匹配基于文献晶胞，配对本身可能错配
    （实测 LiNiO₂ 用 NCM811 参考标定时，a 初值差 0.4 %，44.4° 的真峰被
    配到 44.62° 的理论峰，LM 随即被拉向错误晶胞 a=2.861 vs 真值 2.875）。
    故每次拟合后剔除偏差超过 3×RMS 的配对并重拟合，最多 3 轮。
    """
    from ncm.core.refine.lm import lm_minimize

    use = list(pairs)
    cell_new = cell
    for _ in range(3):
        hkls = [p.hkl[0] for p in use]     # hkl 是等价集合，取其一即可
        obs_arr = np.array([p.obs_tt for p in use], dtype=np.float64)
        resid = _resid_factory(obs_arr, hkls, cell, lam)

        res = lm_minimize(resid, np.array([cell_new[0], cell_new[2]],
                                          dtype=np.float64), max_iter=40)
        a, c = float(res.x[0]), float(res.x[1])
        cell_new = (a, a, c, cell[3], cell[4], cell[5])
        devs = [abs(p.dev) for p in use]
        rms_now = math.sqrt(sum(d * d for d in devs) / len(devs))
        keep = [p for p in use if abs(p.dev) <= max(3.0 * rms_now, 0.02)]
        if len(keep) < 4 or len(keep) == len(use):
            break
        use = keep
    return cell_new, use


def calibrate(struct: CifStructure, obs: list[ObservedPeak], lam: float):
    """迭代「匹配 → 拟合 a,c → 重匹配」。返回 (cell, 配对)。"""
    cell = struct.cell
    pairs: list[MatchPair] = []
    for _ in range(C.CALIB_ROUNDS):
        pairs = match(obs, theo_list(cell), C.C1_MATCH_TOL_DEG)
        if len(pairs) < 4:
            break
        cell, kept = fit_cell(cell, pairs, lam)
        if len(kept) < len(pairs):
            pairs = kept
    return cell, pairs


def calibrate_pool(pool, obs: list[ObservedPeak], lam: float):
    """对候选池逐个标定，按峰位 RMS 升序返回 `[(struct, cell, pairs, rms)]`。

    **为什么要"池中最佳"而不是固定用一个参考**：标定对**初值敏感** ——
    文献晶胞差 0.4 % 就可能把匹配带偏并收敛到错误的 (a, c)（实测 LiNiO₂
    谱用 NCM811 参考标定得 a=2.861，而用 NCM811_alt 标定得 a=2.876，
    真值 2.8755）。池中覆盖多个初始晶胞，取 RMS 最小者即取到最可信的标定。
    """
    out = []
    for st in pool:
        coarse = match(obs, theo_list(st.cell), C.C1_MATCH_TOL_DEG)
        if len(coarse) < 4:
            continue
        cell, pairs = calibrate(st, obs, lam)
        if len(pairs) < 4:
            continue
        out.append((st, cell, pairs, rms(pairs)))
    out.sort(key=lambda x: x[3])
    return out


def cell_drift_pct(cell, ref_cell) -> tuple[float, float]:
    """标定后晶胞相对原 CIF 晶胞的偏差（%）。"""
    da = abs(cell[0] - ref_cell[0]) / max(abs(ref_cell[0]), 1e-9) * 100.0
    dc = abs(cell[2] - ref_cell[2]) / max(abs(ref_cell[2]), 1e-9) * 100.0
    return da, dc

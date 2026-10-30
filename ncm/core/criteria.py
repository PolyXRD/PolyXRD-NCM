"""判定门的三重判据 C1 / C2 / C3（T5.1 引入，T8.5 从 identify.py 拆出）。

**为什么单独成模块**：`ncm/core/identify.py` 曾达 563 行，超「单文件 ≤400 行」
硬约束。三重判据只吃「实测峰表 + 标定晶胞」，不碰候选池、不碰分流逻辑，
是纯判据计算，可以脱离判定门单测。

三个判据的阈值唯一出处在 `ncm/core/constants.py`，本模块不写死任何数字。

| 判据 | 指标 | 含义 |
|---|---|---|
| C1 | 前 N 强峰峰位 RMS | 层状 R-3m 的峰位序列对不对 |
| C2 | (006)/(012)、(108)/(110) 可分辨 | 层状结构的特征双峰 |
| C3 | I(003)/I(104) 区间 | 层状占位是否合理（阳离子混排不严重）|

**C1 的「先匹配、后取强」口径**：实测前 12 强与理论前 12 强是两套独立的强度
排序，对不同配比的层状氧化物并不一致（NCM811 的 Ni 80/Co 10/Mn 10 与 LiNiO₂
的 Ni 100 峰强分布不同），按序硬配会漏掉一半 —— 实测 LiNiO₂ 合成谱因此只命中
5 个主峰而被漏检。改为先把理论峰与实测峰全量贪心匹配，再在**匹配上的对**里取
实测强度前 N 强算 RMS。
"""
from __future__ import annotations

import math

from ncm.core import constants as C
from ncm.core.calibrate import MatchPair, match
from ncm.core.peaks import ObservedPeak, two_theta_of

#: 判据用到的特征 hkl（六方三指数记法）
HKL_003 = (0, 0, 3)
HKL_104 = (1, 0, 4)
HKL_006 = (0, 0, 6)
HKL_012 = (0, 1, 2)
HKL_108 = (1, 0, 8)
HKL_110 = (1, 1, 0)


def peak_near(obs: list[ObservedPeak], pos: float, tol: float
              ) -> ObservedPeak | None:
    """邻域内**最强**的实测峰（Kα1 峰总比 Kα2 伴峰强，故取最强）。"""
    cand = [o for o in obs if abs(o.two_theta - pos) <= tol]
    if not cand:
        return None
    return max(cand, key=lambda o: o.intensity)


def c1(obs: list[ObservedPeak], refl, top_n: int = C.C1_TOP_N):
    """C1：前 N 强峰峰位 RMS（先全量匹配，再在匹配对里取强）。"""
    theo = [(r.two_theta, r.hkls) for r in refl[:top_n * 2]]
    pairs = match(obs, theo, C.C1_RMS_MAX * 2.0)
    if not pairs:
        return False, {"rms_deg": None, "hits": 0, "min_hits": C.C1_MIN_MATCH,
                       "rms_max": C.C1_RMS_MAX, "pass": False}
    order = {round(o.two_theta, 6): o.intensity for o in obs}
    pairs.sort(key=lambda p: -order.get(round(p.obs_tt, 6), 0.0))
    top: list[MatchPair] = pairs[:top_n]
    rms = math.sqrt(sum(p.dev * p.dev for p in top) / len(top))
    hits = len(pairs)
    ok = hits >= C.C1_MIN_MATCH and rms <= C.C1_RMS_MAX
    return ok, {"rms_deg": round(rms, 5), "hits": hits,
                "min_hits": C.C1_MIN_MATCH, "rms_max": C.C1_RMS_MAX,
                "pass": ok}


def c2(obs: list[ObservedPeak], cell, lam: float):
    """C2：(006)/(012) 与 (108)/(110) 双峰可分辨。"""
    checks = []
    for h1, h2 in ((HKL_006, HKL_012), (HKL_108, HKL_110)):
        t1 = two_theta_of(cell, h1, lam)
        t2 = two_theta_of(cell, h2, lam)
        if t1 is None or t2 is None:
            checks.append({"pair": [h1, h2], "pass": False,
                           "reason": "理论峰位不可计算"})
            continue
        p1 = peak_near(obs, t1, C.C2_PEAK_TOL_DEG)
        p2 = peak_near(obs, t2, C.C2_PEAK_TOL_DEG)
        split = abs(t1 - t2)
        ok = (p1 is not None and p2 is not None
              and split >= C.C2_SPLIT_MIN)
        checks.append({
            "pair": [list(h1), list(h2)],
            "two_theta": [round(t1, 3), round(t2, 3)],
            "split_deg": round(split, 4),
            "split_min": C.C2_SPLIT_MIN,
            "found": [p1 is not None, p2 is not None],
            "pass": ok,
        })
    ok = all(c["pass"] for c in checks)
    return ok, {"pairs": checks, "pass": ok}


def c3(obs: list[ObservedPeak], cell, lam: float):
    """C3：I(003)/I(104) 落在宽松区间。"""
    t3 = two_theta_of(cell, HKL_003, lam)
    t4 = two_theta_of(cell, HKL_104, lam)
    p3 = peak_near(obs, t3, C.C3_PEAK_TOL_DEG) if t3 else None
    p4 = peak_near(obs, t4, C.C3_PEAK_TOL_DEG) if t4 else None
    ratio = (p3.intensity / p4.intensity
             if (p3 is not None and p4 is not None and p4.intensity > 0)
             else None)
    ok = ratio is not None and C.C3_RATIO_MIN <= ratio <= C.C3_RATIO_MAX
    return ok, {
        "ratio": round(ratio, 4) if ratio is not None else None,
        "i003": round(p3.intensity, 2) if p3 else None,
        "i104": round(p4.intensity, 2) if p4 else None,
        "window": [C.C3_RATIO_MIN, C.C3_RATIO_MAX],
        "pass": ok,
    }

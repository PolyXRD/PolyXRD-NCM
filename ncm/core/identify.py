"""物相判定门（T5.1）。

**目的**：导入谱后先判断「这是不是 NCM（或其前驱体）」，不是就停下并提示。
本模块**不跑精修**，只做峰位层面的快速结构类型判定 —— 必须能在 GUI 里
秒级返回。

三重判据（STD_FREEZE §1，阈值唯一出处 `ncm/core/constants.py`）
--------------------------------------------------------------
| 判据 | 指标 | 阈值 |
|---|---|---|
| C1 | 前 12 强峰与 R-3m 理论峰的 2θ 均方根偏差 | ≤ 0.10° |
| C2 | (006)/(012) 与 (108)/(110) 双峰可分辨 | Δ2θ ≥ 0.10° |
| C3 | I(003)/I(104) | ∈ [0.5, 3.0] |

**C1 的「理论峰」是标定后的（R-3m 晶胞快速标定）** —— 这是本卡的关键口径，
STD_FREEZE v3 已补记：

1. CIF 自带的晶胞是文献值，与实测差 0.2–0.3%（实测 a=2.87185 vs CIF 2.86450），
   而 2θ 偏差随 tanθ 放大：18.8° 处 −0.04°，44.5° 处 −0.10°，77° 处 −0.23°。
   直接拿 CIF 晶胞比，C1 的 RMS 实测 0.164°，**恒超 0.10° 阈值**，判定门形同虚设。
2. 判定门先做一次**快速晶胞标定**（匹配 → LM 拟合 a,c → 重匹配，3 轮），
   再用标定后的理论峰跑 C1。实测 RMS 0.164° → **0.0138°**，标定得
   a=2.87158 / c=14.19411，与 40 秒全谱精修的锚点 (2.87185 / 14.19502)
   相差 0.01%。
3. 标定检验的是**结构类型**（层状 R-3m 的峰位序列特征），不检验晶胞绝对值 ——
   这正是 STD_FREEZE §1 边界声明要表达的：NCM811 / LiNiO₂ / NCA 的晶胞几乎
   相同，实验室 XRD 分不开，Ni:Co:Mn 比例须由 ICP/EDS 确定。

**分流**：C1–C3 全过 → `ncm`；否则在候选池里找**结构可信**的匹配，按其空间群
归类为 `precursor_hydroxide` / `precursor_carbonate`；都不匹配 → `other`。

**结构可信度门槛（三道，缺一不可）**
----------------------------------
晶胞快速标定只有 (a, c) 两个自由度 —— **什么谱都能拟合出一个像样的峰位
RMS**。只按 RMS 挑最佳候选会翻车（T5.1 实测缺陷，已修）：

| 样品 | 旧口径（只看 RMS） | 修正后 |
|---|---|---|
| 岩盐 NiO | 判成 `precursor_carbonate`（RMS 0.069°） | 无可信候选 → `other` |
| 尖晶石 LiMn₂O₄ | 判成 `ncm` | 无可信候选 → `other` |
| 金红石 TiO₂ | 判成 `ncm`（RMS 0.079°） | 无可信候选 → `other` |
| 纯噪声谱 | 判成 `precursor_hydroxide` | 无可信候选 → `other` |

三道门槛：
1. **峰位**：命中 ≥ `C1_MIN_MATCH` 且 RMS ≤ `C1_RMS_MAX`；
2. **晶胞**：标定后相对原 CIF 晶胞的偏差 ≤ `CALIB_CELL_TOL_PCT`（3%）——
   标定能把尖晶石的 a=8.25 Å 拉到 2.80 Å，这道护栏专治此类；
3. **强度指纹**：整谱 Pearson 相关 ≥ `C_FINGERPRINT_MIN`（0.85）——
   真结构 0.92–0.98，非结构 −0.02–0.55，判别裕度充足。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from ncm.core import constants as C
from ncm.core import fingerprint
from ncm.core.calibrate import (
    MatchPair,
    calibrate,
    calibrate_pool,
    cell_drift_pct,
    match,
    rms,
)
from ncm.core.criteria import (
    HKL_003,
    HKL_006,
    HKL_012,
    HKL_104,
    HKL_108,
    HKL_110,
    c1,
    c2,
    c3,
)
from ncm.core.dtypes import Pattern
from ncm.core.peaks import (
    WAVELENGTH_KA1,
    ObservedPeak,
    find_peaks,
    prepare,
    reflections,
)
from ncm.core.profile.cif import CifStructure

__all__ = [
    "HKL_003",
    "HKL_006",
    "HKL_012",
    "HKL_104",
    "HKL_108",
    "HKL_110",
    "IdentifyResult",
    "MatchPair",
    "category_of",
    "default_pool",
    "identify",
]

#: 兼容别名 —— 保 `tests/`、`tools/` 与历史内部调用点的旧名不破
_c1 = c1
_c2 = c2
_c3 = c3
_calibrate = calibrate
_calibrate_pool = calibrate_pool
_cell_drift_pct = cell_drift_pct
_match = match
_rms = rms

#: 空间群国际表号 → 类别
_SG_CATEGORY = {
    166: C.KIND_NCM,                     # R -3 m：层状氧化物
    164: C.KIND_PRECURSOR_HYDROXIDE,     # P -3 m 1：类 β-Ni(OH)2 氢氧化物
    167: C.KIND_PRECURSOR_CARBONATE,     # R -3 c：方解石型碳酸盐
}

#: 判定门内置参考结构（STD_FREEZE 的「R-3m 理论峰」出处）
REFERENCE_NAME = "NCM811"


@dataclass(frozen=True)
class IdentifyResult:
    """判定门结论。

    - `ok`：True = **可以进入 NCM 精修流程**（仅当 kind == ncm 且 C1–C3 全过）。
    - `kind`：结构类型（ncm / precursor_hydroxide / precursor_carbonate / other），
      即使 `ok` 为 False 也给出，用于界面措辞（「这是前驱体，请走前驱体流程」）。
    - `reasons`：逐条中文理由（界面直接显示）。
    - `metrics`：量化明细（可进结果卡 / 日志）。
    """

    ok: bool
    kind: str
    reasons: tuple[str, ...] = ()
    metrics: dict = field(default_factory=dict)

    def summary(self) -> str:
        head = "通过" if self.ok else "未通过"
        return f"[{head}] {self.kind}｜" + "；".join(self.reasons)


# ---------------------------------------------------------------------------
# 候选池
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def default_pool() -> tuple[CifStructure, ...]:
    """内置 CIF 全池（14 份：层状氧化物 / 前驱体）。"""
    from ncm.core.solve import builtin_structure

    names = ("NCM811", "NCM811_alt", "NCM111", "NCM111_alt", "NCM523",
             "NCM622", "LiNiO2", "LiCoO2", "Lirich", "NCM_delith",
             "precursor_NCM811_OH", "precursor_NiOH2",
             "precursor_NCM811_CO3", "precursor_NiCO3")
    out = []
    for n in names:
        try:
            out.append(builtin_structure(n))
        except (FileNotFoundError, ValueError):
            continue
    return tuple(out)


def category_of(struct: CifStructure) -> str:
    """按空间群归类（CIF 未带空间群时归 other）。"""
    from ncm.core.symmetry import lookup

    sg = getattr(struct, "spacegroup", None)
    if not sg:
        return C.KIND_OTHER
    try:
        info = lookup(sg)
    except KeyError:
        return C.KIND_OTHER
    if info.number is None:
        return C.KIND_OTHER
    return _SG_CATEGORY.get(int(info.number), C.KIND_OTHER)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def identify(pat: Pattern, cif_pool=None, *, anode: str = "Cu",
             ka2_ratio: float = 0.5) -> IdentifyResult:
    """判定门主流程。

    参数
    ----
    pat : 原始谱（可含背景与 Kα2 —— 判定门内部自行预处理）
    cif_pool : 候选结构列表；None = 内置 14 份

    返回语义的约定
    --------------
    - `ok=True` **当且仅当** kind == ncm 且 C1–C3 全过 → 可以进入 NCM 精修。
    - `kind` 是**结构类型**：ncm / precursor_hydroxide / precursor_carbonate /
      other。`ok=False` 时 kind 仍会给出（例如 LiCoO₂ 是层状 R-3m，kind=ncm
      但 ok=False），界面据此措辞（"是层状氧化物但晶胞不是 NCM，是否仍按 NCM
      精修？"），而不是一律拒之门外。
    """
    lam = WAVELENGTH_KA1
    net = prepare(pat, ka2_ratio=ka2_ratio, anode=anode)
    obs = find_peaks(net, rel_min=C.PEAK_REL_MIN)
    metrics: dict = {"n_peaks": len(obs),
                     "peak_rel_min": C.PEAK_REL_MIN}

    if len(obs) < C.C1_MIN_MATCH:
        return IdentifyResult(False, C.KIND_OTHER,
                              (f"可用峰仅 {len(obs)} 个（不足 "
                               f"{C.C1_MIN_MATCH}），谱图可能不是 XRD 粉末谱。",),
                              metrics)
    if len(obs) > C.C_MAX_OBS_PEAKS:
        return IdentifyResult(False, C.KIND_OTHER,
                              (f"寻得 {len(obs)} 个峰，超过上限 "
                               f"{C.C_MAX_OBS_PEAKS} —— 谱图含大量噪声，"
                               f"不是可用的 XRD 粉末谱。",),
                              metrics)

    pool = tuple(cif_pool) if cif_pool else default_pool()
    ref = _reference(pool)
    if ref is None:
        return IdentifyResult(False, C.KIND_OTHER,
                              ("候选池中没有可用的 R-3m 参考结构。",), metrics)

    # --- 快速路径：只用内置参考结构标定，判据全过就收工（绝大多数情况）---
    st_ref = ref
    cell, pairs = _calibrate(ref, obs, lam)
    c1_ok, c1 = _c1(obs, _refl_for_cell(st_ref, cell, lam))
    c2_ok, c2 = _c2(obs, cell, lam) if c1_ok else (False, None)
    c3_ok, c3 = _c3(obs, cell, lam) if c1_ok else (False, None)

    # --- 完整路径：快速路径未全过 → 用池中最佳标定重试 ---
    pool_cal = []
    if not (c1_ok and c2_ok and c3_ok):
        pool_cal = _calibrate_pool(pool, obs, lam)
        if pool_cal:
            st_ref, cell, pairs, _rms0 = pool_cal[0]
            c1_ok, c1 = _c1(obs, _refl_for_cell(st_ref, cell, lam))
            c2_ok, c2 = _c2(obs, cell, lam) if c1_ok else (False, None)
            c3_ok, c3 = _c3(obs, cell, lam) if c1_ok else (False, None)

    metrics["c1"] = c1
    metrics["c2"] = c2 if c2 else {"pass": None, "evaluated": False,
                                   "reason": "C1 未通过，未评估"}
    metrics["c3"] = c3 if c3 else {"pass": None, "evaluated": False,
                                   "reason": "C1 未通过，未评估"}
    metrics["calibrated_cell"] = {"a": round(cell[0], 5), "c": round(cell[2], 5)}
    metrics["calib_hits"] = len(pairs)
    metrics["calib_rms"] = round(_rms(pairs), 5) if pairs else None
    metrics["reference"] = st_ref.name

    reasons: list[str] = []
    if c1_ok:
        reasons.append(f"C1 通过：{c1['hits']} 个主峰峰位 RMS "
                       f"{c1['rms_deg']:.4f}° ≤ {C.C1_RMS_MAX}°。")
    else:
        reasons.append(f"C1 未通过：命中 {c1['hits']} 个主峰，RMS "
                       f"{c1['rms_deg'] if c1['rms_deg'] is not None else '—'}°"
                       f"（阈值 {C.C1_RMS_MAX}°，至少需命中 "
                       f"{C.C1_MIN_MATCH} 个）。")

    c2_ok = c3_ok = False
    if c1_ok:
        c2_ok, c2 = _c2(obs, cell, lam)
        c3_ok, c3 = _c3(obs, cell, lam)
        metrics["c2"], metrics["c3"] = c2, c3
        reasons.append("C2 通过：(006)/(012) 与 (108)/(110) 双峰均可分辨。"
                       if c2_ok else "C2 未通过：层状特征双峰未能分辨。")
        reasons.append(f"C3 通过：I(003)/I(104) = {c3['ratio']:.3f}。"
                       if c3_ok else
                       f"C3 未通过：I(003)/I(104) = "
                       f"{c3['ratio'] if c3['ratio'] is not None else '—'}"
                       f"（应落在 {C.C3_RATIO_MIN}–{C.C3_RATIO_MAX}）。")
    else:
        metrics["c2"] = {"pass": None, "evaluated": False,
                          "reason": "C1 未通过，未评估"}
        metrics["c3"] = {"pass": None, "evaluated": False,
                          "reason": "C1 未通过，未评估"}

    if c1_ok and c2_ok and c3_ok:
        a_lo, a_hi = C.NCM_FAMILY_A_RANGE
        a_val = cell[0]
        reasons.append(f"标定晶胞 a={a_val:.4f} Å、c={cell[2]:.4f} Å。")
        if not (a_lo <= a_val <= a_hi):
            reasons.append(f"晶胞族属判据未通过：标定 a={a_val:.4f} Å 不在 NCM "
                           f"族区间 {a_lo}–{a_hi} Å —— 疑似 LiCoO₂ "
                           f"(a≈2.814 Å) 等其他层状氧化物，或脱锂体系；"
                           f"该谱不按 NCM 成品放行（层状结构类型仍予保留）。")
            metrics["ncm_family_a"] = {"value": round(a_val, 5),
                                       "range": [a_lo, a_hi], "pass": False}
            return IdentifyResult(False, C.KIND_NCM, tuple(reasons), metrics)
        metrics["ncm_family_a"] = {"value": round(a_val, 5),
                                   "range": [a_lo, a_hi], "pass": True}
        reasons.append(f"晶胞族属判据通过：a 落在 NCM 族 {a_lo}–{a_hi} Å。")
        reasons.append("提示：NCM811 / LiNiO₂ / NCA 的晶胞几乎相同，"
                       "实验室 XRD 分不开，Ni:Co:Mn 比例须由 ICP/EDS 确定。")
        return IdentifyResult(True, C.KIND_NCM, tuple(reasons), metrics)

    reasons.append("判据未全部通过，转入结构类型分流。")
    trusted = _best_match(pool_cal, obs, lam, net, pat.two_theta)
    metrics["trusted_matches"] = trusted
    if not trusted:
        reasons.append("候选池中无任何结构能以可信方式匹配该谱"
                       f"（峰位 RMS ≤ {C.C1_RMS_MAX}°、晶胞偏差 ≤ "
                       f"{C.CALIB_CELL_TOL_PCT}%、指纹相关 ≥ "
                       f"{C.C_FINGERPRINT_MIN}）。")
        return IdentifyResult(False, C.KIND_OTHER, tuple(reasons), metrics)

    best = trusted[0]
    kind = best["category"]
    reasons.append(f"最佳可信匹配「{best['name']}」：峰位 RMS "
                   f"{best['rms_deg']:.4f}°、命中 {best['hits']} 峰、"
                   f"指纹相关 {best['corr']:.3f}、标定 a={best['a']:.4f} Å。")
    if kind == C.KIND_PRECURSOR_HYDROXIDE:
        reasons.append("→ 三元氢氧化物前驱体（P-3m1），不是层状氧化物成品。")
    elif kind == C.KIND_PRECURSOR_CARBONATE:
        reasons.append("→ 碳酸盐前驱体（R-3c），不是层状氧化物成品。")
    elif kind == C.KIND_NCM:
        reasons.append("→ 层状 R-3m 锂过渡金属氧化物，但与标准 NCM 参考的"
                       "晶胞/峰位不完全吻合（可能是 LiCoO₂、脱锂或富锂体系）。")
    else:
        reasons.append("→ 判定为非 NCM 样品。")
    return IdentifyResult(False, kind, tuple(reasons), metrics)


def _reference(pool: tuple[CifStructure, ...]) -> CifStructure | None:
    """判定门的 R-3m 参考结构：优先内置 NCM811，否则池中任一 R-3m。"""
    for st in pool:
        if st.name == REFERENCE_NAME:
            return st
    for st in pool:
        if category_of(st) == C.KIND_NCM:
            return st
    return None


def _refl_for_cell(ref: CifStructure, cell, lam: float):
    """按标定后晶胞重算反射表（强度随晶胞微变，hkl 不变）。"""
    scaled = CifStructure(ref.name, tuple(cell), ref.atoms)
    return reflections(scaled, lam, C.IDENTIFY_TMIN, C.IDENTIFY_TMAX)


def _best_match(pool_cal, obs: list[ObservedPeak], lam: float, net: Pattern,
                grid: np.ndarray) -> list[dict]:
    """在**已标定**的候选里挑出结构可信的匹配（按峰位 RMS 升序）。

    三道门槛（缺一不可）：
    1. 峰位：命中 ≥ `C1_MIN_MATCH` 且 RMS ≤ `C1_RMS_MAX`；
    2. 晶胞：标定后相对原 CIF 晶胞的偏差 ≤ `CALIB_CELL_TOL_PCT`
       —— 标定只有 2 个自由度，没有这道护栏，什么谱都能被"拟合"成候选；
    3. 强度指纹：整谱 Pearson 相关 ≥ `C_FINGERPRINT_MIN`
       —— 只看峰位会把"强行标定"的假匹配当真（T5.1 实测缺陷）。
       指纹本身在 `ncm/core/fingerprint.py`（峰宽自适应，T8.2）。
    """
    out: list[dict] = []
    for st, cell, pairs, pair_rms in pool_cal:
        if len(pairs) < C.C1_MIN_MATCH or pair_rms > C.C1_RMS_MAX:
            continue
        da, dc = _cell_drift_pct(cell, st.cell)
        if max(da, dc) > C.CALIB_CELL_TOL_PCT:
            continue
        corr = fingerprint.corr(st, cell, net, grid)
        if corr < C.C_FINGERPRINT_MIN:
            continue
        out.append({"name": st.name, "category": category_of(st),
                    "rms_deg": round(pair_rms, 5), "hits": len(pairs),
                    "corr": round(corr, 4),
                    "a": round(cell[0], 5), "c": round(cell[2], 5),
                    "cell_drift_pct": [round(da, 2), round(dc, 2)]})
    out.sort(key=lambda r: r["rms_deg"])
    return out

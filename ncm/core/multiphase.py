"""第二相槽位与多相定量（T5.3）。

**要解决的问题**：真实 NCM 样品常含少量杂质 —— 表面残碱 Li₂CO₃、合成副产物
NiO、碳包覆/石墨。单相精修会把这些相的峰当作"未解释峰"，拉高 Rwp，也让
晶胞与占位参数出现系统偏差。本模块提供：

1. **第二相槽位**：主相 + ≤2 个杂质相（`MAX_IMPURITIES = 2`）。
   多相前向模型与每相独立 scale 在 vendor 侧已就绪
   （`refine/linear.py::solve_linear_detail` 的 `coeffs[:P]` 即各相 scale），
   本模块只管**槽位编排、候选匹配与定量**。
2. **定量**：Hill–Howard 质量分数（`refine/qpa.py`，vendor 副本）。
3. **残差诊断**：从单相精修的残差里找出**未解释峰**，并给出可能的杂质相
   建议 —— 这是"要不要开第二相槽位"的决策依据。

**定量口径与前提**（写入报告与界面提示，不可省略）：
- Hill–Howard 要求各相的 scale 与 |F|²·LP 同一绝对标度 → 前向模型必须
  `integrated=True`（峰高按积分强度归一化），这是 Rietveld 标量 S 的标准口径。
- 前提条件：各相**无择优取向**、粒度与吸收差异不显著、标度因子与相含量
  线性。实际样品中吸收差异（重相 vs 轻相）会带来系统偏差，报告应注明。
- 质量分数是**相对值**（归一到 100%），非绝对含量（未做内标）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from ncm.core.profile.cif import CifStructure
from ncm.core.refine.qpa import PhaseWeight, qpa_inputs_from_cif, qpa_weights

#: 主相之外最多允许的杂质相数量
MAX_IMPURITIES = 2

#: 槽位角色
ROLE_MAIN = "main"
ROLE_IMPURITY = "impurity"

#: 残差诊断：未解释峰的相对强度下限（相对实测最强峰）
#: 取 0.5%（而非 2%）：真实 NCM 表面的残碱 Li₂CO₃ 常只有 0.1–2 wt%，
#: 其最强峰仅为主峰的 1–2%，2% 门槛会把 10 wt% 的 Li₂CO₃ 整个漏掉。
UNEXPLAINED_REL_MIN = 0.005
#: 残差诊断：局部信噪比下限（残差峰 / 局部稳健噪声 σ）
#: 计数噪声下 σ ≈ √y，5σ 可滤掉纯噪声的偶然极大（噪声峰一般只有 3–4σ）。
UNEXPLAINED_SNR_MIN = 5.0
#: 残差诊断：局部噪声统计窗口的半宽（度）
UNEXPLAINED_LOCAL_HALF_WIDTH = 1.5
#: 残差诊断：未解释峰与候选相理论峰位的匹配容差（度）
MATCH_TOL_DEG = 0.15


@dataclass(frozen=True)
class PhaseSlot:
    """一个相槽位。

    `formula` 通常**留空** —— 由 CIF 自带的 `_chemical_formula_sum` 决定。
    内置 NCM811 实为锂富集型 `Li1.03Ni0.77Co0.1Mn0.1O2`，与教科书配方
    `LiNi0.8Co0.1Mn0.1O2` 不同；若让用户手填化学式，摩尔质量会算错，
    Hill–Howard 定量随之全错。
    """

    name: str
    structure: CifStructure
    formula: str | None = None
    role: str = ROLE_IMPURITY
    enabled: bool = True

    def resolved_formula(self) -> str:
        """实际使用的化学式：优先手填，其次 CIF 自带。"""
        f = self.formula or getattr(self.structure, "formula", None)
        if not f:
            raise ValueError(
                f"相「{self.name}」既未指定化学式，CIF 也缺少 "
                f"_chemical_formula_sum，无法定量")
        return f

    def zmv(self) -> tuple[int, float, float]:
        """(Z, 晶胞体积 Å³, 化学式量 g/mol)。

        Z 由「全晶胞原子占位 ÷ 配方」反算，**不信 CIF 自述的
        `_cell_formula_units_Z`**（内置手工编辑过的 CIF 该值与实际不符）。
        """
        return qpa_inputs_from_cif(self.structure, self.resolved_formula())

    def scale_for_weight(self, weight: float) -> float:
        """给定质量分数，反推 Hill–Howard 标度因子。

        `w_p ∝ S_p·Z_p·M_p·V_p` → `S_p = w_p/(Z_p·M_p·V_p)`（差一个公共常数）。
        合成多相谱时按此给各相 scale，定量才能自洽往返。
        """
        z, vol, mass = self.zmv()
        return weight / (z * vol * mass)


@dataclass(frozen=True)
class MultiPhasePlan:
    """多相方案：主相 + ≤2 杂质槽位。"""

    main: PhaseSlot
    impurities: tuple[PhaseSlot, ...] = ()

    def __post_init__(self) -> None:
        if len(self.impurities) > MAX_IMPURITIES:
            raise ValueError(f"杂质相最多 {MAX_IMPURITIES} 个，收到 "
                             f"{len(self.impurities)}")

    @property
    def slots(self) -> tuple[PhaseSlot, ...]:
        return (self.main,) + self.impurities

    @property
    def enabled_slots(self) -> tuple[PhaseSlot, ...]:
        return tuple(s for s in self.slots if s.enabled)

    def phases(self) -> list[CifStructure]:
        """按槽位顺序给出结构列表（与精修的相下标一一对应）。"""
        return [s.structure for s in self.enabled_slots]


@dataclass(frozen=True)
class UnexplainedPeak:
    """模型未解释的峰。"""

    two_theta: float
    height: float          # 相对实测最强峰


@dataclass(frozen=True)
class ImpuritySuggestion:
    """杂质相建议。"""

    name: str
    formula: str
    hits: int
    matched: tuple[tuple[float, float], ...]   # (未解释峰 2θ, 候选理论峰 2θ)
    strength: float       # 命中峰强度之和（相对）

    def as_dict(self) -> dict:
        return {"name": self.name, "formula": self.formula,
                "hits": self.hits, "strength": round(self.strength, 5),
                "matched": [(round(a, 3), round(b, 3))
                            for a, b in self.matched]}


# ---------------------------------------------------------------------------
# 内置杂质相
# ---------------------------------------------------------------------------

#: 内置杂质相：(文件名, 显示名, 化学式, 说明)
_BUILTIN_IMPURITY_SPEC = (
    ("Li2CO3", "Li2CO3", "Li2CO3",
     "表面残碱（碳酸锂），COD 9008283，单斜 C2/c，Z=4"),
    ("NiO", "NiO", "NiO",
     "合成副产物（氧化镍），COD 1010093，岩盐 Fm-3m，Z=4"),
    ("graphite", "graphite", "C",
     "碳包覆/石墨，COD 9011577，六方 P63/mmc，Z=4"),
)


def _load_impurity_cif(stem: str) -> CifStructure:
    from ncm.core.solve import load_structure

    base = Path(__file__).resolve().parents[1] / "data" / "cif" / "impurity"
    return load_structure(base / f"{stem}.cif")


@lru_cache(maxsize=1)
def builtin_impurities() -> tuple[PhaseSlot, ...]:
    """内置杂质槽位（Li₂CO₃ / NiO / 石墨）。

    化学式一律取 CIF 自带（`formula=None`），不手填。
    """
    out = []
    for stem, disp, _formula, _note in _BUILTIN_IMPURITY_SPEC:
        try:
            st = _load_impurity_cif(stem)
        except (FileNotFoundError, ValueError):
            continue
        out.append(PhaseSlot(name=disp, structure=st, formula=None,
                             role=ROLE_IMPURITY))
    return tuple(out)


def impurity_notes() -> dict[str, str]:
    """杂质相说明（界面提示用）。"""
    return {disp: note for _stem, disp, _f, note in _BUILTIN_IMPURITY_SPEC}


def make_plan(main: CifStructure, main_formula: str | None = None,
              impurities: list[PhaseSlot] | None = None) -> MultiPhasePlan:
    """构造多相方案。

    - `impurities` 为 None：取内置候选的前 `MAX_IMPURITIES` 个（Li₂CO₃、NiO）。
    - `impurities` 显式给出：**不做静默截断**，超过 `MAX_IMPURITIES` 直接
      抛 ValueError —— 悄悄丢掉用户指定的相是危险的（用户以为加了 3 个杂质，
      实际只算了 2 个）。
    """
    slot_main = PhaseSlot(name=main.name, structure=main, formula=main_formula,
                           role=ROLE_MAIN)
    imps = tuple(builtin_impurities()[:MAX_IMPURITIES] if impurities is None
                 else tuple(impurities))
    return MultiPhasePlan(main=slot_main, impurities=imps)


# ---------------------------------------------------------------------------
# 定量
# ---------------------------------------------------------------------------

def quantify(slots, scales) -> list[PhaseWeight]:
    """Hill–Howard 质量分数。

    参数
    ----
    slots : 相槽位序列（与 `scales` 逐项对应）
    scales : 精修得到的每相标度因子（`RefineResult.scales[:P]`）

    返回质量分数之和为 1 的 `PhaseWeight` 列表。
    """
    if len(slots) != len(scales):
        raise ValueError(f"槽位数 {len(slots)} 与 scale 数 {len(scales)} 不符")
    inputs = []
    for slot, scale in zip(slots, scales):
        z, vol, mass = slot.zmv()
        inputs.append((slot.name, float(scale), z, vol, mass))
    return qpa_weights(inputs)


# ---------------------------------------------------------------------------
# 残差诊断与杂质建议
# ---------------------------------------------------------------------------

def _local_sigma(resid: np.ndarray, tt: np.ndarray, center: float,
                 half_width: float) -> float:
    """局部稳健噪声估计（1.4826 × MAD）。

    取 ±`half_width` 度的窗口，用中位数绝对偏差估计 σ。相比 Poisson 假设
    σ=√y，本法对归一化后的谱、已扣背景的谱、探测器不同增益都成立。
    """
    sel = np.abs(tt - center) <= half_width
    w = resid[sel]
    if w.size < 8:
        w = resid
    med = np.median(w)
    sigma = 1.4826 * float(np.median(np.abs(w - med)))
    return sigma if sigma > 0 else 1e-12


def unexplained_peaks(two_theta, y_obs, y_calc, *,
                       rel_min: float = UNEXPLAINED_REL_MIN,
                       smooth_window: int = 7,
                       snr_min: float = UNEXPLAINED_SNR_MIN,
                       local_half_width: float = UNEXPLAINED_LOCAL_HALF_WIDTH
                       ) -> list[UnexplainedPeak]:
    """从残差里找模型未解释的正峰。

    残差 = 实测 − 计算（**不含背景** —— 背景已在 y_calc 里）。取残差的局部
    正极大，且同时满足两个门槛：

    1. **绝对显著性**：`residual ≥ rel_min × 实测最强峰`；
    2. **局部信噪比**：`residual ≥ snr_min × 局部稳健噪声σ(MAD)`。

    只用第 1 条不够 —— 计数噪声下最强峰处的 σ 本身就有峰值的 1% 量级；
    只用第 2 条也不够 —— 模型整体偏差大时会把噪声当信号。两条并用，
    既能抓到 10 wt% 残碱这类弱峰（最强峰仅主峰的 1.5%），又不误报噪声。
    """
    from scipy.signal import find_peaks as _sp_find_peaks

    from ncm.core.smooth import SmoothConfig, savitzky_golay

    tt = np.asarray(two_theta, dtype=np.float64)
    yo = np.asarray(y_obs, dtype=np.float64)
    yc = np.asarray(y_calc, dtype=np.float64)
    if not (tt.shape == yo.shape == yc.shape) or tt.size < 5:
        return []
    resid = yo - yc
    if smooth_window and smooth_window % 2 == 0:
        raise ValueError(f"平滑窗口必须为奇数: {smooth_window}")
    if smooth_window and smooth_window >= 3:
        resid = savitzky_golay(resid, SmoothConfig(enabled=True,
                                                   window=smooth_window,
                                                   polyorder=2))
    scale = float(np.max(yo)) if yo.size else 0.0
    if scale <= 0:
        return []
    idx, _ = _sp_find_peaks(resid, prominence=0.0)
    out = []
    for i in idx:
        h = float(resid[i])
        if h <= 0:
            continue
        rel = h / scale
        if rel < rel_min:
            continue
        sigma = _local_sigma(resid, tt, float(tt[i]), local_half_width)
        if h < snr_min * sigma:
            continue
        out.append(UnexplainedPeak(float(tt[i]), rel))
    out.sort(key=lambda p: -p.height)
    return out


def suggest_impurities(unexplained: list[UnexplainedPeak],
                       candidates=None, *,
                       tol: float = MATCH_TOL_DEG
                       ) -> list[ImpuritySuggestion]:
    """按未解释峰给出可能的杂质相建议。

    对每个候选相，收集其理论峰位落在未解释峰附近的匹配对，按命中数与
    命中强度排序。命中 0 的候选不列出。
    """
    from ncm.core.peaks import WAVELENGTH_KA1, reflections

    cands = candidates if candidates is not None else builtin_impurities()
    out: list[ImpuritySuggestion] = []
    for slot in cands:
        refl = reflections(slot.structure, WAVELENGTH_KA1, 10.0, 90.0)
        matched: list[tuple[float, float]] = []
        strength = 0.0
        used = set()
        for up in unexplained:
            best = None
            for r in refl:
                if abs(r.two_theta - up.two_theta) > tol:
                    continue
                if best is None or abs(r.two_theta - up.two_theta) < \
                        abs(best.two_theta - up.two_theta):
                    best = r
            if best is None:
                continue
            key = round(best.two_theta, 3)
            if key in used:
                continue
            used.add(key)
            matched.append((up.two_theta, best.two_theta))
            strength += up.height
        if matched:
            out.append(ImpuritySuggestion(name=slot.name,
                                          formula=slot.formula,
                                          hits=len(matched),
                                          matched=tuple(matched),
                                          strength=strength))
    out.sort(key=lambda s: (-s.hits, -s.strength))
    return out

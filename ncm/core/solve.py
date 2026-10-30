"""NCM 精修求解层（T1.4）。

把「读 CIF → 读谱 → 配参数 → 跑精修 → 收结果」封成一个函数，供 CLI 与 GUI 共用。
GUI 不应该直接拼 `RefineConfig`，否则两处默认值会慢慢漂开。

**golden 基线的一致性靠这里**：`standard_options()` 是所有默认值的唯一出处，
`tests/test_golden.py` 用它复现 `Rwp = 7.87%`。改这个函数 = 动基线，必须开卡。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ncm.core import constants as C
from ncm.core.dtypes import Pattern
from ncm.core.patterns import load_pattern
from ncm.core.profile.cif import CifStructure, parse_cif_string
from ncm.core.profile.forward import ProfileParams
from ncm.core.refine.nonlinear import RefineConfig, RefineResult, refine

#: 峰形初值（golden 基线配套）。NCM 实验室谱（Cu Kα，步长 0.02°）的经验起点。
DEFAULT_PRM = ProfileParams(
    zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6,
    anode="Cu", ka_ratio=0.5, asym=0.0, bfactor=0.0,
)


@dataclass(frozen=True)
class SolveOptions:
    """一次精修的全部开关。默认值见 `standard_options()`。"""

    tmin: float = C.DEFAULT_TMIN
    tmax: float = C.DEFAULT_TMAX
    n_bg: int = C.DEFAULT_N_BG
    max_iter: int = C.DEFAULT_MAX_ITER
    bg_mode: str = C.DEFAULT_BG_MODE

    refine_zero: bool = True
    refine_uvw: bool = True
    refine_eta: bool = True
    refine_cell: bool = True
    refine_asym: bool = True
    refine_bfactor: bool = True
    refine_po: bool = False
    # ---- TCH 尺寸/应变（T2.1）。默认关，golden 不受影响。 ----
    refine_size: bool = False       # 精修 Y（Kλ/D）
    refine_strain: bool = False     # 精修 X（4ε）
    X: float = 0.0                  # 应变初值（度）
    Y: float = 0.0                  # 尺寸项初值（度）
    # ---- 择优取向（T3.3）。None = 不启用；如 {"NCM811": (0,0,1,1.0)} ----
    po_r: dict | None = None

    anode: str = "Cu"
    wavelength: float | None = None     # None = 由 anode 决定（含 Kα1/α2 双线）

    def to_refine_config(self, **extra) -> RefineConfig:
        # TCH 生效时逐峰 η 由 (ΓG, ΓL) 决定，prm.eta 被前向忽略 —— 此时再精修
        # eta 是纯浪费的自由度（且会拖慢 LM），故强制关闭。
        tch_on = self.refine_size or self.refine_strain or self.X or self.Y
        return RefineConfig(
            refine_zero=self.refine_zero,
            refine_uvw=self.refine_uvw,
            refine_eta=False if tch_on else self.refine_eta,
            n_bg=self.n_bg,
            max_iter=self.max_iter,
            tmin=self.tmin,
            tmax=self.tmax,
            bg_mode=self.bg_mode,
            refine_asym=self.refine_asym,
            refine_bfactor=self.refine_bfactor,
            refine_cell=self.refine_cell,
            refine_po=self.refine_po,
            refine_size=self.refine_size,
            refine_strain=self.refine_strain,
            **extra,
        )

    def to_profile_params(self) -> ProfileParams:
        """构造精修的峰形初值。

        NCM 修改（T6.4d）：TCH 尺寸/应变项在**开启精修但未显式给初值**时，
        自动取 `constants.TCH_SIZE_INIT_Y` / `TCH_STRAIN_INIT_X` —— 不能
        用 0，因为 0 恰是参数下界，LM 的中心差分雅可比会在越界试探点上
        失真，导致参数推不离下界（实测 Y 恒为 0，晶粒尺寸误报"超出检出
        上限"）。显式给了初值（`self.Y`/`self.X`）则以调用方为准。
        """
        base = DEFAULT_PRM
        Y = self.Y
        X = self.X
        if self.refine_size and Y <= 0.0:
            Y = C.TCH_SIZE_INIT_Y
        if self.refine_strain and X <= 0.0:
            X = C.TCH_STRAIN_INIT_X
        if self.wavelength is not None:
            return ProfileParams(
                zero=base.zero, U=base.U, V=base.V, W=base.W, eta=base.eta,
                anode=None, ka_ratio=base.ka_ratio, wavelength=self.wavelength,
                asym=base.asym, bfactor=base.bfactor,
                X=X, Y=Y, po_r=self.po_r,
            )
        return ProfileParams(
            zero=base.zero, U=base.U, V=base.V, W=base.W, eta=base.eta,
            anode=self.anode, ka_ratio=base.ka_ratio, asym=base.asym,
            bfactor=base.bfactor, X=X, Y=Y, po_r=self.po_r,
        )


def standard_options() -> SolveOptions:
    """**golden 基线用的标准配方**。改它就要重出 golden。"""
    return SolveOptions()


def load_structure(cif_path: str | Path) -> CifStructure:
    """从磁盘读一份 CIF 结构。"""
    p = Path(cif_path)
    if not p.exists():
        raise FileNotFoundError(f"CIF 不存在: {p}")
    return parse_cif_string(p.read_text(encoding="utf-8", errors="replace"),
                            p.stem)


def builtin_structure(name: str) -> CifStructure:
    """读内置 CIF（写在包内 `ncm/data/cif/`）。"""
    cif_dir = Path(__file__).resolve().parents[1] / "data" / "cif"
    key = name if name.lower().endswith(".cif") else f"{name}.cif"
    return load_structure(cif_dir / key)


@dataclass
class SolveResult:
    """精修结果 + 复现它所需的全部上下文。"""

    result: RefineResult
    structure: CifStructure
    pattern: Pattern
    options: SolveOptions
    cell: tuple[float, float, float, float, float, float]

    @property
    def a(self) -> float:
        return self.cell[0]

    @property
    def c(self) -> float:
        return self.cell[2]

    @property
    def c_over_a(self) -> float:
        return self.cell[2] / self.cell[0]

    @property
    def volume(self) -> float:
        """**精修后**晶胞体积（不是 CIF 起始体积）。"""
        import math

        a, b, c, al, be, ga = self.cell
        al, be, ga = (math.radians(v) for v in (al, be, ga))
        return a * b * c * math.sqrt(max(0.0,
            1 - math.cos(al) ** 2 - math.cos(be) ** 2 - math.cos(ga) ** 2
            + 2 * math.cos(al) * math.cos(be) * math.cos(ga)))

    @property
    def structure_scaled(self) -> CifStructure:
        """施加精修晶胞后的结构（原子分数坐标不变）。

        第二段精修（占位/z_O 等）必须用它，否则峰位整体错开
        （refine_cell 时 ±1%，实测 Rwp 3% -> 22%）。"""
        return CifStructure(self.structure.name, tuple(self.cell),
                            self.structure.atoms)

    @property
    def rwp(self) -> float:
        return float(self.result.rf.rwp)

    def as_dict(self) -> dict:
        """扁平化输出（CLI JSON / golden 基线 / 报告都用它）。"""
        p = self.result.params
        return {
            "rwp": round(float(self.result.rf.rwp), 4),
            "rp": round(float(self.result.rf.rp), 4),
            "rexp": round(float(self.result.rf.rexp), 4),
            "gof": round(float(self.result.rf.rwp / self.result.rf.rexp), 4)
            if self.result.rf.rexp else None,
            "rbragg": self.result.rf.rbragg,
            "a": round(self.a, 6),
            "c": round(self.c, 6),
            "c_over_a": round(self.c_over_a, 5),
            "volume": round(self.volume, 3),
            "zero": round(p.zero, 5),
            "U": round(p.U, 6), "V": round(p.V, 6), "W": round(p.W, 6),
            "eta": round(p.eta, 4),
            "asym": round(p.asym, 5),
            "bfactor": round(p.bfactor, 4),
            "iters": self.result.iters,
            "success": bool(self.result.success),
        }


def solve(pat: Pattern, structure: CifStructure,
          options: SolveOptions | None = None, *,
          init_params: ProfileParams | None = None, **cfg_extra) -> SolveResult:
    """跑一次单相全谱精修。

    pat 必须是**原始谱**（未经平滑/去 Kα2/扣背景）—— 见 `preprocess.for_refinement`。

    NCM 修改（T6.4d）：新增可选入参 `init_params`（峰形初值）。
    - 为 None：初值取 `options.to_profile_params()`（原行为，逐位不变）；
    - 给定：以它为初值（`options` 仍决定**哪些自由度被精修**）。

    用途：两段峰形精修 —— 先把择优取向/峰形稳定，再以稳定解为起点放开
    TCH 尺寸项。实测真实 NCM811 样品：PO 与 TCH 尺寸项**一次性同开**会
    落入坏解（Rwp 3.87%、U 触下界 0），而分段后 Rwp 3.158%、D = 155 nm。
    """
    opt = options or standard_options()
    focused = _focus(pat, opt)
    cfg = opt.to_refine_config(**cfg_extra)
    prm0 = init_params if init_params is not None else opt.to_profile_params()
    res = refine([structure], focused, prm0, cfg)
    res = _with_bragg_r(res, structure, focused, opt)

    fa, fc = res.cell_scales[0] if res.cell_scales else (1.0, 1.0)
    a, b, c, al, be, ga = structure.cell
    cell = (a * fa, b * fa, c * fc, al, be, ga)
    return SolveResult(result=res, structure=structure, pattern=focused,
                       options=opt, cell=cell)


def _with_bragg_r(res: RefineResult, structure: CifStructure,
                  pat: Pattern, opt: SolveOptions) -> RefineResult:
    """精修后补算 Bragg R 因子（填 `RFactors.rbragg`）。

    必须用**缩放后晶胞**（refine_cell 时峰位移动 ±1%）—— 与第二段占位
    精修同一个教训。
    """
    from dataclasses import replace

    from ncm.core.refine.linear import background_basis
    from ncm.core.refine.rbragg import (
        bragg_r_factor,
        collect_peaks,
        profile_eta,
        profile_fwhm,
    )

    fa, fc = res.cell_scales[0] if res.cell_scales else (1.0, 1.0)
    a, b, c, al, be, ga = structure.cell
    scaled = CifStructure(structure.name, (a * fa, b * fa, c * fc, al, be, ga),
                          structure.atoms)
    coeffs = np.asarray(res.bg, dtype=np.float64).ravel()
    bg = (background_basis(pat.two_theta, coeffs.size, opt.bg_mode) @ coeffs
          if coeffs.size else np.zeros_like(pat.intensity))
    peaks = collect_peaks(scaled, res.params, opt.tmin, opt.tmax)
    rb = bragg_r_factor(pat.two_theta, pat.intensity, res.ycalc, bg, peaks,
                        profile_fwhm(res.params),
                        eta_func=profile_eta(res.params))
    return replace(res, rf=replace(res.rf, rbragg=rb.rbragg))


def _focus(pat: Pattern, opt: SolveOptions) -> Pattern:
    """按 2θ 区间裁剪（精修区间与判定门需要的最强峰范围不同）。"""
    m = (pat.two_theta >= opt.tmin) & (pat.two_theta <= opt.tmax)
    if not m.any():
        raise ValueError(f"2θ 区间 {opt.tmin}–{opt.tmax}° 内无数据点"
                         f"（谱范围 {pat.two_theta[0]:.2f}–{pat.two_theta[-1]:.2f}°）")
    return Pattern(two_theta=pat.two_theta[m].copy(),
                   intensity=pat.intensity[m].copy(), meta=dict(pat.meta))


def load_sample(path: str | Path) -> Pattern:
    """读谱（多格式，走 vendor 读谱器）。"""
    return load_pattern(path)


def residual_arrays(sr: SolveResult) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 (2θ, 观测, 计算) —— 作图用，长度一致。"""
    y = sr.pattern.intensity
    yc = np.asarray(sr.result.ycalc, dtype=np.float64)
    return sr.pattern.two_theta, y, yc


def background_curve(sr: SolveResult) -> np.ndarray:
    """把 `result.bg` 的**系数**展开成**曲线**。

    注意 `RefineResult.bg` 是背景基函数的系数向量（长度 = n_bg），不是逐点强度。
    作图/报告里要的逐点背景必须经基函数还原 —— 传错会得到长度 8 的数组
    （T1.4 首跑即踩过）。
    """
    from ncm.core.refine.linear import background_basis

    coeffs = np.asarray(sr.result.bg, dtype=np.float64).ravel()
    if coeffs.size == 0:
        return np.zeros_like(sr.pattern.intensity)
    basis = background_basis(sr.pattern.two_theta, coeffs.size,
                             sr.options.bg_mode)
    return basis @ coeffs

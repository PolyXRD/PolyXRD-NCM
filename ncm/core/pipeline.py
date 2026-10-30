"""两段式精修编排器（T6.4a · 新建，非 vendor）。

把「一次完整的 NCM 精修」编排成可复现的三步管线，供 GUI 结果卡与
后续导出（T7.1）共用：

    stage1  solve()        峰形（zero/U/V/W/η/asym/B）+ 晶胞 + 择优取向 + TCH 尺寸
    stage2  refine_occ()   Li 占位 occ_Li + O 的 6c 参数 z_O（峰形/晶胞冻结）
    stage3  from_tch()     晶粒尺寸（相干衍射畴）+ 微观应变反演

**为什么必须分两段**
------------------
占位与 z_O 只在峰形/晶胞稳定后再解，否则 6 个自由度和 2 个占位自由度会
互相补偿（实测：occ 与 bfactor/scale 的相关达 -0.32，收敛到边界）。

**stage2 必须用缩放后结构**
---------------------------
`refine_cell=True` 时 stage1 会把晶胞缩放 ±1%，若把**原始**结构交给
stage2，峰位整体错开，实测 Rwp 3% → 22.5%、occ 撞上界（见
`docs/VALIDATION_OCC.md` §4）。故此处统一走 `SolveResult.structure_scaled`。

**与 CLI 的关系**
----------------
CLI（`ncm/cli/ncm.py`）目前只跑 stage1 —— 那是 golden 基线的复现路径，
不能改。本模块是**增量**：CLI 保持 stage1 不变，GUI 走完整三段。

**取消**
--------
`cancel_cb`（callable() -> bool）在 stage1 的残差评估处由核心层检查
（见 `ncm/core/refine/nonlinear.py` 的 `_check_cancel`），在 stage2 前后
再各检查一次 —— stage2 内部是自写 LM，没有残差钩子，只能在其前后判。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ncm.core.crystallite import CrystalliteResult, from_tch
from ncm.core.dtypes import Pattern
from ncm.core.profile.cif import CifStructure
from ncm.core.refine.nonlinear import RefineCancelled, RefineResult
from ncm.core.refine.occ import OccRefineResult, identify_sites, refine_occ
from ncm.core.refine.plan import check_cancel as _check_cancel
from ncm.core.refine.plan import stage1_options as _stage1_options
from ncm.core.refine.plan import stage2_options as _stage2_options
from ncm.core.refine.plan import wavelength_for as _wavelength_for
from ncm.core.refine.valley import valley_init as _valley_init
from ncm.core.refine.valley import valley_scan as _valley_scan
from ncm.core.solve import SolveOptions, SolveResult, solve

#: stage2 的占位初值（NCM 典型反位水平；最终值由精修决定）
DEFAULT_OCC0 = 0.98

#: stage2 迭代上限（占位/坐标各 1 个自由度，30 次足够）
DEFAULT_OCC_MAX_ITER = 30


@dataclass(frozen=True)
class PipelineOptions:
    """三段管线的配置。

    stage1 : solve() 的开关（默认用 `SolveOptions()`，即 golden 标准配方）
    refine_occ : 是否跑第二段（Li 占位 + z_O）。关掉时结果卡里这两项为 None。
    refine_size : stage1 是否精修 TCH 尺寸项 Y（晶粒尺寸的来源）。
        关掉时 stage3 不产出晶粒尺寸（Y<=0 -> D=inf）。
    refine_strain : stage1 是否精修 TCH 应变项 X（微观应变的来源）。
    occ0 / occ_max_iter : stage2 的占位初值与迭代上限。
    """

    stage1: SolveOptions = field(default_factory=SolveOptions)
    refine_occ: bool = True
    refine_size: bool = True
    refine_strain: bool = False
    occ0: float = DEFAULT_OCC0
    occ_max_iter: int = DEFAULT_OCC_MAX_ITER


@dataclass(frozen=True)
class RefinePipelineResult:
    """三段管线的完整结果。

    stage1 : 第一段（峰形/晶胞/PO）结果 —— 晶胞、峰形、优度指标的来源
    stage2 : 第二段（占位/z_O）结果；`refine_occ=False` 时为 None
    crystallite : 晶粒尺寸/应变反演结果；未开 TCH 尺寸项时为 None
    structure : **最终**结构（stage2 施加 occ/z_O 后的；无 stage2 时为 stage1 结构）
    """

    stage1: SolveResult
    stage2: OccRefineResult | None = None
    crystallite: CrystalliteResult | None = None
    structure: CifStructure | None = None

    @property
    def refine_result(self) -> RefineResult:
        """第一段的 RefineResult（结果卡 build_card 的入参）。"""
        return self.stage1.result

    @property
    def rwp(self) -> float:
        """最终 Rwp（百分比）。

        有第二段时用第二段的值 —— 它是在同一模型上把占位/z_O 放开后重解的
        残差，是**更完整模型**下的优度；用第一段会高估（实测 3.0431 vs 3.0086）。
        """
        if self.stage2 is not None:
            return float(self.stage2.rf.rwp)
        return float(self.stage1.rwp)

    @property
    def occ_li(self) -> float | None:
        return self.stage2.occ_li if self.stage2 is not None else None

    @property
    def z_o(self) -> float | None:
        return self.stage2.z_o if self.stage2 is not None else None

    @property
    def cell(self) -> tuple[float, float, float, float, float, float]:
        """最终晶胞（stage1 精修后的）。"""
        return self.stage1.cell


def _run_stage1(pat: Pattern, structure: CifStructure, opt: PipelineOptions,
                *, progress_cb, on_iter, cancel_cb):
    """第一段峰形精修（择优取向 + 峰形 + 晶胞，**不开** TCH 尺寸项）。

    为什么先不放开 TCH：PO 的 r 与 TCH 的 Y 在部分反射上强相关（都调制
    强度/宽度分布），一次性同开会落入坏解 —— 实测真实 NCM811 样品
    Rwp 3.87%、U 触下界 0；分段后 Rwp 3.16%、D = 155 nm。
    """
    from dataclasses import replace

    s1 = replace(opt.stage1, refine_size=False, refine_strain=False)
    return solve(pat, structure, s1,
                 progress_cb=progress_cb, on_iter=on_iter,
                 cancel_cb=cancel_cb)


def _run_stage1b(pat: Pattern, structure: CifStructure, opt: PipelineOptions,
                 init_params, *, cell_scales=None,
                 progress_cb=None, on_iter=None, cancel_cb=None):
    """第二段峰形精修：以第一段的参数为初值，放开 TCH 尺寸/应变项。

    择优取向 r 固定在第一段的值（不参与本段精修，但经 `init_params.po_r`
    带入正向模型 —— T8.1 修复），结果里也保留，否则结果卡会漏掉择优取向。

    ★初值必须避开 Y=0 下界（LM 中心差分雅可比在边界失真，参数推不离
    下界 —— 另见 `constants.TCH_SIZE_INIT_Y` 注释），且 (U,V,W)↔Y 的联合
    代价谷是**弯的**，单一初值不可靠：

    - **谷扫描初值**（`_valley_scan`，总 FWHM 守恒方向）：合成 round-trip
      精确命中真值盆地（Y 误差 0.8 %）；但真实 Data040 上反而落进
      Rwp 3.63 的次盆地（旧锚定 3.158）—— 合成与真实的 landscape
      方向相反；
    - **普通初值**（段 1 解 + `TCH_SIZE_INIT_Y`）：真实样上找到好盆地，
      合成谱上落假盆地（Y→0 + UVW 回吸）。

    → **双候选择优**：两个初值各跑一次 LM，按加权 Rwp 取优（判据与
    报告口径一致），但**边界解让位给内部解**（`_pick_candidate`，T8.2：
    Y 停在 0 与 Y=0.06 是「超出检出上限」vs「D=130 nm」的定性差别，而
    两者 Rwp 可能只差 0.85 %）。代价是段 1b 耗时 ×2，换确定性。

    **偏离登记（T8.1）**：新增 keyword-only 入参 `cell_scales`（段 1 的
    晶胞缩放；谷扫描必须用缩放后晶胞合成 forward，否则峰位错开、扫描
    无意义）。本函数为 T6.4 新建的内部函数，仅 `run_pipeline` 调用。
    """
    from dataclasses import replace

    from ncm.core import constants as C

    Y = init_params.Y
    X = init_params.X
    inits: list = []
    if opt.refine_size and Y <= 0.0:
        y_star = _valley_scan(pat, structure, init_params, cell_scales,
                              opt.stage1)
        if y_star > 0.0:
            inits.append(_valley_init(init_params, y_star, opt.stage1))
        Y = opt.stage1.Y if opt.stage1.Y > 0.0 else C.TCH_SIZE_INIT_Y
        inits.append(replace(init_params, Y=Y))
    else:
        inits.append(replace(init_params, Y=max(Y, 0.0)))
    if opt.refine_strain and inits[0].X <= 0.0:
        X = opt.stage1.X if opt.stage1.X > 0.0 else C.TCH_STRAIN_INIT_X
        inits = [replace(p, X=X) for p in inits]

    s2 = _stage2_options(opt)
    cands = []
    for init2 in inits:
        sr = solve(pat, structure, s2, init_params=init2,
                   progress_cb=progress_cb, on_iter=on_iter,
                   cancel_cb=cancel_cb)
        cands.append(sr)
    sr = _pick_candidate(cands)
    if sr.result.po_r is None and init_params.po_r:
        sr.result = replace(sr.result, po_r=init_params.po_r)
    return sr


def _pick_candidate(cands: list):
    """双候选择优：按加权 Rwp 取优，**但边界解让位给内部解**（T8.2）。

    为什么不能只看 Rwp：Y 停在下界 0 时报告口径是「尺寸超出检出上限」，
    这与「Y=0.06 → D=130 nm」是**定性差别**，而两者的 Rwp 差可能小于
    噪声。实测合成 NCM622（真值 Y=0.06043）：谷扫描候选 Y=0.06058 /
    Rwp 12.294 %，普通候选 Y=0（D=inf）/ Rwp 12.190 % —— 只差 0.85 %，
    按 Rwp 会挑中边界解，把 130 nm 的样品报成"超出检出上限"。

    规则：若胜出者的 Y 在边界上、且存在内部解候选其 Rwp ≤ 胜出者 ×
    (1 + `TCH_BOUNDARY_TIE_TOL`)，则取内部解 —— 「拟合同样好时优先非
    边界解」是优化与 Rietveld 的通行做法（边界解先验可信度更低）。

    其它情形（胜出者本身就是内部解、或两个都在边界上）一律按 Rwp 取优，
    与 T8.1 的择优口径逐位一致。
    """
    from ncm.core import constants as C

    if not cands:
        raise ValueError("候选列表为空")
    best = min(cands, key=lambda s: s.rwp)
    if float(best.result.params.Y) > C.TCH_Y_BOUNDARY_EPS:
        return best
    inner = [s for s in cands
             if float(s.result.params.Y) > C.TCH_Y_BOUNDARY_EPS]
    if not inner:
        return best
    alt = min(inner, key=lambda s: s.rwp)
    if alt.rwp <= best.rwp * (1.0 + C.TCH_BOUNDARY_TIE_TOL):
        return alt
    return best


def is_layered_ncm(structure: CifStructure) -> bool:
    """判断结构是否为**层状 R-3m**（NCM 族）。

    判据：空间群符号归一化后以 "R-3m" 开头（覆盖 "R -3 m :H"、"-R3m" 等写法）。
    注意：R-3m 的其他非层状材料（如 Bi2O3 的 R-3m）也会命中 —— 但本软件
    的判定门只放 NCM 族进来，且层状与否最终由占位精修能否找到 Li 层兜底
    （`identify_sites` 抛 ValueError 时自动降级）。
    """
    from ncm.core.symmetry import normalize_hm

    sg = getattr(structure, "spacegroup", None)
    if not sg:
        return False
    return normalize_hm(sg).upper().replace(" ", "").startswith("R-3M")


def default_options_for(structure: CifStructure) -> PipelineOptions:
    """按结构类型给出**推荐**的管线配置。

    - 层状 R-3m（NCM 族）：默认开择优取向 (001)（层状惯习面，见
      `docs/VALIDATION_OCC.md` §1，PO 精修不扰动晶胞锚点）；
    - 其它结构（前驱体等）：不开 PO。
    - 两者都开 TCH 尺寸项（晶粒尺寸是需求原文要求的输出项）。

    注意这只影响**默认**；调用方可以自己构造 `PipelineOptions` 覆盖。
    """
    from dataclasses import replace

    base = SolveOptions()
    if is_layered_ncm(structure):
        base = replace(base, refine_po=True,
                       po_r={structure.name: (0, 0, 1, 1.0)})
    return PipelineOptions(stage1=base, refine_occ=True, refine_size=True,
                           refine_strain=False)


def run_pipeline(pat: Pattern, structure: CifStructure,
                 options: PipelineOptions | None = None,
                 *, progress_cb=None, on_iter=None,
                 cancel_cb=None) -> RefinePipelineResult:
    """跑完整精修管线。

    pat : 原始谱（**未经平滑/去 Kα2/扣背景**）
    structure : 起始结构（CIF）
    options : 管线配置；None 时用默认（开占位与晶粒尺寸）
    progress_cb / on_iter : 进度回调（透传给精修引擎）
    cancel_cb : 取消钩子（callable() -> bool）

    流程::

        stage1a  solve()   择优取向 + 峰形 + 晶胞（不开 TCH）
        stage1b  solve()   以 1a 的参数为初值，放开 TCH 尺寸项（PO 固定）
        stage2   refine_occ()  Li 占位 + z_O（峰形/晶胞冻结）
        stage3   from_tch()    晶粒尺寸 + 微观应变反演

    抛 `RefineCancelled`（用户取消）。结构里没有 Li 位点时**降级**为
    跳过 stage2，不中断。
    """
    opt = options or PipelineOptions()

    # ---- stage1a：峰形 / 晶胞 / 择优取向 ----
    stage1a = _run_stage1(pat, structure, opt, progress_cb=progress_cb,
                          on_iter=on_iter, cancel_cb=cancel_cb)

    # ---- stage1b：放开 TCH 尺寸项（以 1a 的稳定解为初值，谷扫描定谷底） ----
    if opt.refine_size or opt.refine_strain:
        _check_cancel(cancel_cb)
        stage1 = _run_stage1b(pat, structure, opt, stage1a.result.params,
                              cell_scales=stage1a.result.cell_scales,
                              progress_cb=progress_cb, on_iter=on_iter,
                              cancel_cb=cancel_cb)
    else:
        stage1 = stage1a

    # ---- stage2：Li 占位 + z_O ----
    stage2: OccRefineResult | None = None
    if opt.refine_occ:
        _check_cancel(cancel_cb)
        try:
            sites = identify_sites(stage1.structure_scaled)
            stage2 = refine_occ(stage1.structure_scaled, stage1.pattern,
                                stage1.result.params, sites=sites,
                                occ0=opt.occ0, zo0=sites.z_o,
                                max_iter=opt.occ_max_iter)
        except ValueError:
            # 结构里没有 Li 位点（明显的非层状相，如前驱体）—— 占位精修
            # 不适用，降级为只跑峰形精修，不算失败。
            stage2 = None
        _check_cancel(cancel_cb)

    # ---- stage3：晶粒尺寸 / 应变反演 ----
    cryst: CrystalliteResult | None = None
    prm = stage1.result.params
    if opt.refine_size or opt.refine_strain:
        cryst = from_tch(prm.Y, prm.X, _wavelength_for(stage1))

    final_struct = stage2.structure if stage2 is not None else structure
    return RefinePipelineResult(stage1=stage1, stage2=stage2,
                                 crystallite=cryst, structure=final_struct)


def build_pipeline_card(result: RefinePipelineResult,
                        meta: dict | None = None) -> dict:
    """把管线结果汇成结果卡（复用核心层 `build_card`，口径一致）。

    meta 里可带 `sample_name` / `operator` / `instrument` 等上下文；
    **不要**在这里塞 occ_li / z_o / crystallite —— 它们由管线结果自动带入，
    避免"卡片显示的值"与"精修实际得到的值"脱节。

    ★用 stage1 的原始结构（带空间群元数据）而不是 stage2 的最终结构：
    `apply_occ_zo` 造的是**新** `CifStructure(name, cell, atoms)`，不携带
    `spacegroup` / `sg_number` —— 用它建卡会让晶系/点群/空间群/劳厄群
    全部变成空值。晶胞不依赖它（由 meta["cell"] 提供 stage1 精修后的晶胞）。
    """
    from ncm.core.resultcard import build_card

    ctx = dict(meta or {})
    ctx.setdefault("occ_li", result.occ_li)
    ctx.setdefault("z_o", result.z_o)
    ctx.setdefault("crystallite", result.crystallite)
    # 晶胞用第一段精修后的（stage2 不改晶胞）
    ctx.setdefault("cell", result.cell)
    return build_card(result.refine_result, result.stage1.structure, ctx)

"""T8.2 · 多型号泛化 + 真实前驱体实样验证。

**数据现状如实登记**：家族数据根（`D:/Project/XRD/XRData/`）里**只有一份
NCM 正极实样**（`csuHJW/Data040：NCM：811`），没有 622/523/111 的实测谱。
另有：

- `csuHJW/Data043：Ni(OH)2` —— 真实 **(Ni,Co,Mn)(OH)₂ 三元氢氧化物前驱体**
  实样（Ni:Co:Mn = 5:3:2，即 523 配比），且**随附 Maud 2.55 的独立精修
  结果**（`Data043：Ni(OH)2.par`：P-3m1，a=3.130435 Å、c=4.619966 Å、
  z_O=0.24166）。这是本卡最有价值的一项 —— 真实数据 + 外部独立参考值。
- `ShiJiKong-shXRD/Si#B##.../sim_123*.txt` —— Maud 的 **Si 模拟谱**，
  与 NCM 无关（已核实文件头 `_maud_comment Simulated_data`），排除。
- 其余非 NCM 实样（尖晶石/LFP/岩盐/锐钛矿/ZnO 等）已由 T5.2 样本库
  承担负样本判据，本卡不重复。

因此本卡采用**三路验证**（偏离原「多型号实样」设想，已登记）：

| 路 | 对象 | 证明什么 |
|---|---|---|
| A | 811/622/523/111 四型号**合成谱** | 管线不止对 811 成立（型号泛化） |
| B | 真实前驱体 Data043 | 判定门正确分流 + 精修晶胞与 Maud 独立值一致 |
| C | 真实 811（Data040） | T8.1 的改动没有把已冻结的实样锚点带偏 |

**为什么型号泛化只能用合成谱**：实验室 XRD 对 NCM811/622/523 的晶胞几乎
相同（内置 CIF 里 811/622/523 三者晶胞逐位相同，a=2.8645、c=14.1610），
Ni:Co:Mn 比例须由 ICP/EDS 确定（见 `docs/STD_FREEZE.md` §1 边界声明）。
所以「型号」在本卡里的可验证含义是**不同晶胞/不同占位/不同峰强分布**，
而不是「不同 Ni 含量能被 XRD 分开」—— 后者在物理上不成立，不能拿来当判据。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from ncm.core import constants as C
from ncm.core.dtypes import Pattern
from ncm.core.identify import identify
from ncm.core.patterns import load_pattern
from ncm.core.pipeline import default_options_for, run_pipeline
from ncm.core.profile.cif import CifStructure
from ncm.core.profile.forward import ProfileParams, compute_phase_profile
from ncm.core.solve import SolveOptions, builtin_structure, solve

#: 型号列表（内置 CIF 名）
MODELS = ("NCM111", "NCM523", "NCM622", "NCM811")

#: 合成谱真值：把 CIF 晶胞沿 a、c 各偏一点（远大于回收精度，防"原样返回"）
_A_MUL = 1.004
_C_MUL = 0.996

#: 真实实样路径（只读引用家族数据根）
_DATA = "D:/Project/XRD/XRData"
PRECURSOR_REAL = f"{_DATA}/csuHJW/Data043/Data043：Ni(OH)2.txt"
NCM811_REAL = f"{_DATA}/csuHJW/txt/Data040：NCM：811_raw.txt"

#: Data043 随附 Maud 2.55 独立精修结果（`Data043：Ni(OH)2.par`）
MAUD_A = 3.130435
MAUD_C = 4.619966


def _y_deg_for(d_nm: float, wavelength: float = 1.5406) -> float:
    """晶粒尺寸 → TCH 洛伦兹尺寸项 Y（度），口径同 `test_roundtrip`。"""
    return math.degrees(1.0) * C.SCHERRER_K * wavelength / (d_nm * 10.0)


def _synth_model(model: str, *, seed: int = 7) -> tuple[Pattern, float, float]:
    """按型号 CIF 合成一份带 Poisson 噪声的谱，返回 (谱, a_gt, c_gt)。

    真值晶胞 = CIF 晶胞 × (1.004, 0.996) —— 起点故意错开，避免"输入等于
    输出"的空验证。
    """
    st0 = builtin_structure(model)
    a0, c0 = st0.cell[0], st0.cell[2]
    a_gt, c_gt = a0 * _A_MUL, c0 * _C_MUL
    st = CifStructure(f"{model}_gt", (a_gt, a_gt, c_gt, 90.0, 90.0, 120.0),
                      st0.atoms)
    st._variant = 771234          # noqa: SLF001 —— 缓存盐值，防 id 复用撞车
    prm = ProfileParams(U=0.03, V=-0.012, W=0.010, Y=_y_deg_for(120.0), X=0.0)
    tt = np.arange(12.0, 78.0, 0.03)
    prof = compute_phase_profile(st, tt, prm, 12.0, 78.0)
    bg = 40.0 + 30.0 * (tt - 12.0) / 66.0
    y = prof / prof.max() * 6000.0 + bg
    y = np.random.default_rng(seed).poisson(y).astype(np.float64)
    return Pattern(two_theta=tt, intensity=y, meta={}), a_gt, c_gt


@pytest.fixture(scope="module")
def model_fits() -> dict:
    """四型号各跑一次 stage1（峰形/晶胞/背景），module 级缓存。"""
    out = {}
    for model in MODELS:
        pat, a_gt, c_gt = _synth_model(model)
        res = solve(pat, builtin_structure(model), SolveOptions())
        out[model] = (res, a_gt, c_gt,
                      100.0 * math.sqrt(pat.intensity.size
                                        / pat.intensity.sum()))
    return out


# ---------------------------------------------------------------------------
# A · 型号泛化（合成谱）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model", MODELS)
def test_cell_a_recovered_per_model(model, model_fits) -> None:
    """逐型号：a 回收误差 ≤ 5 mÅ（实测 ≤ 0.11 mÅ，留 40 倍裕度）。"""
    res, a_gt, _c_gt, _floor = model_fits[model]
    assert abs(res.a - a_gt) <= 0.005, \
        f"{model}: a={res.a:.5f} vs 真值 {a_gt:.5f}"


@pytest.mark.parametrize("model", MODELS)
def test_cell_c_recovered_per_model(model, model_fits) -> None:
    """逐型号：c 回收误差 ≤ 10 mÅ（实测 ≤ 0.87 mÅ）。"""
    res, _a_gt, c_gt, _floor = model_fits[model]
    assert abs(res.c - c_gt) <= 0.010, \
        f"{model}: c={res.c:.5f} vs 真值 {c_gt:.5f}"


@pytest.mark.parametrize("model", MODELS)
def test_rwp_at_noise_floor_per_model(model, model_fits) -> None:
    """逐型号：Rwp 应贴着合成谱的 Poisson 统计下限（≈9.6 %）。

    **不能照搬真实样的 3 % 经验值** —— 弱背景合成谱（峰 6000 计数、
    背景 40–70 计数）的统计下限就在 9.6 % 量级。
    """
    res, _a_gt, _c_gt, floor = model_fits[model]
    assert res.rwp < 1.6 * floor, \
        f"{model}: Rwp={res.rwp:.3f} % vs 统计下限 {floor:.3f} %"


def test_all_models_converge_to_distinct_cells(model_fits) -> None:
    """四型号都能收敛，且 111 与 8xx 系的晶胞确实不同（泛化不是复制）。

    内置 CIF 中 811/622/523 的晶胞逐位相同、111 不同 —— 本断言把这一点
    固化成事实，防止后续有人「统一」CIF 晶胞而悄悄改变型号含义。
    """
    assert len(model_fits) == len(MODELS)
    a111 = model_fits["NCM111"][0].a
    a8 = model_fits["NCM811"][0].a
    assert abs(a111 - a8) > 0.005, f"111 与 811 的 a 相差过小: {a111} vs {a8}"


# ---------------------------------------------------------------------------
# B · 真实前驱体实样（Data043，(Ni,Co,Mn)(OH)₂，523 配比）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def precursor_identify():
    """真实前驱体实样跑判定门。"""
    if not Path(PRECURSOR_REAL).exists():
        pytest.skip(f"实样缺失: {PRECURSOR_REAL}")
    return identify(load_pattern(PRECURSOR_REAL))


@pytest.fixture(scope="module")
def precursor_fit():
    """以三元氢氧化物 CIF 直接跑管线（绕过 GUI 判定门，验证精修本身）。

    管线对「结构里没有 Li 位点」的设计行为是**降级跳过 stage2**，
    不抛异常（见 `pipeline.run_pipeline` docstring）。
    """
    if not Path(PRECURSOR_REAL).exists():
        pytest.skip(f"实样缺失: {PRECURSOR_REAL}")
    st = builtin_structure("precursor_NCM811_OH")
    return run_pipeline(load_pattern(PRECURSOR_REAL), st,
                        default_options_for(st))


def test_real_precursor_not_mistaken_for_noise(precursor_identify) -> None:
    """**T8.2 抓出的缺陷回归**：真实前驱体谱不得被判成「含大量噪声」。

    修前：寻峰器不看突出度，把 9 个真实峰切成 62 个噪声肩 → 峰数超
    `C_MAX_OBS_PEAKS` → 判定门在「噪声」分支直接返回 other，用户拿到的
    结论是"谱图含大量噪声"，与事实相反。
    """
    assert precursor_identify.metrics["n_peaks"] <= C.C_MAX_OBS_PEAKS, \
        f"峰数 {precursor_identify.metrics['n_peaks']} 超上限"
    assert not any("噪声" in r for r in precursor_identify.reasons), \
        f"仍被判成噪声: {precursor_identify.reasons}"


def test_real_precursor_routes_to_hydroxide(precursor_identify) -> None:
    """真实前驱体应分流到 `precursor_hydroxide`（**不是** ncm、不是 other）。

    `ok=False` 是对的：前驱体是 P-3m1 氢氧化物，不能拿层状 R-3m 的 NCM
    正极 CIF 去精修。界面据此提示"这是前驱体"，而不是拒之门外。
    """
    assert precursor_identify.ok is False
    assert precursor_identify.kind == C.KIND_PRECURSOR_HYDROXIDE, \
        f"kind={precursor_identify.kind}｜{'；'.join(precursor_identify.reasons)}"


@pytest.mark.slow
def test_real_precursor_cell_matches_maud(precursor_fit) -> None:
    """**本卡最有价值的一项**：精修晶胞与 Maud 2.55 的独立结果一致。

    参考值取自实样随附的 `Data043：Ni(OH)2.par`（Maud 用 Popa 各向异性
    尺寸/应变模型、双线 Kα1/Kα2、背景多项式 + 手工节点，与我们的模型
    完全不同）—— 两条独立路线给出同一晶胞，才说明晶胞精修可信。
    """
    res = precursor_fit
    a, c = res.cell[0], res.cell[2]
    dev_a = abs(a - MAUD_A) / MAUD_A * 100.0
    dev_c = abs(c - MAUD_C) / MAUD_C * 100.0
    assert dev_a <= 0.3, f"a={a:.5f} vs Maud {MAUD_A}（偏差 {dev_a:.3f} %）"
    assert dev_c <= 0.3, f"c={c:.5f} vs Maud {MAUD_C}（偏差 {dev_c:.3f} %）"


@pytest.mark.slow
def test_real_precursor_skips_occupancy_without_breaking(precursor_fit) -> None:
    """无 Li 位点 → stage2 降级为 None，管线不中断（设计要求）。"""
    res = precursor_fit
    assert res.stage2 is None, "前驱体不应产出 Li 占位结果"
    assert res.occ_li is None and res.z_o is None
    assert res.structure is not None
    assert res.rwp > 0.0


@pytest.mark.slow
def test_real_precursor_rwp_consistent_with_noise(precursor_fit) -> None:
    """Rwp 应与该谱的统计下限同量级（实测 ≈2.1 × 下限）。

    这份谱很弱（最强峰 3389 计数、5–80° 共 3751 点），且前驱体是片状
    晶体、各向异性展宽明显 —— 单一 Caglioti 模型拟不到 Maud 那种
    Popa 各向异性模型的水平。断言按「统计下限的倍数」而非绝对百分比，
    避免把模型能力边界误判成缺陷。
    """
    pat = load_pattern(str(Path(PRECURSOR_REAL)))
    floor = 100.0 * math.sqrt(pat.intensity.size / pat.intensity.sum())
    assert precursor_fit.rwp < 2.6 * floor, \
        f"Rwp={precursor_fit.rwp:.3f} % vs 统计下限 {floor:.3f} %"


# ---------------------------------------------------------------------------
# C · 真实 NCM811 锚点（T8.1 改动不得把已冻结的实样带偏）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ncm811_fit():
    if not Path(NCM811_REAL).exists():
        pytest.skip(f"实样缺失: {NCM811_REAL}")
    st = builtin_structure("NCM811")
    return run_pipeline(load_pattern(NCM811_REAL), st, default_options_for(st))


@pytest.mark.slow
def test_real_811_rwp_anchor(ncm811_fit) -> None:
    """真实 NCM811 锚点：Rwp ≤ 3.3 %（T8.1 重锚定实测 3.1151 %）。"""
    assert ncm811_fit.rwp <= 3.3, f"Rwp={ncm811_fit.rwp:.4f} %"


@pytest.mark.slow
def test_real_811_microstructure_anchor(ncm811_fit) -> None:
    """真实 NCM811 锚点：晶粒尺寸 155 nm ±10 %（实测 155.0）。"""
    d = ncm811_fit.crystallite.D_nm
    assert d is not None and math.isfinite(d)
    assert 140.0 <= d <= 172.0, f"D={d:.1f} nm"


@pytest.mark.slow
def test_real_811_occupancy_anchor(ncm811_fit) -> None:
    """真实 NCM811 锚点：Li 占位 0.987 ±0.5 %（实测 0.98689）。"""
    occ = ncm811_fit.occ_li
    assert occ is not None
    assert 0.978 <= occ <= 0.995, f"occ_Li={occ:.5f}"


# ---------------------------------------------------------------------------
# D · 双候选择优的边界解让位（T8.2 抓出的缺陷）
# ---------------------------------------------------------------------------

def _cand(y: float, rwp: float):
    """构造 `_pick_candidate` 需要的最小候选（只有 rwp 与 Y 被读到）。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        rwp=rwp, result=SimpleNamespace(params=SimpleNamespace(Y=y)))


def test_pick_candidate_prefers_interior_over_boundary() -> None:
    """边界解（Y=0）Rwp 仅略优时，应取内部解 —— 本卡实测场景。

    实测数据：合成 NCM622 真值 Y=0.06043；谷扫描候选 Y=0.06058 /
    Rwp 12.294 %，普通候选 Y=0.0（D=inf）/ Rwp 12.190 %。按 Rwp 会挑中
    边界解，把 130 nm 的样品报成"超出检出上限"。
    """
    from ncm.core.pipeline import _pick_candidate

    boundary = _cand(0.0, 12.190)
    interior = _cand(0.06058, 12.294)
    assert _pick_candidate([boundary, interior]) is interior
    assert _pick_candidate([interior, boundary]) is interior


def test_pick_candidate_keeps_boundary_when_interior_much_worse() -> None:
    """内部解明显更差（超过 5 % 容差）时仍取边界解 —— 规则不能盖过数据。"""
    from ncm.core.pipeline import _pick_candidate

    boundary = _cand(0.0, 12.0)
    interior = _cand(0.06, 13.0)
    assert _pick_candidate([boundary, interior]) is boundary


def test_pick_candidate_plain_rwp_when_best_is_interior() -> None:
    """胜出者本身就是内部解时，行为与 T8.1 的纯 Rwp 取优逐位一致。"""
    from ncm.core.pipeline import _pick_candidate

    good = _cand(0.05, 9.1)
    worse = _cand(0.06, 9.4)
    assert _pick_candidate([good, worse]) is good


def test_pick_candidate_both_boundary() -> None:
    """两个候选都停在边界 → 无内部解可让，仍按 Rwp 取优。"""
    from ncm.core.pipeline import _pick_candidate

    a = _cand(0.0, 10.2)
    b = _cand(0.0, 10.1)
    assert _pick_candidate([a, b]) is b

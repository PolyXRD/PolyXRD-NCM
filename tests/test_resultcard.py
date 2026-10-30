"""结果卡测试（T4.3 验收）。"""
from __future__ import annotations

import numpy as np
import pytest

from ncm.core.crystallite import from_tch
from ncm.core.profile.forward import ProfileParams, compute_phase_profile
from ncm.core.resultcard import build_card, render_text
from ncm.core.solve import builtin_structure, solve


@pytest.fixture(scope="module")
def refined():
    """小窗口合成谱的一次标准精修（快速）。"""
    from ncm.core.dtypes import Pattern

    st = builtin_structure("NCM811")
    prm = ProfileParams(zero=0.0, U=0.02, V=-0.01, W=0.008, eta=0.6, anode="Cu")
    tt = np.arange(15.0, 45.0, 0.02)
    prof = compute_phase_profile(st, tt, prm, 15.0, 45.0)
    y = prof / prof.max() * 8000.0 + 50.0
    rng = np.random.default_rng(20261030)
    y = rng.poisson(y).astype(np.float64)      # 加计数噪声，指标才有意义
    pat = Pattern(two_theta=tt, intensity=y, meta={})
    from ncm.core.solve import SolveOptions

    sr = solve(pat, st, SolveOptions(max_iter=8, refine_asym=False,
                                     refine_bfactor=False))
    return sr, st


def test_card_has_all_required_sections(refined) -> None:
    sr, st = refined
    card = build_card(sr.result, st, {"sample_name": "合成样"})
    for key in ("header", "structure", "cell", "composition",
                "microstructure", "profile", "fit", "correlations",
                "criteria_sources"):
        assert key in card


def test_card_structure_metadata(refined) -> None:
    sr, st = refined
    card = build_card(sr.result, st)
    s = card["structure"]
    assert s["space_group"] == "R -3 m :H"
    assert s["crystal_system_zh"] == "三方"
    assert s["point_group"] == "-3m"
    assert s["laue_group"] == "-3m"
    assert s["bravais_lattice"] == "hR"


def test_card_cell_values(refined) -> None:
    sr, st = refined
    card = build_card(sr.result, st)
    c = card["cell"]
    assert c["a"] > 0 and c["c"] > 0
    assert 4.5 < c["c_over_a"] < 5.5
    assert c["volume"] > 0
    # 与 SolveResult 的精修晶胞一致
    assert abs(c["a"] - sr.a) < 1e-4
    assert abs(c["c"] - sr.c) < 1e-4


def test_card_fit_metrics(refined) -> None:
    sr, st = refined
    card = build_card(sr.result, st)
    f = card["fit"]
    assert f["rwp"] > 0 and f["rexp"] > 0
    assert abs(f["gof"] - f["rwp"] / f["rexp"]) < 1e-3
    assert f["rbragg"] is not None          # solve() 已填充 RB
    assert f["success"] is True


def test_card_optional_context(refined) -> None:
    sr, st = refined
    meta = {
        "sample_name": "NCM811-实测",
        "operator": "赵同新",
        "occ_li": 0.9874,
        "z_o": 0.25828,
        "crystallite": from_tch(0.05, 0.0, 1.54056),
    }
    card = build_card(sr.result, st, meta)
    assert card["header"]["sample"] == "NCM811-实测"
    assert card["header"]["operator"] == "赵同新"
    assert card["composition"]["li_occupancy"] == pytest.approx(0.9874, abs=1e-4)
    assert card["composition"]["o_z"] == pytest.approx(0.25828, abs=1e-5)
    assert card["microstructure"]["crystallite_size_nm"] is not None
    assert card["microstructure"]["method"] == "scherrer"


def test_card_missing_context_is_none(refined) -> None:
    sr, st = refined
    card = build_card(sr.result, st)
    assert card["composition"]["li_occupancy"] is None
    assert card["microstructure"]["crystallite_size_nm"] is None
    assert card["correlations"] is None


def test_card_correlations_present(refined) -> None:
    sr, st = refined
    from ncm.core.solve import SolveOptions

    sr2 = solve(sr.pattern, st, SolveOptions(max_iter=5, refine_asym=False,
                                              refine_bfactor=False),
                refine_corr=True)
    card = build_card(sr2.result, st)
    corr = card["correlations"]
    assert corr is not None
    assert len(corr["labels"]) == len(corr["matrix"])
    assert isinstance(corr["high_pairs"], list)


def test_card_is_json_serializable(refined) -> None:
    import json

    sr, st = refined
    card = build_card(sr.result, st, {"occ_li": 0.98, "z_o": 0.259})
    text = json.dumps(card, ensure_ascii=False)
    assert "crystal_system_zh" in text


def test_render_text_contains_key_numbers(refined) -> None:
    sr, st = refined
    card = build_card(sr.result, st, {"sample_name": "S1", "occ_li": 0.9874})
    txt = render_text(card)
    assert "S1" in txt
    assert "Rwp=" in txt and "RB=" in txt
    assert "三方" in txt
    assert f"{card['fit']['rwp']:.4f}" in txt
    assert "Li 占位" in txt

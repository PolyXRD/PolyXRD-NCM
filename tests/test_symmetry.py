"""空间群元数据测试（T4.2 验收）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from ncm.core.symmetry import (
    _POINT_GROUP_TABLE,
    describe,
    lookup,
    lookup_by_number,
    normalize_hm,
)

CIF_DIR = Path(__file__).resolve().parents[1] / "ncm" / "data" / "cif"


def test_acceptance_r_minus_3m() -> None:
    """任务卡验收口径：R -3 m -> 三方 / -3m / -3m / hR。"""
    info = lookup("R -3 m")
    assert info.crystal_system_zh == "三方"
    assert info.point_group == "-3m"
    assert info.laue_group == "-3m"
    assert info.bravais == "hR"
    assert info.number == 166


@pytest.mark.parametrize("sym", ["R -3 m", "R-3m", "R -3 m :H", "r-3m", "R  -3  m"])
def test_normalization_variants(sym: str) -> None:
    assert lookup(sym).hm == "R-3m"


def test_normalize_hm_strips_setting() -> None:
    assert normalize_hm("R -3 m :H") == "R-3m"
    assert normalize_hm("P 21/c") == "P21/c"


def test_p_minus_3m1() -> None:
    info = lookup("P -3 m 1")
    assert info.number == 164
    assert info.crystal_system_zh == "三方"
    assert info.bravais == "hP"


def test_r_minus_3c() -> None:
    info = lookup("R -3 c")
    assert info.number == 167
    assert info.point_group == "-3m"
    assert info.bravais == "hR"


def test_cubic_and_orthorhombic() -> None:
    assert lookup("Fd-3m").crystal_system_zh == "立方"
    assert lookup("Fd-3m").bravais == "cF"
    assert lookup("Pnma").crystal_system_zh == "正交"
    assert lookup("Pnma").point_group == "mmm"
    assert lookup("Pnma").bravais == "oP"


def test_lookup_by_number() -> None:
    assert lookup_by_number(166).hm == "R-3m"
    assert lookup_by_number(227).hm == "Fd-3m"
    with pytest.raises(KeyError):
        lookup_by_number(999)


def test_unknown_symbol_raises() -> None:
    with pytest.raises(KeyError):
        lookup("完全不是空间群")


def test_derived_fallback() -> None:
    """未登记符号走规则兜底（derived=True），点群/劳厄群仍正确。"""
    info = lookup("P 21/n")           # 表外（只收了 P21/c）
    assert info.derived is True
    assert info.point_group == "2/m"
    assert info.laue_group == "2/m"
    assert info.crystal_system == "monoclinic"


def test_point_group_table_consistency() -> None:
    """32 点群表：每个点群的劳厄类必须与其晶系相符。"""
    laue_by_system = {}
    for pg, (system, laue) in _POINT_GROUP_TABLE.items():
        laue_by_system.setdefault(system, set()).add(laue)
    assert len(_POINT_GROUP_TABLE) == 32
    for system, laues in laue_by_system.items():
        assert len(laues) == 1, f"{system} 对应多个劳厄类: {laues}"


def test_all_builtin_cifs_resolve() -> None:
    """内置 CIF 的空间群必须都能查到元数据。"""
    from ncm.core.profile.cif import parse_cif

    files = sorted(CIF_DIR.glob("*.cif"))
    assert files, "内置 CIF 目录为空"
    for f in files:
        st = parse_cif(f)
        assert st.spacegroup, f"{f.name} 未解析出空间群"
        info = lookup(st.spacegroup)
        assert info.crystal_system_zh
        assert info.point_group and info.laue_group and info.bravais


def test_describe_contains_zh() -> None:
    txt = describe("R -3 m")
    assert "三方" in txt and "-3m" in txt and "hR" in txt

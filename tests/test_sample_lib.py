"""判定门样本库回归测试（T5.2 验收 · pytest 版）。

`tools/bench_identify.py` 是给人看的评测工具；本文件把它的**硬判据**
（正样本召回 100%、负样本误纳 0%）固化成 pytest，用���在 CI 里守住
INV-4「判定门在负样本上 100% 拒绝」。

样本清单：`tests/data/manifest.json`（由 `tools/build_sample_lib.py` 生成）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ncm.core.identify import identify
from ncm.core.patterns import load_pattern

LIB = Path(__file__).resolve().parent / "data"
MANIFEST = LIB / "manifest.json"


def _entries() -> list[dict]:
    if not MANIFEST.exists():
        pytest.skip("样本清单缺失：请先执行 python tools/build_sample_lib.py")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


ENTRIES = _entries()
IDS = [e["file"] for e in ENTRIES]


@pytest.fixture(scope="module")
def results() -> dict:
    """逐样本跑一次判定门（module 级缓存）。"""
    out = {}
    for e in ENTRIES:
        path = LIB / e["file"]
        out[e["file"]] = identify(load_pattern(path))
    return out


def test_sample_library_is_populated() -> None:
    """各类别样本数达标（TASKS.md T5.2：LCO/尖晶石/LFP/岩盐/前驱体 各 ≥2）。"""
    cats: dict[str, int] = {}
    for e in ENTRIES:
        cats[e["category"]] = cats.get(e["category"], 0) + 1
    for cat in ("lco", "spinel", "lfp", "rocksalt", "precursor"):
        assert cats.get(cat, 0) >= 2, f"类别 {cat} 样本不足 2 个: {cats}"
    assert cats.get("ncm", 0) >= 1
    # 正负样本都要有：真实谱与合成谱各至少 1 个
    origins = {e["origin"] for e in ENTRIES}
    assert origins == {"real", "synthetic"}


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_sample_matches_expectation(entry, results) -> None:
    """**硬判据**：ok 必须与期望一致。

    负样本被放行（ok=True）是最严重的错误 —— GUI 会直接进入精修流程。
    """
    res = results[entry["file"]]
    assert bool(res.ok) == bool(entry["expect_ok"]), (
        f"{entry['file']}: ok={res.ok}，期望 {entry['expect_ok']}"
        f"｜{'; '.join(res.reasons)}")


def test_positive_recall_is_100_percent(results) -> None:
    """正样本召回必须 100%（漏检 = 用户被无谓拦下）。"""
    pos = [e for e in ENTRIES if e["expect_ok"]]
    assert pos, "样本库缺少正样本"
    missed = [e["file"] for e in pos
              if not (results[e["file"]].ok
                      and results[e["file"]].kind == e["expect_kind"])]
    assert not missed, f"正样本漏检: {missed}"


def test_negative_false_accept_is_zero(results) -> None:
    """负样本误纳必须为 0（INV-4）。"""
    neg = [e for e in ENTRIES if not e["expect_ok"]]
    assert neg, "样本库缺少负样本"
    admitted = [e["file"] for e in neg if results[e["file"]].ok]
    assert not admitted, f"负样本误纳: {admitted}"


def test_negative_kind_never_ncm_for_non_layered(results) -> None:
    """非层状负样本不得被判成 ncm（层状结构类型必须保留给真正的层状相）。"""
    for e in ENTRIES:
        if e["category"] in ("spinel", "lfp", "rocksalt", "other"):
            assert results[e["file"]].kind != "ncm", (
                f"{e['file']} 被误判为 ncm")


def test_precursor_classification_works(results) -> None:
    """前驱体分流必须有效（用与池内 CIF 同型的合成谱验证）。"""
    for e in ENTRIES:
        if e["category"] != "precursor":
            continue
        if "syn" not in e["file"]:
            continue    # 真实 β-Ni(OH)₂ 与池内 CIF 非同一多型，见 manifest note
        assert results[e["file"]].kind == e["expect_kind"], (
            f"{e['file']}: kind={results[e['file']].kind}")
        assert results[e["file"]].ok is False

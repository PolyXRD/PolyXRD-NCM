"""CLI 导出格式测试（T7.1d）。

判据：CLI 的四种新导出格式（SVG / 逐点 CSV / 结果卡 TXT / HTML 报告）
都能落盘，且内容自洽；CLI 与 GUI 走**同一套**核心层导出代码（配色一致）。

用合成谱（快），不跑真实样。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def sample_txt(tmp_path):
    """一条合成的两列谱图文件（CLI 的输入）。"""
    tt = np.arange(15.0, 45.0, 0.02)
    y = 1000.0 * np.exp(-((tt - 44.5) / 0.15) ** 2) \
        + 600.0 * np.exp(-((tt - 18.8) / 0.2) ** 2) + 50.0
    p = tmp_path / "synth.txt"
    with p.open("w", encoding="utf-8") as fh:
        for t, v in zip(tt, y):
            fh.write(f"{t:.4f} {v:.3f}\n")
    return p


def _run(sample, tmp_path, extra_args) -> int:
    from ncm.cli.ncm import main

    args = ["--sample", str(sample), "--cif", "NCM811",
            "--max-iter", "2", "--quiet"] + extra_args
    return main(args)


def test_cli_svg_export(sample_txt, tmp_path) -> None:
    out = tmp_path / "r.svg"
    assert _run(sample_txt, tmp_path, ["--svg", str(out)]) in (0, 2)
    assert out.exists()
    assert "<svg" in out.read_text(encoding="utf-8")


def test_cli_points_csv_export(sample_txt, tmp_path) -> None:
    out = tmp_path / "p.csv"
    assert _run(sample_txt, tmp_path, ["--points-csv", str(out)]) in (0, 2)
    assert out.exists()
    text = out.read_text(encoding="utf-8-sig")
    assert text.startswith("2theta_deg")
    assert text.count("\n") > 100


def test_cli_card_txt_export(sample_txt, tmp_path) -> None:
    out = tmp_path / "c.txt"
    assert _run(sample_txt, tmp_path, ["--card-txt", str(out)]) in (0, 2)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Rwp" in text
    assert "晶胞" in text


def test_cli_html_export(sample_txt, tmp_path) -> None:
    out = tmp_path / "r.html"
    assert _run(sample_txt, tmp_path, ["--html", str(out)]) in (0, 2)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html, "HTML 报告应内嵌 SVG 图"
    assert "Rwp" in html


def test_cli_existing_outputs_still_work(sample_txt, tmp_path) -> None:
    """★既有的 --out / --card / --png 语义不变（不得破坏）。"""
    out_json = tmp_path / "o.json"
    out_card = tmp_path / "c.json"
    out_png = tmp_path / "o.png"
    assert _run(sample_txt, tmp_path,
                ["--out", str(out_json), "--card", str(out_card),
                 "--png", str(out_png)]) in (0, 2)
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert "rwp" in data
    card = json.loads(out_card.read_text(encoding="utf-8"))
    assert "fit" in card
    assert out_png.exists()


def test_cli_html_uses_palette_colors(sample_txt, tmp_path) -> None:
    """CLI 导出的 HTML 内嵌的 SVG 必须用统一色板。"""
    from ncm.core.palette import PALETTE

    out = tmp_path / "r.html"
    assert _run(sample_txt, tmp_path, ["--html", str(out)]) in (0, 2)
    html = out.read_text(encoding="utf-8").upper()
    assert PALETTE["obs"].upper() in html
    assert PALETTE["diff"].upper() in html

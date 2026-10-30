"""判定门批量评测（T5.2 验收工具）。

读 `tests/data/manifest.json`，逐个样本跑判定门，对比期望结论。

用法
----
```bash
D:/Project/XRD/python310/python.exe tools/bench_identify.py
# 期望：正样本召回 100%，负样本误纳 0
```

**判读口径**
- **硬失败**：`ok` 与期望不符 —— 正样本被拒（漏检）或负样本被放行（误纳）。
  误纳是判定门最严重的错误（GUI 会直接进入精修流程）。
- **软警告**：`kind` 与期望不符但 `ok` 相符 —— 例如含 CaCO₃ 的混合谱被判成
  `precursor_carbonate` 而不是 `other`。结构类型判得更细不是错误，但值得
  记录，便于核对分流措辞。

退出码：存在硬失败返回 1，否则 0。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ncm.core.identify import identify
from ncm.core.patterns import load_pattern

LIB = ROOT / "tests" / "data"
MANIFEST = LIB / "manifest.json"


def _fmt(v, width=8):
    return str(v).ljust(width)


def run(verbose: bool = False) -> int:
    if not MANIFEST.exists():
        print(f"样本清单缺失: {MANIFEST}\n"
              f"请先执行: python tools/build_sample_lib.py")
        return 2
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))

    print(f"判定门批量评测 — 样本 {len(entries)} 个\n")
    print(f"{_fmt('样本', 34)}{_fmt('类别', 11)}{_fmt('ok', 5)}"
          f"{_fmt('kind', 22)}{_fmt('C1 RMS', 10)}{_fmt('判定', 8)}")
    print("-" * 96)

    hard_fail = 0
    soft_warn = 0
    pos_total = pos_hit = 0
    neg_total = neg_fa = 0
    t_start = time.time()

    for e in entries:
        path = LIB / e["file"]
        try:
            pat = load_pattern(path)
            res = identify(pat)
        except Exception as exc:  # noqa: BLE001
            print(f"{_fmt(e['file'], 34)}{_fmt(e['category'], 11)}"
                  f"{'—':5}{'—':22}{'—':10}{'读取/判定失败':8}  {exc}")
            hard_fail += 1
            continue

        m = res.metrics
        c1 = m.get("c1", {})
        rms = c1.get("rms_deg")
        rms_s = f"{rms:.4f}" if isinstance(rms, (int, float)) else "—"

        ok_match = bool(res.ok) == bool(e["expect_ok"])
        kind_match = res.kind == e["expect_kind"]
        if e["expect_ok"]:
            pos_total += 1
            if res.ok and res.kind == e["expect_kind"]:
                pos_hit += 1
            else:
                hard_fail += 1
        else:
            neg_total += 1
            if res.ok:
                neg_fa += 1
                hard_fail += 1
        if not kind_match and ok_match:
            soft_warn += 1

        verdict = "OK" if ok_match and kind_match else (
            "类型差异" if ok_match else "★失败")
        print(f"{_fmt(e['file'], 34)}{_fmt(e['category'], 11)}"
              f"{_fmt(str(res.ok), 5)}{_fmt(res.kind, 22)}"
              f"{_fmt(rms_s, 10)}{_fmt(verdict, 8)}")
        if verbose or not ok_match:
            for r in res.reasons:
                print(f"      · {r}")

    dt = time.time() - t_start
    recall = 100.0 * pos_hit / pos_total if pos_total else 0.0
    fa_rate = 100.0 * neg_fa / neg_total if neg_total else 0.0
    print("-" * 96)
    print(f"正样本召回：{pos_hit}/{pos_total} = {recall:.1f}%   "
          f"（期望 100%）")
    print(f"负样本误纳：{neg_fa}/{neg_total} = {fa_rate:.1f}%   "
          f"（期望 0%）")
    print(f"类型软警告：{soft_warn} 个（ok 相符但 kind 与期望不同）")
    print(f"总耗时 {dt:.1f} s")
    if hard_fail:
        print(f"\n★ 硬失败 {hard_fail} 个 —— 判定门不满足验收条件")
        return 1
    print("\n判定门满足验收条件：正样本召回 100%，负样本误纳 0")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="判定门批量评测")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="打印每个样本的判据理由")
    args = ap.parse_args(argv)
    return run(verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())

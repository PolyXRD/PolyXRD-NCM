"""生成 / 刷新 golden 基线（T1.4）。

golden 是**回归锚点**：任何改动（TCH 峰形、占位精修、RB 实现）都必须让
`tests/test_golden.py` 继续绿，或明确开卡改基线并在 `docs/VALIDATION.md` 记录原因。

用法::

    D:/Project/XRD/python310/python.exe tools/make_golden.py            # 重建
    D:/Project/XRD/python310/python.exe tools/make_golden.py --check    # 只比对
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ncm.core.solve import builtin_structure, load_sample, solve  # noqa: E402

SAMPLE = Path("D:/Project/XRD/XRData/csuHJW/txt/Data040：NCM：811_raw.txt")
GOLDEN = ROOT / "tests" / "golden" / "ncm811_baseline.json"

#: 只冻结**有物理意义且应稳定**的量。像 `iters` 这种依赖数值路径的字段
#: 不进基线 —— 否则每换一次 numpy 小版本就红。
KEYS = ("rwp", "rp", "rexp", "gof", "a", "c", "c_over_a", "volume",
        "zero", "U", "V", "W", "eta", "asym", "bfactor")


def run() -> dict:
    pat = load_sample(SAMPLE)
    sr = solve(pat, builtin_structure("NCM811"))
    d = sr.as_dict()
    return {k: d[k] for k in KEYS}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 golden 基线")
    ap.add_argument("--check", action="store_true", help="只比对，不写")
    args = ap.parse_args(argv)

    if not SAMPLE.exists():
        print(f"实样缺失: {SAMPLE}", file=sys.stderr)
        return 1

    print("跑标准精修…")
    now = run()

    if args.check:
        if not GOLDEN.exists():
            print("基线不存在，先不带 --check 跑一次", file=sys.stderr)
            return 1
        old = json.loads(GOLDEN.read_text(encoding="utf-8"))["metrics"]
        bad = [k for k in KEYS if abs(now[k] - old[k]) > 1e-4 * max(abs(old[k]), 1)]
        for k in KEYS:
            flag = "≠" if k in bad else "="
            print(f"  {k:<10} {old[k]:>12.5f} {flag} {now[k]:>12.5f}")
        print(f"\n{'❌ 漂移: ' + ', '.join(bad) if bad else '✅ 与基线一致'}")
        return 1 if bad else 0

    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps({
        "sample": str(SAMPLE),
        "cif": "NCM811",
        "note": "T1.4 冻结。改动需开新卡并在 docs/VALIDATION.md 记录原因。",
        "metrics": now,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    for k in KEYS:
        print(f"  {k:<10} {now[k]:>12.5f}")
    print(f"\n已写入 {GOLDEN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

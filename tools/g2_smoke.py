"""GSAS-II 可用性冒烟（T0.4，T8.3 修订）。

定位 GSAS-II 自带 Python → 打印版本与三个关键路径（源码根 / 二进制目录 /
解释器）→（可选）用内置 NCM811 结构对真实 811 谱跑一次 Le Bail + Rietveld。

未安装时**不报错退出**：打印 BLOCKED 与安装指引，退出码 0，不阻断 CI。

用法::

    python tools/g2_smoke.py
    python tools/g2_smoke.py --run     # 真跑一次（约 6 秒）

**T8.3 修订的两处**
------------------
1. **必须给子进程 PATH 加 `GSASII-bin\\win_64_p*`**，否则 `add_phase()` 以
   `0xC06D007F` 原生终止（无 traceback）。见 `tools/g2_env.py`。
2. 请求里**必须带一个相**：GSAS-II 没有相就报 "No Phases in GPX file"。
   旧版本这里传的是空 `phases: []`，永远跑不出结果。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import g2_env  # noqa: E402
from g2_crosscheck import run_bridge  # noqa: E402


def load_xy(path: Path) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split()
        if len(p) >= 2:
            try:
                xs.append(float(p[0]))
                ys.append(float(p[1]))
            except ValueError:
                pass
    return xs, ys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GSAS-II 可用性冒烟")
    ap.add_argument("--run", action="store_true", help="真跑一次 Le Bail")
    args = ap.parse_args(argv)

    py = g2_env.find_g2_python()
    if py is None:
        print("BLOCKED: 未找到 GSAS-II 自带 Python。")
        print("  已查路径：POLYXRD_GSAS2_PYTHON / %PROGRAMDATA%\\gsas2main /")
        print("            D:\\GSASII / C:\\GSASII / E:\\GSASII / ~\\GSASII")
        print("  安装方式见 docs/GSAS2_STATUS.md。交叉验证在未安装时自动跳过。")
        return 0

    for line in g2_env.describe(py):
        print(f"  {line}")
    if not args.run:
        print("（未加 --run，跳过 Le Bail）")
        return 0

    if not g2_env.BRIDGE.exists():
        print(f"BLOCKED: 桥脚本缺失 {g2_env.BRIDGE}")
        return 1
    if not g2_env.SAMPLE_NCM811.exists():
        print(f"BLOCKED: 实样缺失 {g2_env.SAMPLE_NCM811}")
        return 1

    xs, ys = load_xy(g2_env.SAMPLE_NCM811)
    print(f"  调用桥脚本（{len(xs)} 点，相 = 内置 NCM811）…")
    out = run_bridge((xs, ys), g2_env.CIF_NCM811)
    if not out.get("ok"):
        print(f"  失败: {out.get('error')}")
        print("  " + str(out.get("stderr_tail", ""))[-800:])
        return 1
    lat = (out.get("phases") or [{}])[0].get("lattice") or {}
    print(f"  晶胞 a={lat.get('a'):.5f} Å  c={lat.get('c'):.5f} Å")
    print(f"  wR(LeBail)={out.get('wR')}  wR(Rietveld)={out.get('wR_rietveld')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

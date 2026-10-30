"""GSAS-II 运行环境的统一入口（T8.3）。

**为什么单独成模块**：`g2_smoke.py`（可用性冒烟）和 `g2_crosscheck.py`（交叉
比对）都要「找到 GSAS-II 的 python → 用正确的环境跑桥脚本」。这层逻辑放过一
次就够了，两处各写一份必然漂移。

三个关键事实（实测得来，别再踩）
--------------------------------
1. **官方发布渠道是 `AdvancedPhotonSource/GSAS-II-buildtools`**，不是
   `AdvancedPhotonSource/GSAS-II`（后者无 release）。安装包
   `gsas2main-Latest-Windows-x86_64.exe` 自带 Python 与全部依赖，
   NSIS 静默安装：`gsas2main.exe /S /D=D:\\GSASII`。
2. **必须把 `GSAS-II\\GSASII-bin\\win_64_p3.13_n2.2` 放进子进程 PATH**。
   否则 `G2Project.add_phase()` 会以 exit `0xC06D007F`（delay-load 找不到
   DLL）**原生终止**，没有 traceback、stderr 全空 —— 看起来像"GSAS-II 装坏了"，
   实际只是 DLL 搜索路径不对。
3. **新版（build 5844）把模块收进了 `GSASII` 包**：`from GSASII import
   GSASIIscriptable`，源码根 `D:\\GSASII\\GSAS-II` 要进 sys.path
   （通过环境变量 `GSASII_ROOT` 传给桥脚本）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: 家族主程序（PolyXRD）的 GSAS-II 桥：JSON 子进程，Le Bail + Rietveld 定量
BRIDGE = Path("D:/Project/XRD/PolyXRD/scripts/gsas2_bridge.py")

#: 内置 NCM811 结构（交叉比对的起始模型）
CIF_NCM811 = Path(__file__).resolve().parents[1] / "ncm" / "data" / "cif" / "NCM811.cif"

#: 真实 NCM811 实样（XRData 里唯一一份 NCM 实测谱）
SAMPLE_NCM811 = Path("D:/Project/XRD/XRData/csuHJW/txt/Data040：NCM：811_raw.txt")


def _candidate_prefixes() -> list[Path]:
    """GSAS-II 安装根目录候选（按主程序同款优先级）。"""
    out: list[Path] = []
    env = os.environ.get("POLYXRD_GSAS2_PYTHON", "").strip()
    if env:
        out.append(Path(env).parent)
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    for prefix in (Path(programdata) / "gsas2main", Path(r"D:\GSASII"),
                   Path(r"C:\GSASII"), Path(r"E:\GSASII"),
                   Path(r"D:\g2main"), Path(r"C:\g2main"), Path(r"E:\g2main"),
                   Path.home() / "GSASII", Path.home() / "g2main"):
        out.append(prefix)
    return out


def find_g2_python() -> Path | None:
    """定位 GSAS-II 自带解释器；未安装返回 None。"""
    env = os.environ.get("POLYXRD_GSAS2_PYTHON", "").strip()
    if env and Path(env).exists():
        return Path(env)
    for prefix in _candidate_prefixes():
        for cand in (prefix / "python.exe", prefix / "bin" / "python.exe"):
            if cand.exists():
                return cand
    return None


def find_g2_source(py: Path) -> Path | None:
    """定位 GSAS-II 源码根（含 `GSASII/` 包的那一层）。"""
    env = os.environ.get("GSASII_ROOT", "").strip()
    if env and (Path(env) / "GSASII").is_dir():
        return Path(env)
    prefix = py.parent
    for cand in (prefix / "GSAS-II", prefix / "GSAS-II" / "GSAS-II",
                 prefix / "gsas2full", prefix):
        if (cand / "GSASII").is_dir():
            return cand
    return None


def find_g2_bin(src: Path | None) -> Path | None:
    """定位 GSAS-II 编译扩展目录（`GSASII-bin\\win_64_p*`）。

    **这就是那个 0xC06D007F 的根因目录**：不在 PATH 上时 delay-load 失败。
    """
    if src is None:
        return None
    base = src / "GSASII-bin"
    if not base.is_dir():
        return None
    cands = sorted(p for p in base.iterdir() if p.is_dir())
    return cands[-1] if cands else None


def g2_env(py: Path | None = None, src: Path | None = None) -> dict[str, str]:
    """构造跑桥脚本用的环境变量（PATH 加 GSAS-II 二进制目录 + GSASII_ROOT）。"""
    py = py or find_g2_python()
    src = src or (find_g2_source(py) if py else None)
    binp = find_g2_bin(src)

    env = dict(os.environ)
    if src is not None:
        env["GSASII_ROOT"] = str(src)
    parts = [str(p) for p in (binp, src, py.parent / "Library" / "bin" if py
                              else None) if p]
    env["PATH"] = ";".join(parts + [env.get("PATH", "")])
    return env


def describe(py: Path | None = None) -> list[str]:
    """一行一条的环境描述（冒烟与比对脚本共用，便于贴进证据）。"""
    py = py or find_g2_python()
    if py is None:
        return ["GSAS-II: 未找到"]
    src = find_g2_source(py)
    binp = find_g2_bin(src)
    lines = [f"python: {py}"]
    lines.append(f"source: {src if src else '(未找到)'}")
    lines.append(f"bin:    {binp if binp else '(未找到 —— 会触发 0xC06D007F)'}")
    try:
        import subprocess

        out = subprocess.run([str(py), "-c",
                              "import sys;print(sys.version.split()[0])"],
                             capture_output=True, text=True, timeout=60)
        lines.append(f"python 版本: {out.stdout.strip() or out.stderr.strip()}")
    except Exception as exc:  # noqa: BLE001 —— 冒烟要报出任何异常
        lines.append(f"python 版本: 调用失败 {type(exc).__name__}: {exc}")
    return lines


if __name__ == "__main__":
    print("\n".join(describe()))
    sys.exit(0 if find_g2_python() else 0)

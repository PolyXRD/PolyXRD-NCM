"""从家族仓库同步 vendor 代码（T1.1 起）。

为什么用脚本而不是手工拷
------------------------
1. **可审计**：`VENDOR_MANIFEST` 逐文件记录来源仓库、源路径、说明；
2. **可复现**：重新同步一条命令，不会漏文件、不会残留旧包名；
3. **可追踪**：保留原版权头，只在包前缀处改写 `rutana.` -> `ncm.`，
   并在文件首行插入 `# vendored from ...` 标记（幂等，不重复插入）。

用法::

    D:/Project/XRD/python310/python.exe tools/vendor_sync.py
    D:/Project/XRD/python310/python.exe tools/vendor_sync.py --check   # 只校验是否一致
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = Path("D:/Project/XRD/PolyXRD-RutAna")
SRC_PKG = "rutana"
DST_PKG = "ncm"

MARK = "# vendored from PolyXRD-RutAna"

#: 源路径(相对 SRC_ROOT) -> 目标路径(相对 ROOT)
VENDOR_MANIFEST: dict[str, str] = {
    # ---- T1.1 读谱与预处理 ----
    "rutana/core/dtypes.py": "ncm/core/dtypes.py",
    "rutana/core/vendor/__init__.py": "ncm/core/vendor/__init__.py",
    "rutana/core/vendor/model.py": "ncm/core/vendor/model.py",
    "rutana/core/vendor/raw_formats.py": "ncm/core/vendor/raw_formats.py",
    "rutana/core/vendor/text_formats.py": "ncm/core/vendor/text_formats.py",
    "rutana/core/patterns.py": "ncm/core/patterns.py",
    "rutana/core/smooth.py": "ncm/core/smooth.py",
    "rutana/core/background.py": "ncm/core/background.py",
    "rutana/core/kalpha2.py": "ncm/core/kalpha2.py",
    # ---- T1.2 CIF / 结构因子 / 前向模型 ----
    "rutana/core/profile/cif.py": "ncm/core/profile/cif.py",
    "rutana/core/profile/shape.py": "ncm/core/profile/shape.py",
    "rutana/core/profile/struct.py": "ncm/core/profile/struct.py",
    "rutana/core/profile/forward.py": "ncm/core/profile/forward.py",
    # ---- T1.3 精修引擎 ----
    "rutana/core/refine/linear.py": "ncm/core/refine/linear.py",
    "rutana/core/refine/lm.py": "ncm/core/refine/lm.py",
    "rutana/core/refine/rfactors.py": "ncm/core/refine/rfactors.py",
    "rutana/core/refine/nonlinear.py": "ncm/core/refine/nonlinear.py",
}


#: 已在本项目内**改动过**的 vendor 文件：默认不覆盖，避免把补丁冲掉。
#: 需要重新取源时加 --force，并**手工重新打补丁**（补丁点见各文件 `# NCM 修改`）。
PATCHED: set[str] = {
    "ncm/core/profile/cif.py",       # T1.2b: _to_float 容忍 esd 括号
    "ncm/core/profile/forward.py",   # T2.1: ProfileParams 加 X/Y + TCH 逐峰分支
    "ncm/core/refine/nonlinear.py",  # T2.1: refine_size/strain 开关 + X/Y 打包解包
}


def rewrite(text: str, src_rel: str) -> str:
    """改包前缀 + 插入来源标记。"""
    out = text.replace(f"{SRC_PKG}.core.", f"{DST_PKG}.core.")
    out = out.replace(f"from {SRC_PKG} import", f"from {DST_PKG} import")
    if not out.startswith(MARK):
        out = f"{MARK} :: {src_rel}\n{out}"
    return out


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同步家族 vendor 代码")
    ap.add_argument("--check", action="store_true", help="只比对，不写")
    ap.add_argument("--force", action="store_true", help="连已打补丁的文件也覆盖")
    args = ap.parse_args(argv)

    if not SRC_ROOT.exists():
        print(f"源仓库不存在: {SRC_ROOT}", file=sys.stderr)
        return 1

    drift = 0
    written = 0
    skipped = 0
    for src_rel, dst_rel in VENDOR_MANIFEST.items():
        src = SRC_ROOT / src_rel
        dst = ROOT / dst_rel
        if not src.exists():
            print(f"[缺失源] {src}", file=sys.stderr)
            return 1
        if dst_rel in PATCHED and dst.exists() and not args.force:
            skipped += 1
            continue
        want = rewrite(src.read_text(encoding="utf-8"), src_rel)
        old = dst.read_text(encoding="utf-8") if dst.exists() else None
        if old == want:
            continue
        if args.check:
            drift += 1
            print(f"[不一致] {dst_rel}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(want, encoding="utf-8")
        written += 1
        print(f"  写入 {dst_rel:<44} {len(want.splitlines()):>5} 行  sha={sha(want)[:12]}")

        # 空 __init__ 需要保留包结构
    for d in ("ncm/core/vendor",):
        init = ROOT / d / "__init__.py"
        if not init.exists() and not args.check:
            init.write_text(f'"""{d} 包。"""\n', encoding="utf-8")

    if args.check:
        print(f"vendor 校验：{drift} 个文件与源不一致" if drift else "vendor 校验：全部一致")
        return 1 if drift else 0

    print(f"\nvendor 完成：本次写入 {written} 个文件（跳过已打补丁 {skipped} 个），"
          f"清单共 {len(VENDOR_MANIFEST)} 个，累计 "
          f"{sum(len((ROOT / p).read_text(encoding='utf-8').splitlines()) for p in VENDOR_MANIFEST.values() if (ROOT / p).exists())} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

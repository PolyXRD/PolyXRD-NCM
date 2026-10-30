"""打印 ``ncm/version.py`` 里的 ``__version__``（供 .bat 读取）。

**为什么不直接在 .bat 里内联 Python 单行**：版本号的正则要用引号，
而 ``"`` 在 cmd.exe 里既要过 ``for /f`` 的括号解析、又要过 Python 字符串
转义 —— 实测 ``\"`` 会被原样传给 Python，raw string 里就变成「反斜杠 +
引号」，正则永远匹配不到。抽成脚本后，.bat 只剩一句重定向，没有任何
引号嵌套。

用法（构建脚本内部）::

    python tools\\read_version.py > "%TEMP%\\ver.txt"
    set /p VER=<"%TEMP%\\ver.txt"

读不到时**输出空串并返回退出码 1**，由调用方决定是否中止 —— 版本号读
不到就打包，产物会带上错误的名字，比直接失败更糟。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_version(path: Path | None = None) -> str:
    """从 `ncm/version.py` 抓 `__version__`；找不到返回空串。"""
    p = path or (ROOT / "ncm" / "version.py")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1).strip() if m else ""


def main() -> int:
    ver = read_version()
    if not ver:
        return 1
    sys.stdout.write(ver)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

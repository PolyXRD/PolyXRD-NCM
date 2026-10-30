# -*- mode: python ; coding: utf-8 -*-
"""PolyXRD-NCM 打包配置（PyInstaller）—— **内部评估版**，单文件 onefile。

**与家族对齐（T8.5）**
--------------------
家族（PolyXRD-LFP / NCA / …）的产物口径是「一个单文件 exe + 一个 Setup」：

| 产物 | 出处 | 命名 |
|---|---|---|
| 内部评估版 | 本 spec | `dist\\PolyXRD-NCM-Internal-vX.Y.Z.exe` |
| 安装注册版 | `scripts\\PolyXRD-NCM-Setup.iss` 打包上面这个 exe | `dist\\PolyXRD-NCM-vX.Y.Z-Setup.exe` |

**为什么本包只有一个 exe**：NCM 目前**没有注册机制**（见下），内部评估版与
注册版是同一个二进制，故不做 `-Internal` / 注册版两份，只出 `-Internal` 一份。
家族里 DoCryst / CrySize 同属这一档。

**注册机制为何不在本包内实现**
------------------------------
家族已有注册流程，本包是同系列成员，注册应**由家族统一实现**；在本包内重复
一套会造成两处状态不一致。当前版本无任何注册提示，安装包中的 exe 与内部评估
版逐字节相同。

**打包态的资源路径（onefile 关键）**
----------------------------------
onefile 下所有内容解到 `sys._MEIPASS`，包目录是 `_MEIPASS/ncm/`：

- `ncm/gui/resources.py::resource_path()` 查 `_MEIPASS/ncm/resources/<name>`；
- `ncm/core/symmetry.py::DATA_PATH` 查 `_MEIPASS/ncm/data/spacegroups.json`；
- 内置 CIF 经 `ncm/data/cif/INDEX.json` 索引，查 `_MEIPASS/ncm/data/cif/`。

**故 `datas` 必须整目录带 `ncm/data`**（含 `spacegroups.json` + `cif/` +
`cif/impurity/` + `INDEX.json`）。历史上只带 `ncm/data/cif*` 而漏掉
`spacegroups.json` —— 打包版能启动、能出谱图，但**晶系/点群/空间群/劳厄群
全部为空**，且冒烟测试查不出来（冒烟只看窗口构造与 CIF 计数）。

**bootloader Splash 与 QSplashScreen 的分工**
--------------------------------------------
onefile 解压阶段（数秒）Qt 还没起来，`QSplashScreen` 无从显示 —— 这段空窗由
PyInstaller 的 bootloader `Splash` 覆盖。主窗口就绪后由
`ncm/gui/__main__.py::_close_boot_splash()` 关闭，随后接 QSplashScreen 的
品牌动画。两者都用同图 `splash-screen.png`，视觉上无缝衔接。
"""
import re
from pathlib import Path

# spec 自身所在目录 (= 仓库根)。PyInstaller 构建时把 SPECPATH 注入 globals。
_SPEC_DIR = globals().get("SPECPATH") or str(Path(__file__).resolve().parent)
_ROOT = Path(_SPEC_DIR)

#: 版本号唯一真源：`ncm/version.py`
_VER = re.search(
    r'__version__\s*=\s*"([^"]+)"',
    (_ROOT / "ncm" / "version.py").read_text(encoding="utf-8"),
).group(1)


def _datas():
    """收集必须随包的非代码资源（onefile：全部内嵌进 exe）。"""
    items = [
        ("ncm/data", "ncm/data"),          # spacegroups.json + cif/ + INDEX.json
        ("ncm/resources", "ncm/resources"),  # logo / 启动图 / 图标
        ("ncm/i18n", "ncm/i18n"),          # 翻译表（模块，双保险）
    ]
    out = []
    for src, dst in items:
        s = _ROOT / src
        if not s.exists():
            continue
        out.append((str(s), dst))
    return out


#: 翻译表是**数据模块**，PyInstaller 静态分析可能漏收 —— 显式 hiddenimports
hiddenimports = [
    "ncm",
    "ncm.version",
    "ncm.gui",
    "ncm.gui.__main__",
    "ncm.gui.resources",
    "ncm.gui.main_window",
    "ncm.gui.canvas",
    "ncm.gui.flow",
    "ncm.gui.workers",
    "ncm.i18n",
    "ncm.i18n.i18n_manager",
    "ncm.i18n.translations.zh_CN",
    "ncm.i18n.translations.en_US",
    "ncm.i18n.translations.ja_JP",
    "ncm.core.pipeline",
    "ncm.core.identify",
    "ncm.core.calibrate",
    "ncm.core.criteria",
    "ncm.core.fingerprint",
    "ncm.core.plotting",
    "ncm.core.export",
    "ncm.core.report_html",
    "ncm.core.palette",
    "ncm.core.symmetry",
]

datas = _datas()

a = Analysis(
    [str(_ROOT / "ncm" / "gui" / "__main__.py")],
    pathex=[str(_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# bootloader 启动画面：图上已烙品牌与版本号，故不附加文本。
splash = Splash(
    str(_ROOT / "ncm" / "resources" / "splash-screen.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    min_font_color="white",
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    # splash.binaries 必须作为独立 TOC 传入（PyInstaller 官方模板要求）：
    # 内含 Tcl/Tk 运行时，缺它启动画面会在 onefile 解压期静默失败。
    splash.binaries,
    [],
    name=f"PolyXRD-NCM-Internal-v{_VER}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(_ROOT / "ncm" / "resources" / "app-icon.ico")],
)

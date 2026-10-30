"""GUI 入口：``python -m ncm.gui``。

启动流程：bootloader 启动图（**仅 onefile 打包态**，覆盖解压的几秒）→
QSplashScreen（`resources/splash-screen.png`，缺失时优雅降级不阻断启动）→
主窗口 → 事件循环。

``--smoke``：只构造主窗口并跑几轮事件循环，**不进入长驻事件循环**，
用于 CI / 冒烟验证（验收命令：`python -m ncm.gui --smoke`）。
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from ncm.gui.resources import app_icon_path, splash_path
from ncm.version import APP_NAME

#: 启动图展示时长（毫秒）
SPLASH_MS = 1200


def _make_app(argv) -> QApplication:
    # 已有实例时复用（QApplication 是进程级单例，重复创建会 RuntimeError；
    # pytest 的 qapp fixture 已建过实例时尤其重要）
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    icon = app_icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))
    return app


def _make_splash(app: QApplication) -> QSplashScreen | None:
    """启动图；资源缺失时返回 None（不阻断启动）。"""
    path = splash_path()
    if not path:
        return None
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None
    splash = QSplashScreen(pixmap)
    splash.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    splash.show()
    app.processEvents()
    return splash


def _close_boot_splash() -> None:
    """关闭 **bootloader** 启动图（onefile 解压期显示的那一张）。

    onefile 打包态下，PyInstaller 的 bootloader 在解压的几秒里显示
    `PolyXRD-NCM.spec` 里 `Splash(...)` 指定的图，此时 Qt 尚未起来 ——
    这段空窗由它覆盖，Qt 的 `QSplashScreen` 接手前必须把它关掉，否则
    两张图会叠在一起。

    非打包态（开发 / pytest / onedir）**没有 `pyi_splash` 模块**，
    故按 ImportError 静默跳过；`close()` 被重复调用也无副作用。
    """
    try:
        import pyi_splash  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        return
    pyi_splash.close()


def _check_resources() -> list[str]:
    """打包态资源完整性检查，返回问题清单（空 = 通过）。

    **为什么冒烟必须查这一项**：onefile 只带 `datas` 里列出的东西。历史上
    `PolyXRD-NCM.spec` 只带 `ncm/data/cif*` 而漏了 `ncm/data/spacegroups.json`
    —— 打包版照样能启动、能出谱图、CIF 计数也正常，但**晶系/点群/空间群/
    劳厄群全部为空**，用户跑到结果卡才发现。所以冒烟要真的查一次空间群表。

    只读不写、只做一次查询，耗时在毫秒级，可以进 CI。
    """
    problems: list[str] = []
    try:
        from ncm.core import symmetry

        if not symmetry.DATA_PATH.exists():
            problems.append(f"缺空间群表 {symmetry.DATA_PATH}")
        else:
            info = symmetry.lookup("R -3m")
            if int(info.number) != 166:
                problems.append(f"空间群表内容异常：R-3m 返回 {info.number}")
    except Exception as exc:  # noqa: BLE001 —— 冒烟要报出任何异常而不是崩掉
        problems.append(f"空间群表不可用：{type(exc).__name__}: {exc}")
    return problems


def run_smoke(app: QApplication) -> int:
    """冒烟：构造主窗口并跑几轮事件循环，确认无异常。"""
    from ncm.gui.main_window import MainWindow

    problems = _check_resources()
    window = MainWindow()
    window.show()
    for _ in range(5):
        app.processEvents()
    assert window.canvas is not None
    assert window.cif_list is not None
    n_cif = window.cif_list.count()
    if problems:
        print(f"[smoke] version={APP_NAME}  cif={n_cif}")
        for p in problems:
            print(f"[smoke] RESOURCE PROBLEM: {p}")
    else:
        print(f"[smoke] OK  version={APP_NAME}  cif={n_cif}"
              f"  resources=spacegroups+R-3m")
    window.close()
    _close_boot_splash()
    return 1 if problems else 0


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    smoke = "--smoke" in argv
    if smoke:
        argv.remove("--smoke")
        # 冒烟必须在无显示器的机器上也能跑 —— 强制 Qt 离屏平台。
        # 必须在 QApplication 创建**之前**设入才生效。
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = _make_app(argv)
    if smoke:
        return run_smoke(app)
    splash = _make_splash(app)
    from ncm.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    # bootloader 图先撤，再让 Qt 启动图接管 —— 顺序反了会闪一下桌面
    _close_boot_splash()
    if splash is not None:
        QTimer.singleShot(SPLASH_MS, splash.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

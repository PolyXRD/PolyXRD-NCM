"""资源路径解析（开发态 / PyInstaller 打包态通用）。

家族工具统一把 logo、启动图、应用图标放在 `resources/` 目录；打包成 onefile
后资源被解到 `sys._MEIPASS`，故两处都要找。**找不到时返回包内路径**，
调用方用 `.exists()` 判断并优雅降级（启动图缺失不应阻断启动）。

**打包态的路径层级（T7.2 修）**
-------------------------------
打包后包目录在 `sys._MEIPASS` 下是 **`ncm/`**（不是资源目录本身），故打包态
要查 `sys._MEIPASS/ncm/resources/<name>`。原先只查 `sys._MEIPASS/<name>`，
在 onefile 下必然找不到资源 —— 开发态正常、打包后启动图/图标静默消失。

**为什么图标优先 PNG**
----------------------
Qt6 的 PNG 解码器**内建在 Qt6Gui 里**，取 PNG 不加载任何 imageformats 插件；
而 `.ico` 必须加载 `qico.dll` 插件 —— 家族实测：打包版启动阶段（窗口
`show()` 之前）多加载一个图片插件会显著提高原生崩溃概率（干净 3/3 vs 崩 0/3）。
`.ico` 仍保留给 exe 资源 / 安装器使用（与 Qt 运行时无关）。
"""
from __future__ import annotations

import sys
from pathlib import Path

#: 资源目录名（打包后位于 `sys._MEIPASS/<pkg>/resources`）
_RES_DIR = "resources"


def resource_path(name: str) -> Path:
    """返回资源文件的绝对路径（不存在时返回包内应有路径）。"""
    base = Path(__file__).resolve().parents[1] / _RES_DIR
    cand = base / name
    if cand.exists():
        return cand
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        # 打包态：包目录在 _MEIPASS 下，资源在 <包名>/resources/
        cand = Path(meipass) / "ncm" / _RES_DIR / name
        if cand.exists():
            return cand
        # 兼容「资源直接铺在 _MEIPASS 根」的构建方式
        cand = Path(meipass) / name
        if cand.exists():
            return cand
    return base / name


def app_icon_path() -> str:
    """运行时窗口图标路径（优先 PNG；找不到返回空串）。"""
    for name in ("app-icon.png", "app-icon.ico"):
        p = resource_path(name)
        if p.exists():
            return str(p)
    return ""


def splash_path() -> str:
    """启动图路径（优先 PNG；找不到返回空串 —— 缺启动图不阻断启动）。"""
    for name in ("splash-screen.png", "splash-screen.jpg"):
        p = resource_path(name)
        if p.exists():
            return str(p)
    return ""


def logo_path() -> str:
    """水平 Logo 路径（找不到返回空串）。"""
    p = resource_path("logo-horizontal.png")
    return str(p) if p.exists() else ""


def crystal_mark_path() -> str:
    """晶体标志路径（找不到返回空串）。"""
    p = resource_path("crystal-mark.png")
    return str(p) if p.exists() else ""

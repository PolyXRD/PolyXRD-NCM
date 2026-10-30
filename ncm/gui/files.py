"""文件选择与读取（T7.1d · 新建，非 vendor）。

从 `MainWindow` 抽出来的文件相关逻辑：

- `choose_pattern()` —— 弹「打开谱图」对话框；
- `choose_cif()`     —— 弹「导入 CIF」对话框；
- `read_pattern()`   —— 读谱（失败时抛异常，由调用方转成用户可读提示）。

**为什么要抽**
--------------
主窗口在 T7.1d 接入导出后又逼近 400 行上限（规则 2），而文件选择是**独立
于流程状态**的一小块胶水逻辑，抽出来还能顺带单测（对话框可 monkeypatch）。

**读谱失败不弹框**
-----------------
本模块只负责「读」，**不负责弹窗** —— 弹窗要带 parent 上下文，交给调用方
（主窗口）决定，避免核心逻辑里藏 UI 副作用。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from ncm.core.patterns import load_pattern
from ncm.i18n import tr


def choose_pattern(parent) -> str | None:
    """弹「打开谱图」对话框；用户取消返回 None。"""
    path, _ = QFileDialog.getOpenFileName(
        parent, tr("dlg.open_pattern"), "", tr("filter.pattern"))
    return path or None


def choose_cif(parent) -> str | None:
    """弹「导入 CIF」对话框；用户取消返回 None。"""
    path, _ = QFileDialog.getOpenFileName(
        parent, tr("dlg.open_cif"), "", tr("filter.cif"))
    return path or None


def read_pattern(path: str):
    """读谱；失败抛异常（调用方转成用户可读提示）。

    返回 `ncm.core.dtypes.Pattern`。
    """
    return load_pattern(path)


def describe_error(path: str, exc: Exception) -> str:
    """把读谱异常转成「文件名: 原因」的用户可读提示。"""
    return f"{Path(path).name}: {exc}"

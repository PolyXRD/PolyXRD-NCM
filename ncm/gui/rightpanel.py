"""右侧栏容器（T7.1d · 新建，非 vendor）。

右栏是**上下两段**：上段 CIF 结构面板（`cif_panel.py`），下段精修结果卡
（`resultcard.py`）。

**为什么要抽**
--------------
这两块是需求原文里「右侧内置 CIF + 精修结果」的直接载体，把它们的装配
从主窗口里拿出来，主窗口就只剩「左画布 | 右栏」这一个布局决定；而且
「右栏是一个容器、CIF 面板与结果卡都是它的子控件」这个结构关系值得有
**一个明确的地方**表达 —— 散在主窗口里容易在改布局时不小心破坏父子关系
（既有测试就断言 `cif_panel.parentWidget() is right`）。

**尺寸策略**
------------
右栏**不参与拉伸**（stretch 因子 0），默认 360 px；结果卡条目多，给它
独立滚动区，避免把 CIF 列表挤出视野。
"""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ncm.gui.cif_panel import CifPanel
from ncm.gui.resultcard import ResultCard

#: 右栏默认宽度（像素）
DEFAULT_WIDTH = 360


def build_right_panel(parent) -> tuple[QWidget, CifPanel, ResultCard]:
    """建右栏容器，返回 ``(container, cif_panel, result_card)``。"""
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    cif_panel = CifPanel(container)
    result_card = ResultCard(container)
    layout.addWidget(cif_panel)
    layout.addWidget(result_card, 1)     # 结果卡吃掉多余高度
    return container, cif_panel, result_card
